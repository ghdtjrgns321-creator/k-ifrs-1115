import io
import sys
# Windows cp949 환경에서 이모지 출력 시 UnicodeEncodeError 방지
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import json
import time
import re
import os
from pymongo import MongoClient
from app.config import settings
from app.embeddings import embed_texts_sync

sys.stdout.reconfigure(encoding="utf-8")

CHILD_COLLECTION  = settings.mongo_collection_name
PARENT_COLLECTION = "k-ifrs-1115-qna-parents"


def split_qna_to_children(qna_id, full_text, metadata):
    """QNA content를 Q/A/S 3단 분할."""
    hierarchy = metadata.get("hierarchy", "")
    children = []

    # Q / A 분리: 05에서 "## 회신"으로 정규화됨
    qa_parts = re.split(r'\n## 회신', full_text, maxsplit=1)

    # Fallback: 정규화가 커버하지 못한 포맷
    if len(qa_parts) == 1:
        split_pattern_qa_fallback = r'\n[ \t]*(?=2\.\s*(?:검토|결론|결정|조사)|(?:##|#|□|ㅇ|▶|-|\[)\s*회\s*신|회\s*신\s*[:\n□ㅇ▶#])'
        qa_parts = re.split(split_pattern_qa_fallback, full_text, maxsplit=1)

    # 질의(Q) 파트
    q_text = qa_parts[0].strip()
    q_page_content = f"[문맥: {hierarchy} > 질의]\n{q_text}"
    q_metadata = {**metadata, "parent_id": qna_id, "chunk_type": "question", "chunk_id": f"{qna_id}_Q"}
    children.append({"text": q_page_content, "metadata": q_metadata})

    # 회신(A) 및 부록(S)
    if len(qa_parts) > 1:
        a_full_text = qa_parts[1].strip()

        split_pattern_supp = r'\n## (?:관련\s*회계\s*기준|참고\s*자료)'
        supp_parts = re.split(split_pattern_supp, a_full_text, maxsplit=1)

        if len(supp_parts) == 1:
            split_pattern_supp_fallback = r'\n(?=#*\s*참고\s*자료|#*\s*검토과정|#*\s*질의에서\s*제시된|관련\s*회계\s*기준)'
            supp_parts = re.split(split_pattern_supp_fallback, a_full_text, maxsplit=1)

        a_core = supp_parts[0].strip()
        a_page_content = f"[문맥: {hierarchy} > 회신/판단근거]\n{a_core}"
        a_metadata = {**metadata, "parent_id": qna_id, "chunk_type": "answer", "chunk_id": f"{qna_id}_A"}
        children.append({"text": a_page_content, "metadata": a_metadata})

        if len(supp_parts) > 1:
            supp_text = supp_parts[1].strip()
            s_page_content = f"[문맥: {hierarchy} > 관련기준/부록]\n{supp_text}"
            s_metadata = {**metadata, "parent_id": qna_id, "chunk_type": "supplementary", "chunk_id": f"{qna_id}_S"}
            children.append({"text": s_page_content, "metadata": s_metadata})

    return children


def load_pdr_to_atlas():
    INPUT_FILE = "data/web/kifrs-1115-qna-chunks.json"

    if not os.path.exists(INPUT_FILE):
        print(f"파일을 찾을 수 없습니다: {INPUT_FILE}")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_qnas = json.load(f)

    client = MongoClient(settings.mongo_uri)
    db = client[settings.mongo_db_name]

    parent_docs_to_insert = []
    child_docs_to_embed = []

    for qna in raw_qnas:
        qna_id = qna["id"]
        full_text = qna["content"]
        metadata = qna["metadata"]

        parent_docs_to_insert.append({
            "_id": qna_id,
            "content": full_text,
            "metadata": metadata
        })

        children = split_qna_to_children(qna_id, full_text, metadata)
        child_docs_to_embed.extend(children)

    # STEP 1. Parent 컬렉션
    parent_coll = db[PARENT_COLLECTION]

    print(f"1. 기존 Parent 컬렉션 데이터를 초기화합니다...")
    p_del_result = parent_coll.delete_many({})
    print(f"-> 기존 Parent 데이터 {p_del_result.deleted_count}개 삭제 완료.")

    print(f"2. 새로운 Parent QnA 원본 {len(parent_docs_to_insert)}개를 저장합니다...")
    parent_coll.insert_many(parent_docs_to_insert)
    print("-> Parent 적재 완료!")

    # STEP 2. Child 컬렉션 (벡터 DB)
    child_coll = db[CHILD_COLLECTION]

    print(f"\n3. 기존 Child 컬렉션에서 QnA 데이터만 삭제합니다 (본문 + 감리사례 보호)...")
    c_del_result = child_coll.delete_many({"parent_id": {"$regex": "^QNA-"}})
    print(f" -> 기존 QnA Child 데이터 {c_del_result.deleted_count}개 삭제 완료.")

    print(f"\n4. 총 {len(child_docs_to_embed)}개의 Child 청크(Q/A/S) 벡터 임베딩을 시작합니다...")

    success_count = 0
    skipped_docs = []

    for i, doc in enumerate(child_docs_to_embed):
        parent_id = doc["metadata"].get('parent_id')
        chunk_type = doc["metadata"].get('chunk_type')
        text_length = len(doc["text"])

        try:
            # 직접 임베딩 + MongoDB 삽입
            vector = embed_texts_sync([doc["text"]], settings.embed_passage_model)[0]
            mongo_doc = {
                "text": doc["text"],
                "embedding": vector,
                **doc["metadata"],
            }
            child_coll.insert_one(mongo_doc)
            success_count += 1
            if success_count % 10 == 0:
                print(f"  -> {success_count} / {len(child_docs_to_embed)} 개 적재 완료")
            time.sleep(0.05)

        except Exception as e:
            print(f"\n[SKIP] {parent_id}의 {chunk_type} 파트 적재 실패 (토큰 초과)")
            skipped_docs.append({
                "parent_id": parent_id,
                "chunk_type": chunk_type,
                "length": text_length
            })
            continue

    # STEP 3. 결과 보고서
    print(f"\n{'='*65}")
    print(f"PDR 아키텍처 질의회신 적재 최종 보고서")
    print(f"{'='*65}")
    print(f"성공: {success_count}개 청크 (Vector DB 안착)")
    print(f"스킵: {len(skipped_docs)}개 청크 (API 용량 초과)")

    if skipped_docs:
        print("\n[스킵된 문서 목록 상세 내역]")
        for skip in skipped_docs:
            print(f"  - ID: {skip['parent_id']} | 타입: {skip['chunk_type']} | 길이: {skip['length']:,.0f}자")
    print(f"{'='*65}")

    client.close()

if __name__ == "__main__":
    load_pdr_to_atlas()

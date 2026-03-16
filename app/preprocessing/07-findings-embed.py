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

# ── 상수 ────────────────────────────────────────────────────────────────────────
INPUT_FILE        = "data/findings/findings-final.json"
CHILD_COLLECTION  = settings.mongo_collection_name
PARENT_COLLECTION = "k-ifrs-1115-findings-parents"
FINDINGS_WEIGHT   = 1.2


def split_finding_to_children(finding_id: str, full_text: str, metadata: dict) -> list[dict]:
    """감리지적사례 content를 Q/A/S 3단 분할."""
    # 서두 변환: "레퍼런스 [ID] 제목..." → "**[ID]** 제목..."
    full_text = re.sub(
        r'^레퍼런스\s*\[([^\]]+)\]\s*([^\n]+)\n(관련\s*회계\s*기준[^\n]*)(?:\n출처:[^\n]*)?\n본문\n?',
        r'**[\1]** \2\n\3\n\n',
        full_text
    )

    hierarchy = metadata.get("hierarchy", "")
    children = []

    qa_parts = re.split(r'\n##\s*회\s*신', full_text, maxsplit=1)

    # Q 파트
    q_text = qa_parts[0].strip()
    children.append({
        "text": f"[문맥: {hierarchy} > 배경 및 질의]\n{q_text}",
        "metadata": {
            **metadata,
            "parent_id": finding_id,
            "chunk_type": "question",
            "chunk_id": f"{finding_id}_Q",
        },
    })

    if len(qa_parts) > 1:
        a_full = qa_parts[1].strip()
        as_parts = re.split(r'\n##\s*참고\s*자료', a_full, maxsplit=1)

        # A 파트
        a_text = as_parts[0].strip()
        children.append({
            "text": f"[문맥: {hierarchy} > 감리지적내용]\n{a_text}",
            "metadata": {
                **metadata,
                "parent_id": finding_id,
                "chunk_type": "answer",
                "chunk_id": f"{finding_id}_A",
            },
        })

        # S 파트
        if len(as_parts) > 1:
            s_text = as_parts[1].strip()
            children.append({
                "text": f"[문맥: {hierarchy} > 참고기준]\n{s_text}",
                "metadata": {
                    **metadata,
                    "parent_id": finding_id,
                    "chunk_type": "supplementary",
                    "chunk_id": f"{finding_id}_S",
                },
            })

    return children


def load_findings_to_atlas():
    if not os.path.exists(INPUT_FILE):
        print(f"파일을 찾을 수 없습니다: {INPUT_FILE}")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_findings = json.load(f)

    client = MongoClient(settings.mongo_uri)
    db = client[settings.mongo_db_name]

    parent_docs = []
    child_docs = []

    for finding in raw_findings:
        finding_id = finding["id"]
        full_text = finding["content"]
        metadata = finding["metadata"]

        metadata_with_weight = {**metadata, "weight_score": FINDINGS_WEIGHT}

        parent_docs.append({
            "_id": finding_id,
            "content": full_text,
            "metadata": metadata_with_weight,
        })

        children = split_finding_to_children(finding_id, full_text, metadata_with_weight)
        child_docs.extend(children)

    # STEP 1. Parent 컬렉션
    parent_coll = db[PARENT_COLLECTION]

    print("1. 기존 Parent 컬렉션을 초기화합니다...")
    p_del = parent_coll.delete_many({})
    print(f" -> {p_del.deleted_count}개 삭제 완료.")

    print(f"2. 감리사례 원본 {len(parent_docs)}개를 저장합니다...")
    parent_coll.insert_many(parent_docs)
    print(" -> Parent 적재 완료!")

    # STEP 2. Child 컬렉션
    child_coll = db[CHILD_COLLECTION]

    print("\n3. 기존 Findings Child 데이터 삭제합니다 (본문 + QNA 보호)...")
    c_del = child_coll.delete_many({"parent_id": {"$regex": "^(FSS-|KICPA-)"}})
    print(f" -> {c_del.deleted_count}개 삭제 완료.")

    # STEP 3. 벡터 임베딩 & 적재
    print(f"\n4. 총 {len(child_docs)}개 Child 청크(Q/A/S) 벡터 임베딩을 시작합니다...")

    success_count = 0
    skipped_docs = []

    for doc in child_docs:
        parent_id = doc["metadata"].get("parent_id")
        chunk_type = doc["metadata"].get("chunk_type")
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
                print(f"  -> {success_count} / {len(child_docs)} 개 적재 완료")
            time.sleep(0.05)

        except Exception as e:
            print(f"\n[SKIP] {parent_id}의 {chunk_type} 파트 적재 실패! ({e})")
            skipped_docs.append({
                "parent_id": parent_id,
                "chunk_type": chunk_type,
                "length": text_length,
            })
            continue

    # STEP 4. 보고서
    print(f"\n{'='*65}")
    print("감리지적사례 PDR 적재 최종 보고서")
    print(f"{'='*65}")
    print(f"성공: {success_count}개 청크 (Vector DB 안착)")
    print(f"스킵: {len(skipped_docs)}개 청크 (API 용량 초과)")

    if skipped_docs:
        print("\n[스킵된 문서 목록]")
        for skip in skipped_docs:
            print(f"  - ID: {skip['parent_id']} | 타입: {skip['chunk_type']} | 길이: {skip['length']:,.0f}자")

    print(f"{'='*65}")
    client.close()


if __name__ == "__main__":
    load_findings_to_atlas()

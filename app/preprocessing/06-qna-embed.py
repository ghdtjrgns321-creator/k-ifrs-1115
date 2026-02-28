import sys
import json
import os
import time
import re
import unicodedata
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
from pymongo import MongoClient
from langchain_upstage import UpstageEmbeddings
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_core.documents import Document

# 환경 변수 로드
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("MONGO_DB_NAME", "kifrs_db")
CHILD_COLLECTION = os.getenv("MONGO_COLLECTION_NAME", "k-ifrs-1115-chatbot")
PARENT_COLLECTION = "kifrs_1115_qna_parents" # 신규 Parent 컬렉션

import re

def split_qna_to_children(qna_id, full_text, metadata):
    
    # 1. 보이지 않는 유니코드 노이즈 제거
    full_text = re.sub(r'[\u200b\u200c\u200d\ufeff\u00a0]', ' ', full_text)
    
    hierarchy = metadata.get("hierarchy", "")
    children = []

    # 2. 강제 분리 전처리 (줄바꿈이 없어도 문맥상 경계를 찾아 \n 주입)
    # [패턴 A] 질문 끝(?)과 회신 시작 사이
    full_text = re.sub(r'(\?|있음|함)\s*(회\s*신\s*[□ㅇ▶#\[])', r'\1\n\2', full_text)
    # [패턴 B] 답변 끝과 관련기준 시작 사이 (가장 안 잘리던 부분)
    full_text = re.sub(r'(\)|함|임|음)\s*(관련\s*회계\s*기준)', r'\1\n\2', full_text)
    # [패턴 C] 본문과 질의 시작 사이
    full_text = re.sub(r'(본문)\s*(질의)', r'\1\n\2', full_text)

    # 3. 분할 실행
    
    # Q와 A 분리
    # Q/A 분리 패턴 설명:
    # \n[ \t]* : 줄바꿈 후 선행 공백/탭 허용 (NBSP→공백 변환으로 생기는 " 회신" 케이스 대응)
    # 1) "2. 결론" / "2. 조사 결과와 결론" 등 숫자 목차로 시작하는 답변 섹션
    # 2) "□ 회신" / "ㅇ 회신" 처럼 기호가 회신 앞에 오는 경우
    # 3) "회신:" / "회신\n" / "회신□" 처럼 회신 뒤에 구두점·기호·줄바꿈이 오는 경우
    split_pattern_qa = r'\n[ \t]*(?=2\.\s*(?:검토|결론|결정|조사)|(?:##|#|□|ㅇ|▶|-|\[)\s*회\s*신|회\s*신\s*[:\n□ㅇ▶#])'
    qa_parts = re.split(split_pattern_qa, full_text, maxsplit=1)

    # 질의(Q) 파트 저장
    q_text = qa_parts[0].strip()
    children.append(Document(
        page_content=f"[문맥: {hierarchy} > 질의]\n{q_text}",
        metadata={**metadata, "parent_id": qna_id, "chunk_type": "question","chunk_id": f"{qna_id}_Q"}
        
    ))

    # 회신(A) 및 부록(S) 처리
    if len(qa_parts) > 1:
        a_full_text = qa_parts[1].strip()
        
        # 부록(관련기준 등) 분리
        split_pattern_supp = r'\n(?=#*\s*참고\s*자료|#*\s*검토과정|#*\s*질의에서\s*제시된|관련\s*회계\s*기준)'
        supp_parts = re.split(split_pattern_supp, a_full_text, maxsplit=1)

        # 회신/판단근거 (Answer)
        a_core = supp_parts[0].strip()
        children.append(Document(
            page_content=f"[문맥: {hierarchy} > 회신/판단근거]\n{a_core}",
            metadata={**metadata, "parent_id": qna_id, "chunk_type": "answer", "chunk_id": f"{qna_id}_A"}
        ))

        # 부록 (Supplementary)
        if len(supp_parts) > 1:
            supp_text = supp_parts[1].strip()
            children.append(Document(
                page_content=f"[문맥: {hierarchy} > 관련기준/부록]\n{supp_text}",
                metadata={**metadata, "parent_id": qna_id, "chunk_type": "supplementary", "chunk_id": f"{qna_id}_S"}
            ))

    return children


def load_pdr_to_atlas():
    INPUT_FILE = "data/web/kifrs-1115-qna-chunks.json" # 경로 확인 필수
    
    if not os.path.exists(INPUT_FILE):
        print(f"❌ 파일을 찾을 수 없습니다: {INPUT_FILE}")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_qnas = json.load(f)

    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    parent_docs_to_insert = []
    child_docs_to_embed = []
    
    # 데이터 파싱 및 3단 분할
    for qna in raw_qnas:
        qna_id = qna["id"]
        full_text = qna["content"]
        metadata = qna["metadata"]
        
        # Parent 저장용
        parent_docs_to_insert.append({
            "_id": qna_id, 
            "content": full_text,
            "metadata": metadata
        })
        
        # Child 분할
        children = split_qna_to_children(qna_id, full_text, metadata)
        child_docs_to_embed.extend(children)

    # ==========================================
    # STEP 1. Parent 컬렉션 처리 (중복 방지)
    # ==========================================
    parent_coll = db[PARENT_COLLECTION]
    
    print(f"🧹 1. 기존 Parent 컬렉션 데이터를 초기화합니다...")
    p_del_result = parent_coll.delete_many({})
    print(f"   -> 기존 Parent 데이터 {p_del_result.deleted_count}개 삭제 완료.")
    
    print(f"📦 2. 새로운 Parent QnA 원본 {len(parent_docs_to_insert)}개를 저장합니다...")
    parent_coll.insert_many(parent_docs_to_insert)
    print("   -> ✅ Parent 적재 완료!")

    # ==========================================
    # STEP 2. Child 컬렉션(벡터 DB) 처리 (본문 보호 + 중복 방지)
    # ==========================================
    child_coll = db[CHILD_COLLECTION]

    print(f"\n🧹 3. 기존 Child 컬렉션에서 'QnA 데이터만 핀셋 삭제' 합니다 (본문 1,297개 보호)...")
    c_del_result = child_coll.delete_many({"parent_id": {"$exists": True}})
    print(f"   -> 기존 QnA Child 데이터 {c_del_result.deleted_count}개 삭제 완료.")

    print(f"\n🚀 4. 총 {len(child_docs_to_embed)}개의 Child 청크(Q/A/S) 벡터 임베딩을 시작합니다...")
    
    embeddings = UpstageEmbeddings(model="solar-embedding-1-large-passage")
    vector_search = MongoDBAtlasVectorSearch(
        collection=child_coll,
        embedding=embeddings,
        index_name="vector_index"
    )

    success_count = 0
    skipped_docs = []

    # API 에러 대비 단건 적재 로직
    for i, doc in enumerate(child_docs_to_embed):
        parent_id = doc.metadata.get('parent_id')
        chunk_type = doc.metadata.get('chunk_type')
        text_length = len(doc.page_content)
        
        try:
            vector_search.add_documents([doc])
            success_count += 1
            if success_count % 10 == 0:
                print(f"  -> {success_count} / {len(child_docs_to_embed)} 개 적재 완료")
            time.sleep(0.05)
            
        except Exception as e:
            print(f"\n❌ [SKIP] {parent_id}의 {chunk_type} 파트 적재 실패! (토큰 초과)")
            skipped_docs.append({
                "parent_id": parent_id,
                "chunk_type": chunk_type,
                "length": text_length
            })
            continue

    # ==========================================
    # STEP 3. 최종 결과 보고서
    # ==========================================
    print(f"\n{'='*65}")
    print(f"🎉 PDR 아키텍처 질의회신 적재 최종 보고서")
    print(f"{'='*65}")
    print(f"✅ 성공: {success_count}개 청크 (Vector DB 안착)")
    print(f"⚠️ 스킵: {len(skipped_docs)}개 청크 (API 용량 초과)")
    
    if skipped_docs:
        print("\n📋 [스킵된 문서 목록 상세 내역]")
        for skip in skipped_docs:
            print(f"  - ID: {skip['parent_id']} | 타입: {skip['chunk_type']} | 길이: {skip['length']:,.0f}자")
    print(f"{'='*65}")
            
    client.close()

if __name__ == "__main__":
    load_pdr_to_atlas()
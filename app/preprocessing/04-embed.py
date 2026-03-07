import json
import time
from pymongo import MongoClient, UpdateOne
from langchain_upstage import UpstageEmbeddings
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_core.documents import Document
from app.config import settings


def load_main_text_to_atlas_safe():
    INPUT_FILE = "data/web/kifrs-1115-chunks.json"

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_chunks = json.load(f)

    # Upstage 임베딩 모델 최대 컨텍스트: 4000 토큰 ≈ 한국어 약 3000자
    # 초과 시 BadRequestError → 앞 3000자만 임베딩 (검색 인덱스용)
    MAX_EMBED_CHARS = 3000

    documents = []
    for chunk in raw_chunks:
        metadata = chunk["metadata"].copy()
        metadata["chunk_id"] = chunk["id"]
        hierarchy_context = metadata.get("hierarchy", "")
        content = chunk["content"]
        contextual_text = f"[문맥: {hierarchy_context}]\n{content}"
        if len(contextual_text) > MAX_EMBED_CHARS:
            contextual_text = contextual_text[:MAX_EMBED_CHARS]
            metadata["truncated"] = True
        documents.append(Document(page_content=contextual_text, metadata=metadata))

    client = MongoClient(settings.mongo_uri)
    collection = client[settings.mongo_db_name][settings.mongo_collection_name]
    embeddings = UpstageEmbeddings(model=settings.embed_passage_model)

    # 1115호 기준서 본문(parent_id 없는 최상위 문서)만 타기팅해서 삭제
    # delete_many({})를 쓰면 QNA 등 다른 stdNum 데이터도 함께 날아가는 위험이 있음

    # [중요] 삭제 전 기존 title 필드 백업
    # 08-generate-titles.py로 생성된 LLM 제목은 JSON에 없으므로 재삽입 시 유실됨
    existing_titles = {
        doc["chunk_id"]: doc["title"]
        for doc in collection.find(
            {
                "stdNum": "1115",
                "parent_id": {"$exists": False},
                "title": {"$exists": True, "$ne": ""},
            },
            {"chunk_id": 1, "title": 1, "_id": 0},
        )
        if "chunk_id" in doc and "title" in doc
    }
    print(f"기존 LLM 제목 백업: {len(existing_titles)}개")

    print("기존 데이터 삭제 중 (기준서 본문 1115호만 타기팅)...")
    collection.delete_many(
        {
            "stdNum": "1115",
            "parent_id": {"$exists": False},
        }
    )
    print("기준서 본문(1115호) 기존 데이터 삭제 완료.")

    vector_search = MongoDBAtlasVectorSearch(
        collection=collection, embedding=embeddings, index_name="vector_index"
    )

    print("단건(1개씩) 단위 안전 적재 시작...")

    success_count = 0
    error_chunks = []

    # 1개씩 보내면서 에러가 나도 멈추지 않고 다음으로 넘어감감
    for i, doc in enumerate(documents):
        try:
            vector_search.add_documents([doc])
            success_count += 1

            # 50개 단위로 진행 상황 출력
            if success_count % 50 == 0:
                print(f"  -> {success_count} / {len(documents)} 개 적재 완료")

            time.sleep(0.05)

        except Exception as e:
            chunk_id = doc.metadata.get("chunk_id", f"unknown_{i}")
            # 이모지 제거: Windows cp949 환경에서 UnicodeEncodeError 방지
            print(
                f"\n[SKIP] {i}번째 청크 (ID: {chunk_id}) 적재 실패: {type(e).__name__}"
            )
            error_chunks.append(chunk_id)
            continue

    print(f"\n적재 완료! 총 {success_count}개의 데이터가 클라우드에 올라갔습니다.")
    if error_chunks:
        print(f"[실패 청크 목록] ({len(error_chunks)}개): {error_chunks}")

    # [중요] 백업해둔 LLM 제목 복원
    # 새로 삽입된 문서에 기존 title을 다시 씀 (08-generate-titles 재실행 불필요)
    if existing_titles:
        print(f"\nLLM 제목 복원 중... ({len(existing_titles)}개)")
        ops = [
            UpdateOne({"chunk_id": k}, {"$set": {"title": v}})
            for k, v in existing_titles.items()
        ]
        result = collection.bulk_write(ops, ordered=False)
        print(f"LLM 제목 복원 완료: {result.modified_count}개")

    client.close()


if __name__ == "__main__":
    load_main_text_to_atlas_safe()

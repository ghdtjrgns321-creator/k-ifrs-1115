import json
import time
from pymongo import MongoClient, UpdateOne
from app.config import settings
from app.embeddings import embed_texts_sync


def load_main_text_to_atlas_safe():
    INPUT_FILE = "data/web/kifrs-1115-chunks.json"

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_chunks = json.load(f)

    # Upstage 임베딩 최대 4000 토큰 ≈ 한국어 약 3000자
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
        documents.append({"text": contextual_text, "metadata": metadata})

    client = MongoClient(settings.mongo_uri)
    collection = client[settings.mongo_db_name][settings.mongo_collection_name]

    # 기존 title 필드 백업 (08-generate-titles.py로 생성된 LLM 제목 보존)
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

    print("단건(1개씩) 단위 안전 적재 시작...")

    success_count = 0
    error_chunks = []

    for i, doc in enumerate(documents):
        try:
            # 직접 임베딩 + MongoDB 삽입 (langchain-mongodb 대체)
            vector = embed_texts_sync([doc["text"]], settings.embed_passage_model)[0]
            mongo_doc = {
                "text": doc["text"],
                "embedding": vector,
                **doc["metadata"],
            }
            collection.insert_one(mongo_doc)
            success_count += 1

            if success_count % 50 == 0:
                print(f"  -> {success_count} / {len(documents)} 개 적재 완료")

            time.sleep(0.05)

        except Exception as e:
            chunk_id = doc["metadata"].get("chunk_id", f"unknown_{i}")
            print(
                f"\n[SKIP] {i}번째 청크 (ID: {chunk_id}) 적재 실패: {type(e).__name__}"
            )
            error_chunks.append(chunk_id)
            continue

    print(f"\n적재 완료! 총 {success_count}개의 데이터가 클라우드에 올라갔습니다.")
    if error_chunks:
        print(f"[실패 청크 목록] ({len(error_chunks)}개): {error_chunks}")

    # 백업해둔 LLM 제목 복원
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

import json
import time
from pymongo import MongoClient
from langchain_upstage import UpstageEmbeddings
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_core.documents import Document
from app.config import settings

def load_main_text_to_atlas_safe():
    INPUT_FILE = "data/web/kifrs-1115-chunks.json"

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_chunks = json.load(f)

    documents = []
    for chunk in raw_chunks:
        metadata = chunk["metadata"].copy()
        metadata["chunk_id"] = chunk["id"]
        hierarchy_context = metadata.get("hierarchy", "")
        contextual_text = f"[문맥: {hierarchy_context}]\n{chunk['content']}"
        documents.append(Document(page_content=contextual_text, metadata=metadata))

    client = MongoClient(settings.mongo_uri)
    collection = client[settings.mongo_db_name][settings.mongo_collection_name]
    embeddings = UpstageEmbeddings(model=settings.embed_passage_model)

    # 기존 데이터 깔끔하게 다시 초기화
    print(f"기존 데이터 삭제 중...")
    collection.delete_many({})

    vector_search = MongoDBAtlasVectorSearch(
        collection=collection,
        embedding=embeddings,
        index_name="vector_index"
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
            chunk_id = doc.metadata.get('chunk_id', f'unknown_{i}')
            print(f"\n❌ [SKIP] {i}번째 청크 (ID: {chunk_id}) 적재 실패: 토큰 초과 의심")
            error_chunks.append(chunk_id)
            continue

    print(f"\n적재 완료! 총 {success_count}개의 데이터가 클라우드에 올라갔습니다.")
    if error_chunks:
        print(f"⚠️실패한 청크 ID 목록 ({len(error_chunks)}개): {error_chunks}")
        
    client.close()

if __name__ == "__main__":
    load_main_text_to_atlas_safe()
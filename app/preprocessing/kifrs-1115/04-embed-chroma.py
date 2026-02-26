import json
import os
import chromadb
from dotenv import load_dotenv
from langchain_upstage import UpstageEmbeddings
from langchain_core.documents import Document
from langchain_chroma import Chroma

load_dotenv()

def load_into_chroma():
    INPUT_FILE = "data/web/kifrs_1115_chunks.json"
    
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_chunks = json.load(f)

    # ==========================================
    # 1. LangChain Document 객체로 변환
    # ==========================================
    documents = []
    ids = []
    
    for chunk in raw_chunks:
        metadata = chunk["metadata"]
        metadata["chunk_id"] = chunk["id"] 
        # 🌟 핵심: Contextual Chunking 적용
        # 임베딩 모델이 문맥을 이해할 수 있도록 계층 경로를 텍스트 맨 앞에 박아줍니다.
        hierarchy_context = metadata.get("hierarchy", "")
        contextual_text = f"[문맥: {hierarchy_context}]\n{chunk['content']}"
        
        doc = Document(
            page_content=contextual_text, # 원본 content 대신 문맥이 결합된 텍스트를 넣습니다.
            metadata=metadata
        )
        documents.append(doc)
        ids.append(chunk["id"])

    print(f"✅ 총 {len(documents)}개의 문서를 준비했습니다.")

    # ==========================================
    # 2. Upstage 임베딩 및 ChromaDB 클라이언트 설정
    # ==========================================
    # 적재할 때는 반드시 'passage' 모델을 사용합니다.
    embeddings = UpstageEmbeddings(model="solar-embedding-1-large-passage")

    # 설정한 Docker의 8100 포트로 연결
    chroma_client = chromadb.HttpClient(host="localhost", port=8100)
    
    # LangChain 래퍼를 통해 Chroma 컬렉션 생성 (기존에 있으면 불러옴)
    vector_db = Chroma(
        client=chroma_client,
        collection_name="kifrs_1115",
        embedding_function=embeddings,
    )

    # ==========================================
    # 3. 배치(Batch) 단위 적재 (API 과부하 방지)
    # ==========================================
    BATCH_SIZE = 100
    print("🚀 ChromaDB에 임베딩 및 적재를 시작합니다... (API 통신으로 시간이 다소 소요됩니다)")
    
    for i in range(0, len(documents), BATCH_SIZE):
        batch_docs = documents[i : i + BATCH_SIZE]
        batch_ids = ids[i : i + BATCH_SIZE]
        
        # ChromaDB에 문서와 ID 밀어넣기
        vector_db.add_documents(documents=batch_docs, ids=batch_ids)
        print(f"  -> {min(i + BATCH_SIZE, len(documents))} / {len(documents)} 청크 적재 완료")

    print("\n🎉 모든 K-IFRS 데이터가 ChromaDB에 성공적으로 적재되었습니다!")
    
    # ==========================================
    # 4. 즉석 검색 테스트 (가중치 메타데이터 확인용)
    # ==========================================
    print("\n✨ [DB 적재 후 즉석 검색 테스트]")
    
    # 검색할 때는 내부적으로 'query' 모델이 자동으로 사용됩니다.
    query = "변동대가와 환불부채를 어떻게 측정해야 해?"
    results = vector_db.similarity_search(query, k=2)
    
    for idx, res in enumerate(results):
        print(f"\n[Top {idx+1}] ID: {res.metadata.get('chunk_id')}")
        print(f"▶ 카테고리: {res.metadata.get('category')} (가중치: {res.metadata.get('weight_score')})")
        print(f"▶ 계층경로: {res.metadata.get('hierarchy')}")
        print(f"▶ 본문내용: {res.page_content[:100]}...")

if __name__ == "__main__":
    load_into_chroma()
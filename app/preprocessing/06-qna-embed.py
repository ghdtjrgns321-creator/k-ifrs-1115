import json
import os
import chromadb
from dotenv import load_dotenv
from langchain_upstage import UpstageEmbeddings
from langchain_core.documents import Document
from langchain_chroma import Chroma

load_dotenv()

def append_qna_into_chroma():
    # 타겟 파일을 방금 수집한 '질의회신' 파일로 지정
    INPUT_FILE = "data/web/kifrs-1115-qna-chunks.json"
    
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_chunks = json.load(f)

    # ==========================================
    # 1. LangChain Document 객체로 변환 (Contextual Chunking 유지)
    # ==========================================
    documents = []
    ids = []
    
    for chunk in raw_chunks:
        metadata = chunk["metadata"]
        metadata["chunk_id"] = chunk["id"] 
        
        # 🌟 핵심: 문맥(Hierarchy)을 텍스트 맨 앞에 박아주는 Contextual Chunking 그대로 적용
        hierarchy_context = metadata.get("hierarchy", "")
        contextual_text = f"[문맥: {hierarchy_context}]\n{chunk['content']}"
        
        doc = Document(
            page_content=contextual_text, 
            metadata=metadata
        )
        documents.append(doc)
        ids.append(chunk["id"])

    print(f"✅ 총 {len(documents)}개의 질의회신 문서를 준비했습니다.")

    # ==========================================
    # 2. Upstage 임베딩 및 ChromaDB 클라이언트 설정
    # ==========================================
    embeddings = UpstageEmbeddings(model="solar-embedding-1-large-passage")
    chroma_client = chromadb.HttpClient(host="localhost", port=8100)
    
    # 🌟 기존에 만들어둔 "kifrs_1115" 컬렉션을 그대로 불러옵니다.
    vector_db = Chroma(
        client=chroma_client,
        collection_name="kifrs_1115",
        embedding_function=embeddings,
    )

    # ==========================================
    # 3. 배치(Batch) 단위 적재 (기존 DB에 안전하게 추가됨)
    # ==========================================
    BATCH_SIZE = 50 # 질의회신은 본문이 길 수 있으니 배치를 조금 줄여서 안정적으로 밀어넣습니다.
    print("🚀 기존 ChromaDB 컬렉션에 질의회신 추가 적재를 시작합니다...")
    
    for i in range(0, len(documents), BATCH_SIZE):
        batch_docs = documents[i : i + BATCH_SIZE]
        batch_ids = ids[i : i + BATCH_SIZE]
        
        # add_documents는 ID가 겹치지 않으면 기존 데이터 뒤에 예쁘게 추가해 줍니다.
        vector_db.add_documents(documents=batch_docs, ids=batch_ids)
        print(f"  -> {min(i + BATCH_SIZE, len(documents))} / {len(documents)} 청크 적재 완료")

    print("\n🎉 질의회신 데이터가 기존 K-IFRS 1115호 DB에 완벽하게 융합되었습니다!")

if __name__ == "__main__":
    append_qna_into_chroma()
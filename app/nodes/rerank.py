# app/nodes/rerank.py
from app.state import RAGState
from app.reranker import rerank_results  # (작성해두신 reranker.py 경로에 맞게 import)

def rerank_docs(state: RAGState):
    """1차 검색된 문서들을 Upstage Reranker와 비즈니스 룰로 재정렬합니다."""
    
    query = state["standalone_query"]
    retrieved_docs = state.get("retrieved_docs", [])
    
    # Reranker를 통과하며 5개로 압축되고 비즈니스 룰(임계값, 페널티)이 적용됩니다.
    reranked = rerank_results(query, retrieved_docs, top_n=5)
    
    return {"reranked_docs": reranked}
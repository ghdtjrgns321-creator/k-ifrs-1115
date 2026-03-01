# app/nodes/retrieve.py
from app.state import RAGState
from app.retriever import search_all


def retrieve_docs(state: RAGState):
    """사용자의 독립형 질문으로 Vector + BM25 하이브리드 검색을 수행합니다."""

    # Reranker가 충분히 고를 수 있도록 20개를 넉넉하게 가져옵니다.
    docs = search_all(state["standalone_query"], limit=20)

    return {"retrieved_docs": docs}

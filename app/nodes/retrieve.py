from app.state import RAGState
from app.retriever import search_all


def retrieve_docs(state: RAGState):
    """사용자의 독립형 질문으로 Vector + BM25 하이브리드 검색을 수행.

    is_situation=True인 경우, 긴 자연어 대신 K-IFRS 핵심 키워드(search_keywords)로
    검색하여 retrieval 품질을 높입니다.
    """
    keywords = state.get("search_keywords", [])
    if keywords:
        # 키워드를 공백으로 연결 → 짧고 명확한 검색 쿼리 (긴 자연어보다 효과적)
        search_query = " ".join(keywords)
    else:
        search_query = state["standalone_query"]

    # Reranker가 충분히 고를 수 있도록 20개를 넉넉하게 가져옴.
    docs = search_all(search_query, limit=20)

    return {"retrieved_docs": docs}

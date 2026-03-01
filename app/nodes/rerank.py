# app/nodes/rerank.py
from app.state import RAGState
from app.reranker import rerank_results


def rerank_docs(state: RAGState):
    """1차 검색된 문서들을 Upstage Reranker와 비즈니스 룰로 재정렬합니다."""

    query = state["standalone_query"]
    retrieved_docs = state.get("retrieved_docs", [])

    try:
        # Reranker를 통과하며 5개로 압축되고 비즈니스 룰(임계값, 페널티)이 적용됩니다.
        reranked = rerank_results(query, retrieved_docs, top_n=5)
    except Exception as e:
        # Reranker API 장애(404, 타임아웃 등) 시 파이프라인이 중단되지 않도록 폴백
        # 검색 score 기준 상위 5개를 그대로 사용합니다.
        print(f"  ⚠️  Reranker 실패 ({type(e).__name__}), 검색 score 순위로 대체", flush=True)
        reranked = sorted(retrieved_docs, key=lambda d: d.get("score", 0), reverse=True)[:5]

    return {"reranked_docs": reranked}

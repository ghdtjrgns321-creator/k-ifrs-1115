# app/nodes/rerank.py
# Cohere Reranker + 비즈니스 룰 재정렬
import asyncio

from app.reranker import rerank_results


async def rerank_docs(state: dict) -> dict:
    """1차 검색된 문서들을 Cohere Reranker와 비즈니스 룰로 재정렬."""

    query = state["standalone_query"]
    retrieved_docs = state.get("retrieved_docs", [])

    try:
        # rerank_results는 동기 함수 (Cohere API) → 스레드에서 실행
        # top_n=15: generate는 상위 3개만 사용하지만, evidence 패널에
        # 본문/적용사례/QNA/감리사례 등 다양한 카테고리 문서를 표시하기 위해 넉넉히 반환
        reranked = await asyncio.to_thread(rerank_results, query, retrieved_docs, 15)
    except Exception as e:
        # Reranker API 장애 시 검색 score 순위로 대체
        print(f"  ⚠️  Reranker 실패 ({type(e).__name__}), 검색 score 순위로 대체", flush=True)
        reranked = sorted(retrieved_docs, key=lambda d: d.get("score", 0), reverse=True)[:15]

    return {"reranked_docs": reranked}

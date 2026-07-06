# app/nodes/rerank.py
# Cohere Reranker + 비즈니스 룰 재정렬
#
# pinpoint(큐레이션) 문서는 reranker bypass — decision_tree에서 직접 큐레이션한
# 데이터이므로 Cohere의 query-document 유사도 판단에 맡기지 않음.
# IE 적용사례는 generate에서 desc로 대체되므로 수량 제한 불필요.
import asyncio
import logging

from app.reranker import rerank_results

logger = logging.getLogger(__name__)

# reranker 최종 반환 수 (pinpoint 제외)
RERANK_TOP_N = 15


async def rerank_docs(state: dict) -> dict:
    """1차 검색된 문서들을 Cohere Reranker와 비즈니스 룰로 재정렬.

    pinpoint 문서는 reranker bypass:
    Why: 큐레이션 데이터(precedents/red_flags)가 Cohere의 텍스트 유사도 채점에서
    0.05 미만으로 탈락하는 문제 해결. T3 테스트에서 105건 중 103건 탈락 확인됨.

    수량 제한 없음:
    Why: IE 적용사례는 generate에서 topics.json desc로 대체 (원문 LLM 미전달),
    QNA/감리사례는 수량이 적어 토큰 폭발 위험 없음.
    전체 pinpoint은 UX3 왼쪽 패널에 표시되므로 자르면 안 됨.
    """
    query = state["standalone_query"]
    retrieved_docs = state.get("retrieved_docs", [])

    # pinpoint 분리 — reranker bypass 대상
    pinpoint = [d for d in retrieved_docs if d.get("chunk_type") == "pinpoint"]
    non_pinpoint = [d for d in retrieved_docs if d.get("chunk_type") != "pinpoint"]

    try:
        # non-pinpoint만 reranker 채점
        reranked = await asyncio.to_thread(
            rerank_results,
            query,
            non_pinpoint,
            RERANK_TOP_N,
        )
    except Exception as e:
        logger.warning("Reranker 실패 (%s), 검색 score 순위로 대체", type(e).__name__)
        reranked = sorted(non_pinpoint, key=lambda d: d.get("score", 0), reverse=True)[
            :RERANK_TOP_N
        ]

    # pinpoint 1순위 배치 + reranked 2순위
    combined = pinpoint + reranked
    logger.info(
        "pinpoint_bypass=%d, reranked=%d, total=%d",
        len(pinpoint),
        len(reranked),
        len(combined),
    )

    return {"reranked_docs": combined}

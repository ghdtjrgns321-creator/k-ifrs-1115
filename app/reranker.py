import logging

import cohere
from app.config import settings

logger = logging.getLogger(__name__)

# Reranker 점수가 이 값 미만이면 쿼리와 무관한 문서로 간주하고 제거
# 0.1 → 0.05: 조금이라도 관련 있으면 전부 통과시켜 전수 반환 지원
RERANK_THRESHOLD = 0.05

# 한국어 문서에 최적화된 Cohere 다국어 Reranker 모델
COHERE_RERANK_MODEL = "rerank-multilingual-v3.0"

# 카테고리별 관련성 가중치 — Cohere rerank_score에 곱하여 최종 점수 산출
# Why: 모든 소스를 동일 가중치로 두면 결론도출근거/Q파트가 실무 답변보다 높은 순위를 차지
WEIGHT_BC = 0.85  # 결론도출근거: 제정 의도 파악용, 직접 실무 답변에 덜 적합
WEIGHT_IE = 0.95  # 적용사례: 본문보다 참고 비중 낮지만 BC보다 높음
WEIGHT_QUESTION = 0.80  # QNA/감리 Q파트: 질문 텍스트라 검색 잘 걸리지만 답변 가치 낮음
WEIGHT_SUPPLEMENTARY = 0.95  # QNA/감리 부록: 참고 수준

# Cohere 클라이언트 싱글턴 — HTTP 커넥션 풀 재사용
# Why: 매 요청마다 ClientV2를 생성하면 커넥션 초기화 비용이 누적됨
_cohere_client: cohere.ClientV2 | None = None


def _get_cohere_client() -> cohere.ClientV2:
    global _cohere_client
    if _cohere_client is None:
        _cohere_client = cohere.ClientV2(api_key=settings.cohere_api_key)
    return _cohere_client


def rerank_results(
    query: str, unified_results: list[dict], top_n: int = 5
) -> list[dict]:
    """Cohere Reranker를 호출하고, 실무 비즈니스 룰(페널티)을 적용하여 최종 정렬합니다."""

    if not unified_results:
        return []

    # 1. Cohere Reranker API 호출
    co = _get_cohere_client()

    # Reranker에는 자식 청크의 내용(content)만 보냅니다.
    documents = [doc["content"] for doc in unified_results]

    response = co.rerank(
        model=COHERE_RERANK_MODEL,
        query=query,
        documents=documents,
        top_n=len(unified_results),
        request_options={"timeout_in_seconds": settings.reranker_timeout},
    )

    # API 결과를 기존 딕셔너리에 매핑
    for item in response.results:
        unified_results[item.index]["rerank_score"] = item.relevance_score

    # 진단 로그: pinpoint 문서의 rerank_score 확인
    pinpoint_cids = {
        d["chunk_id"] for d in unified_results if d.get("chunk_type") == "pinpoint"
    }
    if pinpoint_cids:
        logger.info("pinpoint 문서 %d건 rerank 채점 결과:", len(pinpoint_cids))
        for doc in unified_results:
            if doc["chunk_id"] in pinpoint_cids:
                logger.debug(
                    "  %s -> rerank_score=%.4f | %s",
                    doc["chunk_id"],
                    doc.get("rerank_score", 0),
                    doc["source"],
                )

    # 2. 맞춤형 비즈니스 룰 적용 (하이브리드 스코어링)
    for doc in unified_results:
        base_score = doc.get("rerank_score", 0.0)

        # [룰 4] 임계값 필터: Reranker가 "무관"으로 판단한 문서는 가중치와 무관하게 제거
        # 낮은 base_score에 multiplier를 곱해봤자 의미 없는 문서가 순위에 끼는 것을 방지합니다.
        if base_score < RERANK_THRESHOLD:
            doc["final_score"] = 0.0
            continue

        multiplier = 1.0

        # [룰 1] 카테고리 선호도: 본문 > 적용지침B > 적용사례IE > 결론도출근거
        # 결론도출근거는 기준서 제정 의도 파악용으로 직접 실무 답변에는 덜 적합합니다.
        cat = doc.get("category", "")
        if "결론도출근거" in cat:
            multiplier *= WEIGHT_BC
        elif "적용사례" in cat:
            multiplier *= WEIGHT_IE

        # [룰 2] QNA/감리사례 chunk_type 선호도: A(회신/감리지적) > S(부록) > Q(질의)
        # Q 파트는 사용자 질문과 의미가 유사해 검색에 잘 걸리지만, 실제 답변이 아님
        chunk_type = doc.get("chunk_type", "")
        if chunk_type == "question":
            multiplier *= WEIGHT_QUESTION
        elif chunk_type == "supplementary":
            multiplier *= WEIGHT_SUPPLEMENTARY

        doc["final_score"] = base_score * multiplier

    # 진단 로그: pinpoint 문서 탈락 여부
    if pinpoint_cids:
        dropped = [
            d
            for d in unified_results
            if d["chunk_id"] in pinpoint_cids and d.get("final_score", 0) == 0
        ]
        survived = [
            d
            for d in unified_results
            if d["chunk_id"] in pinpoint_cids and d.get("final_score", 0) > 0
        ]
        if dropped:
            logger.warning("PINPOINT 탈락 %d건:", len(dropped))
            for d in dropped:
                logger.warning(
                    "  DROPPED: %s (rerank=%.4f)",
                    d["chunk_id"],
                    d.get("rerank_score", 0),
                )
        if survived:
            logger.info("PINPOINT 생존 %d건:", len(survived))
            for d in survived:
                logger.debug(
                    "  SURVIVED: %s (final=%.4f)",
                    d["chunk_id"],
                    d.get("final_score", 0),
                )

    # 3. threshold 미달 문서 제거 후 최종 점수 기준으로 내림차순 정렬
    above_threshold = [d for d in unified_results if d.get("final_score", 0) > 0]
    above_threshold.sort(key=lambda x: x["final_score"], reverse=True)

    return above_threshold[:top_n]

import cohere
from app.config import settings

# Reranker 점수가 이 값 미만이면 쿼리와 무관한 문서로 간주하고 제거합니다.
# 가중치 보정으로 저품질 문서가 살아나는 것을 방지하는 안전망입니다.
RERANK_THRESHOLD = 0.1

# 한국어 문서에 최적화된 Cohere 다국어 Reranker 모델
COHERE_RERANK_MODEL = "rerank-multilingual-v3.0"


def rerank_results(query: str, unified_results: list[dict], top_n: int = 5) -> list[dict]:
    """Cohere Reranker를 호출하고, 실무 비즈니스 룰(페널티)을 적용하여 최종 정렬합니다."""

    if not unified_results:
        return []

    # 1. Cohere Reranker API 호출
    co = cohere.ClientV2(api_key=settings.cohere_api_key)

    # Reranker에는 자식 청크의 내용(content)만 보냅니다.
    documents = [doc["content"] for doc in unified_results]

    response = co.rerank(
        model=COHERE_RERANK_MODEL,
        query=query,
        documents=documents,
        # 비즈니스 룰 적용을 위해 전체 결과를 받고, 이후 top_n으로 자릅니다.
        top_n=len(unified_results),
    )

    # API 결과를 기존 딕셔너리에 매핑
    for item in response.results:
        unified_results[item.index]["rerank_score"] = item.relevance_score

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
            multiplier *= 0.85
        elif "적용사례" in cat:
            multiplier *= 0.95

        # [룰 2] QNA/감리사례 chunk_type 선호도: A(회신/감리지적) > S(부록) > Q(질의)
        # Q 파트는 사용자 질문과 의미가 유사해 검색에 잘 걸리지만, 실제 답변이 아닙니다.
        # Findings(감리사례)의 Q도 동일하게 적용됩니다.
        chunk_type = doc.get("chunk_type", "")
        if chunk_type == "question":
            multiplier *= 0.80
        elif chunk_type == "supplementary":
            multiplier *= 0.95

        doc["final_score"] = base_score * multiplier

    # 3. 최종 점수 기준으로 내림차순 정렬 후 Top N 반환
    unified_results.sort(key=lambda x: x["final_score"], reverse=True)

    return unified_results[:top_n]

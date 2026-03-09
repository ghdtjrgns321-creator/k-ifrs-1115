# app/nodes/retrieve.py
# Vector + BM25 하이브리드 검색
#
# 검색 쿼리 보강 전략 (범용):
#   1. analyze_agent의 search_keywords (공식 용어 2~3개)
#   2. QUERY_MAPPING으로 사용자 원문의 실무 용어를 공식 용어로 자동 확장
#      → "쿠폰" → "고객충성제도", "멤버십" → "환불되지 않는 선수금" 등
#      → 수백 개 실무 용어가 매핑되어 있으므로 개별 키워드 추가 불필요
import asyncio

from app.config import settings
from app.retriever import search_all


def _expand_with_query_mapping(text: str) -> list[str]:
    """사용자 원문에서 QUERY_MAPPING 키에 해당하는 실무 용어를 찾아 공식 용어로 확장합니다.

    Why: analyze_agent가 추출하는 search_keywords는 공식 용어("수행의무", "수익인식 시점")라
    적용지침(B문단) 검색이 누락됨. 사용자 원문에 포함된 실무 용어("쿠폰", "적립금", "멤버십")를
    QUERY_MAPPING으로 확장하면 어떤 실무 용어든 관련 조항이 자동으로 검색됨.
    """
    from app.services.search_service import QUERY_MAPPING

    expanded: list[str] = []
    seen: set[str] = set()
    text_lower = text.lower()

    for practitioner_term, official_terms in QUERY_MAPPING.items():
        if practitioner_term.lower() in text_lower:
            for term in official_terms:
                if term not in seen:
                    seen.add(term)
                    expanded.append(term)

    return expanded


async def retrieve_docs(state: dict) -> dict:
    """사용자의 독립형 질문으로 Vector + BM25 하이브리드 검색을 수행.

    검색 쿼리 구성:
      1. search_keywords가 있으면 keywords 조인, 없으면 standalone_query
      2. 사용자 원문(standalone_query)을 QUERY_MAPPING으로 스캔하여 공식 용어 추가
    """
    keywords = state.get("search_keywords", [])
    if keywords:
        search_query = " ".join(keywords)
    else:
        search_query = state["standalone_query"]

    # 사용자 원문에서 실무 용어 → 공식 용어 자동 확장
    # standalone_query + 원본 메시지 모두 스캔 (analyze가 정규화하면서 실무 용어가 빠질 수 있으므로)
    original_text = state["standalone_query"]
    messages = state.get("messages", [])
    if messages:
        # 마지막 human 메시지 = 원본 질문
        for role, content in reversed(messages):
            if role == "human":
                original_text = content
                break

    expanded_terms = _expand_with_query_mapping(original_text)
    if expanded_terms:
        search_query += " " + " ".join(expanded_terms)

    # search_all은 동기 함수 (MongoDB + BM25) → 스레드에서 실행
    docs = await asyncio.to_thread(search_all, search_query, settings.retrieval_limit)

    return {"retrieved_docs": docs}

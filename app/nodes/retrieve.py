# app/nodes/retrieve.py
# Vector + BM25 하이브리드 검색
#
# 검색 쿼리 보강 전략 (범용):
#   1. analyze_agent의 search_keywords (공식 용어 3~5개)
#   2. QUERY_MAPPING으로 사용자 원문의 실무 용어를 공식 용어로 자동 확장
#      → "쿠폰" → "고객충성제도", "멤버십" → "환불되지 않는 선수금" 등
#   3. matched_topics 체크리스트에서 문단 번호 + judgment_goal 추출
#      → tree_matcher가 이미 매칭한 핵심 판단 문단을 검색 쿼리에 반영
import asyncio
import re

from app.retriever import search_all

# RRF 최종 반환 문서 수 — reranker가 이 중 상위 N개를 선별
RETRIEVAL_LIMIT = 30


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


def _extract_checklist_keywords(matched_topics: list[dict]) -> list[str]:
    """matched_topics의 체크리스트에서 검색 보강용 키워드를 추출합니다.

    Why: tree_matcher가 매칭한 체크리스트에는 핵심 판단 문단(B35, B37 등)이 명시되어 있지만,
    retrieve는 이를 활용하지 않아 해당 문단이 검색에서 누락됨.
    체크리스트 텍스트에서 문단 번호를 추출하고, judgment_goal을 추가하여 검색 쿼리를 보강.
    """
    keywords: list[str] = []
    seen: set[str] = set()

    for topic in matched_topics:
        # 1. 체크리스트에서 문단 번호 추출 ("문단 B37", "문단 35" 등)
        #    tree_type별로 checklist 항목이 str 또는 dict이므로 텍스트를 통합 추출
        for item in topic.get("checklist", []):
            if isinstance(item, str):
                text = item
            elif isinstance(item, dict):
                # qna_match: question 필드, red_flag: question + paragraph_basis
                text = " ".join(str(v) for v in item.values())
            else:
                continue

            for m in re.findall(r"문단\s*(B?\d+)", text):
                if m not in seen:
                    seen.add(m)
                    keywords.append(f"문단 {m}")

        # 2. judgment_goal 추가 (decision_tree에만 존재)
        #    예: "거래에서 기업이 본인인지 대리인인지 판단"
        goal = topic.get("judgment_goal", "")
        if goal and goal not in seen:
            seen.add(goal)
            keywords.append(goal)

    return keywords


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
    from app.nodes.generate import _get_last_human_message
    messages = state.get("messages", [])
    original_text = _get_last_human_message(messages) or state["standalone_query"]

    expanded_terms = _expand_with_query_mapping(original_text)
    if expanded_terms:
        search_query += " " + " ".join(expanded_terms)

    # matched_topics 체크리스트에서 핵심 문단 번호/judgment_goal 추출하여 검색 보강
    # Why: tree_matcher가 매칭한 체크리스트의 핵심 문단이 검색에 누락되는 문제 해결
    matched_topics = state.get("matched_topics", [])
    if matched_topics:
        checklist_kw = _extract_checklist_keywords(matched_topics)
        if checklist_kw:
            search_query += " " + " ".join(checklist_kw)

    # search_all은 동기 함수 (MongoDB + BM25) → 스레드에서 실행
    docs = await asyncio.to_thread(search_all, search_query, RETRIEVAL_LIMIT)

    return {"retrieved_docs": docs}

# app/nodes/retrieve.py
# 2계층 검색: 핀포인트(큐레이션) 1순위 + 리트리버(벡터+BM25) 2순위
#
# 검색 전략:
#   1순위: decision_tree의 precedents/red_flags에서 문서 ID 파싱 → MongoDB 직접 조회
#          → 큐레이션 데이터이므로 관련성 보장, 리트리버 커버리지 한계 보완
#   2순위: analyze_agent의 search_keywords + QUERY_MAPPING + 체크리스트 문단으로 하이브리드 검색
#          → 핀포인트가 커버 못하는 본문 조항/적용지침 보충
import asyncio
import logging
import re

from app.retriever import search_all, fetch_pinpoint_docs

logger = logging.getLogger(__name__)

# RRF 최종 반환 문서 수 — reranker가 이 중 상위 N개를 선별
RETRIEVAL_LIMIT = 30


def _expand_with_query_mapping(text: str) -> list[str]:
    """사용자 원문에서 QUERY_MAPPING 키에 해당하는 실무 용어를 찾아 공식 용어로 확장합니다.

    Why: analyze_agent가 추출하는 search_keywords는 공식 용어("수행의무", "수익인식 시점")라
    적용지침(B문단) 검색이 누락됨. 사용자 원문에 포함된 실무 용어("쿠폰", "적립금", "멤버십")를
    QUERY_MAPPING으로 확장하면 어떤 실무 용어든 관련 조항이 자동으로 검색됨.
    """
    from app.services.query_mapping import QUERY_MAPPING

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
        for item in topic.get("checklist", []):
            text = item
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


def _merge_pinpoint_and_retriever(
    pinpoint_docs: list[dict],
    retriever_docs: list[dict],
) -> list[dict]:
    """핀포인트(1순위) + 리트리버(2순위) 문서를 중복 제거하여 병합합니다.

    Why: 핀포인트가 큐레이션 데이터로 관련성이 보장되므로 앞에 배치하고,
    리트리버는 핀포인트가 커버 못하는 본문/적용지침을 뒤에서 보충.
    parent_id 기준으로 중복 제거하여 같은 문서가 2번 들어가지 않게 함.
    """
    merged: list[dict] = []
    seen_parent_ids: set[str] = set()
    seen_chunk_ids: set[str] = set()

    # 1순위: 핀포인트 문서
    for doc in pinpoint_docs:
        pid = doc.get("parent_id") or ""
        cid = doc.get("chunk_id") or ""
        if pid and pid not in seen_parent_ids:
            seen_parent_ids.add(pid)
        if cid:
            seen_chunk_ids.add(cid)
        merged.append(doc)

    # 2순위: 리트리버 문서 (핀포인트와 중복되는 parent_id 제외)
    for doc in retriever_docs:
        pid = doc.get("parent_id") or ""
        cid = doc.get("chunk_id") or ""
        # parent_id 중복 체크 (같은 QNA/감리사례 원문이 이미 핀포인트에 있으면 스킵)
        if pid and pid in seen_parent_ids:
            continue
        # chunk_id 중복 체크
        if cid and cid in seen_chunk_ids:
            continue
        if pid:
            seen_parent_ids.add(pid)
        if cid:
            seen_chunk_ids.add(cid)
        merged.append(doc)

    return merged


async def retrieve_docs(state: dict) -> dict:
    """2계층 검색: 핀포인트(1순위) + 리트리버(2순위).

    핀포인트: decision_tree의 precedents/red_flags 문서 ID → MongoDB 직접 조회
    리트리버: search_keywords + QUERY_MAPPING + 체크리스트 문단 → 벡터+BM25 하이브리드
    """
    matched_topics = state.get("matched_topics", [])

    # ── 2순위 검색 쿼리를 먼저 구성 (핀포인트와 독립적이므로 gather 전에 완료) ──
    keywords = state.get("search_keywords", [])
    if keywords:
        search_query = " ".join(keywords)
    else:
        search_query = state["standalone_query"]

    # 사용자 원문에서 실무 용어 → 공식 용어 자동 확장
    from app.nodes.generate import _get_last_human_message

    messages = state.get("messages", [])
    original_text = _get_last_human_message(messages) or state["standalone_query"]

    expanded_terms = _expand_with_query_mapping(original_text)
    if expanded_terms:
        search_query += " " + " ".join(expanded_terms)

    # matched_topics 체크리스트에서 핵심 문단 번호/judgment_goal 추출하여 검색 보강
    if matched_topics:
        checklist_kw = _extract_checklist_keywords(matched_topics)
        if checklist_kw:
            search_query += " " + " ".join(checklist_kw)

    # ── 핀포인트 + 리트리버 병렬 실행 ──
    # Why: 두 작업이 완전 독립 → 순차 실행 대비 max(핀포인트, 리트리버) 시간으로 단축
    pinpoint_docs, retriever_docs = await asyncio.gather(
        asyncio.to_thread(fetch_pinpoint_docs, matched_topics),
        asyncio.to_thread(search_all, search_query, RETRIEVAL_LIMIT),
    )

    # ── 병합: 핀포인트 1순위 + 리트리버 2순위 (중복 제거) ──
    merged = _merge_pinpoint_and_retriever(pinpoint_docs, retriever_docs)

    # 진단 로그: 각 계층별 문서 수 + pinpoint 상세
    logger.info(
        "pinpoint=%d, retriever=%d, merged=%d",
        len(pinpoint_docs),
        len(retriever_docs),
        len(merged),
    )
    for doc in pinpoint_docs:
        logger.debug(
            "  pinpoint: %s | %s | %s",
            doc["chunk_id"],
            doc["source"],
            doc.get("hierarchy", "")[:60],
        )

    return {"retrieved_docs": merged}

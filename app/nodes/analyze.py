# app/nodes/analyze.py
# 사용자 질문 분석 + 라우팅 + 온톨로지 개념 진입 (STEP 5-2)
# tree_matcher(임베딩 유사도+키워드 라우팅) 제거 → graph.resolve_question
import logging

from app.agents import analyze_agent
from app.domain.graph import get_graph

logger = logging.getLogger(__name__)

# 기준서별 전용 용어 — 프롬프트에서 못 잡는 경우 방어적 안전장치
# Why: C3 — "증분차입이자율"(1116호)을 "유의적 금융요소"(1115호)와 혼동하는 문제
_HARD_OUT_TERMS = {
    "증분차입이자율",
    "사용권자산",
    "리스부채",
    "리스료",
    "기대신용손실",
    "SPPI",
}
_IFRS1115_ANCHOR = {"수익 인식", "수행의무", "거래가격", "1115"}


def _get_last_human_message(messages: list[tuple[str, str]]) -> str:
    """대화 히스토리에서 마지막 사용자 메시지를 추출합니다."""
    for role, content in reversed(messages):
        if role == "human":
            return content
    return ""


async def analyze_query(state: dict) -> dict:
    """사용자 질문을 분석하여 멀티턴을 재구성하고 라우팅 방향을 결정합니다."""

    # 최근 3턴만 전달하여 토큰 절약
    formatted_messages = "\n".join(
        f"{role}: {content}" for role, content in state.get("messages", [])[-3:]
    )

    result = await analyze_agent.run(f"최신 대화 기록 및 질문: {formatted_messages}")
    data = result.output

    # 원본 사용자 메시지 — scope guard + tree_matcher 양쪽에서 사용
    user_text = _get_last_human_message(state.get("messages", []))

    # 코드 레벨 scope guard — 프롬프트 못 잡는 타 기준서 전용 용어 방어
    if data.routing == "IN":
        has_out = any(t in user_text for t in _HARD_OUT_TERMS)
        has_anchor = any(t in user_text for t in _IFRS1115_ANCHOR)
        if has_out and not has_anchor:
            logger.info("scope guard: OUT 강제 전환 (hard_out=%s)", user_text[:50])
            data.routing = "OUT"

    # 온톨로지 개념 진입 — 용어사전(결정적) + LLM 지목 토픽→개념 매핑
    # 임베딩 유사도 미사용. 개념 질문/상황 질문 모두 적용(그래프 탐색이 후보 축소).
    entry = get_graph().resolve_question(
        data.standalone_query or user_text,
        data.search_keywords,
        data.topic_hints,
    )

    return {
        "routing": data.routing,
        "standalone_query": data.standalone_query,
        "is_situation": data.is_situation,
        "search_keywords": data.search_keywords,
        "concept_ids": entry["concept_ids"],
        # via_topic: LLM 지목 주제 직속 개념(subtree 확장 전). 트리 매칭 오선택 차단용.
        "via_topic": entry["via_topic"],
        "entry_cases": entry["cases"],
        # matched_topics: 하위 노드 호환용 — 5-3/5-4에서 그래프 탐색으로 정리
        "matched_topics": [],
        "confusion_point": data.confusion_point,
        "complexity": data.complexity,
        "provided_info": data.provided_info,
        "needs_calculation": data.needs_calculation,
    }

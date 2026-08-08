# app/nodes/analyze.py
# 사용자 질문 분석 + 라우팅 + 온톨로지 개념 진입 (STEP 5-2)
# tree_matcher(임베딩 유사도+키워드 라우팅) 제거 → graph.resolve_question
import logging

from app.agents import analyze_agent
from app.config import settings
from app.domain.graph import get_graph
from app.embeddings import embed_query

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


async def _entry_vector(text: str) -> list[float] | None:
    """보조 진입용 질의 벡터 — 실패해도 파이프라인을 멈추지 않는다(안전망 성격).

    Why(원문 사용): 재작성문(standalone_query)은 회차마다 달라져 진입을 흔든다. 보조 진입은
    사용자 원문을 쓰므로 이 통로만큼은 결정적이다. exp_decision.md의 코사인 실측도 원문 기준이다.
    """
    if not text or settings.entry_embed_top_k <= 0:
        return None
    try:
        return await embed_query(text)
    except Exception:
        logger.warning("보조 진입 임베딩 실패 — 건너뜀", exc_info=True)
        return None


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

    # 온톨로지 개념 진입 — 용어사전 경유(LLM 지목 + 글자매칭) + 임베딩.
    # 개념 질문/상황 질문 모두 적용(그래프 탐색이 후보 축소).
    entry = get_graph().resolve_question(
        data.standalone_query or user_text,
        data.term_hints,
        query_vec=await _entry_vector(user_text),
    )

    return {
        "routing": data.routing,
        "standalone_query": data.standalone_query,
        "is_situation": data.is_situation,
        "concept_ids": entry["concept_ids"],
        # via_llm: LLM이 지목한 용어에서 나온 개념. 파이프라인은 안 쓰고 품질 로그만
        # 쓴다 — 진입이 빌 때 원인을 가르는 신호다(사례 수집 한정은 폐기됨).
        "via_llm": entry["via_llm"],
        # via_embed: 임베딩으로만 들어온 개념. 근거 경로에 진입 방식을 표시한다.
        "via_embed": entry["via_embed"],
        # matched_terms: 글자매칭으로 걸린 말. 파이프라인은 안 쓰고 품질 로그만 쓴다.
        # Why: 진입이 비었을 때 "사전 미등재" 때문인지 구분하는 유일한 신호(docs/quality-loop/01).
        "matched_terms": entry["matched_terms"],
        # term_hints: LLM이 고른 용어 원본. 파이프라인은 안 쓰고 품질 로그만 쓴다.
        # Why: 진입이 비었을 때 "LLM이 용어를 안 댔다"와 "댔는데 사전에 없는 말이었다"를
        # 가르는 유일한 신호다. 둘은 고칠 대상이 다르다(지시문 vs 사전).
        "term_hints": data.term_hints or [],
        # unknown_terms: LLM이 댔지만 사전에 없던 말 — 사전 보강 대상 목록.
        "unknown_terms": entry["unknown_terms"],
        # matched_topics: 하위 노드 호환용 — 5-3/5-4에서 그래프 탐색으로 정리
        "matched_topics": [],
        "confusion_point": data.confusion_point,
        "complexity": data.complexity,
        "provided_info": data.provided_info,
        "needs_calculation": data.needs_calculation,
    }

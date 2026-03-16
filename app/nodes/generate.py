# app/nodes/generate.py
# 최종 답변 생성 — PydanticAI의 네이티브 structured output으로 3단 폴백 제거
#
# is_situation 분기:
#   True  → clarify_agent (체크리스트 system prompt 동적 주입 + 꼬리질문 선택지)
#   False → generate_agent (개념 답변 + 꼬리질문)
import logging
import re

from app.agents import (
    generate_agent,
    clarify_agent,
    calc_clarify_agent,
    calc_fallback,
    ClarifyDeps,
    ClarifyOutput,
)
from app.domain.topic_content_map import get_topic_descs
from app.prompts import CLARIFY_USER, GENERATE_USER
from app.services.query_mapping import INVERTED_MAPPING

logger = logging.getLogger(__name__)


def _get_last_human_message(messages: list[tuple[str, str]]) -> str:
    """대화 히스토리에서 마지막 사용자 메시지를 추출합니다."""
    for role, content in reversed(messages):
        if role == "human":
            return content
    return ""


def _get_related_practitioner_terms(docs: list[dict]) -> str:
    """검색된 문서에 등장하는 기준서 공식 용어의 실무 별칭을 조회합니다."""
    combined_text = " ".join(
        (doc.get("content", "") + " " + doc.get("full_content", "")) for doc in docs
    )

    seen_official: set[str] = set()
    lines: list[str] = []

    for official_term, practitioner_terms in INVERTED_MAPPING.items():
        if official_term in combined_text and official_term not in seen_official:
            seen_official.add(official_term)
            aliases = ", ".join(f'"{pt}"' for pt in practitioner_terms[:3])
            lines.append(f"- {official_term} → 실무 표현: {aliases}")

    return "\n".join(lines[:5]) if lines else "(해당 없음)"


def _format_precedents_context(matched_topics: list[dict]) -> str:
    """matched_topics의 precedents + calculation_formula를 context 텍스트로 포맷.

    Why: retriever가 선례·공식을 못 찾을 수 있으므로, decision_tree에서 직접 주입하여
    LLM이 실제 사례와 계산 근거를 참조할 수 있게 한다.
    """
    parts: list[str] = []
    for topic in matched_topics:
        name = topic.get("topic_name", "")

        precedents = topic.get("precedents", {})
        if precedents:
            for branch, cases in precedents.items():
                parts.append(f"[선례: {name} — {branch}]")
                parts.extend(cases)

        formula = topic.get("calculation_formula")
        if formula:
            for branch, text in formula.items():
                parts.append(f"[계산공식: {name} — {branch}]")
                parts.append(text)

    return "\n".join(parts)


def _format_topic_knowledge(matched_topics: list[dict]) -> str:
    """매칭된 토픽의 topics.json desc 요약을 [참고 지식]으로 포맷.

    Why: 리트리버가 놓치는 핵심 문단도 desc 요약으로 100% 커버리지 확보.
    원문 대신 요약이므로 토큰 절약 효과.
    """
    parts: list[str] = []
    for topic in matched_topics:
        name = topic.get("topic_name", "")
        descs = get_topic_descs(name)
        if descs:
            parts.append(f"[{name} 핵심 요약]\n{descs}")
    return "\n\n".join(parts)


async def generate_answer(state: dict) -> dict:
    """최종 필터링된 문서를 바탕으로 답변을 생성합니다."""
    all_docs = state.get("relevant_docs", [])

    # IE 적용사례 pinpoint: calc 경로에서만 제외, 일반/상황 질문에서는 LLM에 전달
    # Why: calc에서는 IE 원문이 GENERATE_DOC_LIMIT 슬롯을 차지해 산술 문맥이 밀려나지만,
    #       일반/상황 질문에서는 IE 사례가 핵심 근거가 됨
    use_calc = state.get("needs_calculation", False)
    if use_calc:
        docs = [
            d
            for d in all_docs
            if not (d.get("chunk_type") == "pinpoint" and d.get("category") == "적용사례IE")
        ]
        ie_skipped = len(all_docs) - len(docs)
        if ie_skipped:
            logger.info("IE 적용사례 %d건 LLM context 제외 (calc 경로)", ie_skipped)
    else:
        docs = all_docs
    is_situation = state.get("is_situation", False)
    force_conclusion = state.get("force_conclusion", False)
    messages = state.get("messages", [])

    # fast-path 후속 턴: analyze 스킵으로 standalone_query가 비어있음
    # → 마지막 human 메시지를 question으로 사용
    if state.get("is_clarify_followup") and not state.get("standalone_query"):
        state["standalone_query"] = _get_last_human_message(messages) or "질문"

    # 문서 컨텍스트 + 출처 메타데이터 구성
    context_parts = []
    cited_sources = []

    for doc in docs:
        source_type = doc.get("source", "본문")
        raw = doc.get("full_content") if source_type != "본문" else doc.get("content")
        text = raw or ""
        hierarchy = doc.get("hierarchy", "")
        context_parts.append(f"[{source_type}] {hierarchy}\n{text}")
        cited_sources.append(
            {
                "source": source_type,
                "hierarchy": hierarchy,
                "chunk_id": doc.get("chunk_id", ""),
                "related_paragraphs": doc.get("related_paragraphs", []),
            }
        )

    context_str = "\n\n---\n\n".join(context_parts)
    confusion_point = state.get("confusion_point", "") or "(없음)"
    is_conclusion = False

    # LLM 호출 — is_situation + force_conclusion에 따라 agent 분기
    try:
        if is_situation and not force_conclusion:
            # clarify_agent 실패 시 generate_agent로 fallback
            # Why: C1 — result_validator의 ModelRetry 소진(retries=2)이나
            # Gemini API 일시 에러로 clarify 실패 시 답변 불가 방지
            try:
                output = await _run_clarify(
                    state, messages, context_str, confusion_point
                )
            except Exception:
                logger.warning(
                    "clarify_agent 실패 → generate_agent fallback", exc_info=True
                )
                output = await _run_force_conclusion(
                    state, docs, context_str, confusion_point
                )
            is_conclusion = output.is_conclusion
            # CalcClarifyOutput에는 selected_branches 없음 (non-reasoning 모델용)
            selected_branches = getattr(output, "selected_branches", [])
            structured_cited = output.cited_paragraphs
        elif is_situation and force_conclusion:
            output = await _run_force_conclusion(
                state, docs, context_str, confusion_point
            )
            is_conclusion = True
            selected_branches = []
            structured_cited = getattr(output, "cited_paragraphs", [])
        else:
            output = await _run_generate(state, docs, context_str, confusion_point)
            is_conclusion = output.is_conclusion
            selected_branches = []
            structured_cited = getattr(output, "cited_paragraphs", [])

        answer = output.answer
        # LLM이 answer 필드에 "follow_up_questions:" 텍스트를 포함시키는 경우 제거
        answer = re.split(
            r"\n*follow_up_questions\s*[:：]", answer, flags=re.IGNORECASE
        )[0].rstrip()
        follow_up_questions = output.follow_up_questions[:3]

        # concluded 상태에서 follow_up 강제 제거 (LLM 생성과 무관하게)
        # Why: C2 — Gemini thinking이 [결론 확인 모드] 프롬프트를 무시하고 follow_up 생성하는 문제 방지
        if (state.get("checklist_state") or {}).get("concluded", False):
            follow_up_questions = []

    except Exception:
        logger.error("generate_answer failed", exc_info=True)
        answer = "답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        follow_up_questions = []
        selected_branches = []
        structured_cited = []

    return {
        "answer": answer,
        "cited_sources": cited_sources,
        "follow_up_questions": follow_up_questions,
        "is_situation": is_situation,
        "is_conclusion": is_conclusion,
        "selected_branches": selected_branches,
        "cited_paragraphs": structured_cited,
    }


# ── 분기별 LLM 호출 ─────────────────────────────────────────────────────────


async def _run_clarify(
    state: dict, messages: list, context_str: str, confusion_point: str
) -> ClarifyOutput:
    """is_situation=True, force_conclusion=False → clarify_agent 호출."""
    deps = ClarifyDeps(
        matched_topics=state.get("matched_topics", []),
        checklist_state=state.get("checklist_state"),
        provided_info=state.get("provided_info", []),
        messages=messages,  # critical_factors 매칭 범위 확대 (C1)
    )
    # 대화 히스토리 구성 — AI가 이미 물어본 내용을 반복하지 않도록
    # Why: 최근 2턴만 사용 — checklist_state.checked_items에 이미 구조화된 Q&A가 있으므로
    # 전체 히스토리 순회는 토큰 낭비 (3턴째 context 비대화 → 5~10초 절감)
    recent = messages[-5:-1] if len(messages) > 5 else messages[:-1]
    history_lines = []
    for role, content in recent:
        prefix = "사용자" if role == "human" else "AI"
        history_lines.append(f"{prefix}: {content[:150]}")
    conversation_history = "\n".join(history_lines) if history_lines else "(첫 질문)"

    # 사용자 원문 추출 — 혼동점 해소에서 사용자가 쓴 단어를 인용하기 위해
    original_message = _get_last_human_message(messages)

    # calc 라우팅: analyze_agent가 LLM으로 판단한 needs_calculation 사용
    # Why: regex heuristic(_CALC_COMMAND + _AMOUNT_PATTERN)은 토픽 매칭 비결정성으로
    # B1/B2에서 1/3만 calc 진입하는 문제 발생 → LLM 판단으로 전환 (14/14 정확도)
    use_calc = state.get("needs_calculation", False)

    # topics.json desc 주입 — calc 경로에서는 스킵
    # Why: topic_knowledge(~2000자)가 gpt-4.1-mini의 산술 집중도를 분산시켜
    # 진행률 계산 등의 정확도가 0.845→0.67로 급락하는 현상 확인됨
    if not use_calc:
        topic_knowledge = _format_topic_knowledge(state.get("matched_topics", []))
        if topic_knowledge:
            context_str = f"[참고 지식]\n{topic_knowledge}\n\n---\n\n{context_str}"

    # precedents/formula를 context 앞에 추가 — retriever 의존도 축소
    precedents_text = _format_precedents_context(state.get("matched_topics", []))
    if precedents_text:
        context_str = f"[큐레이션 선례·공식]\n{precedents_text}\n\n---\n\n{context_str}"

    user_msg = CLARIFY_USER.format(
        context=context_str,
        confusion_point=confusion_point,
        conversation_history=conversation_history,
        original_message=original_message,
        question=state["standalone_query"],
    )

    # 듀얼트랙: 계산 질문이면 calc_clarify_agent, 아니면 Gemini Flash (기본값)
    # Why: clarify_agent는 Gemini thinking용 — selected_branches 필수 + validator 재시도.
    # gpt-4.1-mini(non-reasoning)에서 포맷 FAIL + 산술 정확도 하락 발생.
    # calc_clarify_agent는 non-reasoning 전용 스키마/프롬프트로 이 문제 해결.
    # 후속 턴(is_clarify_followup)은 thinking=low로 속도 최적화
    # Why: 짧은 확인 답변에 깊은 추론 불필요 — 턴당 ~20초 절감
    is_followup = state.get("is_clarify_followup", False)

    if use_calc:
        logger.info("clarify model=gpt-4.1-mini(calc) via calc_clarify_agent")
        result = await calc_clarify_agent.run(
            user_msg,
            model_settings={"temperature": 0.0},
        )
    elif is_followup:
        logger.info("clarify model=gemini-flash(thinking=low) [fast-path]")
        result = await clarify_agent.run(
            user_msg,
            deps=deps,
            model_settings={"google_thinking_config": {"thinking_level": "low"}},
        )
    else:
        logger.info("clarify model=gemini-flash(thinking=medium)")
        result = await clarify_agent.run(user_msg, deps=deps)
    return result.output


async def _run_force_conclusion(
    state: dict, docs: list, context_str: str, confusion_point: str
):
    """is_situation=True, force_conclusion=True → generate_agent에 체크리스트 맥락 포함."""
    checked = state.get("checklist_state", {})
    checked_items = checked.get("checked_items", []) if checked else []
    context_with_checks = context_str
    if checked_items:
        check_lines = []
        for c in checked_items:
            if isinstance(c, dict):
                check_lines.append(
                    f"- Q: {c.get('question', '?')} → A: {c.get('answer', '?')}"
                )
            else:
                check_lines.append(f"- {c}")
        context_with_checks += "\n\n[사용자가 확인한 사항]\n" + "\n".join(check_lines)

    # calc 라우팅: analyze_agent가 LLM으로 판단한 needs_calculation 사용
    use_calc = state.get("needs_calculation", False)

    # topics.json desc 주입 — calc 경로에서는 스킵 (산술 집중도 유지)
    if not use_calc:
        topic_knowledge = _format_topic_knowledge(state.get("matched_topics", []))
        if topic_knowledge:
            context_with_checks = (
                f"[참고 지식]\n{topic_knowledge}\n\n---\n\n{context_with_checks}"
            )

    # precedents/formula를 context 앞에 추가 — retriever 의존도 축소
    precedents_text = _format_precedents_context(state.get("matched_topics", []))
    if precedents_text:
        context_with_checks = (
            f"[큐레이션 선례·공식]\n{precedents_text}\n\n---\n\n{context_with_checks}"
        )

    user_msg = GENERATE_USER.format(
        complexity="complex",
        practitioner_terms=_get_related_practitioner_terms(docs),
        context=context_with_checks,
        confusion_point=confusion_point,
        question=state["standalone_query"],
    )

    # 듀얼트랙: 계산 질문이면 gpt-4.1-mini, 아니면 Gemini Flash (기본값)
    # force_conclusion은 항상 thinking=low — 충분한 맥락이 이미 확보된 상태
    if use_calc:
        logger.info("force_conclusion model=gpt-4.1-mini(calc)")
        result = await generate_agent.run(
            user_msg,
            model=calc_fallback,
            model_settings={"temperature": 0.0},
        )
    else:
        logger.info("force_conclusion model=gemini-flash(thinking=low)")
        result = await generate_agent.run(
            user_msg,
            model_settings={"google_thinking_config": {"thinking_level": "low"}},
        )
    return result.output


async def _run_generate(
    state: dict, docs: list, context_str: str, confusion_point: str
):
    """is_situation=False → generate_agent (개념 답변)."""
    complexity = state.get("complexity", "complex")
    user_msg = GENERATE_USER.format(
        complexity=complexity,
        practitioner_terms=_get_related_practitioner_terms(docs),
        context=context_str,
        confusion_point=confusion_point,
        question=state["standalone_query"],
    )

    # 듀얼트랙 라우팅: 계산 → gpt-4.1-mini, simple → Gemini low, complex → Gemini high
    use_calc = state.get("needs_calculation", False)
    model_tag = "gemini-flash(thinking=medium)"  # 기본값 — 분기 추가 시 미선언 방지
    if use_calc:
        model_tag = "gpt-4.1-mini(calc)"
        result = await generate_agent.run(
            user_msg,
            model=calc_fallback,
            model_settings={"temperature": 0.0},
        )
    elif complexity == "simple":
        model_tag = "gemini-flash(thinking=low)"
        result = await generate_agent.run(
            user_msg,
            model_settings={"google_thinking_config": {"thinking_level": "low"}},
        )
    else:
        model_tag = "gemini-flash(thinking=medium)"
        result = await generate_agent.run(user_msg)

    logger.info("generate model=%s, complexity=%s", model_tag, complexity)
    return result.output

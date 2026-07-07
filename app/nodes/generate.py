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
from app.config import settings
from app.domain.graph import get_graph
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


def _format_concept_hint(concept_path: list[str]) -> str:
    """그래프 탐색 경로(traverse.path)에서 개념명을 뽑아 [관련 개념] 힌트로 포맷.

    topics.json desc 주입을 대체 — 원문은 retrieved_docs가 담고, 여기서는
    질문이 어느 K-IFRS 1115호 개념에 걸렸는지 결정적 경로만 힌트로 제공한다.
    """
    names: list[str] = []
    for p in concept_path:
        m = re.search(r"개념\[(.+?)\]", p)
        if m and m.group(1) not in names:
            names.append(m.group(1))
    return ", ".join(names)


def _inject_prefix(state: dict, context: str) -> str:
    """calc 아닌 경로 공통 주입 — 관련개념·판단트리를 context 앞에.

    3경로(_run_generate/_run_clarify/_run_force_conclusion)가 동일 로직을 중복하던 것을 통합.

    Note: STEP2 혼동쌍 기반 프레임판별 헤더는 활성화 신호 부재로 미채택
    (근거: app/test/qna_holdout/step2_postmortem.md). confusion_pairs.json은 보존.
    """
    if state.get("needs_calculation", False):
        return context
    g = get_graph()
    concept_hint = _format_concept_hint(state.get("concept_path", []))
    if concept_hint:
        context = f"[관련 개념] {concept_hint}\n\n---\n\n{context}"
    tree = g.match_judgment_tree(
        state.get("concept_ids", []), state.get("via_topic", [])
    )
    if tree:
        context = f"[판단 절차 — 기준서 본문]\n{tree}\n\n---\n\n{context}"
    return context


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
            if not (
                d.get("chunk_type") == "pinpoint" and d.get("category") == "적용사례IE"
            )
        ]
        ie_skipped = len(all_docs) - len(docs)
        if ie_skipped:
            logger.info("IE 적용사례 %d건 LLM context 제외 (calc 경로)", ie_skipped)
    else:
        docs = all_docs

    # 유형별 슬롯 상한 — 문단·감리·IE를 분리해 서로 밀어내지 않게(07-retrieval-priority §3).
    # 문단은 fetch가 tr.paras 진입순서를 보존 → 앞쪽이 topic_hint 주제 개념 문단.
    def _kind(d: dict) -> str:
        s = str(d.get("source", ""))
        if "감리" in s:
            return "findings"
        if "질의" in s:
            return "qna"
        if s == "적용사례IE":
            return "ie"
        return "para"

    buckets: dict[str, list] = {"para": [], "findings": [], "ie": [], "qna": []}
    for d in docs:
        buckets[_kind(d)].append(d)
    n_before = len(docs)
    # 문단은 무제한(doc_slot_para=0 → cap=None → 전체). A안: C 상한밀림 해소.
    para_cap = settings.doc_slot_para or None
    sel = {
        "para": buckets["para"][:para_cap],
        "ie": buckets["ie"][: settings.doc_slot_ie],
        "findings": buckets["findings"][: settings.doc_slot_findings],
        "qna": buckets["qna"][: settings.doc_slot_qna],
    }
    docs = sel["para"] + sel["ie"] + sel["findings"] + sel["qna"]
    if n_before > len(docs):
        logger.info(
            "유형 슬롯: %d → %d건 (문단%d·IE%d·감리%d·QNA%d)",
            n_before,
            len(docs),
            len(sel["para"]),
            len(sel["ie"]),
            len(sel["findings"]),
            len(sel["qna"]),
        )

    is_situation = state.get("is_situation", False)
    force_conclusion = state.get("force_conclusion", False)
    messages = state.get("messages", [])

    # fast-path 후속 턴: analyze 스킵으로 standalone_query가 비어있음
    # → 마지막 human 메시지를 question으로 사용
    if state.get("is_clarify_followup") and not state.get("standalone_query"):
        # checklist_state에 저장된 원래 질문 + 현재 답변 결합
        # Why: fast-path에서 analyze 스킵 시 standalone_query가 비어있는데,
        # 현재 답변("A한테 있다")만으로는 LLM이 맥락을 알 수 없음
        original_query = (state.get("checklist_state") or {}).get("original_query", "")
        current_answer = _get_last_human_message(messages) or ""
        if original_query:
            state["standalone_query"] = (
                f"{original_query} (사용자 추가 정보: {current_answer})"
            )
        else:
            state["standalone_query"] = current_answer or "질문"

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
    recent = messages[-5:] if len(messages) > 5 else messages
    history_lines = []
    for role, content in recent:
        prefix = "사용자" if role == "human" else "AI"
        history_lines.append(f"{prefix}: {content[:500]}")
    conversation_history = "\n".join(history_lines) if history_lines else "(첫 질문)"

    # 사용자 원문 추출 — 혼동점 해소에서 사용자가 쓴 단어를 인용하기 위해
    original_message = _get_last_human_message(messages)

    # calc 라우팅: analyze_agent가 LLM으로 판단한 needs_calculation 사용
    # Why: regex heuristic(_CALC_COMMAND + _AMOUNT_PATTERN)은 토픽 매칭 비결정성으로
    # B1/B2에서 1/3만 calc 진입하는 문제 발생 → LLM 판단으로 전환 (14/14 정확도)
    use_calc = state.get("needs_calculation", False)

    # 그래프 경로 힌트 + 판단 트리 + 프레임판별 주입 — calc 경로에서는 스킵(산술 집중도)
    context_str = _inject_prefix(state, context_str)

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
    logger.info("TOKENUSAGE clarify %s", result.usage())
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

    # 그래프 경로 힌트 + 판단 트리 + 프레임판별 주입 — calc 경로에서는 스킵(산술 집중도)
    context_with_checks = _inject_prefix(state, context_with_checks)

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
    logger.info("TOKENUSAGE force_conclusion %s", result.usage())
    return result.output


async def _run_generate(
    state: dict, docs: list, context_str: str, confusion_point: str
):
    """is_situation=False → generate_agent (개념 답변)."""
    complexity = state.get("complexity", "complex")

    # 그래프 경로 힌트 + 판단 트리 + 프레임판별 주입 — calc 경로에서는 스킵(산술 집중도).
    # Why(주입 0%): 일반 개념 질문 경로에 트리·개념 힌트가 없어 판단 절차를 못 봤음.
    context_str = _inject_prefix(state, context_str)

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
    logger.info("TOKENUSAGE generate %s", result.usage())
    return result.output

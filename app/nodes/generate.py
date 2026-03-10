# app/nodes/generate.py
# 최종 답변 생성 — PydanticAI의 네이티브 structured output으로 3단 폴백 제거
#
# is_situation 분기:
#   True  → clarify_agent (체크리스트 system prompt 동적 주입 + 꼬리질문 선택지)
#   False → generate_agent (개념 답변 + 꼬리질문)
import re
import traceback

from app.agents import generate_agent, clarify_agent, ClarifyDeps, GenerateOutput
from app.prompts import CLARIFY_USER, GENERATE_USER
from app.services.search_service import INVERTED_MAPPING

# 생성에 사용할 최대 문서 수 — reranker가 관련성 순 정렬하므로 상위 N개면 충분
GENERATE_DOC_LIMIT = 3
# PDR 원리 + 토큰 절약: 문서당 최대 글자 수
MAX_DOC_CHARS = 1200


def _get_last_human_message(messages: list[tuple[str, str]]) -> str:
    """대화 히스토리에서 마지막 사용자 메시지를 추출합니다."""
    for role, content in reversed(messages):
        if role == "human":
            return content
    return ""


def _get_related_practitioner_terms(docs: list[dict]) -> str:
    """검색된 문서에 등장하는 기준서 공식 용어의 실무 별칭을 조회합니다."""
    combined_text = " ".join(
        (doc.get("content", "") + " " + doc.get("full_content", ""))
        for doc in docs
    )

    seen_official: set[str] = set()
    lines: list[str] = []

    for official_term, practitioner_terms in INVERTED_MAPPING.items():
        if official_term in combined_text and official_term not in seen_official:
            seen_official.add(official_term)
            aliases = ", ".join(f'"{pt}"' for pt in practitioner_terms[:3])
            lines.append(f"- {official_term} → 실무 표현: {aliases}")

    return "\n".join(lines[:5]) if lines else "(해당 없음)"


async def generate_answer(state: dict) -> dict:
    """최종 필터링된 문서를 바탕으로 답변을 생성합니다."""
    docs = state.get("relevant_docs", [])[:GENERATE_DOC_LIMIT]
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
        text = raw[:MAX_DOC_CHARS] if raw and len(raw) > MAX_DOC_CHARS else raw
        hierarchy = doc.get("hierarchy", "")
        context_parts.append(f"[{source_type}] {hierarchy}\n{text}")
        cited_sources.append({
            "source": source_type,
            "hierarchy": hierarchy,
            "chunk_id": doc.get("chunk_id", ""),
            "related_paragraphs": doc.get("related_paragraphs", []),
        })

    context_str = "\n\n---\n\n".join(context_parts)
    confusion_point = state.get("confusion_point", "") or "(없음)"
    is_conclusion = False

    # LLM 호출 — is_situation + force_conclusion에 따라 agent 분기
    try:
        if is_situation and not force_conclusion:
            output = await _run_clarify(state, messages, context_str, confusion_point)
            is_conclusion = output.is_conclusion

        elif is_situation and force_conclusion:
            output = await _run_force_conclusion(state, docs, context_str, confusion_point)
            is_conclusion = True

        else:
            output = await _run_generate(state, docs, context_str, confusion_point)
            is_conclusion = output.is_conclusion

        answer = output.answer
        # LLM이 answer 필드에 "follow_up_questions:" 텍스트를 포함시키는 경우 제거
        answer = re.split(r'\n*follow_up_questions\s*[:：]', answer, flags=re.IGNORECASE)[0].rstrip()
        follow_up_questions = output.follow_up_questions[:3]

    except Exception:
        print(f"[error] generate_answer failed:\n{traceback.format_exc()}")
        answer = "답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        follow_up_questions = []

    return {
        "answer": answer,
        "cited_sources": cited_sources,
        "follow_up_questions": follow_up_questions,
        "is_situation": is_situation,
        "is_conclusion": is_conclusion,
    }


# ── 분기별 LLM 호출 ─────────────────────────────────────────────────────────

async def _run_clarify(
    state: dict, messages: list, context_str: str, confusion_point: str
) -> GenerateOutput:
    """is_situation=True, force_conclusion=False → clarify_agent 호출."""
    deps = ClarifyDeps(
        matched_topics=state.get("matched_topics", []),
        checklist_state=state.get("checklist_state"),
    )
    # 대화 히스토리 구성 — AI가 이미 물어본 내용을 반복하지 않도록
    history_lines = []
    for role, content in messages[:-1]:  # 마지막(현재 질문)은 제외
        prefix = "사용자" if role == "human" else "AI"
        history_lines.append(f"{prefix}: {content[:300]}")
    conversation_history = "\n".join(history_lines) if history_lines else "(첫 질문)"

    # 사용자 원문 추출 — 혼동점 해소에서 사용자가 쓴 단어를 인용하기 위해
    original_message = _get_last_human_message(messages)

    user_msg = CLARIFY_USER.format(
        context=context_str,
        confusion_point=confusion_point,
        conversation_history=conversation_history,
        original_message=original_message,
        question=state["standalone_query"],
    )
    result = await clarify_agent.run(user_msg, deps=deps)
    return result.output


async def _run_force_conclusion(
    state: dict, docs: list, context_str: str, confusion_point: str
) -> GenerateOutput:
    """is_situation=True, force_conclusion=True → generate_agent에 체크리스트 맥락 포함."""
    checked = state.get("checklist_state", {})
    checked_items = checked.get("checked_items", []) if checked else []
    context_with_checks = context_str
    if checked_items:
        check_lines = []
        for c in checked_items:
            if isinstance(c, dict):
                check_lines.append(f"- Q: {c.get('question', '?')} → A: {c.get('answer', '?')}")
            else:
                check_lines.append(f"- {c}")
        context_with_checks += "\n\n[사용자가 확인한 사항]\n" + "\n".join(check_lines)

    user_msg = GENERATE_USER.format(
        complexity="complex",
        practitioner_terms=_get_related_practitioner_terms(docs),
        context=context_with_checks,
        confusion_point=confusion_point,
        question=state["standalone_query"],
    )
    result = await generate_agent.run(user_msg)
    return result.output


async def _run_generate(
    state: dict, docs: list, context_str: str, confusion_point: str
) -> GenerateOutput:
    """is_situation=False → generate_agent (개념 답변)."""
    complexity = state.get("complexity", "complex")
    user_msg = GENERATE_USER.format(
        complexity=complexity,
        practitioner_terms=_get_related_practitioner_terms(docs),
        context=context_str,
        confusion_point=confusion_point,
        question=state["standalone_query"],
    )
    # complexity 기반 reasoning 강도 조절: simple → low(빠름), complex → medium(기본값)
    # Why: 모델을 바꾸면 agent-level model_settings와 충돌 → 같은 모델에서 effort만 조절
    if complexity == "simple":
        result = await generate_agent.run(
            user_msg,
            model_settings={"openai_reasoning_effort": "low", "max_tokens": 4096},
        )
    else:
        result = await generate_agent.run(user_msg)
    return result.output

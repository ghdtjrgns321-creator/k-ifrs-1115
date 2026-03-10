# app/nodes/generate.py
# 최종 답변 생성 — PydanticAI의 네이티브 structured output으로 3단 폴백 제거
#
# is_situation 분기:
#   True  → clarify_agent (체크리스트 system prompt 동적 주입 + 꼬리질문 선택지)
#   False → generate_agent (개념 답변 + 꼬리질문)
import re

from app.agents import generate_agent, clarify_agent, ClarifyDeps, GenerateOutput, _generate_model, _front_model
from app.prompts import CLARIFY_USER, GENERATE_USER
from app.services.search_service import INVERTED_MAPPING


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
    """최종 필터링된 문서를 바탕으로 답변을 생성합니다.

    PydanticAI의 네이티브 Pydantic 검증 + 자동 재시도로
    LangChain의 3단 폴백(structured→StrParser→raw) 코드를 완전 제거합니다.
    """
    # 토큰 절약: reranker가 관련성 순 정렬 → 상위 3개면 충분
    docs = state.get("relevant_docs", [])[:3]
    is_situation = state.get("is_situation", False)
    force_conclusion = state.get("force_conclusion", False)

    # fast-path 후속 턴: analyze 스킵으로 standalone_query가 비어있음
    # → 마지막 human 메시지를 question으로 사용
    if state.get("is_clarify_followup") and not state.get("standalone_query"):
        messages = state.get("messages", [])
        for role, content in reversed(messages):
            if role == "human":
                state["standalone_query"] = content
                break

    # 문서 컨텍스트 + 출처 메타데이터 구성
    context_parts = []
    cited_sources = []

    for doc in docs:
        source_type = doc.get("source", "본문")
        # PDR 원리 + 토큰 절약: full_content를 최대 2,000자로 제한
        MAX_DOC_CHARS = 1200
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
    # 사용자 혼동 원인 — 빈 문자열이면 "(없음)" 처리
    confusion_point = state.get("confusion_point", "") or "(없음)"
    is_conclusion = False

    # LLM 호출 — is_situation + force_conclusion에 따라 agent 분기
    try:
        if is_situation and not force_conclusion:
            # clarify_agent: 체크리스트가 system prompt에 동적 주입됨
            deps = ClarifyDeps(
                matched_topics=state.get("matched_topics", []),
                checklist_state=state.get("checklist_state"),
            )
            # 대화 히스토리 구성 — AI가 이미 물어본 내용을 반복하지 않도록
            messages = state.get("messages", [])
            history_lines = []
            for role, content in messages[:-1]:  # 마지막(현재 질문)은 제외
                prefix = "사용자" if role == "human" else "AI"
                history_lines.append(f"{prefix}: {content[:300]}")
            conversation_history = "\n".join(history_lines) if history_lines else "(첫 질문)"

            user_msg = CLARIFY_USER.format(
                context=context_str,
                confusion_point=confusion_point,
                conversation_history=conversation_history,
                question=state["standalone_query"],
            )
            # 첫 턴: reasoning 모델로 정확한 분석, 후속 턴: 경량 모델로 빠른 응답
            model_override = _generate_model() if not state.get("is_clarify_followup") else None
            result = await clarify_agent.run(user_msg, deps=deps, model=model_override)
            output: GenerateOutput = result.output
            is_conclusion = output.is_conclusion

        elif is_situation and force_conclusion:
            # 강제 결론: generate_agent에 체크리스트 맥락 포함
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
                practitioner_terms=_get_related_practitioner_terms(docs),
                context=context_with_checks,
                confusion_point=confusion_point,
                question=state["standalone_query"],
            )
            result = await generate_agent.run(user_msg)
            output = result.output
            is_conclusion = True

        else:
            # generate_agent: 개념 답변 + 실무 용어 대응표
            user_msg = GENERATE_USER.format(
                practitioner_terms=_get_related_practitioner_terms(docs),
                context=context_str,
                confusion_point=confusion_point,
                question=state["standalone_query"],
            )
            # complexity 기반 모델 스위칭: simple → gpt-5-mini(빠름), complex → o4-mini(정확)
            complexity = state.get("complexity", "complex")
            if complexity == "simple":
                result = await generate_agent.run(
                    user_msg,
                    model=_front_model(),
                    model_settings={"openai_reasoning_effort": "low", "max_tokens": 4096},
                )
            else:
                result = await generate_agent.run(user_msg)
            output = result.output

        answer = output.answer
        # LLM이 answer 필드에 "follow_up_questions:" 텍스트를 포함시키는 경우 제거
        answer = re.split(r'\n*follow_up_questions\s*[:：]', answer, flags=re.IGNORECASE)[0].rstrip()
        follow_up_questions = output.follow_up_questions[:3]

    except Exception:
        # 모든 재시도 실패 시 — 서비스 중단 방지
        answer = "답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        follow_up_questions = []

    return {
        "answer": answer,
        "cited_sources": cited_sources,
        "follow_up_questions": follow_up_questions,
        "is_situation": is_situation,
        "is_conclusion": is_conclusion,
    }

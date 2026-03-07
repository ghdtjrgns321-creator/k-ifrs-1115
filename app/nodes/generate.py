import json

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from pydantic import BaseModel, Field

from app.llm import get_generate_llm
from app.state import RAGState
from app.prompts import GENERATE_PROMPT, CLARIFY_PROMPT
from app.services.search_service import INVERTED_MAPPING


# LLM이 한 번의 호출로 반환해야 하는 구조화된 출력 스키마
# with_structured_output()이 이 모델을 기반으로 JSON을 파싱합니다.
class GenerateOutput(BaseModel):
    answer: str = Field(description="K-IFRS 1115호 답변 (마크다운)")
    follow_up_questions: list[str] = Field(
        description="실무 담당자를 위한 핵심 후속 질문 3개 (각 20자 이내, '👉 ' 접두어 포함)"
    )


def _get_related_practitioner_terms(docs: list[dict]) -> str:
    """검색된 문서에 등장하는 기준서 공식 용어의 실무 별칭을 INVERTED_MAPPING에서 조회합니다.

    왜 필터링하는가:
      전체 매핑을 주입하면 토큰 낭비 + 무관한 용어로 LLM이 혼동됩니다.
      실제 컨텍스트에 등장하는 용어만 선별해 '현재 질문과 연관된' 대응표를 구성합니다.
    """
    # 검색된 모든 문서 텍스트를 하나로 합쳐 포함 여부를 일괄 검사합니다.
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

    # 과도한 토큰 방지: 최대 15개 항목만 주입합니다.
    return "\n".join(lines[:15]) if lines else "(해당 없음)"


def generate_answer(state: RAGState):
    """최종 필터링된 문서를 바탕으로 환각 없는 정확한 회계 답변을 생성합니다.

    LLM 1회 호출로 답변(answer)과 꼬리질문(follow_up_questions)을 동시에 생성합니다.
    structured_output 실패 시 StrOutputParser로 폴백하여 서비스 안정성을 보장합니다.
    """
    docs = state.get("relevant_docs", [])

    context_parts = []
    cited_sources = []

    for doc in docs:
        source_type = doc.get("source", "본문")

        # PDR 원리: 자식 청크가 아닌 부모 원문(full_content)을 통째로 LLM에 넘김
        text = doc.get("full_content") if source_type != "본문" else doc.get("content")
        hierarchy = doc.get("hierarchy", "")

        context_parts.append(f"[{source_type}] {hierarchy}\n{text}")

        cited_sources.append({
            "source": source_type,
            "hierarchy": hierarchy,
            "chunk_id": doc.get("chunk_id", ""),
            "related_paragraphs": doc.get("related_paragraphs", [])
        })

    context_str = "\n\n---\n\n".join(context_parts)

    # is_situation=True면 결론 금지 + 꼬리질문 선택지 모드
    is_situation = state.get("is_situation", False)
    prompt_template = CLARIFY_PROMPT if is_situation else GENERATE_PROMPT

    invoke_input = {
        "context": context_str,
        "question": state["standalone_query"],
    }

    # GENERATE_PROMPT에만 실무 용어 대응표를 주입합니다.
    # CLARIFY_PROMPT는 꼬리질문 수집이 목적이므로 용어표가 불필요합니다.
    if not is_situation:
        invoke_input["practitioner_terms"] = _get_related_practitioner_terms(docs)

    answer, follow_up_questions = _invoke_structured(invoke_input, prompt_template)

    return {
        "answer": answer,
        "cited_sources": cited_sources,
        "follow_up_questions": follow_up_questions,
        "is_situation": is_situation,
    }


def _invoke_structured(invoke_input: dict, prompt_template: str = GENERATE_PROMPT) -> tuple[str, list[str]]:
    """LLM을 1회 호출하여 (answer, follow_up_questions)를 반환합니다.

    1차 시도: with_structured_output() — JSON 스키마를 강제하여 파싱 보장
    2차 폴백: StrOutputParser → 수동 JSON 파싱 시도
    3차 폴백: 원문 텍스트 반환, 꼬리질문 빈 리스트
    """
    prompt = ChatPromptTemplate.from_template(prompt_template)
    llm = get_generate_llm()

    # 1차 시도: structured output (LLM이 GenerateOutput JSON을 직접 반환)
    try:
        structured_llm = llm.with_structured_output(GenerateOutput)
        result: GenerateOutput = (prompt | structured_llm).invoke(invoke_input)
        return result.answer, result.follow_up_questions[:3]
    except Exception:
        pass

    # 2차 폴백: plain text 출력 → JSON 직접 파싱
    try:
        raw = (prompt | llm | StrOutputParser()).invoke(invoke_input)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > 0:
            parsed = json.loads(raw[start:end])
            answer = parsed.get("answer", raw)
            follow_ups = parsed.get("follow_up_questions", [])
            if isinstance(follow_ups, list):
                return answer, [q for q in follow_ups if isinstance(q, str)][:3]
        # JSON 파싱 실패 시 원문 그대로 반환
        return raw, []
    except Exception:
        # 모든 시도 실패 시 — 서비스 중단을 막기 위해 에러 메시지를 답변으로 반환
        return "답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.", []

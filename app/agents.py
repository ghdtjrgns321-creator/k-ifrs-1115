# app/agents.py
# PydanticAI Agent 정의 — LangChain의 ChatPromptTemplate + with_structured_output() 대체
#
# 7개 LLM 호출 포인트를 PydanticAI Agent로 통일합니다:
#   analyze_agent  — 질문 분석/라우팅 (gpt-4.1-mini, structured output)
#   grade_agent    — 문서 품질 평가 (gpt-4.1-mini, structured output)
#   generate_agent — 최종 답변 생성 (gpt-5-mini, reasoning_effort=medium, structured output)
#   clarify_agent  — 거래 상황 분석 + 결론 (gpt-5-mini, reasoning_effort=medium, 동적 system prompt)
#   rewrite_agent  — 질문 재작성 (gpt-4.1-mini, plain text)
#   hyde_agent     — HyDE 가상 문서 (gpt-4.1-mini, plain text)
#   text_agent     — search_service LLM 키워드 추출용 (gpt-4.1-mini, plain text)
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import settings
from app.prompts import ANALYZE_PROMPT, CLARIFY_SYSTEM, GENERATE_SYSTEM


# ── 모델 팩토리 ────────────────────────────────────────────────────────────────
# OpenAIProvider로 api_key를 주입하고, OpenAIModel에 provider를 전달합니다.

_provider = OpenAIProvider(api_key=settings.openai_api_key)


def _front_model() -> OpenAIModel:
    """analyze / grade / rewrite / hyde 용 경량 모델."""
    return OpenAIModel(settings.llm_front_model, provider=_provider)


def _generate_model() -> OpenAIModel:
    """generate/clarify 전용 reasoning 모델 (gpt-5-mini, reasoning_effort=medium)."""
    return OpenAIModel(settings.llm_generate_model, provider=_provider)


# ── 출력 스키마 ────────────────────────────────────────────────────────────────

class AnalyzeResult(BaseModel):
    routing: str = Field(description="회계 관련이면 'IN', 무관하면 'OUT'")
    standalone_query: str = Field(description="재작성된 독립형 질문 (OUT이면 빈 문자열)")
    is_situation: bool = Field(default=False, description="구체적 거래 상황 설명이면 True")
    search_keywords: list[str] = Field(default_factory=list, description="벡터 DB 검색용 K-IFRS 핵심 키워드 3~5개")
    confusion_point: str = Field(
        default="",
        description="사용자 혼동 원인 (예: '세금계산서 발행 주체'). 없으면 빈 문자열",
    )
    complexity: str = Field(
        default="complex",
        description="simple: 단일 쟁점/조항 직접 인용 가능, complex: 다중 쟁점/Case 분기 필요",
    )


class DocGrade(BaseModel):
    chunk_id: str = Field(description="평가한 문서의 chunk_id")
    is_relevant: bool = Field(description="질문에 대한 답변으로 유효한지 여부 (True/False)")


class GradeResult(BaseModel):
    results: list[DocGrade]


class GenerateOutput(BaseModel):
    answer: str = Field(description="K-IFRS 1115호 답변 (마크다운)")
    follow_up_questions: list[str] = Field(
        description="실무 담당자를 위한 핵심 후속 질문 3개"
    )
    is_conclusion: bool = Field(
        default=False,
        description="충분한 정보가 모여 최종 결론을 포함한 답변이면 True",
    )


# ── 의존성 (clarify_agent 동적 system prompt 주입용) ────────────────────────────

@dataclass
class ClarifyDeps:
    """clarify_agent에 런타임으로 주입되는 의존성."""
    matched_topics: list[dict] = field(default_factory=list)
    checklist_state: dict | None = None


# ── Agent 정의 ─────────────────────────────────────────────────────────────────

analyze_agent = Agent(
    _front_model(),
    output_type=AnalyzeResult,
    retries=2,
    system_prompt=ANALYZE_PROMPT,
    model_settings={"temperature": settings.llm_temperature},
)

grade_agent = Agent(
    _front_model(),
    output_type=GradeResult,
    retries=2,
    model_settings={"temperature": settings.llm_temperature},
)

generate_agent = Agent(
    _generate_model(),
    output_type=GenerateOutput,
    retries=2,
    system_prompt=GENERATE_SYSTEM,
    # reasoning 모델은 temperature 무시 → reasoning_effort로 속도/품질 조절
    # max_tokens=4096: reasoning 내부 사고 토큰 + 출력 토큰 합산 상한 → 과도한 reasoning 방지로 10~30% 속도 개선
    model_settings={"openai_reasoning_effort": "medium", "max_tokens": 4096},
)

clarify_agent = Agent(
    _generate_model(),  # o4-mini: 거래 상황 분석은 reasoning 필수
    output_type=GenerateOutput,
    retries=2,
    deps_type=ClarifyDeps,
    # reasoning 모델 → temperature 자동 무시, reasoning_effort로 속도/품질 조절
    model_settings={"openai_reasoning_effort": "medium", "max_tokens": 4096},
)

rewrite_agent = Agent(
    _front_model(),
    output_type=str,
    retries=2,
    model_settings={"temperature": settings.llm_temperature},
)

hyde_agent = Agent(
    _front_model(),
    output_type=str,
    retries=1,
    model_settings={"temperature": settings.llm_temperature},
)

# search_service._extract_keywords_llm 등 범용 텍스트 호출용
text_agent = Agent(
    _front_model(),
    output_type=str,
    retries=1,
    model_settings={"temperature": settings.llm_temperature},
)


# ── clarify_agent 동적 system prompt ───────────────────────────────────────────
# 체크리스트를 system 메시지에 직접 주입 → user 메시지에 끼워넣기보다 LLM이 더 강하게 따름

@clarify_agent.system_prompt
async def _inject_clarify_system(ctx: RunContext[ClarifyDeps]) -> str:
    """CLARIFY_SYSTEM + 체크리스트 가이드 + 이미 확인된 항목을 합쳐 system prompt를 구성합니다."""
    parts = [CLARIFY_SYSTEM]

    # 체크리스트 가이드 (tree_matcher가 매칭한 토픽)
    # 체크리스트 범위 밖 질문을 금지하여 맥락 이탈 방지
    total_checklist_items = 0
    if ctx.deps.matched_topics:
        guide_lines = [
            "\n\n[체크리스트 가이드레일] 반드시 아래 체크리스트 항목 범위 내에서만 질문하세요. "
            "체크리스트 외 질문은 금지합니다. 사용자가 설명한 거래와 무관한 업종/산업의 질문도 금지합니다."
        ]
        for topic in ctx.deps.matched_topics:
            guide_lines.append(topic["checklist_text"])
            # 체크리스트 항목 수 카운트
            total_checklist_items += len(topic.get("checklist", []))
        parts.append("\n\n".join(guide_lines))

    # 멀티턴: 이미 확인된 항목 (Q&A 쌍 또는 레거시 문자열)
    checked_count = 0
    if ctx.deps.checklist_state:
        checked = ctx.deps.checklist_state.get("checked_items", [])
        checked_count = len(checked)
        if checked:
            formatted_items = []
            for item in checked:
                if isinstance(item, dict):
                    formatted_items.append(
                        f"- Q: {item.get('question', '?')}\n  A: {item.get('answer', '?')}"
                    )
                else:
                    formatted_items.append(f"- {item}")
            parts.append(
                "\n\n[이미 확인된 항목 — 절대 다시 질문 금지]\n"
                + "\n".join(formatted_items)
                + "\n\n위 항목과 [이전 대화 기록]에서 사용자가 이미 답변한 사항은 절대 다시 묻지 마세요."
                "\n새로운 정보가 필요한 항목만 질문하세요."
            )

    # 남은 체크리스트 항목 수를 LLM에 알려주어 결론 전환 판단 지원
    remaining = max(0, total_checklist_items - checked_count)
    conclusion_hint = ""
    if checked_count == 0:
        conclusion_hint = " 첫 턴입니다. 정보가 충분하면 결론을 내리세요. 부족하면 조건부 결론 제시 후 핵심 판단 요소를 확인하세요."
    elif remaining == 0:
        conclusion_hint = " 모든 항목 확인 완료. 결론을 내리세요."
    elif remaining <= 2:
        conclusion_hint = f" 핵심 항목 {remaining}개 남음. 현재 정보로 결론 가능하면 내리세요."
    parts.append(
        f"\n\n[진행 상황] 체크리스트 {total_checklist_items}개 중 {checked_count}개 확인 완료, "
        f"남은 항목: {remaining}개.{conclusion_hint}"
    )

    return "\n".join(parts)

# app/test/model_comparison/agents_nonreasoning.py
# non-reasoning 모델 전용 테스트 Agent 팩토리
#
# 프로덕션 clarify_agent와의 차이:
#   - output_validator 없음 (selected_branches 미제공 → ModelRetry 폭주 방지)
#   - selected_branches 필드 제거 (non-reasoning 모델에서 안정적 생성 불가)
#   - deps_type 없음 (체크리스트는 user message에 직접 주입)
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from app.agents import GenerateOutput
from app.test.model_comparison.prompts_nonreasoning import (
    CLARIFY_SYSTEM_NONREASONING,
    GENERATE_SYSTEM_NONREASONING,
)


# ── 완화된 ClarifyOutput — selected_branches 제거 ────────────────────────────

class ClarifyOutputNonReasoning(BaseModel):
    """non-reasoning clarify 전용 스키마 — selected_branches 없음."""
    answer: str = Field(description="K-IFRS 1115호 답변 (마크다운)")
    cited_paragraphs: list[str] = Field(
        default_factory=list,
        description='답변에서 인용한 문단 번호 목록. 예: ["문단 B35", "문단 56"]',
    )
    follow_up_questions: list[str] = Field(
        default_factory=list,
        description="TYPE 1: 조건을 좁힐 후속 질문 3개. TYPE 2: 빈 배열",
    )
    is_conclusion: bool = Field(
        default=True,
        description="항상 True. 조건부든 확정이든 결론을 반드시 포함.",
    )


# ── Agent 캐시 — 같은 모델로 반복 생성 방지 ──────────────────────────────────

_clarify_cache: dict[str, Agent] = {}
_generate_cache: dict[str, Agent] = {}


def build_clarify_agent_nr(model, cache_key: str) -> Agent:
    """Non-reasoning clarify agent — validator 없음, 완화된 스키마."""
    if cache_key not in _clarify_cache:
        _clarify_cache[cache_key] = Agent(
            model,
            output_type=ClarifyOutputNonReasoning,
            retries=4,
            system_prompt=CLARIFY_SYSTEM_NONREASONING,
        )
    return _clarify_cache[cache_key]


def build_generate_agent_nr(model, cache_key: str) -> Agent:
    """Non-reasoning generate agent — 기존 GenerateOutput 스키마 재사용."""
    if cache_key not in _generate_cache:
        _generate_cache[cache_key] = Agent(
            model,
            output_type=GenerateOutput,
            retries=4,
            system_prompt=GENERATE_SYSTEM_NONREASONING,
        )
    return _generate_cache[cache_key]

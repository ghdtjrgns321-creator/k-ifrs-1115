# app/agents.py
# PydanticAI Agent 정의 — 듀얼트랙 generate (Gemini Flash high + gpt-4.1-mini calc)
#
# 7개 LLM 호출 포인트를 PydanticAI Agent로 통일합니다:
#   analyze_agent  — 질문 분석/라우팅 (gpt-4.1-mini, structured output)
#   grade_agent    — 문서 품질 평가 (gpt-4.1-mini, structured output)
#   generate_agent — 일반 답변 생성 (Gemini Flash thinking=high, structured output)
#   clarify_agent  — 거래 상황 분석 + 결론 (Gemini Flash thinking=high, 동적 system prompt)
#   rewrite_agent  — 질문 재작성 (gpt-4.1-mini, plain text)
#   hyde_agent     — HyDE 가상 문서 (gpt-4.1-mini, plain text)
#   text_agent     — search_service LLM 키워드 추출용 (gpt-4.1-mini, plain text)
#   calc_fallback  — 계산 질문 폴백 (gpt-4.1-mini, 산술 정확도 100%)
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import settings
from app.prompts import (
    ANALYZE_PROMPT,
    CALC_CLARIFY_SYSTEM,
    CLARIFY_SYSTEM,
    GENERATE_SYSTEM,
)


# ── 모델 팩토리 ────────────────────────────────────────────────────────────────

_openai_provider = OpenAIProvider(api_key=settings.openai_api_key)
_google_provider = GoogleProvider(api_key=settings.google_api_key)


def _front_model() -> OpenAIModel:
    """analyze / grade / rewrite / hyde 용 경량 모델."""
    return OpenAIModel(settings.llm_front_model, provider=_openai_provider)


def _generate_model() -> GoogleModel:
    """generate/clarify 전용 — Gemini Flash (thinking=high)."""
    return GoogleModel(settings.llm_generate_model, provider=_google_provider)


def _calc_model() -> OpenAIModel:
    """계산 질문 폴백 — gpt-4.1-mini (산술 정확도 100%)."""
    return OpenAIModel(settings.llm_calc_model, provider=_openai_provider)


# generate.py에서 import하여 model override에 사용
calc_fallback = _calc_model()


# ── 출력 스키마 ────────────────────────────────────────────────────────────────


class AnalyzeResult(BaseModel):
    routing: str = Field(description="회계 관련이면 'IN', 무관하면 'OUT'")
    standalone_query: str = Field(
        description="재작성된 독립형 질문 (OUT이면 빈 문자열)"
    )
    is_situation: bool = Field(
        default=False, description="구체적 거래 상황 설명이면 True"
    )
    search_keywords: list[str] = Field(
        default_factory=list, description="벡터 DB 검색용 K-IFRS 핵심 키워드 3~5개"
    )
    confusion_point: str = Field(
        default="",
        description="사용자 혼동 원인 (예: '세금계산서 발행 주체'). 없으면 빈 문자열",
    )
    complexity: str = Field(
        default="complex",
        description="simple: 단일 쟁점/조항 직접 인용 가능, complex: 다중 쟁점/Case 분기 필요",
    )
    provided_info: list[str] = Field(
        default_factory=list,
        description="사용자 설명에서 이미 명시된 판단 요소. "
        "예: ['가격결정권: 기업이 보유', '재고위험: 없음']. "
        "is_situation=true일 때만 추출. 명시적 언급만, 추론 금지.",
    )
    needs_calculation: bool = Field(
        default=False,
        description="사용자가 구체적 숫자 계산 결과를 요청하면 true. "
        "판단 원칙/개념/인식 시점을 묻는 질문이면 false. "
        "핵심 구분: '계산해줘/구해줘/산정해주세요/얼마인가요' + 금액 3개 이상 = true, "
        "'~하나요/뭐야/어떻게/원칙이 적용되나요' = false. "
        "'산정하면 어떤 원칙이?' = false (원칙을 묻는 것), '산정해주세요' = true (결과를 요구)",
    )
    topic_hints: list[str] = Field(
        default_factory=list,
        description="질문의 거래 구조상 쟁점이 되는 K-IFRS 1115호 토픽. "
        "반드시 [토픽 목록]에서만 선택, 최대 3개. "
        "키워드가 직접 언급되지 않아도 거래 실질상 해당 토픽이 쟁점이면 포함. "
        "예: 재판매 구조 → '본인 vs 대리인', 소프트웨어 라이선스 → '라이선싱'",
    )


class DocGrade(BaseModel):
    chunk_id: str = Field(description="평가한 문서의 chunk_id")
    is_relevant: bool = Field(
        description="질문에 대한 답변으로 유효한지 여부 (True/False)"
    )


class GradeResult(BaseModel):
    results: list[DocGrade]


class GenerateOutput(BaseModel):
    answer: str = Field(description="K-IFRS 1115호 답변 (마크다운)")
    cited_paragraphs: list[str] = Field(
        default_factory=list,
        description='답변에서 인용한 문단 번호 목록. 예: ["문단 46", "문단 B58"]',
    )
    follow_up_questions: list[str] = Field(
        description="실무 담당자를 위한 핵심 후속 질문 3개"
    )
    is_conclusion: bool = Field(
        default=False,
        description="충분한 정보가 모여 최종 결론을 포함한 답변이면 True",
    )


class ClarifyOutput(BaseModel):
    """clarify_agent 전용 — 분기 선택 + 인용을 구조적으로 강제."""

    selected_branches: list[str] = Field(
        description="[결론 가이드]에서 선택한 분기 라벨. "
        "TYPE 1(조건부)이면 해당 모든 분기, TYPE 2(확정)이면 확정 1개. "
        '예: ["[분기 1] 5가지 요건 모두 충족 → IFRS 1115호 적용 (문단 9)"]',
    )
    answer: str = Field(
        description="K-IFRS 1115호 답변 (마크다운). output_contract의 TYPE 1 또는 TYPE 2 형식.",
    )
    cited_paragraphs: list[str] = Field(
        description='답변에서 인용한 K-IFRS 1115호 문단 번호 목록. 예: ["문단 B35", "문단 56"]',
    )
    follow_up_questions: list[str] = Field(
        default_factory=list,
        description="TYPE 1: 조건을 좁힐 후속 질문 3개. TYPE 2: 빈 배열",
    )
    is_conclusion: bool = Field(
        default=True,
        description="항상 True. 조건부든 확정이든 결론을 반드시 포함.",
    )


class CalcClarifyOutput(BaseModel):
    """calc_clarify_agent 전용 — selected_branches 없음, validator 없음.

    Why: gpt-4.1-mini(non-reasoning)는 selected_branches를 안정적으로 생성하지 못하고,
    output_validator의 ModelRetry가 산술 정확도를 떨어뜨림.
    """

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


# ── 의존성 (clarify_agent 동적 system prompt 주입용) ────────────────────────────


@dataclass
class ClarifyDeps:
    """clarify_agent에 런타임으로 주입되는 의존성."""

    matched_topics: list[dict] = field(default_factory=list)
    checklist_state: dict | None = None
    provided_info: list[str] = field(default_factory=list)
    # 사용자 원문 메시지 — critical_factors 매칭 범위 확대용
    # Why: C1 — checked_items만으로는 사용자가 이미 답변한 factor를 놓치는 문제
    messages: list[tuple[str, str]] = field(default_factory=list)


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
    # Gemini Flash thinking=medium: A/B 테스트 결과 high 대비 일관성 대폭 향상
    # Why: high에서 thinking이 과도하여 불필요한 분기 생성 → 꼬리질문 비결정성 유발
    # 결과: 꼬리질문 일관성 60%→100%, 토픽 매칭 안정화, 품질 손실 없음
    model_settings={"google_thinking_config": {"thinking_level": "medium"}},
)

clarify_agent = Agent(
    _generate_model(),  # Gemini Flash: 거래 상황 분석은 thinking 필수
    output_type=ClarifyOutput,
    retries=2,
    deps_type=ClarifyDeps,
    # Gemini Flash thinking=medium (A/B 테스트 결과 high 대비 일관성 우수)
    model_settings={"google_thinking_config": {"thinking_level": "medium"}},
)

# Why: gpt-4.1-mini 전용. selected_branches 불필요, validator 없음, non-reasoning 프롬프트.
# 프로덕션 clarify_agent는 Gemini thinking용이라 calc 모델에서 포맷 FAIL + 재시도 폭주.
calc_clarify_agent = Agent(
    _calc_model(),
    output_type=CalcClarifyOutput,
    retries=4,
    system_prompt=CALC_CLARIFY_SYSTEM,
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


# ── clarify_agent result_validator — 빈 인용/빈 분기 reject ──────────────────


@clarify_agent.output_validator
async def _validate_clarify(
    ctx: RunContext[ClarifyDeps], result: ClarifyOutput
) -> ClarifyOutput:
    """빈 인용/빈 분기를 reject + 양방향 분기 TYPE 2 단정 방지 → ModelRetry."""
    errors = []
    if not result.cited_paragraphs:
        errors.append(
            "cited_paragraphs가 비어있습니다. 답변의 근거 문단 번호를 반드시 포함하세요."
        )
    if not result.selected_branches:
        errors.append(
            "selected_branches가 비어있습니다. [결론 가이드]에서 선택한 분기를 반드시 포함하세요."
        )

    # 양방향 분기 TYPE 2 단정 방지:
    # critical_factors가 있는 토픽에서 selected_branches가 1개(TYPE 2)인데
    # checklist_state에 해당 factor 확인 이력이 없으면 reject
    if len(result.selected_branches) == 1 and ctx.deps.matched_topics:
        checked_text = ""
        # 사용자 원문 메시지 포함 — 이미 답변한 factor를 놓치지 않도록
        # Why: C1 — "재고위험도 저희가 부담"이라고 답했으나 checked_items에 없어 미확인 판정
        for role, content in (ctx.deps.messages or []):
            if role == "human":
                checked_text += " " + content
        if ctx.deps.checklist_state:
            items = ctx.deps.checklist_state.get("checked_items", [])
            for i in items:
                if isinstance(i, dict):
                    checked_text += (
                        " " + i.get("question", "") + " " + i.get("answer", "")
                    )
                else:
                    checked_text += " " + str(i)
        # provided_info도 확인 이력으로 간주
        provided = getattr(ctx.deps, "provided_info", []) or []
        checked_text += " " + " ".join(provided)

        for topic in ctx.deps.matched_topics:
            factors = topic.get("critical_factors", [])
            if not factors:
                continue
            # factor 키워드가 checked_text에 하나라도 포함되지 않으면 미확인
            unconfirmed = [f for f in factors if not _factor_in_text(f, checked_text)]
            if unconfirmed:
                errors.append(
                    f"TYPE 2(확정 결론)를 선택했지만 다음 핵심 판단 요소가 아직 확인되지 않았습니다: "
                    f"{'; '.join(unconfirmed)}. TYPE 1(조건부 결론)으로 변경하세요."
                )
                break

    # concluded 상태에서 follow_up 강제 클리어 (방어적 보강)
    # Why: C2 — validator 단계에서도 concluded 후 follow_up 누수 차단
    if ctx.deps.checklist_state and ctx.deps.checklist_state.get("concluded", False):
        result.follow_up_questions = []

    if errors:
        raise ModelRetry("\n".join(errors))
    return result


def _factor_in_text(factor: str, text: str) -> bool:
    """critical_factor 문자열의 핵심 키워드가 text에 포함되는지 판단.

    Why: factor는 "가격결정권 보유 여부 (문단 B37⑴)" 같은 형태.
    괄호 앞의 핵심 키워드로 매칭한다.
    """
    # 괄호 이전 부분에서 핵심 키워드 추출
    core = factor.split("(")[0].strip()
    # "여부", "유무" 등 판단 접미사 제거 — 매칭 정확도 향상
    # Why: C1 — "재고위험 여부"의 "여부"가 text에 없어 매칭 실패
    _JUDGMENT_SUFFIXES = {"여부", "유무", "가능성", "해당"}
    keywords = [w for w in core.split() if len(w) >= 2 and w not in _JUDGMENT_SUFFIXES]
    # 키워드 중 절반 이상이 text에 있으면 확인된 것으로 간주
    if not keywords:
        return True
    matched = sum(1 for kw in keywords if kw in text)
    return matched >= max(1, len(keywords) // 2)


# ── provided_info → 체크리스트 직접 반영 ──────────────────────────────────────
# Why: provided_info가 체크리스트와 분리되면 LLM이 체크리스트를 그대로 따라가며
# 사용자가 이미 명시한 팩트를 재질문하는 문제 발생


def _mark_provided_in_checklist(checklist_text: str, provided_info: list[str]) -> str:
    """provided_info와 매칭되는 체크리스트 번호 라인에 ✅ 표시를 추가합니다.

    매칭 알고리즘 (보수적):
    - provided_info의 ':'앞 키워드 추출 (예: "통제권: 사용자 보유" → "통제권")
    - 3글자 이상 키워드만 매칭 대상 (오탐 방지)
    - 체크리스트 번호 라인(숫자로 시작)만 매칭 대상 (제목/가이드 제외)
    """
    if not provided_info:
        return checklist_text

    # provided_info에서 키워드 추출: ":" 앞 부분, 3글자 이상
    keywords: list[tuple[str, str]] = []  # (keyword, 원본 info)
    for info in provided_info:
        key_part = info.split(":")[0].strip() if ":" in info else info.strip()
        # 공백으로 분리된 개별 단어도 매칭 대상
        for word in key_part.split():
            if len(word) >= 3:
                keywords.append((word, info))

    if not keywords:
        return checklist_text

    lines = checklist_text.split("\n")
    result = []
    for line in lines:
        stripped = line.strip()
        # 숫자로 시작하는 라인만 매칭 대상 (체크리스트 항목)
        if stripped and stripped[0].isdigit():
            for kw, info in keywords:
                if kw in stripped and "✅" not in line:
                    line = f"✅ [사용자 확인 완료] {stripped} → 사용자: '{info}'"
                    break
        result.append(line)
    return "\n".join(result)


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
            # provided_info 매칭 항목에 ✅ 표시 → LLM이 재질문하지 않도록
            marked_text = _mark_provided_in_checklist(
                topic["checklist_text"], ctx.deps.provided_info
            )
            guide_lines.append(marked_text)
            total_checklist_items += len(topic.get("checklist", []))
        parts.append("\n\n".join(guide_lines))

        # 양방향 분기 안전장치 — critical_factors가 있는 토픽에서
        # 핵심 판단 요소가 미확인이면 TYPE 2(확정 결론)를 금지
        cf_lines: list[str] = []
        for topic in ctx.deps.matched_topics:
            factors = topic.get("critical_factors", [])
            if factors:
                cf_lines.append(f"  [{topic.get('topic_name', '')}]")
                cf_lines.extend(f"  - {f}" for f in factors)
        if cf_lines:
            parts.append(
                "\n\n[양방향 분기 안전장치]\n"
                "이 토픽의 결론은 다음 핵심 판단 요소에 따라 갈립니다:\n"
                + "\n".join(cf_lines)
                + "\n위 항목 중 하나라도 사용자 설명에서 명시적으로 확인되지 않았다면 "
                "반드시 TYPE 1(조건부 결론)을 사용하세요."
            )

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

    # provided_info: analyze가 추출한 "이미 명시된 판단 요소"
    # Why: 충분 정보 질문에서 불필요 꼬리질문을 방지
    if ctx.deps.provided_info:
        info_lines = [f"- {info}" for info in ctx.deps.provided_info]
        parts.append(
            "\n\n[사용자 설명에서 이미 확인된 정보 — 다시 질문 금지]\n"
            + "\n".join(info_lines)
            + "\n위 정보는 사용자가 이미 명시적으로 제공했으므로 "
            "이 항목에 대해 다시 질문하지 마세요."
        )

    # 이전 턴에서 이미 결론을 도출한 경우 → 결론 확인 모드
    # Why: C2처럼 T2에서 "접근권 → 기간에 걸쳐 인식" 결론 후
    # T3에서 불필요한 로열티/MG 질문을 생성하는 문제 방지
    already_concluded = False
    if ctx.deps.checklist_state:
        already_concluded = ctx.deps.checklist_state.get("concluded", False)

    if already_concluded:
        parts.append(
            "\n\n[⚠️ 결론 확인 모드]\n"
            "이전 턴에서 이미 결론을 도출했습니다. 추가 확인 질문을 생성하지 마세요.\n"
            "사용자의 새 답변을 반영하여 결론을 확인·보강하고, TYPE 2(확정 결론)로 마무리하세요.\n"
            "follow_up_questions는 반드시 빈 배열([])로 설정하세요."
        )

    # 남은 체크리스트 항목 수를 LLM에 알려주어 결론 전환 판단 지원
    remaining = max(0, total_checklist_items - checked_count)
    conclusion_hint = ""
    if already_concluded:
        conclusion_hint = " 결론 확인 모드: 추가 질문 없이 확정 결론만 제시하세요."
    elif checked_count == 0:
        conclusion_hint = " 첫 턴입니다. 정보가 충분하면 결론을 내리세요. 부족하면 조건부 결론 제시 후 핵심 판단 요소를 확인하세요."
    elif remaining == 0:
        conclusion_hint = " 모든 항목 확인 완료. 결론을 내리세요."
    elif remaining <= 2:
        conclusion_hint = (
            f" 핵심 항목 {remaining}개 남음. 현재 정보로 결론 가능하면 내리세요."
        )
    parts.append(
        f"\n\n[진행 상황] 체크리스트 {total_checklist_items}개 중 {checked_count}개 확인 완료, "
        f"남은 항목: {remaining}개.{conclusion_hint}"
    )

    return "\n".join(parts)

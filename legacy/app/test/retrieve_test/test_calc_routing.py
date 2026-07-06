"""needs_calculation LLM 라우팅 정확도 테스트.

analyze_agent에 needs_calculation 필드를 추가했을 때
gpt-4.1-mini가 "계산 요청 vs 판단 질문"을 얼마나 정확히 구분하는지 검증.

실행: PYTHONPATH=. uv run python app/test/test_calc_routing.py
"""

import asyncio

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import settings

# ── 테스트용 경량 Agent (needs_calculation만 판단) ──────────────────────────────

class CalcRoutingResult(BaseModel):
    needs_calculation: bool = Field(
        description=(
            "사용자가 구체적 숫자 계산 결과를 요청하면 true. "
            "판단 원칙/개념/인식 시점을 묻는 질문이면 false. "
            "판단 기준: '~해줘/구해줘/얼마' + 금액 3개 이상 = true, "
            "'~하나요/뭐야/어떻게' = false"
        ),
    )
    reasoning: str = Field(description="판단 근거 1줄")


_provider = OpenAIProvider(api_key=settings.openai_api_key)
_model = OpenAIModel(settings.llm_front_model, provider=_provider)

test_agent = Agent(
    _model,
    output_type=CalcRoutingResult,
    system_prompt=(
        "K-IFRS 1115호 전문 AI. 사용자 질문이 구체적 숫자 계산을 요청하는지 판단하세요.\n"
        "- 계산 요청: 금액/비율이 여러 개 주어지고 '계산해줘/구해줘/산정해주세요/얼마인가요' 등 "
        "직접적인 계산 결과를 요구하는 질문 → needs_calculation=true\n"
        "- 판단/개념 질문: 원칙이 뭔지, 어떻게 인식하는지, 어떤 기준이 적용되는지 묻는 질문 "
        "→ needs_calculation=false\n"
        "- 핵심 구분: '산정하면 어떤 원칙이 적용되나요?' = false (원칙을 묻는 것), "
        "'산정해주세요' = true (결과를 요구)"
    ),
    model_settings={"temperature": 0.0},
)

# ── 테스트 케이스 ─────────────────────────────────────────────────────────────
# (질문, 정답, 설명)

CASES: list[tuple[str, bool, str]] = [
    # === 명확한 calc (True) ===
    (
        "거래가격이 총 1억 2천만 원이고, 수행의무 A의 개별 판매가격이 6,000만 원, "
        "B가 3,000만 원, C가 1,000만 원입니다. 각 수행의무에 배분할 거래가격을 계산해주세요.",
        True,
        "A3: 명시적 계산 명령 + 금액 4개",
    ),
    (
        "총 계약금액 150억 원, 총 예상원가 100억 원인 건설 계약입니다. "
        "당기까지 누적 발생원가가 60억 원인데, 이 중 20억 원은 외부에서 단순 구매한 "
        "미설치 엘리베이터 원가입니다. 당기 인식할 수익을 구해줘.",
        True,
        "B1: '구해줘' + 금액 4개",
    ),
    (
        "기본 대가 5억 원, 보너스 2억 원(확률 60%), 3억 원(확률 25%), 0원(확률 15%). "
        "기댓값 방법으로 변동대가를 포함한 거래가격을 산정해주세요.",
        True,
        "B2: '산정해주세요' + 금액/확률 다수",
    ),
    (
        "제품 200개를 개당 10만 원에 판매, 원가 개당 6만 원, 반품률 10%(20개). "
        "수익, 환불부채, 반환제품회수권을 각각 계산해줘.",
        True,
        "B3: '계산해줘' + 금액/수량 다수",
    ),
    # === 명확한 non-calc (False) ===
    (
        "K-IFRS 1115호에서 말하는 '변동대가'가 정확히 뭔가요? "
        "기댓값이랑 최빈값 방법의 차이가 궁금해요.",
        False,
        "A1: 개념 질문, 숫자 없음",
    ),
    (
        "저희 회사가 고객사에 장비 100대를 납품하는 계약을 했는데, "
        '계약서에 "납기 지연 시 1대당 5만 원의 위약금" 조항이 있습니다. '
        "이 위약금 조항이 수익 인식에 어떤 영향을 주나요?",
        False,
        "A2: 거래 상황이지만 판단 질문 (영향을 묻는 것)",
    ),
    (
        "건설 계약에서 총 공사예정원가가 200억 원이고, 이번 달까지 누적 발생원가가 "
        "80억 원입니다. 30억 원짜리 고가 장비를 아직 설치 안 했는데, "
        "이런 경우에 진행률을 산정하면 어떤 원칙이 적용되나요?",
        False,
        "A4: '원칙이 적용되나요' = 판단 질문 (금액 3개 있지만 계산 요청 아님)",
    ),
    (
        "본인과 대리인 구분 기준이 뭔가요?",
        False,
        "순수 개념 질문",
    ),
    # === 에지케이스 ===
    (
        "매출 100억 원, 매출원가 60억 원, 판관비 20억 원인데 영업이익이 얼마인가요?",
        True,
        "에지: '얼마인가요' + 금액 3개 → calc (단순 산술)",
    ),
    (
        "계약금 50억, 중도금 30억, 잔금 20억인 분양 계약에서 수익 인식 시점은 언제인가요?",
        False,
        "에지: 금액 3개 있지만 '시점은 언제' = 판단 질문",
    ),
    (
        "거래가격 배분 방법을 알려줘",
        False,
        "에지: '알려줘'는 설명 요청이지 계산 요청이 아님",
    ),
    (
        "라이선스 수익 50억을 5년에 걸쳐 인식하면 연간 얼마인가요?",
        True,
        "에지: '얼마인가요' + 금액 + 기간 → 단순 계산",
    ),
    (
        "고객에게 상품권 1만 원짜리 100장을 판매했고, 과거 경험상 사용률은 80%입니다. "
        "비행사 부채를 산출해주세요.",
        True,
        "에지: '산출해주세요' + 숫자들 → calc",
    ),
    (
        "변동대가 추정 시 기댓값법과 최빈값법 중 어떤 게 더 적합한가요?",
        False,
        "에지: 방법론 비교 질문",
    ),
]

RUNS = 3  # 일관성 확인용


async def main():
    print("=" * 70)
    print(f"needs_calculation LLM 라우팅 정확도 테스트 ({len(CASES)}개 × {RUNS}회)")
    print("=" * 70)

    results: list[dict] = []

    for i, (question, expected, desc) in enumerate(CASES, 1):
        correct_count = 0
        predictions = []

        for run in range(1, RUNS + 1):
            result = await test_agent.run(f"질문: {question}")
            pred = result.output.needs_calculation
            predictions.append(pred)
            if pred == expected:
                correct_count += 1

        consistency = len(set(predictions)) == 1
        all_correct = correct_count == RUNS
        status = "PASS" if all_correct else ("PARTIAL" if correct_count > 0 else "FAIL")

        results.append({
            "id": i,
            "desc": desc,
            "expected": expected,
            "predictions": predictions,
            "correct": correct_count,
            "consistent": consistency,
            "status": status,
        })

        exp_str = "calc" if expected else "non-calc"
        pred_str = "/".join("T" if p else "F" for p in predictions)
        icon = "OK" if all_correct else ("!!" if correct_count == 0 else "??")
        print(f"  [{icon}] {i:2d}. {desc}")
        print(f"       expected={exp_str}, got=[{pred_str}], {correct_count}/{RUNS}")

    # 요약
    total = len(results)
    perfect = sum(1 for r in results if r["status"] == "PASS")
    partial = sum(1 for r in results if r["status"] == "PARTIAL")
    fail = sum(1 for r in results if r["status"] == "FAIL")
    consistent = sum(1 for r in results if r["consistent"])

    print()
    print("=" * 70)
    print(f"결과: PASS {perfect}/{total}, PARTIAL {partial}/{total}, FAIL {fail}/{total}")
    print(f"일관성 (3회 동일): {consistent}/{total} ({consistent/total*100:.0f}%)")
    print(f"정확도: {sum(r['correct'] for r in results)}/{total * RUNS} "
          f"({sum(r['correct'] for r in results) / (total * RUNS) * 100:.1f}%)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

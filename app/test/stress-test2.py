# app/test/stress-test2.py
# K-IFRS 1115 챗봇 스트레스 테스트 2 (6개 섹션 / 12개 케이스)
# 실행: uv run app/test/stress-test2.py
#
# 각 섹션이 검증하는 영역:
#   Section 1 (Bundled)    → 복합 수행의무: 묶음 판매 시 거래가격 배분 능력
#   Section 2 (Variable)   → 변동대가: 반품·보너스 불확실성 추정 기준
#   Section 3 (Principal)  → 본인 vs 대리인: 통제권·신용위험 구분
#   Section 4 (License)    → 라이선스·프랜차이즈: 접근권 vs 사용권
#   Section 5 (EdgeCase)   → 계약변경·비현금 대가 엣지 케이스
#   Section 6 (AdvSlang)   → 구어체 고급: 보증 유형·고객충성제도
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path

# HyDE + rewrite 양쪽 폴백이 발동되는 최악 경로 커버 (HyDE 15s + o4-mini 90s + 기타 ~30s)
CASE_TIMEOUT_SEC = 150

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from app.graph import rag_graph  # noqa: E402
from app.config import settings  # noqa: E402
from openai import OpenAI        # noqa: E402


# ── 공통 헬퍼 (stress-test.py와 동일) ────────────────────────────────────────

def p(*args, **kwargs):
    kwargs.setdefault("flush", True)
    print(*args, **kwargs)

def sep(char="═", n=62):
    p(char * n)

def sep2(char="─", n=62):
    p(char * n)

def _invoke(messages: list) -> dict:
    return rag_graph.invoke({
        "messages":         messages,
        "routing":          "",
        "standalone_query": "",
        "retry_count":      0,
        "retrieved_docs":   [],
        "reranked_docs":    [],
        "relevant_docs":    [],
        "answer":           "",
        "cited_sources":    [],
        "findings_case":    None,
    })

def _check(label: str, condition: bool, detail: str = "") -> bool:
    icon = "  ✅" if condition else "  ❌"
    p(f"{icon} {label}" + (f"  ({detail})" if detail else ""))
    return condition

_judge_client: OpenAI | None = None

def _get_judge_client() -> OpenAI:
    global _judge_client
    if _judge_client is None:
        _judge_client = OpenAI(api_key=settings.openai_api_key)
    return _judge_client

def _judge_semantic(text: str, criteria: str) -> tuple[bool, str]:
    response = _get_judge_client().chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 테스트 채점관입니다. "
                    "아래 [평가 기준]에 따라 [평가 대상]을 판정하세요.\n"
                    "반드시 JSON으로만 응답하세요: "
                    '{\"pass\": true 또는 false, \"reason\": \"1줄 근거\"}'
                ),
            },
            {
                "role": "user",
                "content": f"[평가 기준]\n{criteria}\n\n[평가 대상]\n{text}",
            },
        ],
    )
    result = json.loads(response.choices[0].message.content)
    return bool(result.get("pass", False)), result.get("reason", "")

def _run_case(label: str, messages: list, checks_fn) -> bool:
    question_preview = messages[-1][1]
    p(f"\n  🔹 {label}")
    p(f"     Q: {question_preview[:80]}{'...' if len(question_preview) > 80 else ''}")
    p("     ⏳ 실행 중...", end=" ")
    t0 = time.time()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_invoke, messages)
            result = future.result(timeout=CASE_TIMEOUT_SEC)
    except FuturesTimeoutError:
        elapsed = time.time() - t0
        p(f"\n     ⏰ 타임아웃 ({elapsed:.0f}초 / 허용: {CASE_TIMEOUT_SEC}초)")
        return False
    except Exception as e:
        p(f"\n     ❌ 오류: {type(e).__name__}: {e}")
        return False
    elapsed = time.time() - t0
    p(f"완료 ({elapsed:.1f}초)")

    routing  = result.get("routing", "?")
    sq       = result.get("standalone_query", "")
    answer   = result.get("answer", "")
    r_docs   = result.get("retrieved_docs", [])
    rr_docs  = result.get("reranked_docs", [])
    rel_docs = result.get("relevant_docs", [])

    p(f"     🔀 라우팅: {routing}")
    if sq:
        p(f"     📝 독립형: {sq[:70]}{'...' if len(sq) > 70 else ''}")
    p(f"     📦 retrieve {len(r_docs)}개 → rerank {len(rr_docs)}개 → grade {len(rel_docs)}개")
    p(f"     💬 답변 앞 120자: {answer[:120].replace(chr(10), ' ')}")

    passed = checks_fn(result, routing, sq, answer)
    p(f"     {'─ PASS ✅' if passed else '─ FAIL ❌'}")
    return passed


# ══════════════════════════════════════════════════════════════════════════════
# Section 1: Bundled Services Test (복합 수행의무)
# 검증: 묶음 판매에서 수행의무 식별 및 거래가격 배분 원칙을 안내하는지
# ══════════════════════════════════════════════════════════════════════════════

BUNDLED_CASES = [
    (
        "스마트폰 + 2년 통신 약정 → 거래가격 배분",
        "스마트폰 기기를 팔면서 2년 통신 약정을 같이 묶어서 팔았어요. "
        "기기값은 대폭 할인해줬는데, 이때 통신 수익과 기기 매출을 어떻게 배분해서 인식해야 하나요?",
        "답변이 거래가격을 개별 판매가격의 상대적 비율(relative standalone selling price)로 "
        "수행의무별로 배분해야 한다는 원칙을 설명하고 있으며, "
        "할인액도 수행의무별로 배분된다는 내용을 포함하고 있는가?",
    ),
    (
        "기계장치 + 전담 설치 용역 → 구별 가능 여부 (문단 27)",
        "기계장치를 판매하면서 설치 용역을 무상으로 제공하기로 했습니다. "
        "근데 이 설치가 너무 복잡해서 우리 회사 엔지니어만 할 수 있다면, "
        "기계 인도 시점에 수익을 다 잡아도 되나요?",
        "답변이 설치 용역이 '구별되는 수행의무'인지를 판단해야 한다고 설명하며, "
        "설치 없이 기계장치만으로 고객이 효익을 얻을 수 없다면 "
        "두 약속이 단일 수행의무가 될 수 있다는 내용을 포함하고 있는가?",
    ),
]


def run_section1() -> int:
    sep()
    p("  Section 1 | Bundled Services Test (복합 수행의무)")
    p("  검증: 묶음 판매 → 수행의무 식별 + 거래가격 배분 원칙 안내")
    sep()
    passed = 0
    failed = []
    for label, question, judge_criteria in BUNDLED_CASES:
        def checks(result, routing, sq, answer, _criteria=judge_criteria):
            ok = True
            ok &= _check("라우팅 IN", routing == "IN", routing)
            rel = result.get("relevant_docs", [])
            ok &= _check("관련 문서 1개 이상 통과", len(rel) > 0, f"{len(rel)}개")
            judge_pass, reason = _judge_semantic(answer, _criteria)
            ok &= _check("답변 품질 (LLM Judge)", judge_pass, reason)
            return ok
        if _run_case(label, [("human", question)], checks):
            passed += 1
        else:
            failed.append(label)
    sep2()
    p(f"  Section 1 결과: {passed}/{len(BUNDLED_CASES)}")
    if failed:
        p(f"  ❌ 실패 케이스: {', '.join(failed)}")
    return passed


# ══════════════════════════════════════════════════════════════════════════════
# Section 2: Variable Consideration Test (변동대가)
# 검증: 반품·보너스 불확실성에서 변동대가 추정 제약과 방법 선택 기준을 안내하는지
# ══════════════════════════════════════════════════════════════════════════════

VARIABLE_CASES = [
    (
        "신제품 100% 반품 허용 + 과거 데이터 없음 → 수익 인식 제약 (문단 56)",
        "신제품을 처음 출시하면서 대리점에 반품을 100% 받아주기로 했습니다. "
        "시장 반응을 몰라서 과거 반품 데이터가 전혀 없는데, 출고 시점에 수익을 인식해도 될까요?",
        "답변이 변동대가(반품에 따른 불확실성)의 추정치가 '높은 확률로 유의적인 수익 환입이 "
        "발생하지 않는 범위'까지만 수익으로 인식해야 한다는 제약 원칙을 설명하며, "
        "과거 데이터 없는 상황에서 수익 인식을 보류하거나 제한해야 한다는 결론을 담고 있는가?",
    ),
    (
        "건설 계약 조기완공 보너스 + 지연 페널티 → 기댓값 vs 최빈값 선택",
        "건설 계약인데, 조기 완공하면 보너스를 받고 지연되면 페널티를 물어야 해요. "
        "완공일이 날씨 때문에 불확실한데 변동대가를 기댓값으로 추정해야 하나요, "
        "아니면 가능성이 가장 높은 금액으로 해야 하나요?",
        "답변이 변동대가 추정 방법으로 '기댓값'과 '가능성이 가장 높은 금액(최빈값)' 두 가지를 "
        "소개하고, 가능한 결과치의 수가 많으면 기댓값이 적절하다는 선택 기준을 설명하고 있는가?",
    ),
]


def run_section2() -> int:
    sep()
    p("  Section 2 | Variable Consideration Test (변동대가)")
    p("  검증: 반품·보너스 불확실성 → 변동대가 추정 제약 + 방법 선택 기준 안내")
    sep()
    passed = 0
    failed = []
    for label, question, judge_criteria in VARIABLE_CASES:
        def checks(result, routing, sq, answer, _criteria=judge_criteria):
            ok = True
            ok &= _check("라우팅 IN", routing == "IN", routing)
            rel = result.get("relevant_docs", [])
            ok &= _check("관련 문서 1개 이상 통과", len(rel) > 0, f"{len(rel)}개")
            judge_pass, reason = _judge_semantic(answer, _criteria)
            ok &= _check("답변 품질 (LLM Judge)", judge_pass, reason)
            return ok
        if _run_case(label, [("human", question)], checks):
            passed += 1
        else:
            failed.append(label)
    sep2()
    p(f"  Section 2 결과: {passed}/{len(VARIABLE_CASES)}")
    if failed:
        p(f"  ❌ 실패 케이스: {', '.join(failed)}")
    return passed


# ══════════════════════════════════════════════════════════════════════════════
# Section 3: Principal vs. Agent Test (본인 대 대리인)
# 검증: 통제권(문단 B34)과 신용위험 부담(문단 B37)으로 본인/대리인을 판단하는지
# ══════════════════════════════════════════════════════════════════════════════

PRINCIPAL_CASES = [
    (
        "배달 앱 플랫폼 → 총액 vs 순액 (통제권 기준 B34)",
        "배달 앱 플랫폼입니다. 음식값과 배달비를 고객에게 한 번에 결제받고, "
        "음식점과 배달기사에게 정산해줍니다. "
        "우리는 플랫폼 수수료만 매출로 잡아야 하나요, 아니면 전체 결제액을 매출로 잡아야 하나요?",
        "답변이 고객에게 재화나 용역이 이전되기 전에 플랫폼이 해당 재화나 용역을 '통제'하는지를 "
        "기준으로 본인(총액 인식)과 대리인(수수료/순액 인식)을 판단해야 한다고 설명하는가?",
    ),
    (
        "신용위험 부담 → 본인 판단 기준 (문단 B37)",
        "상품의 재고 위험은 우리가 안 지는데, 고객이 돈을 안 낼 위험(신용위험)은 "
        "우리가 전적으로 져요. 그럼 우리가 본인인가요?",
        "답변이 신용위험을 부담한다는 사실만으로는 본인(통제권 보유)으로 볼 수 없으며, "
        "통제권 여부가 핵심 판단 기준임을 명확히 설명하고 있는가?",
    ),
]


def run_section3() -> int:
    sep()
    p("  Section 3 | Principal vs. Agent Test (본인 대 대리인)")
    p("  검증: 플랫폼 구조에서 통제권·신용위험 기준으로 본인/대리인 판단")
    sep()
    passed = 0
    failed = []
    for label, question, judge_criteria in PRINCIPAL_CASES:
        def checks(result, routing, sq, answer, _criteria=judge_criteria):
            ok = True
            ok &= _check("라우팅 IN", routing == "IN", routing)
            rel = result.get("relevant_docs", [])
            ok &= _check("관련 문서 1개 이상 통과", len(rel) > 0, f"{len(rel)}개")
            judge_pass, reason = _judge_semantic(answer, _criteria)
            ok &= _check("답변 품질 (LLM Judge)", judge_pass, reason)
            return ok
        if _run_case(label, [("human", question)], checks):
            passed += 1
        else:
            failed.append(label)
    sep2()
    p(f"  Section 3 결과: {passed}/{len(PRINCIPAL_CASES)}")
    if failed:
        p(f"  ❌ 실패 케이스: {', '.join(failed)}")
    return passed


# ══════════════════════════════════════════════════════════════════════════════
# Section 4: License & Franchise Test (라이선스·프랜차이즈)
# 검증: 접근권(기간 인식) vs 사용권(시점 인식) 구분, 프랜차이즈 가맹비 처리
# ══════════════════════════════════════════════════════════════════════════════

LICENSE_CASES = [
    (
        "프랜차이즈 가맹비 일시 수령 → 기간 인식 여부",
        "프랜차이즈 본사인데, 가맹점 계약할 때 가맹비 5천만 원을 한 번에 받았습니다. "
        "간판 달아주고 매뉴얼 교육해주는 의무가 있는데, 이 가맹비 수익은 언제 인식하나요?",
        "답변이 프랜차이즈 권리 제공이 '접근권'인지, 또는 별도 수행의무(간판, 교육)와 함께 "
        "묶인 것인지를 분석하며, 기간에 걸쳐 수익을 인식해야 할 가능성을 설명하고 있는가?",
    ),
    (
        "보안 SW 3년 라이선스 + 매일 업데이트 → 접근권 (문단 B58)",
        "보안 소프트웨어 라이선스를 3년간 부여했습니다. "
        "보안 특성상 우리가 매일 최신 바이러스 패턴으로 업데이트를 해줘야 하는데, "
        "이 라이선스는 한 시점에 수익을 잡나요, 기간에 걸쳐 잡나요?",
        "답변이 기업의 활동(지속적 업데이트)이 지적재산에 유의적인 영향을 미치므로 "
        "'접근권'으로 분류되어 기간에 걸쳐 수익을 인식해야 한다는 결론을 포함하고 있는가?",
    ),
]


def run_section4() -> int:
    sep()
    p("  Section 4 | License & Franchise Test (라이선스·프랜차이즈)")
    p("  검증: 접근권(기간) vs 사용권(시점) + 프랜차이즈 가맹비 처리 안내")
    sep()
    passed = 0
    failed = []
    for label, question, judge_criteria in LICENSE_CASES:
        def checks(result, routing, sq, answer, _criteria=judge_criteria):
            ok = True
            ok &= _check("라우팅 IN", routing == "IN", routing)
            rel = result.get("relevant_docs", [])
            ok &= _check("관련 문서 1개 이상 통과", len(rel) > 0, f"{len(rel)}개")
            judge_pass, reason = _judge_semantic(answer, _criteria)
            ok &= _check("답변 품질 (LLM Judge)", judge_pass, reason)
            return ok
        if _run_case(label, [("human", question)], checks):
            passed += 1
        else:
            failed.append(label)
    sep2()
    p(f"  Section 4 결과: {passed}/{len(LICENSE_CASES)}")
    if failed:
        p(f"  ❌ 실패 케이스: {', '.join(failed)}")
    return passed


# ══════════════════════════════════════════════════════════════════════════════
# Section 5: Edge Case Test (계약변경·비현금 대가)
# 검증: 계약변경 시 회계처리 방법(문단 21)과 비현금 대가 측정 기준(문단 68)
# ══════════════════════════════════════════════════════════════════════════════

EDGE_CASES = [
    (
        "진행 중 계약변경 + 단가 인하 + 추가 납품 → 새 계약 vs 기존 수정 (문단 21)",
        "100개 제품을 납품하는 계약을 진행 중인데, 50개 납품한 상태에서 "
        "단가를 깎아주고 50개를 추가로 납품하기로 계약을 바꿨습니다. "
        "이거 기존 계약의 수정인가요, 새로운 계약인가요?",
        "답변이 추가되는 재화가 구별되더라도 가격이 개별 판매가격을 반영하지 않으므로 "
        "기존 계약을 종료하고 새로운 계약을 체결한 것으로 회계처리해야 한다는 내용, "
        "또는 계약변경의 세 가지 회계처리 방법 중 어느 것을 적용할지를 설명하고 있는가?",
    ),
    (
        "고객이 주식으로 결제 → 비현금 대가 공정가치 측정 기준일 (문단 68)",
        "고객이 돈 대신 자기네 회사 주식으로 결제한대요. "
        "근데 계약 시점 주가랑 실제 주식 받을 때 주가가 다르면, "
        "거래가격은 언제를 기준으로 측정해요?",
        "답변이 비현금 대가의 공정가치는 '계약 개시일'을 기준으로 측정하며, "
        "그 이후의 공정가치 변동은 거래가격에 반영하지 않는다는 원칙을 설명하고 있는가?",
    ),
]


def run_section5() -> int:
    sep()
    p("  Section 5 | Edge Case Test (계약변경·비현금 대가)")
    p("  검증: 계약변경 회계처리 방법 + 비현금 대가 기준일 측정")
    sep()
    passed = 0
    failed = []
    for label, question, judge_criteria in EDGE_CASES:
        def checks(result, routing, sq, answer, _criteria=judge_criteria):
            ok = True
            ok &= _check("라우팅 IN", routing == "IN", routing)
            rel = result.get("relevant_docs", [])
            ok &= _check("관련 문서 1개 이상 통과", len(rel) > 0, f"{len(rel)}개")
            judge_pass, reason = _judge_semantic(answer, _criteria)
            ok &= _check("답변 품질 (LLM Judge)", judge_pass, reason)
            return ok
        if _run_case(label, [("human", question)], checks):
            passed += 1
        else:
            failed.append(label)
    sep2()
    p(f"  Section 5 결과: {passed}/{len(EDGE_CASES)}")
    if failed:
        p(f"  ❌ 실패 케이스: {', '.join(failed)}")
    return passed


# ══════════════════════════════════════════════════════════════════════════════
# Section 6: Advanced Slang Test (구어체 고급)
# 검증: 보증 유형 구분(확신 vs 용역) + 고객충성제도 별도 수행의무 인식
# ══════════════════════════════════════════════════════════════════════════════

ADV_SLANG_CASES = [
    (
        "기본 AS + 유상 연장 보증 → 확신유형 vs 용역유형 구분",
        "물건 팔고 1년짜리 기본 AS 말고, 돈 더 내면 3년으로 연장해주는 거 팔았는데 "
        "이거 수익 매출이랑 같이 잡아도 됨?",
        "답변이 기본 AS(확신유형 보증)와 유상 연장 AS(용역유형 보증)를 구분하여, "
        "연장 보증은 별도의 수행의무로 보아 수익을 이연해야 한다는 내용을 설명하고 있는가?",
    ),
    (
        "백화점 상품권 끼워주기 → 고객충성제도 별도 수행의무 이연",
        "물건 팔면서 우리 백화점 상품권 얹어줬는데, "
        "이거 어차피 공짜로 준 거니까 매출에서 안 까고 다 수익 잡아도 되지?",
        "답변이 고객에게 중요한 권리(상품권)를 제공하는 것이 별도의 수행의무에 해당하며, "
        "거래가격 일부를 이 수행의무에 배분하여 이연해야 한다는 원칙을 설명하고 있는가?",
    ),
]


def run_section6() -> int:
    sep()
    p("  Section 6 | Advanced Slang Test (구어체 고급)")
    p("  검증: 보증 유형 구분(확신 vs 용역) + 고객충성제도 수익 이연 안내")
    sep()
    passed = 0
    failed = []
    for label, question, judge_criteria in ADV_SLANG_CASES:
        def checks(result, routing, sq, answer, _criteria=judge_criteria):
            ok = True
            ok &= _check("라우팅 IN", routing == "IN", routing)
            rel = result.get("relevant_docs", [])
            ok &= _check("관련 문서 1개 이상 통과", len(rel) > 0, f"{len(rel)}개")
            judge_pass, reason = _judge_semantic(answer, _criteria)
            ok &= _check("답변 품질 (LLM Judge)", judge_pass, reason)
            return ok
        if _run_case(label, [("human", question)], checks):
            passed += 1
        else:
            failed.append(label)
    sep2()
    p(f"  Section 6 결과: {passed}/{len(ADV_SLANG_CASES)}")
    if failed:
        p(f"  ❌ 실패 케이스: {', '.join(failed)}")
    return passed


# ══════════════════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════════════════

def main():
    total = (
        len(BUNDLED_CASES) + len(VARIABLE_CASES) + len(PRINCIPAL_CASES)
        + len(LICENSE_CASES) + len(EDGE_CASES) + len(ADV_SLANG_CASES)
    )
    sep("═")
    p("  K-IFRS 1115 챗봇 스트레스 테스트 2")
    p(f"  6개 섹션 / {total}개 케이스 — 실전 회계 시나리오 기반 품질 검증")
    sep("═")

    t_start = time.time()

    s1 = run_section1()
    s2 = run_section2()
    s3 = run_section3()
    s4 = run_section4()
    s5 = run_section5()
    s6 = run_section6()

    total_pass = s1 + s2 + s3 + s4 + s5 + s6
    elapsed    = time.time() - t_start

    sep("═")
    p("  최종 결과 요약")
    sep2()
    p(f"  Section 1 Bundled Services  : {s1}/{len(BUNDLED_CASES)}")
    p(f"  Section 2 Variable Consid.  : {s2}/{len(VARIABLE_CASES)}")
    p(f"  Section 3 Principal/Agent   : {s3}/{len(PRINCIPAL_CASES)}")
    p(f"  Section 4 License/Franchise : {s4}/{len(LICENSE_CASES)}")
    p(f"  Section 5 Edge Cases        : {s5}/{len(EDGE_CASES)}")
    p(f"  Section 6 Advanced Slang    : {s6}/{len(ADV_SLANG_CASES)}")
    sep2()
    p(f"  총합: {total_pass}/{total}  (소요: {elapsed:.0f}초)")
    if total_pass == total:
        p("  전체 통과!")
    else:
        p(f"  {total - total_pass}개 실패")
    sep("═")


if __name__ == "__main__":
    main()

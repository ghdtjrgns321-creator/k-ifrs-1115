"""
라우팅 정확도 + 계산 검증 + 멀티턴 흐름 테스트 10선

싱글턴(A1~A4, B1~B3): POST /chat → done 이벤트 1회 수집
멀티턴(C1~C3): session_id 유지하며 연속 호출 → 턴별 done 이벤트 수집

실행:
  1. 서버 기동: uv run uvicorn app.main:app --port 8002
  2. 테스트:    PYTHONPATH=. uv run python app/test/quality_test/run_routing_calc_multiturn_test.py
  3. 리포트만:  PYTHONPATH=. uv run python app/test/quality_test/run_routing_calc_multiturn_test.py report
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

# ── 설정 ────────────────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8002"
RUNS_PER_CASE = 3
RESULTS_DIR = Path(__file__).parent / "results"
# 결과 파일 태그: 환경변수 RESULT_TAG로 오버라이드 가능 (기본값: 빈 문자열)
# 예: RESULT_TAG=_v2 → routing_calc_multiturn_results_v2.json
_TAG = os.environ.get("RESULT_TAG", "")
RESULTS_FILE = RESULTS_DIR / f"routing_calc_multiturn_results{_TAG}.json"
REPORT_FILE = RESULTS_DIR / f"routing_calc_multiturn_report{_TAG}.md"
TIMEOUT = 180  # 멀티턴은 대기 시간이 길 수 있음


# ── 테스트 케이스 정의 ──────────────────────────────────────────────────────────
# type: "single" (단일 호출) 또는 "multi" (멀티턴 — turns 배열)

TEST_CASES: list[dict[str, Any]] = [
    # ─── 섹션 A: 라우팅 분기 정확도 ──────────────────────────────────────────────
    {
        "id": "A1",
        "group": "라우팅 분기 정확도",
        "title": "개념 질문 → generate 경로",
        "type": "single",
        "message": (
            "K-IFRS 1115호에서 말하는 '변동대가'가 정확히 뭔가요? "
            "기댓값이랑 최빈값 방법의 차이가 궁금해요."
        ),
        "criteria": [
            "is_situation=False로 판정 (generate_agent 호출)",
            "변동대가 정의(문단 50~51) + 기댓값/최빈값(문단 53) 설명",
            "불필요한 clarify 질문 미생성",
            "follow_up_questions 3개 포함",
        ],
        "expected_routing": "generate",
    },
    {
        "id": "A2",
        "group": "라우팅 분기 정확도",
        "title": "거래 상황 질문 → clarify 경로",
        "type": "single",
        "message": (
            "저희 회사가 고객사에 장비 100대를 납품하는 계약을 했는데, "
            '계약서에 "납기 지연 시 1대당 5만 원의 위약금을 물어야 한다"는 조항이 있습니다. '
            "이 위약금 조항이 수익 인식에 어떤 영향을 주나요?"
        ),
        "criteria": [
            "is_situation=True로 판정 (clarify_agent 호출)",
            "위약금이 변동대가에 해당함을 지적",
            "확률 추정 관련 꼬리질문 생성",
        ],
        "expected_routing": "clarify",
    },
    {
        "id": "A3",
        "group": "라우팅 분기 정확도",
        "title": "계산 명령 → calc 경로",
        "type": "single",
        "message": (
            "거래가격이 총 1억 2천만 원이고, 수행의무 A의 개별 판매가격이 6,000만 원, "
            "B가 3,000만 원, C가 1,000만 원입니다. "
            "각 수행의무에 배분할 거래가격을 계산해주세요."
        ),
        "criteria": [
            "calc 경로 라우팅 (gpt-4.1-mini)",
            "A=7,200만 원, B=3,600만 원, C=1,200만 원 정확 산출",
            "개별 판매가격 비례 배분 공식(문단 73~74) 인용",
        ],
        "expected_routing": "calc",
        "expected_answer": "A=7200, B=3600, C=1200",
    },
    {
        "id": "A4",
        "group": "라우팅 분기 정확도",
        "title": "계산처럼 보이지만 판단 질문 → calc 아닌 경로",
        "type": "single",
        "message": (
            "건설 계약에서 총 공사예정원가가 200억 원이고, 이번 달까지 누적 발생원가가 "
            "80억 원입니다. 그런데 30억 원짜리 고가 장비를 외부에서 단순 구매해서 현장에 "
            "들여놨는데 아직 설치를 안 했거든요. 이런 경우에 진행률을 산정하면 어떤 원칙이 "
            "적용되나요?"
        ),
        "criteria": [
            "calc 경로로 라우팅되지 않음 (generate 또는 clarify)",
            "미설치 고가 자재 진행률 제외 원칙(문단 B19⑵) 설명",
            "마진 0% 적용 원칙(IE 사례 19) 언급",
        ],
        "expected_routing": "not_calc",
    },
    # ─── 섹션 B: 계산 정확도 ─────────────────────────────────────────────────────
    {
        "id": "B1",
        "group": "계산 정확도",
        "title": "진행률 측정 — 미설치 고가 자재 제외",
        "type": "single",
        "message": (
            "총 계약금액(거래가격) 150억 원, 총 예상원가 100억 원인 건설 계약입니다. "
            "당기까지 누적 발생원가가 60억 원인데, 이 중 20억 원은 외부에서 단순 구매한 "
            "미설치 엘리베이터 원가입니다. 당기 인식할 수익을 구해줘."
        ),
        "criteria": [
            "미설치 자재를 진행률 분자/분모에서 모두 제외",
            "미설치 자재에 마진 0%(원가=수익) 적용",
            "최종 답이 85억 원 (±허용 오차 없음)",
            "문단 B19⑵와 IE 사례 19 인용",
        ],
        "expected_answer": "85억",
    },
    {
        "id": "B2",
        "group": "계산 정확도",
        "title": "변동대가 기댓값 산출",
        "type": "single",
        "message": (
            "고객과 소프트웨어 납품 계약을 체결했습니다. 기본 대가는 5억 원이고, "
            "성과 보너스 조건은 다음과 같습니다:\n"
            "- 납기 1주 단축 시 보너스 2억 원 (발생 확률 60%)\n"
            "- 납기 2주 단축 시 보너스 3억 원 (발생 확률 25%)\n"
            "- 납기 미단축 시 보너스 없음 (발생 확률 15%)\n"
            "기댓값 방법으로 변동대가를 포함한 거래가격을 산정해주세요."
        ),
        "criteria": [
            "기댓값 1.95억 원 정확 산출",
            "거래가격 6.95억 원(제약 적용 전) 제시",
            "변동대가 제약(문단 56~58) 언급",
        ],
        "expected_answer": "6.95억 또는 1.95억",
    },
    {
        "id": "B3",
        "group": "계산 정확도",
        "title": "반품권이 있는 판매 — 환불부채 + 회수권",
        "type": "single",
        "message": (
            "제품 200개를 개당 10만 원에 판매하고 전액 수취했습니다. 제품 원가는 개당 "
            "6만 원입니다. 30일 내 무조건 반품 가능 조건이며, 과거 경험상 반품률은 "
            "10%(20개)로 추정됩니다. 수익, 환불부채, 반환제품회수권을 각각 계산해줘."
        ),
        "criteria": [
            "수익 1,800만 원 정확",
            "환불부채 200만 원 정확",
            "매출원가 1,080만 원 정확",
            "반환제품회수권 120만 원 정확",
            "문단 B21~B27, IE 사례 22 인용",
        ],
        "expected_answer": "수익=1800, 환불부채=200, 원가=1080, 회수권=120",
    },
    # ─── 섹션 C: 멀티턴 대화 시나리오 ────────────────────────────────────────────
    {
        "id": "C1",
        "group": "멀티턴 대화",
        "title": "본인 vs 대리인 — 2턴",
        "type": "multi",
        "turns": [
            {
                "turn": 1,
                "message": (
                    "저희 회사가 해외 유명 브랜드의 화장품을 국내에 독점 유통하고 있습니다. "
                    "브랜드사로부터 제품을 매입해서 국내 백화점과 온라인몰에 판매하는데, "
                    "매출을 총액(전체 판매가)으로 인식하고 있습니다. 이게 맞는 건가요?"
                ),
                "criteria": [
                    "is_situation=True로 판정",
                    "즉시 총액/순액 단정 결론 내리지 않음",
                    "통제 3징후(주된 책임, 재고위험, 가격결정권) 중 적어도 하나 질문",
                ],
            },
            {
                "turn": 2,
                "message": (
                    "네, 저희가 브랜드사한테 제품을 확정 매입하고 재고위험도 저희가 "
                    "부담합니다. 판매가격도 저희가 자체적으로 정하고요. "
                    "반품이 오면 저희가 떠안고 브랜드사에 반품할 수 없습니다."
                ),
                "criteria": [
                    "1턴 정보를 종합하여 최종 결론",
                    "'본인' + '총액 인식 적정' 명확한 판단",
                    "문단 B34~B38 인용",
                ],
            },
        ],
    },
    {
        "id": "C2",
        "group": "멀티턴 대화",
        "title": "라이선싱 접근권 vs 사용권 — 3턴",
        "type": "multi",
        "turns": [
            {
                "turn": 1,
                "message": (
                    "저희 게임 회사가 중국 퍼블리셔에게 자체 개발한 모바일 게임의 IP "
                    "라이선스를 5년간 독점 제공하기로 하고 선급금 50억 원을 받았습니다. "
                    "라이선스 대금이니까 계약 시점에 50억 원 전액을 수익으로 인식하면 되나요?"
                ),
                "criteria": [
                    "is_situation=True로 판정",
                    "선급금에 현혹되어 일시 인식 결론 내리지 않음",
                    "접근권 3요건(문단 B58)의 '유의적 영향 활동' 확인 질문",
                ],
            },
            {
                "turn": 2,
                "message": (
                    "네, 저희가 매달 신규 캐릭터와 시즌 이벤트를 업데이트하고, "
                    "게임 밸런스 패치도 수시로 진행합니다. 퍼블리셔가 운영하는 중국 서버에 "
                    "이 업데이트가 자동으로 반영됩니다."
                ),
                "criteria": [
                    "접근권 가능성 인지",
                    "1턴 Q&A 중복 질문 안 함",
                    "추가 확인 또는 결론 도달",
                ],
            },
            {
                "turn": 3,
                "message": (
                    "네, 저희 업데이트가 게임 매출에 직접적인 영향을 줍니다. "
                    "콘텐츠를 안 넣으면 유저 이탈이 급격하고요."
                ),
                "criteria": [
                    "'접근권 → 기간에 걸쳐 인식' 최종 결론",
                    "B58 3요건 점검 완료",
                    "이전 턴 답변 중복 질문 없음",
                ],
            },
        ],
    },
    {
        "id": "C3",
        "group": "멀티턴 대화",
        "title": "범위 밖 → 정상 복귀 — 2턴",
        "type": "multi",
        "turns": [
            {
                "turn": 1,
                "message": (
                    "리스 부채 할인율 산정할 때 증분차입이자율을 어떻게 구하나요?"
                ),
                "criteria": [
                    "범위 밖(1116호) 안내",
                    "억지로 1115호 답변 만들지 않음",
                ],
            },
            {
                "turn": 2,
                "message": (
                    "그러면 수주계약에서 계약체결 증분원가의 상각기간은 어떻게 결정하나요?"
                ),
                "criteria": [
                    "정상 1115호 답변 제공",
                    "이전 턴 리스 질문이 맥락 오염 안 함",
                    "문단 94, 99 인용",
                ],
            },
        ],
    },
]


# ── 단일 호출 ───────────────────────────────────────────────────────────────────


def call_chat(
    message: str, session_id: str | None = None
) -> tuple[dict[str, Any], float]:
    """POST /chat → (done_event, response_time_sec)."""
    start = time.time()
    done_event: dict[str, Any] | None = None
    error_msg: str | None = None

    payload: dict[str, Any] = {"message": message}
    if session_id:
        payload["session_id"] = session_id

    with httpx.Client(timeout=httpx.Timeout(TIMEOUT, connect=10)) as client:
        with client.stream(
            "POST",
            f"{BASE_URL}/chat",
            json=payload,
            headers={"Accept": "text/event-stream"},
        ) as resp:
            for line in resp.iter_lines():
                line = line.strip()
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "done":
                    done_event = event
                elif event.get("type") == "error":
                    error_msg = event.get("message", "unknown error")

    elapsed = time.time() - start

    if done_event:
        return done_event, elapsed
    if error_msg:
        return {"type": "error", "message": error_msg}, elapsed
    return {"type": "error", "message": "no done event received"}, elapsed


# ── 결과 저장/로드 ──────────────────────────────────────────────────────────────


def load_results() -> list[dict[str, Any]]:
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    return []


def save_results(results: list[dict[str, Any]]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def already_done(results: list[dict[str, Any]], test_id: str, run: int) -> bool:
    return any(r["test_id"] == test_id and r["run"] == run for r in results)


# ── 싱글턴 실행 ─────────────────────────────────────────────────────────────────


def _run_single(case: dict, run: int) -> dict[str, Any]:
    """싱글턴 테스트 실행 → 결과 dict 반환."""
    event, elapsed = call_chat(case["message"])
    return _build_result(case, run, event, elapsed)


# ── 멀티턴 실행 ─────────────────────────────────────────────────────────────────


def _run_multi(case: dict, run: int) -> list[dict[str, Any]]:
    """멀티턴 테스트 — session_id 유지하며 연속 호출."""
    session_id: str | None = None
    results = []

    for turn_def in case["turns"]:
        turn_num = turn_def["turn"]
        event, elapsed = call_chat(turn_def["message"], session_id=session_id)

        # 첫 턴의 done 이벤트에서 session_id를 캡처하여 후속 턴에 사용
        if session_id is None and event.get("session_id"):
            session_id = event["session_id"]

        result = _build_result(
            case,
            run,
            event,
            elapsed,
            turn=turn_num,
            turn_criteria=turn_def.get("criteria", []),
        )
        results.append(result)
        print(f"T{turn_num} ", end="", flush=True)

    return results


# ── 공통 결과 빌더 ──────────────────────────────────────────────────────────────


def _build_result(
    case: dict,
    run: int,
    event: dict,
    elapsed: float,
    *,
    turn: int = 0,
    turn_criteria: list[str] | None = None,
) -> dict[str, Any]:
    """API 응답을 결과 dict로 변환."""
    return {
        "test_id": case["id"],
        "run": run,
        "turn": turn,
        "group": case["group"],
        "title": case["title"],
        "response_time": round(elapsed, 2),
        "answer_text": event.get("text", ""),
        "cited_paragraphs": event.get("cited_paragraphs", []),
        "follow_up_questions": event.get("follow_up_questions", []),
        "is_conclusion": event.get("is_conclusion", False),
        "is_situation": event.get("is_situation", False),
        "matched_topic_keys": event.get("matched_topic_keys", []),
        "selected_branches": event.get("selected_branches", []),
        "retrieved_docs": _summarize_docs(event.get("retrieved_docs", [])),
        "session_id": event.get("session_id", ""),
        "error": event.get("message") if event.get("type") == "error" else None,
        "turn_criteria": turn_criteria or case.get("criteria", []),
    }


def _summarize_docs(docs: list[dict] | None) -> list[dict[str, str]]:
    if not docs:
        return []
    return [
        {
            "source": d.get("source", ""),
            "chunk_id": d.get("chunk_id", ""),
            "hierarchy": d.get("hierarchy", ""),
        }
        for d in docs
    ]


# ── 메인 실행 ───────────────────────────────────────────────────────────────────


def run_tests() -> None:
    results = load_results()
    total_calls = sum(
        RUNS_PER_CASE * (len(c.get("turns", [])) if c["type"] == "multi" else 1)
        for c in TEST_CASES
    )
    done_count = len(results)

    print("=== 라우팅/계산/멀티턴 품질 테스트 시작 ===")
    print(f"총 ~{total_calls}회 호출 (이미 완료: {done_count}건)")
    print()

    for case in TEST_CASES:
        for run in range(1, RUNS_PER_CASE + 1):
            if already_done(results, case["id"], run):
                print(f"  [SKIP] {case['id']} run {run}")
                continue

            print(
                f"  [{case['id']}] run {run}/{RUNS_PER_CASE} ... ",
                end="",
                flush=True,
            )

            try:
                if case["type"] == "single":
                    result = _run_single(case, run)
                    results.append(result)
                    status = "ERROR" if result["error"] else "OK"
                    print(f"{status} ({result['response_time']:.1f}s)")
                else:
                    turn_results = _run_multi(case, run)
                    results.extend(turn_results)
                    total_time = sum(r["response_time"] for r in turn_results)
                    errors = sum(1 for r in turn_results if r.get("error"))
                    status = f"OK ({errors} err)" if errors else "OK"
                    print(f"{status} (total {total_time:.1f}s)")
            except Exception as e:
                # 전체 실패 시 에러 결과 하나만 기록
                results.append(
                    {
                        "test_id": case["id"],
                        "run": run,
                        "turn": 0,
                        "group": case["group"],
                        "title": case["title"],
                        "response_time": 0.0,
                        "answer_text": "",
                        "error": str(e),
                    }
                )
                print(f"EXCEPTION: {e}")

            save_results(results)

    print()
    print(f"=== 테스트 완료: {len(results)}건 ===")
    print(f"결과 파일: {RESULTS_FILE}")


# ── 리포트 생성 ─────────────────────────────────────────────────────────────────


def grade_and_report() -> None:
    """결과 JSON → 마크다운 채점 리포트."""
    results = load_results()
    if not results:
        print("결과 파일이 없습니다.")
        return

    # 케이스 메타 매핑
    case_meta = {c["id"]: c for c in TEST_CASES}

    # test_id + run으로 그룹핑
    by_test: dict[str, list[dict]] = {}
    for r in results:
        by_test.setdefault(r["test_id"], []).append(r)

    lines: list[str] = []
    lines.append("# 라우팅/계산/멀티턴 품질 테스트 리포트\n")
    lines.append("**실행일**: 2026-03-14")
    lines.append(f"**테스트 케이스**: {len(TEST_CASES)}개 × {RUNS_PER_CASE}회\n")

    # ── 응답 시간 통계 ────────────────────────────────────────────────────────
    all_times = [r["response_time"] for r in results if not r.get("error")]
    error_count = sum(1 for r in results if r.get("error"))
    if all_times:
        lines.append("---\n")
        lines.append("## 1. 응답 시간 통계\n")
        lines.append("| 지표 | 값 |")
        lines.append("|------|-----|")
        lines.append(f"| 평균 | {sum(all_times)/len(all_times):.1f}초 |")
        lines.append(f"| 최소 | {min(all_times):.1f}초 |")
        lines.append(f"| 최대 | {max(all_times):.1f}초 |")
        lines.append(f"| 에러 | {error_count}건 |")
        lines.append("")

    # ── 그룹별 요약 테이블 ────────────────────────────────────────────────────
    lines.append("---\n")
    lines.append("## 2. 종합 등급표\n")
    lines.append(
        "| 케이스 | 제목 | 유형 | 평균시간 | 등급 | 핵심 사유 |"
    )
    lines.append(
        "|--------|------|------|---------|------|----------|"
    )
    for test_id in _sorted_ids(by_test.keys()):
        runs = by_test[test_id]
        meta = case_meta.get(test_id, {})
        times = [r["response_time"] for r in runs if not r.get("error")]
        avg_time = f"{sum(times)/len(times):.1f}s" if times else "N/A"
        case_type = "멀티턴" if meta.get("type") == "multi" else "싱글"
        # 등급은 수동 채점용 placeholder
        lines.append(
            f"| {test_id} | {meta.get('title', '')} | {case_type} | "
            f"{avg_time} | **[ ]** | |"
        )
    lines.append("")

    # ── 케이스별 상세 ─────────────────────────────────────────────────────────
    lines.append("---\n")
    lines.append("## 3. 케이스별 상세\n")

    for test_id in _sorted_ids(by_test.keys()):
        runs = by_test[test_id]
        meta = case_meta.get(test_id, {})

        lines.append(f"### {test_id}: {meta.get('title', '')}\n")
        lines.append(f"**그룹**: {meta.get('group', '')}")
        lines.append(f"**유형**: {'멀티턴' if meta.get('type') == 'multi' else '싱글'}\n")

        # run별 그룹핑
        runs_by_num: dict[int, list[dict]] = {}
        for r in runs:
            runs_by_num.setdefault(r["run"], []).append(r)

        for run_num in sorted(runs_by_num.keys()):
            run_results = sorted(runs_by_num[run_num], key=lambda x: x.get("turn", 0))
            lines.append(f"#### Run {run_num}\n")

            for r in run_results:
                turn = r.get("turn", 0)
                turn_label = f" (턴 {turn})" if turn > 0 else ""

                if r.get("error"):
                    lines.append(f"**{turn_label} ERROR**: {r['error']}\n")
                    continue

                lines.append(f"**{turn_label}**")
                lines.append(f"- 응답시간: {r['response_time']:.1f}s")
                lines.append(
                    f"- is_situation: {'Yes' if r.get('is_situation') else 'No'}"
                )
                lines.append(
                    f"- is_conclusion: {'Yes' if r.get('is_conclusion') else 'No'}"
                )
                lines.append(
                    f"- 꼬리질문: {r.get('follow_up_questions', []) or '없음'}"
                )
                lines.append(f"- 인용 문단: {r.get('cited_paragraphs', [])}")
                lines.append(f"- 매칭 토픽: {r.get('matched_topic_keys', [])}")

                branches = r.get("selected_branches", [])
                if branches:
                    lines.append(f"- 선택 분기: {branches}")

                docs = r.get("retrieved_docs", [])
                if docs:
                    doc_summaries = [
                        f"{d.get('source', '')}:{d.get('hierarchy', '')}"
                        for d in docs[:5]
                    ]
                    lines.append(f"- 검색 문서(상위5): {doc_summaries}")

                answer = r.get("answer_text", "")
                preview = (
                    answer[:300].replace("\n", " ")
                    + ("..." if len(answer) > 300 else "")
                )
                lines.append(f"- 답변 미리보기: {preview}")

                # 채점기준 체크리스트
                criteria = r.get("turn_criteria", [])
                if criteria:
                    lines.append(f"\n**채점기준{turn_label}**:")
                    for c in criteria:
                        lines.append(f"- [ ] {c}")
                lines.append("")

        lines.append("---\n")

    # ── 파일 저장 ─────────────────────────────────────────────────────────────
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report = "\n".join(lines)
    REPORT_FILE.write_text(report, encoding="utf-8")
    print(f"리포트 생성 완료: {REPORT_FILE}")


def _sorted_ids(ids) -> list[str]:
    """A1~A4, B1~B3, C1~C3 순서 정렬."""

    def key(test_id: str) -> tuple[int, int]:
        prefix = test_id[0]
        num = int(test_id[1:])
        order = {"A": 0, "B": 1, "C": 2}.get(prefix, 9)
        return (order, num)

    return sorted(ids, key=key)


# ── 엔트리 포인트 ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "report":
        grade_and_report()
    else:
        run_tests()
        grade_and_report()

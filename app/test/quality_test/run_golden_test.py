"""
K-IFRS 1115 통합 골든 테스트 실행기

47개 케이스 × N회 순차 실행 → JSON 결과 저장 → 채점 리포트 생성.
중단 후 재실행 시 이미 완료된 (test_id, run) 쌍은 자동 스킵.

실행:
  # 전체 (47케이스, 기본 runs=3 / 스트레스 runs=1)
  PYTHONPATH=. uv run python app/test/quality_test/run_golden_test.py

  # 리포트만 재생성
  PYTHONPATH=. uv run python app/test/quality_test/run_golden_test.py report

  # 특정 케이스만
  PYTHONPATH=. uv run python app/test/quality_test/run_golden_test.py --cases S01,R01,C01

  # 반복 횟수 오버라이드
  PYTHONPATH=. uv run python app/test/quality_test/run_golden_test.py --runs 1

  # 결과 파일 태그
  RESULT_TAG=_v2 PYTHONPATH=. uv run python app/test/quality_test/run_golden_test.py
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from app.test.quality_test.golden_cases import (
    GOLDEN_CASES,
    GOLDEN_CASES_BY_ID,
    GoldenCase,
)

# ── 설정 ────────────────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8002"
TIMEOUT = 180  # 멀티턴은 대기 시간이 길 수 있음

RESULTS_DIR = Path(__file__).parent / "results"
_TAG = os.environ.get("RESULT_TAG", "")
RESULTS_FILE = RESULTS_DIR / f"golden_results{_TAG}.json"
REPORT_FILE = RESULTS_DIR / f"golden_report{_TAG}.md"


# ── SSE 호출 ───────────────────────────────────────────────────────────────────


def call_chat(
    message: str, session_id: str | None = None
) -> tuple[dict[str, Any], float]:
    """POST /chat → (done_event, response_time_sec).

    SSE 스트리밍을 소비하여 done 이벤트를 추출한다.
    """
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


# ── 결과 저장/로드 (중단/재개용) ──────────────────────────────────────────────────


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
    """이미 완료된 (test_id, run) 쌍인지 확인."""
    return any(r["test_id"] == test_id and r["run"] == run for r in results)


# ── 공통 결과 빌더 ──────────────────────────────────────────────────────────────


def _build_result(
    case: GoldenCase,
    run: int,
    event: dict,
    elapsed: float,
    *,
    turn: int = 0,
    turn_criteria: list[str] | None = None,
) -> dict[str, Any]:
    """API 응답을 결과 dict로 변환."""
    return {
        "test_id": case.id,
        "run": run,
        "turn": turn,
        "group": case.group,
        "title": case.title,
        "topic": case.topic,
        "response_time": round(elapsed, 2),
        "answer_text": event.get("text", ""),
        "cited_paragraphs": event.get("cited_paragraphs", []),
        "cited_sources": event.get("cited_sources", []),
        "follow_up_questions": event.get("follow_up_questions", []),
        "is_conclusion": event.get("is_conclusion", False),
        "is_situation": event.get("is_situation", False),
        "needs_calculation": event.get("needs_calculation", False),
        "matched_topic_keys": event.get("matched_topic_keys", []),
        "selected_branches": event.get("selected_branches", []),
        "search_keywords": event.get("search_keywords", []),
        "retrieved_docs": _summarize_docs(event.get("retrieved_docs", [])),
        "session_id": event.get("session_id", ""),
        "findings_case": event.get("findings_case"),
        "error": event.get("message") if event.get("type") == "error" else None,
        "turn_criteria": turn_criteria or case.scoring_criteria,
    }


def _summarize_docs(docs: list[dict] | None) -> list[dict[str, str]]:
    """retrieved_docs에서 source, chunk_id, hierarchy만 추출하여 경량화."""
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


# ── 싱글턴 실행 ─────────────────────────────────────────────────────────────────


def _run_single(case: GoldenCase, run: int) -> dict[str, Any]:
    """싱글턴(단일 메시지) 테스트 실행."""
    event, elapsed = call_chat(case.message)
    return _build_result(case, run, event, elapsed)


# ── 멀티턴 실행 ─────────────────────────────────────────────────────────────────


def _run_multi(case: GoldenCase, run: int) -> list[dict[str, Any]]:
    """멀티턴 테스트 — session_id 유지하며 연속 호출."""
    session_id: str | None = None
    results = []

    for turn_def in case.turns:
        event, elapsed = call_chat(turn_def.message, session_id=session_id)

        # 첫 턴의 done 이벤트에서 session_id 캡처
        if session_id is None and event.get("session_id"):
            session_id = event["session_id"]

        result = _build_result(
            case,
            run,
            event,
            elapsed,
            turn=turn_def.turn,
            turn_criteria=turn_def.criteria,
        )
        results.append(result)
        print(f"T{turn_def.turn} ", end="", flush=True)

    return results


# ── 멀티턴 여부 판단 ────────────────────────────────────────────────────────────


def _is_multi(case: GoldenCase) -> bool:
    """turns가 있으면 멀티턴."""
    return len(case.turns) > 0


# ── 메인 실행 ───────────────────────────────────────────────────────────────────


def run_tests(
    cases: list[GoldenCase] | None = None,
    runs_override: int | None = None,
) -> None:
    """골든 테스트 실행. cases=None이면 전체, runs_override로 반복 횟수 오버라이드."""
    target_cases = cases or GOLDEN_CASES
    results = load_results()
    done_count = len(results)

    # 총 API 호출 수 계산
    total_calls = 0
    for c in target_cases:
        r = runs_override if runs_override is not None else c.runs
        if _is_multi(c):
            total_calls += r * len(c.turns)
        else:
            total_calls += r

    print("=== K-IFRS 1115 통합 골든 테스트 시작 ===")
    print(f"케이스: {len(target_cases)}개, ~{total_calls}회 호출 (이미 완료: {done_count}건)")
    print()

    for case in target_cases:
        runs = runs_override if runs_override is not None else case.runs

        for run in range(1, runs + 1):
            if already_done(results, case.id, run):
                print(f"  [SKIP] {case.id} run {run}")
                continue

            print(
                f"  [{case.id}] {case.title} — run {run}/{runs} ... ",
                end="",
                flush=True,
            )

            try:
                if _is_multi(case):
                    turn_results = _run_multi(case, run)
                    results.extend(turn_results)
                    total_time = sum(r["response_time"] for r in turn_results)
                    errors = sum(1 for r in turn_results if r.get("error"))
                    status = f"OK ({errors} err)" if errors else "OK"
                    print(f"{status} (total {total_time:.1f}s)")
                else:
                    result = _run_single(case, run)
                    results.append(result)
                    status = "ERROR" if result["error"] else "OK"
                    print(f"{status} ({result['response_time']:.1f}s)")
            except Exception as e:
                results.append(
                    {
                        "test_id": case.id,
                        "run": run,
                        "turn": 0,
                        "group": case.group,
                        "title": case.title,
                        "topic": case.topic,
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
    """결과 JSON → 진단 중심 마크다운 리포트.

    구조:
      1. 대시보드 (종합 결과 1줄 + 그룹별 통계)
      2. 문제 케이스 (자동 진단 → 무엇이 틀렸고 어떻게 고쳐야 하는지)
      3. 잘된 케이스 요약 (한줄씩)
      4. 그룹별 스코어카드 (토픽 매칭 O/X 한눈에)
    """
    results = load_results()
    if not results:
        print("결과 파일이 없습니다. 먼저 테스트를 실행하세요.")
        return

    case_meta = GOLDEN_CASES_BY_ID

    # test_id별 그룹핑
    by_test: dict[str, list[dict]] = {}
    for r in results:
        by_test.setdefault(r["test_id"], []).append(r)

    # ── 자동 진단 ─────────────────────────────────────────────────────────
    issues: list[dict] = []       # 문제 케이스
    good_cases: list[dict] = []   # 정상 케이스

    for test_id in _sorted_ids(by_test.keys()):
        runs = by_test[test_id]
        meta = case_meta.get(test_id)
        if not meta:
            continue

        # 마지막 run의 마지막 턴 결과
        last_run = [x for x in runs if x["run"] == max(r["run"] for r in runs)]
        r = sorted(last_run, key=lambda x: x.get("turn", 0))[-1]

        case_issues: list[str] = []
        case_good: list[str] = []

        # 1) 에러 체크
        if r.get("error"):
            case_issues.append(f"API 에러: {r['error']}")

        # 2) 토픽 매칭 체크
        topics = r.get("matched_topic_keys") or []
        if meta.topic and meta.question_type == "situation":
            if topics:
                match_ok = any(meta.topic in t for t in topics)
                if match_ok:
                    is_top1 = meta.topic in topics[0]
                    if is_top1:
                        case_good.append(f"토픽 매칭 정확 (top-1)")
                    else:
                        # top-3 포함이면 정상 — LLM이 체크리스트를 읽고 판단
                        rank = next(i + 1 for i, t in enumerate(topics) if meta.topic in t)
                        case_good.append(f"토픽 매칭 포함 (top-{rank})")
                else:
                    case_issues.append(
                        f"토픽 매칭 실패: 기대=`{meta.topic}` → "
                        f"실제=`{topics}`"
                    )
            else:
                case_issues.append(
                    f"토픽 매칭 없음: 기대=`{meta.topic}`"
                )

        # 3) 라우팅 체크
        if meta.expected_routing:
            is_sit = r.get("is_situation", False)
            is_conc = r.get("is_conclusion", False)
            actual_route = _infer_routing(is_sit, is_conc, r)
            if meta.expected_routing == actual_route:
                case_good.append(f"라우팅 정확 ({actual_route})")
            else:
                case_issues.append(
                    f"라우팅 불일치: "
                    f"기대=`{meta.expected_routing}` → 실제=`{actual_route}`"
                )

        # 4) 계산 정답 체크
        if meta.expected_answer:
            answer = r.get("answer_text", "")
            # 기대 정답의 핵심 숫자를 답변에서 찾기
            found = _check_answer_numbers(meta.expected_answer, answer)
            if found:
                case_good.append(f"계산 정답 포함")
            else:
                case_issues.append(
                    f"계산 정답 미포함: 기대=`{meta.expected_answer}`"
                )

        # 5) 인용 문단 체크
        cited = r.get("cited_paragraphs") or []
        if meta.expected_docs and not cited:
            case_issues.append("인용 문단 없음")
        elif cited:
            case_good.append(f"인용 {len(cited)}건")

        # 6) 응답시간 체크 (60초 초과 경고)
        total_time = sum(x["response_time"] for x in last_run)
        if total_time > 60:
            case_issues.append(f"응답 느림: {total_time:.0f}s")

        # 7) 결론 체크 (상황 질문인데 결론 없음)
        if meta.question_type == "situation" and not r.get("is_conclusion"):
            case_issues.append("상황 질문인데 결론 미생성")

        # 8) 꼬리질문 체크
        # Why: 마지막 턴만 보면 멀티턴(Turn 2 concluded)이나 단일턴 TYPE 2(즉답)가
        #      거짓 양성으로 ISSUE 판정됨 → 전체 대화 맥락을 고려해야 정확
        fups = r.get("follow_up_questions") or []
        if meta.question_type == "situation" and not fups:
            if len(meta.turns) > 0:
                # 멀티턴: 전체 대화에서 한 번이라도 꼬리질문이 있었으면 정상
                any_fups = any(
                    t.get("follow_up_questions")
                    for t in last_run
                )
                if not any_fups:
                    case_issues.append("상황 질문인데 꼬리질문 없음")
            elif not r.get("is_conclusion"):
                # 단일턴: concluded=True(TYPE 2 확정 결론)이면 꼬리질문 불필요
                case_issues.append("상황 질문인데 꼬리질문 없음")

        entry = {
            "test_id": test_id,
            "title": meta.title,
            "group": meta.group,
            "topic": meta.topic,
            "time": total_time,
            "issues": case_issues,
            "good": case_good,
            "topics_matched": topics,
            "cited_count": len(cited),
            "is_multi": len(meta.turns) > 0,
        }
        if case_issues:
            issues.append(entry)
        else:
            good_cases.append(entry)

    # ── 리포트 생성 ───────────────────────────────────────────────────────
    lines: list[str] = []

    # 1. 대시보드
    all_times = [r["response_time"] for r in results if not r.get("error")]
    error_count = sum(1 for r in results if r.get("error"))

    lines.append("# K-IFRS 1115 골든 테스트 리포트\n")
    avg = f"{sum(all_times)/len(all_times):.1f}s" if all_times else "N/A"
    lines.append(
        f"> **{len(by_test)}개 케이스** | "
        f"**문제 {len(issues)}건** | "
        f"**정상 {len(good_cases)}건** | "
        f"평균 {avg} | 에러 {error_count}건\n"
    )

    # 그룹별 1줄 통계
    group_order = [
        "거래상황", "개념이론", "라우팅", "계산",
        "멀티턴", "신규커버리지", "스트레스",
    ]
    lines.append("| 그룹 | 케이스 | 문제 | 평균시간 |")
    lines.append("|------|--------|------|---------|")
    for g in group_order:
        g_all = [e for e in issues + good_cases if e["group"] == g]
        g_issues = [e for e in issues if e["group"] == g]
        if not g_all:
            continue
        times = [e["time"] for e in g_all]
        avg_t = f"{sum(times)/len(times):.0f}s"
        issue_str = f"**{len(g_issues)}건**" if g_issues else "0"
        lines.append(f"| {g} | {len(g_all)}개 | {issue_str} | {avg_t} |")
    lines.append("")

    # ── 2. 문제 케이스 (핵심) ──────────────────────────────────────────────
    lines.append("---\n")
    if issues:
        lines.append(f"## 문제 케이스 ({len(issues)}건)\n")
        for e in issues:
            multi = " (멀티턴)" if e["is_multi"] else ""
            lines.append(f"### {e['test_id']}: {e['title']}{multi}\n")
            lines.append(f"그룹: {e['group']} | 토픽: {e['topic']} | {e['time']:.0f}s\n")

            for issue in e["issues"]:
                lines.append(f"- **문제**: {issue}")
            for g in e["good"]:
                lines.append(f"- 정상: {g}")
            lines.append("")
    else:
        lines.append("## 문제 케이스\n")
        lines.append("없음! 전체 PASS\n")

    # ── 3. 잘된 케이스 (1줄 요약) ──────────────────────────────────────────
    lines.append("---\n")
    lines.append(f"## 정상 케이스 ({len(good_cases)}건)\n")
    lines.append("| ID | 제목 | 그룹 | 시간 | 요약 |")
    lines.append("|-----|------|------|------|------|")
    for e in good_cases:
        summary = ", ".join(e["good"][:3])
        lines.append(
            f"| {e['test_id']} | {e['title']} | {e['group']} "
            f"| {e['time']:.0f}s | {summary} |"
        )
    lines.append("")

    # ── 4. 그룹별 스코어카드 ──────────────────────────────────────────────
    lines.append("---\n")
    lines.append("## 스코어카드\n")

    for group_name in group_order:
        g_entries = [
            e for e in issues + good_cases if e["group"] == group_name
        ]
        if not g_entries:
            continue
        g_entries.sort(key=lambda x: _sort_key(x["test_id"]))

        lines.append(f"### {group_name}\n")
        lines.append("| ID | 제목 | 토픽 | 인용 | 시간 | 판정 |")
        lines.append("|-----|------|------|------|------|------|")
        for e in g_entries:
            verdict = "PASS" if not e["issues"] else "**ISSUE**"
            topic_display = e["topics_matched"][0] if e["topics_matched"] else "-"
            lines.append(
                f"| {e['test_id']} | {e['title']} | {topic_display} "
                f"| {e['cited_count']}건 | {e['time']:.0f}s | {verdict} |"
            )
        lines.append("")

    # ── 파일 저장 ──────────────────────────────────────────────────────────
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report = "\n".join(lines)
    REPORT_FILE.write_text(report, encoding="utf-8")
    print(f"리포트 생성 완료: {REPORT_FILE}")


def _infer_routing(is_situation: bool, is_conclusion: bool, r: dict) -> str:
    """결과에서 실제 라우팅 경로를 추론합니다.

    Why: needs_calculation 플래그로 calc/clarify 구분.
    SSE done 이벤트에 needs_calculation이 포함되어야 동작함.
    """
    if not is_situation:
        return "generate"
    if r.get("needs_calculation", False):
        return "calc"
    return "clarify"


def _check_answer_numbers(expected: str, answer: str) -> bool:
    """기대 정답의 핵심 숫자가 답변에 포함되는지 확인합니다."""
    import re
    # Why: LLM이 "7200만" 또는 "72,000,000"으로 출력할 수 있으므로 콤마 제거 후 비교
    answer_clean = answer.replace(",", "")
    # 기대 정답에서 숫자 추출 (예: "85억" → "85", "6.95억" → "6.95")
    numbers = re.findall(r"[\d]+(?:\.[\d]+)?", expected)
    if not numbers:
        return expected in answer
    # 핵심 숫자 중 절반 이상이 답변에 포함되면 정답
    found = sum(1 for n in numbers if n in answer_clean)
    return found >= len(numbers) / 2


def _sort_key(test_id: str) -> tuple[int, int]:
    """정렬 키 헬퍼."""
    prefix_order = {"S": 0, "K": 1, "R": 2, "C": 3, "M": 4, "N": 5, "X": 6}
    prefix = test_id[0]
    num = int(test_id[1:])
    return (prefix_order.get(prefix, 9), num)


def _sorted_ids(ids) -> list[str]:
    """S01~S20, K01~K05, R01~R04, C01~C03, M01~M03, N01~N10, X01~X08 순 정렬."""
    prefix_order = {"S": 0, "K": 1, "R": 2, "C": 3, "M": 4, "N": 5, "X": 6}

    def key(test_id: str) -> tuple[int, int]:
        prefix = test_id[0]
        num = int(test_id[1:])
        order = prefix_order.get(prefix, 9)
        return (order, num)

    return sorted(ids, key=key)


# ── CLI 엔트리 포인트 ───────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="K-IFRS 1115 통합 골든 테스트")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "report"],
        help="run: 테스트 실행 + 리포트, report: 리포트만 재생성",
    )
    parser.add_argument(
        "--cases",
        type=str,
        default="",
        help="실행할 케이스 ID (쉼표 구분, 예: S01,R01,C01)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=None,
        help="반복 횟수 오버라이드 (기본: 케이스별 runs 값)",
    )

    args = parser.parse_args()

    if args.command == "report":
        grade_and_report()
        return

    # 케이스 필터링
    target_cases: list[GoldenCase] | None = None
    if args.cases:
        case_ids = [c.strip() for c in args.cases.split(",")]
        target_cases = [GOLDEN_CASES_BY_ID[cid] for cid in case_ids if cid in GOLDEN_CASES_BY_ID]
        missing = [cid for cid in case_ids if cid not in GOLDEN_CASES_BY_ID]
        if missing:
            print(f"[WARNING] 존재하지 않는 케이스 ID: {missing}")

    run_tests(cases=target_cases, runs_override=args.runs)
    grade_and_report()


if __name__ == "__main__":
    main()

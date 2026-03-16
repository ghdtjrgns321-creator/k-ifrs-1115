"""TEST-0 토픽 매칭 안정성 + 회귀 테스트 스크립트

/chat SSE 엔드포인트에서 done 이벤트를 파싱하여:
1. TEST-0 5회 반복 → 매칭률 측정
2. 회귀 테스트 (SECTION-5, 6, 19) 각 1회
3. 실패 시 search_keywords 캡처 → 근본 원인 분석
4. 결과를 JSON + 마크다운 리포트로 저장
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

import httpx

BASE = "http://localhost:8002"
RESULTS_DIR = Path(__file__).parent.parent / "quality_test" / "results"

# 테스트 케이스: (id, message, expected_topic_substr)
CASES = [
    (
        "TEST-0",
        "A가 B에게 재화(완성된 의류)를 100원에 공급하고 이 때 공급가액(100원)으로 "
        "세금계산서를 끊음. 이후 B는 최종 고객 C에게 재화를 120원에 판매하는데, "
        "이 경우 A가 인식하여야 할 매출액은 100원인지, 120원인지 궁금합니다.",
        "본인 vs 대리인",
    ),
    (
        "SECTION-5",
        "저희 회사가 고객에게 판매한 제품을 일정 기간 내에 다시 매입하기로 약정했는데, "
        "이 경우 수익을 인식해도 되나요? 재매입가격은 원래 판매가보다 낮습니다.",
        "재매입약정",
    ),
    (
        "SECTION-6",
        "저희 플랫폼을 이용하는 유저(방송 크리에이터)들의 광고 수익 중 일부를 "
        "캐시백 형태로 돌려주고 있는데, 이걸 매출 차감으로 처리해야 하나요? "
        "아니면 광고선전비로 처리해야 하나요?",
        "고객에게 지급할 대가",
    ),
    (
        "SECTION-19",
        "저희 회사가 신규 고객과 계약을 체결하면서 초기 세팅 비용이 발생했는데, "
        "이 원가를 자산으로 인식할 수 있나요? 계약기간은 3년입니다.",
        "계약이행원가",
    ),
]


async def parse_sse_done(resp: httpx.Response) -> dict:
    """SSE 스트림에서 done 이벤트를 파싱합니다."""
    done_data = {}
    async for line in resp.aiter_lines():
        if line.startswith("data: "):
            payload = json.loads(line[6:])
            if payload.get("type") == "done":
                done_data = payload
                break
    return done_data


async def test_single(
    client: httpx.AsyncClient, case_id: str, message: str,
    expected: str, run: int,
) -> dict:
    """단일 테스트 실행 — SSE 스트림에서 done 이벤트 파싱"""
    async with client.stream(
        "POST",
        f"{BASE}/chat",
        json={"message": message, "session_id": f"stability-{case_id}-{run}"},
        timeout=120.0,
    ) as resp:
        done = await parse_sse_done(resp)

    topic_keys = done.get("matched_topic_keys") or []
    search_kws = done.get("search_keywords") or []
    matched = any(expected in k for k in topic_keys)
    top1 = topic_keys[0] if topic_keys else "NONE"
    return {
        "case": case_id,
        "run": run,
        "matched": matched,
        "top1": top1,
        "all_topics": topic_keys,
        "search_keywords": search_kws,
    }


async def main():
    all_results = []

    async with httpx.AsyncClient() as client:
        # ── TEST-0: 5회 반복 ──
        print("=" * 60)
        print("TEST-0 안정성 테스트 (5회)")
        print("=" * 60)
        test0_results = []
        for i in range(5):
            r = await test_single(client, "TEST-0", CASES[0][1], CASES[0][2], i)
            status = "OK" if r["matched"] else "FAIL"
            print(f"  Run {i}: {status} | top1={r['top1']}")
            print(f"         keywords={r['search_keywords']}")
            print(f"         topics={r['all_topics']}")
            test0_results.append(r)
            all_results.append(r)

        hit = sum(1 for r in test0_results if r["matched"])
        print(f"\n  결과: {hit}/5 매칭 ({hit * 20}%)")

        # ── 회귀 테스트 ──
        print("\n" + "=" * 60)
        print("회귀 테스트 (각 1회)")
        print("=" * 60)
        for case_id, message, expected in CASES[1:]:
            r = await test_single(client, case_id, message, expected, 0)
            status = "OK" if r["matched"] else "FAIL"
            extra = ""
            if case_id == "SECTION-6":
                is_top1 = expected in (r["top1"] or "")
                extra = f" | top1_correct={'YES' if is_top1 else 'NO'}"
            print(f"  {case_id}: {status} | top1={r['top1']}{extra}")
            print(f"         keywords={r['search_keywords']}")
            print(f"         topics={r['all_topics']}")
            all_results.append(r)

    # ── 결과 저장 ──
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # JSON 저장
    json_path = RESULTS_DIR / f"topic_stability_{timestamp}.json"
    json_path.write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nJSON 저장: {json_path}")

    # 마크다운 리포트 생성
    report = _build_report(test0_results, all_results, timestamp)
    md_path = RESULTS_DIR / f"topic_stability_{timestamp}.md"
    md_path.write_text(report, encoding="utf-8")
    print(f"리포트 저장: {md_path}")


def _build_report(
    test0_results: list[dict], all_results: list[dict], timestamp: str,
) -> str:
    """마크다운 리포트를 생성합니다."""
    lines = [
        f"# 토픽 매칭 안정성 테스트 리포트",
        f"",
        f"**실행일시**: {timestamp}",
        f"**변경사항**: user_message 보조 매칭(가중치 0.5) + trigger_keywords 4개 추가",
        f"",
        f"## TEST-0 안정성 (5회 반복)",
        f"",
        f"**기대 토픽**: 본인 vs 대리인",
        f"",
        f"| Run | 결과 | Top-1 | search_keywords | 전체 토픽 |",
        f"|-----|------|-------|-----------------|-----------|",
    ]
    for r in test0_results:
        status = "OK" if r["matched"] else "**FAIL**"
        kws = ", ".join(r["search_keywords"][:6])
        topics = ", ".join(r["all_topics"])
        lines.append(f"| {r['run']} | {status} | {r['top1']} | {kws} | {topics} |")

    hit = sum(1 for r in test0_results if r["matched"])
    lines.extend([
        f"",
        f"**매칭률: {hit}/5 ({hit * 20}%)**",
        f"",
    ])

    # 실패 분석
    failures = [r for r in test0_results if not r["matched"]]
    if failures:
        lines.extend([
            f"### 실패 케이스 분석",
            f"",
        ])
        for r in failures:
            lines.extend([
                f"**Run {r['run']}**:",
                f"- Top-1: `{r['top1']}`",
                f"- search_keywords: `{r['search_keywords']}`",
                f"- 매칭된 토픽: `{r['all_topics']}`",
                f"- **원인 추정**: LLM이 search_keywords에서 "
                f"'본인/대리인/통제/위탁' 등 핵심 trigger를 누락하고 "
                f"일반적 용어만 추출 → keyword 점수 부족 → "
                f"user_message(+0.5)와 embedding(~3.0)만으로는 "
                f"다른 토픽의 keyword 점수를 이기지 못함",
                f"",
            ])
    else:
        lines.extend([
            f"### 실패 케이스",
            f"",
            f"없음 (5/5 성공)",
            f"",
        ])

    # 회귀 테스트
    regression = [r for r in all_results if r["case"] != "TEST-0"]
    lines.extend([
        f"## 회귀 테스트",
        f"",
        f"| 케이스 | 기대 토픽 | 결과 | Top-1 | search_keywords |",
        f"|--------|-----------|------|-------|-----------------|",
    ])
    expected_map = {c[0]: c[2] for c in CASES[1:]}
    for r in regression:
        expected = expected_map.get(r["case"], "")
        status = "OK" if r["matched"] else "**FAIL**"
        kws = ", ".join(r["search_keywords"][:6])
        lines.append(
            f"| {r['case']} | {expected} | {status} | {r['top1']} | {kws} |"
        )

    reg_hit = sum(1 for r in regression if r["matched"])
    lines.extend([
        f"",
        f"**회귀 결과: {reg_hit}/{len(regression)} 통과**",
        f"",
        f"## SECTION-6 교차 오염 확인",
        f"",
    ])
    sec6 = next((r for r in regression if r["case"] == "SECTION-6"), None)
    if sec6:
        has_principal = any("본인 vs 대리인" in t for t in sec6["all_topics"])
        lines.extend([
            f"- Top-1: `{sec6['top1']}` → "
            f"{'정확 (순위 역전 없음)' if '고객에게 지급할 대가' in sec6['top1'] else '순위 역전 발생!'}",
            f"- '본인 vs 대리인' 진입: {'예 (부차 토픽)' if has_principal else '아니오'}",
            f"- **결론**: {'가중치 0.5 방어 정상 작동' if '고객에게 지급할 대가' in sec6['top1'] else '추가 조치 필요'}",
            f"",
        ])

    lines.extend([
        f"## 가중치 체계",
        f"",
        f"| 소스 | 가중치 | 역할 |",
        f"|------|--------|------|",
        f"| search_keywords | 2.0 | LLM 추출 핵심 용어 |",
        f"| standalone_query | 1.0 | LLM 재작성 문장 |",
        f"| **user_message** | **0.5** | **원본 결정적 보완 (신규)** |",
        f"| topic_hints | +3.0 | LLM 추론 토픽 |",
        f"| embedding | sim×10.0 | 의미적 매칭 |",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    asyncio.run(main())

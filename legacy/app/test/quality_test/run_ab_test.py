"""thinking_level A/B 테스트 — Partial 5건 × 5회

실행 전 agents.py에서 thinking_level 변경 + 서버 재시작 필요.
결과를 JSON으로 저장 후 기존 high 결과(quality_results.json)와 비교.

실행:
  PYTHONPATH=. uv run --env-file .env python app/test/quality_test/run_ab_test.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "http://localhost:8002"
RUNS = 5
TIMEOUT = 120
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)
OUT_FILE = RESULTS_DIR / "ab_test_medium.json"

# Partial 5건만 추출
CASES = [
    {
        "id": "TEST-0",
        "title": "본인 vs 대리인(위탁판매)",
        "message": (
            "A가 B에게 재화(완성된 의류)를 100원에 공급하고 이 때 공급가액(100원)으로 "
            "세금계산서를 끊음. 이후 B는 최종 고객 C에게 재화를 120원에 판매하는데, "
            "이 경우 A가 인식하여야 할 매출액은 100원인지, 120원인지 궁금합니다."
        ),
        "criteria": "통제권 확인 꼬리질문, 본인 120원 총액, 세금계산서 혼동",
    },
    {
        "id": "SECTION-4",
        "title": "미인도청구약정 (Bill-and-Hold)",
        "message": (
            "D업체에 여름 시즌 제품을 5,000만 원에 판매하고 세금계산서도 발행했습니다. "
            "대금도 일부 받았고요. 그런데 제품은 아직 인도하지 않고 우리 회사 창고에 "
            "그대로 보관 중입니다. 이거 당장 수익으로 인식해도 됩니까?"
        ),
        "criteria": "미인도청구약정 4요건 꼬리질문",
    },
    {
        "id": "SECTION-5",
        "title": "재매입약정 (콜옵션)",
        "message": (
            "우리 회사가 생산 설비를 고객에게 1억 원에 판매했습니다. 그런데 계약 조건에 "
            "2년 뒤에 우리 회사가 원할 경우 이 설비를 다시 사올 수 있는 '콜옵션'이 포함되어 "
            "있습니다. 설비를 다시 사 올 가능성은 적은데, 일단 1억 원을 판매 시점에 매출로 "
            "잡으면 되나요?"
        ),
        "criteria": "콜옵션 수익 인식 불가, 행사가격 꼬리질문",
    },
    {
        "id": "SECTION-6",
        "title": "고객에게 지급할 대가",
        "message": (
            "저희 플랫폼을 이용하는 유저(방송 크리에이터)들의 이탈을 막기 위해 "
            "활동지원금(캐시백 리워드) 명목으로 현금 1,000만 원을 지급했습니다. "
            "마케팅 목적이니까 당연히 '광고선전비(비용)'로 처리하려고 합니다. "
            "맞게 하는 건가요?"
        ),
        "criteria": "고객 해당 여부 + 구별되는 용역 꼬리질문, 수익 차감 vs 비용",
    },
    {
        "id": "SECTION-19",
        "title": "계약이행원가 (교육훈련비)",
        "message": (
            "저희가 3년짜리 IT 아웃소싱 용역을 수주했습니다. 성공적인 용역 제공을 위해 "
            "투입될 저희 직원들을 대상으로 대대적인 '소프트웨어 코딩 교육'을 실시하고 "
            "5천만 원을 썼습니다. 이 교육비는 계약을 이행하기 위해 쓴 돈이니까 "
            "'계약이행원가(자산)'로 잡고 3년간 상각처리 할 수 있죠?"
        ),
        "criteria": "타 기준서(IAS 38) 우선 적용 지적, 교육훈련비 즉시 비용",
    },
]


def call_chat(message: str) -> tuple[dict[str, Any], float]:
    start = time.time()
    done_event = None
    error_msg = None
    with httpx.Client(timeout=httpx.Timeout(TIMEOUT, connect=10)) as client:
        with client.stream(
            "POST", f"{BASE_URL}/chat",
            json={"message": message},
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
    return {"type": "error", "message": "no done event"}, elapsed


def main():
    results = []
    total = len(CASES) * RUNS
    print(f"=== A/B 테스트 (thinking=medium) ===")
    print(f"총 {total}회 호출 ({len(CASES)}건 × {RUNS}회)\n")

    for case in CASES:
        for run in range(1, RUNS + 1):
            print(f"  [{case['id']}] run {run}/{RUNS} ... ", end="", flush=True)
            try:
                event, elapsed = call_chat(case["message"])
            except Exception as e:
                event = {"type": "error", "message": str(e)}
                elapsed = 0.0

            fq = event.get("follow_up_questions", [])
            result = {
                "test_id": case["id"],
                "run": run,
                "title": case["title"],
                "response_time": round(elapsed, 1),
                "answer_len": len(event.get("text", "")),
                "follow_up_count": len(fq) if fq else 0,
                "follow_up_questions": fq or [],
                "is_conclusion": event.get("is_conclusion", False),
                "is_situation": event.get("is_situation", False),
                "matched_topic_keys": event.get("matched_topic_keys", []),
                "cited_count": len(event.get("cited_paragraphs", []) or []),
                "error": event.get("message") if event.get("type") == "error" else None,
            }
            results.append(result)
            status = "ERROR" if result["error"] else "OK"
            fq_tag = f" fq={result['follow_up_count']}" if not result["error"] else ""
            print(f"{status} ({elapsed:.1f}s{fq_tag})")

    # 저장
    OUT_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {OUT_FILE}")

    # 요약
    print("\n=== 요약 ===\n")
    by_case: dict[str, list] = {}
    for r in results:
        by_case.setdefault(r["test_id"], []).append(r)

    for case_id, runs in by_case.items():
        times = [r["response_time"] for r in runs if not r["error"]]
        fqs = [r["follow_up_count"] for r in runs if not r["error"]]
        errors = sum(1 for r in runs if r["error"])
        topics_sets = [tuple(sorted(r["matched_topic_keys"])) for r in runs if not r["error"]]
        topic_consistency = len(set(topics_sets)) == 1 if topics_sets else False

        print(f"  {case_id}:")
        print(f"    시간: avg={sum(times)/len(times):.1f}s" if times else "    시간: N/A")
        print(f"    꼬리질문: {fqs}  (일관={all(f == fqs[0] for f in fqs) if fqs else 'N/A'})")
        print(f"    토픽일관: {topic_consistency}")
        print(f"    에러: {errors}/{RUNS}")
        print()


if __name__ == "__main__":
    main()

"""STEP 6 홀드아웃 러너 — qna_testset 92건을 QNA-off 파이프라인에 통과시켜 응답 수집.

서버를 exclude_qna=ON(EXCLUDE_QNA=1)로 띄운 뒤 실행해야 A안(QNA 격리)이 적용된다.
채점은 grade.py가 담당. 여기선 응답 원문·인용·검색 source만 저장(재개 가능).

실행:
  # 서버 (별도 셸): EXCLUDE_QNA=1 PYTHONPATH=. uv run --env-file .env \
  #   uvicorn app.main:app --port 8002
  PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/run.py
  PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/run.py --cases QNA-2017-I-KAQ015-Q1
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.test.qna_holdout.sse_client import call_chat

_HERE = Path(__file__).parent
TESTSET = Path(__file__).resolve().parents[3] / "data" / "testdata" / "qna_testset.json"
RESULTS = _HERE / "results.json"


def load_cases() -> list[dict]:
    return json.loads(TESTSET.read_text(encoding="utf-8"))


def load_results() -> list[dict]:
    return json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else []


def save_results(rows: list[dict]) -> None:
    RESULTS.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _summarize_sources(docs: list[dict] | None) -> list[str]:
    """격리 증명용 — 검색된 문서 source만 뽑는다(질의회신 잔존 검사)."""
    return [str(d.get("source", "")) for d in (docs or [])]


def run(case_ids: list[str] | None = None) -> None:
    cases = load_cases()
    if case_ids:
        cases = [c for c in cases if c["id"] in case_ids]
    rows = load_results()
    done = {r["id"] for r in rows}

    print(f"=== QNA-off 홀드아웃 {len(cases)}건 (완료 {len(done)}) ===")
    for c in cases:
        if c["id"] in done:
            print(f"  [SKIP] {c['id']}")
            continue
        print(f"  [{c['id']}] {c['title'][:24]} ... ", end="", flush=True)
        # 한 건이 timeout/네트워크 예외로 죽어도 전체 중단 금지 — error로 기록하고 계속
        try:
            event, elapsed = call_chat(c["question"])
        except Exception as e:
            event, elapsed = {"type": "error", "message": str(e)}, 0.0
        docs = event.get("retrieved_docs", [])
        rows.append(
            {
                "id": c["id"],
                "title": c["title"],
                "category": c["category"],
                "question": c["question"],
                "answer_gold": c["answer_gold"],
                "gold_cited": c.get("cited_paragraphs", []),
                "answer_text": event.get("text", ""),
                "resp_cited": event.get("cited_paragraphs", []),
                "retrieved_sources": _summarize_sources(docs),
                "response_time": round(elapsed, 2),
                "error": event.get("message") if event.get("type") == "error" else None,
            }
        )
        save_results(rows)
        status = "ERROR" if rows[-1]["error"] else "OK"
        print(f"{status} ({elapsed:.1f}s)")

    errors = [r["id"] for r in rows if r.get("error")]
    print(f"\n완료 {len(rows)}건, 에러 {len(errors)}건 {errors or ''}")
    print(f"→ {RESULTS}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=str, default="", help="쉼표구분 id (기본 전체)")
    args = ap.parse_args()
    ids = [x.strip() for x in args.cases.split(",") if x.strip()] or None
    run(ids)


if __name__ == "__main__":
    main()

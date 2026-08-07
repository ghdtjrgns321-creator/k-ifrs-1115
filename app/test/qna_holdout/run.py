"""eval-v2 홀드아웃 러너 — qna_testset 92건을 QNA-off 파이프라인에 통과시켜 응답 수집.

서버를 exclude_qna=ON(EXCLUDE_QNA=1)로 띄운 뒤 실행해야 QNA 격리가 적용된다.
격리 위반(질의회신 문서가 검색됨)은 첫 발생 즉시 중단한다 — 오염된 회차를 끝까지 돌려봐야
버려야 하고, 살려두면 나중에 섞인다.

채점은 하지 않는다. 여기선 회차별 원자료만 남긴다:
  routing          ① 진입 지표 — "IN"이 아니면 범위 밖 거절
  retrieved_paras  ② 회수 지표 — LLM이 실제로 읽은 컨텍스트의 1115호 문단 번호
  answer_text      ③ 결론 지표 — judge_binary.py가 소비

**결과 파일은 회차별로 분리한다.** `runs/run{N}.json`. 덮어쓰기가 없으므로 리포에 남은
수치의 출처를 항상 되짚을 수 있다(구 `results.json`은 이게 없어 78·80·85·87이 공존했다).

실행:
  # 서버 (별도 셸): EXCLUDE_QNA=1 PYTHONPATH=. uv run --env-file .env \
  #   uvicorn app.main:app --port 8002
  PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/run.py --run 1
  PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/run.py --run 1 --cases QNA-SSI-38677
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.test.qna_holdout.sse_client import call_chat
from app.ui.constants import SRC_QNA, SRC_QNA_SHORT

_HERE = Path(__file__).parent
_ROOT = Path(__file__).resolve().parents[3]
TESTSET = _ROOT / "data" / "testdata" / "qna_testset.json"
RUNS_DIR = _HERE / "runs"

# 격리 위반 감지용 — 이 source가 컨텍스트에 있으면 QNA-off가 안 걸린 것
_QNA_SOURCES = {SRC_QNA, SRC_QNA_SHORT}


def run_path(n: int) -> Path:
    return RUNS_DIR / f"run{n}.json"


def load_cases() -> list[dict]:
    return json.loads(TESTSET.read_text(encoding="utf-8"))


def load_rows(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def save_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _paras(docs: list[dict] | None) -> list[str]:
    """LLM 컨텍스트에 들어온 1115호 문단 번호. 사례 문서는 para_num이 ""라 자동 제외.

    hierarchy 문자열을 정규식으로 긁지 않는다 — 문단 번호는 API가 para_num으로 그대로 준다.
    """
    seen: list[str] = []
    for d in docs or []:
        p = str(d.get("para_num", "")).strip()
        if p and p not in seen:
            seen.append(p)
    return seen


def _qna_leak(docs: list[dict] | None) -> list[str]:
    return [
        str(d.get("chunk_id", ""))
        for d in docs or []
        if str(d.get("source", "")) in _QNA_SOURCES
    ]


def run(n: int, case_ids: list[str] | None = None) -> None:
    path = run_path(n)
    cases = load_cases()
    if case_ids:
        cases = [c for c in cases if c["id"] in case_ids]
    rows = load_rows(path)
    done = {r["id"] for r in rows}

    print(
        f"=== eval-v2 홀드아웃 run{n} — {len(cases)}건 (완료 {len(done)}) → {path.name}"
    )
    for c in cases:
        if c["id"] in done:
            print(f"  [SKIP] {c['id']}")
            continue
        print(f"  [{c['id']}] {c['title'][:24]} ... ", end="", flush=True)
        # 한 건이 timeout/네트워크 예외로 죽어도 전체 중단 금지 — error로 기록하고 계속
        event: dict
        try:
            event, elapsed = call_chat(c["question"])
        except Exception as e:
            event, elapsed = {"type": "error", "message": str(e)}, 0.0
        docs: list[dict] = event.get("retrieved_docs") or []

        leak = _qna_leak(docs)
        if leak:
            save_rows(path, rows)
            raise SystemExit(
                f"\n격리 위반 — {c['id']}에서 질의회신 문서가 검색됐다: {leak[:3]}\n"
                "서버를 EXCLUDE_QNA=1로 다시 띄우고, 이 회차 파일을 지운 뒤 처음부터 돌려라."
            )

        rows.append(
            {
                "id": c["id"],
                "title": c["title"],
                "category": c["category"],
                "question": c["question"],
                "answer_gold": c["answer_gold"],
                "routing": event.get("routing"),
                "answer_text": event.get("text", ""),
                "resp_cited": event.get("cited_paragraphs") or [],
                "retrieved_paras": _paras(docs),
                "retrieved_sources": [str(d.get("source", "")) for d in docs],
                "response_time": round(elapsed, 2),
                "error": event.get("message") if event.get("type") == "error" else None,
            }
        )
        save_rows(path, rows)
        r = rows[-1]
        status = "ERROR" if r["error"] else ("REJECT" if r["routing"] != "IN" else "OK")
        print(f"{status} 문단{len(r['retrieved_paras'])} ({elapsed:.1f}s)")

    errors = [r["id"] for r in rows if r.get("error")]
    rejected = [
        r["id"] for r in rows if r.get("routing") != "IN" and not r.get("error")
    ]
    print(f"\n완료 {len(rows)}건 · 에러 {len(errors)} {errors or ''}")
    print(f"거절(routing!=IN) {len(rejected)}건 {rejected or ''}")
    print(f"→ {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=int, required=True, help="회차 번호 (1,2,3)")
    ap.add_argument("--cases", type=str, default="", help="쉼표구분 id (기본 전체)")
    args = ap.parse_args()
    ids = [x.strip() for x in args.cases.split(",") if x.strip()] or None
    run(args.run, ids)


if __name__ == "__main__":
    main()

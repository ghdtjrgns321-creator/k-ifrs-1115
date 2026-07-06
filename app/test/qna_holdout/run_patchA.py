"""A안(문단 상한 제거) 검증 — 미재현 17건만 재실행해 하드 재현율 before/after 대조.

before = 직전 코드 상태(results.json, subtree 개선까지 반영) 하드
after  = 이 스크립트가 새 서버(doc_slot_para=0)로 호출한 하드
둘 다 grade.hard_recall 동일 지표. baseline(results.json) 미변경.

실행(서버 EXCLUDE_QNA=1·doc_slot_para=0 기동 후):
  PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/run_patchA.py
"""

from __future__ import annotations

import json
from pathlib import Path

from app.test.qna_holdout.sse_client import call_chat
from app.test.qna_holdout.grade import hard_recall

_HERE = Path(__file__).parent
BEFORE = _HERE / "results.json"  # 직전 상태(A안 전)
OUT = _HERE / "results_patchA.json"

# 미재현 17건 (report.md 미재현 표)
IDS = [
    "QNA-2018-I-KQA004",
    "QNA-2018-I-KQA009-Q1",
    "QNA-2018-I-KQA009-Q2",
    "QNA-201803A",
    "QNA-2019-I-KQA009-Q1",
    "QNA-201906D",
    "QNA-201909A",
    "QNA-2020-I-KQA006-Q1",
    "QNA-202003D",
    "QNA-2021-I-KQA008",
    "QNA-2022-I-KQA007",
    "QNA-2024-I-KQA005",
    "QNA-SSI-202412041",
    "QNA-SSI-202412043",
    "QNA-SSI-202503008",
    "QNA-SSI-36904",
    "QNA-SSI-38697",
]


def main() -> None:
    before = {r["id"]: r for r in json.loads(BEFORE.read_text(encoding="utf-8"))}
    prev = (
        {r["id"]: r for r in json.loads(OUT.read_text(encoding="utf-8"))}
        if OUT.exists()
        else {}
    )
    rows = list(prev.values())
    done = set(prev)

    for cid in IDS:
        if cid in done:
            print(f"  [SKIP] {cid}")
            continue
        b = before.get(cid, {})
        gold = b.get("gold_cited", [])
        q = b.get("question", "")
        print(f"  [{cid}] ... ", end="", flush=True)
        try:
            event, elapsed = call_chat(q)
        except Exception as e:
            event, elapsed = {"type": "error", "message": str(e)}, 0.0
        docs = event.get("retrieved_docs", [])

        def _is_para(d: dict) -> bool:
            s = str(d.get("source", ""))
            return s != "적용사례IE" and "감리" not in s and "질의" not in s

        n_para = sum(1 for d in docs if isinstance(d, dict) and _is_para(d))
        rows.append(
            {
                "id": cid,
                "gold_cited": gold,
                "resp_cited": event.get("cited_paragraphs", []),
                "answer_text": event.get("text", ""),
                "n_docs": len(docs),
                "n_para_ctx": n_para,
                "response_time": round(elapsed, 2),
                "error": event.get("message") if event.get("type") == "error" else None,
            }
        )
        OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        st = "ERROR" if rows[-1]["error"] else "OK"
        print(f"{st} ({elapsed:.1f}s, docs={len(docs)})")

    # 대조 출력
    after = {r["id"]: r for r in rows}
    print("\n=== 하드 재현율 before/after (분모 17) ===")
    print(f"{'id':24} before  after")
    sb = sa = 0.0
    nb = na = 0
    for cid in IDS:
        gb = before[cid]["gold_cited"]
        hb = hard_recall(gb, before[cid]["resp_cited"])
        ha = hard_recall(after[cid]["gold_cited"], after[cid]["resp_cited"])
        if hb is not None:
            sb += hb
            nb += 1
        if ha is not None:
            sa += ha
            na += 1
        fb = f"{hb:.0%}" if hb is not None else "-"
        fa = f"{ha:.0%}" if ha is not None else "-"
        arrow = (
            "▲"
            if (hb is not None and ha is not None and ha > hb)
            else ("▼" if (hb is not None and ha is not None and ha < hb) else "=")
        )
        print(f"{cid:24} {fb:>5}  {fa:>5} {arrow}")
    print(f"\n평균 before {sb / nb:.1%}(N{nb}) → after {sa / na:.1%}(N{na})")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()

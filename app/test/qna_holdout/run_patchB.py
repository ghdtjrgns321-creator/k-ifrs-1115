"""변경1(라우팅 재균형)+변경2(일관성 검증) 검증 — 미재현 17건 재실행.

각 답변의 구조 신호를 분류한다:
- 강등: "[검증 경고]" 포함 → 검증이 모순 감지해 유보 강등(오답 2건 기대)
- 조건부: Case/⚠️/Gray Area 포함 → 유보(일치 조건부 6건은 유지 기대)
- 확정: 그 외 → 확정 결론(유보 9건이 확정 전환 기대)

실행(서버 EXCLUDE_QNA=1·신코드 기동 후):
  PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/run_patchB.py
"""

from __future__ import annotations

import json
from pathlib import Path

from app.test.qna_holdout.sse_client import call_chat

_HERE = Path(__file__).parent
BEFORE = _HERE / "results.json"
OUT = _HERE / "results_patchB.json"

ODAP = ["QNA-2022-I-KQA007", "QNA-SSI-38697"]
YUBO = [
    "QNA-2018-I-KQA009-Q1",
    "QNA-201803A",
    "QNA-2019-I-KQA009-Q1",
    "QNA-201906D",
    "QNA-201909A",
    "QNA-2020-I-KQA006-Q1",
    "QNA-202003D",
    "QNA-2021-I-KQA008",
    "QNA-SSI-202412043",
]
ILCHI = [
    "QNA-2018-I-KQA004",
    "QNA-2018-I-KQA009-Q2",
    "QNA-2024-I-KQA005",
    "QNA-SSI-202412041",
    "QNA-SSI-202503008",
    "QNA-SSI-36904",
]
GROUP = {
    **{i: "오답" for i in ODAP},
    **{i: "유보" for i in YUBO},
    **{i: "일치" for i in ILCHI},
}
IDS = ODAP + YUBO + ILCHI


def classify(answer: str) -> str:
    if "[검증 경고]" in answer:
        return "강등"
    if any(
        m in answer
        for m in ("Case 1", "Case 2", "⚠️", "전문가 판단 필요", "Gray Area", "확인 질문")
    ):
        return "조건부"
    return "확정"


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
        q = before.get(cid, {}).get("question", "")
        print(f"  [{GROUP[cid]}:{cid}] ... ", end="", flush=True)
        try:
            event, elapsed = call_chat(q)
        except Exception as e:
            event, elapsed = {"type": "error", "message": str(e)}, 0.0
        answer = event.get("text", "")
        rows.append(
            {
                "id": cid,
                "group": GROUP[cid],
                "type": classify(answer),
                "answer_text": answer,
                "resp_cited": event.get("cited_paragraphs", []),
                "response_time": round(elapsed, 2),
                "error": event.get("message") if event.get("type") == "error" else None,
            }
        )
        OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        st = "ERROR" if rows[-1]["error"] else classify(answer)
        print(f"{st} ({elapsed:.1f}s)")

    # 집계
    after = {r["id"]: r for r in rows}
    print("\n=== 구조 신호 (분모: 그룹별) ===")
    for grp, ids in (("오답", ODAP), ("유보", YUBO), ("일치", ILCHI)):
        types = [after[i]["type"] for i in ids if i in after]
        print(
            f"[{grp}] "
            + " · ".join(f"{t}:{types.count(t)}" for t in ("확정", "조건부", "강등"))
            + f" (N{len(types)})"
        )
    print("\n케이스별:")
    for cid in IDS:
        if cid in after:
            print(f"  {GROUP[cid]:4} {cid:24} → {after[cid]['type']}")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()

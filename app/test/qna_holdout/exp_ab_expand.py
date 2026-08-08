"""개념 넓히기 A/B 집계 — 두 회차 원자료를 하나의 재사용 가능한 산출물로 굳힌다.

    PYTHONPATH=. uv run python app/test/qna_holdout/exp_ab_expand.py

입력  runs/run_none.json · runs/run_kin1.json   (run.py가 남긴 원자료)
출력  ab_expand.json                            (집계 + 케이스별 표)

Why(별도 파일): 원자료는 회차 파일이 정본이고, 여기서 만드는 건 파생 지표다.
    채점(judge_binary.py)·보고서·문서가 같은 숫자를 쓰도록 한 곳에서 계산한다.

**여기서 재는 것은 회수뿐이다.** 회수만 보면 넓은 쪽이 항상 이긴다 —
규칙 확정은 답 품질 채점(judge_binary.py)이 한다. 이 파일은 그 옆에 놓는 참고치다.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

from app.test.qna_holdout import exp_common as EC

HERE = Path(__file__).parent
RUNS = HERE / "runs"
OUT = HERE / "ab_expand.json"

CONDS = {"none": "run_none.json", "kin1": "run_kin1.json"}
# 회수 집계에서 나눠 볼 출처. run.py가 이미 결론도출근거(BC)를 문단 회수에서 뺀다.
SRC_KEYS = ["본문", "적용지침B", "적용사례IE", "감리사례", "결론도출근거", "질의회신"]


def load(path: Path) -> dict[str, dict]:
    rows = json.loads(path.read_text("utf-8"))
    return {r["id"]: r for r in rows}


def per_case(rows: dict[str, dict], gold: dict[str, set[str]]) -> dict[str, dict]:
    out = {}
    for cid, r in rows.items():
        got = {EC.norm_para(p) for p in r.get("retrieved_paras", [])}
        g = {EC.norm_para(p) for p in gold.get(cid, set())}
        src = collections.Counter(r.get("retrieved_sources") or [])
        out[cid] = {
            "routing": r.get("routing"),
            "error": r.get("error"),
            "paras": len(r.get("retrieved_paras", [])),
            "gold_hit": len(g & got),
            "gold_total": len(g),
            "gold_missed": sorted(g - got),
            "answer_chars": len(r.get("answer_text") or ""),
            "sources": {k: src.get(k, 0) for k in SRC_KEYS if src.get(k)},
        }
    return out


def agg(cases: dict[str, dict]) -> dict:
    n = len(cases) or 1
    src = collections.Counter()
    for c in cases.values():
        src.update(c["sources"])
    return {
        "n": len(cases),
        "routing_in": sum(1 for c in cases.values() if c["routing"] == "IN"),
        "errors": sum(1 for c in cases.values() if c["error"]),
        "gold_hit": sum(c["gold_hit"] for c in cases.values()),
        "gold_total": sum(c["gold_total"] for c in cases.values()),
        "paras_avg": round(sum(c["paras"] for c in cases.values()) / n, 1),
        # retrieved_paras에는 IE 문단번호(IE23…)가 섞인다. 기준서 문단만 따로 센 값이
        # exp_expand.py·results-traverse.md의 "문단" 수치와 같은 자다.
        "paras_std_avg": round((src["본문"] + src["적용지침B"]) / n, 1),
        "paras_ie_avg": round(src["적용사례IE"] / n, 1),
        "answer_chars_avg": round(sum(c["answer_chars"] for c in cases.values()) / n),
        "docs_avg": {k: round(v / n, 1) for k, v in src.items()},
    }


def main() -> None:
    gold = EC.gold_paras(essential_only=True)
    data: dict[str, dict] = {}
    for cond, fname in CONDS.items():
        p = RUNS / fname
        if not p.exists():
            print(f"  [없음] {p} — 건너뜀")
            continue
        cases = per_case(load(p), gold)
        data[cond] = {"source": f"runs/{fname}", "summary": agg(cases), "cases": cases}

    # 케이스별 회수 차이 — 어느 질문이 넓히기로 갈렸는지
    deltas = []
    if len(data) == 2:
        a, b = data["none"]["cases"], data["kin1"]["cases"]
        for cid in sorted(set(a) & set(b)):
            d = b[cid]["gold_hit"] - a[cid]["gold_hit"]
            if d:
                deltas.append(
                    {
                        "id": cid,
                        "gold_total": a[cid]["gold_total"],
                        "none": a[cid]["gold_hit"],
                        "kin1": b[cid]["gold_hit"],
                        "delta": d,
                    }
                )

    OUT.write_text(
        json.dumps(
            {
                "_meta": {
                    "generated_by": "app/test/qna_holdout/exp_ab_expand.py",
                    "gold": "gold_paragraphs.json 필수(essential) 1115호 문단",
                    "note": "회수 지표만. 규칙 확정은 judge_binary.py 답 품질 채점이 한다",
                    "bc": "BC 문단은 LLM이 안 읽으므로 run.py가 문단 회수에서 제외",
                    "caveat": (
                        "두 회차는 진입까지 새로 돈다. 진입 LLM이 결정적이지 않아 "
                        "케이스별 gold 회수 감소는 넓히기 탓이 아닐 수 있다. "
                        "진입을 고정한 비교는 expand.json(exp_expand.py)에 있다"
                    ),
                },
                "conditions": data,
                "gold_delta_by_case": deltas,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"{'조건':6}{'건':>5}{'IN':>5}{'에러':>5}{'gold회수':>10}"
        f"{'기준서문단':>11}{'IE문단':>8}{'답변자수':>9}"
    )
    for cond, d in data.items():
        s = d["summary"]
        print(
            f"{cond:6}{s['n']:>5}{s['routing_in']:>5}{s['errors']:>5}"
            f"{s['gold_hit']:>6}/{s['gold_total']:<3}"
            f"{s['paras_std_avg']:>11}{s['paras_ie_avg']:>8}{s['answer_chars_avg']:>9}"
        )
    for cond, d in data.items():
        print(f"  {cond:6} 문서/질문 {d['summary']['docs_avg']}")
    if deltas:
        up = [x for x in deltas if x["delta"] > 0]
        down = [x for x in deltas if x["delta"] < 0]
        print(
            f"\ngold 회수가 갈린 질문 {len(deltas)}건 · kin1 우세 {len(up)} · none 우세 {len(down)}"
        )
        for x in deltas:
            print(f"  {x['id']:16} {x['none']}→{x['kin1']} /{x['gold_total']}")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()

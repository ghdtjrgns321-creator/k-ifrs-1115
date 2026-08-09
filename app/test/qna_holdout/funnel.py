"""퍼널 집계 — 회차 원자료와 채점 결과에서 공시 수치를 뽑는다.

문서·README의 숫자를 손으로 옮기지 않는다. 여기서 나온 값만 쓴다.
분모는 gold 라벨(`gold_paragraphs.json`)이 정한다 — `scope`가 붙은 항목은 전부 분모 밖.

  ① 라우팅   질문이 파이프라인에 들어갔나 (routing == "IN")
  ② 회수     정답이 근거로 든 필수 문단이 LLM 컨텍스트에 들어왔나
  ③ 결론     답이 정답과 같은 방향인가 (v4 이진 판정)

②는 ①을 통과한 건에서만 성립한다 — 거절된 케이스는 검색 자체가 없다.
그래서 단계별 분모가 다르고, 그게 "성능이 어디서 새는지"를 보여준다.

실행: PYTHONPATH=. uv run python app/test/qna_holdout/funnel.py
"""

from __future__ import annotations

import json
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = Path(__file__).resolve().parents[3]
_GOLD = _ROOT / "data" / "testdata" / "gold_extract" / "gold_paragraphs.json"
_SCORES = _HERE / "judge_r3_scores.json"
RUNS = ("run_none", "run_none2", "run_none3")


def _load_gold() -> tuple[dict[str, list[str]], set[str]]:
    """(케이스 → 필수 문단, 결론 채점 대상 케이스). scope 붙은 건 전부 분모 밖."""
    gold = json.loads(_GOLD.read_text("utf-8"))
    scored = {c["id"] for c in gold if c.get("scope") != "excluded"}
    ess = {}
    for c in gold:
        if c["id"] not in scored:
            continue
        ps = [
            p["para"]
            for p in c["paragraphs"]
            if p["standard"] == "1115" and p.get("essential") and not p.get("scope")
        ]
        if ps:
            ess[c["id"]] = ps
    return ess, scored


def main() -> None:
    ess, scored = _load_gold()
    total_paras = sum(len(v) for v in ess.values())
    scores = json.loads(_SCORES.read_text("utf-8"))["scores"]

    rows = {
        r: {
            x["id"]: x
            for x in json.loads((_HERE / "runs" / f"{r}.json").read_text("utf-8"))
        }
        for r in RUNS
    }

    print(
        f"분모 — 결론 {len(scored)}케이스 · 회수 {len(ess)}케이스 / {total_paras}문단\n"
    )
    print(f"{'회차':12} {'①라우팅':>10} {'②회수':>14} {'③결론':>13}")

    agg = {"routing": [], "recall": [], "concl": []}
    for r in RUNS:
        data = rows[r]
        in_ = [i for i in scored if data[i].get("routing") == "IN"]
        hit = sum(
            1
            for cid, ps in ess.items()
            for p in ps
            if p in set(data[cid]["retrieved_paras"])
        )
        con = sum(v[r] for v in scores.values())
        agg["routing"].append(len(in_))
        agg["recall"].append(hit)
        agg["concl"].append(con)
        print(
            f"{r:12} {len(in_):>4}/{len(scored)} {len(in_) / len(scored):>5.1%}"
            f" {hit:>6}/{total_paras} {hit / total_paras:>6.1%}"
            f" {con:>5}/{len(scored)} {con / len(scored):>6.1%}"
        )

    # 재현되는 실패 = 3회 모두 실패. 흔들리는 실패와 구분해야 원인을 볼 수 있다.
    print()
    rej = sorted(
        i for i in scored if all(rows[r][i].get("routing") != "IN" for r in RUNS)
    )
    fail = sorted(i for i, v in scores.items() if sum(v.values()) == 0)
    split = sorted(i for i, v in scores.items() if 0 < sum(v.values()) < len(RUNS))
    # 분모가 164 문단-케이스 쌍이므로 쌍으로 센다. 문단 번호만 모으면 같은 번호가
    # 다른 케이스에서 놓친 것이 합쳐져 실제보다 적게 나온다.
    never = sorted(
        f"{cid}:{p}"
        for cid, ps in ess.items()
        for p in ps
        if all(p not in set(rows[r][cid]["retrieved_paras"]) for r in RUNS)
    )
    print(f"3회 모두 거절   {len(rej)}건 {rej}")
    print(f"3회 모두 오답   {len(fail)}건 {fail}")
    print(f"회차별로 갈림   {len(split)}건 {split}")
    print(f"3회 모두 미회수 문단 {len(never)}개 {never}")

    out = _HERE / "funnel.json"
    out.write_text(
        json.dumps(
            {
                "runs": list(RUNS),
                "denominator": {
                    "conclusion_cases": len(scored),
                    "recall_cases": len(ess),
                    "essential_paras": total_paras,
                },
                "per_run": agg,
                "always_rejected": rej,
                "always_wrong": fail,
                "unstable": split,
                "never_retrieved_paras": never,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()

"""STEP 1 판정 — baseline/cosine/selector hit-rate 대조 + 채택 결정.

hit = gold개념 ∩ 후보개념 ≠ ∅. 분모 = dev-with-gold(57).
채택기준: (baseline ∪ 후보)의 hit-rate가 baseline 대비 순증(Δ>0)이면 그 후보 채택.
둘 다 Δ≤0이면 STEP 1 폐기. cosine/selector 모두 순증이면 Δ 큰 쪽(동률시 결정적인 cosine).

산출: exp_decision.md
"""

from __future__ import annotations

from pathlib import Path
from statistics import mean

from app.test.qna_holdout import exp_common as C

_HERE = Path(__file__).parent
A_BUCKET = ["QNA-SSI-38676", "QNA-SSI-38680"]  # 진입누락 — 개념포착 개별 추적


def _rate(hit: int, n: int) -> str:
    return f"{hit}/{n} ({100 * hit / n:.1f}%)"


def main() -> None:
    cases = C.dev_gold_cases()
    gold = {cid: gc for cid, _c, gc in cases}
    ids = [cid for cid, _c, _gc in cases]
    N = len(cases)

    baseline = C.load_json(_HERE / "exp_baseline.json")
    cosine = C.load_json(_HERE / "exp_cosine.json")
    selector = C.load_json(_HERE / "exp_selector.json")

    # baseline: 회차별 concept_ids
    def base_cand(rnd, cid):
        return set(baseline["rounds"][rnd].get(cid, {}).get("concept_ids", []))

    def base_union_cid(cid):  # 회차 합집합(케이스별 최대 진입)
        s = set()
        for rnd in range(len(baseline["rounds"])):
            s |= base_cand(rnd, cid)
        return s

    # 회차별 baseline hit-rate
    base_rates = []
    for rnd in range(len(baseline["rounds"])):
        hit = sum(1 for cid in ids if gold[cid] & base_cand(rnd, cid))
        base_rates.append(hit)
    base_avg = mean(base_rates)
    # 판정 기준선: 회차합집합 baseline(케이스별 3회 중 한 번이라도 진입) — 안정적 상한
    base_hit_union = sum(1 for cid in ids if gold[cid] & base_union_cid(cid))

    # cosine@k + union
    def cos_topk(cid, k):
        return set(cosine.get(cid, {}).get("top7", [])[:k])

    cos_rows = {}
    for k in (3, 5, 7):
        cos_hit = sum(1 for cid in ids if gold[cid] & cos_topk(cid, k))
        uni_hit = sum(
            1 for cid in ids if gold[cid] & (base_union_cid(cid) | cos_topk(cid, k))
        )
        cos_rows[k] = (cos_hit, uni_hit)

    # selector: 회차별 + 회차합집합 union
    def sel_cand(rnd, cid):
        return set(selector["rounds"][rnd].get(cid, {}).get("concept_ids", []))

    def sel_union_cid(cid):
        s = set()
        for rnd in range(len(selector["rounds"])):
            s |= sel_cand(rnd, cid)
        return s

    sel_rates = []
    for rnd in range(len(selector["rounds"])):
        hit = sum(1 for cid in ids if gold[cid] & sel_cand(rnd, cid))
        sel_rates.append(hit)
    sel_avg = mean(sel_rates)
    sel_uni_hit = sum(
        1 for cid in ids if gold[cid] & (base_union_cid(cid) | sel_union_cid(cid))
    )

    # A버킷 개별 추적
    a_track = []
    for aid in A_BUCKET:
        loc = "dev" if aid in ids else "test(held-out)"
        gc = gold.get(aid, C.gold_concepts(C.testset_map()[aid], C.para_to_concept()))
        if aid in ids:
            in_base = bool(gc & base_union_cid(aid))
            in_cos = bool(gc & cos_topk(aid, 7))
            in_sel = bool(gc & sel_union_cid(aid))
            a_track.append(
                f"- {aid} ({loc}, gold={sorted(gc)}): baseline={in_base}, cosine@7={in_cos}, selector={in_sel}"
            )
        else:
            a_track.append(f"- {aid} ({loc}, gold={sorted(gc)}): dev 밖 — 판정 제외")

    # 채택 판정
    best_cos_k = max((3, 5, 7), key=lambda k: cos_rows[k][1])
    cos_union_best = cos_rows[best_cos_k][1]
    d_cos = cos_union_best - base_hit_union
    d_sel = sel_uni_hit - base_hit_union
    if d_cos <= 0 and d_sel <= 0:
        verdict = f"**STEP 1 폐기** — cosine Δ={d_cos}, selector Δ={d_sel} 모두 순증 없음. baseline이 이미 상한."
    elif d_cos >= d_sel:
        verdict = f"**코사인 채택 (k={best_cos_k})** — union hit {base_hit_union}→{cos_union_best} (Δ+{d_cos}), selector Δ+{d_sel}."
    else:
        verdict = f"**LLM 선택기 채택** — union hit {base_hit_union}→{sel_uni_hit} (Δ+{d_sel}), cosine Δ+{d_cos}."

    md = [
        "# STEP 1 진입 재현율 실험 — 판정",
        "",
        f"분모 = dev-with-gold **{N}건**. hit = gold개념 ∩ 후보개념 ≠ ∅.",
        "baseline 기준선은 3회 합집합(케이스별 한 번이라도 진입)으로 안정화.",
        "",
        "## hit-rate 대조",
        "",
        "| 후보 | hit-rate |",
        "|---|---|",
        f"| baseline (회차평균) | {_rate(round(base_avg), N)} (회차별 {base_rates}) |",
        f"| baseline (3회 합집합, 기준선) | {_rate(base_hit_union, N)} |",
        f"| cosine@3 단독 | {_rate(cos_rows[3][0], N)} |",
        f"| cosine@5 단독 | {_rate(cos_rows[5][0], N)} |",
        f"| cosine@7 단독 | {_rate(cos_rows[7][0], N)} |",
        f"| baseline ∪ cosine@3 | {_rate(cos_rows[3][1], N)} |",
        f"| baseline ∪ cosine@5 | {_rate(cos_rows[5][1], N)} |",
        f"| baseline ∪ cosine@7 | {_rate(cos_rows[7][1], N)} |",
        f"| selector (회차평균) | {_rate(round(sel_avg), N)} (회차별 {sel_rates}) |",
        f"| baseline ∪ selector(3회합) | {_rate(sel_uni_hit, N)} |",
        "",
        "## A버킷(진입누락) 개념 포착 추적",
        "",
        *a_track,
        "",
        "## 판정",
        "",
        verdict,
    ]
    (_HERE / "exp_decision.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\n→ {_HERE / 'exp_decision.md'}")


if __name__ == "__main__":
    main()

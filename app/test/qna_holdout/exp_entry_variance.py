"""진입 흔들림의 통로 분해 + 용어사전 입력 원문 전환 시뮬레이션. LLM 호출 0.

analyze는 그래프에 두 값을 넘긴다(analyze.py:56-59).
  (a) topic_hints      → via_topic (exp_baseline.json에 회차별 기록됨)
  (b) standalone_query → resolve_terms(substring) → 개념

resolve_question의 concept_ids = via_topic + _adaptive_subtree 확장 + resolve_terms.
앞 둘은 via_topic만 있으면 결정적으로 재계산되므로, 나머지(residual)가 (b)의 몫이다.
이를 이용해 회차간 변동이 어느 통로에서 오는지 가른다.

시뮬레이션: (b)의 입력을 재작성문 대신 사용자 원문으로 바꿨을 때의 후보집합
  = set(expand(기록된 via_topic)) | resolve_terms(원문)
via_topic은 양쪽 동일하므로 (b) 채널만의 효과가 분리된다.

실행: PYTHONPATH=. uv run python app/test/qna_holdout/exp_entry_variance.py
"""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.graph import get_graph
from app.test.qna_holdout import exp_common as C

BASELINE = Path(__file__).parent / "exp_baseline.json"

_g = get_graph()


def expand(via: list[str]) -> list[str]:
    """resolve_question의 결정적 확장부를 그대로 재현."""
    out = list(via)
    for c in via:
        for e in _g._adaptive_subtree(c):
            if e not in out:
                out.append(e)
    return out


def load_rows():
    """(id, gold개념, 원문사전결과, [(via, 실제후보, 원문가정후보)] x3)."""
    b = json.loads(BASELINE.read_text(encoding="utf-8"))
    ts = C.testset_map()
    gold = {cid: gc for cid, _, gc in C.dev_gold_cases()}
    rows = []
    for cid in b["cases"]:
        gc = gold.get(cid)
        if not gc:
            continue
        r = _g.resolve_terms(ts[cid]["question"])
        raw = set(r["concept_ids"])
        per = []
        for rnd in b["rounds"]:
            d = rnd.get(cid) or {}
            via = d.get("via_topic") or []
            per.append(
                (
                    frozenset(via),
                    frozenset(d.get("concept_ids") or []),
                    frozenset(set(expand(via)) | raw),
                )
            )
        rows.append((cid, gc, r["matched_terms"], raw, per))
    return rows


def premise_check(rows) -> None:
    """분해의 전제 — 지금 온톨로지 확장 집합이 캡처본에 포함되나(순서는 무관)."""
    ok = bad = 0
    for _cid, _gc, _t, _raw, per in rows:
        for via, actual, _sim in per:
            if not via:
                continue
            det = set(expand(sorted(via)))
            ok, bad = (ok + 1, bad) if det <= set(actual) else (ok, bad + 1)
    print(f"[전제] 확장집합 포함 성립 {ok} / 깨짐 {bad}  (깨지면 이하 수치 무효)")


def channel_split(rows) -> None:
    """회차간 변동이 주제지목(a)에서 오나 용어매칭(b)에서 오나."""
    n = len(rows)
    same_all = same_via = same_res = 0
    via_only = res_only = both = 0
    for _cid, _gc, _t, _raw, per in rows:
        vias = {p[0] for p in per}
        residuals = {frozenset(p[1] - set(expand(sorted(p[0])))) for p in per}
        alls = {p[1] for p in per}
        v, r, a = len(vias) == 1, len(residuals) == 1, len(alls) == 1
        same_via, same_res, same_all = same_via + v, same_res + r, same_all + a
        if not a:
            both += not v and not r
            via_only += not v and r
            res_only += v and not r
    print(f"\n[통로 분해] N={n}")
    print(f"  진입 개념집합 3회 동일        : {same_all}/{n} ({same_all / n:.1%})")
    print(f"  주제지목(via_topic) 3회 동일  : {same_via}/{n} ({same_via / n:.1%})")
    print(f"  용어매칭 잔여분 3회 동일      : {same_res}/{n} ({same_res / n:.1%})")
    print(
        f"  흔들린 {n - same_all}건 분해 — 주제만 {via_only} · 용어만 {res_only} · 둘다 {both}"
    )


def compare(rows) -> None:
    """실제(사전입력=재작성문) vs 가정(사전입력=원문)."""
    n = len(rows)
    for label, idx in (("실제 (사전입력=재작성문)", 1), ("가정 (사전입력=원문)", 2)):
        print(f"\n[{label}]")
        for ri in range(3):
            hit = cov = 0.0
            size = 0
            for _cid, gc, _t, _raw, per in rows:
                cand = per[ri][idx]
                inter = gc & cand
                hit += 1 if inter else 0
                cov += len(inter) / len(gc)
                size += len(cand)
            print(
                f"  회차{ri + 1}  hit {hit:.0f}/{n} ({hit / n:.1%})"
                f" · 커버리지 {cov / n:.1%} · 평균후보 {size / n:.1f}개"
            )
        same = sum(1 for r in rows if len({r[4][i][idx] for i in range(3)}) == 1)
        print(f"  3회 동일 : {same}/{n} ({same / n:.1%})")


def losses(rows) -> None:
    """원문 전환으로 맞힘→놓침이 되는 케이스와 잃는 개념."""
    titles = {k: v.get("title", "") for k, v in _g.concepts.items()}
    flip, cnt = [], {}
    for cid, gc, terms, _raw, per in rows:
        for ri, (_via, actual, sim) in enumerate(per):
            for x in gc & (actual - sim):
                cnt[titles.get(x, x)] = cnt.get(titles.get(x, x), 0) + 1
            if (gc & actual) and not (gc & sim):
                flip.append((cid, ri + 1, terms))
    ids = sorted({c for c, _, _ in flip})
    print(f"\n[손실] 맞힘→놓침 (케이스,회차) {len(flip)}건 · 케이스 {len(ids)}개")
    for cid in ids:
        t = next(t for c, _, t in flip if c == cid)
        print(f"  {cid}  원문 사전매칭 {t or '(없음)'}")
    print("  잃은 정답개념 빈도")
    for k, v in sorted(cnt.items(), key=lambda kv: -kv[1]):
        print(f"    {v:>2}회  {k}")
    zero = sum(1 for r in rows if not r[2])
    print(f"\n  원문으로 사전에 한 건도 안 걸린 케이스: {zero}/{len(rows)}")


if __name__ == "__main__":
    _rows = load_rows()
    print(f"대상 {len(_rows)}건 (gold 개념 매핑되고 3회 기록된 dev 케이스)")
    premise_check(_rows)
    channel_split(_rows)
    compare(_rows)
    losses(_rows)

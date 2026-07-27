"""진입 폭·홉 포화·문단 순위 방식 비교 (exp_entry_variance.md 결과 4~7). LLM 호출 0.

평가 = 케이스의 gold 문단(cited_paragraphs)이 순위 몇 번째에 오는가.
튜닝셋 = dev 57건만. test 32건은 최종 검증용으로 손대지 않는다.

간선(무방향): 개념-개념(부모·자식·e2) / 개념-문단(관할) / 문단-문단(e3)
홉 상한 3 = 실측값(정답 문단 100%가 3홉 내, 4홉부터 정답 증가 0) — 튜닝 상수 아님.

실행: PYTHONPATH=. uv run python app/test/qna_holdout/exp_rank_compare.py
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict, deque
from pathlib import Path

from app.domain.graph import get_graph
from app.test.qna_holdout import exp_common as C

MAXHOP = 3
_g = get_graph()
_ts = C.testset_map()
_b = json.loads(
    (Path(__file__).parent / "exp_baseline.json").read_text(encoding="utf-8")
)

# 목차 순서 = concepts.json 선언 순서
TOC = {}
for _c in _g.concepts:
    for _p in _g.concepts[_c]["paras"]:
        TOC.setdefault(_p, len(TOC))

ADJ: dict = defaultdict(set)
for _c, _n in _g.concepts.items():
    for _p in _n["paras"]:
        ADJ[("c", _c)].add(("p", _p))
        ADJ[("p", _p)].add(("c", _c))
    rel = ([_n["parent"]] if _n["parent"] else []) + _n["children"]
    for _x in rel + _g.e2_index.get(_c, []):
        if _x in _g.concepts:
            ADJ[("c", _c)].add(("c", _x))
            ADJ[("c", _x)].add(("c", _c))
for _p, _qs in _g.e3_index.items():
    for _q in _qs:
        ADJ[("p", _p)].add(("p", _q))
        ADJ[("p", _q)].add(("p", _p))


def entries():
    """(케이스id, 회차1 진입 개념) — gold 문단이 있는 dev 케이스만."""
    for cid in _b["cases"]:
        golds = {
            C.norm_para(x) for x in (_ts.get(cid) or {}).get("cited_paragraphs", [])
        }
        ids = (_b["rounds"][0].get(cid) or {}).get("concept_ids") or []
        if golds and ids:
            yield cid, ids, golds


def reach(seed: str, maxhop: int = MAXHOP) -> dict:
    """개념 하나에서 maxhop 내 도달 문단 → 최단 홉."""
    dist, dq, out = {("c", seed): 0}, deque([("c", seed)]), {}
    while dq:
        node = dq.popleft()
        d = dist[node]
        if d >= maxhop:
            continue
        for nb in ADJ[node]:
            if nb not in dist:
                dist[nb] = d + 1
                if nb[0] == "p":
                    out.setdefault(nb[1], d + 1)
                dq.append(nb)
    return out


def rank_lex(seeds: list[str]) -> list[str]:
    """사전식: 홉 오름 → 도달 갈래 내림 → 목차 순. 파라미터 0."""
    hop, deg = {}, Counter()
    for s in seeds:
        if s in _g.concepts:
            for p, h in reach(s).items():
                hop[p] = min(hop.get(p, 99), h)
                deg[p] += 1
    return sorted(hop, key=lambda p: (hop[p], -deg[p], TOC.get(p, 10**6)))


def rank_ppr(seeds: list[str], alpha: float) -> list[str]:
    """PPR 3회 반복(=3홉). 감쇠율 alpha 1개만 파라미터."""
    seeds = [s for s in seeds if s in _g.concepts]
    if not seeds:
        return []
    r = {("c", s): 1.0 / len(seeds) for s in seeds}
    base = dict(r)
    for _ in range(MAXHOP):
        nxt: dict = defaultdict(float)
        for node, v in r.items():
            if ADJ[node]:
                share = alpha * v / len(ADJ[node])
                for nb in ADJ[node]:
                    nxt[nb] += share
        for node, v in base.items():
            nxt[node] += (1 - alpha) * v
        r = nxt
    sc = {k[1]: v for k, v in r.items() if k[0] == "p" and v > 0}
    return sorted(sc, key=lambda p: (-sc[p], TOC.get(p, 10**6)))


def evaluate(ranker) -> dict:
    rr = 0.0
    ranks, rec, n, dead = [], Counter(), 0, 0
    for _cid, ids, golds in entries():
        pos = {p: i + 1 for i, p in enumerate(ranker(ids))}
        hits = sorted(pos[x] for x in golds if x in pos)
        n += 1
        if not hits:
            dead += 1
            continue
        rr += 1 / hits[0]
        ranks.append(hits[0])
        for k in (5, 10, 20, 50):
            rec[k] += hits[0] <= k
    med = sorted(ranks)[len(ranks) // 2] if ranks else 0
    return {
        "MRR": rr / n,
        "중앙": med,
        "전멸": dead,
        **{k: rec[k] / n for k in (5, 10, 20, 50)},
    }


def show(name: str, m: dict) -> None:
    print(
        f"{name:<24}{m['MRR']:>7.3f}{m['중앙']:>6}"
        f"{m[5]:>8.1%}{m[10]:>8.1%}{m[20]:>8.1%}{m[50]:>8.1%}{m['전멸']:>6}"
    )


def hop_saturation() -> None:
    all_p = {p for c in _g.concepts for p in _g.concepts[c]["paras"]}
    cum, gold_hop, n = Counter(), Counter(), 0
    for _cid, ids, golds in entries():
        n += 1
        ph: dict = {}
        for s in ids:
            if s in _g.concepts:
                for p, h in reach(s, 5).items():
                    ph[p] = min(ph.get(p, 99), h)
        for h in range(1, 6):
            cum[h] += sum(1 for v in ph.values() if v <= h)
        for p, h in ph.items():
            if p in golds:
                gold_hop[h] += 1
    print(f"\n[홉 포화] 전체 관할 문단 {len(all_p)}개 · {n}건 평균")
    for h in range(1, 6):
        print(f"  {h}홉  {cum[h] / n:>6.1f}개  ({cum[h] / n / len(all_p):>5.1%})")
    tot = sum(gold_hop.values())
    print(
        "  정답 문단이 처음 닿는 홉: "
        + " · ".join(f"{h}홉 {gold_hop[h] / tot:.1%}" for h in sorted(gold_hop))
    )


if __name__ == "__main__":
    hop_saturation()
    print(f"\n[순위 비교] dev {sum(1 for _ in entries())}건 · test 미사용")
    print(
        f"{'방식':<24}{'MRR':>7}{'중앙':>6}{'@5':>8}{'@10':>8}{'@20':>8}{'@50':>8}{'전멸':>6}"
    )
    m0 = evaluate(lambda ids: _g.traverse(ids).paras)
    show("현재(대조군)", m0)
    show("가 사전식(파라미터 0)", evaluate(rank_lex))
    for a in [round(0.1 * i, 1) for i in range(1, 10)]:
        show(f"나 PPR α={a}", evaluate(lambda ids, a=a: rank_ppr(ids, a)))
    print("\n[대조군의 힘이 어디서 오나 — 개념 순서만 교체]")
    key = lambda c: TOC.get((_g.concepts.get(c, {}).get("paras") or ["~"])[0], 10**6)  # noqa: E731
    show(
        "개념순서 목차순", evaluate(lambda ids: _g.traverse(sorted(ids, key=key)).paras)
    )
    show("개념순서 역순", evaluate(lambda ids: _g.traverse(list(reversed(ids))).paras))

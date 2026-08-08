"""2-4 개념 넓히기 — 어느 간선으로 몇 홉 넓힐 때 무엇을 얻고 무엇을 무나.

진입 개념은 고정하고(entry_capture_v2.json), 순회에서 넓히는 규칙만 바꿔가며
gold 문단 회수 / 문단 수 / 사례 수를 잰다. 진입은 1단계에서 확정됐으므로 건드리지 않는다.

    PYTHONPATH=. uv run python app/test/qna_holdout/exp_expand.py
"""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.graph import get_graph
from app.test.qna_holdout import exp_common as EC

HERE = Path(__file__).parent
OUT = HERE / "expand.json"


def rules(g) -> dict:
    """규칙명 → 개념 하나를 받아 넓힌 개념 집합을 주는 함수."""

    def kids(c, hops):
        acc, frontier = {c}, [c]
        for _ in range(hops):
            nxt = []
            for x in frontier:
                for ch in g.concepts.get(x, {}).get("children", []):
                    if ch not in acc:
                        acc.add(ch)
                        nxt.append(ch)
            frontier = nxt
        return acc

    def parent(c, hops):
        acc, cur = {c}, c
        for _ in range(hops):
            p = g.concepts.get(cur, {}).get("parent")
            if not p:
                break
            acc.add(p)
            cur = p
        return acc

    def sibling(c):
        p = g.concepts.get(c, {}).get("parent")
        return {c} | set(g.concepts.get(p, {}).get("children", []) if p else [])

    return {
        "0 넓히지 않음": lambda c: {c},
        "자식 1홉": lambda c: kids(c, 1),
        "자식 전체": lambda c: kids(c, 9),
        "부모 1홉": lambda c: parent(c, 1),
        "형제(부모 공유)": sibling,
        "자식1 + 부모1": lambda c: kids(c, 1) | parent(c, 1),
        "자식전체 + 부모1": lambda c: kids(c, 9) | parent(c, 1),
        "자식1 + 5단계이웃": lambda c: kids(c, 1) | {c} | set(g.e2_index.get(c, [])),
        "자식전체+부모1+형제": lambda c: kids(c, 9) | parent(c, 1) | sibling(c),
    }


def main() -> None:
    g = get_graph()
    cap = json.loads((HERE / "entry_capture_v2.json").read_text("utf-8"))["rounds"]
    qv = json.loads((HERE / "entry_qvec.json").read_text("utf-8"))
    gold = {
        cid: [EC.norm_para(r["para"]) for r in recs if r.get("essential")]
        for cid, recs in EC.gold_cases().items()
    }
    total = sum(len(v) for v in gold.values())

    # 진입 개념은 회차별로 한 번만 푼다 — 규칙 비교에 진입 변동을 섞지 않는다.
    entry = {
        rnd: {
            cid: g.resolve_question(v["standalone_query"], v["term_hints"], qv.get(cid))
            for cid, v in rows.items()
        }
        for rnd, rows in cap.items()
    }

    print(f"필수 gold 문단 {total}개 · 72건 · 3회차\n")
    print(f"{'규칙':22}{'gold 회수':>22}{'개념':>7}{'문단':>7}{'사례':>7}{'IE':>6}")
    out = {}
    for name, fn in rules(g).items():
        hits, cs, ps, ks, ies = [], [], [], [], []
        for rows in entry.values():
            hit = n_c = n_p = n_k = n_i = 0
            for cid, r in rows.items():
                wide: list[str] = []
                for c in r["concept_ids"]:
                    for x in fn(c):
                        if x not in wide:
                            wide.append(x)
                tr = g.traverse(wide)
                got = set(tr.paras)
                hit += sum(1 for p in gold.get(cid, []) if p in got)
                n_c += len(wide)
                n_p += len(tr.paras)
                n_k += len(tr.cases)
                n_i += len(tr.ie_cases)
            n = len(rows)
            hits.append(hit)
            cs.append(n_c / n)
            ps.append(n_p / n)
            ks.append(n_k / n)
            ies.append(n_i / n)
        s = "/".join(str(h) for h in hits)
        print(
            f"{name:22}{s:>22}{sum(cs) / 3:>7.1f}{sum(ps) / 3:>7.1f}"
            f"{sum(ks) / 3:>7.1f}{sum(ies) / 3:>6.1f}"
        )
        out[name] = {
            "gold": hits,
            "concepts": round(sum(cs) / 3, 2),
            "paras": round(sum(ps) / 3, 2),
            "cases": round(sum(ks) / 3, 2),
            "ie": round(sum(ies) / 3, 2),
        }
    OUT.write_text(
        json.dumps({"total_gold": total, "rules": out}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()

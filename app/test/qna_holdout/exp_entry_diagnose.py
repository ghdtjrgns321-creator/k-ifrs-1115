"""진입 분해 진단 — 누가 무엇을 집었고, 놓친 것은 왜 놓쳤나.

ablation(exp_entry_ablation.py)은 조합별 총량을 낸다. 이 스크립트는 그 안을 뜯는다.

  · gold 문단 173개를 "어느 통로가 집었나"로 귀속        → §2
  · 놓친 문단마다 "목록에 말이 없어서"인지 "말은 있는데
    안 골라서"인지 가른다                                 → §3  (가장 중요)
  · LLM 선택 품질 — 개수·안정성·목록 밖 답변             → §4
  · 개념 폭발 — 한 용어가 개념을 몇 개까지 끌고 오나      → §5
  · 케이스별 전량 덤프(JSON) — 직접 뜯어보기용           → entry_diagnose.json

선행: exp_entry_capture.py --round 1~3. LLM을 부르지 않는다.
실행: PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/exp_entry_diagnose.py
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from app.config import settings
from app.domain.graph import get_graph
from app.test.qna_holdout import exp_common as C

_HERE = Path(__file__).parent
CAP = _HERE / "entry_capture_v2.json"
QVEC = _HERE / "entry_qvec.json"
OUT = _HERE / "entry_diagnose.json"

_norm = lambda s: re.sub(r"\s+", "", s or "")  # noqa: E731


def head(t: str) -> None:
    print(f"\n{'=' * 74}\n{t}\n{'=' * 74}")


def channels(g, cap: dict, qvec) -> dict[str, list[str]]:
    """통로별로 각자 데려온 개념 — 겹침 제거 전 원본."""
    return {
        "L": g.concepts_of_terms(cap["term_hints"])[0],
        "G": g.resolve_terms(cap["standalone_query"])["concept_ids"],
        "E": g.resolve_by_vector(qvec, settings.entry_embed_top_k) if qvec else [],
    }


def paras_of(g, cids: list[str]) -> set[str]:
    return set(g.traverse(cids, via_llm=None).paras) if cids else set()


def main() -> None:
    if not CAP.exists():
        raise SystemExit(f"{CAP.name} 없음 — exp_entry_capture.py --round 1 부터")
    g = get_graph()
    gold = C.gold_paras(essential_only=True)
    ids = sorted(gold)
    qv = json.loads(QVEC.read_text("utf-8"))
    caps_all = json.loads(CAP.read_text("utf-8"))["rounds"]
    rounds = sorted(caps_all)
    total_gold = sum(len(v) for v in gold.values())

    # 개념 → 그 개념을 가리킬 수 있는 목록 용어 (도달 가능성 판정용)
    reach: dict[str, list[str]] = defaultdict(list)
    for term in g.entry_terms:
        for cid in g.concepts_by_term.get(_norm(term), []):
            reach[cid].append(term)

    print(f"케이스 {len(ids)} · 필수 gold 문단 {total_gold} · 회차 {rounds}")
    dump: dict = {"rounds": {}}

    # ── §1 총괄 ────────────────────────────────────────────────────
    head("[1] 총괄 — 회차별")
    print(
        f"{'회차':>4} {'필수회수':>8} {'회수율':>7} {'개념/건':>8} "
        f"{'문단/건':>8} {'정밀도':>7} {'용어/건':>8}"
    )
    per_round = {}
    for rnd in rounds:
        caps = caps_all[rnd]
        hit = npara = ncid = nterm = 0
        for i in ids:
            ch = channels(g, caps[i], qv.get(i))
            cids = list(dict.fromkeys(ch["L"] + ch["G"] + ch["E"]))
            ps = paras_of(g, cids)
            hit += len(gold[i] & ps)
            npara += len(ps)
            ncid += len(cids)
            nterm += len(caps[i]["term_hints"])
        n = len(ids)
        per_round[rnd] = {"hit": hit, "paras": npara, "cids": ncid}
        print(
            f"{rnd:>4} {hit:>8} {hit / total_gold:>6.1%} {ncid / n:>8.1f} "
            f"{npara / n:>8.1f} {hit / npara:>6.1%} {nterm / n:>8.1f}"
        )
    print("\n  옛 구조 baseline(35토픽+subtree): 142/143/144 · 개념 11.4 · 문단 83.7")

    # ── §2 통로 귀속 ───────────────────────────────────────────────
    head("[2] gold 문단을 누가 집었나 — 회차1 기준")
    caps = caps_all[rounds[0]]
    attr = Counter()
    solo_gain = Counter()  # 그 통로가 없으면 잃는 gold
    for i in ids:
        ch = channels(g, caps[i], qv.get(i))
        ps = {k: paras_of(g, v) for k, v in ch.items()}
        allp = ps["L"] | ps["G"] | ps["E"]
        for p in gold[i]:
            if p not in allp:
                attr["놓침"] += 1
                continue
            who = "".join(k for k in "LGE" if p in ps[k])
            attr[who] += 1
            if len(who) == 1:
                solo_gain[who] += 1
    print(f"{'귀속':>6} {'문단':>6}  설명")
    labels = {
        "L": "LLM 용어만",
        "G": "글자매칭만",
        "E": "임베딩만",
        "LG": "LLM+글자",
        "LE": "LLM+임베딩",
        "GE": "글자+임베딩",
        "LGE": "셋 다",
        "놓침": "아무도 못 집음",
    }
    for k, n in sorted(attr.items(), key=lambda kv: -kv[1]):
        print(f"{k:>6} {n:>6}  {labels.get(k, '')}")
    print(f"\n  단독 기여(그 통로 빼면 잃는 gold): {dict(solo_gain)}")

    # ── §3 놓친 이유 ───────────────────────────────────────────────
    head("[3] 놓친 gold 문단 — 왜 놓쳤나 (회차1)")
    reasons = Counter()
    detail: list[dict] = []
    for i in ids:
        ch = channels(g, caps[i], qv.get(i))
        cids = list(dict.fromkeys(ch["L"] + ch["G"] + ch["E"]))
        ps = paras_of(g, cids)
        for p in sorted(gold[i] - ps):
            cid = g.para_to_concept.get(p)
            if p.startswith("BC"):
                why = "BC 문단 — 개념 관할 밖(구조적)"
            elif cid is None:
                why = "온톨로지에 개념 미할당"
            elif not reach.get(cid):
                why = "목록에 그 개념을 가리키는 말이 없음"
            else:
                why = "말은 목록에 있었는데 아무도 안 고름"
            reasons[why] += 1
            detail.append(
                {
                    "case": i,
                    "para": p,
                    "concept": g.concepts.get(cid, {}).get("title", cid),
                    "why": why,
                    "reachable_terms": reach.get(cid or "", [])[:6],
                }
            )
    for w, n in reasons.most_common():
        print(f"  {n:>4}  {w}")

    miss_c = Counter(d["concept"] for d in detail if "안 고름" in d["why"])
    print("\n  '말은 있는데 안 고름' 개념 top10 — 프롬프트로 잡을 여지:")
    for c, n in miss_c.most_common(10):
        ex = next(d["reachable_terms"] for d in detail if d["concept"] == c)
        print(f"    {n:>3}  {str(c)[:34]:36} 후보용어: {', '.join(ex[:4])}")

    gap_c = Counter(d["concept"] for d in detail if "말이 없음" in d["why"])
    if gap_c:
        print("\n  '목록에 말이 없음' 개념 — 사전 보강 대상:")
        for c, n in gap_c.most_common(10):
            print(f"    {n:>3}  {c}")

    # ── §4 LLM 선택 품질 ───────────────────────────────────────────
    head("[4] LLM 선택 품질")
    picks_all = Counter()
    unknown = Counter()
    sizes = Counter()
    for rnd in rounds:
        for i in ids:
            th = caps_all[rnd][i]["term_hints"]
            sizes[len(th)] += 1
            for t in th:
                picks_all[t] += 1
            for t in g.concepts_of_terms(th)[1]:
                unknown[t] += 1
    print("  고른 개수 분포:", dict(sorted(sizes.items())))
    print(f"  목록 밖 답변: {sum(unknown.values())}회 · 고유 {len(unknown)}종")
    # 가까운 목록 항목을 함께 보인다 — 별칭으로 흡수할지 판단하는 재료.
    # 제안만 한다. 자동 채택하면 근거 없는 매핑이 사전에 섞인다.
    import difflib

    for t, n in unknown.most_common(20):
        near = difflib.get_close_matches(t, g.entry_terms, n=2, cutoff=0.6)
        sub = [x for x in g.entry_terms if _norm(t) and _norm(t) in _norm(x)][:2]
        hint = " | ".join(dict.fromkeys(near + sub)) or "—"
        print(f"    {n:>3}  {t[:26]:28} ≈ {hint}")
    print("\n  많이 고른 용어 top15:")
    for t, n in picks_all.most_common(15):
        nc = len(g.concepts_by_term.get(_norm(t), []))
        print(f"    {n:>3}  {t[:30]:32} (개념 {nc})")

    if len(rounds) > 1:
        same = sum(
            1
            for i in ids
            if len({tuple(sorted(caps_all[r][i]["term_hints"])) for r in rounds}) == 1
        )
        print(f"\n  회차 간 완전 동일: {same}/{len(ids)}건 (옛 구조 11/57 ≈ 19%)")

    # ── §5 개념 폭발 ───────────────────────────────────────────────
    head("[5] 개념 폭발 — 한 용어가 개념을 몇 개 끌고 오나")
    wide = {t: len(v) for t, v in g.concepts_by_term.items() if len(v) >= 5}
    fired = Counter()
    for rnd in rounds:
        for i in ids:
            for t in caps_all[rnd][i]["term_hints"]:
                k = _norm(t)
                if k in wide:
                    fired[t] += 1
    print(
        f"  개념 5개+ 주는 목록 용어 {len(wide)}종 중 실제로 선택된 것: {len(fired)}종"
    )
    for t, n in fired.most_common(12):
        print(f"    {n:>3}회  {t[:28]:30} → 개념 {wide[_norm(t)]}")
    prog = [c for c, v in g.concepts.items() if "진행률" in v["title"]]
    both = 0
    for i in ids:
        ch = channels(g, caps[i], qv.get(i))
        cids = set(ch["L"] + ch["G"] + ch["E"])
        if len(cids & set(prog)) >= 3:
            both += 1
    print(
        f"\n  진행률 계열 개념({len(prog)}개) 중 3개 이상 동시 진입: {both}/{len(ids)}건"
    )

    # ── 덤프 ───────────────────────────────────────────────────────
    for rnd in rounds:
        rows = {}
        for i in ids:
            cap = caps_all[rnd][i]
            ch = channels(g, cap, qv.get(i))
            cids = list(dict.fromkeys(ch["L"] + ch["G"] + ch["E"]))
            ps = paras_of(g, cids)
            rows[i] = {
                "term_hints": cap["term_hints"],
                "unknown": g.concepts_of_terms(cap["term_hints"])[1],
                "matched_terms": g.resolve_terms(cap["standalone_query"])[
                    "matched_terms"
                ],
                "concepts": {
                    k: [g.concepts.get(c, {}).get("title", c) for c in v]
                    for k, v in ch.items()
                },
                "n_paras": len(ps),
                "gold_hit": sorted(gold[i] & ps),
                "gold_miss": sorted(gold[i] - ps),
            }
        dump["rounds"][rnd] = rows
    dump["miss_detail"] = detail
    OUT.write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n케이스별 전량 덤프 → {OUT.name}")


if __name__ == "__main__":
    main()

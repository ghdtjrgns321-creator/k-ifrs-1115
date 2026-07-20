"""홀드아웃 오염 실험 — analyze topic_hint 캡처(1회) + 오염 vs clean 진입 재현율.

phase capture : analyze_agent 92건 → analyze_capture_holdout.json (LLM, 오염 독립)
phase measure : 캡처된 topic_hints를 오염판/정제판 graph에 동일 주입 → gold 회수 비교

실행:
  PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/exp_contamination.py capture
  PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/exp_contamination.py measure
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = Path(__file__).resolve().parents[3]
TESTSET = _ROOT / "data" / "testdata" / "qna_testset.json"
SPLIT = _HERE / "split.json"
CAP = _HERE / "analyze_capture_holdout.json"


def _holdout() -> list[str]:
    s = json.loads(SPLIT.read_text(encoding="utf-8"))
    return sorted((set(s["dev"]) | set(s["test"])) - {"_meta"})


def _norm(p: str) -> str:
    return p.replace("문단", "").strip()


async def phase_capture() -> None:
    from app.agents import analyze_agent

    ts = {r["id"]: r for r in json.loads(TESTSET.read_text(encoding="utf-8"))}
    sem = asyncio.Semaphore(6)

    async def one(cid: str):
        q = ts[cid]["question"]
        async with sem:
            try:
                r = await analyze_agent.run(f"최신 대화 기록 및 질문: human: {q}")
                d = r.output
                return cid, {
                    "routing": d.routing,
                    "standalone_query": d.standalone_query,
                    "topic_hints": d.topic_hints,
                }
            except Exception as e:
                return cid, {"error": f"{type(e).__name__}: {e}"}

    res = dict(await asyncio.gather(*(one(c) for c in _holdout())))
    CAP.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    errs = [k for k, v in res.items() if v.get("error")]
    ins = sum(1 for v in res.values() if v.get("routing") == "IN")
    print(f"캡처 {len(res)}건: routing IN {ins}, error {len(errs)} {errs[:5]}")


def phase_measure() -> None:
    from app.domain.graph import Graph

    ts = {r["id"]: r for r in json.loads(TESTSET.read_text(encoding="utf-8"))}
    cap = json.loads(CAP.read_text(encoding="utf-8"))
    g_dirty = Graph(ont_dir=_ROOT / "data" / "ontology")
    g_clean = Graph(ont_dir=_ROOT / "data" / "ontology_clean")

    def entry(g, q, hints, gold):
        r = g.resolve_question(q or "", topic_hints=hints)
        cids = r["concept_ids"]
        tr = g.traverse(cids, hops=1)
        paras = {_norm(p) for p in tr.paras}
        gold_concepts = {
            g.para_to_concept.get(p) for p in gold if p in g.para_to_concept
        }
        gold_concepts.discard(None)
        return {
            "concept_hit": bool(set(cids) & gold_concepts),
            "para_hit": len(gold & paras),
            "para_recall": len(gold & paras) / len(gold) if gold else 0.0,
        }

    rows = []
    for cid in _holdout():
        c = cap.get(cid, {})
        if c.get("error") or c.get("routing") != "IN":
            continue
        gold = {_norm(p) for p in ts[cid].get("cited_paragraphs", [])}
        if not gold:
            continue
        q = c.get("standalone_query") or ts[cid]["question"]
        hints = c.get("topic_hints") or []
        d = entry(g_dirty, q, hints, gold)
        cl = entry(g_clean, q, hints, gold)
        rows.append((cid, d, cl))

    n = len(rows)
    dh = sum(1 for _, d, _ in rows if d["concept_hit"])
    ch = sum(1 for _, _, c in rows if c["concept_hit"])
    dpr = statistics.mean(d["para_recall"] for _, d, _ in rows)
    cpr = statistics.mean(c["para_recall"] for _, _, c in rows)
    dph = sum(1 for _, d, _ in rows if d["para_hit"] > 0)
    cph = sum(1 for _, _, c in rows if c["para_hit"] > 0)
    print(
        f"홀드아웃 routing=IN & gold보유 {n}건 — full 진입(analyze topic_hint 포함)\n"
    )
    print(
        f"gold 개념 진입:    오염 {dh}/{n} ({dh / n:.1%})  →  clean {ch}/{n} ({ch / n:.1%})   Δ={dh - ch}"
    )
    print(f"gold 문단 회수율:  오염 {dpr:.1%}  →  clean {cpr:.1%}   Δ={dpr - cpr:+.1%}")
    print(
        f"gold 문단 ≥1 회수: 오염 {dph}/{n} ({dph / n:.1%})  →  clean {cph}/{n} ({cph / n:.1%})   Δ={dph - cph}"
    )
    flip = [cid for cid, d, c in rows if d["concept_hit"] and not c["concept_hit"]]
    print(f"\n[오염 의존] 오염판에서만 gold 개념 진입 성공: {len(flip)}건")
    for cid in flip:
        print("  ", cid, ts[cid]["title"][:35])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["capture", "measure"])
    args = ap.parse_args()
    if args.phase == "capture":
        asyncio.run(phase_capture())
    else:
        phase_measure()


if __name__ == "__main__":
    main()

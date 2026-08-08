"""STEP 2 제안 생성 — 점검에 걸린 로그 → proposals.json. 파일은 절대 고치지 않는다.

설계: docs/quality-loop/03-proposals-gate.md

1층(용어사전)만 구체적 변경안을 만든다. 입력은 진입부가 준 `unknown_terms` —
AI가 이 질문에 필요하다고 답했는데 사전에 없어서 버려진 말이다. 용어를 추측하지
않으므로 근거가 로그에 그대로 있다.
나머지는 **변경안을 만들지 않고** 사람이 볼 보고서만 만든다.

실행:
  PYTHONPATH=. uv run --env-file .env python usage-data-collecting/propose.py
  PYTHONPATH=. uv run --env-file .env python usage-data-collecting/propose.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

from bson import ObjectId

sys.path.insert(0, str(Path(__file__).parent))

import guards  # noqa: E402
from flags import HUMAN_TEXT  # noqa: E402
from suggest import concept_catalog, link_term  # noqa: E402

from app.domain.graph import get_graph  # noqa: E402
from app.services.usage_logger import SCHEMA_VER, _get_collection  # noqa: E402

_HERE = Path(__file__).parent
CONCURRENCY = 4

# 자동 변경안을 만들지 않고 보고만 하는 항목 → (층, action, 사람이 볼 곳)
REPORT_ONLY = {
    "ENTRY_EMPTY": (1, "investigate_entry", "진입 통로 전체 — 사전·임베딩 둘 다 실패"),
    "DICT_MISS": (1, "review_dictionary_coverage", "용어사전 커버리지(aliases.json)"),
    "TERM_MISS_RAW": (
        1,
        "review_dictionary_coverage",
        "용어사전 커버리지(사용자 어휘)",
    ),
    "HINT_EMPTY": (2, "review_analyze_prompt", "용어 지목 지시문·목록(prompts.py)"),
    "CITATION_OUT": (3, "review_generate_prompt", "답변 생성 지시문(prompts.py)"),
    "NO_DOCS": (4, "investigate_graph", "개념→문단 배정 또는 조회 규약"),
}


def _load_scored(limit: int) -> list[dict]:
    """점검 이상·보강 후보·사람 신호 중 하나라도 붙은 로그. 구버전 채점 결과는 제외.

    사람 신호(👎·재질문)를 조건에 넣는 이유: L1은 "0건이냐"만 결정적으로 판정하므로
    이상 0건인데 답이 나쁜 실패를 못 본다(실측 10건에서 flags 0). 정답이 없는 실사용
    로그에서 그 실패를 가리키는 건 사용자 행동뿐이다.
    """
    col = _get_collection().database["scored_logs"]
    q = {
        "schema_ver": {"$gte": SCHEMA_VER},
        "$or": [
            {"flags": {"$ne": []}},
            {"observations": {"$ne": []}},
            {"human.feedback": "down"},
            {"human.followup": {"$ne": None}},
        ],
    }
    return list(col.find(q).sort("scored_at", -1).limit(limit))


def _feedback_cases(rows: list[dict]) -> list[dict]:
    """사람이 나쁘다고 한 답변 → 개발자가 볼 원자료. 제안이 아니다.

    Why 제안으로 안 만드나: 👎·재질문은 "실패했다"만 말하고 "무엇을 고쳐라"는 말하지
    않는다. 층 추정은 L1 신호가 붙었을 때만 하고, 없으면 비워둔다 — 없는 근거로 층을
    찍으면 그게 또 근거 없는 판정이다. 오히려 "사람은 나쁘다는데 코드로는 이상 없음"이
    지금 루프가 못 보는 실패라, 그게 보이는 것 자체가 이 목록의 목적이다.
    """
    marked = [
        r
        for r in rows
        if (r.get("human") or {}).get("feedback") == "down"
        or (r.get("human") or {}).get("followup")
    ]
    if not marked:
        return []

    logs_col = _get_collection()
    raw = {
        str(d["_id"]): d
        for d in logs_col.find(
            {"_id": {"$in": [ObjectId(r["log_id"]) for r in marked]}}
        )
    }

    out = []
    for r in marked:
        lg = raw.get(r["log_id"]) or {}
        entry = lg.get("entry") or {}
        retrieval = lg.get("retrieval") or {}
        human = r.get("human") or {}
        out.append(
            {
                "log_id": r["log_id"],
                "signal": "down" if human.get("feedback") == "down" else "followup",
                "question": r.get("question", ""),
                "answer": lg.get("answer", ""),
                "reason": human.get("reason", ""),
                "followup_question": (human.get("followup") or {}).get("question", ""),
                "entry": {
                    "concept_ids": entry.get("concept_ids") or [],
                    "via_llm": entry.get("via_llm") or [],
                    "via_embed": entry.get("via_embed") or [],
                    "matched_terms": entry.get("matched_terms") or [],
                    "term_hints": entry.get("term_hints") or [],
                    "unknown_terms": entry.get("unknown_terms") or [],
                },
                "retrieval": {
                    "doc_count": retrieval.get("doc_count", 0),
                    "context_paras": retrieval.get("context_paras") or [],
                    "concept_path": retrieval.get("concept_path") or [],
                },
                "cited_paragraphs": lg.get("cited_paragraphs") or [],
                "flags": r.get("flags") or [],
                "observations": r.get("observations") or [],
                "grounded": (r.get("verdict_a") or {}).get("grounded"),
                # L1 신호가 없으면 층을 찍지 않는다
                "suspect_layer": r.get("suspect_layer"),
            }
        )
    return out


def _signals(row: dict) -> set[str]:
    """이 로그에 붙은 항목 전부(이상 + 보강 후보)."""
    return set(row.get("flags") or []) | set(row.get("observations") or [])


async def _alias_proposals(rows: list[dict], catalog: str, sem) -> list[dict]:
    """1층 — unknown_terms를 사전에 등재하는 제안. 용어는 추측하지 않는다."""
    g = get_graph()
    known_concepts = set(g.concepts)
    existing = {guards.norm(k) for k in g.concepts_by_term}
    all_questions = [r["question"] for r in rows]

    # 같은 용어가 여러 질문에서 나오면 한 제안으로 합친다
    by_term: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        for t in r.get("unknown_terms") or []:
            by_term[t].append(r)

    rejected: list[str] = []
    targets: list[tuple[str, list[dict]]] = []
    for term, rs in by_term.items():
        reason = guards.check_term(term, existing)
        if reason:
            rejected.append(f"{term} — {reason}")
            continue
        targets.append((term, rs))

    async def one(term, rs):
        async with sem:
            try:
                return term, rs, await link_term(term, rs[0]["question"], catalog)
            except Exception as exc:
                print(f"  초안 실패 {term}: {type(exc).__name__}: {exc}")
                return term, rs, None

    out = []
    for term, rs, link in await asyncio.gather(*(one(t, r) for t, r in targets)):
        if not link:
            continue
        cids = guards.valid_concepts(link.concept_ids, known_concepts)
        if not cids:
            rejected.append(f"{term} — 연결할 개념 없음(LLM이 판단 보류)")
            continue
        out.append(
            {
                "layer": 1,
                "action": "add_alias",
                "target": "data/ontology/aliases.json",
                "change": {"term": term.strip(), "concept_ids": cids},
                "evidence": {
                    "log_ids": [r["log_id"] for r in rs],
                    "flags": ["TERM_UNKNOWN"],
                    "questions": [r["question"] for r in rs][:5],
                    "term_hints": rs[0].get("term_hints") or [],
                },
                "why": link.why,
                "impact": {
                    "affected_logs": len(rs),
                    "literal_hits": guards.literal_hits(term, all_questions),
                    "term_collision": guards.term_collisions(term, existing),
                    # 개념 개수를 그대로 싣는다 — 상한으로 자르지 않으므로 많으면
                    # 사람이 보고 판단한다(기존 사전은 1개 46% · 2개 27%).
                    "concept_count": len(cids),
                },
            }
        )
    if rejected:
        print(f"  가드에서 제외 {len(rejected)}건: {rejected[:5]}")
    return out


def _report_proposals(rows: list[dict]) -> list[dict]:
    """변경안을 만들지 않고 사람이 볼 보고서만 만든다.

    Why: 지시문 한 줄을 고치면 전 질문의 답변이 바뀐다. 그래프는 원문에 정답이 있어
    창작 여지가 없다. 사전 커버리지는 개별 용어가 아니라 추세로 봐야 한다.
    """
    by_item: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        for f in _signals(r):
            if f in REPORT_ONLY:
                by_item[f].append(r)

    out = []
    for item, rs in by_item.items():
        layer, action, what = REPORT_ONLY[item]
        out.append(
            {
                "layer": layer,
                "action": action,
                "target": what,
                "change": None,  # 사람이 정한다
                "evidence": {
                    "log_ids": [r["log_id"] for r in rs],
                    "flags": [item],
                    "questions": [r["question"] for r in rs][:5],
                },
                "why": f"{HUMAN_TEXT[item]} ({len(rs)}건)",
                "impact": {"affected_logs": len(rs)},
                "warning": "기준서 원문 파생 자산 — 03 문서 §4 경고 확인"
                if layer == 4
                else "",
            }
        )
    return sorted(out, key=lambda p: (p["layer"], -p["impact"]["affected_logs"]))


async def main_async(args) -> None:
    rows = _load_scored(args.limit)
    if not rows:
        print("점검에 걸린 로그가 없습니다. score.py를 먼저 실행하세요.")
        return
    print(f"점검 대상 로그 {len(rows)}건 → 제안 생성")

    feedback = _feedback_cases(rows)
    if feedback:
        blind = [f for f in feedback if not f["flags"] and not f["observations"]]
        print(f"사람 신호 {len(feedback)}건 (코드로는 이상 없음 {len(blind)}건)")

    aliases = await _alias_proposals(
        rows, concept_catalog(), asyncio.Semaphore(CONCURRENCY)
    )
    proposals = aliases + _report_proposals(rows)
    for i, p in enumerate(proposals, 1):
        p["id"] = f"P-{i:04d}"
        p["status"] = "pending"

    print(f"\n제안 {len(proposals)}건")
    for p in proposals:
        chg = p["change"] or "(사람이 결정)"
        print(f"  [{p['id']}] L{p['layer']} {p['action']:26s} {chg}")

    if args.dry_run:
        print("\n--dry-run — 파일을 쓰지 않았습니다.")
        return
    out = _HERE / args.out
    out.write_text(
        json.dumps(proposals, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"→ {out}")

    # 사람 신호는 proposals.json과 분리한다 — status 편집(승인/거절) 대상이 아니라
    # 개발자가 읽고 직접 손볼 원자료다.
    fb_out = _HERE / args.feedback_out
    fb_out.write_text(
        json.dumps(feedback, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"→ {fb_out} ({len(feedback)}건)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--out", default="proposals.json")
    ap.add_argument("--feedback-out", default="feedback.json")
    ap.add_argument("--dry-run", action="store_true")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()

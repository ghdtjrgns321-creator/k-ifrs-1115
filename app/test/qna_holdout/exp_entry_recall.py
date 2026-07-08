"""STEP 1 진입 재현율 실험 러너 — 페이즈별 실행, 산출물 캐시.

  embed    : 개념 80개 passage 임베딩 → concept_embeddings.json (결정적, 1회)
  baseline : dev 57건 analyze R회 → exp_baseline.json (topic 진입 concept_ids)
  cosine   : dev 57건 query 임베딩 top-k(3/5/7) → exp_cosine.json (결정적)
  selector : dev 57건 gpt-4.1-mini 개념지목 R회 → exp_selector.json
  judge    : 위 산출물 종합 → exp_decision.md (hit-rate 대조 + 채택판정)

QNA-off 불필요(진입만 측정, retrieve 미실행). analyze는 in-memory 그래프.

실행:
  PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/exp_entry_recall.py embed
  PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/exp_entry_recall.py baseline --repeats 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.test.qna_holdout import exp_common as C

_HERE = Path(__file__).parent
CONCEPT_EMB = C._ROOT / "data" / "ontology" / "concept_embeddings.json"


# ── embed: 개념 80개 임베딩 ──────────────────────────────────────────────────
def phase_embed() -> None:
    from app.embeddings import embed_texts_sync

    texts = C.build_concept_texts()
    cids = list(texts)
    vecs = embed_texts_sync([texts[c] for c in cids])  # passage 모델
    empty = sum(1 for v in vecs if not v)
    CONCEPT_EMB.write_text(
        json.dumps({c: v for c, v in zip(cids, vecs)}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"개념 임베딩 {len(cids)}개 저장, dim={len(vecs[0])}, 빈벡터={empty}")
    print(f"→ {CONCEPT_EMB}")


# ── baseline: analyze 진입 개념 ──────────────────────────────────────────────
async def _analyze_one(question: str) -> dict:
    from app.nodes.analyze import analyze_query

    state = {"messages": [("human", question)]}
    out = await analyze_query(state)
    return {
        "routing": out.get("routing"),
        "concept_ids": out.get("concept_ids", []),
        "via_topic": out.get("via_topic", []),
    }


async def phase_baseline(repeats: int) -> None:
    cases = C.dev_gold_cases()
    sem = asyncio.Semaphore(6)

    async def run_case(cid, question):
        async with sem:
            try:
                return cid, await _analyze_one(question)
            except Exception as e:
                return cid, {"error": f"{type(e).__name__}: {e}"}

    rounds = []
    for r in range(repeats):
        res = await asyncio.gather(
            *(run_case(cid, c["question"]) for cid, c, _ in cases)
        )
        rounds.append(dict(res))
        errs = sum(1 for v in dict(res).values() if v.get("error"))
        print(f"  baseline round {r + 1}/{repeats}: {len(res)}건, error {errs}")
    (_HERE / "exp_baseline.json").write_text(
        json.dumps(
            {"cases": [c[0] for c in cases], "rounds": rounds},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"→ exp_baseline.json ({len(cases)}건 × {repeats}회)")


# ── cosine: query 임베딩 top-k ───────────────────────────────────────────────
def phase_cosine() -> None:
    from app.embeddings import embed_texts_sync
    from app.config import settings

    cases = C.dev_gold_cases()
    concept_emb = C.load_json(CONCEPT_EMB)
    cids = list(concept_emb)
    qtexts = [c["question"] for _, c, _ in cases]
    qvecs = embed_texts_sync(qtexts, settings.embed_query_model)  # query 모델

    out = {}
    for (cid, _c, _gc), qv in zip(cases, qvecs):
        sims = sorted(((C.cosine(qv, concept_emb[k]), k) for k in cids), reverse=True)
        out[cid] = {
            "top7": [k for _, k in sims[:7]],
            "sims7": [round(s, 4) for s, _ in sims[:7]],
        }
    (_HERE / "exp_cosine.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"→ exp_cosine.json ({len(cases)}건, top-7 저장)")


# ── selector: LLM 개념 지목 ──────────────────────────────────────────────────
def _concept_menu() -> str:
    concepts = C.load_json(C.CONCEPTS)["concepts"]
    lines = []
    for cid, n in concepts.items():
        if n.get("level", 0) and n.get("title"):
            lines.append(f"{cid}\t{n['title']}\t{n.get('path', '')}")
    return "\n".join(lines)


async def phase_selector(repeats: int) -> None:
    from pydantic_ai import Agent
    from pydantic import BaseModel

    class Picked(BaseModel):
        concept_ids: list[str]

    menu = _concept_menu()
    sysprompt = (
        "너는 K-IFRS 1115호 회계 질문을 읽고 관련된 개념을 아래 개념목록에서 고르는 분류기다.\n"
        "각 줄은 '개념ID<TAB>개념명<TAB>경로'. 질문의 회계 쟁점에 직접 관련된 개념ID를 최대 5개 고른다.\n"
        "반드시 목록의 개념ID만 반환. 확실치 않으면 넓게 포함.\n\n[개념목록]\n" + menu
    )
    agent = Agent("openai:gpt-4.1-mini", output_type=Picked, system_prompt=sysprompt)
    valid = set(C.load_json(C.CONCEPTS)["concepts"])
    cases = C.dev_gold_cases()
    sem = asyncio.Semaphore(6)

    async def run_case(cid, question):
        async with sem:
            try:
                res = await agent.run(f"질문: {question}")
                picks = [p for p in res.output.concept_ids if p in valid]
                return cid, {"concept_ids": picks}
            except Exception as e:
                return cid, {"error": f"{type(e).__name__}: {e}"}

    rounds = []
    for r in range(repeats):
        res = await asyncio.gather(
            *(run_case(cid, c["question"]) for cid, c, _ in cases)
        )
        rounds.append(dict(res))
        errs = sum(1 for v in dict(res).values() if v.get("error"))
        print(f"  selector round {r + 1}/{repeats}: {len(res)}건, error {errs}")
    (_HERE / "exp_selector.json").write_text(
        json.dumps(
            {"cases": [c[0] for c in cases], "rounds": rounds},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"→ exp_selector.json ({len(cases)}건 × {repeats}회)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["embed", "baseline", "cosine", "selector"])
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()
    if args.phase == "embed":
        phase_embed()
    elif args.phase == "baseline":
        asyncio.run(phase_baseline(args.repeats))
    elif args.phase == "cosine":
        phase_cosine()
    elif args.phase == "selector":
        asyncio.run(phase_selector(args.repeats))


if __name__ == "__main__":
    main()

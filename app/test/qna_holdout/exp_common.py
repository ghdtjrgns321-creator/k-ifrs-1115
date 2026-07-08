"""STEP 1 진입 재현율 실험 — 공통 로직.

개념 재현율 지표 = gold 문단의 관할개념이 후보개념집합에 들어오는가(hit).
데이터 로드·gold개념 산출·개념 임베딩 텍스트·재현율 계산을 한곳에.
"""

from __future__ import annotations

import json
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = Path(__file__).resolve().parents[3]
TESTSET = _ROOT / "data" / "testdata" / "qna_testset.json"
CONCEPTS = _ROOT / "data" / "ontology" / "concepts.json"
CHUNKS = _ROOT / "data" / "web" / "kifrs-1115-chunks.json"
TOPICMAP = _ROOT / "data" / "ontology" / "topic_concept_map.json"
SPLIT = _HERE / "split.json"

MAX_CONCEPT_CHARS = 2500  # Upstage 한국어 여유(3000자 상한 아래)


def norm_para(p: str) -> str:
    return str(p).replace("문단", "").strip()


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def dev_ids() -> list[str]:
    return load_json(SPLIT)["dev"]


def testset_map() -> dict:
    return {c["id"]: c for c in load_json(TESTSET)}


def para_to_concept() -> dict:
    return load_json(CONCEPTS)["para_to_concept"]


def gold_concepts(case: dict, p2c: dict) -> set[str]:
    """케이스 gold 문단 → 관할 개념 집합(매핑 가능한 것만)."""
    out = set()
    for g in case.get("cited_paragraphs", []):
        cid = p2c.get(norm_para(g))
        if cid:
            out.add(cid)
    return out


def dev_gold_cases() -> list[tuple[str, dict, set]]:
    """(id, case, gold_concepts) — gold개념 매핑 가능한 dev 케이스만."""
    ts, p2c = testset_map(), para_to_concept()
    out = []
    for cid in dev_ids():
        c = ts[cid]
        gc = gold_concepts(c, p2c)
        if gc:
            out.append((cid, c, gc))
    return out


def build_concept_texts() -> dict[str, str]:
    """개념ID → 임베딩용 텍스트(제목 + 경로 + 관할문단 본문)."""
    concepts = load_json(CONCEPTS)["concepts"]
    chunks = load_json(CHUNKS)
    para_text = {str(x["metadata"].get("paraNum")): x["content"] for x in chunks}

    out = {}
    for cid, node in concepts.items():
        parts = [node.get("title", ""), node.get("path", "")]
        for p in node.get("paras", []):
            t = para_text.get(str(p))
            if t:
                parts.append(t)
        text = "\n".join(x for x in parts if x)[:MAX_CONCEPT_CHARS]
        out[cid] = text or node.get("title", cid)
    return out


def cosine(a: list[float], b: list[float]) -> float:
    import math

    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def hit_rate(cases: list, candidate_of) -> tuple[int, int, list[str]]:
    """cases: (id, case, gold_concepts). candidate_of(id)->set. 반환 (hit, N, miss_ids)."""
    hit, miss = 0, []
    for cid, _c, gc in cases:
        cand = candidate_of(cid)
        if gc & cand:
            hit += 1
        else:
            miss.append(cid)
    return hit, len(cases), miss

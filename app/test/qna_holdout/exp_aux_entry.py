"""보조 진입(코사인 후순위 병합)이 dev에서 무엇을 바꾸나. 임베딩 API만 사용, LLM 0.

기록된 회차1 진입(exp_baseline.json)에 코사인 상위 k를 뒤에 붙여 대조한다.
via_topic·용어사전 몫은 양쪽 동일하므로 보조 진입만의 효과가 분리된다.

질의 벡터는 exp_aux_qvec.json에 캐시한다(재실행 시 임베딩 호출 0).

실행: PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/exp_aux_entry.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.config import settings
from app.domain.graph import get_graph
from app.test.qna_holdout import exp_common as C

_HERE = Path(__file__).parent
QVEC = _HERE / "exp_aux_qvec.json"
_g = get_graph()
_ts = C.testset_map()
_b = json.loads((_HERE / "exp_baseline.json").read_text(encoding="utf-8"))


def query_vectors(ids: list[str]) -> dict:
    """질의 벡터 캐시 — 없으면 원문 질문을 query 모델로 임베딩해 저장."""
    if QVEC.exists():
        cached = json.loads(QVEC.read_text(encoding="utf-8"))
        if all(i in cached for i in ids):
            return cached
    from app.embeddings import embed_texts_sync

    vecs = embed_texts_sync(
        [_ts[i]["question"] for i in ids], settings.embed_query_model
    )
    out = dict(zip(ids, vecs))
    QVEC.write_text(json.dumps(out), encoding="utf-8")
    print(f"질의 벡터 {len(out)}건 생성 → {QVEC.name}")
    return out


def coverage(sets: dict, gold: dict, ids: list[str]) -> dict:
    """진입 후보 자체의 지표 — 정답개념 포착·개념수·문단수."""
    hit = cov = 0.0
    nc = npara = 0
    for cid in ids:
        s = set(sets[cid])
        inter = gold[cid] & s
        hit += 1 if inter else 0
        cov += len(inter) / len(gold[cid])
        nc += len(s)
        npara += len(_g.traverse(sets[cid]).paras)
    n = len(ids)
    return {"hit": hit, "N": n, "커버리지": cov / n, "개념": nc / n, "문단": npara / n}


def ranking(sets: dict, ids: list[str]) -> dict:
    """gold 문단이 회수 순서 몇 번째에 오는가 — exp_rank_compare와 같은 정의."""
    rr = 0.0
    ranks, rec, dead = [], Counter(), 0
    for cid in ids:
        golds = {C.norm_para(x) for x in _ts[cid].get("cited_paragraphs", [])}
        if not golds:
            continue
        pos = {p: i + 1 for i, p in enumerate(_g.traverse(sets[cid]).paras)}
        hits = sorted(pos[x] for x in golds if x in pos)
        if not hits:
            dead += 1
            continue
        rr += 1 / hits[0]
        ranks.append(hits[0])
        for k in (5, 10, 20, 50):
            rec[k] += hits[0] <= k
    n = len(ids)
    med = sorted(ranks)[len(ranks) // 2] if ranks else 0
    return {
        "MRR": rr / n,
        "중앙": med,
        "전멸": dead,
        **{k: rec[k] / n for k in (5, 10, 20, 50)},
    }


def main() -> None:
    gold = {cid: gc for cid, _, gc in C.dev_gold_cases()}
    ids = [c for c in _b["cases"] if c in gold]
    qv = query_vectors(ids)
    k = settings.entry_embed_top_k

    base = {c: (_b["rounds"][0].get(c) or {}).get("concept_ids") or [] for c in ids}
    aux, added = {}, 0
    for c in ids:
        extra = [x for x in _g.resolve_by_vector(qv[c], k) if x not in base[c]]
        aux[c] = base[c] + extra
        added += len(extra)

    variants = (("보조 없음", base), ("보조 있음", aux))
    print(
        f"\n대상 {len(ids)}건 · 코사인 top-{k} · 새로 붙은 개념 평균 {added / len(ids):.2f}개"
    )

    print(f"\n{'':<12}{'개념':>6}{'문단':>7}{'hit':>17}{'커버리지':>10}")
    for name, s in variants:
        m = coverage(s, gold, ids)
        print(
            f"{name:<12}{m['개념']:>6.1f}{m['문단']:>7.1f}"
            f"{m['hit']:>10.0f}/{m['N']} ({m['hit'] / m['N']:>5.1%}){m['커버리지']:>9.1%}"
        )

    print(
        f"\n{'':<12}{'MRR':>7}{'중앙':>6}{'@5':>8}{'@10':>8}{'@20':>8}{'@50':>8}{'전멸':>6}"
    )
    for name, s in variants:
        m = ranking(s, ids)
        print(
            f"{name:<12}{m['MRR']:>7.3f}{m['중앙']:>6}"
            f"{m[5]:>8.1%}{m[10]:>8.1%}{m[20]:>8.1%}{m[50]:>8.1%}{m['전멸']:>6}"
        )


if __name__ == "__main__":
    main()

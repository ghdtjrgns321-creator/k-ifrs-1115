"""진입 통로가 각각 필요한가 — 조합 ablation (용어 목록 구조).

진입은 통로 둘이고, 용어사전 경유는 같은 사전을 두 방법으로 읽는다.

  ┌ 용어사전 경유 ─┬─ L: LLM이 [용어 목록]에서 선택
  │                └─ G: 질문에 글자 그대로 있는 용어 매칭
  └ E: 개념 임베딩 코사인 top-k (사용자 원문)

L·G는 용어를 산출하고 사전이 개념으로 번역한다. 세 스위치가 독립이므로 조합은 2³=8.

하나씩 빼보는 것만으로는 판정이 안 된다. 두 통로가 같은 개념을 데려오면 하나씩
빼도 손실이 0이라 "둘 다 불필요"라는 틀린 답이 나온다. 단독·하나빼기를 함께 본다.

비용축(평균 문단 수)을 함께 낸다. union 구조라 회수만 보면 통로를 더할수록 항상
좋아져서 "빼자"는 결론이 원리적으로 안 나온다.

옛 구조(35개 토픽 + subtree 확장) 결과는 `entry_ablation.json`에 보존돼 있다.
그쪽 baseline은 필수회수 142/143/144다. 이 스크립트는 v2 파일에만 쓴다.

선행: exp_entry_capture.py로 회차 캡처. 이 스크립트는 LLM을 부르지 않는다.
실행: PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/exp_entry_ablation.py
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import settings
from app.domain.graph import get_graph
from app.test.qna_holdout import exp_common as C

_HERE = Path(__file__).parent
CAP = _HERE / "entry_capture_v2.json"
QVEC = _HERE / "entry_qvec.json"
OUT = _HERE / "entry_ablation_v2.json"

# (라벨, LLM 용어, 글자매칭, 임베딩)
COMBOS = [
    (f"{'L' if x else '-'}{'G' if y else '-'}{'E' if z else '-'}", x, y, z)
    for x in (False, True)
    for y in (False, True)
    for z in (False, True)
]
FULL = "LGE"


def compose(g, cap: dict, llm: bool, terms: bool, cos: bool, qvec) -> tuple:
    """진입 개념 조립 — graph.resolve_question과 동일 순서로 통로만 켜고 끈다."""
    cids: list[str] = []
    via_llm: list[str] = []
    if llm:
        for cid in g.concepts_of_terms(cap["term_hints"])[0]:
            if cid not in cids:
                cids.append(cid)
                via_llm.append(cid)
    if terms:
        for cid in g.resolve_terms(cap["standalone_query"])["concept_ids"]:
            if cid not in cids:
                cids.append(cid)
    if cos and qvec:
        for cid in g.resolve_by_vector(qvec, settings.entry_embed_top_k):
            if cid not in cids:
                cids.append(cid)
    return cids, via_llm


def query_vectors(ids: list[str], ts: dict) -> dict:
    """질의 벡터 캐시 — 원문 질문 기준(analyze._entry_vector와 동일)."""
    if QVEC.exists():
        cached = json.loads(QVEC.read_text("utf-8"))
        if all(i in cached for i in ids):
            return cached
    from app.embeddings import embed_texts_sync

    vecs = embed_texts_sync(
        [ts[i]["question"] for i in ids], settings.embed_query_model
    )
    out = dict(zip(ids, vecs))
    QVEC.write_text(json.dumps(out), encoding="utf-8")
    print(f"질의 벡터 {len(out)}건 생성 → {QVEC.name}")
    return out


def run_combo(g, ids, caps, gold, qv, llm, terms, cos) -> dict:
    """조합 1개 실측 — 필수 gold 문단 회수 · 회수 문단 총량."""
    got = paras = 0
    per_case = {}
    for i in ids:
        cids, via = compose(g, caps[i], llm, terms, cos, qv.get(i))
        ps = set(g.traverse(cids, via_llm=via).paras)
        hit = gold[i] & ps
        per_case[i] = sorted(hit)
        got += len(hit)
        paras += len(ps)
    return {"필수회수": got, "문단합": paras, "per_case": per_case}


def verify_full(g, ids, caps, qv) -> None:
    """전체 조합이 프로덕션 resolve_question과 같은지 — 로직 복제 오류 차단."""
    for i in ids:
        mine, _ = compose(g, caps[i], True, True, True, qv.get(i))
        real = g.resolve_question(
            caps[i]["standalone_query"], caps[i]["term_hints"], query_vec=qv.get(i)
        )["concept_ids"]
        if mine != real:
            raise SystemExit(f"조립 불일치 {i}\n  ablation={mine}\n  graph={real}")
    print(f"전체 조합 == resolve_question 검증 통과 ({len(ids)}건)")


def main() -> None:
    if not CAP.exists():
        raise SystemExit(f"{CAP.name} 없음 — exp_entry_capture.py --round 1 부터")
    g, ts = get_graph(), C.testset_map()
    gold = {k: v for k, v in C.gold_paras(essential_only=True).items()}
    caps_all = json.loads(CAP.read_text("utf-8"))["rounds"]
    ids = sorted(gold)
    qv = query_vectors(ids, ts)
    total_gold = sum(len(v) for v in gold.values())
    print(f"케이스 {len(ids)} · 필수 gold 문단 {total_gold} · 회차 {sorted(caps_all)}")

    results = {}
    for rnd in sorted(caps_all):
        caps = caps_all[rnd]
        missing = [i for i in ids if i not in caps]
        if missing:
            raise SystemExit(f"회차 {rnd} 캡처 누락 {len(missing)}건: {missing[:5]}")
        verify_full(g, ids, caps, qv)
        results[rnd] = {
            label: run_combo(g, ids, caps, gold, qv, x, y, z)
            for label, x, y, z in COMBOS
        }
        print(f"\n── 회차 {rnd} ─────────────────────────────────")
        print(
            f"{'조합':10} {'필수회수':>8} {'회수율':>7} {'평균문단':>8} {'정밀도':>7}"
        )
        for label, *_ in COMBOS:
            r = results[rnd][label]
            rate = r["필수회수"] / total_gold
            avg = r["문단합"] / len(ids)
            prec = r["필수회수"] / r["문단합"] if r["문단합"] else 0.0
            mark = " ←전체" if label == FULL else ""
            print(
                f"{label:10} {r['필수회수']:>8} {rate:>6.1%} {avg:>8.1f} {prec:>6.1%}{mark}"
            )

    OUT.write_text(
        json.dumps(
            {"gold_total": total_gold, "n_cases": len(ids), "results": results},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\n저장 → {OUT.name}")
    print(
        "옛 구조 baseline(35토픽+subtree): 필수회수 142/143/144 — entry_ablation.json"
    )


if __name__ == "__main__":
    main()

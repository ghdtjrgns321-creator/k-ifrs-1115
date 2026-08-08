"""그래프 전수 점검 — 채점 착수 전에 "이상한 데 없나"를 눈이 아니라 분모로 본다.

노드 종류별로 ① 몇 개가 있고 ② 몇 개가 순회에 닿고 ③ 몇 개가 실제로 LLM까지
가는지를 각각 센다. ②와 ③이 갈리는 곳이 배선이 끊긴 자리다.

    PYTHONPATH=. uv run python app/test/qna_holdout/exp_graph_audit.py
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

from app.domain.graph import get_graph
from app.test.qna_holdout import exp_common as EC

HERE = Path(__file__).parent
ONT = Path(__file__).resolve().parents[3] / "data" / "ontology"


def bar(title: str) -> None:
    print(f"\n{'─' * 4} {title} {'─' * (60 - len(title))}")


def main() -> None:
    g = get_graph()
    topics = json.loads((ONT / "case_topics.json").read_text("utf-8"))["topics"]
    cap = json.loads((HERE / "entry_capture_v2.json").read_text("utf-8"))["rounds"]
    qv = json.loads((HERE / "entry_qvec.json").read_text("utf-8"))

    # 3회차 216질문을 실제로 순회해 무엇이 나오는지 집계
    seen = {k: collections.Counter() for k in ("para", "case", "ie", "bc", "tree")}
    empty = collections.Counter()
    for rows in cap.values():
        for cid, v in rows.items():
            r = g.resolve_question(v["standalone_query"], v["term_hints"], qv.get(cid))
            tr = g.traverse(r["concept_ids"])
            for p in tr.paras:
                seen["para"][p] += 1
            for c in tr.cases:
                seen["case"][c["db_parent_id"]] += 1
            for c in tr.ie_cases:
                seen["ie"][c["id"]] += 1
            for x in tr.bc_groups:
                seen["bc"][x] += 1
            if g.match_judgment_tree(r["concept_ids"]):
                seen["tree"]["hit"] += 1
            for name, n in (
                ("문단", len(tr.paras)),
                ("사례", len(tr.cases)),
                ("IE", len(tr.ie_cases)),
            ):
                if n == 0:
                    empty[name] += 1

    bar("1. 노드 종류별 — 있는 것 / 순회에 닿는 것 / LLM까지 가는 것")
    ie_all = {c["id"] for c in g.cases["ie"]}
    case_all = {c["db_parent_id"] for k in ("qna", "findings") for c in g.cases[k]}
    rows = [
        ("기준서 문단", len(g.para_to_concept), len(seen["para"]), "예"),
        ("QNA·감리 사례", len(case_all), len(seen["case"]), "예"),
        ("IE 적용사례", len(ie_all), len(seen["ie"]), "예"),
        ("BC 그룹", len(g.bc["groups"]), len(seen["bc"]), "**아니오**"),
        ("판단 트리", len(g.judgment_trees), "-", "예"),
    ]
    print(f"{'종류':16}{'전체':>7}{'216질문에서 닿음':>18}{'LLM까지 가나':>14}")
    for name, total, hit, to_llm in rows:
        print(f"{name:16}{total:>7}{str(hit):>18}{to_llm:>14}")
    print(f"\n판단 트리가 붙은 질문: {seen['tree']['hit']}/216")

    bar("2. BC — 걷기만 하고 버린다")
    print("  traverse가 bc_groups를 채우지만 fetch_documents가 조회하지 않는다.")
    print(
        f"  216질문 평균 {sum(seen['bc'].values()) / 216:.1f}그룹이 수집되고 전량 버려진다."
    )
    print(f"  닿는 그룹 {len(seen['bc'])}/{len(g.bc['groups'])} · tasks 2-5 미착수")

    bar("3. 고아 — 어디에도 안 걸린 것")
    no_para = [c for c, n in g.concepts.items() if not n["paras"]]
    no_topic = sorted(
        {c["id"] for c in g.cases["ie"]}
        - {k for k in topics if topics[k]["kind"] == "ie"}
    )
    never_case = sorted(case_all - set(seen["case"]))
    never_ie = sorted(ie_all - set(seen["ie"]))
    never_para = sorted(set(g.para_to_concept) - set(seen["para"]))
    print(
        f"  관할 문단 0인 개념      {len(no_para)}/80  {[g.concepts[c]['title'][:16] for c in no_para]}"
    )
    print(f"  주제 간선 0인 IE        {len(no_topic)}  {no_topic}")
    print("  216질문에서 한 번도 안 나온:")
    print(
        f"    문단 {len(never_para)}/{len(g.para_to_concept)}  사례 {len(never_case)}/{len(case_all)}  IE {len(never_ie)}/{len(ie_all)}"
    )

    bar("4. 빈손으로 끝난 질문 (216 중)")
    for k in ("문단", "사례", "IE"):
        print(f"  {k} 0건: {empty[k]}")

    bar("5. 용어사전")
    aliases = json.loads((ONT / "aliases.json").read_text("utf-8"))["terms"]
    with_c = sum(1 for t in aliases if t.get("concept_ids"))
    with_case = sum(1 for t in aliases if t.get("cases") and not t.get("concept_ids"))
    dead = sum(1 for t in aliases if not t.get("concept_ids") and not t.get("cases"))
    print(
        f"  전체 {len(aliases)} = 개념연결 {with_c} + 사례제목만 {with_case} + 미등재 {dead}"
    )
    print(f"  글자매칭 대상(term_index) {len(g.term_index)} — 개념연결만")
    print(f"  LLM 목록(entry_terms) {len(g.entry_terms)} = 실무어 + 개념제목")
    orphan_terms = [
        t["term"]
        for t in aliases
        if t.get("concept_ids") and any(c not in g.concepts for c in t["concept_ids"])
    ]
    print(
        f"  존재하지 않는 개념을 가리키는 용어: {len(orphan_terms)} {orphan_terms[:5]}"
    )

    bar("6. gold 도달 상한 — 그래프가 원리적으로 못 주는 문단")
    gold = EC.gold_cases()
    p2c = g.para_to_concept
    miss = collections.Counter()
    tot = 0
    for recs in gold.values():
        for r in recs:
            if not r.get("essential"):
                continue
            tot += 1
            p = EC.norm_para(r["para"])
            if p not in p2c:
                miss["개념 관할 밖"] += 1
            elif p not in seen["para"]:
                miss["관할은 있으나 216질문에서 미회수"] += 1
    print(f"  필수 gold {tot}개 중")
    for k, v in miss.items():
        print(f"    {k}: {v}")
    bc_gold = [
        EC.norm_para(r["para"])
        for recs in gold.values()
        for r in recs
        if r.get("essential") and EC.norm_para(r["para"]).startswith("BC")
    ]
    print(f"    그중 BC 문단: {len(bc_gold)} {sorted(set(bc_gold))}")


if __name__ == "__main__":
    main()

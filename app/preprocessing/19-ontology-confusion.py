"""온톨로지 STEP 2 후속: 혼동쌍 도출 — 형제 개념쌍 + e3 연결 개념쌍.

사용법:
  PYTHONPATH=. uv run python app/preprocessing/19-ontology-confusion.py

Why: 실무자가 혼동하는 개념쌍(반품권↔재매입 등)을 기계적으로 전수 도출한다.
     관찰된 실패 케이스를 손으로 적지 않는다(오버피팅 차단) — 온톨로지 구조가 근거:
       (1) 같은 부모의 content-bearing 형제쌍 = 같은 층위의 경쟁 개념
       (2) e3 상호참조로 문단이 서로를 가리키는 개념쌍 = 기준서가 직접 연결
     런타임(generate)은 via_topic(LLM 직접 지목)에 든 쌍만 활성화 → subtree 확장이
     진입을 형제로 도배하는 노이즈(케이스당 15~19쌍) 회피. 여기선 쌍 사전만 만든다.

     criterion_paras = 한쪽 개념의 문단이 e3로 다른쪽 문단을 가리키는 지점(기준서가
     둘을 대비한 문단). 없으면 빈 배열 → 런타임은 구조헤더+개념별 그룹핑으로 폴백.
"""

import json
from itertools import combinations
from pathlib import Path

CONCEPTS_PATH = Path("data/ontology/concepts.json")
EDGES_PATH = Path("data/ontology/edges.json")
OUTPUT_PATH = Path("data/ontology/confusion_pairs.json")


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def pair_key(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


def build_para_owner(concepts: dict) -> dict:
    """문단번호 → 관할 개념ID (concepts[cid].paras 역인덱스)."""
    owner = {}
    for cid, node in concepts.items():
        for p in node.get("paras", []):
            owner[str(p)] = cid
    return owner


def e3_concept_links(edges: dict, para_owner: dict) -> dict:
    """e3 문단 상호참조 → 개념쌍별 근거 문단(criterion 후보) 집계."""
    links: dict[str, set] = {}
    for e in edges.get("e3_cross_refs", []):
        src_p = str(e.get("from"))
        src_c = para_owner.get(src_p)
        if not src_c:
            continue
        for dst_p in e.get("to", []):
            dst_c = para_owner.get(str(dst_p))
            if dst_c and dst_c != src_c:
                links.setdefault(pair_key(src_c, dst_c), set()).add(src_p)
    return links


def main() -> None:
    oc = load(CONCEPTS_PATH)
    concepts = oc["concepts"]
    edges = load(EDGES_PATH)
    para_owner = build_para_owner(concepts)
    e3links = e3_concept_links(edges, para_owner)

    # (1) content-bearing 형제쌍
    by_parent: dict[str, list] = {}
    for cid, node in concepts.items():
        if node.get("parent") and node.get("paras"):
            by_parent.setdefault(node["parent"], []).append(cid)

    pairs: dict[str, dict] = {}
    for parent, kids in by_parent.items():
        for a, b in combinations(sorted(kids), 2):
            k = pair_key(a, b)
            pairs[k] = {
                "concepts": [a, b],
                "titles": [concepts[a]["title"], concepts[b]["title"]],
                "relation": "sibling",
                "parent": parent,
                "criterion_paras": sorted(e3links.get(k, set())),
            }

    # (2) e3 연결 개념쌍 (형제 아니어도) — 비형제 쌍만 추가
    for k, ev in e3links.items():
        if k in pairs:
            pairs[k]["criterion_paras"] = sorted(set(pairs[k]["criterion_paras"]) | ev)
            continue
        a, b = k.split("|")
        pairs[k] = {
            "concepts": [a, b],
            "titles": [concepts[a]["title"], concepts[b]["title"]],
            "relation": "e3",
            "parent": None,
            "criterion_paras": sorted(ev),
        }

    OUTPUT_PATH.write_text(
        json.dumps(
            {"_meta": {"count": len(pairs)}, "pairs": pairs},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    n = len(pairs)
    m = sum(1 for v in pairs.values() if v["criterion_paras"])
    n_sib = sum(1 for v in pairs.values() if v["relation"] == "sibling")
    n_e3 = n - n_sib
    print(f"혼동쌍 {n} (형제 {n_sib} + e3 {n_e3}), criterion 보유 {m}")
    # 검증: 35567의 반품권↔재매입 포함?
    rp = pair_key("1IdzfY", "vw8tzF")
    print(
        f"반품권↔재매입({rp}) 포함: {rp in pairs} | {pairs.get(rp, {}).get('relation')}"
    )
    print(f"→ {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

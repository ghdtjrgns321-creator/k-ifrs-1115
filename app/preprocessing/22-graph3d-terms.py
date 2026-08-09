"""3D 뷰어의 용어 레이어를 aliases.json으로 재생성 (2026-08-09)

사용법:
  PYTHONPATH=. uv run python app/preprocessing/22-graph3d-terms.py

Why: graph-3d.html은 GRAPH 상수를 본문에 박아 배포하는 단일 파일이라, 17e로 사전이
     349행이 된 뒤에도 용어 노드 400개가 그대로 남았다. 사전을 정본으로 삼아 용어
     노드와 용어→개념 간선만 다시 만든다. 개념·문단·사례·BC 레이어는 손대지 않는다
     (그쪽 정본은 concepts/edges/case_links이고 이 스크립트의 범위가 아니다).
"""

import json
import re
from pathlib import Path

HTML_PATH = Path("graph-3d.html")
ALIASES_PATH = Path("data/ontology/aliases.json")
GRAPH_RE = re.compile(r"(const GRAPH = )(\{.*?\})(;)", re.S)


def main():
    html = HTML_PATH.read_text(encoding="utf-8")
    m = GRAPH_RE.search(html)
    assert m, "GRAPH 상수를 찾지 못함 — 뷰어 구조 변경 여부 확인"
    g = json.loads(m.group(2))
    terms = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))["terms"]

    concept_ids = {n["id"] for n in g["nodes"] if n["type"] == "concept"}
    before_n = sum(1 for n in g["nodes"] if n["type"] == "term")
    before_l = sum(1 for lk in g["links"] if lk.get("type") == "term")

    # 용어 레이어 교체 — caseid는 뷰어가 노드 출처 툴팁에 쓰는 칸이다.
    nodes = [n for n in g["nodes"] if n["type"] != "term"]
    links = [lk for lk in g["links"] if lk.get("type") != "term"]
    ghost = []
    for t in terms:
        nid = f"t:{t['term']}"
        nodes.append(
            {
                "id": nid,
                "label": t["term"],
                "type": "term",
                "caseid": t["sources"][0],
            }
        )
        for cid in t["concept_ids"]:
            if cid not in concept_ids:
                ghost.append((t["term"], cid))
                continue
            links.append({"s": nid, "t": cid, "type": "term"})

    g["nodes"], g["links"] = nodes, links
    n_terms = sum(1 for n in nodes if n["type"] == "term")
    n_links = sum(1 for lk in links if lk.get("type") == "term")
    g["meta"]["terms"] = n_terms
    g["meta"]["links"]["term"] = n_links

    print(f"용어 노드 {before_n} → {n_terms} / 용어 간선 {before_l} → {n_links}")
    print(f"유령 개념 ID: {len(ghost)}건 {ghost[:5]} (0이어야 PASS)")
    assert not ghost

    body = json.dumps(g, ensure_ascii=False, separators=(", ", ": "))
    HTML_PATH.write_text(html[: m.start(2)] + body + html[m.end(2) :], encoding="utf-8")
    print(f"저장: {HTML_PATH}")


if __name__ == "__main__":
    main()

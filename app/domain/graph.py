"""온톨로지 지식그래프 — 질문 진입(resolve) + 탐색(traverse). 순수 로직, DB 무관.

STEP 5-1 (05-pipeline.md §3). 임베딩 유사도 없이 개념 노드로 진입하고
그래프 간선을 따라 결정적으로 문단·사례·BC를 수집한다.
DB 원문 조회는 graph_fetch.py가 담당.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.config import settings

_ONT = Path(__file__).resolve().parents[2] / "data" / "ontology"


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


@dataclass
class TraverseResult:
    """개념에서 그래프를 따라 수집한 근거 후보. 순서는 그래프 위상(직속 우선)."""

    concept_ids: list[str] = field(default_factory=list)
    paras: list[str] = field(default_factory=list)  # 관할 문단 + e3 인용 이웃
    cases: list[dict] = field(default_factory=list)  # QNA·감리 {db_parent_id, title}
    ie_cases: list[dict] = field(default_factory=list)  # IE {id, title, group}
    bc_groups: list[str] = field(default_factory=list)
    related_concepts: list[str] = field(default_factory=list)
    path: list[str] = field(default_factory=list)  # 사람이 읽는 근거 경로


class Graph:
    def __init__(self, ont_dir: Path = _ONT):
        self._load(ont_dir)
        self._build_indexes()

    def _load(self, d: Path) -> None:
        self.concepts: dict = json.loads((d / "concepts.json").read_text("utf-8"))[
            "concepts"
        ]
        self.para_to_concept: dict = json.loads(
            (d / "concepts.json").read_text("utf-8")
        )["para_to_concept"]
        self.edges: dict = json.loads((d / "edges.json").read_text("utf-8"))
        self.cases: dict = json.loads((d / "case_links.json").read_text("utf-8"))
        self.bc: dict = json.loads((d / "bc_links.json").read_text("utf-8"))
        self.terms: list = json.loads((d / "aliases.json").read_text("utf-8"))["terms"]
        self.topic_map: dict = json.loads(
            (d / "topic_concept_map.json").read_text("utf-8")
        )["map"]
        self.judgment_trees: dict = json.loads(
            (d / "judgment_trees.json").read_text("utf-8")
        )["trees"]

    def _build_indexes(self) -> None:
        # 용어 인덱스: 등재 용어(개념·사례 목적지 보유)만. norm(term) → 행
        self.term_index = [
            t
            for t in self.terms
            if (t.get("concept_ids") or t.get("cases")) and len(_norm(t["term"])) >= 2
        ]
        # 개념 → 사례 역인덱스 (문단 경유 + 직결 concepts 필드 + IE concept)
        self.case_by_concept: dict[str, list] = {}
        for kind in ("qna", "findings"):
            for c in self.cases[kind]:
                hit = {
                    self.para_to_concept[p]
                    for p in c.get("paras", [])
                    if p in self.para_to_concept
                }
                hit |= set(c.get("concepts", []))  # 문단 인용 0인 직결 6건
                for cid in hit:
                    self.case_by_concept.setdefault(cid, []).append(
                        {"db_parent_id": c["db_parent_id"], "title": c["title"]}
                    )
        self.ie_by_concept: dict[str, list] = {}
        for c in self.cases["ie"]:
            cid = c.get("concept")
            if cid:
                self.ie_by_concept.setdefault(cid, []).append(
                    {"id": c["id"], "title": c["title"], "group": c.get("group", "")}
                )
        # 개념 → BC 그룹 역인덱스
        self.bc_by_concept: dict[str, list] = {}
        for g in self.bc["groups"]:
            for cid in g.get("concepts_within", []):
                self.bc_by_concept.setdefault(cid, []).append(g["group"])
        # 문단 상호참조(e3): from → [to...]
        self.e3_index: dict[str, list] = {}
        for e in self.edges.get("e3_cross_refs", []):
            self.e3_index.setdefault(e["from"], []).extend(e["to"])
        # 개념 선행판단(e2): from → [to...] 양방향
        self.e2_index: dict[str, list] = {}
        for e in self.edges.get("e2_five_step", []):
            self.e2_index.setdefault(e["from"], []).append(e["to"])
            self.e2_index.setdefault(e["to"], []).append(e["from"])

    def resolve_terms(self, text: str) -> dict:
        """질문 텍스트 → 개념 후보 + 직접 걸린 사례. 용어사전 substring 매칭(결정적)."""
        tn = _norm(text)
        matched, concept_ids, cases = [], [], []
        for t in self.term_index:
            if _norm(t["term"]) in tn:
                matched.append(t["term"])
                for cid in t.get("concept_ids", []):
                    if cid not in concept_ids:
                        concept_ids.append(cid)
                for c in t.get("cases", []):
                    if c not in cases:
                        cases.append(c)
        return {"concept_ids": concept_ids, "cases": cases, "matched_terms": matched}

    def match_judgment_tree(
        self, concept_ids: list[str], via_topic: list[str] | None = None
    ) -> str:
        """진입 개념에 걸린 판단 트리를 전부 이어붙여 반환(트리거에 걸린 것 모두).

        본문에서 추출한 조건-분기(예: 기간에 걸쳐 vs 한 시점)를 generate에 주입해,
        LLM이 흩어진 문단에서 판단 순서를 스스로 조립하는 부담을 없앤다.

        Why(트리 오선택): via_topic(LLM 지목 주제 개념)이 있으면 그것만으로 매칭한다.
        concept_ids 전체는 subtree 확장으로 딸려온 배경 개념을 포함해, 투표수로 주제
        트리를 이기는 오선택(측정 14/27)과 신규 트리 미주입(17/18)을 유발했다.
        단일 best-1 선택 폐기: 질문 하나가 여러 개념에 걸치면 걸린 판단 절차를 모두 넣는다
        (트리 개당 ~500자, 문단 상한 제거와 동일 논리). via_topic 없으면 concept_ids로 폴백.
        """
        match_set = set(via_topic or concept_ids)
        texts = [
            t["text"]
            for t in self.judgment_trees.values()
            if match_set & set(t["trigger_concepts"])
        ]
        return "\n\n".join(texts)

    def _resolve_topic_hint(self, th: str) -> list[str]:
        """topic_hint → 개념. LLM 축약(예 '수행의무 식별'→'수행의무') 부분매칭 흡수."""
        if th in self.topic_map:
            return self.topic_map[th]
        for key, cids in self.topic_map.items():
            if th and (th in key or key in th):
                return cids
        return []

    def _subtree(self, cid: str, acc: set | None = None) -> set:
        """개념 하위 트리(자신 포함)."""
        if acc is None:
            acc = set()
        acc.add(cid)
        for ch in self.concepts.get(cid, {}).get("children", []):
            if ch not in acc:
                self._subtree(ch, acc)
        return acc

    def _adaptive_subtree(self, cid: str) -> set:
        """개념의 주제군 확장 — 부모 subtree가 작으면 형제 포함, 크면 자기 하위만.

        Why(07 gap): topic_map이 말단 개념 1개만 가리켜 형제(같은 주제군)를 놓친다.
        부모가 큰 대분류(부록B 24개)면 형제 포함이 문단 폭발이므로 임계로 억제.
        """
        p = self.concepts.get(cid, {}).get("parent")
        if p:
            ps = self._subtree(p)
            if len(ps) - 1 <= settings.subtree_expand_max:
                return ps
        return self._subtree(cid)

    def resolve_question(
        self,
        text: str,
        keywords: list[str] | None = None,
        topic_hints: list[str] | None = None,
    ) -> dict:
        """질문 진입 통합 — LLM 지목 토픽(우선) + 용어사전(보조).

        임베딩 유사도 없이 개념 후보를 산출. tree_matcher(match_topics) 대체.
        topic_hint(LLM 주제 지목) 개념을 앞에 배치 → 용어사전(배경어) 개념은 뒤로.
        Why(07-retrieval-priority): 배경어(계약·수행의무)가 진입 앞자리를 뺏어 질문 주제
        문단이 generate 상한에 밀리는 문제. traverse는 개념 순서대로 문단을 넣으므로
        개념 순서를 바꾸면 문단 우선순위가 따라온다.
        """
        blob = (text or "") + " " + " ".join(keywords or [])
        r = self.resolve_terms(blob)
        cids: list[str] = []
        via_topic: list[str] = []
        for th in topic_hints or []:
            for cid in self._resolve_topic_hint(th):
                if cid not in cids:
                    cids.append(cid)
                    via_topic.append(cid)
        # 계층 subtree 확장 — hint 개념의 주제군 형제/하위를 후순위로 포함(gap 보강).
        # hint 직속(위)이 앞, 확장 개념은 뒤 → 문단 우선순위 보존.
        for cid in list(via_topic):
            for e in self._adaptive_subtree(cid):
                if e not in cids:
                    cids.append(e)
        for cid in r["concept_ids"]:
            if cid not in cids:
                cids.append(cid)
        return {
            "concept_ids": cids,
            "cases": r["cases"],
            "matched_terms": r["matched_terms"],
            "via_topic": via_topic,
        }

    def traverse(self, concept_ids: list[str], hops: int = 1) -> TraverseResult:
        """개념 → 관할 문단·사례·BC·관련 개념 수집. hops=1이면 문단 e3 이웃 1홉 확장."""
        r = TraverseResult(concept_ids=list(concept_ids))
        seen_p, seen_c, seen_ie, seen_bc, seen_rc = set(), set(), set(), set(), set()

        def add_para(p):
            if p not in seen_p:
                seen_p.add(p)
                r.paras.append(p)

        for cid in concept_ids:
            node = self.concepts.get(cid)
            if not node:
                continue
            r.path.append(f"개념[{node['title']}]")
            for p in node["paras"]:
                add_para(p)
            for c in self.case_by_concept.get(cid, []):
                if c["db_parent_id"] not in seen_c:
                    seen_c.add(c["db_parent_id"])
                    r.cases.append(c)
            for c in self.ie_by_concept.get(cid, []):
                if c["id"] not in seen_ie:
                    seen_ie.add(c["id"])
                    r.ie_cases.append(c)
            for g in self.bc_by_concept.get(cid, []):
                if g not in seen_bc:
                    seen_bc.add(g)
                    r.bc_groups.append(g)
            for rel in (
                ([node["parent"]] if node["parent"] else [])
                + node["children"]
                + self.e2_index.get(cid, [])
            ):
                if rel and rel not in seen_rc:
                    seen_rc.add(rel)
                    r.related_concepts.append(rel)
        # e3 인용 이웃 확장
        if hops >= 1:
            for p in list(r.paras):
                for q in self.e3_index.get(p, []):
                    add_para(q)
        return r


@lru_cache(maxsize=1)
def get_graph() -> Graph:
    """프로세스 단위 싱글턴."""
    return Graph()

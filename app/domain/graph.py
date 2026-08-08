"""온톨로지 지식그래프 — 질문 진입(resolve) + 탐색(traverse). 순수 로직, DB 무관.

STEP 5-1 (05-pipeline.md §3). 용어사전 글자 매칭으로 개념 노드에 진입하고
그래프 간선을 따라 결정적으로 문단·사례·BC를 수집한다. 유사도는 진입 후보 맨 뒤에
붙는 안전망으로만 쓴다(resolve_by_vector) — 순회 구간에는 유사도가 없다.
DB 원문 조회는 graph_fetch.py가 담당.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.config import settings

_ONT = Path(__file__).resolve().parents[2] / "data" / "ontology"


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class TraverseResult:
    """개념에서 그래프를 따라 수집한 근거 후보. 순서는 그래프 위상(직속 우선)."""

    concept_ids: list[str] = field(default_factory=list)
    paras: list[str] = field(default_factory=list)  # 관할 문단 + e3 인용 이웃
    cases: list[dict] = field(default_factory=list)  # QNA·감리 {db_parent_id, title}
    ie_cases: list[dict] = field(default_factory=list)  # IE {id, title, group}
    bc_groups: list[str] = field(default_factory=list)
    # 회수한 문단을 논의한 BC 문단. **LLM에게 주지 않는다** — 근거 표시 전용이다.
    bc_paras: list[str] = field(default_factory=list)
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
        # 사례 주제 간선 — 21-ontology-case-topics.py 산출. case_links.json의 인용
        # 간선과 파일을 나눈다(16-ontology-cases.py가 저쪽을 통째로 덮어쓴다).
        self.case_topics: dict = json.loads(
            (d / "case_topics.json").read_text("utf-8")
        )["topics"]
        self.bc: dict = json.loads((d / "bc_links.json").read_text("utf-8"))
        self.terms: list = json.loads((d / "aliases.json").read_text("utf-8"))["terms"]
        self.judgment_trees: dict = json.loads(
            (d / "judgment_trees.json").read_text("utf-8")
        )["trees"]
        # 개념 임베딩 — 보조 진입 전용. 없으면 보조 진입만 비활성(나머지 경로 무영향).
        emb = d / "concept_embeddings.json"
        self.concept_emb: dict[str, list[float]] = (
            json.loads(emb.read_text("utf-8")) if emb.exists() else {}
        )

    def _build_indexes(self) -> None:
        # 용어 인덱스: **개념을 주는 행만**. norm(term) → 행
        # Why(사례 제목 행 115개 제외): 그 행들은 개념 없이 사례만 가리켜, 제목이
        # 질문에 글자로 있으면 사례를 순회 밖에서 곧바로 꽂아 넣었다. 그건 "제목이
        # 겹치면 같은 쟁점"이라는 가정이고, 인용을 쟁점으로 쓰던 것과 같은 오류다.
        # 사례는 주제 간선(case_topics.json)으로만 걷는다. 실측 기여는 72건 중 2건.
        self.term_index = [
            t for t in self.terms if t.get("concept_ids") and len(_norm(t["term"])) >= 2
        ]
        # 진입 용어 목록 + 용어→개념 번역표. 두 출처를 합친다.
        #  ① 용어사전에서 개념이 걸린 행 — 실무어(CIF·SaaS·마일리지). 사례 제목만
        #     걸린 행(115개)은 제외한다: 개념을 못 주므로 진입 산출물이 될 수 없다.
        #  ② 개념 제목 — 용어사전은 실무 질의에서 뽑은 말이라 기준서 공식 용어가
        #     term으로 없다(옛 토픽 33개 중 29개 부재: 변동대가·라이선싱·보증·공시…).
        #     LLM이 "이건 라이선싱 문제"라고 알아봐도 목록에 없으면 고를 수 없어
        #     판단력이 통째로 사라진다. 관할 문단이 없는 개념은 뺀다 — 골라도 가져올
        #     게 없다(기준서 루트·인식·계약원가 3개가 여기 걸린다).
        # norm 기준으로 합집합한다. "개별 판매가격"/"개별판매가격"처럼 공백만 다른
        # 행이 따로 등재돼 있고, 제목과 term이 같은 경우도 9건 있다.
        self.concept_terms = [t for t in self.term_index if t.get("concept_ids")]
        self.concepts_by_term: dict[str, list[str]] = {}
        self.entry_terms: list[str] = []

        def _link(term: str, cids: list[str]) -> None:
            key = _norm(term)
            if key not in self.concepts_by_term:
                self.entry_terms.append(term)
            acc = self.concepts_by_term.setdefault(key, [])
            for cid in cids:
                if cid not in acc:
                    acc.append(cid)

        for t in self.concept_terms:
            _link(t["term"], t["concept_ids"])
        for cid, node in self.concepts.items():
            if node.get("paras"):
                _link(node["title"], [cid])
        # 개념 → 사례 역인덱스 — **주제 간선만** 탄다.
        # Why: case_links.json의 링크는 "이 사례가 이 문단을 인용했다"는 출처 표시다.
        # 그걸 주제로 쓰면 문단 하나를 스친 사례까지 딸려온다 — 링크 323개 중 54%가
        # 문단 1개 근거였고 사례당 배정 개념이 2.94개(실제 쟁점 1.68개)였다.
        # case_topics.json은 그 인용 개념을 울타리로 두고 쟁점만 남긴 것이라 항상
        # 부분집합이다(560 → 283). dev/entry-traverse/results-traverse.md.
        self.case_by_concept: dict[str, list] = {}
        self.ie_by_concept: dict[str, list] = {}
        meta = {
            (c.get("db_parent_id") or c["id"]): (kind, c)
            for kind in ("qna", "findings", "ie")
            for c in self.cases[kind]
        }
        for key, row in self.case_topics.items():
            kind, c = meta.get(key, (None, None))
            if not c:
                continue
            for cid in row["topics"]:
                if kind == "ie":
                    self.ie_by_concept.setdefault(cid, []).append(
                        {
                            "id": c["id"],
                            "title": c["title"],
                            "group": c.get("group", ""),
                        }
                    )
                else:
                    self.case_by_concept.setdefault(cid, []).append(
                        {"db_parent_id": c["db_parent_id"], "title": c["title"]}
                    )
        # 문단 → 그 문단을 논의한 BC (E-BC4, 목차 괄호표기 최심). 없으면 빈 인덱스.
        self.para_to_bc: dict[str, list[str]] = self.bc.get("para_to_bc_anno", {})
        # 개념 → BC 그룹 역인덱스
        self.bc_by_concept: dict[str, list] = {}
        for g in self.bc["groups"]:
            for cid in g.get("concepts_within", []):
                self.bc_by_concept.setdefault(cid, []).append(g["group"])
        # 문단 상호참조(e3): from → [to...]
        self.e3_index: dict[str, list] = {}
        for e in self.edges.get("e3_cross_refs", []):
            self.e3_index.setdefault(e["from"], []).extend(e["to"])
        # 개념 → 판단 트리 역인덱스 (트리거는 41개 중 40개가 개념 1개, timing-35만 6개)
        self.tree_by_concept: dict[str, list[str]] = {}
        for tid, t in self.judgment_trees.items():
            for cid in t["trigger_concepts"]:
                self.tree_by_concept.setdefault(cid, []).append(tid)
        # 개념 선행판단(e2): from → [to...] 양방향.
        # **순회는 타지 않는다** — 넓히기 실측에서 이득 0이었고 사례만 늘렸다(ADR-45).
        # 실험 스크립트(exp_expand·exp_rank_compare)가 규칙 후보를 재려고 읽는다.
        self.e2_index: dict[str, list] = {}
        for e in self.edges.get("e2_five_step", []):
            self.e2_index.setdefault(e["from"], []).append(e["to"])
            self.e2_index.setdefault(e["to"], []).append(e["from"])

    def term_list_for_prompt(self) -> str:
        """LLM에게 보여줄 용어 목록 — 실무어 + 개념 제목, 가나다순 한 줄.

        Why(개념을 같이 보여주지 않는가): 용어사전은 실무어→기준서 개념 번역표이고
        그 오른쪽은 사람이 검수한 자산이다(aliases.json _meta.review 99건). 개념까지
        보여주면 LLM이 사전을 덮어써 "CIF지만 대리인 얘기는 아닌 듯" 하고 걸린 개념
        일부를 빠뜨린다. 왼쪽만 보여주고 번역은 코드가 하면 LLM이 틀릴 수 있는 자리가
        "용어를 못 알아봄" 하나로 줄어든다(docs/entry-traverse/plan.md §4).
        """
        return ", ".join(sorted(self.entry_terms))

    def concepts_of_terms(self, terms: list[str]) -> tuple[list[str], list[str]]:
        """용어 목록 → (개념 id, 미등재 용어). 사전 정확 일치(공백 무시)만 인정한다.

        Why(부분매칭 안 함): 용어는 글자수 중앙값 5로 짧아 부분매칭이 위험하다.
        "계약"이 계약자산·계약부채·계약변경을 전부 끌어온다. 옛 topic_hint 경로는
        긴 토픽명이라 부분매칭 폴백이 성립했지만 용어에는 그 전제가 없다.
        미등재분은 버리되 두 번째 값으로 돌려준다 — 사전 보강 대상을 남기는 신호다.
        """
        cids: list[str] = []
        unknown: list[str] = []
        for term in terms:
            hit = self.concepts_by_term.get(_norm(term or ""))
            if not hit:
                if term:
                    unknown.append(term)
                continue
            for cid in hit:
                if cid not in cids:
                    cids.append(cid)
        return cids, unknown

    def resolve_terms(self, text: str) -> dict:
        """질문 텍스트 → 개념 후보. 용어사전 substring 매칭(결정적)."""
        tn = _norm(text)
        matched, concept_ids = [], []
        for t in self.term_index:
            if _norm(t["term"]) in tn:
                matched.append(t["term"])
                for cid in t["concept_ids"]:
                    if cid not in concept_ids:
                        concept_ids.append(cid)
        return {"concept_ids": concept_ids, "matched_terms": matched}

    def resolve_by_vector(self, qvec: list[float], top_k: int) -> list[str]:
        """질의 벡터 → 코사인 상위 개념. 보조 진입 전용(용어사전 뒤 후순위 병합).

        Why(존재 이유): 용어사전은 글자 매칭이라 등재되지 않은 말로 물으면 진입이 비고,
        LLM 지목은 회차마다 흔들린다(3회 동일 11/57). ADR-23이 같은 진단으로 임베딩을
        보완 신호로 두었다가 온톨로지 전환 때 tree_matcher와 함께 사라진 자리다.

        Why(임계·가중 없음): ADR-23 원형은 임계 0.28·가중 10.0을 썼고 근거가 없었다.
        여기서는 점수를 순위 결정에만 쓰고 값 자체를 다른 신호와 섞지 않는다. top_k는
        exp_decision.md에서 3·5·7이 같은 결과(56/57)여서 최소값을 취한 것이다.
        """
        if not self.concept_emb or not qvec:
            return []
        sims = ((_cosine(qvec, v), cid) for cid, v in self.concept_emb.items())
        return [cid for _, cid in sorted(sims, reverse=True)[:top_k]]

    def match_judgment_tree(self, concept_ids: list[str]) -> str:
        """진입 개념에 걸린 판단 트리를 개념 순서대로 이어붙여 반환.

        본문에서 추출한 조건-분기(예: 기간에 걸쳐 vs 한 시점)를 generate에 주입해,
        LLM이 흩어진 문단에서 판단 순서를 스스로 조립하는 부담을 없앤다.

        Why(문단과 같은 문턱): 트리는 그 개념 관할 문단의 조건-분기를 접어놓은 것이다
        (judgment_trees.json _meta "기준서 본문 원문 추출 · AI 창작 아님"). 문단이
        들어오는데 트리만 빠질 이유가 없어 진입 통로 한정을 폐기했다. 한정의 근거였던
        "투표수로 주제 트리를 이기는 오선택 14/27"은 겹침 최다 1개만 고르던 시절 수치이며,
        걸린 트리를 전부 주입하는 지금 구조에서는 성립하지 않는다(ADR-37).

        Why(순서): concept_ids 순서를 그대로 따른다. 재현성 목적이지 우선순위가 아니다
        — 문단은 하류(graph_fetch)에서 기준서 번호순으로 다시 정렬된다.
        """
        seen: set[str] = set()
        texts: list[str] = []
        for cid in concept_ids:
            for tid in self.tree_by_concept.get(cid, []):
                if tid not in seen:
                    seen.add(tid)
                    texts.append(self.judgment_trees[tid]["text"])
        return "\n\n".join(texts)

    def _subtree(
        self, cid: str, acc: list | None = None, seen: set | None = None
    ) -> list:
        """개념 하위 트리(자신 포함) — 기준서 목차 순서로 반환.

        Why(리스트로 모으는 이유): set으로 모으면 문자열 해시가 프로세스마다 달라
        재시작 후 순회 순서가 바뀐다(결정적 순회라는 설계와 모순). children 선언
        순서를 따르는 리스트로 모아 원문 위계 순서를 그대로 재현한다.
        """
        if acc is None:
            acc = []
        if seen is None:
            seen = set()
        if cid in seen:
            return acc
        seen.add(cid)
        acc.append(cid)
        for ch in self.concepts.get(cid, {}).get("children", []):
            self._subtree(ch, acc, seen)
        return acc

    def resolve_question(
        self,
        text: str,
        term_hints: list[str] | None = None,
        query_vec: list[float] | None = None,
    ) -> dict:
        """질문 진입 — 개념만 산출한다. 통로는 용어사전 경유와 임베딩 둘.

        용어사전 경유는 같은 사전을 두 방법으로 읽는다. LLM이 목록에서 고른 용어와
        질문에 글자 그대로 있는 용어를 합쳐 사전으로 개념을 번역한다. 글자매칭을
        남기는 이유는 비용이 0이면서 LLM이 놓쳤을 때의 바닥이 되기 때문이다.

        Why(개념 확장이 여기 없음): 형제·하위로 넓히는 것은 그래프를 타는 일이라
        순회의 몫이다. 진입은 "어디서 시작하나"만 정한다(docs/entry-traverse/plan.md).

        Why(순서): 재현성 목적이지 우선순위가 아니다. 슬롯 상한·rerank가 없어
        순서를 바꿔도 문서 집합이 같고, 문단 순서는 graph_fetch가 기준서 번호순으로
        다시 정한다(ADR-40).
        """
        r = self.resolve_terms(text or "")
        llm_cids, unknown_terms = self.concepts_of_terms(term_hints or [])
        cids: list[str] = []
        # via_llm — LLM이 직접 지목한 용어에서 나온 개념. traverse의 사례 수집 한정에 쓴다.
        via_llm: list[str] = []
        for cid in llm_cids:
            if cid not in cids:
                cids.append(cid)
                via_llm.append(cid)
        for cid in r["concept_ids"]:
            if cid not in cids:
                cids.append(cid)
        # 임베딩 진입 — via_embed는 traverse.path의 "유사도 진입" 표기에만 쓴다.
        via_embed: list[str] = []
        if query_vec:
            for cid in self.resolve_by_vector(query_vec, settings.entry_embed_top_k):
                if cid not in cids:
                    cids.append(cid)
                    via_embed.append(cid)
        return {
            "concept_ids": cids,
            "matched_terms": r["matched_terms"],
            "via_llm": via_llm,
            "via_embed": via_embed,
            # 사전에 없는 말을 LLM이 답한 경우. 파이프라인은 안 쓰고 품질 로그만 쓴다
            # — 진입이 비었을 때 "LLM이 답을 안 했다"와 "답했는데 사전에 없다"를 가른다.
            "unknown_terms": unknown_terms,
        }

    def expand_concepts(self, concept_ids: list[str], mode: str) -> list[str]:
        """진입 개념을 위계로 넓힌다. "none"이면 그대로, "kin1"이면 부모·자식 1홉.

        Why(순회의 몫): 어디서 시작하나는 진입이 정하고, 그 자리에서 얼마나 볼지는
        순회가 정한다. 옛 구조는 진입 단계에서 하위를 넓히면서 `subtree_expand_max=8`
        이라는 근거 없는 상한을 달고 있었다 — 그 상한은 옮기지 않았다(ADR-36).

        Why(1홉·부모+자식): 홀드아웃 실측에서 깊이는 값을 못 했고(자식 전체는 1홉
        대비 gold +1), 5단계 이웃(e2)은 이득 0이며, 형제까지 열면 기준서 문단의
        70%가 들어온다. results-traverse.md §16.
        """
        if mode == "none":
            return list(concept_ids)
        if mode != "kin1":
            raise ValueError(f"알 수 없는 traverse_expand: {mode!r} (none|kin1)")
        out: list[str] = []
        for cid in concept_ids:
            node = self.concepts.get(cid)
            if not node:
                continue
            for x in [
                cid,
                *(node["children"]),
                *([node["parent"]] if node["parent"] else []),
            ]:
                if x not in out:
                    out.append(x)
        return out

    def traverse(
        self,
        concept_ids: list[str],
        hops: int = 1,
        via_embed: list[str] | None = None,
        expand: str | None = None,
    ) -> TraverseResult:
        """개념 → 관할 문단·사례·BC·관련 개념 수집. hops=1이면 문단 e3 이웃 1홉 확장.

        Why(사례 한정을 폐기함): 예전엔 LLM이 지목한 용어에서 나온 개념(via_llm)에서만
        사례를 걷었다. 링크가 인용 유래라 흔한 문단을 스치기만 해도 사례가 쏟아지던
        시절의 응급조치다. 두 가지 이유로 없앴다. ① 원인을 고쳤다 — 사례는 이제
        주제 간선(case_topics.json)으로만 걸린다. ② 애초에 근거가 없었다. 같은 개념인데
        문단은 세 통로 전부에서 걷고 사례만 한 통로로 제한할 이유가 없고, 하필 그 통로가
        문단 회수 기여도 3위였다(단독 회수 임베딩 122 · 글자매칭 105 · LLM용어 93).
        결과로 72건 중 7건이 사례를 하나도 못 받고 있었다.

        expand는 개념 넓히기 규칙(none|kin1). None이면 설정값을 따른다 —
        실험 스크립트만 인자로 덮어쓴다.
        """
        concept_ids = self.expand_concepts(
            concept_ids, expand if expand is not None else settings.traverse_expand
        )
        embed_set = set(via_embed or [])
        r = TraverseResult(concept_ids=list(concept_ids))
        seen_p, seen_c, seen_ie, seen_bc = set(), set(), set(), set()

        def add_para(p):
            if p not in seen_p:
                seen_p.add(p)
                r.paras.append(p)

        for cid in concept_ids:
            node = self.concepts.get(cid)
            if not node:
                continue
            mark = " · 유사도 진입" if cid in embed_set else ""
            r.path.append(f"개념[{node['title']}{mark}]")
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
        # e3 인용 이웃 확장
        if hops >= 1:
            for p in list(r.paras):
                for q in self.e3_index.get(p, []):
                    add_para(q)
        # 회수한 문단을 논의한 BC — 근거 표시용. 문단 순서를 따른다.
        seen_bcp: set[str] = set()
        for p in r.paras:
            for bc in self.para_to_bc.get(p, []):
                if bc not in seen_bcp:
                    seen_bcp.add(bc)
                    r.bc_paras.append(bc)
        return r


@lru_cache(maxsize=1)
def get_graph() -> Graph:
    """프로세스 단위 싱글턴."""
    return Graph()

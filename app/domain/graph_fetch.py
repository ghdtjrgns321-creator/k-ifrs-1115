"""온톨로지 노드 → MongoDB 원문 조회 (조회 규약 4종). STEP 5-1 (05-pipeline.md §4).

규약: 문단=메인 paraNum / QNA="QNA-"+id parent / 감리=id parent / IE=category+hierarchy.
"""

from __future__ import annotations

import re
from functools import lru_cache

from pymongo import MongoClient

from app.config import settings

# UI 그룹핑 SSOT — source 정규명. constants.py는 의존성 없음(os만)이라 backend 안전.
from app.ui.constants import DOC_PREFIXES_FINDING, SRC_FINDING, SRC_QNA

_MAIN = settings.mongo_collection_name
_QNA_PARENT = "k-ifrs-1115-qna-parents"
_FINDINGS_PARENT = "k-ifrs-1115-findings-parents"


# 기준서 문단 번호 정렬 — 본문(한국 추가문단 포함) → 부록B → 부록C → 기타.
# "한4.1"이 문단 4 뒤에, "B34A"가 B34 뒤에 오도록 (접두·숫자·나머지)로 쪼갠다.
_PARA_RE = re.compile(r"^(한?[A-Z]*)(\d+)(.*)$")
_PARA_GROUP = {"": 0, "한": 0, "B": 1, "한B": 1, "C": 2, "한C": 2}


def para_sort_key(p: str) -> tuple:
    """paraNum 문자열 → 기준서 등재 순서 키. 형식을 못 읽으면 맨 뒤로."""
    m = _PARA_RE.match(p or "")
    if not m:
        return (9, 0, "", p or "")
    pre, num, rest = m.group(1), int(m.group(2)), m.group(3)
    return (_PARA_GROUP.get(pre, 8), num, rest, p)


@lru_cache(maxsize=1)
def _db():
    return MongoClient(settings.mongo_uri)[settings.mongo_db_name]


def fetch_para(para_num: str) -> dict | None:
    """개념 관할 문단 → 메인 컬렉션 원문. paraNum 우선, chunk_id 패턴 폴백."""
    coll = _db()[_MAIN]
    doc = coll.find_one({"paraNum": para_num}, {"embedding": 0})
    if not doc:
        doc = coll.find_one({"chunk_id": f"1115-{para_num}"}, {"embedding": 0})
    return doc


def fetch_case(db_parent_id: str) -> dict | None:
    """QNA·감리 사례 → parent 컬렉션 원문. db_parent_id 접두사로 컬렉션 결정."""
    coll = _QNA_PARENT if db_parent_id.startswith("QNA-") else _FINDINGS_PARENT
    return _db()[coll].find_one({"_id": db_parent_id})


def fetch_ie(title: str) -> list[dict]:
    """IE 적용사례 → 메인 컬렉션(parent 없음). case_group_title 정확 일치.

    온톨로지 ie title == DB case_group_title(예 "사례 1: 대가의 회수 가능성").
    prefix 매칭은 "사례 1"이 "사례 10~19"까지 잡으므로 정확 일치가 원칙.
    title이 미세하게 다를 때만 번호 경계(?!\\d) prefix로 폴백.
    """
    coll = _db()[_MAIN]
    base = {"category": "적용사례IE"}
    docs = list(coll.find({**base, "case_group_title": title}, {"embedding": 0}))
    if docs:
        return docs
    m = re.match(r"사례\s*\d+", title)
    if not m:
        return []
    pat = "^" + re.escape(m.group(0)) + r"(?!\d)"
    return list(
        coll.find({**base, "case_group_title": {"$regex": pat}}, {"embedding": 0})
    )


# ── 정규화: MongoDB 원문 → generate 소비 스키마 ──────────────────────────
# generate는 source·(content|full_content)·hierarchy·chunk_id·related_paragraphs 소비.
# source=="본문"이면 content, 그 외는 full_content를 읽음(generate.py:133).


def _norm_para(d: dict) -> dict:
    cat = d.get("category", "본문")
    text = d.get("text") or d.get("content") or d.get("fullContent") or ""
    doc = {
        "source": cat,
        "hierarchy": d.get("hierarchy", ""),
        "chunk_id": d.get("chunk_id") or d.get("paraNum", ""),
        "paraNum": d.get("paraNum", ""),
        "related_paragraphs": d.get("related_paragraphs", []),
        # IE 적용사례 그룹핑 키 — UI가 "사례 N"으로 묶으려면 필수(문단은 빈 값).
        "case_group_title": d.get("case_group_title", ""),
    }
    # 본문은 content, 그 외(부록B·BC·IE)는 full_content 슬롯
    doc["content" if cat == "본문" else "full_content"] = text
    return doc


def _norm_case(d: dict) -> dict:
    meta = d.get("metadata", {}) or {}
    pid = str(d.get("_id", ""))
    # UI ACCORDION_GROUPS는 정규 소스명(질의회신/감리사례)만 인식한다. DB 원본
    # category는 "질의회신(신속처리질의)"처럼 세분화돼 있어 그룹 매칭에 실패하므로
    # parent_id 접두어(FSS-/KICPA- vs QNA-)로 정규화한다(fetch_case 라우팅과 동일).
    source = SRC_FINDING if pid.startswith(DOC_PREFIXES_FINDING) else SRC_QNA
    return {
        "source": source,
        "hierarchy": d.get("hierarchy") or meta.get("hierarchy", ""),
        "chunk_id": pid,
        "parent_id": pid,
        "full_content": d.get("content", ""),
        "related_paragraphs": d.get("related_paragraphs")
        or meta.get("related_paragraphs", []),
    }


def fetch_bc(paras: list[str]) -> list[dict]:
    """BC 문단 → 정규화 문서. **LLM 컨텍스트에 넣지 않는다** — 근거 패널 전용.

    Why(따로 두는 이유): BC는 652문단·평균 539자로 본문의 5배다. 회수 문단 하나당
    평균 21개가 달려 있어 컨텍스트에 넣으면 질문당 12만자가 붙는다(현재 전체 11만자).
    반면 "왜 이렇게 정해졌나"를 사람이 읽는 값은 크다. 그래서 LLM은 안 읽고 사람만
    읽는 자리에 놓는다. UI는 source="결론도출근거" 아코디언으로 이미 받는다.
    """
    if not paras:
        return []
    coll = _db()[_MAIN]
    found = {
        d.get("paraNum"): d
        for d in coll.find({"paraNum": {"$in": paras}}, {"embedding": 0})
    }
    return [_norm_para(found[p]) for p in paras if p in found]


def fetch_documents(tr) -> list[dict]:
    """TraverseResult → 정규화 문서 리스트 (05-pipeline §3 fetch_documents).

    문단은 paraNum 배치 조회, 사례는 parent 컬렉션, IE는 메인.
    순서 = 유형 묶음(문단 → 사례 → IE), 문단 안은 기준서 번호순.
    순서는 우선순위 신호가 아니다 — 프롬프트에도 그렇게 명시한다(prompts.py [참고 문서]).
    """
    coll = _db()[_MAIN]
    docs: list[dict] = []

    # 1) 문단 — paraNum 배치 조회 후 기준서 번호순 정렬
    # Why: 과거엔 tr.paras 진입순서를 보존해 topic_hint 문단을 앞에 놨다. 그 명분은
    # generate 슬롯 상한(뒤가 잘림)이었는데 상한이 제거돼(generate.py) 잘릴 자리가 없다.
    # 진입순서를 남겨두면 LLM에 임의의 우선순위 신호만 준다. 기준서 번호순으로 고정한다.
    if tr.paras:
        found = {
            d.get("paraNum"): d
            for d in coll.find({"paraNum": {"$in": tr.paras}}, {"embedding": 0})
        }
        for p in sorted(tr.paras, key=para_sort_key):
            d = found.get(p)
            if d:
                docs.append(_norm_para(d))

    # 2) 사례 — QNA·감리 parent (주제 간선으로 걷은 것만)
    # STEP 6: exclude_qna면 QNA("QNA-" 접두)를 스킵(감리는 유지) — 순환 격리
    seen: set[str] = set()
    case_ids = [c["db_parent_id"] for c in tr.cases]
    for cid in case_ids:
        if cid in seen:
            continue
        seen.add(cid)
        if settings.exclude_qna and cid.startswith("QNA-"):
            continue
        d = fetch_case(cid)
        if d:
            docs.append(_norm_case(d))

    # 3) IE 적용사례 — 메인 컬렉션
    for ie in tr.ie_cases:
        for d in fetch_ie(ie["title"]):
            docs.append(_norm_para(d))

    return docs

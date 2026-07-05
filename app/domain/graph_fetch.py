"""온톨로지 노드 → MongoDB 원문 조회 (조회 규약 4종). STEP 5-1 (05-pipeline.md §4).

규약: 문단=메인 paraNum / QNA="QNA-"+id parent / 감리=id parent / IE=category+hierarchy.
"""

from __future__ import annotations

import re
from functools import lru_cache

from pymongo import MongoClient

from app.config import settings

_MAIN = settings.mongo_collection_name
_QNA_PARENT = "k-ifrs-1115-qna-parents"
_FINDINGS_PARENT = "k-ifrs-1115-findings-parents"


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
    }
    # 본문은 content, 그 외(부록B·BC·IE)는 full_content 슬롯
    doc["content" if cat == "본문" else "full_content"] = text
    return doc


def _norm_case(d: dict) -> dict:
    meta = d.get("metadata", {}) or {}
    return {
        "source": d.get("category") or meta.get("category", "질의회신"),
        "hierarchy": d.get("hierarchy") or meta.get("hierarchy", ""),
        "chunk_id": str(d.get("_id", "")),
        "parent_id": str(d.get("_id", "")),
        "full_content": d.get("content", ""),
        "related_paragraphs": d.get("related_paragraphs")
        or meta.get("related_paragraphs", []),
    }


def fetch_documents(tr, entry_cases: list | None = None) -> list[dict]:
    """TraverseResult + 진입 사례 → 정규화 문서 리스트 (05-pipeline §3 fetch_documents).

    문단은 paraNum 배치 조회, 사례는 parent 컬렉션, IE는 메인.
    순서 = 그래프 위상(문단 → 사례 → IE).
    """
    coll = _db()[_MAIN]
    docs: list[dict] = []

    # 1) 문단 — paraNum 배치 조회 (본문·부록B·BC)
    if tr.paras:
        for d in coll.find({"paraNum": {"$in": tr.paras}}, {"embedding": 0}):
            docs.append(_norm_para(d))

    # 2) 사례 — QNA·감리 parent (traverse + 용어 진입 사례 합집합, 중복 제거)
    seen: set[str] = set()
    case_ids = [c["db_parent_id"] for c in tr.cases] + list(entry_cases or [])
    for cid in case_ids:
        if cid in seen:
            continue
        seen.add(cid)
        d = fetch_case(cid)
        if d:
            docs.append(_norm_case(d))

    # 3) IE 적용사례 — 메인 컬렉션
    for ie in tr.ie_cases:
        for d in fetch_ie(ie["title"]):
            docs.append(_norm_para(d))

    return docs

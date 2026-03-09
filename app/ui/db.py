# app/ui/db.py
# MongoDB 문단 직접 조회 유틸리티.
#
# evidence_docs에 없는 조항도 클릭 한 번으로 원문을 볼 수 있도록
# 매 클릭마다 DB에서 실시간 조회합니다.
# 커넥션은 @st.cache_resource로 캐싱하여 세션당 1회만 연결합니다.

import re
import traceback

import streamlit as st


@st.cache_resource
def _get_mongo_collection():
    """MongoDB 커넥션을 앱 전역에서 단 한 번만 생성합니다.

    매 클릭마다 새 연결을 맺으면 Timeout 에러가 자주 발생하므로
    @st.cache_resource로 프로세스 수명 동안 재사용합니다.
    """
    import sys
    from pathlib import Path

    # streamlit run으로 실행 시 app 모듈을 못 찾는 문제 해결
    root_dir = str(Path(__file__).parent.parent.parent)
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    from pymongo import MongoClient
    from app.config import settings

    client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    db = client[settings.mongo_db_name]
    return db[settings.mongo_collection_name]


def _fetch_para_from_db(para_num: str) -> dict | None:
    """문단 번호(예: 'B23', '55', 'IE7')로 MongoDB에서 해당 문서를 조회합니다.

    paraNum → chunk_id → title → hierarchy 순서로 다중 필드 매칭합니다.
    evidence_docs에 없는 문서라도 DB에서 실시간 조회합니다.
    """
    try:
        coll = _get_mongo_collection()

        # 1순위: paraNum / chunk_id 직접 매칭 (가장 정확한 결과)
        doc = coll.find_one(
            {
                "$or": [
                    {"paraNum": {"$regex": f"^{para_num}$", "$options": "i"}},
                    {"chunk_id": {"$regex": f"^{para_num}$", "$options": "i"}},
                    {"chunk_id": {"$regex": f"-{para_num}$", "$options": "i"}},
                    {"paraNum": para_num},
                    {"chunk_id": f"1115-{para_num}"},
                ]
            },
            {"embedding": 0},
        )
        if doc:
            return dict(doc)

        # 2순위: title 정규식 매칭 (예: title = "문단 B23")
        doc = coll.find_one(
            {"title": {"$regex": para_num, "$options": "i"}},
            {"embedding": 0},
        )
        if doc:
            return dict(doc)

        # 3순위: hierarchy 포함 매칭
        doc = coll.find_one(
            {"hierarchy": {"$regex": para_num, "$options": "i"}},
            {"embedding": 0},
        )
        return dict(doc) if doc else None

    except Exception as e:
        st.error(
            f"DB 조회 중 오류 발생 (단순히 문단이 없는 게 아니라 시스템 오류일 수 있습니다):"
            f"\n\n{e}\n\n{traceback.format_exc()}"
        )
        return None


def _expand_para_range(raw_num: str) -> list[str]:
    """'56~59' → ['56','57','58','59'],  'B20~B27' → ['B20',...,'B27'].

    범위가 아니면 [raw_num]을 그대로 반환합니다.
    20개 초과 범위는 성능 보호를 위해 시작 번호만 반환합니다.
    """
    try:
        # 하위 문단 접미사 제거: "B19(1)" → "B19"
        # DB는 하위 문단을 별도 문서로 저장하지 않으므로 기본 문단으로 조회
        cleaned = re.sub(r"\([0-9가-힣]+\)$", "", raw_num.strip())
        m = re.match(r"^([A-Za-z]*?)(\d+)[~～\-]([A-Za-z]*?)(\d+)$", cleaned)
        if not m:
            return [cleaned]
        prefix1, start_n, prefix2, end_n = (
            m.group(1),
            int(m.group(2)),
            m.group(3),
            int(m.group(4)),
        )
        prefix = prefix1 or prefix2  # 공통 접두사 (B, BC, IE 등)
        if start_n > end_n or (end_n - start_n) > 20:
            return [f"{prefix}{start_n}"]
        return [f"{prefix}{n}" for n in range(start_n, end_n + 1)]
    except Exception as exc:
        import logging
        logging.warning("_expand_para_range 오류: raw_num=%r, exc=%s", raw_num, exc)
        return [raw_num]


def fetch_parent_doc(parent_id: str) -> dict | None:
    """parent_id(chunk_id)로 MongoDB에서 부모 문서를 조회합니다.

    QNA/감리사례의 자식 청크가 부모 원문을 참조할 때 사용합니다.
    """
    if not parent_id:
        return None
    try:
        coll = _get_mongo_collection()
        doc = coll.find_one({"chunk_id": parent_id}, {"embedding": 0})
        return dict(doc) if doc else None
    except Exception:
        return None


def fetch_docs_by_topic(topic_title: str, allowed_sources: tuple[str, ...] = ()) -> list[dict]:
    """소제목(hierarchy 내 토픽명)으로 MongoDB에서 해당 문서를 조회합니다.

    grouping.py에서 소소제목 펼침 시 전체 문단을 가져오는 데 사용됩니다.
    """
    if not topic_title:
        return []
    try:
        coll = _get_mongo_collection()
        query: dict = {"hierarchy": {"$regex": re.escape(topic_title), "$options": "i"}}
        if allowed_sources:
            query["source"] = {"$in": list(allowed_sources)}
        docs = list(coll.find(query, {"embedding": 0}).limit(50))
        return [dict(d) for d in docs]
    except Exception:
        return []


def fetch_docs_by_para_ids(para_ids: tuple) -> list[dict]:
    """문단 번호 목록으로 MongoDB에서 문서를 일괄 조회합니다.

    pinpoint_panel.py에서 AI 답변에 인용된 문단을 근거 패널에 표시하는 데 사용됩니다.
    """
    if not para_ids:
        return []
    try:
        coll = _get_mongo_collection()
        or_clauses = []
        for pid in para_ids:
            or_clauses.extend([
                {"paraNum": pid},
                {"chunk_id": pid},
                {"chunk_id": f"1115-{pid}"},
            ])
        docs = list(coll.find({"$or": or_clauses}, {"embedding": 0}))
        return [dict(d) for d in docs]
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def fetch_ie_case_docs(case_titles: tuple) -> list[dict]:
    """case_group_title 목록으로 IE 적용사례 문서를 일괄 조회합니다.

    evidence.py에서 사례별 그룹 렌더링에 사용됩니다.
    한 번의 DB 쿼리로 모든 사례 문서를 가져와 네트워크 왕복을 최소화합니다.
    """
    if not case_titles:
        return []
    try:
        coll = _get_mongo_collection()
        query = {"case_group_title": {"$in": list(case_titles)}}
        docs = list(coll.find(query, {"embedding": 0}))
        return [dict(d) for d in docs]
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def _validate_refs_against_db(refs_tuple: tuple) -> tuple:
    """참조 후보 목록을 DB에 조회해 실제 존재하는 것만 반환합니다.

    정규식으로 찾은 모든 후보를 DB에서 존재 여부로 필터링합니다.
    DB에 없는 오탐(가짜 참조, 서식 코드 등)은 자동 제외합니다.
    @st.cache_data(ttl=300)으로 5분간 결과 캐시 → DB 부하 최소화.
    """
    valid: list[str] = []
    for ref in refs_tuple:
        try:
            num = re.sub(r"^문단\s*", "", ref).strip()
            # 범위인 경우 시작 번호만 확인 (예: 56~59 → 56)
            check_num = re.split(r"[~～]", num)[0].strip()
            if check_num and _fetch_para_from_db(check_num) is not None:
                valid.append(ref)
        except Exception:
            pass  # DB 오류 시 해당 후보만 조용히 스킵
    return tuple(valid)

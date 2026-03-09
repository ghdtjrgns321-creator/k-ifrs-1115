# app/domain/topic_content_map.py
# 토픽별 큐레이션 데이터 — JSON에서 로드.
#
# 데이터 소싱: topic-curation.txt → 10-parse-curation.py → topics.json
# paras/bc_paras 값은 MongoDB chunk_id "1115-{para}" 패턴으로 조회됨.

import json
from pathlib import Path
from typing import TypedDict


class SectionItem(TypedDict, total=False):
    title: str
    desc: str
    paras: list[str]       # 본문 문단 번호 (예: ["18", "19"])
    bc_paras: list[str]    # BC 문단 번호 (예: ["BC77", "BC78"])


class MainAndBc(TypedDict):
    summary: str
    sections: list[SectionItem]


class IECase(TypedDict, total=False):
    title: str
    desc: str
    para_range: str        # "IE19~IE24"
    case_group_title: str  # fetch_ie_case_docs용 매칭 키


class IESection(TypedDict):
    summary: str
    cases: list[IECase]


class QNASection(TypedDict):
    summary: str
    qna_ids: list[str]     # "QNA-xxx" 패턴 parent_id


class FindingsSection(TypedDict):
    summary: str
    finding_ids: list[str]  # "FSS-xxx" / "KICPA-xxx" 패턴 parent_id


class TopicData(TypedDict, total=False):
    display_name: str
    cross_links: list[str]  # 관련 토픽 추천 (topic_browse에서 활용)
    main_and_bc: MainAndBc
    ie: IESection
    qna: QNASection
    findings: FindingsSection


# ── JSON에서 토픽 데이터 로드 ─────────────────────────────────────────────────
_JSON_PATH = Path(__file__).parent.parent.parent / "data" / "topic-curation" / "topics.json"

TOPIC_CONTENT_MAP: dict[str, TopicData] = {}

if _JSON_PATH.exists():
    _raw: dict = json.loads(_JSON_PATH.read_text(encoding="utf-8"))
    for _key, _data in _raw.items():
        TOPIC_CONTENT_MAP[_key] = _data  # type: ignore[assignment]


# ── JSON에 없는 개별 서브토픽용 스텁 ──────────────────────────────────────────
# 통합 버튼("통제 이전의 특수 형태", "고객의 권리 관련")의 하위 개별 토픽은
# JSON에 포함되지 않으므로 스텁으로 등록 (검색 폴백용)
_STUB_TOPICS: dict[str, tuple[str, list[str]]] = {
    "재매입약정": ("재매입약정", ["기간에 걸쳐 vs 한 시점 인식"]),
    "위탁약정": ("위탁약정", []),
    "미인도청구약정": ("미인도청구약정", ["기간에 걸쳐 vs 한 시점 인식"]),
    "고객의 인수": ("고객의 인수", ["기간에 걸쳐 vs 한 시점 인식"]),
    "고객의 선택권": ("고객의 선택권", ["수행의무 식별"]),
    "고객이 행사하지 않은 권리": ("고객이 행사하지 않은 권리", []),
    "환불되지 않는 선수수수료": ("환불되지 않는 선수수수료", ["계약의 식별"]),
}

_EMPTY_STUB: TopicData = {
    "display_name": "",
    "main_and_bc": {"summary": "", "sections": []},
    "ie": {"summary": "", "cases": []},
    "qna": {"summary": "", "qna_ids": []},
    "findings": {"summary": "", "finding_ids": []},
}

for _key, (_display, _links) in _STUB_TOPICS.items():
    if _key not in TOPIC_CONTENT_MAP:
        TOPIC_CONTENT_MAP[_key] = {
            **_EMPTY_STUB,
            "display_name": _display,
            "cross_links": _links,
        }

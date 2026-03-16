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
    paras: list[str]  # 본문 문단 번호 (예: ["18", "19"])
    bc_paras: list[str]  # BC 문단 번호 (예: ["BC77", "BC78"])


class MainAndBc(TypedDict):
    summary: str
    sections: list[SectionItem]


class IECase(TypedDict, total=False):
    title: str
    desc: str
    para_range: str  # "IE19~IE24"
    case_group_title: str  # fetch_ie_case_docs용 매칭 키


class IESection(TypedDict):
    summary: str
    cases: list[IECase]


class QNASection(TypedDict):
    summary: str
    qna_ids: list[str]  # "QNA-xxx" 패턴 parent_id


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
# Why: data/ 폴더는 .gitignore + .dockerignore로 제외 → git/Docker에 포함되지 않음
# app/domain/ 안에 두면 git 추적 + Docker COPY app/ 에 자동 포함
_JSON_PATH = Path(__file__).parent / "topics.json"

TOPIC_CONTENT_MAP: dict[str, TopicData] = {}

if _JSON_PATH.exists():
    _raw: dict = json.loads(_JSON_PATH.read_text(encoding="utf-8"))
    for _key, _data in _raw.items():
        TOPIC_CONTENT_MAP[_key] = _data  # type: ignore[assignment]

# Why: topics.json 로드 실패 시 모든 INDEX가 빈 dict지만 에러가 없어
#       문제를 인지하기 어려움 → 명시적 경고
if not TOPIC_CONTENT_MAP:
    import logging as _logging
    _logging.warning(
        "TOPIC_CONTENT_MAP이 비어있습니다. topics.json 경로: %s (존재: %s)",
        _JSON_PATH, _JSON_PATH.exists(),
    )


# ── 토픽 desc 추출 ──────────────────────────────────────────────────────────


def get_topic_descs(topic_name: str) -> str:
    """토픽명으로 topics.json의 main_and_bc + ie 섹션 desc를 수집하여 텍스트 반환.

    Why: 매칭된 토픽의 요약(desc)을 프롬프트에 [참고 지식]으로 주입하면,
    기준서 원문 수십 개를 주입하지 않고도 LLM이 필요한 지식을 모두 참조 가능.
    """
    topic = TOPIC_CONTENT_MAP.get(topic_name)
    if not topic:
        return ""
    lines: list[str] = []
    # main_and_bc 섹션의 title + desc
    for section in topic.get("main_and_bc", {}).get("sections", []):
        title = section.get("title", "")
        desc = section.get("desc", "")
        if desc:
            lines.append(f"- {title}: {desc}")
    # ie 섹션의 case desc
    for case in topic.get("ie", {}).get("cases", []):
        title = case.get("title", "")
        desc = case.get("desc", "")
        if desc:
            lines.append(f"- {title}: {desc}")
    return "\n".join(lines)


# ── 문단번호 → section desc 역인덱스 ──────────────────────────────────────────
# Why: UX3,4 evidence 패널에서 문단번호로 큐레이션 desc를 조회하여 표시
# 범위 표기("56~58") → 개별 확장하여 각 문단에 동일 desc 매핑


def _expand_range(range_str: str) -> list[str]:
    """'56~58' → ['56','57','58'], 'B3~B4' → ['B3','B4']."""
    import re as _re

    m = _re.match(r"([A-Za-z]*)(\d+)[~～\-]([A-Za-z]*)(\d+)", range_str)
    if not m:
        return [range_str]
    prefix = m.group(1) or m.group(3)
    start, end = int(m.group(2)), int(m.group(4))
    return [f"{prefix}{n}" for n in range(start, end + 1)]


PARA_DESC_INDEX: dict[str, str] = {}
# para → (section_title, desc) 매핑 — 낱개 문단을 섹션별로 재그룹핑할 때 사용
PARA_SECTION_INDEX: dict[str, tuple[str, str]] = {}

for _topic_data in TOPIC_CONTENT_MAP.values():
    for _sec in _topic_data.get("main_and_bc", {}).get("sections", []):
        _title = _sec.get("title", "")
        _desc = _sec.get("desc", "")
        for _p in _sec.get("paras", []) + _sec.get("bc_paras", []):
            for _ep in _expand_range(_p):
                if _ep not in PARA_SECTION_INDEX:
                    PARA_SECTION_INDEX[_ep] = (_title, _desc)
                if _desc and _ep not in PARA_DESC_INDEX:
                    PARA_DESC_INDEX[_ep] = _desc


def get_desc_for_para(para_num: str) -> str:
    """문단번호로 큐레이션 section desc를 조회합니다."""
    return PARA_DESC_INDEX.get(para_num, "")


def get_section_for_para(para_num: str) -> tuple[str, str]:
    """문단번호로 (section_title, desc)를 조회합니다."""
    return PARA_SECTION_INDEX.get(para_num, ("", ""))


# ── parent_id → desc 역인덱스 (QNA/감리사례) ────────────────────────────────
# Why: UX3,4 evidence 패널에서 QNA/감리사례 expander에 큐레이션 desc 표시
# topic_tabs.py와 동일 구조: 개별 desc(qna_descs/finding_descs)만 사용, summary 미혼합
PDR_DESC_INDEX: dict[str, str] = {}

for _topic_data in TOPIC_CONTENT_MAP.values():
    # QNA: 개별 desc만 (topic_tabs.py와 동일)
    for _qid, _qdesc in _topic_data.get("qna", {}).get("qna_descs", {}).items():
        if _qid and _qdesc and _qid not in PDR_DESC_INDEX:
            PDR_DESC_INDEX[_qid] = _qdesc

    # Findings: 개별 desc만 (topic_tabs.py와 동일)
    for _fid, _fdesc in (
        _topic_data.get("findings", {}).get("finding_descs", {}).items()
    ):
        if _fid and _fdesc and _fid not in PDR_DESC_INDEX:
            PDR_DESC_INDEX[_fid] = _fdesc

# 교육자료(EDU): decision_trees.py의 4_precedents에서 자동 추출
# Why: topics.json에 edu 섹션이 없어서, 큐레이션된 설명을 decision_trees에서 가져옴
import re as _re

from app.domain.decision_trees import MASTER_DECISION_TREES as _TREES

for _tree in _TREES.values():
    for _sec_val in _tree.values():
        _texts: list[str] = []
        if isinstance(_sec_val, dict):
            for _sv in _sec_val.values():
                if isinstance(_sv, list):
                    _texts.extend(s for s in _sv if isinstance(s, str))
        elif isinstance(_sec_val, list):
            _texts.extend(s for s in _sec_val if isinstance(s, str))
        for _t in _texts:
            _m = _re.search(r"\[?(EDU-[\w-]+)\]?\s*(?:\(실무 팁\))?\s*(.+)", _t)
            if _m:
                _eid, _edesc = _m.group(1), _m.group(2).strip()
                if _eid not in PDR_DESC_INDEX or len(_edesc) > len(PDR_DESC_INDEX[_eid]):
                    PDR_DESC_INDEX[_eid] = _edesc


def get_desc_for_pdr(parent_id: str) -> str:
    """parent_id로 QNA/감리사례/교육자료 큐레이션 desc를 조회합니다."""
    return PDR_DESC_INDEX.get(parent_id, "")


# ── case_group_title → desc 역인덱스 (IE 적용사례) ────────────────────────
# Why: UX3,4 evidence 패널에서 IE 사례별 expander에 큐레이션 desc 표시
IE_CASE_DESC_INDEX: dict[str, str] = {}
IE_CASE_SUMMARY_INDEX: dict[str, str] = {}  # 토픽별 ie.summary


def _extract_case_num(title: str) -> str:
    """'사례 45: 대리인' → '사례 45', '사례 1A: ...' → '사례 1A'."""
    import re as _re

    m = _re.match(r"(사례\s*\d+[A-Za-z]?)", title)
    return m.group(1) if m else title


for _topic_data in TOPIC_CONTENT_MAP.values():
    _ie_sec = _topic_data.get("ie", {})
    _ie_summary = _ie_sec.get("summary", "")
    for _case in _ie_sec.get("cases", []):
        _raw = _case.get("case_group_title", "") or _case.get("title", "")
        _cdesc = _case.get("desc", "")
        # DB의 case_group_title은 "사례 45" 형태 → 키도 정규화
        _cgt = _extract_case_num(_raw) if _raw else ""
        if _cgt and _cdesc and _cgt not in IE_CASE_DESC_INDEX:
            IE_CASE_DESC_INDEX[_cgt] = _cdesc
    # 유효한 summary만 저장 (쉼표/공백만 있는 경우 제외)
    if _ie_summary and len(_ie_summary.strip().strip(",")) > 2:
        for _case in _ie_sec.get("cases", []):
            _raw = _case.get("case_group_title", "") or _case.get("title", "")
            _cgt = _extract_case_num(_raw) if _raw else ""
            if _cgt and _cgt not in IE_CASE_SUMMARY_INDEX:
                IE_CASE_SUMMARY_INDEX[_cgt] = _ie_summary


# topics.json에 등록되지 않은 사례의 desc 보충
# Why: topics.json의 IE cases는 49개이나 DB에는 65개 사례 존재
_FALLBACK_IE_DESCS = {
    "사례 2": "경제적 어려움 지역 고객에 대해 약속 대가 전액 회수 불확실 시, 암묵적 가격할인을 반영하여 거래가격을 조정합니다.",
    "사례 3": "응급실 비보험환자에 대한 의료용역은 계약요건 미충족으로 수익인식이 지연되며, 이후 지급능력 등 추가정보에 따라 가격할인을 반영합니다.",
    "사례 10": "재화와 용역이 개별적으로 구별되지 않으면 전체 계약을 단일 수행의무로 결합하여 인식합니다.",
    "사례 11": "소프트웨어 라이선스, 설치용역, 갱신, 기술지원을 별도 수행의무로 구별하여 수익을 분리 인식합니다.",
    "사례 12": "유통업자에 대한 무료 유지보수용역 제공 약속은 계약 내 별도 수행의무로 식별합니다.",
    "사례 15": "특정 고객 맞춤 자산은 대체 용도가 없으므로 수행의무를 기간에 걸쳐 이행합니다.",
    "사례 20": "변동대가인 위약금은 추정 후 제약요건을 충족하는 범위에서만 거래가격에 포함합니다.",
    "사례 21": "변동대가가 포함된 기간 이행 수행의무는 각 변동요소별로 합리적 추정하여 거래가격에 반영합니다.",
    "사례 36": "계약체결 증분원가 중 영업사원 수수료만 자산화하며, 법률 실사 비용 등 비증분원가는 즉시 비용 처리합니다.",
    "사례 37": "계약이행원가는 미래 용역수수료 회수 기대에 따라 예상 고객기간에 걸쳐 자산으로 인식하고 상각합니다.",
    "사례 41": "수익은 경제적 특성별로 부문, 지리적 시장, 제품계열, 인식시기별로 구분하여 공시합니다.",
    "사례 42": "나머지 수행의무에 배분된 거래가격 공시는 청구권이 수행 완료 부분 가치에 직접 상응하면 실무적 간편법으로 면제됩니다.",
    "사례 43": "수익인식 시기가 불확실한 경우 나머지 수행의무에 배분된 거래가격은 존속 기간 범위에 대한 질적 설명과 함께 공시합니다.",
    "사례 51": "갱신 선택권이 고객에게 중요한 권리를 제공하면 별도 수행의무로 인식하고 대가를 기간별로 배분합니다.",
    "사례 54": "소프트웨어 라이선스는 사용권으로서 한 시점에 수익을 인식하며, 갱신과 기술지원은 기간에 걸쳐 인식합니다.",
    "사례 55": "지적재산 라이선스가 접근권이면 기간에 걸쳐, 사용권이면 한 시점에 수익을 인식합니다.",
    "사례 56": "라이선스와 제조 용역이 불가분이면 단일 수행의무로 결합하여 인식합니다.",
    "사례 57": "프랜차이즈 라이선스와 장비 제공은 별도 수행의무로 식별되며, 로열티는 판매기준으로 인식합니다.",
    "사례 58": "캐릭터 이미지 라이선스가 접근권이면 라이선스 기간에 걸쳐 정액법으로 수익을 인식합니다.",
    "사례 59": "지적재산 사용권 라이선스는 이전 시점에 한 시점 수익으로 인식합니다.",
    "사례 60": "지적재산 라이선스의 판매기준 로열티는 후속 판매 또는 사용이 일어날 때 수익을 인식합니다.",
    "사례 61": "스포츠 팀 로고 라이선스는 접근권으로서 기간에 걸쳐 수익을 인식합니다.",
    "사례 64": "계약이행원가 자산의 손상 여부를 미래 현금흐름 추정치와 비교하여 판단합니다.",
    "사례 65": "계약이행원가 자산을 재화나 용역 이전 패턴에 따라 체계적으로 상각합니다.",
}
for _k, _v in _FALLBACK_IE_DESCS.items():
    if _k not in IE_CASE_DESC_INDEX:
        IE_CASE_DESC_INDEX[_k] = _v


def get_desc_for_ie_case(case_group_title: str) -> str:
    """case_group_title로 IE 적용사례 큐레이션 desc를 조회합니다."""
    return IE_CASE_DESC_INDEX.get(case_group_title, "")


def get_summary_for_ie_cases(case_group_titles: list[str]) -> str:
    """IE 사례 목록에서 첫 번째 매칭되는 ie.summary를 반환합니다."""
    for cgt in case_group_titles:
        s = IE_CASE_SUMMARY_INDEX.get(cgt, "")
        if s:
            return s
    return ""



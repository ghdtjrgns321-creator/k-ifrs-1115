# app/ui/evidence.py
# 카테고리별 아코디언 문서 패널 — evidence 화면과 ai_answer Split View에서 재사용.
#
# ai_answer 페이지에서는 본문/적용지침/결론도출근거를
# 벡터검색이 아닌 AI 답변에서 직접 인용된 문단만 DB에서 조회하여 표시합니다.
#
# components.py에서 분리. _render_evidence_panel이 유일한 public 함수.

import re

import streamlit as st

from app.ui.constants import (
    ACCORDION_GROUPS,
    SRC_APPENDIX_B,
    SRC_BC,
    SRC_BODY,
    SRC_DEFINITION,
    SRC_EFFECTIVE,
)
from app.ui.db import _expand_para_range, fetch_docs_by_para_ids, fetch_ie_case_docs
from app.ui.doc_helpers import (
    _apply_cluster_first_bonus,
    _get_doc_para_num,
    _normalize_case_group_title,
)
from app.domain.topic_content_map import (
    get_desc_for_ie_case,
    get_desc_for_pdr,
    get_summary_for_ie_cases,
)
from app.ui.doc_renderers import (
    _render_document_expander,
    _render_pdr_expander,
)
from app.ui.text import _esc, _extract_para_refs, _para_ref_to_num

# AI 답변 페이지에서 벡터검색 대신 인용 문단만 표시할 소스 유형
_STANDARD_SOURCES = frozenset(
    {SRC_BODY, SRC_APPENDIX_B, SRC_BC, SRC_DEFINITION, SRC_EFFECTIVE}
)

# 주제별 그룹핑 대상 — 본문/적용지침, BC
_TOPIC_GROUPABLE: dict[str, tuple[str, ...]] = {
    "📘 기준서 본문 및 적용지침": (SRC_BODY, SRC_APPENDIX_B),
    "🔍 결론도출근거(BC)": (SRC_BC,),
}

# QNA/감리사례 그룹
_PDR_GROUPS = frozenset({"💬 질의회신(QNA)", "🚨 감리지적사례"})


def _ie_desc_blockquote(desc: str) -> None:
    """IE 사례 desc를 연한 회색 블록으로 렌더링합니다."""
    if not desc:
        return
    import html as _html

    _d = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", _html.escape(desc))
    _d = re.sub(r"(?<=[가-힣])\.\s+", ".<br>", _d)
    _d = _d.replace("\n", "<br>")
    st.markdown(
        f'<div style="line-height:1.75; color:#475569; font-size:0.88em; '
        f"padding:0.5rem 0.75rem; background:#f8fafc; "
        f'border-left:2px solid #cbd5e1; border-radius:2px;">'
        f"{_d}</div>",
        unsafe_allow_html=True,
    )


def _get_cited_ids() -> set[str]:
    """AI 답변에서 직접 인용된 모든 ID(문단 번호 + QNA/감리 ID)를 추출합니다.

    3종류의 인용 ID를 통합 set으로 반환:
      - 문단: "문단 56", "문단 B20~B21" → {"56", "B20", "B21"}
      - QNA: "QNA-2019-001" → {"QNA-2019-001"}
      - 감리: "FSS-CASE-001" → {"FSS-CASE-001"}
    """
    answer = st.session_state.get("ai_answer", "")
    if not answer:
        return set()

    # 문단 번호 추출
    refs = _extract_para_refs(answer)
    cited_paras: set[str] = set()
    for ref in refs:
        num = _para_ref_to_num(ref)
        cited_paras.update(_expand_para_range(num))

    # QNA/감리사례 ID 추출 (answer 정규식 + LLM 구조화 선언 cited_cases 합집합)
    pdr_ids = set(re.findall(r"(QNA-[\w-]+|FSS-CASE-[\w-]+|KICPA-CASE-[\w-]+)", answer))
    pdr_ids |= set(st.session_state.get("cited_cases", []) or [])

    return cited_paras | pdr_ids


def _extract_num(doc: dict) -> tuple[str, int, str]:
    """suffix 포함 자연 정렬: B59 → B59A → B59B"""
    para_str = _get_doc_para_num(doc)
    m = re.match(r"([A-Za-z]*)(\d+)([A-Za-z]*)", para_str)
    if m:
        return (m.group(1), int(m.group(2)), m.group(3))
    return ("ZZ", 999999, "")


def _get_cited_standard_docs() -> list[dict]:
    """AI 답변 텍스트에서 직접 인용된 문단만 DB에서 조회합니다.

    '문단 46', '문단 B20~B21' 등의 참조를 파싱하여 해당 기준서 문서를 반환합니다.
    본문/적용지침/결론도출근거 소스만 필터링하여 반환합니다.
    """
    answer = st.session_state.get("ai_answer", "")
    if not answer:
        return []

    # 같은 답변에 대한 중복 DB 쿼리 방지 (Streamlit rerun 대응)
    cache_key = hash(answer)
    if st.session_state.get("_cited_docs_cache_key") == cache_key:
        return st.session_state.get("_cited_docs_cache", [])

    refs = _extract_para_refs(answer)
    if not refs:
        return []

    # "문단 B23" → "B23", 범위 확장 "56~59" → ["56","57","58","59"]
    para_nums: set[str] = set()
    for ref in refs:
        num = _para_ref_to_num(ref)
        para_nums.update(_expand_para_range(num))

    if not para_nums:
        return []

    raw_docs = fetch_docs_by_para_ids(tuple(sorted(para_nums)))

    result: list[dict] = []
    seen_ids: set[str] = set()
    for doc in raw_docs:
        # DB 문서는 metadata를 root 레벨로 펼쳐서 저장 (04-embed.py)
        # category, hierarchy, paraNum 등이 root에 위치
        source = (
            doc.get("category", "")
            or doc.get("source", "")
            or (doc.get("metadata") or {}).get("category", "")
        )
        if source not in _STANDARD_SOURCES:
            continue

        cid = doc.get("chunk_id", "") or str(doc.get("_id", ""))
        if cid in seen_ids:
            continue
        seen_ids.add(cid)

        result.append(
            {
                "source": source,
                "hierarchy": doc.get("hierarchy", ""),
                "title": doc.get("title", ""),
                "content": doc.get("content", "") or doc.get("text", ""),
                "full_content": doc.get("content", "") or doc.get("text", ""),
                "chunk_id": doc.get("chunk_id", ""),
                "paraNum": doc.get("paraNum", ""),
                "metadata": doc.get("metadata") or {},
                "score": 0.0,
            }
        )

    # 캐시에 저장
    st.session_state["_cited_docs_cache_key"] = cache_key
    st.session_state["_cited_docs_cache"] = result
    return result


# ---------------------------------------------------------------------------
# 서브 렌더링 함수들 — _render_evidence_panel에서 분리
# ---------------------------------------------------------------------------


def _prepare_ai_answer_docs(docs: list[dict]) -> list[dict]:
    """ai_answer 페이지: LLM이 실제 읽은 컨텍스트를 좌측에 노출.

    docs = context_docs(via_topic 한정 — 케이스·IE는 LLM 지목 주제 직결만, 플러드 없음).
      - QNA/감리/IE: 컨텍스트 그대로 노출 (그래프가 개념 직결로 고른 관련 근거)
      - 문단: 개념 관할 문단이 많아 answer가 인용한 것만 (_get_cited_standard_docs)
    답변이 실제 인용한 것은 렌더러가 cited_ids/cited_case_nums로 📌 강조한다.
    """
    docs = [d for d in docs if d.get("source", "") not in _STANDARD_SOURCES]
    docs.extend(_get_cited_standard_docs())
    return docs


def _get_ie_desc_clean(cgt: str) -> str:
    """case_group_title에서 짧은 키로 desc 조회 + 쓰레기 문자 정리."""
    short_key = re.split(r"[:：]", cgt, maxsplit=1)[0].strip()
    desc = get_desc_for_ie_case(short_key) or get_desc_for_ie_case(cgt)
    if desc:
        desc = re.sub(r"[\s,\.]+$", "", desc).strip() + "."
    return desc if desc and len(desc) > 5 else ""


def _render_ie_group(
    group_name: str,
    group_docs: list[dict],
    cited_ids: set[str] | None = None,
) -> None:
    """IE 적용사례 그룹: 사례별 expander + 더보기 렌더링."""
    # 사례별 분류
    seen_cases: set[str] = set()
    case_order: list[str] = []
    no_case_docs: list[dict] = []
    for d in group_docs:
        raw_cgt = d.get("case_group_title", "")
        cgt = _normalize_case_group_title(raw_cgt) if raw_cgt else ""
        if not cgt:
            no_case_docs.append(d)
        elif cgt not in seen_cases:
            seen_cases.add(cgt)
            case_order.append(cgt)

    # 건수 = 사례 그룹 수 — 청크(문단) 수를 표기하면 "41건"처럼 실제 사례 수와 불일치
    total_count = len(case_order) + len(no_case_docs)
    st.markdown(f"### {group_name} — {total_count}건")

    # IE 섹션 summary 표시 (topic_tabs.py와 동일)
    ie_summary = get_summary_for_ie_cases(case_order)
    if ie_summary:
        _ie_desc_blockquote(ie_summary)

    # 모든 사례 문서를 1번 DB 쿼리 후 분류
    all_ie_docs = fetch_ie_case_docs(tuple(case_order)) if case_order else []
    case_docs_map: dict[str, list[dict]] = {}
    for doc in all_ie_docs:
        raw_cgt = doc.get("case_group_title", "")
        cgt_key = _normalize_case_group_title(raw_cgt) if raw_cgt else ""
        if cgt_key:
            case_docs_map.setdefault(cgt_key, []).append(doc)

    INITIAL_CASES = 3
    main_cases = case_order[:INITIAL_CASES]
    rest_cases = case_order[INITIAL_CASES:]

    # AI 답변에서 인용된 사례 번호 추출 (cited_ids와 별도)
    answer = st.session_state.get("ai_answer", "")
    cited_case_nums = (
        set(re.findall(r"사례\s*(\d+[A-Z]?)", answer)) if answer else set()
    )
    # LLM 구조화 선언 cited_ie도 강조 대상에 합류 (산문에 "Case 1"만 써도 인식)
    for _x in st.session_state.get("cited_ie", []) or []:
        _m = re.match(r"사례\s*(\d+[A-Za-z]?)", _x)
        if _m:
            cited_case_nums.add(_m.group(1))

    doc_idx = 0
    for cgt in main_cases:
        case_docs = sorted(case_docs_map.get(cgt, []), key=_extract_num)
        case_desc = _get_ie_desc_clean(cgt)
        # AI가 직접 인용한 사례는 볼드 표시
        m = re.match(r"사례\s*(\d+[A-Z]?)", cgt)
        case_num = m.group(1) if m else ""
        is_cited = case_num in cited_case_nums
        icon = "📌" if is_cited else "📎"
        label = f"{icon} :blue[**{cgt}**]" if is_cited else f"{icon} {cgt}"
        with st.expander(label, expanded=is_cited):
            _ie_desc_blockquote(case_desc)
            for doc in case_docs:
                _render_document_expander(doc, doc_index=doc_idx)
                doc_idx += 1

    if rest_cases or no_case_docs:
        st.markdown(
            "<div style='border-top:1.5px dashed #b8cef0; "
            "margin:1.25rem 0 0.25rem;'></div>",
            unsafe_allow_html=True,
        )
        with st.expander(
            f"📂 다른 사례 더보기 ({len(rest_cases) + len(no_case_docs)}건)",
            expanded=False,
        ):
            with st.container(border=True):
                for cgt in rest_cases:
                    case_docs = sorted(case_docs_map.get(cgt, []), key=_extract_num)
                    case_desc = _get_ie_desc_clean(cgt)
                    with st.expander(f"📎 {_esc(cgt)}", expanded=False):
                        _ie_desc_blockquote(case_desc)
                        for doc in case_docs:
                            _render_document_expander(doc, doc_index=doc_idx)
                            doc_idx += 1
                if no_case_docs:
                    with st.expander(
                        f"📄 기타 ({len(no_case_docs)}건)", expanded=False
                    ):
                        for d in no_case_docs:
                            _render_document_expander(d, doc_index=doc_idx)
                            doc_idx += 1


def _render_pdr_group(
    group_docs: list[dict],
    cited_ids: set[str] | None = None,
) -> None:
    """QNA/감리사례 그룹: parent_id 기준 dedup 후 전량 메인 렌더링.

    답변이 인용한 것은 cited_ids로 :blue[**[ID]**] 강조(숨김·강등 없음).
    """
    unique_parents: dict[str, dict] = {}
    no_parent_docs: list[dict] = []
    for d in group_docs:
        pid = d.get("parent_id", "")
        if pid:
            if pid not in unique_parents:
                unique_parents[pid] = d
        else:
            no_parent_docs.append(d)

    pdr_docs = list(unique_parents.values()) + no_parent_docs
    for i, d in enumerate(pdr_docs):
        pid = d.get("parent_id", "")
        if pid:
            _render_pdr_expander(
                d, doc_index=i, entry_desc=get_desc_for_pdr(pid), cited_ids=cited_ids
            )
        else:
            _render_document_expander(d, doc_index=i, cited_ids=cited_ids)


def _render_default_group(group_docs: list[dict]) -> None:
    """기타 그룹: 상위 3개 표시 + 나머지 '더보기' 토글."""
    INITIAL = 3
    initial_docs = group_docs[:INITIAL]
    rest_docs = group_docs[INITIAL:]

    initial_docs.sort(key=_extract_num)
    for i, d in enumerate(initial_docs):
        _render_document_expander(d, doc_index=i)

    if rest_docs:
        rest_docs.sort(key=_extract_num)
        with st.expander(f"📂 더보기 ({len(rest_docs)}건)", expanded=False):
            with st.container(border=True):
                for i, d in enumerate(rest_docs):
                    _render_document_expander(d, doc_index=INITIAL + i)


# ---------------------------------------------------------------------------
# 메인 오케스트레이터
# ---------------------------------------------------------------------------


def _render_evidence_panel() -> None:
    """카테고리별 아코디언 문서 목록을 렌더링합니다.

    - 섹션별로 상위 3~5개 문서만 초기 표시
    - 6개 이상이면 토글 버튼으로 나머지 펼쳐보기
    """
    docs: list[dict] = st.session_state.get("evidence_docs", [])

    if not docs:
        st.info("검색된 문서가 없습니다.")
        return

    # 전체 문서 중복 제거 — chunk_id 기준
    seen_ids: set[str] = set()
    deduped: list[dict] = []
    for doc in docs:
        uid = doc.get("chunk_id") or doc.get("id") or ""
        if uid and uid in seen_ids:
            continue
        if uid:
            seen_ids.add(uid)
        deduped.append(doc)
    docs = deduped

    # AI 답변 페이지: 그래프가 가져온 QNA/IE/감리를 그대로 메인으로 노출
    # (표준 문단만 인용분으로 교체). 인용은 렌더러가 강조만 함.
    is_ai_answer = st.session_state.get("page_state") == "ai_answer"
    if is_ai_answer:
        docs = _prepare_ai_answer_docs(docs)

    # ai_answer 단계에서만 인용된 ID 집합 계산 (1/2단계 무영향)
    cited_ids = _get_cited_ids() if is_ai_answer else None

    docs = sorted(docs, key=_extract_num)

    # 문서를 그룹명별로 분류
    groups: dict[str, list[dict]] = {g: [] for g in ACCORDION_GROUPS}

    for doc in docs:
        for group_name, sources in ACCORDION_GROUPS.items():
            if doc.get("source", "") in sources:
                groups[group_name].append(doc)
                break

    # 그룹별 렌더링 (메인 문서가 있는 그룹만 표시)
    for group_name, group_docs in groups.items():
        if not group_docs:
            continue

        # cluster-first 보너스 적용 후 점수 재정렬
        group_docs = _apply_cluster_first_bonus(group_docs)
        group_docs.sort(key=lambda d: d.get("score", 0.0), reverse=True)

        # IE 적용사례 그룹
        if group_name == "📋 적용사례(IE)":
            _render_ie_group(group_name, group_docs, cited_ids=cited_ids)
            continue

        # h3 헤더 (IE 이외 그룹 공통)
        st.markdown(f"### {group_name} — {len(group_docs)}건")

        # 본문/적용지침/BC → 주제별 그룹핑
        if group_name in _TOPIC_GROUPABLE:
            from app.ui.grouping import _render_topic_grouped_docs

            search_query = st.session_state.get("search_query") or ""
            group_docs_sorted = sorted(group_docs, key=_extract_num)
            _render_topic_grouped_docs(
                group_docs_sorted,
                idx_offset=0,
                score_ordered=group_docs,
                search_query=search_query,
                allowed_sources=_TOPIC_GROUPABLE[group_name],
                cited_ids=cited_ids,
            )
            continue

        # QNA/감리사례
        if group_name in _PDR_GROUPS:
            _render_pdr_group(group_docs, cited_ids=cited_ids)
            continue

        # 기타 그룹
        _render_default_group(group_docs)

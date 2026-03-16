# app/ui/doc_renderers.py
# 개별 문서 Streamlit 렌더링 — 모던 카드 UI.
#
# 디자인 원칙:
#   - 라벨은 짧고 깔끔하게 (문단 번호 + 제목, 중복 없음)
#   - 본문은 줄바꿈 유지 + line-height 1.85
#   - 출처 경로는 하단 푸터에 1번만
#   - 관련 조항 칩은 클릭 가능

import html
import re

import streamlit as st

from app.ui.db import _validate_refs_against_db, fetch_parent_doc
from app.ui.doc_helpers import (
    _build_pdr_label,
    _build_self_ids,
    _format_pdr_content,
    _get_doc_para_num,
    _get_parent_field,
    _hierarchy_path,
    _ie_para_sort_key,
    _is_ie_doc,
    _normalize_case_group_title,
)
from app.ui.text import (
    _esc,
    _extract_para_refs,
    _normalize_doc_content,
    clean_text,
    md_tables_to_html,
)


# ── 관련 조항 칩 ──────────────────────────────────────────────────────────────


def _render_para_chips(
    text: str,
    context_key: str,
    doc_index: int = 0,
    self_ids: set[str] | None = None,
) -> None:
    """본문에서 탐지된 문단 참조를 클릭 가능한 pill 태그로 렌더링합니다."""
    self_ids = self_ids or set()
    all_refs = _extract_para_refs(text)
    seen: set[str] = set()
    refs = []
    for r in all_refs:
        if r not in self_ids and r not in seen:
            seen.add(r)
            refs.append(r)
    if not refs:
        return

    refs = list(_validate_refs_against_db(tuple(refs)))
    if not refs:
        return

    st.caption("🔗 관련 조항")
    safe_key = re.sub(r"[^\w]", "_", f"chips_{doc_index}_{context_key}")

    def outer_pill_callback():
        val = st.session_state[safe_key]
        if val:
            val_clean = val.replace("～", "~")
            st.session_state.modal_history = [val_clean]
            st.session_state.show_modal = True
            st.session_state[safe_key] = None

    st.pills(
        label="관련 조항",
        options=[r.replace("~", "～") for r in refs],
        label_visibility="collapsed",
        key=safe_key,
        on_change=outer_pill_callback,
    )


# ── Expander 라벨 생성 ────────────────────────────────────────────────────────


def _make_label(doc: dict, cited_ids: set[str] | None = None) -> str:
    """깔끔한 expander 라벨을 생성합니다.

    결과: "문단 56 - 변동대가의 유의적 환원 가능성"
    title에 이미 문단 번호가 포함되면 중복 안 붙임.
    cited_ids가 주어지고 해당 문단이 포함되면 :blue[**문단 XX**]로 강조합니다.
    """
    title = doc.get("title", "")
    para = _get_doc_para_num(doc)
    hierarchy = doc.get("hierarchy", "")
    cgt = doc.get("case_group_title", "")

    # AI 답변에서 인용된 문단인지 확인
    is_cited = bool(cited_ids and para and para in cited_ids)
    para_tag = f":blue[**문단 {para}**]" if is_cited else f"문단 {para}"

    # IE 사례 내 개별 문서: 사례 그룹 expander 안에서 보이므로 cgt 생략
    # "문단 IE49 - 소프트웨어 라이선스와 서비스 구별" 형태로 짧게
    if cgt and para:
        # title에서 "[hierarchy] 문단 IEXXX - " 접두사 제거 → 순수 제목만 추출
        clean = re.sub(r"^\[.*?\]\s*문단\s*\S+\s*-\s*", "", title) if title else ""
        suffix = f" - {clean}" if clean and clean != title else ""
        # clean이 안 되었으면 원본 title에서 문단 번호 중복 제거 시도
        if not suffix and title and f"문단 {para}" not in title and cgt not in title:
            suffix = f" - {title}"
        return f"{para_tag}{suffix}"

    # title에 이미 문단 번호 포함 → title만 사용 (인용 시 강조 교체)
    if title and para and (f"문단 {para}" in title or f"문단{para}" in title):
        if is_cited:
            label = title.replace(f"문단 {para}", f":blue[**문단 {para}**]")
            return label.replace(f"문단{para}", f":blue[**문단 {para}**]")
        return title
    if para and title:
        return f"{para_tag} - {title}"
    if para:
        return para_tag
    if title:
        return title
    parts = [p.strip() for p in hierarchy.split(" > ") if p.strip()]
    return parts[-1] if parts else "문서"


# ── 본문/적용지침/결론도출근거 문서 카드 ───────────────────────────────────────


def _render_document_expander(
    doc: dict,
    doc_index: int = 0,
    is_key_doc: bool = False,
    cited_ids: set[str] | None = None,
) -> None:
    """개별 문서를 카드 expander로 렌더링합니다.

    구조: 라벨 → 본문 → 관련 조항 → 출처 경로
    """
    hierarchy = doc.get("hierarchy", "출처 없음")
    meta = doc.get("metadata") or {}
    source = doc.get("source", "") or meta.get("source", "")
    para_num = _get_doc_para_num(doc)

    full_text = doc.get("text") or doc.get("full_content") or doc.get("content", "")
    full_content = doc.get("full_content", "")

    label = _make_label(doc, cited_ids=cited_ids)

    with st.expander(_esc(label), expanded=False):
        # 문단 번호 배지 — topic_tabs.py의 _render_para_expander와 동일한 스타일
        if para_num:
            st.markdown(
                f'<span style="display:inline-block; background:#e0e7ff; color:#3730a3; '
                f"font-size:0.8em; font-weight:600; padding:2px 8px; border-radius:4px; "
                f'margin-bottom:0.5rem;">[문단 {html.escape(para_num)}]</span>',
                unsafe_allow_html=True,
            )
        # 본문 — 마크다운 테이블을 HTML로 먼저 변환 후 \n→<br>
        # Why: \n→<br> 변환이 테이블 행 구분자를 파괴하므로 미리 HTML로 변환
        display_text = full_content if full_content else full_text
        normalized = _normalize_doc_content(display_text, source)
        cleaned = clean_text(normalized)
        cleaned = md_tables_to_html(cleaned)
        # \n+ → 단일 <br>로 통합 (이중 줄띄움 방지)
        cleaned = re.sub(r"\n+", "<br>", cleaned)
        st.markdown(
            f'<div style="line-height:1.85; font-size:0.93em;">'
            f"{cleaned}</div>",
            unsafe_allow_html=True,
        )

        # 관련 조항 칩
        self_ids = _build_self_ids(para_num)
        _render_para_chips(normalized, label, doc_index, self_ids)

        # 출처 경로 푸터
        st.html(f'<div class="source-footer">📍 {html.escape(_esc(hierarchy))}</div>')


# ── QNA/감리사례 PDR 문서 카드 ─────────────────────────────────────────────────


def _render_pdr_expander(
    child_doc: dict,
    doc_index: int = 0,
    entry_desc: str = "",
    cited_ids: set[str] | None = None,
) -> None:
    """QNA/감리사례 — Parent 전문을 카드로 렌더링합니다.

    topic_tabs.py의 _render_qna_tab / _render_findings_tab과 동일한 구조:
      라벨: _build_pdr_label(parent_id, title, content)
      🏷️ 경로 태그 (_hierarchy_path)
      desc blockquote (entry_desc)
      content (_format_pdr_content + clean_text)
      🔗 관련 조항 칩
      📍 출처 경로 푸터
    """
    parent_id = child_doc.get("parent_id", "")
    chunk_id = child_doc.get("chunk_id", "")

    if not parent_id and chunk_id:
        parent_id = re.sub(r"_[QAS]$", "", chunk_id)

    # Parent 문서 조회 — 라벨 생성에 필요하므로 먼저 fetch
    parent = fetch_parent_doc(parent_id) if parent_id else None

    if parent:
        raw_title = _get_parent_field(parent, "title", parent_id)
        hierarchy = _get_parent_field(parent, "hierarchy", "")
        content = parent.get("content", "")
    else:
        raw_title = child_doc.get("title", parent_id)
        hierarchy = child_doc.get("hierarchy", "") or ""
        content = child_doc.get("text") or child_doc.get("content", "")

    # 라벨: [ID] 제목 — topic_tabs.py와 동일 로직
    label = _build_pdr_label(parent_id, raw_title, content) if parent_id else raw_title
    # AI 답변에서 인용된 ID이면 파란색 볼드로 강조
    is_cited = bool(cited_ids and parent_id and parent_id in cited_ids)
    if is_cited and parent_id:
        label = label.replace(f"[{parent_id}]", f":blue[**[{parent_id}]**]")

    with st.expander(f":material/description: {_esc(label)}", expanded=False):
        # 🏷️ 경로 태그 — hierarchy에서 마지막 세그먼트(제목) 제거
        hier_path = _hierarchy_path(hierarchy) if hierarchy else ""
        if hier_path:
            st.markdown(
                f'<div style="font-size:0.78em; color:#6b7280; background:#f1f5f9; '
                f"display:inline-block; padding:2px 10px; border-radius:12px; "
                f'margin-bottom:0.5rem;">🏷️ {html.escape(hier_path)}</div>',
                unsafe_allow_html=True,
            )

        # desc blockquote — topic_tabs.py의 _desc_blockquote와 동일 스타일
        if entry_desc:
            _d = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(entry_desc))
            _d = re.sub(r"(?<=[가-힣])\.\s+", ".<br>", _d)
            _d = _d.replace("\n", "<br>")
            st.markdown(
                f'<div style="line-height:1.75; color:#475569; font-size:0.88em; '
                f"padding:0.5rem 0.75rem; background:#f8fafc; "
                f'border-left:2px solid #cbd5e1; border-radius:2px;">'
                f"{_d}</div>"
                f'<hr style="border:none; border-top:1px solid #e2e8f0; margin:0.4rem 0 0.2rem;">',
                unsafe_allow_html=True,
            )

        # 본문 content
        if content:
            adjusted = _format_pdr_content(content)
            cleaned = clean_text(adjusted)
            cleaned = md_tables_to_html(cleaned)
            cleaned = re.sub(r"\n+", "<br>", cleaned)
            st.markdown(
                f'<div style="line-height:1.85; font-size:0.93em;">'
                f"{cleaned}</div>",
                unsafe_allow_html=True,
            )
            # 🔗 관련 조항 칩
            _render_para_chips(content, label, doc_index)
        else:
            st.info("내용을 불러올 수 없습니다.")

        # 📍 출처 경로 푸터
        st.html(
            f'<div class="source-footer">📍 출처 경로: '
            f"{html.escape(hierarchy)}</div>"
        )


# ── IE 적용사례 그룹핑 렌더링 ──────────────────────────────────────────────────


def _render_docs_with_ie_grouping(docs: list[dict], idx_offset: int = 0) -> None:
    """문서 목록을 렌더링합니다. IE 적용사례는 case_group_title로 서브 그룹화."""
    ie_groups: dict[str, list[tuple[int, dict]]] = {}
    non_ie_docs: list[tuple[int, dict]] = []

    for i, doc in enumerate(docs):
        if _is_ie_doc(doc):
            raw_cgt = doc.get("case_group_title", "")
            cgt = _normalize_case_group_title(raw_cgt) if raw_cgt else ""
            if cgt:
                ie_groups.setdefault(cgt, []).append((idx_offset + i, doc))
            else:
                non_ie_docs.append((idx_offset + i, doc))
        else:
            non_ie_docs.append((idx_offset + i, doc))

    for idx, doc in non_ie_docs:
        _render_document_expander(doc, doc_index=idx)

    parent_idx_base = idx_offset + len(docs)
    parent_idx_counter = 0
    rendered_parent_cases: set[str] = set()

    for case_group_title, group_items in ie_groups.items():
        # "사례 1A" 같은 서브 사례 → 부모 "사례 1"의 문서를 먼저 표시
        m_sub = re.match(r"^(사례\s+\d+)[A-Za-z]", case_group_title)
        if m_sub and case_group_title not in rendered_parent_cases:
            from app.ui.db import fetch_ie_case_docs

            parent_cgt = m_sub.group(1)  # "사례 1A" → "사례 1"
            if parent_cgt and parent_cgt not in rendered_parent_cases:
                parent_docs = sorted(
                    fetch_ie_case_docs((parent_cgt,)), key=_ie_para_sort_key
                )
                if parent_docs:
                    st.caption(f"📋 기본 사례: {_esc(parent_cgt)}")
                    for pd in parent_docs:
                        _render_document_expander(
                            pd, doc_index=parent_idx_base + parent_idx_counter
                        )
                        parent_idx_counter += 1
                    rendered_parent_cases.add(parent_cgt)

        st.caption(f"📎 {_esc(case_group_title)}")
        for idx, doc in group_items:
            _render_document_expander(doc, doc_index=idx)

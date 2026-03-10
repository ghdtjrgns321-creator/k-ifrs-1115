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
    _build_self_ids,
    _format_pdr_content,
    _get_doc_para_num,
    _ie_para_sort_key,
    _is_ie_doc,
    _normalize_case_group_title,
)
from app.ui.text import (
    _esc,
    _extract_para_refs,
    _normalize_doc_content,
    clean_text,
)


# ── 관련 조항 칩 ──────────────────────────────────────────────────────────────


def _render_para_chips(
    text: str, context_key: str, doc_index: int = 0,
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


def _make_label(doc: dict) -> str:
    """깔끔한 expander 라벨을 생성합니다.

    결과: "문단 56 - 변동대가의 유의적 환원 가능성"
    title에 이미 문단 번호가 포함되면 중복 안 붙임.
    """
    title = doc.get("title", "")
    para = _get_doc_para_num(doc)
    hierarchy = doc.get("hierarchy", "")

    # title에 이미 문단 번호 포함 → title만 사용
    if title and para and (f"문단 {para}" in title or f"문단{para}" in title):
        return title
    if para and title:
        return f"문단 {para} - {title}"
    if para:
        return f"문단 {para}"
    if title:
        return title
    parts = [p.strip() for p in hierarchy.split(" > ") if p.strip()]
    return parts[-1] if parts else "문서"


# ── 본문/적용지침/결론도출근거 문서 카드 ───────────────────────────────────────


def _render_document_expander(
    doc: dict, doc_index: int = 0, is_key_doc: bool = False
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

    label = _make_label(doc)

    with st.expander(_esc(label), expanded=False):
        # 본문 — 줄바꿈을 <br>로 변환하여 문단 구분 유지
        display_text = full_content if full_content else full_text
        normalized = _normalize_doc_content(display_text, source)
        cleaned = clean_text(normalized)
        st.markdown(
            f'<div style="line-height:1.85; font-size:0.93em;">'
            f'{cleaned.replace(chr(10), "<br>")}</div>',
            unsafe_allow_html=True,
        )

        # 관련 조항 칩
        self_ids = _build_self_ids(para_num)
        _render_para_chips(normalized, label, doc_index, self_ids)

        # 출처 경로 푸터
        st.html(
            f'<div class="source-footer">'
            f'📍 {html.escape(_esc(hierarchy))}</div>'
        )


# ── QNA/감리사례 PDR 문서 카드 ─────────────────────────────────────────────────


def _render_pdr_expander(
    child_doc: dict, doc_index: int = 0, entry_desc: str = "",
) -> None:
    """QNA/감리사례 — Parent 전문을 카드로 렌더링합니다."""
    parent_id = child_doc.get("parent_id", "")
    hierarchy = child_doc.get("hierarchy", "") or ""
    title = child_doc.get("title", "")
    chunk_id = child_doc.get("chunk_id", "")

    if not parent_id and chunk_id:
        parent_id = re.sub(r"_[QAS]$", "", chunk_id)

    label = title if title else (hierarchy or chunk_id or "출처 없음")

    with st.expander(_esc(label), expanded=False):
        # 요약 설명 (topic curation desc)
        if entry_desc:
            _desc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", entry_desc)
            _desc = re.sub(r"\. (?=[가-힣A-Z\[*])", ".<br>", _desc)
            st.markdown(
                f'<div style="line-height:1.75; color:#475569; font-size:0.85em; '
                f'padding:0.5rem 0.75rem; margin-bottom:0.5rem; '
                f'border-left:3px solid #94A3B8; border-radius:4px; '
                f'background:#F8FAFC;">{_desc}</div>',
                unsafe_allow_html=True,
            )

        # Parent 전문
        parent = fetch_parent_doc(parent_id) if parent_id else None
        raw_content = ""

        if parent:
            content = parent.get("content", "")
            if content:
                raw_content = content
                adjusted = _format_pdr_content(content)
                cleaned = clean_text(adjusted)
                st.markdown(
                    f'<div style="line-height:1.85; font-size:0.93em;">'
                    f'{cleaned.replace(chr(10), "<br>")}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.info("내용을 불러올 수 없습니다.")
        else:
            fallback = child_doc.get("text") or child_doc.get("content", "")
            if fallback:
                raw_content = fallback
                normalized = _normalize_doc_content(fallback, child_doc.get("source", ""))
                cleaned = clean_text(normalized)
                st.markdown(
                    f'<div style="line-height:1.85; font-size:0.93em;">'
                    f'{cleaned.replace(chr(10), "<br>")}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.info("내용을 불러올 수 없습니다.")

        if raw_content:
            _render_para_chips(raw_content, label, doc_index)

        # 출처 경로 — 유일한 1개
        st.html(
            f'<div class="source-footer">'
            f'📍 {html.escape(_esc(hierarchy))}</div>'
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

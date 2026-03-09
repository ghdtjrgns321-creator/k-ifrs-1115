# app/ui/doc_renderers.py
# 개별 문서 Streamlit 렌더링 — Expander 카드, 문단 칩, PDR 전문 표시.
#
# components.py에서 분리. st.expander, st.pills 등 Streamlit 위젯 사용.

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


def _render_para_chips(
    text: str, context_key: str, doc_index: int = 0, self_ids: set[str] | None = None
) -> None:
    """본문에서 탐지된 문단 참조를 inline 필 태그로 렌더링합니다.

    클릭 시 show_modal=True + modal_history 설정으로 모달을 트리거합니다.
    """
    self_ids = self_ids or set()
    all_refs = _extract_para_refs(text)
    refs = [r for r in all_refs if r not in self_ids]
    if not refs:
        return

    # DB 검증: 실제 존재하는 문단만 표시
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
        # ~ → ～(전각 물결표): Streamlit markdown 취소선 방지
        options=[r.replace("~", "～") for r in refs],
        label_visibility="collapsed",
        key=safe_key,
        on_change=outer_pill_callback,
    )


def _render_document_expander(
    doc: dict, doc_index: int = 0, is_key_doc: bool = False
) -> None:
    """개별 문서를 카드 레이아웃의 Expander로 렌더링합니다."""
    hierarchy = doc.get("hierarchy", "출처 없음")
    title = doc.get("title", "")
    meta = doc.get("metadata") or {}
    source = doc.get("source", "") or meta.get("source", "")

    full_text = doc.get("text") or doc.get("full_content") or doc.get("content", "")
    expander_label = title if title else hierarchy

    with st.expander(f"📄 {_esc(expander_label)}", expanded=False):
        normalized = _normalize_doc_content(full_text, source)
        cleaned = clean_text(normalized)
        st.markdown(cleaned, unsafe_allow_html=True)

        self_ids = _build_self_ids(_get_doc_para_num(doc))
        _render_para_chips(normalized, expander_label, doc_index, self_ids)

        st.divider()
        st.html(
            f'<div class="source-footer">📍 출처 경로: {html.escape(_esc(hierarchy))}</div>'
        )


def _render_pdr_expander(
    child_doc: dict, doc_index: int = 0, entry_desc: str = "",
) -> None:
    """QNA/감리사례 Child 문서를 Parent 전문(full content)으로 렌더링합니다.

    PDR(Parent-Document Retrieval) 아키텍처:
      - 벡터 검색 대상: Child 청크 → 검색 정밀도 향상
      - 화면 표시 대상: Parent 전문 → 완전한 맥락 제공
    """
    parent_id = child_doc.get("parent_id", "")
    hierarchy = child_doc.get("hierarchy", "") or ""
    title = child_doc.get("title", "")
    chunk_id = child_doc.get("chunk_id", "")

    if not parent_id and chunk_id:
        parent_id = re.sub(r"_[QAS]$", "", chunk_id)

    expander_label = title if title else (hierarchy or chunk_id or "출처 없음")

    _hier_parts = [p.strip() for p in hierarchy.split(">") if p.strip()]
    _hier_path = " > ".join(_hier_parts[:-1]) if len(_hier_parts) > 1 else hierarchy

    with st.expander(f"📄 {_esc(expander_label)}", expanded=False):
        if _hier_path:
            st.markdown(
                f'<div style="font-size: 0.78em; color: #6b7280; background: #f1f5f9; '
                f'display: inline-block; padding: 2px 10px; border-radius: 12px; '
                f'margin-bottom: 0.5rem;">🏷️ {html.escape(_hier_path)}</div>',
                unsafe_allow_html=True,
            )

        if entry_desc:
            _desc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", entry_desc)
            _desc = re.sub(r"\. (?=[가-힣A-Z\[*])", ".<br>", _desc)
            st.markdown(
                f'<div style="line-height: 1.75; color: #475569; font-size: 0.85em; '
                f'padding: 0.5rem 0.75rem; margin-bottom: 0.5rem; '
                f'background: #f8fafc; border-left: 3px solid #60a5fa; '
                f'border-radius: 4px;">{_desc}</div>',
                unsafe_allow_html=True,
            )

        parent = fetch_parent_doc(parent_id) if parent_id else None
        raw_content = ""

        if parent:
            content = parent.get("content", "")
            if content:
                raw_content = content
                adjusted = _format_pdr_content(content)
                cleaned = clean_text(adjusted)
                st.markdown(cleaned, unsafe_allow_html=True)
            else:
                st.info("내용을 불러올 수 없습니다.")
        else:
            fallback = child_doc.get("text") or child_doc.get("content", "")
            if fallback:
                raw_content = fallback
                normalized = _normalize_doc_content(fallback, child_doc.get("source", ""))
                st.markdown(clean_text(normalized), unsafe_allow_html=True)
            else:
                st.info("내용을 불러올 수 없습니다.")

        if raw_content:
            _render_para_chips(raw_content, expander_label, doc_index)

        st.divider()
        st.html(
            f'<div class="source-footer">📍 출처 경로: {html.escape(_esc(hierarchy))}</div>'
        )

    if _hier_path:
        st.html(
            f'<div style="font-size:0.8rem; color:#9ca3af; '
            f'margin:-0.75rem 0 -0.25rem 0.25rem; line-height:1.4;">'
            f'└ {html.escape(_hier_path)}</div>'
        )


def _render_docs_with_ie_grouping(docs: list[dict], idx_offset: int = 0) -> None:
    """문서 목록을 렌더링합니다. IE 적용사례는 case_group_title로 서브 그룹화합니다."""
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
        # 파생 사례 감지 → 부모 사례를 먼저 표시
        m_sub = re.match(r"^사례\s+\d+[A-Za-z]", case_group_title)
        if m_sub and case_group_title not in rendered_parent_cases:
            from app.ui.db import fetch_ie_case_docs, find_sub_case_parent_titles
            parent_map = find_sub_case_parent_titles((case_group_title,))
            parent_cgt = parent_map.get(case_group_title)
            if parent_cgt and parent_cgt not in rendered_parent_cases:
                parent_docs = sorted(
                    fetch_ie_case_docs((parent_cgt,)), key=_ie_para_sort_key
                )
                if parent_docs:
                    st.markdown(
                        f'<div style="margin-top:0.75rem; padding:0.3rem 0.6rem; '
                        f'background:#f5f5f5; border-left:3px solid #999; '
                        f'border-radius:4px; font-size:0.85em; color:#555; font-weight:600;">'
                        f'📋 [기본 사례] {_esc(parent_cgt)}</div>',
                        unsafe_allow_html=True,
                    )
                    for pd in parent_docs:
                        _render_document_expander(
                            pd, doc_index=parent_idx_base + parent_idx_counter
                        )
                        parent_idx_counter += 1
                    rendered_parent_cases.add(parent_cgt)

        st.markdown(
            f'<div style="margin-top:0.75rem; padding: 0.3rem 0.6rem; '
            f'background:#f0f4ff; border-left:3px solid #4c7ef3; '
            f'border-radius:4px; font-size:0.85em; color:#2d4a8a; font-weight:600;">'
            f'📎 {_esc(case_group_title)}</div>',
            unsafe_allow_html=True,
        )
        for idx, doc in group_items:
            _render_document_expander(doc, doc_index=idx)

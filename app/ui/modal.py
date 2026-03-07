# app/ui/modal.py
# 문단 참조 퀵뷰 모달 다이얼로그.
#
# _render_single_para_in_modal: 모달 내 단일 문단 렌더링 + 인라인 참조 칩
# _show_reference_modal:        히스토리 기반 탐색 모달 (중첩 없이 breadcrumb으로)

import html

import streamlit as st

from app.ui.components import _build_self_ids, _get_doc_para_num, _render_para_chips
from app.ui.db import _expand_para_range, _fetch_para_from_db
from app.ui.text import _PARA_REF_RE, _normalize_doc_content, _para_ref_to_num, clean_text


def _render_single_para_in_modal(
    para_num: str, idx: int, total: int, in_history: set[str]
) -> list[str]:
    """모달 내에서 단일 문단을 렌더링하고, 본문 바로 아래에 참조 조항 칩을 표시합니다.

    in_history: 이미 히스토리에 있는 조항 (칩에서 제외할 목록)
    반환값: 이 문단에서 탐지된 참조 목록 (집계용)
    """
    with st.spinner(f"문단 {para_num} 원문 조회 중..."):
        try:
            doc = _fetch_para_from_db(para_num)
        except Exception as exc:
            st.error(f"[오류] 문단 {para_num} DB 조회 실패: {exc}")
            import traceback
            st.code(traceback.format_exc(), language="python")
            return []

    if not doc:
        st.warning(f"**문단 {para_num}**에 해당하는 문서를 DB에서 찾을 수 없습니다.")
        return []

    title = doc.get("title", "")
    hierarchy = doc.get("hierarchy", "")
    source = doc.get("source") or doc.get("category", "")
    raw_text = doc.get("text") or doc.get("full_content") or doc.get("content", "")

    # 범위 참조인 경우 각 문단 앞에 핀 마커 헤딩 표시
    if total > 1:
        st.markdown(f"#### 📌 문단 {para_num}")

    if title:
        st.markdown(f"{'###' if total == 1 else '####'} {title}")
    if hierarchy:
        st.html(f'<div class="source-footer">📍 {html.escape(hierarchy)}</div>')
    st.markdown("")

    cleaned = clean_text(_normalize_doc_content(raw_text, source))
    st.markdown(cleaned, unsafe_allow_html=True)

    # ── 이 문단의 참조 조항을 본문 바로 아래에 즉시 표시 ───────────────────────
    # raw_text 기반으로 탐지 (HTML 간섭 없음)
    normalized_raw = _normalize_doc_content(raw_text, source)
    current_doc_refs = list(dict.fromkeys(_PARA_REF_RE.findall(normalized_raw)))
    own_num = _get_doc_para_num(doc)
    exclude = in_history | _build_self_ids(own_num)
    para_refs = [r for r in current_doc_refs if r not in exclude][:8]

    if para_refs:
        st.caption("🔗 이 문단이 참조하는 조항 (클릭 시 이어서 보기):")
        pill_key = f"modal_inline_pills_{para_num}_{idx}"

        def _inline_callback(key=pill_key):
            val = st.session_state.get(key)
            if val:
                st.session_state.modal_history.append(val)
                st.session_state[key] = None

        st.pills(
            label="인라인 참조 조항",
            options=para_refs,
            label_visibility="collapsed",
            key=pill_key,
            on_change=_inline_callback,
        )
    else:
        st.caption("✅ 이 문단은 다른 조항을 직접 참조하지 않습니다.")

    return [r for r in dict.fromkeys(_PARA_REF_RE.findall(cleaned))]


@st.dialog("📖 조항 원문 보기", width="large")
def _show_reference_modal() -> None:
    """문단 참조 버튼 클릭 시 호출되는 모달 다이얼로그입니다.

    modal_history 리스트로 히스토리를 관리하여 중첩 모달 없이 조항을 탐색합니다.
    범위 참조(56~59)는 숫자를 확장하여 각 문단을 순차 렌더링합니다.
    참조 조항 칩은 각 문단 본문 바로 아래에 개별로 표시됩니다.
    """
    if "modal_history" not in st.session_state or not st.session_state.modal_history:
        st.warning("잘못된 접근입니다.")
        return

    history = st.session_state.modal_history
    current_ref = history[-1]
    in_history: set[str] = set(history)

    # ── 범위 참조 확장: '문단 56~59' → ['56','57','58','59'] ────────────────────
    raw_num = _para_ref_to_num(current_ref)
    para_nums = _expand_para_range(raw_num)

    # ── 네비게이션 헤더 ─────────────────────────────────────────────────────────
    def nav_back_callback():
        st.session_state.modal_history.pop()

    if len(history) > 1:
        nav_col, title_col = st.columns([1, 5])
        with nav_col:
            st.button(
                "⬅ 이전", key=f"modal_back_{len(history)}", on_click=nav_back_callback
            )
        with title_col:
            breadcrumb = " › ".join(history)
            st.caption(f"탐색 경로: {breadcrumb}")
    else:
        st.caption(f"참조 조항: **{current_ref}**")

    st.divider()

    # ── 각 문단 순차 렌더링 (참조 칩은 각 문단 바로 아래에 표시) ──────────────
    total = len(para_nums)
    for idx, para_num in enumerate(para_nums):
        _render_single_para_in_modal(para_num, idx, total, in_history)
        if idx < total - 1:
            st.divider()

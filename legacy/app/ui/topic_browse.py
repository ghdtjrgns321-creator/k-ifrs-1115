# app/ui/topic_browse.py
# 토픽 브라우즈 — 큐레이션된 4탭 뷰 (본문·BC | 적용사례 | 질의회신 | 감리사례)
#
# 홈 화면에서 토픽 버튼 클릭 시 이 페이지로 전환됩니다.
# 실제 탭 렌더링은 topic_tabs.py에 위임합니다.

import html as _html
import re

import streamlit as st

from app.domain.topic_content_map import TOPIC_CONTENT_MAP
from app.ui.client import _call_search
from app.ui.session import _go_home
from app.ui.topic_tabs import (
    _render_findings_tab,
    _render_ie_tab,
    _render_main_bc_tab,
    _render_qna_tab,
)

def _resolve_topic_key(button_name: str, topic_map: dict) -> str | None:
    """버튼 표시명을 TOPIC_CONTENT_MAP 키로 변환합니다.

    괄호 내 설명을 제거하여 JSON 키와 매칭합니다.
    """
    stripped = re.sub(r"\([^)]+\)$", "", button_name).strip()
    # 1) 정확 매칭
    if button_name in topic_map:
        return button_name
    # 2) 괄호 제거 후 매칭
    if stripped in topic_map:
        return stripped
    return None


def _format_desc_html(desc: str) -> str:
    """토픽 설명 텍스트를 안전한 HTML로 변환합니다."""
    if not desc:
        return ""
    escaped = _html.escape(desc)
    return escaped.replace("\n", "<br>")


def _render_topic_browse() -> None:
    """[토픽 브라우즈] 선택된 토픽의 큐레이션된 문서를 4탭으로 표시합니다."""
    topic = st.session_state.get("selected_topic", "")

    # ── 구분선 — 헤더 바로 아래 ─────────────────────────────────────────────
    st.markdown(
        "<hr style='margin-top:-2.5rem; margin-bottom:0; "
        "border:none; border-top:1px solid #E2E8F0;'>",
        unsafe_allow_html=True,
    )

    # ── 헤더: 토픽명 + 새 검색 버튼 ─────────────────────────────────────────
    title_col, btn_col = st.columns([8, 2], vertical_alignment="bottom")
    with title_col:
        st.markdown(
            f"<h3 style='margin:0.2rem 0 0.6rem; padding:0;'>📖 {topic}</h3>",
            unsafe_allow_html=True,
        )
    with btn_col:
        st.button(
            "새 검색",
            icon=":material/arrow_back:",
            use_container_width=True,
            on_click=_go_home,
        )

    # ── 토픽 데이터 로드 ────────────────────────────────────────────────────
    # 버튼 표시명 → JSON 키 정규화 (괄호 설명 제거, 별칭 매핑)
    resolved_key = _resolve_topic_key(topic, TOPIC_CONTENT_MAP)
    topic_data = TOPIC_CONTENT_MAP.get(resolved_key) if resolved_key else None
    if not topic_data:
        st.info(f"'{topic}'에 대한 큐레이션 데이터가 아직 준비되지 않았습니다.")
        st.caption("검색으로 전환하여 관련 문서를 찾아보세요.")
        return

    # ── 관련 토픽 칩 ────────────────────────────────────────────────────────
    cross_links = topic_data.get("cross_links", [])
    if cross_links:
        st.caption("🔗 관련 토픽")

        def _on_xlink_change():
            """pills 위젯의 on_change 콜백 — 위젯 인스턴스 전에 실행되므로 키 수정 가능."""
            picked = st.session_state.get("xlink_pills")
            if picked:
                st.session_state.selected_topic = picked
                st.session_state["xlink_pills"] = None

        st.pills(
            "관련 토픽",
            options=cross_links,
            label_visibility="collapsed",
            key="xlink_pills",
            on_change=_on_xlink_change,
        )

    st.markdown(
        "<hr style='border:none; border-top:1px solid #E2E8F0; margin:0.3rem 0 0.2rem;'>",
        unsafe_allow_html=True,
    )

    # ── 4탭 렌더링 ─────────────────────────────────────────────────────────
    tab_labels = ["📘 본문·BC", "📋 적용사례", "💬 질의회신", "🚨 감리지적사례"]
    tabs = st.tabs(tab_labels)

    # 토픽명: 빈 탭에서 토픽별 안내 메시지 생성에 사용
    _tname = resolved_key or topic

    with tabs[0]:
        with st.container(gap="xsmall"):
            _render_main_bc_tab(topic_data.get("main_and_bc", {}), _tname)
    with tabs[1]:
        with st.container(gap="xsmall"):
            _render_ie_tab(topic_data.get("ie", {}), _tname)
    with tabs[2]:
        with st.container(gap="xsmall"):
            _render_qna_tab(topic_data.get("qna", {}), _tname)
    with tabs[3]:
        with st.container(gap="xsmall"):
            _render_findings_tab(topic_data.get("findings", {}), _tname)

    # ── 하단: 자유 질문 입력 (토픽 맥락) ─────────────────────────────────────
    st.divider()
    st.markdown("#### :material/chat: 이 주제에 대해 더 궁금한 점이 있으신가요?")
    st.caption(
        f"'{topic}'에 관한 기준서 해석이나 비슷한 실무 상황이 있다면 자유롭게 질문해 주세요. "
        "AI가 관련 조항을 근거로 답변을 드립니다."
    )

    @st.fragment
    def _topic_search_fragment():
        query = st.text_area(
            "상황 입력",
            placeholder=f"'{topic}'과 관련된 구체적인 거래 상황이나 궁금한 점을 입력해 주세요...\n"
            f"(예: 이 경우에 수익을 어떤 시점에 인식해야 하나요?)",
            label_visibility="collapsed",
            height=100,
            key="topic_search_input",
        )
        if st.button(
            "검색하기",
            use_container_width=True,
            type="primary",
            key="topic_search_btn",
        ):
            if query and query.strip():
                _call_search(query.strip())

    _topic_search_fragment()

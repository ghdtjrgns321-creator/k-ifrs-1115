# app/ui/topic_browse.py
# 토픽 브라우즈 — 큐레이션된 4탭 뷰 (본문·BC | 적용사례 | 질의회신 | 감리사례)
#
# 홈 화면에서 토픽 버튼 클릭 시 이 페이지로 전환됩니다.
# pinpoint_panel.py에서도 _format_desc_html을 사용합니다.

import html as _html

import streamlit as st

from app.ui.session import _go_home


def _format_desc_html(desc: str) -> str:
    """토픽 설명 텍스트를 안전한 HTML로 변환합니다.

    줄바꿈을 <br>로 변환하고, XSS 방지를 위해 HTML 이스케이프합니다.
    """
    if not desc:
        return ""
    escaped = _html.escape(desc)
    return escaped.replace("\n", "<br>")


def _render_topic_browse() -> None:
    """[토픽 브라우즈] 선택된 토픽의 큐레이션된 문서를 4탭으로 보여줍니다.

    TODO: 스크린샷 기반으로 상세 구현 예정 (현재 플레이스홀더)
    """
    topic = st.session_state.get("selected_topic", "")

    # 헤더: 토픽명 + 홈 버튼
    title_col, btn_col = st.columns([8, 2], vertical_alignment="bottom")
    with title_col:
        st.markdown(f"### :material/menu_book: {topic}")
    with btn_col:
        if st.button("홈으로", icon=":material/arrow_back:", use_container_width=True):
            _go_home()

    st.divider()

    # 토픽 데이터 로드
    from app.domain.topic_content_map import TOPIC_CONTENT_MAP

    topic_data = TOPIC_CONTENT_MAP.get(topic)
    if not topic_data:
        st.info(f"'{topic}'에 대한 큐레이션 데이터가 아직 준비되지 않았습니다.")
        st.caption("검색으로 전환하여 관련 문서를 찾아보세요.")
        return

    st.info("토픽 브라우즈 페이지는 곧 완성됩니다. 현재 토픽 데이터가 로드되었습니다.")
    st.json(topic_data, expanded=False)

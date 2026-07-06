# app/ui/cross_links.py
# 크로스링크(관련 토픽) — st.pills() + CSS로 라벨과 pill을 한 줄에 배치.

import streamlit as st
import streamlit.components.v1 as components

from app.domain.topic_content_map import TOPIC_CONTENT_MAP
from app.ui.constants import CROSS_LINK_NORMALIZE

# stPills 내부 label + pills를 가로 flex row로 전환
_PILL_CSS = """
<style>
/* stPills를 가로 flex: label이 왼쪽, pills가 오른쪽 */
div.st-key-xlink_wrap [data-testid="stPills"] {
    display: flex !important;
    flex-direction: row !important;
    align-items: center !important;
    gap: 0.5rem !important;
    flex-wrap: wrap !important;
    margin: 0 0 0.25rem !important;
    padding: 0 !important;
}
/* label 크기·색상 */
div.st-key-xlink_wrap [data-testid="stPills"] .stWidgetLabel,
div.st-key-xlink_wrap [data-testid="stPills"] > label,
div.st-key-xlink_wrap [data-testid="stPills"] label {
    flex-shrink: 0 !important;
    width: auto !important;
    font-size: 0.8em !important;
    color: #64748b !important;
    white-space: nowrap !important;
    margin: 0 !important;
    padding: 0 !important;
    font-weight: 400 !important;
}
/* pill 버튼 크기 */
div.st-key-xlink_wrap [data-testid="stPillsTag"] {
    font-size: 0.78rem !important;
    padding: 0.1rem 0.65rem !important;
    line-height: 1.5 !important;
}
</style>
"""


def _resolve_cross_link(raw: str) -> tuple[str | None, str]:
    """cross_link 값을 (topic_key | None, 표시명)으로 변환합니다."""
    if raw in CROSS_LINK_NORMALIZE:
        resolved = CROSS_LINK_NORMALIZE[raw]
        return (resolved, raw) if resolved else (None, raw)
    if raw in TOPIC_CONTENT_MAP:
        return (raw, raw)
    return (None, raw)


def render_cross_links(cross_links: list[str], current_topic: str) -> None:
    """관련 토픽을 st.pills()로 라벨 옆에 가로 렌더링합니다."""
    items: list[tuple[str | None, str]] = []
    for raw in cross_links:
        topic_key, display = _resolve_cross_link(raw)
        if topic_key == current_topic:
            continue
        items.append((topic_key, display))

    if not items:
        return

    st.markdown(_PILL_CSS, unsafe_allow_html=True)

    if st.session_state.pop("_xlink_scroll_top", False):
        components.html(
            "<script>window.parent.document.querySelector("
            '"[data-testid=\\"stAppViewContainer\\"]"'
            ").scrollTo(0,0);</script>",
            height=0,
        )

    display_to_key: dict[str, str | None] = {d: k for k, d in items}
    options = [d for _, d in items]

    with st.container(key="xlink_wrap"):
        selected = st.pills(
            "🔗 관련 토픽",
            options=options,
            selection_mode="single",
            default=None,
            label_visibility="visible",
            key="xlink_pills",
        )

    if selected:
        topic_key = display_to_key.get(selected)
        if topic_key:
            st.session_state["current_topic"] = topic_key
            st.session_state["page"] = "topic_browse"
            st.session_state["_xlink_scroll_top"] = True
            st.rerun()

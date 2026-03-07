# app/streamlit_app.py
# K-IFRS 1115 검색/분석 AI — 진입점
#
# UX 철학:
#   기존 챗봇은 AI가 먼저 답변 → 근거를 나중에 보여주는 방식이었습니다.
#   새 UX는 "근거 문서 직접 열람 → AI 인사이트 요청" 순서로 역전시킵니다.
#   사용자가 근거를 먼저 확인 후 AI를 보조 도구로 사용하는 전문가 도구입니다.
#
# 페이지 흐름:
#   [home]     키워드 칩 + 자유 검색창
#       ↓ 검색
#   [evidence] 카테고리별 아코디언(원문) + AI 질문 입력창
#       ↓ AI 질문 제출
#   [ai_answer] 조건부 답변 + 꼬리 질문 버튼 3개 + 추가 입력창
#       ↓ 꼬리 질문 클릭 또는 새 질문
#   [ai_answer] (반복)
#
# 세부 구현은 app/ui/ 패키지로 분리되어 있습니다.

import sys
from pathlib import Path

# Add project root to sys.path to allow running directly from `app/` or root
root_path = Path(__file__).parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

import streamlit as st

from app.ui.layout import _inject_css, _render_header, _render_sidebar
from app.ui.modal import _show_reference_modal
from app.ui.pages import _render_ai_answer, _render_evidence, _render_home
from app.ui.session import _init_session


def main() -> None:
    st.set_page_config(
        page_title="K-IFRS 1115 분석 도구",
        layout="wide",  # ai_answer Split View를 위해 wide 레이아웃 사용
        initial_sidebar_state="expanded",
    )

    _inject_css()
    _init_session()
    _render_sidebar()
    _render_header()

    # page_state에 따라 화면을 분기합니다.
    page = st.session_state.page_state

    if page == "home":
        _render_home()
    elif page == "evidence":
        _render_evidence()
    elif page == "ai_answer":
        _render_ai_answer()

    # ── 모달 전역 트리거 ─────────────────────────────────────────────────────
    # show_modal 플래그는 _render_para_chips에서 설정됩니다.
    # 위젯 렌더링이 모두 끝난 뒤에 모달을 호출해야 Streamlit 에러가 나지 않습니다.
    if st.session_state.get("show_modal"):
        st.session_state.show_modal = False
        _show_reference_modal()


if __name__ == "__main__":
    main()

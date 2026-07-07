# app/streamlit_app.py
# K-IFRS 1115 검색/분석 AI — 진입점
#
# UX 철학:
#   기존 챗봇은 AI가 먼저 답변 → 근거를 나중에 보여주는 방식이었습니다.
#   새 UX는 "근거 문서 직접 열람 → AI 인사이트 요청" 순서로 역전시킵니다.
#   사용자가 근거를 먼저 확인 후 AI를 보조 도구로 사용하는 전문가 도구입니다.
#
# 페이지 흐름 (챗봇 전용):
#   [home]     제목 + 자유 입력창 + 예시 질문 칩 (미니멀)
#       ↓ 질문 제출
#   [ai_answer] Split View — 좌(근거 문서) + 우(AI 답변 + 꼬리질문)
#       ↓ 꼬리 질문 클릭 또는 새 질문
#   [ai_answer] (반복)
# ([evidence]는 /search 경로용으로 남겨둠 — 현재 홈은 /chat 직행)
#
# 세부 구현은 app/ui/ 패키지로 분리되어 있습니다.

import sys
from pathlib import Path

# Add project root to sys.path to allow running directly from `app/` or root
root_path = Path(__file__).parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

import streamlit as st  # noqa: E402

from app.ui.layout import _inject_css, _render_disclaimer, _render_header  # noqa: E402
from app.ui.modal import _show_reference_modal  # noqa: E402
from app.ui.pages import _render_ai_answer, _render_evidence, _render_home  # noqa: E402
from app.ui.session import _init_session  # noqa: E402


def main() -> None:
    st.set_page_config(
        page_title="K-IFRS 1115 분석 도구",
        layout="wide",  # ai_answer Split View를 위해 wide 레이아웃 사용
        initial_sidebar_state="expanded",
    )

    _inject_css()
    _init_session()
    _render_header()

    # page_state에 따라 화면을 분기합니다.
    page = st.session_state.page_state

    if page == "home":
        _render_home()
    elif page == "evidence":
        _render_evidence()
    elif page == "ai_answer":
        _render_ai_answer()

    # 사이드바 제거로 옮긴 '참고 목적' 면책 문구를 하단에 고정 렌더
    _render_disclaimer()

    # ── 모달 전역 트리거 ─────────────────────────────────────────────────────
    # show_modal 플래그는 _render_para_chips에서 설정됩니다.
    # 위젯 렌더링이 모두 끝난 뒤에 모달을 호출해야 Streamlit 에러가 나지 않습니다.
    if st.session_state.get("show_modal"):
        st.session_state.show_modal = False
        _show_reference_modal()


if __name__ == "__main__":
    main()

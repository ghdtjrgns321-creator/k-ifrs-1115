# app/ui/session.py
# 세션 상태 초기화 및 홈 복귀 함수.
#
# _go_home()이 _init_session()을 호출하므로 두 함수는 반드시 같은 파일에 있어야 합니다.
# 순환 임포트를 막기 위해 이 파일은 다른 ui 모듈을 임포트하지 않습니다.

import streamlit as st


def _init_session() -> None:
    """세션 상태 초기값을 설정합니다. 앱 최초 실행 시에만 실행됩니다."""
    defaults = {
        # 페이지 상태 머신: "home" | "topic_browse" | "evidence" | "ai_answer"
        "page_state": "home",
        # 홈에서 선택한 토픽 키 (topic_browse에서 사용)
        "selected_topic": None,
        # 현재 검색어 (홈 화면에서 입력한 값)
        "search_query": "",
        # /search 응답의 캐시 키 (이후 /chat에 전달하여 retrieve 스킵)
        "search_id": None,
        # LLM이 정규화한 검색어 (evidence 화면 상단에 표시)
        "standalone_query": "",
        # /search가 반환한 DocResult 목록
        "evidence_docs": [],
        # AI에 보낸 질문 (ai_answer 화면 상단에 표시)
        "ai_question": "",
        # 멀티턴 질문 이력 — 1턴 질문이 사라지지 않도록 누적
        "ai_questions_history": [],
        # AI 답변 텍스트
        "ai_answer": "",
        # 인용 출처 메타데이터
        "cited_sources": [],
        # 감리사례 dict
        "findings_case": None,
        # 꼬리 질문 버튼 3개
        "follow_up_questions": [],
        # FastAPI 세션 ID (멀티턴 유지)
        "session_id": None,
        # 꼬리 질문 버튼 클릭 시 자동으로 보낼 질문
        "pending_followup": None,
        # True면 꼬리질문 칩이 선택지(답변 유도) 모드, False면 개념 확인 모드
        "is_situation": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _go_home() -> None:
    """세션 상태를 초기화하고 홈 화면으로 돌아갑니다.

    on_click 콜백으로 사용하면 st.rerun()이 필요 없음 —
    Streamlit이 콜백 실행 후 자동 1회 rerun합니다.
    session_id(멀티턴)는 유지하여 대화 맥락이 이어집니다.
    """
    reset_keys = [
        "page_state",
        "selected_topic",
        "search_query",
        "search_id",
        "standalone_query",
        "evidence_docs",
        "ai_question",
        "ai_questions_history",
        "ai_answer",
        "cited_sources",
        "findings_case",
        "follow_up_questions",
        "pending_followup",
        "is_situation",
        # 캐시 키 — 이전 질문의 데이터가 새 질문에 잔류하는 것 방지
        "_supp_by_group",
        "_cited_docs_cache_key",
        "_cited_docs_cache",
        "_cited_pdr_cache_key",
        "_cited_pdr_cache",
        "_cited_ie_cache_key",
        "_cited_ie_cache",
    ]
    for key in reset_keys:
        if key in st.session_state:
            del st.session_state[key]
    # 삭제된 키를 기본값으로 복원합니다.
    _init_session()

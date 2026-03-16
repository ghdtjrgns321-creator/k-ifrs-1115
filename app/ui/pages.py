# app/ui/pages.py
# 페이지 렌더러 함수 3개.
#
# - _render_home:       홈 — 키워드 칩 + 자유 검색창
# - _render_evidence:   근거 열람 — 카테고리별 아코디언 + AI 질문 입력창
# - _render_ai_answer:  AI 답변 — Split View (근거 + 답변 + 꼬리 질문)

import html
import re

import streamlit as st

import httpx

from app.ui.client import _call_chat
from app.ui.components import _render_evidence_panel
from app.ui.constants import FEEDBACK_URL, HOME_TOPICS_LEFT, HOME_TOPICS_RIGHT
from app.ui.doc_helpers import _format_pdr_content
from app.ui.session import _go_home
from app.ui.text import _esc, clean_text


def _format_question(text: str) -> str:
    """사용자 질문을 읽기 좋게 정리합니다.

    연속 빈 줄 → <br> 1개, 단일 줄바꿈 → <br> 1개로 압축하여
    원문의 과도한 공백 없이 깔끔하게 표시합니다.
    """
    escaped = html.escape(text.strip())
    # 연속 줄바꿈(빈 줄 포함)을 <br> 하나로 압축
    return re.sub(r"\n+", "<br>", escaped)


def _navigate_to_topic(topic: str) -> None:
    """토픽 버튼 on_click 콜백 — state만 변경, Streamlit이 자동 rerun.

    on_click 콜백은 script rerun 전에 실행되므로
    st.rerun()을 호출할 필요가 없고 1회 rerun만 발생합니다.
    (기존: if st.button → 2회 rerun → 깜빡임/에러)
    """
    st.session_state.selected_topic = topic
    st.session_state.page_state = "topic_browse"


def _render_topic_column(
    sections: list[tuple[str, list[str]]], key_prefix: str
) -> None:
    """Step 헤더 + 토픽 버튼 목록을 렌더링합니다."""
    for section_title, topics in sections:
        st.markdown(f"**{section_title}**")
        for topic in topics:
            safe_key = f"{key_prefix}_{topic.replace(' ', '_')}"
            # on_click 콜백: state 변경 → Streamlit 자동 1회 rerun
            st.button(
                topic,
                key=safe_key,
                use_container_width=True,
                on_click=_navigate_to_topic,
                args=(topic,),
            )


def _render_home() -> None:
    """[홈] 8섹션 토픽 매트릭스 + 자유 질문 입력을 렌더링합니다.

    좌우 2단 레이아웃: 좌측(5단계 수익인식 모형) / 우측(후속 처리·특수 거래)
    하단에 자유 텍스트 입력 → /chat SSE → ai_answer 페이지로 직행
    """
    # ── 구분선 — 헤더 바로 아래 (topic_browse와 동일) ────────────────────────
    st.markdown(
        "<hr style='margin-top:-2.5rem; margin-bottom:0; "
        "border:none; border-top:1px solid #E2E8F0;'>",
        unsafe_allow_html=True,
    )

    st.html(
        """
        <div style='text-align: center; padding: 0 0 0.5rem;'>
            <h2 style='font-size: 1.5em; font-weight: 700; margin-bottom: 0.3rem; color: #334155;'>
                무엇을 검토하고 싶으신가요?
            </h2>
            <p style='color: #64748B; font-size: 0.9em; margin-bottom: 0;'>
                아래 주제를 클릭하면 관련 기준서 조항을 바로 열람할 수 있습니다.
            </p>
        </div>
    """
    )

    # ── 2단 레이아웃: 좌(5단계 모형) / 우(후속·특수 거래) ────────────────
    left_col, right_col = st.columns(2, gap="small")

    with left_col:
        # Why: 상단 실선·하단 점선 사이에 헤더가 수직 중앙 배치되도록 대칭 마진
        # Why: st.markdown bold는 <p> 기본 마진이 커서 점선과 간격 제어 불가 → st.html로 직접 제어
        st.html(
            "<hr style='border:none; border-top:1px solid #E2E8F0; margin:0.3rem 0 0;'>"
            "<p style='font-weight:700; margin:0; padding:1.2rem 0 4px;'>📋 5단계 수익인식 모형</p>"
            "<hr style='border:none; border-top:1.5px dashed #E2E8F0; margin:0;'>"
        )
        with st.container(border=True, gap="xsmall"):
            _render_topic_column(HOME_TOPICS_LEFT, "L")

    with right_col:
        st.html(
            "<hr style='border:none; border-top:1px solid #E2E8F0; margin:0.3rem 0 0;'>"
            "<p style='font-weight:700; margin:0; padding:1.2rem 0 4px;'>📋 후속 처리 · 특수 거래</p>"
            "<hr style='border:none; border-top:1.5px dashed #E2E8F0; margin:0;'>"
        )
        with st.container(border=True, gap="xsmall"):
            _render_topic_column(HOME_TOPICS_RIGHT, "R")

    # ── 하단: 자유 질문 입력 ──────────────────────────────────────────────
    st.divider()
    st.markdown("#### :material/chat: 직접 질문하기")
    st.caption(
        "구체적인 사실관계를 자유롭게 설명해 주세요. "
        "AI가 상황을 분석하고 사실에 기반한 답변을 드립니다."
    )

    # Why: st.form 제출은 fragment 안에서도 전체 rerun을 유발하므로
    #      일반 위젯 + st.button을 사용해야 fragment rerun만 발생 → 스크롤 유지
    @st.fragment
    def _home_search_fragment():
        query = st.text_area(
            "상황 입력",
            placeholder="상세한 거래 구조나 애매한 회계 상황을 자유롭게 입력해 주세요...\n"
            "(예: 반품 가능성이 높을 때 매출 인식 시기는?)",
            label_visibility="collapsed",
            height=100,
            key="home_search_input",
        )
        if st.button(
            "검색하기", use_container_width=True, type="primary", key="home_search_btn"
        ):
            if query and query.strip():
                st.session_state.search_query = query.strip()
                _call_chat(query.strip(), use_cache=False)

    _home_search_fragment()


def _render_evidence() -> None:
    """[근거 열람] 카테고리별 아코디언 + AI 질문 입력창을 렌더링합니다."""
    # ── 구분선 — 헤더 바로 아래 ─────────────────────────────────────────────
    st.markdown(
        "<hr style='margin-top:-2.5rem; margin-bottom:0; "
        "border:none; border-top:1px solid #E2E8F0;'>",
        unsafe_allow_html=True,
    )

    # ── 상단 헤더: 질문 카드 + 새 검색 버튼 ──────────────────────────────────
    current_query = (
        st.session_state.get("search_query")
        or st.session_state.get("standalone_query")
        or ""
    )

    col1, col2 = st.columns([5, 1], vertical_alignment="bottom")

    with col1:
        st.html(
            f"""
            <div style='padding: 0.5rem 0 0;'>
                <span style='color: #64748B; font-size: 0.9em;'>질문</span><br>
                <span style='line-height: 1.7;'>{_format_question(current_query)}</span>
            </div>
        """
        )

    with col2:
        st.button(
            "새 검색",
            icon=":material/home:",
            use_container_width=True,
            on_click=_go_home,
        )

    st.divider()

    # 아코디언 패널 (공통 함수 재사용)
    if not st.session_state.get("evidence_docs"):
        st.info("관련 조항을 찾지 못했습니다. 다른 검색어로 시도해보세요.")
    else:
        _render_evidence_panel()

    st.divider()

    @st.fragment
    def _ai_question_fragment():
        st.markdown("#### :material/lightbulb: AI에게 해석을 물어보세요")
        st.caption("위 조항들을 바탕으로 AI가 실무 관점의 답변을 드립니다.")

        ai_q = st.text_area(
            "AI 질문",
            placeholder="예: 반품 예상 수량을 합리적으로 추정할 수 없을 때 수익을 전혀 인식하면 안 되나요?",
            label_visibility="collapsed",
            height=100,
            key="evidence_ai_input",
        )
        if st.button(
            "AI에게 질문하기",
            use_container_width=True,
            type="primary",
            key="evidence_ai_btn",
        ):
            if ai_q and ai_q.strip():
                _call_chat(ai_q.strip(), use_cache=False)

    _ai_question_fragment()


def _send_feedback(feedback: str, reason: str = "") -> None:
    """피드백을 서버에 전송하고 session_state에 결과를 저장합니다."""
    log_id = st.session_state.get("log_id")
    if not log_id:
        return
    try:
        payload = {"log_id": log_id, "feedback": feedback}
        if reason:
            payload["reason"] = reason
        resp = httpx.post(FEEDBACK_URL, json=payload, timeout=5)
        if resp.status_code == 200:
            st.session_state.feedback_sent = feedback
    except Exception:
        pass


def _render_feedback_buttons() -> None:
    """답변 하단에 피드백 버튼을 렌더링합니다."""
    # 피드백 완료 상태
    if st.session_state.get("feedback_sent") in ("up", "down"):
        st.caption("피드백 감사합니다 :D")
        return

    if not st.session_state.get("log_id"):
        return

    # 👎 클릭 후 사유 입력 단계
    if st.session_state.get("feedback_sent") == "down_pending":
        st.caption("어떤 점이 부족했나요?")
        reason = st.text_input(
            "개선 사유",
            placeholder="예: 관련 없는 문단을 인용함, 결론이 너무 성급함...",
            label_visibility="collapsed",
            key="feedback_reason_input",
        )
        c1, c2, c3 = st.columns([2, 2, 8])
        with c1:
            if st.button("전송", key="feedback_reason_send", type="primary", use_container_width=True):
                _send_feedback("down", reason=reason.strip() if reason else "")
                st.rerun()
        with c2:
            if st.button("건너뛰기", key="feedback_reason_skip", use_container_width=True):
                _send_feedback("down")
                st.rerun()
        return

    # 초기 상태: 👍/👎 버튼 — 한 줄에 나란히 배치
    col_up, col_down = st.columns(2)
    with col_up:
        if st.button("👍 도움이 됐어요", key="feedback_up", use_container_width=True):
            _send_feedback("up")
            st.rerun()
    with col_down:
        if st.button("👎 개선이 필요해요", key="feedback_down", use_container_width=True):
            st.session_state.feedback_sent = "down_pending"
            st.rerun()


def _render_ai_answer() -> None:
    """[AI 답변] Split View — 좌(근거 문서) + 우(AI 답변 + 꼬리질문) 동시 표시."""
    # ── 구분선 — 헤더 바로 아래 ─────────────────────────────────────────────
    st.markdown(
        "<hr style='margin-top:-2.5rem; margin-bottom:0; "
        "border:none; border-top:1px solid #E2E8F0;'>",
        unsafe_allow_html=True,
    )

    # 헤더: 질문 이력 + 새 검색 버튼
    history = st.session_state.get("ai_questions_history", [])
    # 이력이 비어있으면 현재 질문만 표시
    if not history:
        history = [st.session_state.ai_question] if st.session_state.ai_question else []

    col1, col2 = st.columns([5, 1])
    with col1:
        # 모든 턴의 질문을 순서대로 표시
        for idx, q in enumerate(history):
            label = "질문" if idx == 0 else f"추가 질문 {idx}"
            st.html(
                f"""
                <div style='padding: 0.3rem 0 0;'>
                    <span style='color: #64748B; font-size: 0.9em;'>{label}</span><br>
                    <span style='line-height: 1.7;'>{_format_question(q)}</span>
                </div>
            """
            )
    with col2:
        st.button(
            "새 검색",
            icon=":material/home:",
            use_container_width=True,
            on_click=_go_home,
        )

    st.divider()

    # ── Split View: 좌(근거) + 우(답변) 1:1 비율 ────────────────────────────
    left, right = st.columns([1, 1])

    with left:
        st.subheader(":material/description: 근거 문서")
        _render_evidence_panel()

    with right:
        st.subheader(":material/smart_toy: AI 답변")

        answer = st.session_state.ai_answer
        if answer:
            st.markdown(clean_text(answer), unsafe_allow_html=True)
        else:
            st.info("답변을 준비 중입니다...")

        # 감리사례 expander
        if st.session_state.findings_case:
            fc = st.session_state.findings_case
            case_title = fc.get("title", "감리지적사례")
            with st.expander(
                f":material/gavel: 금융감독원 지적사례: {_esc(case_title)}", expanded=False
            ):
                raw_content = fc.get("content", "내용을 불러올 수 없습니다.")
                adjusted = _format_pdr_content(raw_content)
                st.markdown(clean_text(adjusted), unsafe_allow_html=True)

        # ── 피드백 버튼 (👍/👎) ────────────────────────────────────────
        _render_feedback_buttons()

        st.divider()

        # Why: @st.fragment로 감싸서 입력 시 스크롤 유지 (docs §3 규칙)
        #      fragment 내 st.rerun()은 전체 페이지 rerun (페이지 전환 정상 동작)
        @st.fragment
        def _followup_fragment():
            st.markdown("#### :material/forum: 추가 질문")
            new_q = st.text_area(
                "추가 질문",
                placeholder="추가질문이나 확인 질문에 대한 답변을 입력해주세요...",
                label_visibility="collapsed",
                height=100,
                key="followup_input",
            )

            def _submit_followup():
                """on_click 콜백 — rerun 전에 실행되므로 위젯 키 삭제 가능."""
                q = st.session_state.get("followup_input", "").strip()
                if q:
                    # 다음 rerun에서 사용할 질문을 별도 키에 저장
                    st.session_state["_pending_followup_text"] = q
                    # 위젯 키 삭제 → 다음 렌더에서 빈 상태로 생성
                    del st.session_state["followup_input"]

            st.button(
                "질문하기",
                use_container_width=True,
                type="primary",
                key="followup_btn",
                on_click=_submit_followup,
            )
            # on_click에서 저장한 질문이 있으면 API 호출
            pending = st.session_state.pop("_pending_followup_text", None)
            if pending:
                _call_chat(pending, use_cache=False)

        _followup_fragment()

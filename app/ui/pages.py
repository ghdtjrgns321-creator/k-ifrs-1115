# app/ui/pages.py
# 페이지 렌더러 함수 3개.
#
# - _render_home:       홈 — 자유 질문 입력창 (챗봇 전용, 미니멀)
# - _render_evidence:   근거 열람 — 카테고리별 아코디언 + AI 질문 입력창
# - _render_ai_answer:  AI 답변 — Split View (근거 + 답변 + 꼬리 질문)

import html
import re

import streamlit as st

import httpx

from app.ui.client import _call_chat
from app.ui.components import _render_evidence_panel
from app.ui.constants import FEEDBACK_URL, HOME_EXAMPLE_QUERIES
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


def _render_home() -> None:
    """[홈] 챗봇 전용 미니멀 진입 — 안내 문구 + 자유 질문 입력창.

    입력 제출 → /chat SSE → ai_answer 페이지로 직행합니다.
    (토픽 브라우징·사이드바 제거로 진입점을 자유 질문 하나로 단순화)
    """
    # ── 중앙 정렬: wide 레이아웃에서 입력 블록을 가운데로 모음 (중앙 ≈730px) ──
    _, center, _ = st.columns([1, 3, 1])
    with center:
        # 헤더와 입력창 사이 여백 — 설명 문단 대신 예시 칩이 안내를 대신한다.
        st.html("<div style='height: 1.6rem;'></div>")

        # Why: st.form 제출은 fragment 안에서도 전체 rerun을 유발하므로
        #      chat_input/pills + fragment 조합으로 fragment rerun만 발생 → 스크롤 유지
        @st.fragment
        def _home_search_fragment():
            # 컨테이너 안의 chat_input은 화면 하단 고정이 아니라 inline으로
            # 렌더됨 — 전송(↑) 버튼이 입력창 안에 내장된 챗봇 표준 패턴.
            query = st.chat_input(
                "거래 구조나 회계 상황을 구체적으로 입력하세요",
                key="home_chat_input",
            )
            if query and query.strip():
                st.session_state.search_query = query.strip()
                _call_chat(query.strip(), use_cache=False)

            # ── 예시 질문 카드: 굵은 주제어 + 원문, 클릭 즉시 실행 ──────────
            st.html(
                "<p style='color:#94A3B8; font-size:0.85em; font-weight:600; "
                "margin:1.6rem 0 0.3rem;'>이런 질문을 해보세요</p>"
            )
            for i, ex in enumerate(HOME_EXAMPLE_QUERIES):
                if st.button(
                    f"**{ex['topic']}** · {ex['question']}",
                    use_container_width=True,
                    key=f"home_example_{i}",
                ):
                    st.session_state.search_query = ex["question"]
                    _call_chat(ex["question"], use_cache=False)

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
            if st.button(
                "전송",
                key="feedback_reason_send",
                type="primary",
                use_container_width=True,
            ):
                _send_feedback("down", reason=reason.strip() if reason else "")
                st.rerun()
        with c2:
            if st.button(
                "건너뛰기", key="feedback_reason_skip", use_container_width=True
            ):
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
        if st.button(
            "👎 개선이 필요해요", key="feedback_down", use_container_width=True
        ):
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
                f":material/gavel: 금융감독원 지적사례: {_esc(case_title)}",
                expanded=False,
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

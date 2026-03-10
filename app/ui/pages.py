# app/ui/pages.py
# 페이지 렌더러 함수 3개.
#
# - _render_home:       홈 — 키워드 칩 + 자유 검색창
# - _render_evidence:   근거 열람 — 카테고리별 아코디언 + AI 질문 입력창
# - _render_ai_answer:  AI 답변 — Split View (근거 + 답변 + 꼬리 질문)

import html
import re

import streamlit as st

from app.ui.client import _call_chat, _call_search
from app.ui.components import _render_evidence_panel
from app.ui.constants import HOME_TOPICS_LEFT, HOME_TOPICS_RIGHT
from app.ui.session import _go_home


def _format_question(text: str) -> str:
    """사용자 질문을 읽기 좋게 정리합니다.

    연속 빈 줄 → <br> 1개, 단일 줄바꿈 → <br> 1개로 압축하여
    원문의 과도한 공백 없이 깔끔하게 표시합니다.
    """
    escaped = html.escape(text.strip())
    # 연속 줄바꿈(빈 줄 포함)을 <br> 하나로 압축
    return re.sub(r'\n+', '<br>', escaped)


def _navigate_to_topic(topic: str) -> None:
    """토픽 버튼 on_click 콜백 — state만 변경, Streamlit이 자동 rerun.

    on_click 콜백은 script rerun 전에 실행되므로
    st.rerun()을 호출할 필요가 없고 1회 rerun만 발생합니다.
    (기존: if st.button → 2회 rerun → 깜빡임/에러)
    """
    st.session_state.selected_topic = topic
    st.session_state.page_state = "topic_browse"


def _render_topic_column(sections: list[tuple[str, list[str]]], key_prefix: str) -> None:
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
        st.markdown("**📋 5단계 수익인식 모형**")
        st.markdown("<hr style='border: none; border-top: 1.5px dashed #E2E8F0; margin: 5px 0 20px 0;'>", unsafe_allow_html=True)
        with st.container(border=True, gap="xsmall"):
            _render_topic_column(HOME_TOPICS_LEFT, "L")

    with right_col:
        st.markdown("**📋 후속 처리 · 특수 거래**")
        st.markdown("<hr style='border: none; border-top: 1.5px dashed #E2E8F0; margin: 5px 0 20px 0;'>", unsafe_allow_html=True)
        with st.container(border=True, gap="xsmall"):
            _render_topic_column(HOME_TOPICS_RIGHT, "R")

    # ── 하단: 자유 질문 입력 ──────────────────────────────────────────────
    st.divider()
    st.markdown("#### :material/chat: 직접 질문하기")
    st.caption(
        "구체적인 사실관계를 자유롭게 설명해 주세요. "
        "AI가 상황을 분석하고 사실에 기반한 답변을 드립니다."
    )

    with st.form("search_form", clear_on_submit=False):
        query = st.text_area(
            "상황 입력",
            placeholder="상세한 거래 구조나 애매한 회계 상황을 자유롭게 입력해 주세요...\n"
            "(예: 반품 가능성이 높을 때 매출 인식 시기는?)",
            label_visibility="collapsed",
            height=100,
        )
        submitted = st.form_submit_button(
            "검색하기", use_container_width=True, type="primary"
        )

    # 홈에서 검색 → /chat SSE 직행 (단계별 진행 표시 + split view 결과)
    if submitted and query:
        st.session_state.search_query = query.strip()
        _call_chat(query.strip(), use_cache=False)


def _render_evidence() -> None:
    """[근거 열람] 카테고리별 아코디언 + AI 질문 입력창을 렌더링합니다."""
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

    # AI 질문 입력창
    st.markdown("#### :material/lightbulb: AI에게 해석을 물어보세요")
    st.caption("위 조항들을 바탕으로 AI가 실무 관점의 답변을 드립니다.")

    with st.form("ai_question_form", clear_on_submit=True):
        ai_q = st.text_area(
            "AI 질문",
            placeholder="예: 반품 예상 수량을 합리적으로 추정할 수 없을 때 수익을 전혀 인식하면 안 되나요?",
            label_visibility="collapsed",
            height=100,
        )
        submitted = st.form_submit_button(
            "AI에게 질문하기", use_container_width=True, type="primary"
        )

    if submitted and ai_q:
        _call_chat(ai_q, use_cache=False)


def _render_ai_answer() -> None:
    """[AI 답변] Split View — 좌(근거 문서) + 우(AI 답변 + 꼬리질문) 동시 표시."""
    # 헤더: 질문 + 새 검색 버튼
    col1, col2 = st.columns([5, 1])
    with col1:
        st.html(
            f"""
            <div style='padding: 0.5rem 0 0;'>
                <span style='color: #64748B; font-size: 0.9em;'>질문</span><br>
                <span style='line-height: 1.7;'>{_format_question(st.session_state.ai_question)}</span>
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
            st.markdown(answer)
        else:
            st.info("답변을 준비 중입니다...")

        # 감리사례 expander
        if st.session_state.findings_case:
            fc = st.session_state.findings_case
            case_title = fc.get("title", "감리지적사례")
            with st.expander(f":material/gavel: 금융감독원 지적사례: {case_title}", expanded=False):
                raw_content = fc.get("content", "내용을 불러올 수 없습니다.")
                adjusted = raw_content.replace("# ", "### ").replace("## ", "#### ")
                st.markdown(adjusted)

        st.divider()

        # 자유 입력창 — 새로운 주제 가능성이 있으므로 full pipeline 수행
        st.markdown("#### :material/forum: 추가 질문")
        with st.form("followup_form", clear_on_submit=True):
            new_q = st.text_input(
                "추가 질문",
                placeholder="추가로 궁금한 점을 입력하세요...",
                label_visibility="collapsed",
            )
            submitted = st.form_submit_button("질문하기", use_container_width=True)

        if submitted and new_q:
            # 자유 입력은 새 주제일 수 있으므로 search_id 없이 새 검색 수행
            _call_chat(new_q, use_cache=False)

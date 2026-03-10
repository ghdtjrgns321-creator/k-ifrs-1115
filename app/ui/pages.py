# app/ui/pages.py
# 페이지 렌더러 함수 3개.
#
# - _render_home:       홈 — 키워드 칩 + 자유 검색창
# - _render_evidence:   근거 열람 — 카테고리별 아코디언 + AI 질문 입력창
# - _render_ai_answer:  AI 답변 — Split View (근거 + 답변 + 꼬리 질문)

import html

import streamlit as st

from app.ui.client import _call_chat, _call_search
from app.ui.components import _render_evidence_panel
from app.ui.constants import HOME_TOPICS_LEFT, HOME_TOPICS_RIGHT
from app.ui.session import _go_home


def _navigate_to_topic(topic: str) -> None:
    """토픽 버튼 클릭 → topic_browse 페이지로 전환합니다."""
    st.session_state.selected_topic = topic
    st.session_state.page_state = "topic_browse"
    st.rerun()


def _render_topic_column(sections: list[tuple[str, list[str]]], key_prefix: str) -> None:
    """Step 헤더 + 토픽 버튼 목록을 렌더링합니다."""
    for section_title, topics in sections:
        st.markdown(f"**{section_title}**")
        for topic in topics:
            safe_key = f"{key_prefix}_{topic.replace(' ', '_')}"
            if st.button(topic, key=safe_key, use_container_width=True):
                _navigate_to_topic(topic)


def _render_home() -> None:
    """[홈] 8섹션 토픽 매트릭스 + 자유 질문 입력을 렌더링합니다.

    좌우 2단 레이아웃: 좌측(5단계 수익인식 모형) / 우측(후속 처리·특수 거래)
    하단에 자유 텍스트 입력 → /search → evidence 페이지로 이동
    """
    # ── 구분선 — #7AAACE 포인트, 헤더에 바짝 붙임 ──────────────────────────
    st.markdown("<hr style='margin-top: -2.5rem; margin-bottom: 0; border: none; border-top: 1px solid #E2E8F0;'>", unsafe_allow_html=True)

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

    # 위젯 렌더링 완료 후 API 호출 (Streamlit 원칙)
    search_placeholder = st.empty()
    if submitted and query:
        with search_placeholder:
            _call_search(query.strip())


def _render_evidence() -> None:
    """[근거 열람] 카테고리별 아코디언 + AI 질문 입력창을 렌더링합니다."""
    # ── 상단 헤더: 검색어 타이틀 + 새 검색 버튼 (8:2 비율) ───────────────────
    current_query = (
        st.session_state.get("search_query")
        or st.session_state.get("standalone_query")
        or ""
    )

    title_col, btn_col = st.columns([8, 2], vertical_alignment="bottom")

    with title_col:
        st.markdown(f"### :material/search: 검색 결과: **{current_query}**")

    with btn_col:
        if st.button("새 검색", icon=":material/arrow_back:", use_container_width=True):
            _go_home()

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
            <div style='padding: 0.5rem 0;'>
                <span style='color: #64748B; font-size: 0.9em;'>질문</span><br>
                <strong>{html.escape(st.session_state.ai_question)}</strong>
            </div>
        """
        )
    with col2:
        if st.button("새 검색", icon=":material/home:", use_container_width=True):
            _go_home()

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

        # 출처 expander
        if st.session_state.cited_sources:
            with st.expander(":material/bookmark: 참고 근거 보기", expanded=False):
                for src in st.session_state.cited_sources:
                    source_type = src.get("source", "알 수 없음")
                    hierarchy = src.get("hierarchy", "출처 정보 없음")
                    paragraphs = src.get("related_paragraphs", [])
                    p_str = (
                        f" | 관련 문단: {', '.join(paragraphs)}" if paragraphs else ""
                    )
                    st.caption(f"**[{source_type}]** {hierarchy}{p_str}")

        # 꼬리 질문 버튼 (최대 3개)
        # use_cache=True: 이미 검색된 근거를 재사용하므로 빠르게 응답합니다.
        followups = st.session_state.follow_up_questions
        if followups:
            st.html("<br>")
            st.markdown("**추가로 확인하면 좋을 질문:**")

            btn_cols = st.columns(len(followups))
            for i, fq in enumerate(followups):
                with btn_cols[i]:
                    if st.button(fq, use_container_width=True, key=f"followup_{i}"):
                        # 꼬리질문은 같은 컨텍스트(search_id) 재사용 → retrieve 스킵
                        _call_chat(fq, use_cache=True)

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

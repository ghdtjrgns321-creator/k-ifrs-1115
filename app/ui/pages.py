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
from app.ui.constants import KEYWORD_CHIPS
from app.ui.session import _go_home


def _render_home() -> None:
    """[홈] 키워드 칩 + 자유 검색창을 렌더링합니다.

    KEYWORD_CHIPS(12개) 마지막에 '직접 입력' 칩을 추가하여 총 13개 버튼을 4열로 배치합니다.
    커스텀 칩 클릭 시 인라인 단어 입력창이 펼쳐지며, 단어/용어 입력을 유도합니다.
    """
    _CUSTOM_CHIP_LABEL = "🔍 다른 용어 검색"

    st.html(
        """
        <div style='text-align: center; padding: 2rem 0 1rem;'>
            <h2 style='font-size: 1.6em; font-weight: 700; margin-bottom: 0.4rem;'>
                무엇을 검토하고 싶으신가요?
            </h2>
            <p style='color: #6B7280; font-size: 1.0em;'>
                아래 키워드를 클릭하면 관련 기준서 조항을 바로 열람할 수 있습니다.
            </p>
        </div>
    """
    )

    # ── 키워드 칩 버튼 렌더링 (12개 + 커스텀 1개, 4열 배치) ────────────
    target_chip = None
    spinner_placeholder = None
    active_chip = st.session_state.get("active_chip")

    cols = st.columns(4)
    # 일반 키워드 칩 12개 렌더링
    for i, chip in enumerate(KEYWORD_CHIPS):
        with cols[i % 4]:
            is_active = active_chip == chip
            is_disabled = (active_chip is not None) and (not is_active)
            btn_type = "primary" if is_active else "secondary"

            if st.button(
                chip,
                use_container_width=True,
                key=f"chip_{i}",
                type=btn_type,
                disabled=is_disabled,
            ):
                st.session_state.active_chip = chip
                st.rerun()

            if is_active:
                target_chip = chip
                spinner_placeholder = st.empty()

    # ── 커스텀 단어 검색 버튼 (마지막 칩) ──────────────────────
    custom_query = None

    # 4열 맞춰서 빈 공간에 자연스럽게 배치
    with cols[len(KEYWORD_CHIPS) % 4]:
        chip = _CUSTOM_CHIP_LABEL
        is_active = active_chip == chip
        is_disabled = (active_chip is not None) and (not is_active)
        btn_type = "primary" if is_active else "secondary"

        if st.button(
            chip,
            use_container_width=True,
            key="chip_custom",
            type=btn_type,
            disabled=is_disabled,
        ):
            st.session_state.active_chip = chip
            st.rerun()

    # 버튼이 눌려 활성화된 경우에만 새로운 줄(전체 너비)에 검색 양식을 표시합니다.
    if active_chip == _CUSTOM_CHIP_LABEL:
        st.markdown("<div style='margin-top: 0.5rem;'></div>", unsafe_allow_html=True)
        # 밑에 있는 메인 검색창과 대비되도록, 박스 외곽선을 없애고(border=False) 컴팩트하게 구성
        with st.form("custom_chip_form", clear_on_submit=False, border=False):
            col_in, col_sub, col_can = st.columns([6, 2, 2])
            with col_in:
                custom_input = st.text_input(
                    "용어 직접 입력",
                    placeholder="찾고자 하는 회계 용어 입력 (예: 변동대가 / 수행의무)",
                    label_visibility="collapsed",
                )
            with col_sub:
                # 메인 검색의 빨간색 버튼(primary)과 다르게 기본(secondary) 스타일의 작고 깔끔한 형태
                custom_submitted = st.form_submit_button(
                    "🔍 검색", use_container_width=True
                )
            with col_can:
                cancel = st.form_submit_button("취소", use_container_width=True)

        if custom_submitted and custom_input:
            custom_query = custom_input.strip()
        if cancel:
            st.session_state.active_chip = None
            st.rerun()

        custom_spinner_placeholder = st.empty()

    # 넓은 수직 여백 추가 (구분감 확보)
    st.markdown("<br><br><br>", unsafe_allow_html=True)

    # ── 자유 검색 폼 ──────────────────────────────────────────────────────────
    st.markdown("##### 💬 복잡한 거래 구조나 애매한 상황인가요?")
    st.caption(
        "키워드로 찾기 어려운 구체적인 사실관계를 자유롭게 설명해 주세요. AI가 상황을 분석하고 정확한 판단을 위한 꼬리질문을 던져드립니다."
    )

    with st.form("search_form", clear_on_submit=False):
        query = st.text_area(
            "상황 입력",
            placeholder="상세한 거래 구조나 애매한 회계 상황을 자유롭게 입력해 주세요...\n(예: 반품 가능성이 높을 때 매출 인식 시기는?)",
            label_visibility="collapsed",
            height=150,
        )
        submitted = st.form_submit_button(
            "검색하기", use_container_width=True, type="primary"
        )

    # ── 통신 실행 (모든 위젯 렌더링 완료 후) ────────────────────────────────
    # Streamlit은 위젯 렌더링 이후에 API 호출을 실행해야 합니다.
    if custom_query:
        with custom_spinner_placeholder:
            st.session_state.active_chip = None
            _call_search(custom_query)
    elif submitted and query:
        # spinner는 _call_chat 내부 answer_placeholder가 담당 (중복 제거)
        st.session_state.active_chip = None
        _call_chat(query, use_cache=False)
    elif target_chip and spinner_placeholder:
        with spinner_placeholder:
            st.session_state.active_chip = None
            _call_search(target_chip)


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
        st.markdown(f"### 🔍 검색 결과: **{current_query}**")

    with btn_col:
        if st.button("← 새 검색", use_container_width=True):
            _go_home()

    st.divider()

    # 아코디언 패널 (공통 함수 재사용)
    if not st.session_state.get("evidence_docs"):
        st.info("관련 조항을 찾지 못했습니다. 다른 검색어로 시도해보세요.")
    else:
        _render_evidence_panel()

    st.divider()

    # AI 질문 입력창
    st.markdown("#### 💡 AI에게 해석을 물어보세요")
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
                <span style='color: #6B7280; font-size: 0.9em;'>질문</span><br>
                <strong>{html.escape(st.session_state.ai_question)}</strong>
            </div>
        """
        )
    with col2:
        if st.button("🏠 새 검색", use_container_width=True):
            _go_home()

    st.divider()

    # ── Split View: 좌(근거) + 우(답변) 1:1 비율 ────────────────────────────
    left, right = st.columns([1, 1])

    with left:
        st.subheader("📄 근거 문서")
        _render_evidence_panel()

    with right:
        st.subheader("🤖 AI 답변")

        answer = st.session_state.ai_answer
        if answer:
            st.markdown(answer)
        else:
            st.info("답변을 준비 중입니다...")

        # 감리사례 expander
        if st.session_state.findings_case:
            fc = st.session_state.findings_case
            case_title = fc.get("title", "감리지적사례")
            with st.expander(f"📋 금융감독원 지적사례: {case_title}", expanded=False):
                raw_content = fc.get("content", "내용을 불러올 수 없습니다.")
                adjusted = raw_content.replace("# ", "### ").replace("## ", "#### ")
                st.markdown(adjusted)

        # 출처 expander
        if st.session_state.cited_sources:
            with st.expander("📌 참고 근거 보기", expanded=False):
                for src in st.session_state.cited_sources:
                    source_type = src.get("source", "알 수 없음")
                    hierarchy = src.get("hierarchy", "출처 정보 없음")
                    paragraphs = src.get("related_paragraphs", [])
                    p_str = (
                        f" | 관련 문단: {', '.join(paragraphs)}" if paragraphs else ""
                    )
                    st.caption(f"**[{source_type}]** {hierarchy}{p_str}")

        # 꼬리 질문 버튼 (최대 3개)
        # is_situation=True  → 선택지 모드: 사용자가 상황 답변 선택 (use_cache=False, 새 검색)
        # is_situation=False → 개념 확인 모드: 같은 컨텍스트 재사용 (use_cache=True)
        followups = st.session_state.follow_up_questions
        is_situation = st.session_state.get("is_situation", False)
        if followups:
            st.html("<br>")
            if is_situation:
                st.markdown("**아래 상황 중 해당하는 것을 선택해 주세요:**")
            else:
                st.markdown("**추가로 확인하면 좋을 질문:**")

            btn_cols = st.columns(len(followups))
            for i, fq in enumerate(followups):
                with btn_cols[i]:
                    if st.button(fq, use_container_width=True, key=f"followup_{i}"):
                        # 상황 선택지: 새 검색 필요 / 개념 꼬리질문: 캐시 재사용
                        _call_chat(fq, use_cache=not is_situation)

        st.divider()

        # 자유 입력창 — 새로운 주제 가능성이 있으므로 full pipeline 수행
        st.markdown("#### 💬 추가 질문")
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

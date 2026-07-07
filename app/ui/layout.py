# app/ui/layout.py
# CSS 주입, 헤더, 사이드바 렌더링.
#
# 팔레트:
#   #0F172A — 텍스트, 버튼 (primaryColor로 Streamlit이 처리)
#   #334155 — 강조 제목
#   #E2E8F0 — 테두리, 구분선
#   #FFFFFF — 배경

import streamlit as st

# ── CSS는 레이아웃 보정 용도로만 사용 (색상은 config.toml에서 관리) ──────
_CUSTOM_CSS = """
<style>
    #MainMenu, footer { visibility: hidden; }
    header[data-testid="stHeader"] { background: transparent !important; }
    .block-container {
        padding-top: 2rem; padding-bottom: 2rem;
        max-width: 1220px !important;
    }

    /* expander 카드 — shadcn 스타일 */
    div[data-testid="stExpander"] {
        border: 1px solid #E2E8F0 !important;
        border-radius: 8px !important;
        margin-bottom: 0.15rem !important;
        overflow: hidden;
        box-shadow: 0 1px 2px rgba(0,0,0,0.04);
        transition: border-color 0.15s, box-shadow 0.15s;
    }
    div[data-testid="stExpander"]:hover {
        border-color: #CBD5E1 !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.06);
    }

    /* 근거 패널: 그룹 헤더(h3) 간격 최소화 */
    div[data-testid="stVerticalBlock"] > div > div > .stMarkdown h3 {
        margin-top: 0.4rem !important;
        margin-bottom: 0.1rem !important;
    }

    /* 근거 패널: 소제목(bold) 간격 최소화 */
    div[data-testid="stVerticalBlock"] > div > div > .stMarkdown p {
        margin-bottom: 0.05rem !important;
    }

    /* Streamlit 블록 간 기본 간격 축소 */
    div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"] {
        margin-bottom: 0 !important;
        padding-bottom: 0 !important;
    }
    div[data-testid="stVerticalBlock"] > div {
        gap: 0 !important;
    }

    /* 문단 본문 */
    .doc-body { padding: 0.25rem 0; }
    .doc-body p.doc-para {
        line-height: 1.85;
        margin-bottom: 0.85rem;
        font-size: 0.95em;
    }

    /* 문단 참조 링크 */
    a.para-link-found {
        color: #334155;
        text-decoration: underline;
        text-underline-offset: 2px;
        font-weight: 500;
    }
    a.para-link-found:hover { color: #64748B; }
    a.para-link-ext {
        color: #94A3B8;
        text-decoration: underline dotted;
        text-underline-offset: 2px;
        cursor: default;
    }

    /* 퀵뷰 칩 */
    .quick-chips-row {
        display: flex; flex-wrap: wrap;
        align-items: center; gap: 0.4rem;
        margin: 0.6rem 0 0.2rem;
    }
    .chips-label {
        font-size: 0.75em; font-weight: 600; color: #64748B;
        text-transform: uppercase; letter-spacing: 0.05em;
        margin-right: 0.25rem;
    }
    a.quick-chip.found {
        display: inline-block;
        background: #FFFFFF; color: #334155;
        border: 1px solid #E2E8F0; border-radius: 999px;
        padding: 0.2rem 0.65rem; font-size: 0.8em; font-weight: 500;
        text-decoration: none; cursor: pointer;
        transition: all 0.15s;
    }
    a.quick-chip.found:hover {
        background: #F1F5F9;
        border-color: #94A3B8;
    }
    span.quick-chip.missing {
        display: inline-block;
        background: #FAFAFA; color: #94A3B8;
        border: 1px solid #E2E8F0; border-radius: 999px;
        padding: 0.2rem 0.65rem; font-size: 0.8em;
    }

    /* 출처 푸터 */
    .source-footer {
        background: #F8FAFC; border: 1px solid #E2E8F0;
        border-radius: 6px; padding: 0.45rem 0.8rem;
        font-size: 0.82em; color: #64748B; margin-top: 0.5rem;
    }

    /* rerun 중 stale 위젯 숨김 — 페이지 전환 깜빡임 방지
       Why: display:none은 요소 공간까지 제거 → fragment rerun 시
            레이아웃 시프트 → 브라우저 스크롤 보정 → 위로 점프.
            visibility:hidden은 공간 유지 + 시각적으로만 숨김 → 스크롤 안정 */
    .element-container[data-stale="true"] {
        visibility: hidden !important;
    }

    /* 진행 표시 스피너 애니메이션 */
    @keyframes claude-spin {
        to { transform: rotate(360deg); }
    }
    .progress-spinner {
        display: flex; align-items: center; gap: 8px;
        padding: 0.4rem 0;
    }
    .progress-spinner .spinner-icon {
        width: 14px; height: 14px; flex-shrink: 0;
        border: 2px solid #E2E8F0;
        border-top-color: #334155;
        border-radius: 50%;
        animation: claude-spin 0.8s linear infinite;
    }
    .progress-spinner .spinner-text {
        color: #64748B; font-size: 0.9em;
    }

    /* 홈 chat_input — 기본 1줄이 왜소해 보여 5~6줄 높이 + 큰 글씨로 확장 */
    div[class*="st-key-home_chat_input"] textarea {
        min-height: 170px !important;
        font-size: 1.05rem !important;
    }

    /* 홈 예시 질문 카드 — 굵은 주제어 + 원문, 좌측 정렬 카드형 */
    div[class*="st-key-home_example_"] button {
        border: 1px solid #E2E8F0 !important;
        background: #FFFFFF !important;
        border-radius: 10px !important;
        justify-content: flex-start !important;
        text-align: left !important;
        padding: 0.8rem 1.1rem !important;
        box-shadow: 0 1px 2px rgba(0,0,0,0.04);
        transition: border-color 0.15s, background 0.15s;
    }
    div[class*="st-key-home_example_"] button p {
        font-size: 1.0rem !important;
        color: #334155 !important;
        line-height: 1.55 !important;
    }
    div[class*="st-key-home_example_"] button:hover {
        border-color: #94A3B8 !important;
        background: #F8FAFC !important;
    }
    div[class*="st-key-home_example_"] {
        margin-bottom: 0.5rem !important;
    }

    /* 추가 질문 폼 — 질문하기 버튼 네이비 배경 */
    [data-testid="stFormSubmitButton"] button {
        background-color: #1E293B !important;
        color: white !important;
        border: none !important;
    }
    [data-testid="stFormSubmitButton"] button:hover {
        background-color: #334155 !important;
        color: white !important;
    }
</style>
"""


def _inject_css() -> None:
    """레이아웃 보정 CSS를 주입합니다."""
    st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)


def _render_header() -> None:
    """서비스 타이틀과 설명을 중앙 정렬로 렌더링합니다.

    배지·구분선 없이 제목+부제 두 줄만 — 홈의 예시 질문 칩이
    사용법 안내를 대신하므로 헤더는 정체성 표시에만 집중합니다.
    """
    st.html(
        """
        <div style='max-width: 730px; margin: 0 auto; text-align: center; padding-top: 48px;'>
            <h1 style='font-size: 2.2em; font-weight: 700; margin: 0; color: #0F172A;
                       letter-spacing: -0.01em;'>
                수익인식 기준서 분석
            </h1>
            <p style='font-size: 1.05em; color: #64748B; margin: 10px 0 0;'>
                K-IFRS 1115 기준서 본문 · 질의회신 · 감리사례를 근거로 답변합니다
            </p>
        </div>
    """
    )


def _render_disclaimer() -> None:
    """화면 하단 면책 문구 — 사이드바 제거로 옮긴 '참고 목적' 고지.

    사이드바를 없애면서 회계 도구 특성상 필요한 면책 고지를
    모든 페이지 하단에 작은 회색 줄로 고정 노출합니다.
    """
    st.html(
        "<div style='max-width: 730px; margin: 2.5rem auto 0; "
        "padding-top: 0.8rem; border-top: 1px solid #E2E8F0; "
        "text-align: center; font-size: 0.85em; color: #94A3B8; "
        "line-height: 1.6;'>"
        "본 답변은 실무 검토를 위한 <b>참고 목적</b>으로만 활용해 주세요. "
        "전문가적 판단이 필요한 복잡한 사안은 확정적 결론을 제공하지 못할 수 있습니다."
        "</div>"
    )

# app/ui/layout.py
# CSS 주입, 헤더, 사이드바 렌더링.
#
# 팔레트:
#   #0F172A — 텍스트, 버튼 (primaryColor로 Streamlit이 처리)
#   #334155 — 강조 제목
#   #E2E8F0 — 테두리, 구분선
#   #FFFFFF — 배경

import streamlit as st

from app.ui.session import _go_home

# ── CSS는 레이아웃 보정 용도로만 사용 (색상은 config.toml에서 관리) ──────
_CUSTOM_CSS = """
<style>
    #MainMenu, footer { visibility: hidden; }
    header[data-testid="stHeader"] { background: transparent !important; }
    .block-container {
        padding-top: 2rem; padding-bottom: 2rem;
        max-width: 1220px !important;
    }

    /* 홈: 제목↔박스 간격 최소화 */
    .main .stColumn > div > div > .stMarkdown + div[data-testid="stVerticalBlockBorderWrapper"] {
        margin-top: -1rem !important;
    }

    /* expander 카드 — shadcn 스타일 */
    div[data-testid="stExpander"] {
        border: 1px solid #E2E8F0 !important;
        border-radius: 8px !important;
        margin-bottom: 0.4rem !important;
        overflow: hidden;
        box-shadow: 0 1px 2px rgba(0,0,0,0.04);
        transition: border-color 0.15s, box-shadow 0.15s;
    }
    div[data-testid="stExpander"]:hover {
        border-color: #CBD5E1 !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.06);
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
    """서비스 타이틀과 설명을 중앙 정렬로 렌더링합니다."""
    st.html(
        """
        <div style='text-align: center; padding-top: 16px; padding-bottom: 8px;'>
            <span style='
                display: inline-block;
                border: 1px solid #E2E8F0;
                border-radius: 4px;
                padding: 2px 10px;
                font-size: 0.78em;
                font-weight: 600;
                color: #334155;
                letter-spacing: 0.02em;
                margin-bottom: 8px;
            '>K-IFRS 1115</span>
            <h1 style='font-size: 1.85em; font-weight: 700; margin: 4px 0 0; color: #0F172A;'>
                수익인식 기준서 분석 도구
            </h1>
            <p style='font-size: 0.9em; color: #64748B; margin-top: 6px; margin-bottom: 0;'>
                기준서 본문 · 질의회신 · 감리사례를 직접 열람하고 AI에게 해석을 물어보세요
            </p>
            <hr style='border: none; border-top: 1px solid #E2E8F0; margin-top: 12px; margin-bottom: 0;'>
        </div>
    """
    )


def _render_sidebar() -> None:
    """사이드바 — 일러두기 + 주의사항 + 기술 스택 푸터."""
    with st.sidebar:
        st.title("K-IFRS Chatbot")
        st.caption("기업회계기준서 제1115호  \n고객과의 계약에서 생기는 수익")

        st.button(
            "처음으로",
            icon=":material/home:",
            use_container_width=True,
            on_click=_go_home,
        )

        st.divider()
        st.markdown(
            "**일러두기**\n\n"
            "본 도구는 다음을 바탕으로 사실(Fact) 기반의 원칙적 답변을 제공"
            "합니다.\n\n"
            "- K-IFRS 제1115호 기준서 본문 및 적용지침\n"
            "- 회계기준원·금융감독원 공식 질의회신\n"
            "- 금융감독원 감리지적사례\n\n"
            "**주의**\n\n"
            "전문가적 판단이 개입되어야 하는 "
            "복잡한 사안에 대해서는 확정적 **결론**을 내리지 못할 수 있습니다. "
            "본 답변은 실무 검토를 위한 **참고 목적**으로만 활용해 주세요."
        )

        st.html(
            "<div style='position: fixed; bottom: 16px; font-size: 0.75em; "
            "color: #94A3B8; letter-spacing: 0.01em;'>"
            "PydanticAI · o4-mini · Hybrid Search ·<br>Cohere Reranker"
            "</div>"
        )

# app/ui/layout.py
# CSS 주입, 헤더, 사이드바 렌더링.
#
# _inject_css:      Streamlit 기본 UI를 덮어쓰는 커스텀 CSS 주입
# _render_header:   서비스 타이틀과 설명 중앙 정렬
# _render_sidebar:  일러두기, 아키텍처 정보, 홈 복귀 버튼

import streamlit as st

from app.ui.session import _go_home


def _inject_css() -> None:
    """Streamlit 기본 UI를 덮어쓰는 커스텀 CSS를 주입합니다.

    st.html()을 사용하는 이유:
      순수 HTML/CSS만 주입할 때는 st.markdown(unsafe_allow_html=True) 보다
      st.html()이 더 명시적이고 안전합니다 (frontend-streamlit 가이드 §3).
    """
    st.html(
        """<style>
        /* 기본 메뉴/푸터 숨김 — 포트폴리오용 클린 레이아웃 (header는 사이드바 토글 버튼을 위해 유지) */
        #MainMenu, footer { visibility: hidden; }
        header[data-testid="stHeader"] { background: transparent !important; }
        .block-container { padding-top: 2rem; padding-bottom: 2rem; }

        /* 키워드 칩 + 일반 버튼 스타일 */
        .stButton > button {
            background: #F8FAFF !important;
            border: 1px solid #DBEAFE !important;
            border-radius: 12px;
            color: #1E3A8A;
            padding: 0.6rem 1rem;
            text-align: left;
            transition: all 0.2s;
            outline: none !important;
            box-shadow: none !important;
        }
        .stButton > button[kind="primary"] {
            background: #EFF6FF !important;
            border-color: #3B82F6 !important;
            color: #1E3A8A !important;
            box-shadow: 0 0 0 1px #3B82F6 !important;
            font-weight: 600;
        }
        /* rerun 시 focus/active 상태가 여러 버튼에 잔류하는 것을 방지 */
        .stButton > button:focus:not(:hover),
        .stButton > button:active:not(:hover) {
            background: #F8FAFF !important;
            border-color: #DBEAFE !important;
            box-shadow: none !important;
        }

        /* 꼬리 질문 버튼은 조금 더 강조 */
        .stButton > button[data-testid*="followup"] {
            background: #FFFBEB !important;
            border-color: #FCD34D !important;
            color: #92400E;
        }

        /* ── 카드형 expander 스타일 ─────────────────────────────────── */
        div[data-testid="stExpander"] {
            border: 1px solid #E5E7EB !important;
            border-radius: 12px !important;
            margin-bottom: 0.75rem !important;
            overflow: hidden;
            box-shadow: 0 1px 4px rgba(0,0,0,0.04);
            transition: box-shadow 0.2s;
        }
        div[data-testid="stExpander"]:hover {
            box-shadow: 0 3px 10px rgba(0,0,0,0.08) !important;
        }
        .doc-body {
            padding: 0.25rem 0;
        }
        .doc-body p.doc-para {
            line-height: 1.85;
            margin-bottom: 0.85rem;
            color: #1F2937;
            font-size: 0.95em;
        }

        /* ── 문단 참조 하이퍼링크 ───────────────────────────────────── */
        a.para-link-found {
            color: #2563EB;
            text-decoration: underline;
            text-underline-offset: 2px;
            font-weight: 500;
            cursor: pointer;
            transition: color 0.15s;
        }
        a.para-link-found:hover { color: #1D4ED8; }
        a.para-link-ext {
            color: #9CA3AF;
            text-decoration: underline dotted;
            text-underline-offset: 2px;
            cursor: default;
        }

        /* ── 관련 조항 퀵뷰 칩 ─────────────────────────────────────── */
        .quick-chips-row {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 0.4rem;
            margin: 0.6rem 0 0.2rem;
        }
        .chips-label {
            font-size: 0.75em;
            font-weight: 600;
            color: #6B7280;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-right: 0.25rem;
        }
        a.quick-chip.found {
            display: inline-block;
            background: #EFF6FF;
            color: #2563EB;
            border: 1px solid #BFDBFE;
            border-radius: 999px;
            padding: 0.2rem 0.65rem;
            font-size: 0.8em;
            font-weight: 500;
            text-decoration: none;
            cursor: pointer;
            transition: background 0.15s;
        }
        a.quick-chip.found:hover { background: #DBEAFE; }
        span.quick-chip.missing {
            display: inline-block;
            background: #F9FAFB;
            color: #9CA3AF;
            border: 1px solid #E5E7EB;
            border-radius: 999px;
            padding: 0.2rem 0.65rem;
            font-size: 0.8em;
        }

        /* ── 출처 푸터 회색 박스 ────────────────────────────────────── */
        .source-footer {
            background: #F9FAFB;
            border: 1px solid #E5E7EB;
            border-radius: 8px;
            padding: 0.45rem 0.8rem;
            font-size: 0.82em;
            color: #6B7280;
            margin-top: 0.5rem;
        }
    </style>"""
    )


def _render_header() -> None:
    """서비스 타이틀과 설명을 중앙 정렬로 렌더링합니다."""
    st.html(
        """
        <div style='text-align: center; padding-top: 20px; padding-bottom: 10px;'>
            <h1 style='font-size: 2.2em; font-weight: 800; margin-bottom: 0px;'>
                📊 K-IFRS 1115 분석 도구
            </h1>
            <p style='font-size: 1.0em; color: #6B7280; font-weight: 500; margin-top: 5px;'>
                기준서 본문 · 질의회신 · 감리사례를 직접 열람하고 AI에게 해석을 물어보세요
            </p>
        </div>
        <hr style='margin-top: 0px; margin-bottom: 20px; border-top: 1px solid #E5E7EB;'>
    """
    )


def _render_sidebar() -> None:
    """사이드바 — 일러두기, 아키텍처 정보, 홈 복귀 버튼을 렌더링합니다."""
    with st.sidebar:
        # 어떤 page_state에 있든 무조건 타이틀이 렌더링되도록 강제 (Empty 방지)
        st.title("K-IFRS Chatbot")
        st.caption("기업회계기준서 제1115호  \n고객과의 계약에서 생기는 수익")

        if st.button("🏠 처음으로 돌아가기", use_container_width=True):
            _go_home()

        st.divider()
        st.markdown(
            "#### ⚠️ 일러두기\n\n"
            "본 도구는 다음의 데이터베이스를 바탕으로 **사실(Fact) 기반**의 **원칙적인 답변**을 제공합니다.\n\n"
            "- 🔹 K-IFRS 제1115호 기준서 본문 및 적용지침\n"
            "- 🔹 회계기준원 및 금융감독원 공식 질의회신\n"
            "- 🔹 금융감독원 등 감리지적사례\n\n"
            "---\n\n"
            "#### ❗주의할점\n\n"
            "**전문가적 판단(Professional Judgment)** 이 개입되어야 하는 실무 상황이나, "
            "**이견이 존재**하는 **복잡한 사안**에 대해서는 확정적인 단일 결론을 내리지 못할 수 있습니다.\n\n"
            "따라서 본 답변은 실무 검토를 위한 **참고 목적**으로만 활용해 주시기 바랍니다."
        )
        st.divider()
        st.markdown("#### ⚙️ System Architecture")
        st.html(
            """
        <div style='font-size: 0.9em; color: #4B5563;'>
        <b>[Tech Stack]</b><br>
        • <b>Core:</b> LangGraph 기반 다중 노드 라우팅<br>
        • <b>LLM:</b> o4-mini (복잡한 회계 논리 추론)<br>
        • <b>Search:</b> Hybrid Search (Vector + Keyword)<br>
        • <b>Reranker:</b> Cohere multilingual-v3<br>
        </div>
        """
        )

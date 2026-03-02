# app/streamlit_app.py
# K-IFRS 1115 챗봇 Streamlit UI
#
# 구조:
#   사이드바 — 서비스 소개, 예시 질문, 면책 안내
#   메인     — 대화 히스토리, 실시간 진행 상태, 입력창
#
# SSE 수신 방식: httpx.Client(동기) 사용
#   Streamlit은 동기 실행 환경이므로 asyncio 없이 httpx 동기 클라이언트로 SSE를 처리합니다.
#   이 방식이 st.write_stream()보다 안정적으로 이벤트 타입별 분기를 처리합니다.
import json
import os
import time

import httpx
import streamlit as st

# ── 상수 ────────────────────────────────────────────────────────────────────────
# Docker 환경: compose에서 API_BASE_URL=http://api:8002 주입
# 로컬 환경: 환경변수 미설정 시 localhost 폴백
API_URL = os.getenv("API_BASE_URL", "http://localhost:8002") + "/chat"
API_TIMEOUT = 120  # 초 (RAG 파이프라인 최대 응답 시간 고려)

# 각 RAG 노드의 진행률 (%)
# analyze → retrieve → rerank → grade → [rewrite] → generate → format 순서
_STEP_PROGRESS = {
    "analyze":  15,
    "retrieve": 35,
    "rerank":   55,
    "grade":    70,
    "rewrite":  75,  # 재검색 시에만 실행
    "generate": 85,
    "format":   95,
}


# ── 세션 상태 초기화 ─────────────────────────────────────────────────────────────

def _init_session():
    """세션 상태 초기값을 설정합니다. 앱 최초 실행 시에만 실행됩니다."""
    defaults = {
        "session_id": None,        # FastAPI 서버가 발급한 세션 ID
        "messages": [],            # [{"role": "user"|"ai", "content": str, "cited_sources": list}]
        "pending_input": None,     # 예시 질문 클릭 시 입력창에 자동 채울 텍스트
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ── SSE 스트림 처리 ───────────────────────────────────────────────────────────────

def _stream_and_render(user_message: str):
    """FastAPI SSE를 수신하고, 답변을 단어 단위로 순차 출력합니다."""

    with st.chat_message("assistant"):
        answer_placeholder = st.empty()
        answer_text = ""
        cited_sources = []
        findings_case = None

        # RAG 파이프라인 실행 — done 이벤트까지 대기
        # status/token 이벤트는 무시하고 최종 done만 사용합니다.
        try:
            with httpx.Client(timeout=API_TIMEOUT) as client:
                with client.stream(
                    "POST",
                    API_URL,
                    json={
                        "session_id": st.session_state.session_id,
                        "message": user_message,
                    },
                ) as response:
                    answer_placeholder.markdown("생각하는 중... (0%) ▌")

                    for line in response.iter_lines():
                        if not line.startswith("data:"):
                            continue

                        event = json.loads(line[5:].strip())
                        event_type = event.get("type")

                        if event_type == "status":
                            # 노드 진행 상태 수신 → 진행률 업데이트
                            step = event.get("step", "")
                            step_msg = event.get("message", "처리 중...")
                            pct = _STEP_PROGRESS.get(step, 0)
                            answer_placeholder.markdown(
                                f"생각하는 중... ({pct}%) — {step_msg} ▌"
                            )

                        elif event_type == "done":
                            answer_text = event.get("text", "")
                            cited_sources = event.get("cited_sources") or []
                            findings_case = event.get("findings_case")
                            st.session_state.session_id = event.get("session_id")

                        elif event_type == "error":
                            st.error(f"오류: {event.get('message', '알 수 없는 오류')}")
                            return

        except httpx.TimeoutException:
            st.error("응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.")
            return
        except httpx.ConnectError:
            st.error("서버에 연결할 수 없습니다. FastAPI 서버가 실행 중인지 확인하세요.")
            return

        # 답변을 단어 단위로 순차 출력 (타이핑 효과)
        # 마크다운 구조(줄바꿈, 헤더 등)를 유지하기 위해 줄 단위로 분리 후 단어 단위 출력합니다.
        displayed = ""
        for word in answer_text.split(" "):
            displayed += word + " "
            answer_placeholder.markdown(displayed + "▌")
            time.sleep(0.025)
        answer_placeholder.markdown(answer_text)

        # 감리사례 expander (넛지 텍스트의 "클릭하여 확인해보세요" 대상)
        if findings_case:
            case_title = findings_case.get("title", "감리지적사례")
            with st.expander(f"📋 금융감독원 지적사례: {case_title}", expanded=False):
                raw_content = findings_case.get("content", "내용을 불러올 수 없습니다.")
                adjusted_content = raw_content.replace("# ", "### ").replace("## ", "#### ")
                st.markdown(adjusted_content)

        # 출처 정보 expander
        if cited_sources:
            with st.expander("📌 참고 근거 보기", expanded=False):
                for src in cited_sources:
                    source_type = src.get("source", "알 수 없음")
                    hierarchy = src.get("hierarchy", "출처 정보 없음")
                    paragraphs = src.get("related_paragraphs", [])
                    p_str = f" | 관련 문단: {', '.join(paragraphs)}" if paragraphs else ""
                    st.caption(f"**[{source_type}]** {hierarchy}{p_str}")

    # 대화 히스토리에 저장 (다음 렌더링 시 표시용)
    st.session_state.messages.append({
        "role": "ai",
        "content": answer_text,
        "cited_sources": cited_sources,
        "findings_case": findings_case,
    })


# ── 대화 히스토리 렌더링 ──────────────────────────────────────────────────────────

def _render_history():
    """저장된 대화 히스토리를 화면에 표시합니다."""
    for msg in st.session_state.messages:
        role = msg["role"]
        with st.chat_message("user" if role == "user" else "assistant"):
            st.markdown(msg["content"])
            # AI 메시지에만 출처 + 감리사례 expander 표시
            if role == "ai" and msg.get("cited_sources"):
                with st.expander("📌 참고 근거 보기", expanded=False):
                    for src in msg["cited_sources"]:
                        source_type = src.get("source", "알 수 없음")
                        hierarchy = src.get("hierarchy", "출처 정보 없음")
                        paragraphs = src.get("related_paragraphs", [])
                        p_str = f" | 관련 문단: {', '.join(paragraphs)}" if paragraphs else ""
                        st.caption(f"**[{source_type}]** {hierarchy}{p_str}")
            if role == "ai" and msg.get("findings_case"):
                fc = msg["findings_case"]
                case_title = fc.get("title", "감리지적사례")
                with st.expander(f"📋 금융감독원 지적사례: {case_title}", expanded=False):
                    st.markdown(fc.get("content", "내용을 불러올 수 없습니다."))


# ── CSS 주입 ──────────────────────────────────────────────────────────────────

def _inject_css():
    """Streamlit 기본 UI를 덮어쓰는 커스텀 CSS를 주입합니다."""
    st.markdown("""<style>
        /* 기본 헤더/메뉴/푸터 숨김 — 포트폴리오용 클린 레이아웃 */
        #MainMenu, header, footer { visibility: hidden; }
        .block-container { padding-top: 2rem; padding-bottom: 2rem; }

        /* 예시 질문 카드 버튼 스타일 */
        .stButton > button {
            background: #F8FAFF;
            border: 1px solid #DBEAFE;
            border-radius: 12px;
            color: #1E3A8A;
            padding: 0.6rem 1rem;
            text-align: left;
            transition: all 0.2s;
        }
        .stButton > button:hover {
            background: #EFF6FF;
            border-color: #3B82F6;
        }
    </style>""", unsafe_allow_html=True)


# ── 헤더 렌더링 ────────────────────────────────────────────────────────────────

def _render_header():
    """서비스 타이틀과 설명을 중앙 정렬로 렌더링합니다."""
    st.markdown("""
        <div style='text-align: center; padding-top: 20px; padding-bottom: 20px;'>
            <h1 style= font-size: 2.8em; font-weight: 800; margin-bottom: 0px;'>
                💬 K-IFRS Chatbot
            </h1>
            <p style='font-size: 1.1em; color: #6B7280; font-weight: 500; margin-top: 5px;'>
                기업회계기준서 제1115호 전문 AI 챗봇
            </p>
        </div>
        <hr style='margin-top: 0px; margin-bottom: 30px; border-top: 1px solid #E5E7EB;'>
    """, unsafe_allow_html=True)


# ── 환영 화면 ─────────────────────────────────────────────────────────────────

def _render_welcome():
    """대화 히스토리가 비어있을 때 표시하는 안내 화면입니다."""
    st.markdown("""
        <div style='text-align:; padding: 3rem 1rem;'>
            <p style='font-size: 1.4em; font-weight: 600; margin-bottom: 0.5rem;'>
                질문을 입력해 주세요.
            </p>
            <p style='font-size: 1.0em; color: #6B7280;'>
                💡 분석 정밀도 향상을 위한 팁<BR>
                - 기준서 특성 상 계약의 세부 조항에 따라 결론이 달라질 수 있습니다.<BR>
                - 정확한 분석을 위해 의무와 권리대상, 대가 수취 방식, 위험과 보상의 이전 시점 등 구체적인 사실관계를 포함해주세요.<BR> - 입력 정보가 상세할수록 기준서 최적 매칭 확률이 높아집니다.
            </p>
        </div>
    """, unsafe_allow_html=True)


# ── 사이드바 ────────────────────────────────────────────────────────────────────

st.set_page_config(initial_sidebar_state="expanded")

def _render_sidebar():
    with st.sidebar:
            # 포트폴리오용 프로젝트 타이틀
            st.markdown("# K-IFRS Chatbot # 1")
            st.caption("기업회계기준서 제1115호  \n고객과의 계약에서 생기는 수익")
            
            # 대화 초기화 버튼 (눈에 띄게 primary 컬러 적용)
            if st.button("✨ 새로운 질문 시작", use_container_width=True):
                st.session_state.messages = []
                st.rerun()

            st.divider()
            st.markdown(
            "#### ⚠️ 일러두기\n\n"
            "본 챗봇은 다음의 데이터베이스를 바탕으로 **사실(Fact) 기반**의 **원칙적인 답변**을 제공합니다.\n\n"
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
            st.markdown("""
            <div style='font-size: 0.9em; color: #4B5563;'>
            본 시스템은 수익 인식 관련 실무적 판단을 보조하기 위해 구축된 <b>하이브리드 RAG 파이프라인</b>입니다.
            <br><br>
            <b>[Tech Stack]</b><br>
            • <b>Core:</b> LangGraph 기반 다중 노드 라우팅<br>
            • <b>LLM:</b> o4-mini (복잡한 회계 논리 추론)<br>
            • <b>Search:</b> Hybrid Search (Vector + Keyword)<br>
            </div>
            """, unsafe_allow_html=True)

# ── 메인 ────────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="K-IFRS 1115 챗봇",
        layout="centered",
    )

    _inject_css()
    _init_session()
    _render_sidebar()
    _render_header()

    # 대화 히스토리 렌더링
    _render_history()

    # 히스토리가 없으면 환영 안내 표시
    if not st.session_state.messages:
        _render_welcome()

    # 예시 질문 클릭으로 채워진 pending_input 처리
    default_value = st.session_state.pop("pending_input", None) or ""

    # 사용자 입력창
    user_input = st.chat_input(
        "K-IFRS 1115에 대해 질문하세요...",
    )

    # pending_input이 있으면 직접 처리합니다.
    question = user_input or default_value
    if not question:
        return

    # 사용자 메시지 즉시 표시
    st.session_state.messages.append({
        "role": "user",
        "content": question,
        "cited_sources": [],
    })
    with st.chat_message("user"):
        st.markdown(question)

    # RAG 파이프라인 실행 및 응답 스트리밍
    _stream_and_render(question)


if __name__ == "__main__":
    main()

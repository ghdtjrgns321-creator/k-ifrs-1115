# app/ui/client.py
# FastAPI 백엔드 통신 함수.
#
# _call_search: /search POST → evidence 페이지로 전환
# _call_chat:   /chat SSE 스트리밍 → ai_answer 페이지로 전환
#
# 공통 원칙: 예외 발생 시 page_state를 변경하지 않아 현재 화면을 유지합니다.

import json

import httpx
import streamlit as st

from app.ui.constants import (
    API_TIMEOUT,
    CHAT_URL,
    SEARCH_URL,
    _STEP_LABELS,
    _STEP_PROGRESS,
)


def _call_search(query: str) -> None:
    """/search API를 호출하고 evidence 화면으로 전환합니다."""
    if not query.strip():
        return

    with st.spinner("관련 조항을 검색하고 있어요..."):
        try:
            resp = httpx.post(
                SEARCH_URL,
                json={
                    "query": query,
                    "session_id": st.session_state.session_id,
                },
                timeout=API_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            st.session_state.search_query = query
            st.session_state.standalone_query = data.get("standalone_query", query)
            st.session_state.search_id = data.get("search_id")
            st.session_state.evidence_docs = data.get("docs", [])
            st.session_state.page_state = "evidence"
            st.rerun()

        except httpx.ConnectError:
            st.error("서버에 연결할 수 없습니다. FastAPI 서버가 실행 중인지 확인하세요.")
        except Exception as e:
            st.error(f"검색 중 오류가 발생했습니다: {e}")


def _call_chat(question: str, use_cache: bool = False) -> None:
    """/chat SSE API를 호출하고 ai_answer 화면으로 전환합니다.

    use_cache=True  → 꼬리질문 버튼 클릭 — 기존 search_id를 전달해 retrieve 단계를 스킵합니다.
    use_cache=False → 자유 입력창 제출 — search_id를 None으로 전달해 새 검색을 수행합니다.

    스트리밍이 성공적으로 완료된 후에만 page_state를 ai_answer로 변경합니다.
    """
    if not question.strip():
        return

    # 꼬리질문 클릭이면 기존 search_id 재사용, 자유 입력이면 새 검색 (None)
    search_id = st.session_state.get("search_id") if use_cache else None

    # 질문은 미리 저장합니다 (스트리밍 중 progress 메시지에 사용).
    st.session_state.ai_question = question

    answer_text = ""
    cited_sources = []
    findings_case = None
    follow_up_questions = []

    # 단계별 진행 표시 — 스피너가 계속 돌면서 현재 단계를 알려줍니다
    with st.status("AI가 분석을 시작합니다...", expanded=False) as status:
        try:
            with httpx.Client(timeout=API_TIMEOUT) as client:
                with client.stream(
                    "POST",
                    CHAT_URL,
                    json={
                        "session_id": st.session_state.session_id,
                        "message": question,
                        "search_id": search_id,
                    },
                ) as response:
                    for line in response.iter_lines():
                        if not line.startswith("data:"):
                            continue

                        event = json.loads(line[5:].strip())
                        event_type = event.get("type")

                        if event_type == "status":
                            step = event.get("step", "")
                            label = _STEP_LABELS.get(step, event.get("message", "처리 중..."))
                            pct = _STEP_PROGRESS.get(step, 0)
                            status.update(label=f"{label} ({pct}%)")

                        elif event_type == "done":
                            answer_text = event.get("text", "")
                            cited_sources = event.get("cited_sources") or []
                            findings_case = event.get("findings_case")
                            follow_up_questions = event.get("follow_up_questions") or []
                            st.session_state.session_id = event.get("session_id")
                            st.session_state.is_situation = event.get("is_situation", False)
                            # 자유 입력 시에도 좌측 근거 패널을 채웁니다
                            new_docs = event.get("retrieved_docs") or []
                            if new_docs:
                                st.session_state.evidence_docs = new_docs

                        elif event_type == "error":
                            status.update(label="오류가 발생했습니다", state="error")
                            st.error(f"오류: {event.get('message', '알 수 없는 오류')}")
                            return  # page_state 변경 없이 현재 화면 유지

            # done 이벤트를 받지 못한 경우 (서버 조기 종료 등)
            if not answer_text:
                status.update(label="답변 수신 실패", state="error")
                st.error("답변을 받지 못했습니다. 다시 시도해주세요.")
                return

            status.update(label="분석 완료!", state="complete", expanded=False)

        except httpx.HTTPStatusError as e:
            status.update(label="서버 오류", state="error")
            st.error(f"서버 오류 ({e.response.status_code}): 잠시 후 다시 시도해주세요.")
            return
        except httpx.TimeoutException:
            status.update(label="응답 시간 초과", state="error")
            st.error("응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.")
            return
        except httpx.ConnectError:
            status.update(label="서버 연결 실패", state="error")
            st.error("서버에 연결할 수 없습니다. FastAPI 서버가 실행 중인지 확인하세요.")
            return

    # 스트리밍 성공 후에만 ai_answer 화면으로 전환합니다.
    st.session_state.ai_answer = answer_text
    st.session_state.cited_sources = cited_sources
    st.session_state.findings_case = findings_case
    st.session_state.follow_up_questions = follow_up_questions
    st.session_state.page_state = "ai_answer"
    st.rerun()

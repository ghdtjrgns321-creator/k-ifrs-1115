# app/services/chat_service.py
# 순수 Python 파이프라인 실행 + SSE 이벤트 생성
#
# LangGraph의 astream_events를 pipeline.py의 async generator로 대체합니다.
# 멀티턴 체크리스트 상태를 로드/저장하여 꼬리질문 품질을 개선합니다.
from typing import AsyncGenerator

import time

from app.api.schemas import SSEEvent
from app.pipeline import run_rag_pipeline
from app.services.session_store import SessionStore
from app.services.usage_logger import log_chat_response


def _build_initial_state(
    session_id: str,
    prev_messages: list[tuple],
    new_message: str,
    pre_retrieved_docs: list[dict] | None = None,
    checklist_state: dict | None = None,
    cached_relevant_docs: list[dict] | None = None,
) -> dict:
    """파이프라인 실행용 초기 상태를 구성합니다.

    멀티턴 핵심 규칙:
      - messages: 이전 대화 히스토리 + 새 질문 누적
      - retrieved/reranked/relevant_docs: 매 턴 반드시 [] 초기화
      - checklist_state: 세션에서 로드하여 주입 (후속 턴 추적용)
      - pre_retrieved_docs: 후속 턴에서 cached_relevant_docs가 있으면 주입
    """
    # 후속 턴에서 cached_relevant_docs가 있으면 pre_retrieved_docs로 주입
    # → retrieve/rerank 스킵하고 바로 grade로 점프
    effective_pre = pre_retrieved_docs
    if effective_pre is None and cached_relevant_docs is not None:
        effective_pre = cached_relevant_docs

    # fast-path 진입 조건: 체크리스트 + 캐시 문서가 모두 있는 후속 턴
    # Why: analyze(~2초) 스킵 — checklist_state에 matched_topics가 이미 있고,
    # cached_relevant_docs로 retrieve/rerank도 불필요
    is_followup = checklist_state is not None and cached_relevant_docs is not None

    state = {
        "session_id": session_id,
        "messages": prev_messages + [("human", new_message)],
        "routing": "IN" if is_followup else "",  # fast-path는 라우팅 검증 스킵
        "standalone_query": "",
        "retry_count": 0,
        "retrieved_docs": [],
        "reranked_docs": [],
        "relevant_docs": cached_relevant_docs if is_followup else [],
        "answer": "",
        "cited_sources": [],
        "findings_case": None,
        "follow_up_questions": [],
        "pre_retrieved_docs": effective_pre,
        "is_situation": True if is_followup else False,
        "search_keywords": [],
        "matched_topics": checklist_state.get("matched_topics", []) if is_followup else [],
        "checklist_state": checklist_state,
        "is_clarify_followup": is_followup,
        # needs_calculation: 첫 턴에서 저장한 값 복원 (fast-path에서 리셋 방지)
        # Why: B1/B2 — fast-path 후속 턴에서 analyze 스킵 시 False로 리셋되는 문제 해결
        "needs_calculation": (checklist_state or {}).get("needs_calculation", False),
    }
    return state


async def run_graph_stream(
    session_id: str,
    message: str,
    store: SessionStore,
    search_id: str | None = None,
) -> AsyncGenerator[SSEEvent, None]:
    """RAG 파이프라인을 실행하며 SSE 이벤트를 yield합니다.

    흐름:
      1. search_id가 있으면 캐시에서 docs 로드
      2. 세션 히스토리 + 체크리스트 상태 로드 → 초기 상태 구성
      3. run_rag_pipeline() async generator에서 SSE 이벤트 수신
      4. 세션 히스토리 + 체크리스트 상태 업데이트
    """
    # 응답 시간 측정 시작
    _start_time = time.perf_counter()

    # 1. 이전 /search 결과 로드
    pre_retrieved_docs: list[dict] | None = None
    if search_id:
        pre_retrieved_docs = store.get_search(session_id, search_id)

    # 2. 세션 상태 로드
    prev_messages = store.get_messages(session_id)
    checklist_state = store.get_checklist_state(session_id)
    cached_docs = store.get_cached_docs(session_id)

    initial_state = _build_initial_state(
        session_id=session_id,
        prev_messages=prev_messages,
        new_message=message,
        pre_retrieved_docs=pre_retrieved_docs,
        checklist_state=checklist_state,
        cached_relevant_docs=cached_docs,
    )

    final_state = initial_state

    try:
        async for event in run_rag_pipeline(initial_state):
            # done 이벤트: 로그 저장 후 log_id를 주입하여 yield
            # Why: yield 이후에는 이벤트 수정이 클라이언트에 반영되지 않음
            if event.type == "done":
                final_state = initial_state  # state가 in-place 업데이트됨
                elapsed_ms = int((time.perf_counter() - _start_time) * 1000)
                topics = [
                    t["topic_name"]
                    for t in final_state.get("matched_topics", [])
                    if t.get("topic_name")
                ]
                log_id = log_chat_response(
                    session_id=session_id,
                    question=message,
                    answer=final_state.get("answer", ""),
                    matched_topics=topics,
                    search_keywords=final_state.get("search_keywords"),
                    cited_paragraphs=final_state.get("cited_paragraphs"),
                    is_situation=final_state.get("is_situation", False),
                    needs_calculation=final_state.get("needs_calculation", False),
                    is_conclusion=final_state.get("is_conclusion", False),
                    selected_branches=final_state.get("selected_branches"),
                    response_time_ms=elapsed_ms,
                )
                if log_id:
                    event.log_id = log_id

            yield event

    except TimeoutError:
        yield SSEEvent(
            type="error",
            message="죄송합니다, 답변 생성에 시간이 너무 오래 걸렸어요. 다시 한번 시도해 주시겠어요?",
        )
        return
    except Exception as exc:
        yield SSEEvent(type="error", message=f"처리 중 오류가 발생했습니다: {exc}")
        return

    # 3. 세션 업데이트
    final_answer = final_state.get("answer", "")
    store.append_turn(session_id, message, final_answer)

    # 4. 멀티턴 체크리스트 상태 업데이트
    is_situation = final_state.get("is_situation", False)
    matched_topics = final_state.get("matched_topics", [])

    if is_situation and matched_topics:
        # 첫 턴: 체크리스트 초기화 + 검색 결과 캐시
        if checklist_state is None:
            new_state = {
                "matched_topics": matched_topics,
                "checked_items": [],
                "turn_count": 1,
                "concluded": False,
                # needs_calculation 영속화 — 후속 턴에서 calc 라우팅 유지
                "needs_calculation": final_state.get("needs_calculation", False),
            }
            # 첫 턴에서 바로 결론이 나온 경우 (정보 충분 시)
            if final_state.get("is_conclusion", False):
                new_state["concluded"] = True
            store.set_checklist_state(session_id, new_state)
            # 첫 턴의 relevant_docs를 캐시하여 후속 턴에서 재사용
            relevant_docs = final_state.get("relevant_docs", [])
            if relevant_docs:
                store.set_cached_docs(session_id, relevant_docs)
        else:
            # 후속 턴: turn_count 증가 + 사용자 답변을 Q&A 쌍으로 기록
            checklist_state["turn_count"] = checklist_state.get("turn_count", 0) + 1
            # 이전 턴에서 결론이 나왔으면 concluded 플래그 유지
            # Why: C2처럼 결론 후 불필요 질문 생성 방지
            if final_state.get("is_conclusion", False):
                checklist_state["concluded"] = True
            # 직전 AI 질문을 추출하여 Q&A 쌍으로 저장 → clarify_agent가 중복 질문 방지
            last_ai_question = ""
            for role, content in reversed(prev_messages):
                if role == "ai":
                    last_ai_question = content[:300]
                    break
            checklist_state.setdefault("checked_items", []).append(
                {
                    "question": last_ai_question,
                    "answer": message,
                }
            )
            store.set_checklist_state(session_id, checklist_state)
    elif not is_situation and checklist_state is not None:
        # 최종 답변 전환: 체크리스트 상태 클리어
        store.set_checklist_state(session_id, None)
        store.set_cached_docs(session_id, None)

# app/services/chat_service.py
# 순수 Python 파이프라인 실행 + SSE 이벤트 생성
#
# LangGraph의 astream_events를 pipeline.py의 async generator로 대체합니다.
# 멀티턴 체크리스트 상태를 로드/저장하여 꼬리질문 품질을 개선합니다.
from typing import AsyncGenerator

from app.api.schemas import SSEEvent
from app.pipeline import run_rag_pipeline
from app.services.session_store import SessionStore


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

    return {
        "session_id": session_id,
        "messages": prev_messages + [("human", new_message)],
        "routing": "",
        "standalone_query": "",
        "retry_count": 0,
        "retrieved_docs": [],
        "reranked_docs": [],
        "relevant_docs": [],
        "answer": "",
        "cited_sources": [],
        "findings_case": None,
        "follow_up_questions": [],
        "pre_retrieved_docs": effective_pre,
        "is_situation": False,
        "search_keywords": [],
        "matched_topics": [],
        "checklist_state": checklist_state,
    }


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
            yield event

            # done 이벤트에서 최종 상태 캡처
            if event.type == "done":
                final_state = initial_state  # state가 in-place 업데이트됨

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
            store.set_checklist_state(session_id, {
                "matched_topics": matched_topics,
                "checked_items": [],
                "turn_count": 1,
            })
            # 첫 턴의 relevant_docs를 캐시하여 후속 턴에서 재사용
            relevant_docs = final_state.get("relevant_docs", [])
            if relevant_docs:
                store.set_cached_docs(session_id, relevant_docs)
        else:
            # 후속 턴: turn_count 증가 + 사용자 답변을 Q&A 쌍으로 기록
            checklist_state["turn_count"] = checklist_state.get("turn_count", 0) + 1
            # 직전 AI 질문을 추출하여 Q&A 쌍으로 저장 → clarify_agent가 중복 질문 방지
            last_ai_question = ""
            for role, content in reversed(prev_messages):
                if role == "ai":
                    last_ai_question = content[:300]
                    break
            checklist_state.setdefault("checked_items", []).append({
                "question": last_ai_question,
                "answer": message,
            })
            store.set_checklist_state(session_id, checklist_state)
    elif not is_situation and checklist_state is not None:
        # 최종 답변 전환: 체크리스트 상태 클리어
        store.set_checklist_state(session_id, None)
        store.set_cached_docs(session_id, None)

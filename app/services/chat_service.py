# app/services/chat_service.py
# RAG 그래프 실행 + SSE 이벤트 생성 핵심 비즈니스 로직
#
# 스트리밍 전략:
#   astream_events(version="v2")를 사용해 노드 시작 시점마다 "status" SSE를 전송하고,
#   그래프 전체 완료 시 최종 state에서 answer + cited_sources를 추출해 "done" SSE 전송.
#   단일 astream_events 호출로 진행 상태 + 최종 결과를 모두 처리하므로 이중 실행 없음.
#
# search_id 패턴:
#   /search에서 미리 검색된 docs가 있으면 pre_retrieved_docs로 state에 주입합니다.
#   graph.py의 route_analyze가 pre_retrieved_docs를 감지해 retrieve/rerank를 스킵합니다.
from typing import AsyncGenerator

from app.api.schemas import SSEEvent
from app.graph import rag_graph
from app.services.search_service import _to_doc_result
from app.services.session_store import SessionStore

# LangGraph 노드 이름 → (SSE step ID, 한국어 진행 메시지) 매핑
# 노드 이름은 graph.py의 workflow.add_node() 첫 번째 인자와 정확히 일치해야 합니다.
_STEP_LABELS: dict[str, tuple[str, str]] = {
    "analyze_query":  ("analyze",  "질문을 분석하고 있어요..."),
    "retrieve":       ("retrieve", "관련 조항을 검색하고 있어요..."),
    "rerank":         ("rerank",   "관련성을 재평가하고 있어요..."),
    "grade_docs":     ("grade",    "답변 신뢰도를 검증하고 있어요..."),
    "rewrite_query":  ("rewrite",  "질문을 다시 정제하고 있어요..."),
    "generate":       ("generate", "답변을 생성하고 있어요..."),
    "format_response":("format",   "답변을 정리하고 있어요..."),
}


def _build_initial_state(
    prev_messages: list[tuple],
    new_message: str,
    pre_retrieved_docs: list[dict] | None = None,
) -> dict:
    """LangGraph 실행용 초기 상태를 구성합니다.

    멀티턴 핵심 규칙:
      - messages: 이전 대화 히스토리 + 새 질문 누적 (자동 reducer)
      - retrieved_docs / reranked_docs / relevant_docs: 매 턴 반드시 [] 초기화
        (이전 턴의 검색 결과가 남아있으면 grade 노드가 오동작합니다)

    pre_retrieved_docs:
      - /search에서 캐시된 docs를 주입하면 graph.py가 retrieve/rerank를 스킵합니다.
      - None이면 일반 retrieve 흐름을 실행합니다.
    """
    return {
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
        "pre_retrieved_docs": pre_retrieved_docs,
        "is_situation": False,
        "search_keywords": [],
    }


async def run_graph_stream(
    session_id: str,
    message: str,
    store: SessionStore,
    search_id: str | None = None,
) -> AsyncGenerator[SSEEvent, None]:
    """RAG 그래프를 실행하며 SSE 이벤트를 yield합니다.

    흐름:
      1. search_id가 있으면 캐시에서 docs 로드 → pre_retrieved_docs 주입
      2. 세션 히스토리 로드 → 초기 상태 구성
      3. astream_events로 노드 시작 이벤트 수신 → "status" SSE
      4. 그래프 완료 이벤트에서 최종 answer + cited_sources + follow_up_questions 추출 → "done" SSE
      5. 세션 히스토리 업데이트 (다음 턴 대비)
    """
    # 1. 이전 /search 결과 로드 (있으면 retrieve/rerank 스킵)
    pre_retrieved_docs: list[dict] | None = None
    if search_id:
        pre_retrieved_docs = store.get_search(session_id, search_id)

    prev_messages = store.get_messages(session_id)
    initial_state = _build_initial_state(prev_messages, message, pre_retrieved_docs)

    final_answer = ""
    cited_sources = []
    findings_case = None
    follow_up_questions: list[str] = []
    is_situation: bool = False
    retrieved_docs: list[dict] = []

    try:
        async for event in rag_graph.astream_events(initial_state, version="v2"):
            event_type = event["event"]
            node_name = event.get("name", "")

            # 노드 시작 이벤트 → 진행 상태 SSE 전송
            if event_type == "on_chain_start" and node_name in _STEP_LABELS:
                step_id, label = _STEP_LABELS[node_name]
                yield SSEEvent(type="status", step=step_id, message=label)

            # 그래프 전체 완료 이벤트 → 최종 결과 추출
            # LangGraph가 컴파일한 그래프의 기본 이름은 "LangGraph"입니다.
            if event_type == "on_chain_end" and node_name == "LangGraph":
                output = event["data"].get("output", {})
                final_answer = output.get("answer", "")
                cited_sources = output.get("cited_sources", [])
                findings_case = output.get("findings_case")
                follow_up_questions = output.get("follow_up_questions") or []
                is_situation = output.get("is_situation", False)
                # RAG가 찾은 근거 문서를 DocResult 형식으로 변환하여 프론트에 전달합니다.
                # 자유 입력(/chat 단독 호출) 시에도 좌측 근거 패널이 채워지게 하는 핵심 연결입니다.
                raw_docs = output.get("relevant_docs") or []
                retrieved_docs = [_to_doc_result(d).model_dump() for d in raw_docs]

    except Exception as exc:
        yield SSEEvent(type="error", message=f"처리 중 오류가 발생했습니다: {exc}")
        return

    # 대화 히스토리 저장 (다음 멀티턴 요청을 위해)
    store.append_turn(session_id, message, final_answer)

    yield SSEEvent(
        type="done",
        text=final_answer,
        session_id=session_id,
        cited_sources=cited_sources,
        findings_case=findings_case,
        follow_up_questions=follow_up_questions if follow_up_questions else None,
        is_situation=is_situation,
        retrieved_docs=retrieved_docs if retrieved_docs else None,
    )

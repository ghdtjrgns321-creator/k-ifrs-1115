# app/pipeline.py
# 순수 Python 오케스트레이션 — LangGraph StateGraph 대체
#
# async generator로 SSE 이벤트를 yield합니다.
# 각 노드 함수는 async def로, 부분 dict를 반환하여 state.update()로 병합합니다.
#
# 흐름:
#   analyze → retrieve → rerank → generate → format
import time
from typing import AsyncGenerator

from app.api.schemas import SSEEvent
from app.nodes.analyze import analyze_query
from app.nodes.retrieve import retrieve_docs
from app.nodes.rerank import rerank_docs
from app.nodes.generate import generate_answer
from app.nodes.format import format_response

# 범위 밖 질문 거절 메시지
_REJECT_MSG = "죄송합니다. 저는 K-IFRS 1115호(수익 인식)와 관련된 회계 및 감사 질문에만 답변할 수 있습니다."


async def run_rag_pipeline(state: dict) -> AsyncGenerator[SSEEvent, None]:
    """RAG 파이프라인을 실행하며 SSE 이벤트를 yield합니다.

    각 노드 함수가 반환하는 부분 dict로 state를 병합하는 단순한 구조입니다.
    """

    pipeline_start = time.perf_counter()

    # ── Fast-path: clarify 후속 턴 ──────────────────────────────────────────────
    # analyze/retrieve/rerank 전체 스킵 → clarify LLM 1회만 실행
    if state.get("is_clarify_followup"):
        yield SSEEvent(type="status", step="generate", message="답변을 생성하고 있어요... (시간이 조금 소요될 수 있습니다)")
        t0 = time.perf_counter()
        state.update(await generate_answer(state))
        print(f"[timing] generate(fast-path): {time.perf_counter() - t0:.1f}s")
        print(f"[timing] ── total: {time.perf_counter() - pipeline_start:.1f}s ──")
        yield _done_event(state)
        return

    # ── 1. Analyze ──────────────────────────────────────────────────────────────
    yield SSEEvent(type="status", step="analyze", message="질문을 분석하고 있어요...")
    t0 = time.perf_counter()
    state.update(await analyze_query(state))
    print(f"[timing] analyze: {time.perf_counter() - t0:.1f}s")

    if state.get("routing") != "IN":
        state["answer"] = _REJECT_MSG
        yield _done_event(state)
        return

    # ── 2. Retrieve + Rerank ────────────────────────────────────────────────────
    # pre_retrieved_docs가 있으면 retrieve/rerank 스킵 (search_id 패턴)
    if state.get("pre_retrieved_docs") is not None:
        state["reranked_docs"] = state["pre_retrieved_docs"]
    else:
        yield SSEEvent(type="status", step="retrieve", message="관련 조항을 검색하고 있어요...")
        t0 = time.perf_counter()
        state.update(await retrieve_docs(state))
        print(f"[timing] retrieve: {time.perf_counter() - t0:.1f}s")

        yield SSEEvent(type="status", step="rerank", message="관련성을 재평가하고 있어요...")
        t0 = time.perf_counter()
        state.update(await rerank_docs(state))
        print(f"[timing] rerank: {time.perf_counter() - t0:.1f}s")

    # ── 3. Reranker 결과를 그대로 사용 ──────────────────────────────────────────
    # Cohere rerank-multilingual-v3.0이 이미 문서 관련성을 평가하고
    # rerank_threshold(0.05) 미만을 제거하므로 grade LLM 호출은 불필요
    state["relevant_docs"] = state.get("reranked_docs", [])
    is_situation = state.get("is_situation", False)

    # ── 4. Generate ─────────────────────────────────────────────────────────────
    yield SSEEvent(type="status", step="generate", message="답변을 생성하고 있어요... (시간이 조금 소요될 수 있습니다)")
    t0 = time.perf_counter()
    state.update(await generate_answer(state))
    print(f"[timing] generate: {time.perf_counter() - t0:.1f}s")

    # ── 5. Format — clarify 경로에서는 스킵 (감리사례 넛지 불필요) ──────────────
    if not is_situation:
        yield SSEEvent(type="status", step="format", message="답변을 정리하고 있어요...")
        t0 = time.perf_counter()
        state.update(await format_response(state))
        print(f"[timing] format: {time.perf_counter() - t0:.1f}s")

    print(f"[timing] ── total: {time.perf_counter() - pipeline_start:.1f}s ──")
    yield _done_event(state)


def _done_event(state: dict) -> SSEEvent:
    """파이프라인 완료 SSE 이벤트를 생성합니다."""
    from app.services.search_service import _to_doc_result

    raw_docs = state.get("relevant_docs") or []
    retrieved_docs = [_to_doc_result(d).model_dump() for d in raw_docs] if raw_docs else None

    follow_up = state.get("follow_up_questions") or []

    # 매칭된 토픽 이름 추출 (핀포인트 패널용)
    matched = state.get("matched_topics", [])
    topic_keys = list(dict.fromkeys(
        t["topic_name"] for t in matched if t.get("topic_name")
    ))

    return SSEEvent(
        type="done",
        text=state.get("answer", ""),
        session_id=state.get("session_id"),
        cited_sources=state.get("cited_sources"),
        findings_case=state.get("findings_case"),
        follow_up_questions=follow_up if follow_up else None,
        is_situation=state.get("is_situation", False),
        retrieved_docs=retrieved_docs,
        matched_topic_keys=topic_keys if topic_keys else None,
        search_keywords=state.get("search_keywords") or None,
        is_conclusion=state.get("is_conclusion", False),
    )

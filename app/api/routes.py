# app/api/routes.py
# FastAPI 라우터 — /search (JSON), /chat (SSE 스트리밍), /health 엔드포인트 정의
#
# 새 UX 흐름:
#   POST /search → 근거 문서 목록 반환 (LLM 없는 빠른 검색)
#   POST /chat   → AI 답변 SSE 스트리밍 (search_id 있으면 검색 단계 스킵)
import asyncio
from functools import partial
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from pydantic import BaseModel

from app.api.schemas import ChatRequest, SearchRequest, SearchResponse, SSEEvent
from app.services.chat_service import run_graph_stream
from app.services.search_service import run_search
from app.services.session_store import SessionStore, store

router = APIRouter()


# FastAPI DI용 팩토리 — 테스트 시 mock store로 교체 가능합니다.
def get_store() -> SessionStore:
    return store


@router.post("/search", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    store: SessionStore = Depends(get_store),
):
    """K-IFRS 1115 근거 문서 검색 엔드포인트.

    LLM으로 쿼리를 정규화한 뒤 하이브리드 검색 + Reranker + CRAG를 실행합니다.
    결과는 search_id와 함께 반환되며, 이후 /chat에 search_id를 전달하면
    retrieve/rerank 단계를 건너뛰어 응답 속도가 빨라집니다.

    run_search는 LangChain sync 호출을 포함하는 동기 함수입니다.
    run_in_executor로 별도 스레드에서 실행해 event loop 블로킹을 방지합니다.
    """
    session_id = request.session_id or str(uuid4())
    try:
        # get_running_loop(): 현재 실행 중인 루프를 참조 (Python 3.10+ 권장)
        # get_event_loop()는 3.10+에서 DeprecationWarning 발생
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            partial(run_search, request.query, session_id, store),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/chat")
async def chat(
    request: ChatRequest,
    http_request: Request,
    store: SessionStore = Depends(get_store),
):
    """K-IFRS 1115 챗봇 메인 엔드포인트.

    SSE(text/event-stream)로 응답합니다:
      1. status 이벤트 — RAG 파이프라인 각 단계 진행 알림
      2. done 이벤트   — 최종 답변 + 출처 + 꼬리 질문 3개

    search_id가 있으면 캐시된 docs를 주입해 retrieve/rerank를 스킵합니다.
    """
    session_id = request.session_id or str(uuid4())

    async def event_generator():
        try:
            async for sse_event in run_graph_stream(
                session_id=session_id,
                message=request.message,
                store=store,
                search_id=request.search_id,
            ):
                # SSE 규격: "data: {JSON}\n\n"
                yield f"data: {sse_event.model_dump_json()}\n\n"

                # 클라이언트가 연결을 끊었으면 스트림을 종료합니다.
                if await http_request.is_disconnected():
                    break
        except Exception as exc:
            error_event = SSEEvent(type="error", message=str(exc))
            yield f"data: {error_event.model_dump_json()}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            # 브라우저 및 프록시가 응답을 버퍼링하지 않도록 설정합니다.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


class FeedbackRequest(BaseModel):
    log_id: str
    feedback: str  # "up" | "down"
    reason: str = ""  # 👎 사유 (선택)


@router.post("/feedback")
async def feedback(request: FeedbackRequest):
    """사용자 피드백(👍/👎 + 사유)을 usage_logs에 저장합니다."""
    from app.services.usage_logger import update_feedback

    ok = update_feedback(request.log_id, request.feedback, request.reason)
    if not ok:
        raise HTTPException(status_code=400, detail="피드백 저장 실패")
    return {"status": "ok"}


@router.get("/health")
async def health(store: SessionStore = Depends(get_store)) -> dict:
    """서버 상태 및 간단한 운영 지표를 반환합니다."""
    return {
        "status": "ok",
        "session_count": store.count(),
    }

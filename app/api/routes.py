# app/api/routes.py
# FastAPI 라우터 — /chat (SSE 스트리밍), /health 엔드포인트 정의
import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.schemas import ChatRequest, SSEEvent
from app.services.chat_service import run_graph_stream
from app.services.session_store import store

router = APIRouter()


@router.post("/chat")
async def chat(request: ChatRequest, http_request: Request):
    """K-IFRS 1115 챗봇 메인 엔드포인트.

    SSE(text/event-stream)로 응답합니다:
      1. status 이벤트 — RAG 파이프라인 각 단계 진행 알림
      2. done 이벤트   — 최종 답변 + 출처 메타데이터

    session_id를 처음 보내지 않으면 서버가 UUID를 발급하고
    done 이벤트에 session_id를 포함해 클라이언트에 전달합니다.
    이후 요청에 session_id를 포함하면 멀티턴 대화가 유지됩니다.
    """
    session_id = request.session_id or str(uuid4())

    async def event_generator():
        try:
            async for sse_event in run_graph_stream(session_id, request.message, store):
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


@router.get("/health")
async def health():
    """서버 상태 및 간단한 운영 지표를 반환합니다."""
    return {
        "status": "ok",
        "session_count": store.count(),
    }

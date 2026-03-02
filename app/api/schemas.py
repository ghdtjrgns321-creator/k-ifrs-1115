# app/api/schemas.py
# FastAPI 요청/응답 데이터 구조 정의
# SSE(Server-Sent Events) 스트리밍 이벤트 타입을 명확하게 분리해
# 클라이언트(Streamlit)가 이벤트 종류별로 다른 처리를 할 수 있습니다.
from typing import Literal
from pydantic import BaseModel


class ChatRequest(BaseModel):
    """챗 엔드포인트 요청 스키마."""
    # 세션 ID: 없으면 서버가 UUID를 신규 발급합니다.
    # 클라이언트는 첫 요청 이후 응답의 session_id를 저장해 멀티턴을 유지합니다.
    session_id: str | None = None
    message: str


class SSEEvent(BaseModel):
    """SSE로 전송하는 이벤트 단위.

    type별 의미:
      status  - 파이프라인 단계 진행 알림 (step + message 필드 사용)
      token   - 최종 답변 텍스트 청크 (text 필드 사용)
      done    - 처리 완료 (session_id + cited_sources 포함)
      error   - 오류 발생 (message 필드에 오류 내용)
    """
    type: Literal["status", "token", "done", "error"]
    step: str | None = None              # "analyze" | "retrieve" | ...
    message: str | None = None          # 진행 상태 메시지 또는 오류 내용
    text: str | None = None             # 최종 답변 텍스트 (done 이벤트)
    session_id: str | None = None       # done 이벤트에서 클라이언트가 저장할 세션 ID
    cited_sources: list[dict] | None = None  # done 이벤트의 출처 메타데이터
    findings_case: dict | None = None        # done 이벤트의 감리사례 ({title, hierarchy, content})

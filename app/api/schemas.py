# app/api/schemas.py
# FastAPI 요청/응답 데이터 구조 정의
#
# 새 UX 흐름: /search(근거 열람) → /chat(AI 답변) 두 단계 분리
#   - /search : LLM 없는 빠른 검색 → DocResult 목록 반환
#   - /chat   : SSE 스트리밍 → status/done/error 이벤트
from typing import Literal
from pydantic import BaseModel


# ── /chat 요청 ─────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """챗 엔드포인트 요청 스키마."""

    # 세션 ID: 없으면 서버가 UUID를 신규 발급합니다.
    session_id: str | None = None
    message: str
    # search_id가 있으면 /search 캐시에서 docs를 꺼내 retrieve/rerank 단계를 스킵합니다.
    search_id: str | None = None


# ── /search 요청/응답 ───────────────────────────────────────────────────────────


class SearchRequest(BaseModel):
    """검색 엔드포인트 요청 스키마."""

    query: str
    session_id: str | None = None


class DocResult(BaseModel):
    """검색 결과 단건 문서 스키마.

    근거 열람 화면에서 카테고리별 아코디언으로 표시됩니다.
    """

    source: str  # "본문", "적용지침B", "질의회신", "감리사례", ...
    hierarchy: str  # breadcrumb (예: "[문단 59] 변동대가")
    title: str = (
        ""  # LLM 생성 제목 (08-generate-titles.py 마이그레이션). 없으면 "" → 프론트가 hierarchy로 폴백
    )
    content: str  # 자식 청크 미리보기 (아코디언 헤더에 표시)
    full_content: str  # 부모 원문 전체 (아코디언 펼침 시 표시)
    related_paragraphs: list[str]  # 관련 문단 번호 리스트
    chunk_id: str  # 고유 청크 ID (AI 단계에서 문서 식별용)
    score: float = 0.0  # Reranker 점수 (UI 동적 렌더링 용도)
    case_group_title: str = ""  # IE 적용사례 그룹 제목 (예: "사례 4: 계약 식별 기준의 재검토")


class SearchResponse(BaseModel):
    """검색 엔드포인트 응답 스키마."""

    standalone_query: str  # LLM이 정규화한 검색어 (AI 단계에서 재사용)
    search_id: str  # 세션 캐시 키 (UUID, /chat에 함께 전송)
    docs: list[DocResult]  # 카테고리별로 그룹화 전 원본 순서 목록


# ── SSE 이벤트 ──────────────────────────────────────────────────────────────────


class SSEEvent(BaseModel):
    """SSE로 전송하는 이벤트 단위.

    type별 의미:
      status  - 파이프라인 단계 진행 알림 (step + message 필드 사용)
      done    - 처리 완료 (session_id + cited_sources + follow_up_questions 포함)
      error   - 오류 발생 (message 필드에 오류 내용)
    """

    type: Literal["status", "done", "error"]
    step: str | None = None  # "analyze" | "retrieve" | ...
    message: str | None = None  # 진행 상태 메시지 또는 오류 내용
    text: str | None = None  # 최종 답변 텍스트 (done 이벤트)
    session_id: str | None = None  # done 이벤트에서 클라이언트가 저장할 세션 ID
    cited_sources: list[dict] | None = None  # done 이벤트의 출처 메타데이터
    findings_case: dict | None = None  # done 이벤트의 감리사례
    # AI 답변 후 실무 담당자가 추가로 확인하면 좋을 꼬리 질문 3개
    # 버튼 텍스트로 바로 사용할 수 있는 20자 이내 질문입니다.
    follow_up_questions: list[str] | None = None
    # True면 follow_up_questions가 선택지(답변 유도), False면 개념 확인 꼬리질문
    is_situation: bool | None = None
    # /chat RAG 파이프라인이 찾은 근거 문서 (DocResult 직렬화 dict 목록)
    # 좌측 근거 패널(evidence_docs)을 채우는 데 사용됩니다.
    retrieved_docs: list[dict] | None = None

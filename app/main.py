# app/main.py
# FastAPI 애플리케이션 진입점
#
# lifespan 훅을 사용하는 이유:
#   BM25 인덱스는 MongoDB 전체 문서를 메모리에 로드해 빌드합니다.
#   첫 번째 요청에서 빌드하면 사용자가 12~27초 + BM25 빌드 시간을 기다려야 합니다.
#   서버 시작 시 사전 로드(warm-up)하여 첫 요청부터 정상 속도를 보장합니다.
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작/종료 시 실행되는 수명 주기 핸들러."""
    # 서버 시작: BM25 인덱스 사전 빌드
    # _build_bm25_index()는 내부적으로 이미 호출 여부를 체크하므로 중복 빌드 없음.
    from app.retriever import _build_bm25_index
    print("[startup] BM25 인덱스를 사전 로드합니다...")
    _build_bm25_index()
    print("[startup] BM25 인덱스 로드 완료. 서버 준비 완료!")
    yield
    # 서버 종료: 인메모리 자원은 프로세스 종료 시 자동 해제됩니다.


app = FastAPI(
    title="K-IFRS 1115 Chatbot API",
    description="한국 기업회계기준서 제1115호 전문 Q&A 챗봇 백엔드",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: Streamlit(:8501)에서 FastAPI(:8000)로 요청하므로 허용 필수
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
async def root():
    """루트 접속 시 Swagger UI로 리다이렉트합니다."""
    return RedirectResponse(url="/docs")

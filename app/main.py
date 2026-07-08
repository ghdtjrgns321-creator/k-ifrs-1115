# app/main.py
# FastAPI 애플리케이션 진입점
#
# 검색은 온톨로지 그래프 탐색(app/nodes/retrieve.py)으로 수행하므로
# 기동 시 사전 로드할 인덱스가 없습니다. lifespan 훅은 향후 확장 지점으로만 유지합니다.
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api.routes import router
from app.config import settings

# 프로젝트 공통 로깅 설정 — 애플리케이션 진입점에서 1회만 설정
# Why: config.py에 두면 import 부작용 발생, 테스트 시 로깅 격리 불가
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작/종료 시 실행되는 수명 주기 핸들러."""
    logger.info("서버 준비 완료 (그래프 탐색 기반 — 사전 로드 인덱스 없음)")
    yield


app = FastAPI(
    title="K-IFRS 1115 Chatbot API",
    description="한국 기업회계기준서 제1115호 전문 Q&A 챗봇 백엔드",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: Streamlit(:8501)에서 FastAPI(:8002)로 요청하므로 허용 필수
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
async def root():
    """루트 접속 시 Swagger UI로 리다이렉트합니다."""
    return RedirectResponse(url="/docs")

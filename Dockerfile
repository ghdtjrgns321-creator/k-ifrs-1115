# ── Stage 1: builder ──────────────────────────────────────────────────────────
# uv 공식 이미지에서 의존성만 설치합니다.
# --frozen: uv.lock과 pyproject.toml 불일치 시 실패 (재현성 보장)
# --no-dev: dev 의존성(ruff, pytest 등) 제외
# --no-cache: 캐시 미생성으로 이미지 크기 절감
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
# 경량 Python 이미지에 .venv와 소스코드만 복사합니다.
# uv, 빌드 도구 등은 포함되지 않아 최종 이미지가 가볍습니다.
FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app

# builder에서 생성된 가상환경만 복사
COPY --from=builder /app/.venv /app/.venv

# 소스코드 복사
COPY app/ ./app/

# .venv/bin을 PATH 앞에 추가하여 가상환경 활성화 효과
ENV PATH="/app/.venv/bin:$PATH"
# Python 출력 버퍼링 비활성화 (Docker 로그 실시간 확인용)
ENV PYTHONUNBUFFERED=1

# FastAPI(8002), Streamlit(8501) 포트 노출
EXPOSE 8002 8501

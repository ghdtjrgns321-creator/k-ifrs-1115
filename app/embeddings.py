# app/embeddings.py
# Upstage 임베딩 API 직접 호출 — langchain-upstage 대체
#
# passage(저장)/query(검색) 모델 구분이 필수입니다 (혼용 시 검색 품질 급락).
# async 버전: 런타임 파이프라인용
# sync 버전: 전처리 스크립트 + 동기 검색 서비스용
import httpx
from app.config import settings

_EMBED_URL = "https://api.upstage.ai/v1/solar/embeddings"


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.upstage_api_key}"}


# ── 동기 버전 (전처리 스크립트 + retriever.py + search_service.py) ──────────────

def embed_texts_sync(
    texts: list[str],
    model: str | None = None,
) -> list[list[float]]:
    """passage 모델로 여러 텍스트를 일괄 임베딩합니다 (동기)."""
    model = model or settings.embed_passage_model
    with httpx.Client(timeout=60) as client:
        resp = client.post(
            _EMBED_URL,
            headers=_headers(),
            json={"model": model, "input": texts},
        )
        resp.raise_for_status()
        return [d["embedding"] for d in resp.json()["data"]]


def embed_query_sync(text: str) -> list[float]:
    """query 모델로 단일 텍스트를 임베딩합니다 (동기)."""
    return embed_texts_sync([text], settings.embed_query_model)[0]


# ── 비동기 버전 (런타임 파이프라인) ───────────────────────────────────────────

async def embed_query(text: str) -> list[float]:
    """query 모델로 단일 텍스트를 임베딩합니다 (비동기)."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            _EMBED_URL,
            headers=_headers(),
            json={"model": settings.embed_query_model, "input": [text]},
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]

# app/services/search_service.py
# Deterministic 검색 전용 서비스 — /search 엔드포인트의 비즈니스 로직
#
# 역할: 검색 → 재랭킹 → 캐시 저장 → 응답 반환 (LLM 개입 없음)
# /chat과 달리 SSE 스트리밍 없이 JSON으로 즉시 반환합니다.
from uuid import uuid4

from app.api.schemas import DocResult, SearchResponse
from app.reranker import rerank_results
from app.retriever import search_all
from app.services.query_mapping import _expand_query
from app.services.session_store import SessionStore

# 전수 열람 목적이므로 충분히 크게 잡아 관련 문서 누락을 방지합니다.
BROWSE_LIMIT = 500

# 섹션 표시 순서 — streamlit_app.py ACCORDION_GROUPS 정의와 일치시킵니다.
_SECTION_ORDER = [
    "본문",
    "적용지침B",
    "용어정의",
    "시행일",
    "결론도출근거",
    "적용사례IE",
    "QNA",
    "질의회신",
    "감리사례",
]


def _sort_by_section_and_score(docs: list[dict]) -> list[dict]:
    """섹션 순서로 그룹화하고, 섹션 내에서 Reranker 점수(rerank_score) 내림차순 정렬.

    rerank_score를 정렬 키로 쓰는 이유:
      - final_score는 임계값(0.05) 미만 문서가 모두 0.0으로 동점 처리되어 구별 불가
      - rerank_score는 Cohere 원시 점수이므로 모든 문서에 개별 점수가 부여됨
    """
    groups: dict[str, list[dict]] = {s: [] for s in _SECTION_ORDER}
    others: list[dict] = []

    for doc in docs:
        source = doc.get("source", "본문")
        if source in groups:
            groups[source].append(doc)
        else:
            others.append(doc)

    for source in groups:
        groups[source].sort(key=lambda d: d.get("rerank_score", 0.0), reverse=True)

    result: list[dict] = []
    for source in _SECTION_ORDER:
        result.extend(groups[source])
    result.extend(others)
    return result


def run_search(query: str, session_id: str, store: SessionStore) -> SearchResponse:
    """쿼리를 받아 관련 K-IFRS 문서를 검색하고 SearchResponse를 반환합니다.

    내부 흐름 (deterministic — LLM 없음):
      1. _expand_query  — QUERY_MAPPING 조회 (매핑 없으면 원본 유지)
      2. search_all     — 하이브리드 검색 (Vector + BM25 + RRF), 후보 500개 전수 추출
      3. rerank_results — Cohere Reranker 전체 채점 (top_n 제한 없이 전부 채점)
      4. 섹션 정렬      — 임계값 필터 없이 전체 통과, 섹션 순서 + Reranker 점수 내림차순
      5. store_search   — search_id → docs 캐시 (이후 /chat에서 재사용)
    """
    expanded = _expand_query(query)
    retrieved = search_all(expanded, limit=BROWSE_LIMIT)
    scored = rerank_results(expanded, retrieved, top_n=len(retrieved))
    sorted_docs = _sort_by_section_and_score(scored)

    search_id = str(uuid4())
    store.store_search(session_id, search_id, sorted_docs)

    return SearchResponse(
        standalone_query=expanded,
        search_id=search_id,
        docs=[_to_doc_result(doc) for doc in sorted_docs],
    )


def _to_doc_result(doc: dict) -> DocResult:
    """retriever 반환 dict를 API 응답용 DocResult로 변환합니다."""
    full = doc.get("full_content") or doc.get("content", "")
    return DocResult(
        source=doc.get("source", "본문"),
        hierarchy=doc.get("hierarchy", ""),
        title=doc.get("title", ""),
        content=doc.get("content", ""),
        full_content=full,
        related_paragraphs=doc.get("related_paragraphs", []),
        chunk_id=doc.get("chunk_id", ""),
        score=doc.get("rerank_score", 0.0),
        parent_id=doc.get("parent_id") or "",
        case_group_title=doc.get("case_group_title") or "",
        chunk_type=doc.get("chunk_type") or "",
    )

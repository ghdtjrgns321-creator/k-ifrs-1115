# app/nodes/retrieve.py
# 온톨로지 그래프 탐색 기반 문서 수집 (STEP 5-3)
#
# 이전 구조(벡터+BM25+RRF+weight_score+핀포인트)를 전면 대체.
# analyze가 넘긴 concept_ids로 그래프를 결정적으로 탐색하고, 조회 규약으로
# MongoDB 원문을 수집한다. 임베딩 유사도·가중치 미사용.
import asyncio
import logging

from app.domain.graph import get_graph
from app.domain.graph_fetch import fetch_bc, fetch_documents

logger = logging.getLogger(__name__)


async def retrieve_docs(state: dict) -> dict:
    """개념 진입 → 그래프 탐색 → 원문 조회. 결정적, 유사도 계산 없음.

    입력: state["concept_ids"](analyze 5-2)
    출력: retrieved_docs(정규화 문서), concept_path(근거 경로)
    """
    concept_ids = state.get("concept_ids", [])

    graph = get_graph()
    # via_embed는 근거 경로 표시용 — 수집 대상을 가르지 않는다. 사례를 via_llm으로
    # 한정하던 임시 조치는 폐기됐다(graph.traverse 주석).
    traverse = graph.traverse(concept_ids, via_embed=state.get("via_embed", []))

    # DB 조회는 blocking → 스레드로
    docs = await asyncio.to_thread(fetch_documents, traverse)
    # BC는 LLM 컨텍스트가 아니라 근거 패널로만 간다(graph_fetch.fetch_bc 주석).
    bc_docs = await asyncio.to_thread(fetch_bc, traverse.bc_paras)

    logger.info(
        "graph retrieve: concepts=%d, paras=%d, cases=%d, ie=%d → docs=%d",
        len(concept_ids),
        len(traverse.paras),
        len(traverse.cases),
        len(traverse.ie_cases),
        len(docs),
    )
    logger.info("graph retrieve: bc=%d (근거 표시 전용, LLM 미열람)", len(bc_docs))

    # candidate_paras: 그래프가 준 문단 후보 전량. 파이프라인은 안 쓰고 품질 로그만 쓴다.
    # Why: 답변이 인용한 문단이 이 집합 밖이면 환각 인용(docs/quality-loop/02 CITATION_OUT).
    return {
        "retrieved_docs": docs,
        "bc_docs": bc_docs,
        "concept_path": traverse.path,
        "candidate_paras": traverse.paras,
    }

# app/nodes/retrieve.py
# 온톨로지 그래프 탐색 기반 문서 수집 (STEP 5-3)
#
# 이전 구조(벡터+BM25+RRF+weight_score+핀포인트)를 전면 대체.
# analyze가 넘긴 concept_ids로 그래프를 결정적으로 탐색하고, 조회 규약으로
# MongoDB 원문을 수집한다. 임베딩 유사도·가중치 미사용.
import asyncio
import logging

from app.domain.graph import get_graph
from app.domain.graph_fetch import fetch_documents

logger = logging.getLogger(__name__)


async def retrieve_docs(state: dict) -> dict:
    """개념 진입 → 그래프 탐색 → 원문 조회. 결정적, 유사도 계산 없음.

    입력: state["concept_ids"](analyze 5-2), state["entry_cases"](용어 진입 사례)
    출력: retrieved_docs(정규화 문서), concept_path(근거 경로)
    """
    concept_ids = state.get("concept_ids", [])
    entry_cases = state.get("entry_cases", [])

    graph = get_graph()
    traverse = graph.traverse(concept_ids)

    # DB 조회는 blocking → 스레드로
    docs = await asyncio.to_thread(fetch_documents, traverse, entry_cases)

    logger.info(
        "graph retrieve: concepts=%d, paras=%d, cases=%d, ie=%d → docs=%d",
        len(concept_ids),
        len(traverse.paras),
        len(traverse.cases),
        len(traverse.ie_cases),
        len(docs),
    )

    return {"retrieved_docs": docs, "concept_path": traverse.path}

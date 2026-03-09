# app/nodes/hyde_retrieve.py
# HyDE 폴백 검색 노드
# grade 통과 문서가 부족할 때(< 3개) 호출되어 HyDE 벡터로 재검색합니다.
import asyncio

from app.retriever import search_all_hyde

# grade 통과 문서가 이 값 미만이면 HyDE 폴백을 트리거합니다.
HYDE_TRIGGER_THRESHOLD = 3


async def hyde_retrieve(state: dict) -> dict:
    """HyDE 폴백 검색: 가상 K-IFRS 조항 벡터로 재검색하고 기존 결과와 병합합니다.

    기존 retrieved_docs를 유지하면서 HyDE 결과를 추가합니다.
    chunk_id 기준으로 중복을 제거하므로 같은 문서가 두 번 들어가지 않습니다.
    """
    query = state["standalone_query"]
    existing = {doc["chunk_id"]: doc for doc in state.get("retrieved_docs", [])}

    # search_all_hyde는 동기 함수 → 스레드에서 실행
    hyde_docs = await asyncio.to_thread(search_all_hyde, query, 20)

    for doc in hyde_docs:
        cid = doc["chunk_id"]
        if cid not in existing:
            existing[cid] = doc

    return {
        "retrieved_docs": list(existing.values()),
        "retry_count": state.get("retry_count", 0) + 1,
    }

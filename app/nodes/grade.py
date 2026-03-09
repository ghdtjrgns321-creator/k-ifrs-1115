# app/nodes/grade.py
# 리랭크된 문서가 질문에 답변할 수 있는지 LLM으로 평가 (CRAG)
from app.agents import grade_agent
from app.prompts import GRADE_PROMPT


async def grade_docs(state: dict) -> dict:
    """리랭크된 문서들이 질문에 대답할 수 있는지 평가하여 relevant_docs를 걸러냅니다."""

    reranked_docs = state.get("reranked_docs", [])
    if not reranked_docs:
        return {"relevant_docs": []}

    question = state.get("standalone_query") or ""
    if not question:
        # 질문이 없으면 LLM 평가가 무의미 → 전체 통과
        return {"relevant_docs": reranked_docs}

    context_str = "\n\n".join(
        f"[문서 ID: {doc['chunk_id']}]\n{doc['content']}" for doc in reranked_docs
    )

    result = await grade_agent.run(
        GRADE_PROMPT.format(question=question, context=context_str)
    )

    relevant_ids = {r.chunk_id for r in result.data.results if r.is_relevant}
    relevant_docs = [doc for doc in reranked_docs if doc["chunk_id"] in relevant_ids]

    return {"relevant_docs": relevant_docs}

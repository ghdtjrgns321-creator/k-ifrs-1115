# app/nodes/rewrite.py
# 검색 실패 시 질문을 회계 전문 용어로 재작성
from app.agents import rewrite_agent
from app.prompts import REWRITE_PROMPT


async def rewrite_query(state: dict) -> dict:
    """검색에 실패한 질문을 벡터 검색에 유리한 회계 전문 용어로 재작성."""

    result = await rewrite_agent.run(
        REWRITE_PROMPT.format(question=state["standalone_query"])
    )

    return {
        "standalone_query": result.data.strip(),
        "retry_count": state.get("retry_count", 0) + 1,
    }

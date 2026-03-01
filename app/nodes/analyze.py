# app/nodes/analyze.py
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from app.llm import get_llm
from app.state import RAGState
from app.prompts import ANALYZE_PROMPT


class AnalyzeResult(BaseModel):
    routing: str = Field(description="회계 관련이면 'IN', 무관하면 'OUT'")
    standalone_query: str = Field(description="재작성된 독립형 질문 (OUT이면 빈 문자열)")


def analyze_query(state: RAGState):
    """사용자 질문을 분석하여 멀티턴을 재구성하고 라우팅 방향을 결정합니다."""

    structured_llm = get_llm().with_structured_output(AnalyzeResult)

    prompt = ChatPromptTemplate.from_messages([
        ("system", ANALYZE_PROMPT),
        ("human", "최신 대화 기록 및 질문: {messages}")
    ])

    chain = prompt | structured_llm

    formatted_messages = "\n".join([f"{m.type}: {m.content}" for m in state["messages"][-3:]])

    result = chain.invoke({"messages": formatted_messages})

    # structured_output이 None을 반환하는 경우 (일부 경량 모델) 폴백 처리
    if result is None:
        last_msg = state["messages"][-1].content if state["messages"] else ""
        return {"routing": "IN", "standalone_query": last_msg}

    return {
        "routing": result.routing,
        "standalone_query": result.standalone_query,
    }

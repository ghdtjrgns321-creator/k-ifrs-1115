# app/nodes/analyze.py
from pydantic import BaseModel, Field
from langchain_upstage import ChatUpstage
from langchain_core.prompts import ChatPromptTemplate
from app.config import settings
from app.state import RAGState
from app.prompts import ANALYZE_PROMPT


class AnalyzeResult(BaseModel):
    routing: str = Field(description="회계 관련이면 'IN', 무관하면 'OUT'")
    standalone_query: str = Field(description="재작성된 독립형 질문 (OUT이면 빈 문자열)")


def analyze_query(state: RAGState):
    """사용자 질문을 분석하여 멀티턴을 재구성하고 라우팅 방향을 결정합니다."""

    llm = ChatUpstage(model=settings.llm_model, temperature=0, upstage_api_key=settings.upstage_api_key)
    structured_llm = llm.with_structured_output(AnalyzeResult)

    prompt = ChatPromptTemplate.from_messages([
        ("system", ANALYZE_PROMPT),
        ("human", "최신 대화 기록 및 질문: {messages}")
    ])

    # prompt | structured_llm 파이프라인 패턴 → LangSmith에서 각 단계가 분리되어 추적됨
    chain = prompt | structured_llm

    # LangGraph의 messages 객체를 문자열로 풀어서 전달
    formatted_messages = "\n".join([f"{m.type}: {m.content}" for m in state["messages"][-3:]])

    result = chain.invoke({"messages": formatted_messages})

    return {
        "routing": result.routing,
        "standalone_query": result.standalone_query,
    }

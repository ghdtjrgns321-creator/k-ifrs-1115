# app/nodes/rewrite.py
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from app.llm import get_llm
from app.state import RAGState
from app.prompts import REWRITE_PROMPT


def rewrite_query(state: RAGState):
    """검색에 실패한 질문을 벡터 검색에 유리한 회계 전문 용어로 재작성합니다."""

    chain = ChatPromptTemplate.from_template(REWRITE_PROMPT) | get_llm() | StrOutputParser()
    new_query = chain.invoke({"question": state["standalone_query"]})

    return {
        "standalone_query": new_query.strip(),
        "retry_count": state.get("retry_count", 0) + 1,
    }

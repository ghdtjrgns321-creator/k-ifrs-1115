# app/nodes/rewrite.py
from langchain_upstage import ChatUpstage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from app.config import settings
from app.state import RAGState
from app.prompts import REWRITE_PROMPT

def rewrite_query(state: RAGState):
    """검색에 실패한 질문을 벡터 검색에 유리한 회계 전문 용어로 재작성합니다."""
    
    llm = ChatUpstage(model=settings.llm_model, temperature=0, upstage_api_key=settings.upstage_api_key)
    prompt = ChatPromptTemplate.from_template(REWRITE_PROMPT)
    
    chain = prompt | llm | StrOutputParser()
    new_query = chain.invoke({"question": state["standalone_query"]})
    
    current_retry = state.get("retry_count", 0)
    
    return {
        "standalone_query": new_query.strip(),
        "retry_count": current_retry + 1
    }
# app/nodes/grade.py
from pydantic import BaseModel, Field
from langchain_upstage import ChatUpstage
from langchain_core.prompts import ChatPromptTemplate
from app.config import settings
from app.state import RAGState
from app.prompts import GRADE_PROMPT


# 배치 평가를 위한 Pydantic 스키마
class DocGrade(BaseModel):
    chunk_id: str = Field(description="평가한 문서의 chunk_id")
    is_relevant: bool = Field(description="질문에 대한 답변으로 유효한지 여부 (True/False)")


class GradeResult(BaseModel):
    results: list[DocGrade]


def grade_docs(state: RAGState):
    """리랭크된 문서들이 질문에 대답할 수 있는지 평가하여 relevant_docs를 걸러냅니다."""

    reranked_docs = state.get("reranked_docs", [])
    if not reranked_docs:
        return {"relevant_docs": []}

    llm = ChatUpstage(model=settings.llm_model, temperature=0, upstage_api_key=settings.upstage_api_key)
    structured_llm = llm.with_structured_output(GradeResult)

    prompt = ChatPromptTemplate.from_template(GRADE_PROMPT)

    # prompt | structured_llm 파이프라인 패턴 → LangSmith 추적 호환
    chain = prompt | structured_llm

    # 5개의 문서를 하나의 프롬프트 텍스트로 결합
    context_str = "\n\n".join([f"[문서 ID: {doc['chunk_id']}]\n{doc['content']}" for doc in reranked_docs])

    eval_result = chain.invoke({"question": state["standalone_query"], "context": context_str})

    # True로 판정된 문서만 필터링
    relevant_chunk_ids = {res.chunk_id for res in eval_result.results if res.is_relevant}
    relevant_docs = [doc for doc in reranked_docs if doc["chunk_id"] in relevant_chunk_ids]

    return {"relevant_docs": relevant_docs}

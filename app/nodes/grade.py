from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from app.llm import get_front_llm
from app.state import RAGState
from app.prompts import GRADE_PROMPT


class DocGrade(BaseModel):
    chunk_id: str = Field(description="평가한 문서의 chunk_id")
    is_relevant: bool = Field(description="질문에 대한 답변으로 유효한지 여부 (True/False)")


class GradeResult(BaseModel):
    results: list[DocGrade]


def grade_docs(state: RAGState):
    """리랭크된 문서들이 질문에 대답할 수 있는지 평가하여 relevant_docs를 걸러냄"""

    reranked_docs = state.get("reranked_docs", [])
    if not reranked_docs:
        return {"relevant_docs": []}

    structured_llm = get_front_llm().with_structured_output(GradeResult)

    prompt = ChatPromptTemplate.from_template(GRADE_PROMPT)
    chain = prompt | structured_llm

    context_str = "\n\n".join([f"[문서 ID: {doc['chunk_id']}]\n{doc['content']}" for doc in reranked_docs])

    eval_result = chain.invoke({"question": state["standalone_query"], "context": context_str})

    # structured_output이 None을 반환하는 경우 전체 문서를 통과시킴 (폴백)
    if eval_result is None:
        return {"relevant_docs": reranked_docs}

    relevant_chunk_ids = {res.chunk_id for res in eval_result.results if res.is_relevant}
    relevant_docs = [doc for doc in reranked_docs if doc["chunk_id"] in relevant_chunk_ids]

    return {"relevant_docs": relevant_docs}

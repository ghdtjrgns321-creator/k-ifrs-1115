from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from app.llm import get_generate_llm
from app.state import RAGState
from app.prompts import GENERATE_PROMPT


def generate_answer(state: RAGState):
    """최종 필터링된 문서를 바탕으로 환각 없는 정확한 회계 답변을 생성"""

    docs = state.get("relevant_docs", [])

    context_parts = []
    cited_sources = []

    for doc in docs:
        source_type = doc.get("source", "본문")

        # PDR 원리: 자식 청크가 아닌 부모 원문(full_content)을 통째로 LLM에 넘김
        text = doc.get("full_content") if source_type != "본문" else doc.get("content")
        hierarchy = doc.get("hierarchy", "")

        context_parts.append(f"[{source_type}] {hierarchy}\n{text}")

        cited_sources.append({
            "source": source_type,
            "hierarchy": hierarchy,
            "chunk_id": doc.get("chunk_id", ""),
            "related_paragraphs": doc.get("related_paragraphs", [])
        })

    context_str = "\n\n---\n\n".join(context_parts)

    chain = ChatPromptTemplate.from_template(GENERATE_PROMPT) | get_generate_llm() | StrOutputParser()

    answer = chain.invoke({
        "context": context_str,
        "question": state["standalone_query"]
    })

    return {
        "answer": answer,
        "cited_sources": cited_sources,
    }

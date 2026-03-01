# app/nodes/generate.py
from langchain_upstage import ChatUpstage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from app.config import settings
from app.state import RAGState
from app.prompts import GENERATE_PROMPT

def generate_answer(state: RAGState):
    """최종 필터링된 문서를 바탕으로 환각 없는 정확한 회계 답변을 생성합니다."""
    
    # 노드 4(grade.py)를 통과하여 살아남은 '진짜 관련 있는 문서들'만 가져옵니다.
    docs = state.get("relevant_docs", [])
    
    context_parts = []
    cited_sources = []
    
    for doc in docs:
        source_type = doc.get("source", "본문")
        
        # 핵심: PDR 원리에 따라 자식 청크가 아닌 부모 원문(full_content)을 통째로 넘김
        text = doc.get("full_content") if source_type != "본문" else doc.get("content")
        hierarchy = doc.get("hierarchy", "")
        
        # LLM이 출처를 명확히 알 수 있도록 꼬리표를 달아줍니다.
        context_parts.append(f"[{source_type}] {hierarchy}\n{text}")
        
        # 나중에 노드 7(format.py)에서 출처 링크와 넛지(Nudge) UI를 만들 때 쓸 메타데이터 보관
        cited_sources.append({
            "source": source_type,
            "hierarchy": hierarchy,
            "chunk_id": doc.get("chunk_id", ""),
            "related_paragraphs": doc.get("related_paragraphs", [])
        })
        
    context_str = "\n\n---\n\n".join(context_parts)
    
    # LLM 초기화 (일관성을 위해 temperature=0 고정)
    llm = ChatUpstage(model=settings.llm_model, temperature=0, upstage_api_key=settings.upstage_api_key)
    prompt = ChatPromptTemplate.from_template(GENERATE_PROMPT)
    chain = prompt | llm | StrOutputParser()
    
    # 답변 생성 실행
    answer = chain.invoke({
        "context": context_str,
        "question": state["standalone_query"]
    })
    
    return {
        "answer": answer,
        "cited_sources": cited_sources
    }
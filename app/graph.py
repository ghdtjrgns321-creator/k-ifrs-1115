# app/graph.py
from langgraph.graph import StateGraph, START, END
from app.state import RAGState

# 노드 함수들 임포트
from app.nodes.analyze import analyze_query
from app.nodes.retrieve import retrieve_docs
from app.nodes.rerank import rerank_docs
from app.nodes.grade import grade_docs
from app.nodes.rewrite import rewrite_query
from app.nodes.generate import generate_answer
from app.nodes.format import format_response

# ---------------------------------------------
# 조건부 라우팅 함수 정의
# ---------------------------------------------
def route_analyze(state: RAGState):
    """질문 분석 결과에 따라 정상 검색을 할지, 쳐낼지 결정합니다."""
    if state.get("routing") == "OUT":
        return "reject"
    return "retrieve"

def route_grade(state: RAGState):
    """품질 평가 통과 여부에 따라 답변을 생성할지, 재검색할지 결정합니다."""
    relevant_docs = state.get("relevant_docs", [])
    retry_count = state.get("retry_count", 0)
    
    if relevant_docs:
        return "generate"
    # 관련 문서가 0개인데 아직 재시도를 안 했다면? -> 질문 재작성
    if not relevant_docs and retry_count == 0:
        return "rewrite_query"
    # 재시도까지 했는데도 없으면? -> 있는 걸로 최선을 다해 답변(환각 방지 프롬프트 발동)
    return "generate" 

def reject_out_of_scope(state: RAGState):
    """범위 밖 질문을 받았을 때의 더미 노드"""
    return {"answer": "죄송합니다. 저는 K-IFRS 1115호(수익 인식)와 관련된 회계 및 감사 질문에만 답변할 수 있습니다."}

# ---------------------------------------------
# LangGraph 조립 및 컴파일
# ---------------------------------------------
workflow = StateGraph(RAGState)

# 1. 노드 등록
workflow.add_node("analyze_query", analyze_query)
workflow.add_node("retrieve", retrieve_docs)
workflow.add_node("rerank", rerank_docs)
workflow.add_node("grade_docs", grade_docs)
workflow.add_node("rewrite_query", rewrite_query)
workflow.add_node("generate", generate_answer)
workflow.add_node("format_response", format_response)
workflow.add_node("reject", reject_out_of_scope)

# 2. 엣지 연결 (설계도와 100% 동일)
workflow.add_edge(START, "analyze_query")

workflow.add_conditional_edges(
    "analyze_query",
    route_analyze,
    {"retrieve": "retrieve", "reject": "reject"}
)

workflow.add_edge("retrieve", "rerank")
workflow.add_edge("rerank", "grade_docs")

workflow.add_conditional_edges(
    "grade_docs",
    route_grade,
    {"generate": "generate", "rewrite_query": "rewrite_query"}
)

workflow.add_edge("rewrite_query", "retrieve") # 🔄 재검색 루프
workflow.add_edge("generate", "format_response")
workflow.add_edge("format_response", END)
workflow.add_edge("reject", END)

# 3. 그래프 최종 컴파일 — from app.graph import rag_graph 로 사용
rag_graph = workflow.compile()
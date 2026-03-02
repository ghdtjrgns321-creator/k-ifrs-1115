# app/graph.py
from langgraph.graph import StateGraph, START, END
from app.state import RAGState

from app.nodes.analyze import analyze_query
from app.nodes.retrieve import retrieve_docs
from app.nodes.rerank import rerank_docs
from app.nodes.grade import grade_docs
from app.nodes.hyde_retrieve import hyde_retrieve, HYDE_TRIGGER_THRESHOLD
from app.nodes.rewrite import rewrite_query
from app.nodes.generate import generate_answer
from app.nodes.format import format_response

# ── 라우팅 함수 ────────────────────────────────────────────────────────────────

def route_analyze(state: RAGState):
    """질문 분석 결과에 따라 검색할지 거절할지 결정합니다."""
    return "retrieve" if state.get("routing") == "IN" else "reject"


def route_grade(state: RAGState):
    """
    grade 결과에 따라 다음 단계를 결정합니다.

    retry_count 의미:
      0 → 첫 번째 검색 후 grade 결과
      1 → HyDE 재검색 후 grade 결과 (hyde_retrieve가 +1 했음)
      2 → rewrite_query 재검색 후 grade 결과

    라우팅 규칙:
      relevant >= 3개          → 충분한 근거 확보 → generate
      relevant < 3 && retry=0  → HyDE 폴백 검색 시도
      relevant < 3 && retry=1  → 질문 재작성(rewrite) 시도
      relevant < 3 && retry>=2 → 포기하고 있는 근거로 generate
    """
    relevant  = state.get("relevant_docs", [])
    retry     = state.get("retry_count", 0)

    if len(relevant) >= HYDE_TRIGGER_THRESHOLD:
        return "generate"
    if retry == 0:
        return "hyde_retrieve"   # 1차 폴백: HyDE 재검색
    if retry == 1:
        return "rewrite_query"   # 2차 폴백: 질문 재작성
    return "generate"            # 포기: 있는 근거로 최선


def reject_out_of_scope(state: RAGState):
    """범위 밖 질문 처리 더미 노드."""
    return {"answer": "죄송합니다. 저는 K-IFRS 1115호(수익 인식)와 관련된 회계 및 감사 질문에만 답변할 수 있습니다."}


# ── 그래프 조립 ────────────────────────────────────────────────────────────────

workflow = StateGraph(RAGState)

# 노드 등록
workflow.add_node("analyze_query",  analyze_query)
workflow.add_node("retrieve",       retrieve_docs)
workflow.add_node("rerank",         rerank_docs)
workflow.add_node("grade_docs",     grade_docs)
workflow.add_node("hyde_retrieve",  hyde_retrieve)   # ← 신규
workflow.add_node("rewrite_query",  rewrite_query)
workflow.add_node("generate",       generate_answer)
workflow.add_node("format_response", format_response)
workflow.add_node("reject",         reject_out_of_scope)

# 엣지 연결
workflow.add_edge(START, "analyze_query")

workflow.add_conditional_edges(
    "analyze_query",
    route_analyze,
    {"retrieve": "retrieve", "reject": "reject"},
)

workflow.add_edge("retrieve", "rerank")
workflow.add_edge("rerank",   "grade_docs")

workflow.add_conditional_edges(
    "grade_docs",
    route_grade,
    {
        "generate":      "generate",
        "hyde_retrieve": "hyde_retrieve",  # 1차 폴백
        "rewrite_query": "rewrite_query",  # 2차 폴백
    },
)

# HyDE 재검색 후 → rerank → grade 재평가
workflow.add_edge("hyde_retrieve", "rerank")

# rewrite 재검색 루프 (기존과 동일)
workflow.add_edge("rewrite_query", "retrieve")

workflow.add_edge("generate",       "format_response")
workflow.add_edge("format_response", END)
workflow.add_edge("reject",          END)

rag_graph = workflow.compile()

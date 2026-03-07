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
    """질문 분석 결과에 따라 다음 단계를 결정합니다.

    라우팅 우선순위:
      OUT     → reject (회계 무관 질문)
      pre_retrieved_docs가 있음 → inject_pre (retrieve/rerank 스킵)
      IN + 없음 → retrieve (일반 검색 흐름)
    """
    if state.get("routing") != "IN":
        return "reject"
    # /search에서 미리 검색된 docs가 있으면 inject → grade로 바로 점프합니다.
    # 사용자가 이미 근거 문서를 열람한 뒤 AI 질문을 입력한 경우입니다.
    if state.get("pre_retrieved_docs") is not None:
        return "inject_pre"
    return "retrieve"


def inject_pre_retrieved(state: RAGState):
    """pre_retrieved_docs를 reranked_docs로 복사합니다.

    grade_docs 노드는 reranked_docs를 읽으므로 이 중간 노드가 필요합니다.
    retrieve/rerank 없이 바로 품질 평가로 이동합니다.

    retry_count=2로 설정하는 이유:
      /search 결과로 CRAG를 통과한 문서가 임계값(3개) 미만이더라도
      사용자가 이미 근거 문서를 직접 열람한 상태이므로 HyDE/rewrite 폴백을
      실행하면 의도치 않은 추가 검색이 발생합니다.
      retry_count=2는 route_grade에서 "포기하고 있는 근거로 generate"로
      바로 이동하게 하여 불필요한 재검색을 방지합니다.
    """
    return {
        "reranked_docs": state.get("pre_retrieved_docs", []),
        "retry_count": 2,
    }


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
workflow.add_node("analyze_query",   analyze_query)
workflow.add_node("inject_pre",      inject_pre_retrieved)   # ← pre_retrieved_docs 주입
workflow.add_node("retrieve",        retrieve_docs)
workflow.add_node("rerank",          rerank_docs)
workflow.add_node("grade_docs",      grade_docs)
workflow.add_node("hyde_retrieve",   hyde_retrieve)
workflow.add_node("rewrite_query",   rewrite_query)
workflow.add_node("generate",        generate_answer)
workflow.add_node("format_response", format_response)
workflow.add_node("reject",          reject_out_of_scope)

# 엣지 연결
workflow.add_edge(START, "analyze_query")

workflow.add_conditional_edges(
    "analyze_query",
    route_analyze,
    {
        "retrieve":   "retrieve",
        "inject_pre": "inject_pre",  # pre_retrieved_docs → grade 직행
        "reject":     "reject",
    },
)

# inject_pre → grade_docs (retrieve/rerank 완전 스킵)
workflow.add_edge("inject_pre", "grade_docs")

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

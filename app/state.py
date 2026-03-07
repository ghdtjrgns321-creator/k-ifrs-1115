from typing import Annotated, Sequence
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class RAGState(TypedDict):
    # 1. 대화 히스토리 (LangGraph가 자동으로 메시지를 누적)
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # 2. 라우팅 및 파이프라인 제어
    routing: str                 # "IN" (회계 질문) 또는 "OUT" (무관한 질문)
    standalone_query: str        # 문맥이 반영된 독립형 질문
    retry_count: int             # 재검색 횟수 (무한 루프 방지용, 최대 1회)
    is_situation: bool           # True: 구체적 거래 상황 설명 / False: 개념·조항 질문
    search_keywords: list[str]   # 벡터 DB 검색용 핵심 K-IFRS 용어 2~3개

    # 3. 문서 검색 및 평가 파이프라인
    # 각 단계의 dict 스키마: retriever.py search_all() 반환값 참조
    # {source, chunk_id, parent_id, category, chunk_type, content, full_content, score, ...}
    retrieved_docs: list[dict]   # 1차 검색 결과 (Vector + BM25 + RRF)
    reranked_docs: list[dict]    # 2차 Reranker 결과 (Upstage Reranker + 룰 적용)
    relevant_docs: list[dict]    # 3차 품질 평가 통과 결과 (CRAG - Yes 판정)

    # /search에서 미리 검색·재랭킹·평가된 docs를 주입하면 retrieve/rerank 단계를 스킵합니다.
    # None이면 일반 retrieve 흐름을 실행합니다.
    pre_retrieved_docs: list[dict] | None

    # 4. 생성 결과물
    answer: str                  # LLM이 생성한 최종 답변
    cited_sources: list[dict]    # 인용 출처 메타데이터 ({source, chunk_id, hierarchy, ...})
    findings_case: dict | None   # 섀도우 매칭된 감리사례 ({title, hierarchy, content}), 없으면 None
    follow_up_questions: list[str]  # 답변 후 생성된 꼬리 질문 3개 (버튼 텍스트)

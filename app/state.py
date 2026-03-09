# app/state.py
# RAG 파이프라인 상태 — 순수 TypedDict (LangGraph 의존성 제거)
#
# 각 노드 함수는 이 dict를 입력받고, 부분 업데이트 dict를 반환합니다.
# pipeline.py에서 state.update(result)로 병합합니다.
from typing_extensions import TypedDict


class RAGState(TypedDict):
    # 1. 대화 히스토리 — [("human", "질문"), ("ai", "답변"), ...]
    messages: list[tuple[str, str]]

    # 2. 라우팅 및 파이프라인 제어
    routing: str                 # "IN" (회계 질문) 또는 "OUT" (무관한 질문)
    standalone_query: str        # 문맥이 반영된 독립형 질문
    retry_count: int             # 재검색 횟수 (무한 루프 방지용)
    is_situation: bool           # True: 구체적 거래 상황 / False: 개념·조항 질문
    search_keywords: list[str]   # 벡터 DB 검색용 핵심 K-IFRS 용어 2~3개
    matched_topics: list[dict]   # tree_matcher가 매칭한 체크리스트 토픽 (최대 2개)

    # 3. 문서 검색 및 평가 파이프라인
    retrieved_docs: list[dict]   # 1차 검색 결과 (Vector + BM25 + RRF)
    reranked_docs: list[dict]    # 2차 Reranker 결과
    relevant_docs: list[dict]    # 3차 품질 평가 통과 결과 (CRAG - Yes 판정)

    # /search에서 미리 검색된 docs 주입 → retrieve/rerank 스킵
    pre_retrieved_docs: list[dict] | None

    # 4. 생성 결과물
    answer: str                  # LLM이 생성한 최종 답변
    cited_sources: list[dict]    # 인용 출처 메타데이터
    findings_case: dict | None   # 섀도우 매칭된 감리사례
    follow_up_questions: list[str]  # 꼬리 질문 3개 (버튼 텍스트)

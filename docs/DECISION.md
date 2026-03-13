# 의사결정 기록 (Architecture Decision Records)

> 과거 결정의 맥락과 근거를 빠르게 참조하기 위한 문서.
> 최종 업데이트: 2026-03-13

---

## ADR-1. LangChain/LangGraph → PydanticAI + 순수 Python 오케스트레이션

**결정**: LangGraph StateGraph를 제거하고, `pipeline.py`(async generator) + PydanticAI Agent로 전환

**맥락**: LangGraph의 StateGraph는 노드 간 데이터 흐름·조건 분기를 추상화하지만, 본 프로젝트의 5개 노드(analyze→retrieve→rerank→generate→format) 선형 파이프라인에는 과잉 추상화였음

**근거**:
- StateGraph 디버깅 난이도 높음 (중간 상태 추적 어려움)
- PydanticAI의 `structured output` + `result_validator`로 3단 폴백(JSON 파싱→regex→기본값) 제거
- async generator로 SSE yield 가능 — StreamingResponse와 자연스럽게 결합
- 7개 Agent를 통일된 패턴으로 관리 (analyze, grade, generate, clarify, rewrite, hyde, text)

**삭제된 파일**: graph.py, llm.py, grade.py, hyde_retrieve.py, rewrite.py

---

## ADR-2. 듀얼트랙 모델 라우팅 (Gemini Flash vs gpt-4.1-mini)

**결정**: 일반 질문→Gemini Flash(thinking=high), 계산 질문→gpt-4.1-mini

**맥락**: 모델 비교 평가(`app/test/model_comparison/`)에서 회계 추론 품질과 산술 정확도가 단일 모델로 양립 불가 확인

**근거**:
- Gemini Flash(thinking=high): 회계 추론 품질 1위, 복잡한 판단 질문에 최적
- gpt-4.1-mini: 산술 정확도 100%, non-reasoning이라 계산에 집중
- 3가지 AND 조건으로 회계 판단이 calc로 빠지는 오류 방지:
  1. `matched_topics`에 `calculation_formula` 존재
  2. "계산해줘", "구해줘" 같은 직접 명령
  3. 금액 3개 이상 (2개는 맥락 설명일 수 있음)

**참조**: `app/nodes/generate.py:_needs_calculation()`

---

## ADR-3. ChromaDB → MongoDB Atlas Vector Search

**결정**: 로컬 ChromaDB에서 MongoDB Atlas Vector Search로 전환

**맥락**: Docker 환경에서 ChromaDB 포트 포워딩 이슈(8000→8100) + 메타데이터 필터링 한계

**근거**:
- Atlas의 `$vectorSearch` 파이프라인으로 메타데이터 필터 + 벡터 검색 단일 쿼리
- BM25 키워드 검색을 같은 DB에서 수행 가능 (별도 Elasticsearch 불필요)
- PDR(Parent Document Retrieval)을 위한 다중 컬렉션 자연스럽게 지원
- 임베딩+메타데이터 통합 저장으로 운영 복잡도 감소

---

## ADR-4. BM25 + Vector + RRF 하이브리드 검색

**결정**: Vector Search 단독이 아닌 BM25 + Vector + RRF(Reciprocal Rank Fusion) 융합

**맥락**: 순수 벡터 검색은 회계 용어(정확한 문단 번호, 기준서 조항)의 키워드 매칭에 약함

**근거**:
- Vector Search: 의미 유사도 기반 — "수익 인식 시점"↔"매출 인식 시기" 매칭
- BM25: 키워드 매칭 — "문단 B63A", "제1115호 제35조" 같은 정확한 참조
- RRF(K=60, 논문 권장값): 두 순위 목록을 `1/(rank+K)` 가중합으로 통합
- Window Boost: 같은 섹션 인접 청크에 +0.15 부스팅 (맥락 연속성 보장)
- 도메인 가중치: 본문 > 적용지침B > 적용사례IE > 결론도출근거BC

**참조**: `app/retriever.py`

---

## ADR-5. 2계층 검색: 핀포인트(큐레이션) + 리트리버(벡터+BM25)

**결정**: 큐레이션 문서를 MongoDB 직접 조회(1순위) + 리트리버 검색(2순위) 2계층 구조

**맥락**: 리트리버만으로는 `MASTER_DECISION_TREES`에 큐레이팅된 선례·감리사례의 커버리지가 40% 수준

**근거**:
- decision_tree의 `precedents`/`red_flags`에서 문서 ID 파싱 → MongoDB 직접 조회
- 복잡한 ID 패턴 처리: IE+QNA 혼합, FSS 콤마 접두어 복원, 한글 접미사 등
- 리트리버는 핀포인트가 커버 못하는 본문 조항/적용지침 보충
- 결과: 큐레이션 문서 100% + 벡터 검색 보충 = 높은 커버리지

**참조**: `app/retriever.py:fetch_pinpoint_docs()`, `app/nodes/retrieve.py`

---

## ADR-6. Reranker Bypass (핀포인트 문서)

**결정**: Cohere Reranker에서 핀포인트(큐레이션) 문서를 bypass 처리

**맥락**: T3 테스트에서 핀포인트 fetch 문서 105건 중 103건이 rerank_threshold(0.05) 미만으로 탈락

**근거**:
- Cohere `rerank-multilingual-v3.0`은 query-document 텍스트 유사도 기반 채점
- 큐레이션 문서는 사용자 질문과 직접적 의미 유사도가 낮지만, 도메인 전문가가 관련성을 사전 판단한 것
- 핀포인트 문서는 reranker 건너뛰고 1순위 고정, 나머지만 reranker 채점

**교훈**: Reranker(Cross-encoder)는 텍스트 유사도 기반이므로, 전문가 큐레이션 데이터는 별도 경로로 처리해야 함

**참조**: `app/nodes/rerank.py`, `docs/debugging.md #16`

---

## ADR-7. MASTER_DECISION_TREES 큐레이션 시스템

**결정**: 26개 토픽별 체크리스트 + 결론가이드 + 선례 + 감리경고를 수작업 큐레이션

**맥락**: LLM 자유 추론은 그럴듯하지만 틀린 답(환각) 생성 → 회계감사에서 2종오류(실재 오류 누락) 초래

**근거**:
- **규칙 기반 전문가 시스템** 접근: LLM은 "추론자"가 아닌 "전달자"
- 5단계 방어 레이어:
  1. Domain 큐레이션 (decision_trees)
  2. PydanticAI Structured Output (분기 선택·인용 강제)
  3. result_validator (빈 인용 → ModelRetry)
  4. reasoning_guard (프롬프트 내 논리 뒤집음 방지)
  5. Precedents 직접 주입 (핀포인트 fetch)
- 결론가이드의 분기만 허용 → LLM이 근거 없는 분기를 생성할 수 없는 구조

**Trade-off**: 새로운 사업모델(메타버스, DeFi), 타 기준서 교차(1116호+1115호), Gray Area에서는 효과 제한

**참조**: `app/domain/decision_trees.py`, `app/agents.py`

---

## ADR-8. PDR (Parent Document Retrieval) 패턴

**결정**: QNA/감리사례/교육자료를 작은 청크로 분할 저장하되, LLM에는 부모 원문 전체 제공

**맥락**: 벡터 검색은 작은 청크에서 정확도가 높지만, LLM 답변 생성에는 전체 맥락이 필요

**근거**:
- Child 청크(Q/A/보충 각각)로 분할 → 검색 정확도 향상
- 검색 후 `parent_id`로 부모 원문 전체 조회 → LLM에 풍부한 맥락 제공
- 3개 parent 컬렉션으로 분리: qna-parents, findings-parents, kai-parents
- ID 접두사 라우팅: `QNA-` → qna, `FSS-`/`KICPA-` → findings, `KAI-` → kai

**주의**: parent 컬렉션은 `metadata` dict 안에 `title`, `hierarchy` 중첩 저장 (스키마 불일치 주의)

**참조**: `app/retriever.py`, `docs/debugging.md #9`

---

## ADR-9. 4단계 State Machine UX — "근거 선행, AI 후행"

**결정**: 홈→토픽브라우즈→근거열람→AI답변 4단계 순차 UX

**맥락**: 기존 챗봇은 AI 답변이 먼저, 근거는 나중(또는 없음) → 전문가 도구로 부적합

**근거**:
- 회계감사인은 **객관적 팩트(기준서 원문)**를 먼저 확인하고, AI는 보조 도구로 사용
- 토픽 브라우즈: 4탭(본문·BC | 적용사례 | 질의회신 | 감리사례)으로 큐레이션 문서 즉시 열람
- 근거 열람(evidence): RAG 검색 결과를 카테고리별 아코디언으로 구조화
- AI 답변: Split View(좌=근거 문서, 우=AI 답변+꼬리질문)로 근거와 답변 동시 참조

**핵심 철학**: 사용자가 근거를 확인한 뒤 AI에게 질문하는 **실무 전문가 도구**

---

## ADR-10. calc 경로 최적화 (topic_knowledge 스킵 + CoT prefix 제거)

**결정**: gpt-4.1-mini calc 경로에서 topic_knowledge(~2000자) 조건부 스킵, `_COT_PREFIX` 완전 제거

**맥락**: 모델 비교 테스트에서 산술 정확도 급락 확인 (0.83→0.67)

**근거**:
- `_COT_PREFIX`(포맷 지시)가 시스템 프롬프트와 중복 → attention 분산 → 산술 정확도 하락
- topic_knowledge(개념 설명)가 calc 경로에서 불필요한 토큰 노이즈
- 제거 후 산술 정확도: 0.67 → 0.83 → 0.845 회복

**교훈**: non-reasoning 모델에 system prompt와 user msg에 동일 지시를 중복 주입하면 핵심 태스크 정확도 하락. 포맷 지시는 system prompt 1회만.

**참조**: `app/nodes/generate.py`, `docs/debugging.md #14`

---

## ADR-11. Cohere Reranker 점수 = rerank_score x category_weight x chunk_type_weight

**결정**: Cohere Cross-encoder 점수에 도메인 비즈니스 가중치를 곱하는 하이브리드 점수 체계

**맥락**: 순수 Cross-encoder 점수만으로는 QNA의 Q(질의) 파트가 A(회신) 파트보다 높게 랭킹되는 문제

**근거**:
- Q 파트는 사용자 질문과 의미적으로 유사해 검색은 잘 되지만, 실제 답변이 아님
- Chunk Type 가중치: A(회신/감리지적) 1.0 > S(부록) 0.95 > Q(질의) 0.80
- Category 가중치: 본문 1.0 > 적용지침B 0.95 > 적용사례IE 0.85 > 결론도출근거BC 0.85
- threshold 0.05 미만 → "무관" 판정 후 제거

**참조**: `app/reranker.py`

---

## ADR-12. 임베딩 모델 passage/query 엄격 분리 (Upstage Solar)

**결정**: 저장 시 `solar-embedding-1-large-passage`, 검색 시 `solar-embedding-1-large-query` 엄격 분리

**맥락**: 초기에 passage 모델로 검색 쿼리도 임베딩한 결과, 검색 품질 급락 확인

**근거**:
- Upstage Solar는 passage/query 모델이 별도 학습됨 (asymmetric embedding)
- 혼용 시 벡터 공간 불일치로 코사인 유사도 의미 상실
- 전처리 스크립트(04, 06, 07, 08, 12)에서 passage, retriever.py에서 query 사용

**참조**: `app/config.py`, `app/embeddings.py`

---

## ADR-13. 감리사례 매칭: 문단 번호 기반 → 서머리 임베딩 기반

**결정**: LLM 답변에서 문단 번호 추출→매칭 방식을 폐기하고, 서머리 임베딩 코사인 유사도로 직접 매칭

**맥락**: 범용 문단(9, 12, 22 등)이 자주 매칭되어 노이즈 발생, `GENERIC_PARAGRAPHS` 블랙리스트로는 근본 해결 불가

**근거**:
- 문단 번호 매칭은 간접적(문단→문서→유사도)이라 노이즈에 취약
- `summary-embeddings.json`에 QNA/감리/IE 서머리를 사전 임베딩
- 사용자 질문과 서머리의 코사인 유사도로 직접 매칭 → 블랙리스트 불필요

**참조**: `app/domain/summary_matcher.py`, `data/topic-curation/summary-embeddings.json`

---

## ADR-14. Streamlit CSS: key= 기반 셀렉터만 사용 (JS/iframe 금지)

**결정**: Streamlit 스타일링은 `key="nav_xxx"` + `div[class*="st-key-nav_"]` CSS 셀렉터 패턴만 사용

**맥락**: Streamlit은 CSS 커스터마이징을 공식 지원하지 않으며, 내부 레이아웃 구조가 버전마다 변경됨

**근거**:
- `key=` 기반 셀렉터는 위젯 자체 스타일 변경에 안정적
- 내부 레이아웃(`stVerticalBlock`, gap 등)에 CSS 적용은 불안정
- JS/iframe 주입은 Streamlit의 보안 모델과 충돌
- 간격 제어는 네이티브 `st.container(gap="small")` 사용

**참조**: `docs/debugging.md #1`, `docs/STREAMLIT.md`

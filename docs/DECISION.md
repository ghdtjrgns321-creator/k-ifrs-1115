# 의사결정 기록 (Architecture Decision Records)

> 과거 결정의 맥락과 근거를 빠르게 참조하기 위한 문서.
> 최종 업데이트: 2026-03-16

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

**라우팅 방식 변경 이력**:
- v1 (제거됨): regex 3조건 AND (`_CALC_COMMAND` + `_AMOUNT_PATTERN` + `has_formula`)
  - 문제: 토픽 매칭 비결정성 → B1/B2에서 1/3만 calc 진입
- v2 (현재): `AnalyzeResult.needs_calculation: bool` — analyze_agent(gpt-4.1-mini)가 LLM으로 판단
  - 14개 테스트케이스 × 3회 = 42/42 정확도 100%, 일관성 100%
  - regex 전체 제거 (`_needs_calculation()`, `_CALC_COMMAND`, `_AMOUNT_PATTERN`)
  - 추가 비용 0 (이미 실행 중인 analyze_agent에 필드 1개 추가)

**참조**: `app/agents.py:AnalyzeResult`, `app/nodes/generate.py`

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
- ID 접두사 라우팅: `QNA-` → qna, `FSS-`/`KICPA-` → findings, `EDU-` → kai

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

**참조**: `app/nodes/generate.py`, `docs/debugging.md #13`

---

## ADR-17. 멀티턴 결론 추적 + 양방향 분기 안전장치

**결정**: `checklist_state`에 `concluded` 플래그 추가, `critical_factors` 기반 TYPE 2 단정 방지

**맥락**: 품질 테스트에서 2가지 Partial 패턴 식별
- C2: T2에서 결론 도달 후 T3에서 불필요 추가 질문(로열티/MG) 생성
- C1: 본인/대리인 양방향 분기에서 핵심 요소 미확인인데 TYPE 2 단정

**근거**:
- `concluded` 플래그: `is_conclusion=True` 시 세션에 저장 → 후속 턴에서 [결론 확인 모드] 주입
  → "추가 질문 없이 TYPE 2 확정 결론만 제시" 강제
- `7_critical_factors`: 양방향 분기 토픽(본인/대리인, 라이선싱 등)에 핵심 판단 요소 명시
  → `_validate_clarify()`에서 미확인 factor + TYPE 2 → ModelRetry
  → `_inject_clarify_system()`에서 [양방향 분기 안전장치] 프롬프트 주입

**참조**: `app/services/chat_service.py`, `app/agents.py`, `app/domain/decision_trees.py`

---

## ADR-18. ANALYZE_PROMPT 범위 밖 키워드 가드

**결정**: 타 기준서 전용 개념(증분차입이자율, 사용권자산 등)을 ANALYZE_PROMPT에 명시적 OUT 열거

**맥락**: C3 테스트에서 "증분차입이자율"(1116호)이 1115호 "금융요소"와 혼동되어 범위 밖 판정 실패 (1/3)

**근거**:
- 1116호(리스), 1109호(금융상품), 1037호(충당부채)의 전용 용어를 명시적 negative list로 관리
- 1115호와 교차하는 개념(금융요소, 유의적 금융요소)은 "IN" 유지
- LLM이 유사 용어를 구분하지 못하는 문제를 프롬프트 레벨에서 방어

**참조**: `app/prompts.py:ANALYZE_PROMPT`

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

---

## ADR-15. 외부 테이블 문단: 전처리 크롤링 + UI 테이블 행 보호

**결정**: 외부 `.htm` 테이블을 전처리 단계에서 크롤링·주입하고, UI에서 마크다운 테이블 행을 보호

**맥락**: IE 적용사례 ~29개 문단에 `data-file-name`으로 참조된 외부 테이블/분개가 깨져 표시됨

**근거**:
- `11-fix-external-tables.py`: 외부 .htm 크롤링 → `paraContent`에 `<table>` 주입 → 마크다운 테이블 변환 → MongoDB text 필드 갱신
- `_ensure_paragraph_breaks()`: 테이블 행(`|`로 시작) 사이 `\n`을 보호 마커로 치환하여 `\n→\n\n` 변환에서 제외
- `<th>` 없는 테이블: 빈 헤더 행을 삽입하여 첫 데이터 행이 볼드되지 않도록 처리

**교훈**: 외부 파일 참조는 전처리에서 해결. UI 정규식으로 깨진 데이터 복원은 불가.

**참조**: `app/preprocessing/11-fix-external-tables.py`, `app/ui/text.py`, `docs/debugging.md #21`

---

## ADR-16. topics.json 단일 파이프라인 (parse + split 통합)

**결정**: `10-parse-curation.py` 한 번 실행으로 24개 합산 토픽 파싱 + 7개 개별 토픽 분할까지 완료 → 최종 29개

**맥락**: 이전 2단계 파이프라인(`10-parse-curation.py` → `_add_topics.py`)에서 후속 스크립트 실행 누락이 반복 발생하여 UI가 깨지는 사고 재발

**근거**:
- `_split_merged_topics()` 함수를 `10-parse-curation.py`의 `main()` 끝에 통합
- 분할 데이터는 `_add_topics_data.py`(SPLIT_TOPICS, MERGED_KEYS)로 분리하여 importable 모듈로 관리
- `_add_topics.py`는 DEPRECATED — 별도 실행 불필요
- UI(`constants.py` HOME_TOPICS), decision_trees.py, summary-embeddings.json 모두 개별 토픽명 사용

**교훈**: 2단계 파이프라인은 반드시 누락 사고가 발생한다. 단일 스크립트로 통합하여 원천 차단.

**참조**: `app/preprocessing/10-parse-curation.py`, `app/preprocessing/_add_topics_data.py`

---

## ADR-19. topic_hints — LLM 기반 의미적 토픽 매칭 보완

**결정**: `AnalyzeResult`에 `topic_hints: list[str]` 필드를 추가하여, 키워드 매칭 실패 시에도 거래 실질 기반으로 토픽을 매칭

**맥락**: "A→B→C 재판매, A의 매출액은?" 같은 질문에서 "본인 vs 대리인" 토픽이 의미적으로 해당하지만, `trigger_keywords`에 "재판매"가 없어서 토픽 매칭 실패 → 핀포인트 문서(B34A, B37, 사례 47, QNA, 감리사례) 미검색

**근거**:
- 이미 호출 중인 analyze_agent의 structured output에 필드 1개 추가 → 추가 API 호출 0회, 토큰 증가 ~150개
- ANALYZE_PROMPT에 31개 토픽 목록을 명시하여 LLM이 허용된 토픽만 선택하도록 제한
- `tree_matcher.py`에서 `topic_hints` 가산점 5.0 (키워드 완전일치 3.0보다 높음) → 키워드 매칭 0이어도 hints에 포함되면 candidates 진입
- 하위 호환성 유지: `topic_hints`는 `default_factory=list`, `match_topics`의 파라미터는 `None` 기본값

**수정 파일**: `app/agents.py`, `app/prompts.py`, `app/domain/tree_matcher.py`, `app/nodes/analyze.py`

**참조**: `app/agents.py:AnalyzeResult.topic_hints`, `app/domain/tree_matcher.py:match_topics()`

---

## ADR-20. 감리사례 선별 보강 — 4_precedents 누락 5건 추가

**결정**: topics.json에 큐레이션된 감리사례 중 `4_precedents`에도 `5_red_flags`에도 없는 진짜 누락 5건을 `4_precedents`에 추가

**맥락**: 핀포인트 fetch는 `4_precedents`와 `5_red_flags` 텍스트에서 문서 ID를 파싱하여 MongoDB 원문을 직접 조회하는데, 감리사례가 어느 쪽에도 없으면 리트리버가 놓칠 때 "위험 경고" 기능이 작동하지 않음

**근거**:
- 감리사례는 **규제 리스크 문서** → 반드시 핀포인트 경로로 참조되어야 함
- QNA/IE는 리트리버 + `_format_topic_knowledge()` desc 요약으로 커버 가능하지만, 감리사례는 질문과 의미적 유사도가 낮아 리트리버가 놓칠 확률이 높음
- 나머지 18건은 이미 `5_red_flags`에서 핀포인트 파싱 대상이므로 추가 불필요

**추가 대상**:
| 감리사례 ID | 토픽 | 배치 분기 |
|------------|------|----------|
| FSS-CASE-2024-2505-02 | 계약의 식별 | [분기 2] 요건 미충족 |
| FSS-CASE-2025-2512-01 | 계약의 식별 | [분기 2] 요건 미충족 |
| FSS-CASE-2024-2505-03 | 본인 vs 대리인 + 반품권 | 각 토픽 해당 분기 |
| FSS-CASE-2024-2505-04 | 변동대가의 배분 | [분기 2] 비례 배분 |
| KICPA-CASE-2025-07 | 진행률 측정 | [분기 1] 일반 투입법 |

**참조 표기 규칙**: `4_precedents`는 `[대괄호]` 표기, `5_red_flags`는 `[대괄호]` 표기. retriever.py `_parse_doc_ids_from_text()`는 양쪽 모두 파싱.

**참조**: `app/domain/decision_trees.py`, `app/retriever.py:fetch_pinpoint_docs()`

---

## ADR-21. IE 적용사례 pinpoint: calc 경로에서만 제외 + 사례 단위 병합

**결정**: IE pinpoint 필터를 무조건 제외 → `needs_calculation=True`일 때만 제외로 변경. IE 문단을 사례 단위로 병합.

**맥락**: generate.py에서 IE pinpoint을 무조건 제외하여, 일반/상황 질문에서 IE 적용사례 원문이 LLM에 도달하지 못함. 또한 IE 사례 1건이 여러 문단(IE48, IE48A, IE48B...)으로 분리되어 `GENERATE_DOC_LIMIT` 슬롯을 과다 점유.

**근거**:
- calc 경로: IE 원문이 슬롯을 차지하면 산술 문맥이 밀려남 → 제외 유지
- 일반/상황 질문: IE 사례가 핵심 근거 → LLM에 전달 필수
- 사례 병합: `_fetch_ie_case_chunks()`에서 같은 사례의 문단들을 하나의 doc으로 합침 (47개 문단 → 8개 사례)
- 병합 doc의 chunk_id: `1115-IE-case-{사례번호}`, `_merged_chunk_ids`에 원본 ID 보존

**참조**: `app/nodes/generate.py:95-109`, `app/retriever.py:_fetch_ie_case_chunks()`

---

## ADR-22. 핀포인트 파싱 3중 Gap 수정

**결정**: `_parse_doc_ids_from_text()`와 `fetch_pinpoint_docs()`의 3가지 누락 문제 수정

**맥락**: decision_trees.py 섹션별로 참조 형식이 다르지만, 파서가 section 4/5의 `[대괄호]`만 처리하여 section 2/7의 참조가 누락

**근거**:

| Gap | 원인 | 수정 |
|-----|------|------|
| 소괄호 미파싱 | section 2 checklist는 `(QNA-xxx)` 소괄호 사용 | 대괄호 + 소괄호 양쪽 파싱 추가 |
| 축약 ID 불일치 | section 2에서 `FSS-2022-...` 사용, DB는 `FSS-CASE-2022-...` | `FSS-`→`FSS-CASE-`, `KICPA-`→`KICPA-CASE-` 자동 정규화 |
| critical_factors 미수집 | `fetch_pinpoint_docs()`가 section 7 텍스트 미수집 | `checklist`(리스트) + `critical_factors` 수집 추가 |

**검증**: "본인 vs 대리인" 토픽에서 `(FSS-2022-2311-03)` → `FSS-CASE-2022-2311-03` 정상 파싱, `(문단 B37⑴)` → `B37` 파싱 확인

**참조**: `app/retriever.py:_parse_doc_ids_from_text()`, `app/retriever.py:fetch_pinpoint_docs()`

---

## ADR-23. 토픽 임베딩 기반 의미적 매칭 (tree_matcher 3중 매칭)

**결정**: tree_matcher에 토픽 임베딩 코사인 유사도를 3번째 스코어링 신호로 추가

**맥락**: ADR-19의 `topic_hints`(LLM 기반)만으로는 일상 언어 질문에서 토픽 매칭 불안정. T1 "A→B→C 재판매" 질문을 3회 실행 시 "본인 vs 대리인"이 한 번도 hints에 포함되지 않음.

**근거**:
- **3중 매칭 구조**: keyword 매칭 + topic_hints(LLM) + 임베딩 유사도
- 각 토픽의 `judgment_goal + trigger_keywords + checklist + summary`를 사전 임베딩 (passage 모델, 4096차원)
- 쿼리 시점에 `embed_query_sync()` 1회 호출 (~100ms) → 31개 토픽과 코사인 유사도 계산
- 임베딩 텍스트에 trigger_keywords 포함 → 추상적 goal만 쓸 때 15위였던 "본인 vs 대리인"이 1위로 상승
- `_EMBED_THRESHOLD=0.28`, `_EMBED_WEIGHT=10.0` — Upstage 절대 유사도가 0.29~0.47 범위로 낮으므로 보수적 임계값

**성능 테스트 (8개 질문)**:
- 정답 토픽 1위: 5/8 (62%)
- 정답 토픽 top 3: 7/8 (87%)
- keyword + hints + 임베딩 합산 시 T1 "본인 vs 대리인" top 3 진입 확인

**전처리**: `app/preprocessing/13-topic-embed.py` → `data/topic-curation/topic-embeddings.json`

**참조**: `app/domain/tree_matcher.py`, `app/domain/summary_matcher.py:cosine_similarity()`

---

## ADR-24. pinpoint 미인용 문서를 "참고하면 좋은 추가 문서"로 표시

**결정**: pinpoint(큐레이션) 미인용 문서를 각 섹션의 "참고하면 좋은 추가 문서" 더보기에 배치

**맥락**: pinpoint으로 fetch된 QNA/감리/IE(10~15건)가 LLM context에는 주입되지만, AI가 인용하지 않으면 UI에서 완전히 사라짐

**근거**:
- `DocResult`에 `chunk_type` 필드 추가 → SSE → Streamlit까지 전달
- `_prepare_ai_answer_docs()`에서 pinpoint 미인용 문서를 `_supp_by_group`에 추가
- pinpoint(score=1.0)이 retriever 문서보다 우선 정렬, 소스별 최대 5건
- 메인 docs 리스트에 직접 추가 시 DuplicateElementKey + 그룹 혼선 → 기존 "더보기" 경로 활용

**표시 계층**:
1. AI 인용 문서 → 메인 표시
2. pinpoint 미인용 + retriever 미인용 → "📂 참고하면 좋은 추가 문서" (pinpoint 우선)

**참조**: `app/api/schemas.py:DocResult`, `app/ui/evidence.py`, `docs/debugging.md #35, #36`

---

## ADR-25. source 문자열 + ID 접두어 중앙화 + 데이터 파이프라인 교차 검증

**결정**: source 문자열과 document ID 접두어를 `constants.py`에 상수로 중앙화. 데이터 파이프라인에 교차 검증 함수 추가.

**맥락**: `"본문"`, `"적용지침B"`, `"질의회신"` 등의 source 문자열이 10+파일에 하드코딩. `"QNA-"`, `"FSS-"` 등의 ID 접두어도 retriever, db, evidence에 분산.

**근거**:
- source 문자열 한 곳 변경 시 나머지가 미변경되어 ACCORDION_GROUPS 그룹핑 실패
- `SRC_BODY`, `SRC_IE`, `DOC_PREFIX_QNA` 등 상수를 `constants.py`에 정의
- 주요 소비자(evidence.py, grouping.py, doc_helpers.py, retriever.py, db.py)에서 import 사용
- summary-embeddings.json, topic-embeddings.json에 orphaned 데이터 4+2건 발견
- `verify_data_consistency()` 함수로 topics.json ↔ 임베딩 파일 간 ID 교차 검증

**Trade-off**: 전처리 스크립트, 테스트 파일에는 아직 하드코딩 잔류 (자주 변경되지 않는 파일이라 우선순위 낮음)

**참조**: `app/ui/constants.py`, `app/preprocessing/10-parse-curation.py:verify_data_consistency()`, `docs/debugging.md #40`

---

## ADR-26. AI 답변 좌측 패널 — IE/QNA/감리 표시 아키텍처

**결정**: AI 답변 좌측 근거 패널에 IE 사례, QNA 질의회신, 감리사례를 3계층으로 표시

**맥락**: 기존에는 AI 인용 본문/적용지침만 표시. pinpoint으로 fetch된 QNA/감리/IE(10~40건)가 LLM context에 주입되었으나 UI에서 완전히 보이지 않음.

**구현**:
1. `DocResult`에 `chunk_type` 필드 추가 → SSE로 "pinpoint" 식별 전달
2. IE pinpoint의 source를 "적용사례IE"로 설정 (ACCORDION_GROUPS 매칭)
3. `_prepare_ai_answer_docs()`: pinpoint 미인용 문서를 `_supp_by_group`에 추가
4. 그룹 0건이어도 더보기만 있으면 렌더링
5. `fetch_ie_case_docs`: MongoDB Atlas 한글 $regex 우회 (Python prefix + $or)
6. AI 인용 IE 사례: 📌 볼드 + 자동 펼침 + desc 표시

**표시 계층**:
- ① AI 인용 → 메인 (볼드, 펼침)
- ② pinpoint 미인용 + retriever → "참고하면 좋은 추가 문서" 더보기

**참조**: `docs/debugging.md #41`

---

## ADR-26. Gemini thinking_level: high → medium 전환

**결정**: generate_agent, clarify_agent의 `thinking_level`을 `high`에서 `medium`으로 변경

**맥락**: 26개 품질 테스트(×3회=78회) 결과 Pass 21/Partial 5/Fail 0. Partial 5건의 근본 원인이 Gemini thinking=high의 과도한 reasoning path 비결정성이었음.

**A/B 테스트 결과** (Partial 5건 × 5회):

| 지표 | high (3회) | medium (5회) |
|------|-----------|-------------|
| 꼬리질문 일관성 | 60% | **100%** |
| 토픽 매칭 안정화 | 40% | **80%+** |
| 품질 손실 | — | **없음** |
| 에러 | 1건 생성오류 | 1건 타임아웃 |

**핵심 발견**:
- thinking=high에서 과도한 추론이 오히려 불필요한 분기를 생성 → 같은 질문에 즉답/꼬리질문 갈림
- SECTION-19: high에서 2/3 불필요 꼬리질문 생성 vs medium 5/5 정확한 즉답
- TEST-0: high에서 2/3 통제권 미확인 즉답 vs medium 5/5 꼬리질문 안정화

**변경 파일**: `agents.py` (generate_agent, clarify_agent model_settings)

---

## ADR-32. 실사용 데이터 수집 + 자동 품질 채점 시스템

**결정**: 매 채팅 응답마다 MongoDB `usage_logs`에 자동 로깅 + 규칙 기반 4개 메트릭 인라인 채점. 사용자 피드백(👍/👎 + 사유)과 LLM 심화 채점(3개 메트릭)을 선택적으로 추가.

**맥락**: 골든 테스트 53건(ADR-30)은 개발자 설계 시나리오로 회귀 방지에 효과적이나, 실사용자의 질문 패턴·만족도·실패 케이스는 파악 불가

**구현 구조**:

```
사용자 질문 → pipeline done → usage_logger.log_chat_response()
                                ├─ MongoDB에 로그 저장 (질문, 답변, 토픽, 인용 등)
                                └─ 규칙 기반 4개 메트릭 자동 채점 (~1ms, UX 무영향)
                                        ↓
                                log_id를 SSE로 클라이언트에 전달
                                        ↓
                                👍/👎 버튼 → POST /feedback (사유 포함)
```

**채점 메트릭 7개**:

| 구분 | 메트릭 | 실행 시점 |
|------|--------|-----------|
| 규칙 기반 | 응답 속도, 인용 커버리지, 토픽 매칭, 결론 신중성 | 매 응답 자동 (인라인) |
| LLM 기반 | 근거 충실도, 답변 적절성, 답변 완전성 | `--with-llm` 수동 실행 |

**핵심 설계 판단**:
- 규칙 기반 채점을 `usage_logger.py`에 인라인 → 별도 배치 스크립트 불필요, 미채점 건 원천 방지
- LLM 채점은 건당 3회 API 호출(~$0.001) → 트래픽 규모에 맞춰 선택적 실행
- `yield event` 전에 `log_id` 주입 (yield 후 수정은 SSE에 반영 안 됨 — 초기 버그)
- 👎 클릭 시 사유 입력 단계 추가 → `feedback_reason` 필드로 저장 (최대 500자)

**참조**: `app/services/usage_logger.py`, `app/api/routes.py:/feedback`, `app/ui/pages.py`, `usage-data-collecting/overview.md`

---

## ADR-33. clarify_agent 사용자 명시 정보 무시 + 비용 처리 오답 수정

**결정**: 3건 동시 수정 — ① CLARIFY_SYSTEM 규칙 5 추가, ② provided_info→체크리스트 직접 반영, ③ 위탁약정·본인vs대리인 비용 처리 분기 추가

**맥락**: "통제권은 내가 가지고 있는데 수익인식이 아니라 비용 어떻게 해야 하나?" 질문에서 3중 오답 발생
- 이미 명시한 팩트(통제권 보유)를 재질문
- 수익인식 관점으로만 답변 (비용 처리 무시)
- 정답(통제권 有→재고자산 가산, 無→판관비)을 제시하지 않음

**근본 원인**:
- provided_info가 체크리스트와 분리되어 LLM이 체크리스트를 그대로 따라감
- CLARIFY_SYSTEM에 사용자 단정 팩트 존중 규칙 없음
- conclusion_guide에 비용 처리 분기 자체가 없음

**수정 내용**:
1. `app/prompts.py`: `<checklist_strategy>` 규칙 5 — 사용자 단정 팩트 재질문 금지, ✅ 항목 확인 완료 취급, 질문 범위(비용 처리) 집중
2. `app/agents.py`: `_mark_provided_in_checklist()` — provided_info 키워드(3글자↑)를 체크리스트 번호 라인에 매칭하여 `✅ [사용자 확인 완료]` 표시 주입. `_inject_clarify_system()`에서 호출
3. `app/domain/decision_trees.py`: 위탁약정 분기 3/4(통제→재고자산 가산, 미통제→판관비), 본인vs대리인 분기 4/5(본인→매출원가, 대리인→판관비) 추가

**핵심 로직 흐름**: analyze_agent `provided_info` → `_mark_provided_in_checklist()`가 체크리스트에 ✅ 표시 → CLARIFY_SYSTEM 규칙 5가 재질문 금지 + 범위 집중 → conclusion_guide 비용 분기로 정답 제시

**참조**: `app/prompts.py:177~182`, `app/agents.py:343~378`, `app/domain/decision_trees.py`

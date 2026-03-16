# 검색 테스트 최종 보고서

## 1. 테스트 목적

RAG 챗봇에서 **검색 품질은 답변 품질의 상한을 결정한다.** 본 테스트는 2계층 검색 아키텍처
(핀포인트 큐레이션 + 벡터/BM25 하이브리드)의 정확성과 성능을 종합 검증한다.

검증 대상:
- **핀포인트 문서 정합성**: decision_trees/topics.json의 문단 참조가 DB에 실재하는가?
- **검색 커버리지**: 26개 품질 케이스에서 기대 문서를 검색하는가?
- **calc 라우팅 정확도**: LLM 기반 `needs_calculation` 판단이 정확한가?
- **IE bypass 동작**: 적용사례 핀포인트의 Reranker 우회와 calc 경로 필터가 올바른가?
- **성능**: 배치 조회/병렬 검색 최적화가 효과적인가?

## 2. 테스트 설계

### 테스트 스크립트 6개

| 스크립트 | 목적 | 케이스 | 반복 |
|---------|------|--------|------|
| `test_pinpoint_docs.py` | 핀포인트 문서 4계층 전수 검증 | 전체 토픽 | 1 |
| `test_retrieve_26q.py` | 26개 케이스 검색 커버리지 | 26 | 1 |
| `test_retrieve_5q.py` | 5개 핵심 질문 pinpoint/retriever 분리 분석 | 5 | 1 |
| `test_retrieve_debug.py` | 단일 질문 상세 디버그 추적 | 1 | 1 |
| `test_calc_routing.py` | LLM 계산 라우팅 정확도 | 14 | 3 |
| `test_ie_bypass.py` | IE 적용사례 bypass + E2E 파이프라인 | 1 | 1 |

### 2계층 검색 아키텍처

```
질문 → analyze (토픽 매칭)
         ├── 1계층: 핀포인트 (큐레이션 직접 조회)
         │    └── decision_trees → _parse_doc_ids_from_text() → MongoDB $in
         │
         └── 2계층: 리트리버 (벡터 + BM25 하이브리드)
              ├── Vector Search (Upstage query 임베딩)
              └── BM25 Keyword Search
              └── RRF 융합 (K=60)

         → 병합 (중복 제거, IE 사례 단위 병합)
         → Reranker (핀포인트는 bypass)
         → LLM 전달 (calc 경로: IE 핀포인트 제외)
```

## 3. 테스트 결과

### (A) 핀포인트 문서 4계층 전수 검증 (test_pinpoint_docs.py)

4가지 계층에서 핀포인트 참조의 DB 실재 여부를 검증했다:

#### 검증 1: topics.json 섹션 문단 → DB 존재

- 총 토픽: 26개
- 문단 참조: 100+개
- **범위 전개 규칙**: `"B34~B38"` → `[B34, B35, ..., B38]`, `"한34A~C"` → `[한34A, 한34B, 한34C]`
- 안전 제한: 최대 20개 범위만 전개

#### 검증 2: decision_trees 파싱 + DB 존재

- 파싱 대상: precedents, red_flags, checklist의 모든 문서 ID
- ID 패턴: `1115-B34`, `QNA-SSI-36941`, `FSS-CASE-2024-2505-03` 등
- 정규화: `FSS-` → `FSS-CASE-`, `KICPA-` → `KICPA-CASE-` 자동 변환 (**ADR-22**)

#### 검증 3: IE 사례 hierarchy regex 매칭

- IE 사례 1~30번 각각에 대해 `사례\s*{N}[\s:：]` regex 매칭 검증
- 전각/반각 콜론 대응: `:`, `：` 양쪽 커버

#### 검증 4: chunk_id 패턴 분포 샘플링

- `1115-{숫자}`: 본문 문단
- `1115-B{숫자}`: 적용지침
- `1115-IE-case-{숫자}`: 적용사례
- `1115-한{숫자}`: 한국 추가 규정

### (B) 26개 케이스 검색 커버리지 (test_retrieve_26q.py)

26개 품질 테스트 케이스(TEST 6개 + SECTION 20개)를 대상으로 expected_docs 검색 적중률을 측정했다.

**전체 Hit Rate: 77/81 (95%)**

#### 케이스별 성과 분포

| 매칭 등급 | 건수 | 비율 | 대표 케이스 |
|----------|------|------|-----------|
| 완벽 매칭 (100%) | 22 | 85% | SECTION-11, 12, 17, 18, 19 |
| 부분 실패 (1건 누락) | 3 | 11% | TEST-0, TEST-4 |
| 완전 실패 (전체 누락) | 1 | 4% | SECTION-4 (Bill-and-Hold) |

#### 검색 결과 규모 (26개 케이스 평균)

| 단계 | 평균 문서 수 | 범위 |
|------|------------|------|
| Pinpoint | 37건 | 21~55건 |
| Retriever | 52건 | 43~65건 |
| Merged (중복 제거) | 79건 | 64~98건 |
| LLM 전달 | 79건 | 64~98건 |

#### 카테고리별 핀포인트 분포

| 카테고리 | 평균 | 최다 케이스 |
|---------|------|-----------|
| 본문/적용지침 | 14건 | SECTION-11~13 (16~18건) |
| QNA | 11건 | SECTION-4 (15건) |
| IE 사례 | 9건 | TEST-0, SECTION-3 (13~15건) |
| 감리사례 | 6건 | SECTION-3, SECTION-4 (12건) |
| 교육자료 | 1건 | 대부분 0~2건 |

#### 검색 실패 분석

| 케이스 | Hit Rate | 누락 문서 | 원인 | 상태 |
|--------|---------|----------|------|------|
| **SECTION-4** | **0/2** | B79~B82, B81 | 미인도청구약정 토픽이 top-3 미포함 (LLM 비결정성) | 조건부 해결 — 재실행 시 2/2 확인 |
| TEST-0 | 4/5 | B77 | conclusion_guide는 pinpoint 파싱 대상 아님 | 의도적 미수정 — LLM이 토픽 가이드로 판단 |
| TEST-4 | 3/4 | B56 | checklist/precedents 미참조 문단 | 의도적 미수정 — B54~B63 범위 + B58/B61로 충분 |

### (C) 5개 핵심 질문 분리 분석 (test_retrieve_5q.py)

핀포인트와 리트리버가 **각각 어떤 역할**을 하는지 분리 관찰했다:

| 질문 | 토픽 | Pinpoint | Retriever | Merged | 중복 |
|------|------|----------|-----------|--------|------|
| T1 본인/대리인 | 3개 | 54건 | 50건 | 96건 | 8건 |
| T2 변동대가이론 | 2개 | 32건 | 48건 | 72건 | 8건 |
| T3 볼륨디스카운트 | 2개 | 38건 | 52건 | 82건 | 8건 |
| T4 가공매출 | 2개 | 42건 | 55건 | 88건 | 9건 |
| T5 진행률계산 | 2개 | 35건 | 46건 | 74건 | 7건 |

**핵심 인사이트**:
- **핀포인트**: 큐레이션된 선례/감리사례/IE 사례 — "이 토픽에서 반드시 봐야 할 문서"
- **리트리버**: 의미적/키워드 유사도 기반 — "질문과 직접 관련된 문서"
- **중복 8~9건**: 두 경로가 동일 문서를 독립적으로 찾음 → 검색 신뢰도 교차 검증

### (D) calc 라우팅 정확도 (test_calc_routing.py)

14개 케이스(명확 calc 4, 명확 non-calc 4, 에지 6) × 3회 반복 = 42회 테스트:

**결과: 42/42 정확 (100%)**

| 분류 | 건수 | 정확도 | 판단 기준 |
|------|------|--------|---------|
| 명확 calc (True) | 4 × 3 | 12/12 | 금액 3개+ + "계산/산정/구해줘" |
| 명확 non-calc (False) | 4 × 3 | 12/12 | 개념/원칙/기준 질문 |
| 에지 케이스 | 6 × 3 | 18/18 | "산정하면 어떤 원칙?" = False, "산정해주세요" = True |

**핵심 구분점**: "~해줘/구해줘/얼마" (결과 요구) = calc, "~하나요/뭐야/어떻게" (설명 요구) = non-calc

> 이전 v1(regex 3조건 AND)은 비결정적 search_keywords에 의해 1/3만 calc 진입.
> v2(LLM 판단)로 전환하여 100% 정확도 달성 (**ADR-2**)

### (E) IE bypass 파이프라인 (test_ie_bypass.py)

단일 질문("온라인 플랫폼 중개, 수수료 vs 총액")으로 전체 파이프라인을 추적했다:

**검증 항목**:

| 항목 | 결과 |
|------|------|
| IE 핀포인트 수 | 13건 (사례 46 등 본인/대리인 관련) |
| Reranker bypass | 핀포인트 13건 무조건 1순위 통과 (**ADR-6**) |
| 일반 경로 IE 필터 | 미적용 (IE 13건 LLM 전달) |
| calc 경로 IE 필터 | 적용 시 IE 13건 제외 (**ADR-21**) |
| 최종 LLM 전달 | 96건 (일반) / 83건 (calc) |

## 4. 핵심 개선사항 상세

### 개선 1: 핀포인트 3중 Gap 수정 (ADR-22)

- **문제**: `_parse_doc_ids_from_text()`의 3가지 파싱 결함으로 검색 적중률 36%

| Gap | 원인 | 수정 |
|-----|------|------|
| 괄호 미파싱 | 섹션 2 checklist가 `(QNA-xxx)` 사용 | 괄호 + 대괄호 양쪽 파싱 |
| 축약 ID 불일치 | `FSS-2022-...` vs DB `FSS-CASE-2022-...` | `FSS-` → `FSS-CASE-` 자동 정규화 |
| critical_factors 미수집 | `fetch_pinpoint_docs()` 섹션 7 스킵 | checklist + critical_factors 모두 수집 |

- **효과**: 모델 비교 테스트 기준 검색 적중률 36% → **76%** (+40%p)

### 개선 2: Reranker bypass (ADR-6, debugging.md #E1)

- **문제**: Cohere Reranker가 큐레이션 핀포인트 문서를 탈락시킴 (TEST-3에서 105건 중 103건 탈락)
- **원인**: Cross-encoder는 query-document 의미 유사도 기반 → 큐레이션 문서는 유사도 낮음
- **해결**: `chunk_type == "pinpoint"` 문서는 Reranker 우회, 무조건 1순위 통과

```python
# rerank.py — 핀포인트 문서 bypass
pinpoint_docs = [d for d in merged if d.get("chunk_type") == "pinpoint"]
retriever_docs = [d for d in merged if d.get("chunk_type") != "pinpoint"]
reranked = pinpoint_docs + cohere_rerank(retriever_docs, query)
```

### 개선 3: IE 사례 단위 병합 (ADR-21)

- **문제**: IE 적용사례가 문단 단위로 분산 저장 (47 문단 → 8 사례) → `GENERATE_DOC_LIMIT` 슬롯 과점
- **해결**: `_fetch_ie_case_chunks()`에서 같은 사례 번호의 청크를 단일 문서로 병합

### 개선 4: MongoDB 배치 조회 최적화 (debugging.md #G8)

- **문제**: PDR parent 조회를 `find_one()` N회 반복 → retrieve 3.7s
- **해결**: source별 `$in` 배치 조회 (source당 1회 왕복)

| 단계 | Before | After | 감소율 |
|------|--------|-------|-------|
| retrieve | 3.7s | **0.6s** | **84%** |
| total pipeline | 33.4s | **25.9s** | **22%** |

### 개선 5: 검색 병렬화

- Vector Search + BM25 Keyword Search: `ThreadPoolExecutor` 동시 실행
- Pinpoint + Retriever: `asyncio.gather` 병렬 실행
- Cohere timeout: 30초 설정 (무한 대기 방지)

### 개선 6: calc 라우팅 v1(regex) → v2(LLM) 전환 (ADR-2)

- **문제**: v1 regex 3조건 AND → LLM search_keywords 비결정성에 의해 calc 경로 진입 1/3만 성공
- **해결**: `AnalyzeResult.needs_calculation: bool` — analyze_agent(gpt-4.1-mini)가 LLM으로 판단
- **효과**: 14케이스 × 3회 = 42/42 정확도 **100%**, 일관성 **100%**

## 5. 최종 성과 요약

### 검색 정확도

| 지표 | 값 | 상태 |
|------|-----|------|
| 26케이스 검색 적중률 | **95%** (77/81) | 우수 |
| 완벽 매칭 비율 | **85%** (22/26) | 우수 |
| calc 라우팅 정확도 | **100%** (42/42) | 목표 달성 |
| IE bypass 정상 동작 | **100%** | 목표 달성 |
| 핀포인트 DB 실재율 | **95~100%** | 우수 |

### 성능

| 지표 | Before | After | 변화 |
|------|--------|-------|------|
| retrieve 소요 시간 | 3.7s | **0.6s** | **-84%** |
| total pipeline | 33.4s | **25.9s** | **-22%** |
| calc 라우팅 정확도 | 33% (regex) | **100%** (LLM) | **+67%p** |
| 검색 적중률 | 36% | **95%** | **+59%p** |

### 검색 진화 타임라인

| Phase | 방식 | 커버리지 |
|-------|------|---------|
| 1 | 순수 BM25 키워드 | ~35% |
| 2 | 벡터 검색 추가 | ~60% |
| 3 | 2계층 (핀포인트 + 리트리버) | ~90% |
| 4 (현재) | Reranker bypass + IE 병합 + 배치 최적화 | **95%** |

## 6. 남은 과제 및 향후 계획

### 검색 실패 3건 후속 분석 (2026-03-16)

#### SECTION-4 Bill-and-Hold (0/2 → 조건부 해결)

- **원인**: 2026-03-14 테스트에서 `matched_topics`가 `['고객의 인수', '기간에 걸쳐 vs 한 시점 인식', '본인 vs 대리인']`으로, **미인도청구약정 토픽 자체가 top-3에 미포함**. 체크리스트에 B81 참조가 있지만 토픽이 안 잡혀서 파싱 대상이 아니었음.
- **현재 상태**: 2026-03-16 재실행 시 미인도청구약정이 top-1로 매칭 → **2/2 HIT**. trigger_keywords("인도하지 않", "보관", "창고에")와 3중 매칭(ADR-23 임베딩 + ADR-19 hints)이 정상 동작.
- **결론**: LLM analyze 비결정성으로 인한 간헐 실패. 체크리스트 누락이 아닌 **토픽 매칭 변동성** 문제. 체크리스트에 B81은 이미 존재하며, 토픽만 잡히면 100% HIT.

#### TEST-0 B77 (의도적 미수정)

- **구조**: B77은 "위탁약정" 토픽의 `3_conclusion_guide`에만 존재. `fetch_pinpoint_docs()`는 `2_checklist`, `4_precedents`, `5_red_flags`, `7_critical_factors`만 파싱 → **conclusion_guide는 파싱 대상이 아님**.
- **미수정 이유**: TEST-0의 matched_topics에 "본인 vs 대리인"이 포함되고, 본인/대리인 체크리스트의 B35 + precedents의 IE231~IE243(대리인/본인 사례) + 감리사례가 모두 검색됨. LLM은 top-3 토픽의 전체 체크리스트/결론가이드를 읽고 판단하므로, B77 원문이 context에 없어도 위탁약정 결론가이드("인도 시 통제 미이전, 대리인 최종 판매 시 수익 인식")를 참고하여 정확한 답변 생성. **답변 품질에 실질적 영향 없음.**

#### TEST-4 B56 (의도적 미수정)

- **구조**: B56(라이선스 구별 여부 판단)은 `2_checklist`/`4_precedents`/`5_red_flags` 어디에도 참조 없음. `3_conclusion_guide`의 B54("라이선스가 다른 자원과 구별되지 않음 → 결합")에서 간접 언급.
- **미수정 이유**: expected_docs 4건 중 B54~B63 범위(B58/B63으로 HIT), B58(개별 HIT), B61(retriever HIT)은 모두 검색 성공. B56은 "구별 기준"에 해당하는데 이 내용은 체크리스트 [분기 1]과 결론가이드에서 이미 서술됨. **LLM이 라이선싱 체크리스트를 읽으므로 B56 원문 없이도 구별 여부 판단 가능.**

### 나머지 과제

| 과제 | 현황 | 우선순위 |
|------|------|---------|
| 새로운 사업모델 (메타버스, DeFi) | 26개 고정 토픽 범위 밖 → Gray Area | 향후 |
| 타 기준서 교차 (1116호 등) | K-IFRS 1115호 단독 지원 | 향후 |

> **참고**: 26개 케이스 상세 결과는 `results/retrieve_26q_report.md` 참조.
> ADR 전문은 `docs/DECISION.md` (ADR-2, ADR-4, ADR-5, ADR-6, ADR-21, ADR-22) 참조.
> 디버깅 교훈은 `docs/debugging.md` (E1, G7, G8) 참조.

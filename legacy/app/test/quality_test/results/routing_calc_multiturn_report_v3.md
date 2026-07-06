# 라우팅/계산/멀티턴 품질 테스트 리포트 v3

**실행일**: 2026-03-14
**테스트**: 10개 케이스 × 3회 = 30회 호출 (멀티턴 포함 총 42회)

---

## 1. v2 → v3 비교

| 등급 | v2 | v3 |
|------|-----|-----|
| **Pass** | 4 | **9** |
| **Partial** | 5 | **1** |
| **Fail** | 1 | **0** |

### 적용한 개선 5건

| # | 개선 내용 | 대상 | v2 → v3 | 변경 파일 |
|---|----------|------|---------|----------|
| 1 | concluded 후 follow_up 강제 제거 | C2 | follow_up 3/3 생성 → 0/3 | generate.py, agents.py |
| 2 | needs_calculation 세션 영속화 | B1/B2 | 2/3 정확 → 3/3 | chat_service.py, prompts.py |
| 3 | 반품 매출원가/회수권 공식 보강 | B3 | 매출원가 0/3 → 3/3 + 분개 | decision_trees.py, prompts.py |
| 4 | critical_factors 매칭 범위 확대 | C1 | TYPE 2 과잉 차단 → 2/3 결론 | agents.py, generate.py |
| 5 | 범위 밖 감지 강화 (_HARD_OUT_TERMS) | C3 | IN 3/3 → OUT 3/3 | prompts.py, analyze.py |

### 세션 중 발견·수정한 버그

- **NoneType `.get()` 트랩**: `state.get("checklist_state", {}).get(...)` → `(state.get("checklist_state") or {}).get(...)`
  - Python `dict.get(key, default)`는 key가 존재하고 값이 `None`이면 `default`가 아닌 `None`을 반환
  - `_build_initial_state`에서 `"checklist_state": None` 명시 설정 → 29/40 테스트 실패 유발

---

## 2. 종합 등급표

| 케이스 | 제목 | 유형 | 평균시간 | 등급 |
|--------|------|------|---------|------|
| A1 | 개념 질문 → generate 경로 | 싱글 | 15.1s | **Pass** |
| A2 | 거래 상황 질문 → clarify 경로 | 싱글 | 25.8s | **Pass** |
| A3 | 계산 명령 → calc 경로 | 싱글 | 18.8s | **Pass** |
| A4 | 계산처럼 보이지만 판단 질문 | 싱글 | 34.0s | **Pass** |
| B1 | 진행률 측정 — 미설치 고가 자재 제외 | 싱글 | 20.0s | **Pass** |
| B2 | 변동대가 기댓값 산출 | 싱글 | 17.6s | **Pass** |
| B3 | 반품권 환불부채 + 회수권 | 싱글 | 19.8s | **Pass** |
| C1 | 본인 vs 대리인 — 2턴 | 멀티턴 | 31.6s | **Partial** |
| C2 | 라이선싱 접근권 vs 사용권 — 3턴 | 멀티턴 | 39.0s | **Pass** |
| C3 | 범위 밖 → 정상 복귀 — 2턴 | 멀티턴 | 8.3s | **Pass** |

---

## 3. 잔여 문제점

### 3.1 C1 — Partial (유일한 미완전 케이스)

**현상**: 3회 중 1회에서 T2 generate 에러 발생 → 2/3만 조건부 결론 도달

**원인 분석**:
- 개선 4(critical_factors 매칭 확대)로 TYPE 2 과잉 차단은 해소되었으나, T2에서 generate_agent 호출 시 간헐적 에러 잔존
- 사용자가 "재고위험도 저희가 부담" 등 복수 factor를 한 턴에 제공 → factor 인식 정확도는 올랐지만 LLM 생성 안정성 미달

**개선 방향**:
- generate_agent의 에러 핸들링 보강 (재시도 로직 또는 fallback)
- T2 context가 너무 길어지면 토큰 초과 가능성 → context 압축 검토

---

### 3.2 B1 Run 3 — 타임아웃 (1/3)

**현상**: Cohere Reranker API 429 (Too Many Requests) → 타임아웃

**원인**: 외부 API 레이트 리밋. 코드 버그 아님 — 기존 fallback 로직(rerank 스킵)은 있으나, 전체 파이프라인이 180초 제한 내에 미복구

**개선 방향**:
- Reranker 429 시 즉시 fallback (현재 재시도 대기 시간이 긴 것으로 추정)
- 테스트 간 API 호출 간격 조절 (rate limit 회피)

---

### 3.3 A4 — 응답 시간 편차

**현상**: [26.2s, **44.3s**, 31.5s] — Run 2가 69% 느림

**원인**: calc 아닌 경로(Gemini Flash thinking=high)에서 복잡한 상황 판단 시 thinking 시간 편차 발생

**영향**: 기능적 문제 없음. UX 측면에서 응답 지연 체감 가능

---

### 3.4 응답 일관성 문제 (전체)

**인용문헌 수 편차**:
```
A1: [4, 5, 6]개    A3: [4, 4, 3]개    B2: [3, 4, 7]개
A2: [7, 6, 6]개    B1: [4, 9, 0]개    B3: [6, 4, 7]개
```

**답변 길이 편차**:
```
A3: [560, 872, 836]자   — Run 1이 56% 짧음 (calc 경로 불완전 의심)
A4: [1263, 1511, 1610]자 — 최대 27% 차이
B2: [631, 692, 855]자    — Run 3이 35% 길음
```

**원인 분석**:
1. **Retrieval 비결정성**: 같은 쿼리에 대해 벡터 검색 + Reranker 결과 편차 → 인용 문헌 수 불일치
2. **LLM 생성 편차**: Gemini Flash/gpt-4.1-mini의 temperature > 0에서 답변 길이·포맷 편차
3. **A3 Run 1 특이점**: calc 경로에서 560자로 유의미하게 짧음 → 계산 과정 일부 누락 가능성

**개선 방향**:
- calc 경로 답변 최소 길이 검증 (structured output에 min_length 제약 추가 검토)
- Retrieval 단계 seed 고정 또는 top-k 결과 안정화
- 인용 편차가 답변 품질에 미치는 영향 추가 분석 필요

---

## 4. 추가 개선 우선순위

| 순서 | 대상 | 문제 | 예상 난이도 | 영향도 |
|------|------|------|-----------|--------|
| 1 | C1 | generate 에러 1/3 → 안정화 | 중 | Pass 승격 |
| 2 | A3 | calc 답변 길이 편차 (560자 vs 870자) | 낮 | 답변 완성도 |
| 3 | B1 | Reranker 429 타임아웃 | 낮 | 안정성 |
| 4 | 전체 | 인용문헌 수 일관성 | 높 | 신뢰성 |
| 5 | 전체 | 응답 시간 편차 축소 | 높 | UX |

# 실사용 데이터 수집 시스템

> 최종 업데이트: 2026-03-16

## 1. 왜 만들었나

골든 테스트 53건으로 **규칙 기반 회귀 방지 기준선**을 확보했다 (ADR-30).
하지만 골든 테스트는 개발자가 설계한 시나리오일 뿐이고, 실제 사용자가 어떤 질문을 하고, 어떤 답변에 만족/불만족하는지는 알 수 없다.

실사용 데이터가 있으면:
- **자주 묻는 질문** 패턴 → 토픽/키워드 커버리지 보강 우선순위 결정
- **👎 피드백 + 사유** → 골든셋에 추가하여 회귀 방지 강화
- **자동 채점 점수** → 시스템 품질 추이를 정량적으로 추적
- **포트폴리오 어필** → "운영 후 데이터 기반 개선 사이클" 증명

---

## 2. 무엇이 저장되나

### 자동 저장 (사용자가 질문할 때마다)

사용자가 `/chat`으로 질문을 보내면, AI 답변이 완성되는 시점에
`usage_logger.py`가 **로그 + 규칙 기반 자동 채점**을 동시에 MongoDB `usage_logs`에 저장한다.

| 필드 | 예시 | 설명 |
|------|------|------|
| `question` | "반품권이 있는 판매에서 수익 인식 시점은?" | 사용자 질문 원문 |
| `answer` | "K-IFRS 1115에 따르면..." (최대 2000자) | AI 답변 텍스트 |
| `matched_topics` | `["반품권이 있는 판매"]` | 매칭된 토픽 키 |
| `search_keywords` | `["반품권", "수익 인식", "환불부채"]` | analyze가 추출한 키워드 |
| `cited_paragraphs` | `["문단 56", "문단 B21", "문단 B23"]` | AI가 인용한 기준서 문단 |
| `is_situation` | `true` | 거래상황 vs 개념질문 |
| `needs_calculation` | `false` | 계산 경로 사용 여부 |
| `is_conclusion` | `false` | 체크리스트 결론 도달 여부 |
| `selected_branches` | `["[분기 1] 반품 예상 가능"]` | 결론 가이드 분기 |
| `response_time_ms` | `13449` | 응답 시간 (밀리초) |
| `auto_scores` | `{metrics: {...}, total: 0.98}` | **규칙 기반 자동 채점 결과** |
| `timestamp` | `2026-03-16T09:30:00Z` | UTC 타임스탬프 |

### 사용자 피드백 (버튼 클릭 시)

AI 답변 아래 👍/👎 버튼이 표시된다.
👎 클릭 시 "어떤 점이 부족했나요?" 텍스트 입력 후 전송하거나 건너뛸 수 있다.

| 필드 | 예시 | 설명 |
|------|------|------|
| `feedback` | `"up"` / `"down"` | 사용자 평가 |
| `feedback_reason` | `"관련 없는 문단을 인용함"` | 👎 사유 (최대 500자, 선택) |
| `feedback_at` | `2026-03-16T09:31:00Z` | 피드백 시각 |

---

## 3. 전체 데이터 흐름

```
[Streamlit UI]
    │
    ├─ 사용자 질문 입력
    │       ↓
    ├─ POST /chat (FastAPI)
    │       ↓
    ├─ pipeline 실행: analyze → retrieve → rerank → generate
    │       ↓
    ├─ done 이벤트 생성 (pipeline.py)
    │       ↓
    ├─ usage_logger.log_chat_response()
    │   ├─ MongoDB에 로그 저장
    │   └─ 규칙 기반 4개 메트릭 자동 채점 (~1ms, auto_scores 필드)
    │       ↓
    ├─ log_id를 SSE done 이벤트에 포함하여 클라이언트로 전송
    │       ↓
    ├─ AI 답변 표시 + 👍/👎 버튼 렌더링
    │       ↓
    └─ (선택) 👎 클릭 → 사유 입력 → POST /feedback → feedback + feedback_reason 저장
```

핵심: 로깅/채점이 실패해도 답변 흐름에는 영향이 없다 (예외를 삼킴).

---

## 4. 수집된 데이터 확인 방법

### 방법 1: 분석 스크립트 (가장 간편)

```bash
PYTHONPATH=. uv run --env-file .env python usage-data-collecting/analyze_usage.py
```

출력 예시:
```
=== 실사용 데이터 분석 (50건) ===
  채점 완료: 50건 | 미채점: 0건

[피드백]  좋아요: 12  |  개선필요: 3  |  미응답: 35
  만족률: 80%

[토픽 분포 Top 10]
  변동대가: 8건
  본인 vs 대리인: 6건

[응답 시간]  평균: 18.5s  |  최대: 42.3s

[개선 필요 피드백 최근 5건]
  Q: ESS 계약에서 설치와 유지보수를 어떻게 분리하나요?
    토픽: 수행의무 식별  |  응답: 28000ms
    사유: 결론이 너무 성급함
```

### 방법 2: MongoDB Atlas 웹 콘솔

[MongoDB Atlas](https://cloud.mongodb.com) → `kifrs_db` → `usage_logs`

유용한 필터:
```json
{ "feedback": "down" }                          // 👎 케이스
{ "auto_scores.total": { "$lt": 0.6 } }        // 자동 채점 낮은 건
{ "response_time_ms": { "$gt": 30000 } }        // 30초 초과
{ "feedback_reason": { "$exists": true } }       // 사유 있는 👎
```

### 방법 3: 채점 리포트

```bash
PYTHONPATH=. uv run --env-file .env python usage-data-collecting/score_usage_logs.py
```

DB에 저장된 자동 채점 결과로 `score_report.md` 생성 (API 호출 없음).

---

## 5. 품질 채점 — 7개 메트릭

매 응답마다 **규칙 기반 4개**가 자동 채점되고, 필요 시 **LLM 3개**를 추가할 수 있다.

### 규칙 기반 4개 (매 응답 자동, ~1ms)

`usage_logger.py`가 로그 저장과 동시에 채점. 별도 실행 불필요.

| 메트릭 | 가중치 | 평가 내용 | 산출 방식 |
|--------|--------|-----------|-----------|
| 응답 속도 | 20% | 응답이 빨랐는가 | 15초↓=1.0, 25초↓=0.7, 40초↓=0.4 |
| 인용 커버리지 | 35% | 근거 문단을 충분히 가져왔는가 | 인용 수(4↑=1.0, 2↑=0.7) + "문단" 언급 보너스 |
| 토픽 매칭 | 20% | 올바른 토픽을 식별했는가 | 거래상황이면 `matched_topics` 필수 |
| 결론 신중성 | 25% | 성급하게 결론 내리지 않았는가 | 분기 선택 존재 + 유보 표현 확인 |

### LLM 기반 3개 (수동 실행, gpt-4.1-mini)

```bash
PYTHONPATH=. uv run --env-file .env python usage-data-collecting/score_usage_logs.py --with-llm
```

| 메트릭 | 가중치 | 평가 내용 |
|--------|--------|-----------|
| 근거 충실도 | 20% | 답변이 인용 문단에 기반하는가 (환각 여부) |
| 답변 적절성 | 20% | 질문의 핵심에 답했는가 |
| 답변 완전성 | 15% | 고려할 사항을 빠뜨리지 않았는가 |

### 자동 채점과 사용자 피드백의 교차 분석

- 자동 점수 높은데 👎 → 사용자 기대와 시스템 기준의 괴리 (프롬프트/UX 문제)
- 자동 점수 낮은데 👍 → 채점 기준이 과도하게 엄격 (임계값 조정)
- 자동 점수 낮고 👎 → 실제 품질 문제 (골든셋 추가 후보)

---

## 6. 관련 소스코드

| 파일 | 역할 |
|------|------|
| `app/services/usage_logger.py` | 로그 저장 + 규칙 기반 자동 채점 + 피드백 업데이트 |
| `app/services/chat_service.py` | done 이벤트 직전에 `log_chat_response()` 호출 |
| `app/api/routes.py` | `POST /feedback` 엔드포인트 (사유 포함) |
| `app/api/schemas.py` | `SSEEvent.log_id` 필드 |
| `app/ui/pages.py` | 👍/👎 버튼 + 👎 사유 입력 UI |
| `app/ui/client.py` | done 이벤트에서 `log_id`를 `session_state`에 저장 |
| `usage-data-collecting/analyze_usage.py` | 피드백/토픽/응답시간/일별 사용량 분석 |
| `usage-data-collecting/score_usage_logs.py` | 리포트 생성 + LLM 심화 채점 |
| `usage-data-collecting/export_for_ragas.py` | RAGAS 평가 입력 포맷 추출 |

---

## 7. 골든 테스트와의 관계

```
골든 테스트 53건 (규칙 기반, 개발자 설계)
    ↕ 상호 보완
실사용 로그 (데이터 기반, 사용자 행동)
    ↓
👎 케이스 + 자동 채점 낮은 건 → 골든셋에 추가 → 회귀 방지 강화
```

골든 테스트는 **출발점** (개발 중 품질 보장), 실사용 데이터는 **지속적 품질 개선 엔진** (운영 중 피드백 루프).

---

## 8. 향후 확장

| 현재 한계 | 확장 방향 |
|-----------|-----------|
| answer 2000자 제한 | 필요 시 GridFS 또는 별도 컬렉션 |
| 분석이 CLI 스크립트 기반 | Streamlit 관리자 대시보드 |
| LLM 채점은 수동 실행 | 데이터 100건+ 시 스케줄러(cron)로 자동화 |

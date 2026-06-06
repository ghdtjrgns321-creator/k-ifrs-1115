# K-IFRS 1115 회계감사 AI 어시스턴트

> 검증된 기준서 원문만을 근거로, 도메인 지식으로 구축한 Decision Tree 안에서만 결론을 내리는 **도메인 특화 RAG 시스템**. 일반 AI 챗봇과 달리 자유 추론을 허용하지 않아 환각이 구조적으로 차단된다.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?logo=streamlit&logoColor=white)
![PydanticAI](https://img.shields.io/badge/PydanticAI-E92063?logo=pydantic&logoColor=white)
![MongoDB Atlas](https://img.shields.io/badge/MongoDB%20Atlas-47A248?logo=mongodb&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)

**[🔗 라이브 데모](http://134.185.104.224:8501)**

![Split View — 좌측 근거 문서 + 우측 AI 답변](images/split_view.png)

---

## 핵심 특징

- **Decision Tree 강제** — 토픽별 의사결정 트리로 정해진 Case 분기 내에서만 결론 도출, AI 자의적 추론 차단
- **PydanticAI 구조화 출력** — '근거'와 '결론' 분리를 코드 수준에서 강제, AI 답변의 변동성 억제
- **핀포인트 + Reranker 검색** — 사전 배정 문서 직접 조회 + 실무 약칭 자동 확장(예: "묶음 판매" → 복수의 수행의무·거래가격 배분) 하이브리드 보충
- **근거 선행, AI 후행** — DB에 적재한 1,575건(본문·적용사례·질의회신·감리사례)을 AI 호출 **전에** SUMMARY와 함께 열람 가능
- **Split View 근거 추적** — AI 답변과 인용 근거를 한 화면에서 동시 확인, AI가 참조한 문단은 볼드 처리

---

## 왜 다른가 <sub>[상세: PROJECT-OVERVIEW](FINAL-REPORT/1_PROJECT-OVERVIEW.md)</sub>

범용 LLM을 회계 기준서 해석에 그대로 쓰면 근거 없는 답변을 생성하는 **환각**에 노출되고, 이는 감사 실무에서 AI를 과대신뢰하는 2종 오류로 이어진다. 이 시스템은 유연성을 포기하고 **무결성**에 집중한다.

| 항목         | 일반 ChatGPT              | 이 시스템                                  |
|--------------|---------------------------|--------------------------------------------|
| 답변 근거    | 학습 데이터에서 자유 추론   | DB에 저장된 기준서 원문만 사용               |
| 근거 추적    | 어려움 (출처 불명)         | 문단 번호 단위로 추적 가능                   |
| 환각 방지    | 없음                      | 5-Layer 파이프라인                           |
| 결론 구조    | 자유형 텍스트              | Decision Tree 체크리스트 + Case 분기         |
| 정보 부족 시 | 근거 없이 단정 위험        | 조건부 결론(Case 1/2)으로 분기 제시          |
| 모델         | 단일 모델                 | 듀얼 LLM 라우팅 — 질문 유형별 최적 모델 자동 선택 |

---

## 환각 방지 5-Layer Pipeline <sub>[상세: SEARCH-AND-AI](FINAL-REPORT/4_SEARCH-AND-AI.md)</sub>

데이터 적재부터 최종 답변까지 전 과정을 통제하는 **확정적(Deterministic) 아키텍처**:

1. **도메인 데이터 적재** — 1115호 본문·관련 사례·지적사례 1,575건을 DB에 저장
2. **핀포인트 + Reranker 검색**
   - Tier 1 핀포인트: Decision Tree 사전 배정 문서 ID로 DB 직접 조회 → 핵심 근거 누락 0%
   - Tier 2 하이브리드 보충: 벡터 + BM25 + RRF 융합, 실무 약칭 자동 인식(15개 매핑) + 카테고리 가중치(본문·적용지침 1.3 / 감리 1.2 / BC 0.8)
   - Cohere Cross-encoder 재평가: 1차 결과 30건 재평가, 핀포인트 문서는 보호
3. **듀얼 LLM 라우팅** — Gemini Flash(회계추론 1위) + gpt-4.1-mini(산술 100%) 질문 유형별 자동 선택
4. **Decision Tree 강제** — 정보 부족 시 임의 판단 대신 조건부 결론(Case 분기) 도출
5. **PydanticAI 구조화 출력** — '근거'와 '결론' 분리 강제, result_validator + 자동 재시도

---

## 아키텍처

```
사용자 질문
  │
  ▼
[Analyze]  gpt-4.1-mini — 질문 분석·라우팅 (10개 판단 항목)
  │
  ▼
[Retrieve] 2계층 검색 — 핀포인트 + 하이브리드 (병렬)
  │
  ▼
[Rerank]   Cohere Cross-encoder — 도메인 가중치 + 핀포인트 보호
  │
  ▼
[Generate] 듀얼 LLM 라우팅 — Gemini(판단) / gpt-4.1-mini(계산)
  │
  ▼
[Format]   감리사례 경고 + 꼬리질문 + 인용 정리
```

| 레이어       | 기술                                                                              |
|-------------|-----------------------------------------------------------------------------------|
| **Backend**  | FastAPI · uvicorn · PydanticAI (structured output + 자동 재시도)                   |
| **Frontend** | Streamlit (4단계 State Machine UI)                                                 |
| **AI/ML**    | Gemini Flash (thinking) · gpt-4.1-mini · Cohere Reranker · Upstage Solar Embedding |
| **Database** | MongoDB Atlas Vector Search (벡터 + 메타데이터 필터 + PDR)                          |
| **Infra**    | Docker · docker-compose · uv (Python 3.11)                                         |

---

## 품질 검증 <sub>[상세: TEST-AND-DECISIONS](FINAL-REPORT/5_TEST-AND-DECISIONS.md)</sub>

모델 선정(218회) → 검색 테스트(101회) → 품질 테스트(301회), 3단계 총 **620회 호출**로 검증했다.

| 지표                   | 값                | 의미                                  |
|------------------------|-------------------|---------------------------------------|
| 총 검증 호출 수         | **620회**         | 모델 218 + 검색 101 + 품질 301        |
| 최종 골든 테스트 통과율  | **88.7%** (47/53) | 7개 유형 53건 전수 검증                |
| 환각 발생률            | **0%**            | 전체 테스트에서 근거 없는 답변 0건      |
| 라우팅 정확도          | **100%**          | AI 판단 전환 후 42/42                  |
| 계산 정답률            | **100%**          | 듀얼 LLM 라우팅 확정 후                |
| 응답시간 중위값         | **25.3초**        | Gemini thinking=medium 기준           |

> 통과율 88.7%의 Issue 6건은 "토픽 매칭이 기대와 다름(답변은 정확)", "응답 시간이 긴 편" 수준의 **메타데이터·완성도 이슈**이며, 잘못된 정보 생성이나 근거 없는 단정은 **0건**이다.

---

## 트러블슈팅 — 전략적 문제 해결 <sub>[상세: TROUBLESHOOT](FINAL-REPORT/TROUBLESHOOT.md)</sub>

| 카테고리           | 트러블슈팅            | 핵심 전환                                       |
|--------------------|-----------------------|-------------------------------------------------|
| A. 제품 전략        | 범용 AI와의 차별화     | 챗봇 → UX 2단계(토픽 브라우즈 + AI)              |
| B. 데이터           | PDF 파싱 한계         | case by case 패치 → kifrs.com REST API 크롤링    |
| C. AI 파이프라인    | LLM 답변 분산         | 프롬프트 강화(역효과) → PydanticAI 구조화 출력    |
| C. AI 파이프라인    | 답변 내용 비결정성     | PydanticAI만으로 부족 → Decision Tree 알고리즘 강제 |
| D. 개발 프로세스    | Git 작업 소실         | 사고 발생 → 규칙 체계 수립                        |
| D. 개발 프로세스    | 문서 부재 반복 디버깅  | 기록 없음 → docs 체계 수립                        |

---

## Quickstart

### 환경 변수

```bash
cp .env.example .env
# .env 파일에 API 키 입력 (OPENAI / UPSTAGE / COHERE / GOOGLE / MONGO_URI)
```

### Docker 배포

```bash
docker compose up -d --build
```

- Streamlit UI: http://localhost:8501
- FastAPI Swagger: http://localhost:8002/docs

### 로컬 개발

```bash
uv sync
uv run uvicorn app.main:app --port 8002       # 백엔드
uv run streamlit run app/streamlit_app.py      # 프론트엔드 (별도 터미널)
```

---

## 📚 상세 문서

| 문서                                                        | 내용                      |
|-------------------------------------------------------------|---------------------------|
| [PROJECT-OVERVIEW](FINAL-REPORT/1_PROJECT-OVERVIEW.md)      | 프로젝트 배경과 UX 설계    |
| [DATA-PIPELINE](FINAL-REPORT/2_DATA-PIPELINE.md)            | 6종 데이터 수집·가공 14단계 |
| [DOMAIN-CURATION](FINAL-REPORT/3_DOMAIN-CURATION.md)        | 30개 토픽 큐레이션 과정    |
| [SEARCH-AND-AI](FINAL-REPORT/4_SEARCH-AND-AI.md)            | 검색·AI 파이프라인 상세    |
| [TEST-AND-DECISIONS](FINAL-REPORT/5_TEST-AND-DECISIONS.md)  | 620회 테스트 전체 결과     |
| [LESSONS-LEARNED](FINAL-REPORT/6_LESSONS-LEARNED.md)        | 회고와 배운 점            |
| [TROUBLESHOOT](FINAL-REPORT/TROUBLESHOOT.md)                | 6건 전략적 문제 해결       |

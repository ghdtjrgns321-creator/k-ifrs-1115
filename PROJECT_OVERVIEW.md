# K-IFRS 1115 Chatbot — 프로젝트 개요

> **이 문서는 LLM에게 프로젝트 컨텍스트를 전달하기 위해 작성되었습니다.**
> 새로운 대화를 시작할 때 이 문서를 먼저 읽혀주세요.
>
> **최종 업데이트**: 2026-03-10 (토픽 브라우즈 하단 "직접 질문하기" 추가, LLM 모델 통일 gpt-5-mini + o4-mini, 노드 목록 보완)

---

## 1. 프로젝트 목적

회계법인 입사를 위한 **포트폴리오 프로젝트 #1**.

**K-IFRS 제1115호(고객과의 계약에서 생기는 수익)** 에 관하여, **회계감사인(감사인)**들이 객관적인 팩트를 손쉽게 찾고, AI의 추론을 통해 인사이트를 얻을 수 있도록 하는 **전문 도구**입니다.

### 핵심 가치

- **환각(Hallucination) 방지가 최우선** — 회계감사에서 환각은 치명적입니다.
- AI가 먼저 답하는 것이 아니라, **사용자가 먼저 팩트(근거 문서)를 확인**한 뒤 AI에게 질문하는 **"근거 선행, AI 후행"** 구조입니다.
- AI는 단순 답변에 그치지 않고, 회계처리의 해석 여지가 있는 부분을 포착하여 **꼬리질문**을 던져 사용자의 질문을 고도화합니다.

---

## 2. 핵심 UX 흐름 (4단계 State Machine)

```
[홈 (home)]
  좌우 2단 레이아웃: 왼쪽(5단계 수익인식 모형) / 오른쪽(후속 처리·특수 거래)
    ├─ 토픽 클릭 → [토픽 브라우즈 (topic_browse)]
    └─ 자유 검색 입력 → [근거 열람 (evidence)]

[토픽 브라우즈 (topic_browse)]
  큐레이션된 4개 탭: 본문·BC | 적용사례 | 질의회신 | 감리지적사례
  관련 토픽 칩(pills)으로 토픽 간 이동
  하단 "직접 질문하기" — 토픽 맥락의 자유 질문 입력
    ├─ 자유 검색 입력 → [근거 열람 (evidence)]
    └─ (evidence에서) AI 질문 → [AI 답변 (ai_answer)]

[근거 열람 (evidence)]
  RAG 검색 결과를 카테고리별 아코디언으로 제시
  → 하단 AI 질문 입력
    └─ AI 질문 → [AI 답변 (ai_answer)]

[AI 답변 (ai_answer)]
  Split View: 좌(근거 문서) + 우(AI 답변 + 꼬리질문)
  → 꼬리질문 버튼 클릭 또는 추가 질문 입력 → [AI 답변] 반복
```

### 홈화면 8섹션 매트릭스

```
┌──────────────────────────────┬──────────────────────────────┐
│ 5단계 수익인식 모형          │ 후속 처리 · 특수 거래        │
├──────────────────────────────┼──────────────────────────────┤
│ Step 1. 계약의 식별          │ Step 6. 거래가격의 변동      │
│ Step 2. 수행의무의 식별      │ Step 7. 계약원가             │
│ Step 3. 거래가격의 산정      │ Step 8. 특수한 형태의 거래   │
│ Step 4. 거래가격의 배분      │   ├ 보증                     │
│ Step 5. 수익의 인식          │   ├ 본인과 대리인            │
│                              │   ├ 통제 이전의 특수 형태    │
│                              │   └ 고객의 권리 관련         │
└──────────────────────────────┴──────────────────────────────┘
```

---

## 3. 기술 스택

| 레이어 | 기술 | 비고 |
|--------|------|------|
| **패키지 관리** | uv | Python ≥ 3.11 |
| **백엔드** | FastAPI + uvicorn | REST API (`/search`, `/chat`, `/health`) |
| **프론트엔드** | Streamlit | 4단계 State Machine UI |
| **AI 프레임워크** | PydanticAI | 네이티브 structured output + 자동 재시도 |
| **벡터 DB** | MongoDB Atlas Vector Search | 임베딩 + 메타데이터 통합 저장 |
| **임베딩** | Upstage `solar-embedding-1-large` | passage(저장) / query(검색) 구분 **필수** |
| **LLM (경량/추론)** | OpenAI `gpt-5-mini` | analyze, rewrite, grade, hyde + simple generate (reasoning_effort=low) |
| **LLM (추론·고급)** | OpenAI `o4-mini` | complex generate, clarify 첫 턴 (reasoning_effort=medium) |
| **Reranker** | Cohere `rerank-multilingual-v3.0` | 한국어 최적화 Cross-encoder |
| **설정 관리** | pydantic-settings | `.env` 타입 안전 관리 |
| **컨테이너** | Docker + docker-compose | 멀티스테이지 빌드 |
| **배포** | Oracle Cloud | Docker로 배포 예정 |

---

## 4. 디렉토리 구조

```
k-ifrs-1115-chatbot/
├── app/
│   ├── api/
│   │   ├── routes.py              # FastAPI 라우터 (/chat, /search, /health)
│   │   └── schemas.py             # Pydantic 요청/응답 스키마
│   ├── domain/                    # 도메인 데이터 + 큐레이션 + Decision Tree
│   │   ├── decision_trees.py      # 본문 기반 판단 트리 (22토픽)
│   │   ├── qna_match_trees.py     # QNA 전제조건 매칭 트리 (23항목)
│   │   ├── red_flags.py           # 감리사례 위험신호 패턴 (12패턴)
│   │   ├── summary_matcher.py     # QNA/감리사례/IE 서머리 임베딩 기반 매칭
│   │   ├── topic_content_map.py   # 토픽 큐레이션 데이터 (topics.json 로드)
│   │   ├── tree_matcher.py        # 통합 체크리스트 매칭 로직 (키워드→점수→상위 2개)
│   │   ├── context_main_text.md   # decision_trees.py 생성 컨텍스트
│   │   ├── context_qna.md         # qna_match_trees.py 생성 컨텍스트
│   │   └── context_findings.md    # red_flags.py 생성 컨텍스트
│   ├── nodes/                     # 파이프라인 노드 (async 함수, 1파일 1노드)
│   │   ├── analyze.py             # 질문 분석 + 라우팅 + complexity 판단
│   │   ├── retrieve.py            # Vector + BM25 + RRF 하이브리드 검색
│   │   ├── rerank.py              # Cohere Reranker 재랭킹
│   │   ├── grade.py               # 문서 품질 평가 (CRAG)
│   │   ├── generate.py            # complexity 기반 모델 스위칭 + 답변 생성
│   │   ├── hyde_retrieve.py       # HyDE 가상 문서 생성 → 재검색 폴백
│   │   ├── rewrite.py             # 질문 재작성 폴백
│   │   └── format.py              # 응답 포맷팅 + 감리사례 섀도우 매칭
│   ├── services/                  # 비즈니스 로직 서비스
│   │   ├── chat_service.py        # 파이프라인 실행 + SSE + 체크리스트 Q&A 쌍 관리
│   │   ├── search_service.py      # 열람용 검색 (결정론적, LLM 최소화)
│   │   └── session_store.py       # 세션 + 체크리스트 + cached_docs 관리
│   ├── preprocessing/             # 데이터 전처리 파이프라인 (순서대로 실행, 99-verify-chunks.py로 검증)
│   ├── test/                      # 연결·검색 테스트
│   ├── ui/                        # Streamlit UI 컴포넌트 (18파일)
│   │   ├── layout.py              # CSS 주입 + 헤더 + 사이드바 (shadcn/ui 스타일)
│   │   ├── pages.py               # 홈/근거열람/AI답변 페이지 렌더러
│   │   ├── topic_browse.py        # 토픽 브라우즈 — 토픽 해석 + 4탭 오케스트레이터 + 하단 직접 질문
│   │   ├── topic_tabs.py          # 4탭 실제 렌더링 (본문·BC, 적용사례, 질의회신, 감리)
│   │   ├── evidence.py            # 근거 열람 — 검색 결과 카테고리별 아코디언
│   │   ├── pinpoint_panel.py      # AI 답변 좌측 근거 패널
│   │   ├── grouping.py            # 검색 결과 소제목별 2단계 그룹화
│   │   ├── components.py          # 아코디언/expander 공통 컴포넌트
│   │   ├── constants.py           # 8섹션 키워드 + 토픽 매핑 + 부제
│   │   ├── cross_links.py         # 관련 조항 칩 렌더링
│   │   ├── db.py                  # MongoDB 조회 (PDR 컬렉션 라우팅 + 알파벳 접미사 범위 + @st.cache_resource)
│   │   ├── doc_helpers.py         # 문서 메타 추출 헬퍼 (paraNum, self_ids 등)
│   │   ├── doc_renderers.py       # 문단 칩 + expander 렌더링
│   │   ├── client.py              # FastAPI 호출 래퍼
│   │   ├── session.py             # 세션 초기화 + _go_home
│   │   ├── modal.py               # 문단 원문 모달
│   │   └── text.py                # 텍스트 정규화 + HTML 변환 + 참조 추출
│   ├── main.py                    # FastAPI 진입점 (lifespan + CORS + BM25 인덱스 빌드)
│   ├── streamlit_app.py           # Streamlit UI 진입점
│   ├── config.py                  # pydantic-settings 중앙 설정
│   ├── agents.py                  # PydanticAI Agent 정의 (7개 LLM 호출 포인트)
│   ├── pipeline.py                # 순수 Python async generator 오케스트레이션
│   ├── embeddings.py              # Upstage REST API 직접 호출 (async + sync)
│   ├── retriever.py               # 검색 엔진 (Vector + BM25 + RRF 융합)
│   ├── reranker.py                # Cohere Reranker 래퍼
│   ├── prompts.py                 # 프롬프트 (reasoning/non-reasoning 모델별 최적화)
│   ├── state.py                   # RAGState TypedDict
│   ├── graph.py                   # (레거시) LangGraph StateGraph — pipeline.py로 대체
│   └── llm.py                     # (레거시) langchain_openai 팩토리 — agents.py로 대체
├── data/
│   ├── raw/                       # 크롤링 원본 (gitignore)
│   ├── web/                       # 처리된 청크 JSON + query-mapping-generated.json
│   ├── findings/                  # 감리사례 데이터
│   └── topic-curation/            # 큐레이션 데이터
│       ├── topics.json            # 25개 토픽 구조화 JSON (10-parse-curation.py 출력)
│       ├── topic-curation.txt     # 원본 큐레이션 텍스트
│       └── 분류체계.txt            # 분류 체계 설명
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml                 # uv 의존성
├── .env / .env.example
├── CLAUDE.md                      # 프로젝트 지침 (Claude Code 자동 로드)
├── debugging.md                   # Streamlit 디버깅 교훈
└── PROJECT_OVERVIEW.md            # ← 이 파일
```

---

## 5. RAG 파이프라인 (순수 Python 오케스트레이션)

```
pipeline.py — async generator로 SSE 이벤트를 yield

  [fast-path] clarify 후속 턴 → generate만 실행 (analyze/retrieve/rerank 스킵)

  [일반 흐름]
  analyze → retrieve → rerank → generate → format
                                    ↓
                              is_situation?
                              ├─ True  → clarify_agent (체크리스트 동적 주입 + 꼬리질문)
                              └─ False → generate_agent (complexity 기반 모델 스위칭)
                                          ├─ simple → gpt-5-mini (reasoning_effort=low, ~15-20초)
                                          └─ complex → o4-mini (reasoning_effort=medium, ~40-60초)
```

| 노드 | 역할 | Agent / LLM |
|------|------|-------------|
| analyze | 질문 분석/라우팅/complexity 판단 | `analyze_agent` (gpt-5-mini) |
| retrieve | Vector + BM25 하이브리드 검색 | — |
| rerank | Cohere Reranker + 비즈니스 룰 | — |
| grade | 문서 품질 평가 (CRAG) | `grade_agent` (gpt-5-mini) |
| generate | 개념 답변 생성 | `generate_agent` (simple→gpt-5-mini / complex→o4-mini) |
| clarify | 거래 상황 꼬리질문 (멀티턴 체크리스트) | `clarify_agent` (첫 턴: o4-mini, 후속: gpt-5-mini) |
| hyde_retrieve | HyDE 가상 문서 → 재검색 (폴백) | `hyde_agent` (gpt-5-mini) |
| rewrite | 질문 재작성 (폴백) | `rewrite_agent` (gpt-5-mini) |
| format | 감리사례 넛지 추가 | — |

### 핵심 메커니즘

- **Hybrid Search**: MongoDB Vector Search + BM25(한국어 2-gram) → RRF(Reciprocal Rank Fusion) + 인접 문단 클러스터 부스팅
- **Cross-encoder Reranking**: Cohere `rerank-multilingual-v3.0` — rerank_threshold 0.05 미만 제거
- **PDR (Parent Document Retrieval)**: QNA/감리사례 Child 청크 검색 → parent_id로 부모 원문 전체 조회
- **Complexity 기반 모델 스위칭**: analyze가 simple/complex 판단 → simple은 gpt-5-mini(reasoning_effort=low)로 빠르게, complex는 o4-mini(reasoning_effort=medium)로 정확하게
- **Reasoning 모델 프롬프트 최적화**: o4-mini/gpt-5-mini에 CoT 지시 제거, 목표만 명시 (OpenAI 공식 권장)
- **멀티턴 체크리스트**: clarify 노드가 거래 유형별 Dynamic 체크리스트를 system prompt에 주입, Q&A 쌍으로 진행 추적
- **감리사례 섀도우 매칭**: format 노드에서 질문과 유사한 감리 지적사례를 자동 매칭

### PydanticAI Agent 구성 (`agents.py`)

| Agent | 모델 | 용도 | 출력 |
|-------|------|------|------|
| `analyze_agent` | gpt-5-mini | 질문 분석/라우팅/complexity | `AnalyzeResult` |
| `grade_agent` | gpt-5-mini | 문서 품질 평가 (CRAG) | `GradeResult` |
| `generate_agent` | o4-mini (기본) | 최종 답변 생성 | `GenerateOutput` |
| `clarify_agent` | gpt-5-mini (기본), 첫 턴 o4-mini 오버라이드 | 꼬리질문 생성 | `GenerateOutput` |
| `rewrite_agent` | gpt-5-mini | 질문 재작성 폴백 | `str` |
| `hyde_agent` | gpt-5-mini | HyDE 가상 문서 생성 | `str` |
| `text_agent` | gpt-5-mini | 범용 텍스트 호출 | `str` |

### 프롬프트 설계 원칙 (`prompts.py`)

| 대상 모델 | 전략 | 근거 |
|-----------|------|------|
| gpt-5-mini / o4-mini (reasoning) | CoT 제거, 목표만 명시, 프롬프트 축소 | reasoning 모델에 step-by-step 지시는 역효과 (OpenAI 공식 권장) |

---

## 6. 도메인 체크리스트 시스템 (`app/domain/`)

### 개요

`analyze` 노드가 추출한 `search_keywords`와 `standalone_query`를 3개 dict의 `trigger_keywords`와 매칭하여, `is_situation=True`일 때 `clarify_agent`의 system prompt에 체크리스트를 동적 주입합니다.

### 데이터 소스

| 파일 | 항목 수 | 역할 |
|------|---------|------|
| `decision_trees.py` | 22 토픽 | 본문 기반 판단 체크리스트 (Yes/No 질문) |
| `qna_match_trees.py` | 23 항목 | QNA 전제조건 매칭 (condition/question/yes_path/no_path) |
| `red_flags.py` | 12 패턴 | 감리사례 위험신호 경고 (question/risk_if_yes) |

### 매칭 로직 (`tree_matcher.py`)

1. 3개 dict에서 `trigger_keywords`와 양방향 부분 문자열 매칭 (1자 스킵, 완전 일치 보너스)
2. 타입별 최고 score 1개씩 선발
3. 전체를 score 내림차순 → **상위 2개** 반환
4. `checklist` 필드를 함께 전달하여 `agents.py`에서 진행 상황 추적

---

## 7. 토픽 큐레이션 시스템

### 개요

**25개 토픽**에 대해 **사전 큐레이션된 문서 매핑**을 제공합니다. RAG 검색 없이 `topics.json`의 정적 데이터로 관련 문단을 즉시 조회합니다.

### 토픽별 데이터 구조

```python
TopicData = {
    "display_name": str,              # 표시명 (예: "계약의 식별")
    "cross_links": list[str],         # 관련 토픽 추천 (JSON 키와 정확히 일치해야 함)
    "main_and_bc": {                  # 본문 + 결론도출근거(BC)
        "summary": str,
        "sections": [
            {"title": str, "desc": str,
             "paras": ["9", "10"],     # 본문 문단
             "bc_paras": ["BC34"]}     # BC 문단
        ]
    },
    "ie": {                           # 적용사례
        "summary": str,
        "cases": [
            {"title": str, "desc": str,
             "para_range": "IE19~IE24",
             "case_group_title": "수행의무 - 일회성 용역"}
        ]
    },
    "qna": {                          # 질의회신
        "summary": str,
        "qna_ids": ["QNA-SSI-38612"]
    },
    "findings": {                     # 감리지적사례
        "summary": str,
        "finding_ids": ["FSS-xxx"]
    }
}
```

### 토픽 브라우즈 4탭 뷰

| 탭 | 데이터 소스 | 조회 방식 |
|----|------------|----------|
| 본문·BC | `main_and_bc.sections` | `fetch_docs_by_para_ids()` — 문단 ID 배치 조회 |
| 적용사례 | `ie.cases` | `_expand_para_range()` → `_batch_fetch_paras()` — 문단 범위 확장 후 배치 조회 |
| 질의회신 | `qna.qna_ids` | `fetch_parent_doc()` — ID 접두사로 별도 컬렉션 라우팅 (`k-ifrs-1115-qna-parents`) |
| 감리사례 | `findings.finding_ids` | `fetch_parent_doc()` — ID 접두사로 별도 컬렉션 라우팅 (`k-ifrs-1115-findings-parents`) |

#### QNA/감리사례 제목 빌드 (`_build_pdr_label`)

parent 문서의 title 상태에 따라 3가지 케이스 처리:
- **A)** title에 `[ID]` 포함 → "레퍼런스" 접두어 제거 후 그대로
- **B)** title이 설명만 (ID 미포함) → `[doc_id]` 접두어 추가
- **C)** title이 빈값/ID와 동일 → content 첫 줄에서 설명 추출

---

## 8. 데이터 소스 및 스키마

### 데이터 소스

| 소스 | 설명 | 상태 |
|------|------|------|
| K-IFRS 1115호 본문 | 기준서 본문 + 적용지침 + 결론도출근거 + 용어정의 + 적용사례(IE) | ✅ 완료 |
| 질의회신 (QNA) | kifrs.com 질의회신 101건 | ✅ 완료 |
| 감리사례 (Findings) | 금감원 감리 지적사례 18건 | ✅ 완료 |
| 토픽 큐레이션 | 25개 토픽별 문단·사례·QNA·감리사례 매핑 | ✅ 완료 |
| BIG4 가이드 | 딜로이트·삼일·EY한영·KPMG 실무 가이드 | 미완료 |

**총 청크**: 약 1,298개

### 청크 스키마 (MongoDB)

```python
{
    "chunk_id": str,          # 고유 식별자
    "content": str,           # 청크 본문
    "source": str,            # "본문", "QNA", "감리사례" 등
    "category": str,          # "본문", "적용지침B", "결론도출근거" 등
    "weight_score": float,    # 카테고리별 검색 가중치
    "hierarchy": str,         # Breadcrumb 경로 (문맥 보강)
    "embedding": list[float], # Upstage solar-embedding 벡터 (passage 모드)
}
```

---

## 9. 환경 변수

```bash
# MongoDB
MONGO_URI=mongodb+srv://...
MONGO_DB_NAME=kifrs_db
MONGO_COLLECTION_NAME=k-ifrs-1115-chatbot

# API Keys (필수)
UPSTAGE_API_KEY=up_xxx      # 임베딩 전용
OPENAI_API_KEY=sk-xxx       # LLM 전용 (gpt-5-mini, o4-mini)
COHERE_API_KEY=xxx          # Reranker 전용

# LLM 설정 (선택, 기본값 있음)
LLM_FRONT_MODEL=gpt-5-mini
LLM_GENERATE_MODEL=o4-mini
LLM_TEMPERATURE=0.0
LLM_TIMEOUT=90
```

---

## 10. 실행 방법

```bash
# ── 로컬 개발 ────────────────────────────────────────────────────
uv sync                                          # 의존성 설치
uv run uvicorn app.main:app --port 8002           # FastAPI 서버
uv run streamlit run app/streamlit_app.py         # Streamlit UI

# ── 전처리 파이프라인 (순서대로) ─────────────────────────────────
PYTHONPATH=. uv run --env-file .env app/preprocessing/04-embed.py
PYTHONPATH=. uv run --env-file .env app/preprocessing/06-qna-embed.py
PYTHONPATH=. uv run --env-file .env app/preprocessing/07-findings-embed.py
PYTHONPATH=. uv run --env-file .env app/preprocessing/10-parse-curation.py
PYTHONPATH=. uv run --env-file .env app/preprocessing/11-fix-external-tables.py
PYTHONPATH=. uv run --env-file .env app/preprocessing/12-summary-embed.py

# ── 청크 품질 검증 (재청킹 후 필수) ──────────────────────────
PYTHONPATH=. uv run python app/preprocessing/99-verify-chunks.py

# ── Docker 배포 ──────────────────────────────────────────────────
docker compose build && docker compose up -d
docker compose logs -f

# ── 코드 품질 ────────────────────────────────────────────────────
uv run ruff check .
uv run ruff format .
```

---

## 11. UI/UX 스타일링

### 디자인 시스템

- **shadcn/ui + Linear 스타일**: Tailwind Slate 색상 토큰 기반
- **CSS 주입**: `layout.py`의 `_inject_css()`에서 `st.markdown(unsafe_allow_html=True)`로 메인 DOM에 직접 주입
- **Streamlit 테마**: `.streamlit/config.toml`로 전역 색상/폰트 설정

### 특정 버튼 스타일링 패턴

```python
# key에 nav_ 접두사 부여 → Streamlit이 .st-key-nav_xxx 클래스 자동 생성
st.button("← 새 검색", key="nav_search_top")
```

```css
/* 접두사 매칭으로 네비게이션 버튼만 연한 회색 강조 */
div[class*="st-key-nav_"] button {
    background-color: #f1f5f9 !important;
}
```

> `.st-key-<key>` 셀렉터는 Streamlit 1.38+에서 지원. JS/iframe 접근은 불안정하므로 CSS-only 사용.

---

## 12. 코딩 컨벤션

- 파일 하나 **100줄 내외** 유지 (길어지면 즉시 분리)
- 경로·설정값은 파일 상단 상수 또는 `config.py`에 선언 (하드코딩 금지)
- 주석은 **Why** 중심 (What은 코드가 말함)
- 노드는 `app/nodes/` 하위에 1파일 1노드 원칙
- 임베딩 모델 **passage / query 혼용 금지** (검색 품질 급락)
- LLM 호출: `agents.py`의 PydanticAI Agent (structured output + 자동 재시도)
- reasoning 모델(gpt-5-mini, o4-mini): CoT 프롬프트 금지, temperature 미지원, reasoning_effort로 조절

---

## 13. 향후 개발 방향

### 최근 완료
- [x] 토픽 브라우즈 하단 "직접 질문하기" 추가 — 토픽 맥락 안내 문구 + 자유 질문 → `/search` → evidence 페이지 전환
- [x] 토픽 브라우즈 QNA/감리 탭 전면 수정 — PDR 컬렉션 라우팅, `_build_pdr_label` 제목 빌드, 알파벳 접미사 범위(`IE238A~IE238G`), 중복 para_chips 제거
- [x] LLM 모델 통일: gpt-4.1-mini → gpt-5-mini (front model 포함 전체 reasoning 모델로 전환)
- [x] 문단 참조 볼드 강조 에지 케이스 4건 수정 (`app/ui/text.py`)
- [x] 청킹 품질 고도화 + 청크 전수 검증 스크립트 (`99-verify-chunks.py`)

### 진행 중
- [ ] 답변 형식 재설계 — 조건부 결론 + Case 분기 + 확인 필요사항 섹션
- [ ] 통합 테스트 (서버 실행 + Streamlit 실제 질문)

### 후속 작업
- [ ] BIG4 가이드 크롤링 및 임베딩
- [ ] RAGAS 기반 RAG 품질 평가 자동화 (Faithfulness, Context Precision)
- [ ] 골든셋 구축 (100개 이상 K-IFRS 질문)
- [ ] Redis 시맨틱 캐시 (반복 질문 API 비용 절감)
- [ ] Oracle Cloud 배포
- [ ] 레거시 파일 정리 (`graph.py`, `llm.py` 제거)

---

## 14. 작업 요청 시 유의사항

1. **회계 도메인** — K-IFRS 1115호(수익 인식)가 핵심 도메인입니다. 회계 용어와 맥락을 존중해주세요.
2. **환각 방지 설계** — "AI가 먼저 답하고 근거는 나중에" 방식이 아닌, "근거 먼저, AI 나중에" 설계입니다.
3. **꼬리질문이 핵심** — AI의 답변보다 꼬리질문을 통한 질문 고도화가 이 챗봇의 차별화 포인트입니다.
4. **uv로 패키지 관리** — pip이 아닌 uv를 사용합니다 (`uv sync`, `uv run`, `uv add`).
5. **PydanticAI 기반** — `app/agents.py`(Agent 정의) + `app/pipeline.py`(오케스트레이션) + `app/state.py`(RAGState).
6. **포트폴리오 목적** — 회계법인 입사용 포트폴리오이므로, 코드 품질과 설계 의도의 명확성이 중요합니다.
7. **Streamlit CSS** — 특정 버튼 스타일링은 `key="nav_xxx"` + `div[class*="st-key-nav_"]` 패턴 사용. JS/iframe 접근 금지.
8. **reasoning 모델 프롬프트** — gpt-5-mini/o4-mini에 "단계별로 분석하세요" 등 CoT 지시 금지. 목표만 명시.

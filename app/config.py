from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 1. MongoDB 설정
    mongo_uri: str
    mongo_db_name: str = "kifrs_db"
    # 본문 + QNA Child + Findings Child가 모두 저장되는 공유 컬렉션
    mongo_collection_name: str = "k-ifrs-1115-chatbot"

    # 2. API 키 (필수)
    upstage_api_key: str  # 임베딩 전용
    openai_api_key: str  # LLM 전용
    cohere_api_key: str  # Reranker 전용 (rerank-multilingual-v3.0)
    google_api_key: str  # Gemini API

    # 3. LLM 모델 설정
    # Front Nodes (analyze, rewrite, grade): 빠른 분류·평가용 경량 모델
    llm_front_model: str = "gpt-4.1-mini"
    # Generate Node: 회계 추론 품질 1위 Gemini Flash (thinking=high)
    llm_generate_model: str = "gemini-3-flash-preview"
    # 계산 폴백: 산술 정확도 100% + 최저 비용
    llm_calc_model: str = "gpt-4.1-mini"
    llm_temperature: float = 0.0
    # API 응답 대기 최대 시간(초)
    llm_timeout: int = 90
    # HyDE 가상 문서 생성 전용 타임아웃 — 3-5문장만 생성하므로 15초로 충분
    # 초과 시 원본 쿼리로 즉시 폴백하여 전체 파이프라인 지연 방지
    llm_hyde_timeout: int = 15

    # 5. 임베딩 모델 (passage/query 혼용 시 검색 품질 급락 — 혼용 금지)
    # passage: 문서를 DB에 저장(적재)할 때 사용
    # query:   사용자 검색어를 임베딩할 때 사용
    embed_passage_model: str = "solar-embedding-1-large-passage"
    embed_query_model: str = "solar-embedding-1-large-query"
    embed_batch_size: int = 100  # API 과부하 방지용 배치 단위

    # 6. 외부 API 타임아웃
    # Why: Cohere Reranker가 간헐적으로 응답 지연 → 무한 대기 방지
    reranker_timeout: int = 30
    # Why: 전체 파이프라인 무한 대기 방지 (SECTION-4 미인도청구약정 46초+ 케이스)
    pipeline_timeout: int = 100

    # STEP 6 홀드아웃 검증용 — 켜면 retrieval에서 QNA(질의회신) 문서를 제외한다.
    # Why: 골든셋(qna_testset)이 QNA 원문 파생이라, 답 출처 QNA가 근거로 끌려오면
    #      자기 답 자기 참조(순환)가 된다. 본문+판단트리만으로 재현되는지 격리 측정.
    exclude_qna: bool = False

    # generate 프롬프트 문서 상한 — 유형별 슬롯 (07-retrieval-priority §3).
    # Why: 총량 상한은 문단이 사례·감리를 밀어낸다. 유형을 분리해 각 근거 유형을 보존.
    #      문단 슬롯은 fetch가 topic_hint 진입순서를 보존 → 앞쪽이 질문 주제 문단.
    # A안(C 상한밀림 해소): 문단은 무제한(0)으로 상한 컷을 제거한다. gold 조문이
    #      진입만 하면 위치와 무관하게 generate가 본다. 문단은 값싼 입력토큰이라
    #      비용 증가가 작다(케이스당 +약 8~13원). IE(케이스당 77건)·감리는 노이즈·비용
    #      폭증이라 슬롯 유지. 0 = 무제한.
    doc_slot_para: int = 0
    doc_slot_ie: int = 3
    doc_slot_findings: int = 2
    doc_slot_qna: int = 3

    # topic_hint 개념의 주제군 계층 확장 임계 (07-retrieval-priority gap).
    # Why: topic_map이 말단 개념 1개만 가리켜 형제(같은 주제군)를 놓친다. 부모 subtree가
    #      이 값 이하면 형제를 포함, 초과(부록B 24개 등)하면 폭발 방지로 자기 하위만.
    #      값은 진입 개념 폭발 억제(예산)용이며 골든셋 커버리지 튜닝값이 아니다.
    subtree_expand_max: int = 8

    # 7. 인프라 설정
    # CORS: Streamlit(:8501) → FastAPI(:8002) 교차 요청 허용 목록
    # Why: Docker 내부(http://frontend:8501)와 외부 접속(http://공인IP:8501) 모두 허용 필요
    # .env에서 CORS_ORIGINS='["http://localhost:8501","http://공인IP:8501"]' 형태로 오버라이드
    cors_origins: list[str] = ["http://localhost:8501"]
    # Upstage 임베딩 API 엔드포인트
    upstage_embed_url: str = "https://api.upstage.ai/v1/solar/embeddings"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()

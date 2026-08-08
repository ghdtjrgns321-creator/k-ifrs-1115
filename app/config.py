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
    # temperature 0은 결정성을 보장하지 않는다(같은 질문에 진입 개념이 달라지는
    # 현상 관측). OpenAI seed로 best-effort 재현성을 건다 — Gemini 경로는 미지원.
    llm_seed: int = 1115
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

    # 임베딩 진입 개수. 0이면 이 통로 비활성.
    # Why(값): exp_decision.md에서 3·5·7이 모두 같은 결과(56/57)라 최소값을 취했다.
    #          임계값·가중치는 두지 않는다 — 점수는 순위 결정에만 쓰고 다른 신호와 섞지 않는다.
    entry_embed_top_k: int = 3

    # 순회에서 개념을 넓히는 규칙. "none" | "kin1"
    #   none — 진입 개념 그 자리에서만 걷는다 (현행)
    #   kin1 — 부모 1홉 + 자식 1홉까지 넓혀서 걷는다
    # Why(선택지가 둘뿐): 홀드아웃 실측에서 깊이는 값을 못 했고(자식 전체 vs 1홉 +1),
    #   5단계 이웃은 이득 0, 형제까지 열면 기준서 문단의 70%가 들어온다.
    #   회수만 보면 항상 넓은 쪽이 이기므로 답 품질 채점으로 가른다(A/B).
    #   근거: dev/entry-traverse/results-traverse.md §13·§16
    traverse_expand: str = "none"

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

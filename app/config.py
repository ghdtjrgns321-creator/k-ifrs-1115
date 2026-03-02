from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # 1. MongoDB 설정
    mongo_uri: str
    mongo_db_name: str = "kifrs_db"
    # 본문 + QNA Child + Findings Child가 모두 저장되는 공유 컬렉션
    mongo_collection_name: str = "k-ifrs-1115-chatbot"

    # 2. API 키 (필수)
    upstage_api_key: str  # 임베딩 전용
    openai_api_key: str   # LLM 전용
    cohere_api_key: str   # Reranker 전용 (rerank-multilingual-v3.0)

    # 3. LangSmith 모니터링 설정 (선택사항)
    langchain_api_key: str | None = None
    langchain_tracing_v2: bool = False
    langchain_project: str = "k-ifrs-1115-chatbot"

    # 4. LLM 모델 설정
    # Front Nodes (analyze, rewrite, grade): 빠른 분류·평가용 경량 모델
    llm_front_model: str = "gpt-5-mini"
    # Generate Node: 복잡한 회계 답변 생성용 추론 모델
    llm_generate_model: str = "o4-mini"
    llm_temperature: float = 0.0
    # API 응답 대기 최대 시간(초) — o4-mini 추론 모델은 복잡한 케이스에서 70-80초 소요 가능
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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

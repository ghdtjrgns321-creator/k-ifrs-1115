from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # 1. MongoDB 설정
    mongo_uri: str
    mongo_db_name: str = "kifrs_db"
    # 본문 + QNA Child + Findings Child가 모두 저장되는 공유 컬렉션
    mongo_collection_name: str = "k-ifrs-1115-chatbot"

    # 2. API 키 (필수)
    upstage_api_key: str

    # 3. LangSmith 모니터링 설정 (선택사항)
    langchain_api_key: str | None = None
    langchain_tracing_v2: bool = False
    langchain_project: str = "k-ifrs-1115-chatbot"

    # 4. LLM 모델 설정
    llm_model: str = "solar-pro3"
    llm_temperature: float = 0.0
    # API 응답 대기 최대 시간(초) — 초과 시 TimeoutError 발생하여 파이프라인이 뻗지 않음
    llm_timeout: int = 60

    # 5. 임베딩 모델 (passage/query 혼용 시 검색 품질 급락 — 혼용 금지)
    # passage: 문서를 DB에 저장(적재)할 때 사용용
    # query:   사용자 검색어를 임베딩할 때 사용
    embed_passage_model: str = "solar-embedding-1-large-passage"
    embed_query_model: str = "solar-embedding-1-large-query"
    embed_batch_size: int = 100  # API 과부하 방지용 배치 단위

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
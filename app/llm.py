# app/llm.py
# LLM 싱글턴 관리 — 모든 노드가 이 함수를 통해 동일한 설정으로 LLM을 사용합니다.
# 각 노드에서 ChatUpstage(...)를 직접 만들지 않고 여기서 받아 씁니다.
from langchain_upstage import ChatUpstage
from app.config import settings


def get_llm() -> ChatUpstage:
    """
    설정 기반 ChatUpstage 인스턴스를 반환합니다.

    - temperature=0 : 회계 답변 일관성 최우선
    - request_timeout: API가 응답 없이 멈추는 상황(hang)을 방지
      초과 시 TimeoutError가 발생하여 파이프라인이 무한 대기하지 않습니다.
    """
    return ChatUpstage(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        upstage_api_key=settings.upstage_api_key,
        request_timeout=settings.llm_timeout,
    )

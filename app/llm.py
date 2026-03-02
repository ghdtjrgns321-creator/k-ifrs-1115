# app/llm.py
# LLM 팩토리 — 노드 역할별로 다른 모델을 사용합니다.
#
# Front Nodes (analyze, rewrite, grade): gpt-5-mini
#   - 빠른 분류·평가가 목적이므로 경량 모델로 충분합니다.
#
# Generate Node: o4-mini
#   - 복잡한 회계 답변을 정확하게 생성해야 하므로 추론 특화 모델을 사용합니다.
#   - reasoning 모델은 temperature를 지원하지 않아 별도로 생성합니다.
from langchain_openai import ChatOpenAI
from app.config import settings


def get_front_llm() -> ChatOpenAI:
    """analyze / rewrite / grade 노드용 경량 LLM."""
    return ChatOpenAI(
        model=settings.llm_front_model,
        temperature=settings.llm_temperature,
        api_key=settings.openai_api_key,
        timeout=settings.llm_timeout,
    )


def get_generate_llm() -> ChatOpenAI:
    """generate 노드용 추론 LLM (o4-mini).

    reasoning 모델은 temperature 파라미터를 지원하지 않으므로 생략합니다.
    """
    return ChatOpenAI(
        model=settings.llm_generate_model,
        api_key=settings.openai_api_key,
        timeout=settings.llm_timeout,
    )


def get_hyde_llm() -> ChatOpenAI:
    """HyDE 가상 문서 생성 전용 LLM.

    3-5문장짜리 짧은 텍스트만 생성하므로 타임아웃을 짧게 유지합니다.
    초과 시 retriever.py에서 원본 쿼리로 즉시 폴백하여 파이프라인 지연을 차단합니다.
    """
    return ChatOpenAI(
        model=settings.llm_front_model,
        temperature=settings.llm_temperature,
        api_key=settings.openai_api_key,
        timeout=settings.llm_hyde_timeout,
    )

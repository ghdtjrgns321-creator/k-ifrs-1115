# app/nodes/analyze.py
# 사용자 질문 분석 + 라우팅 + tree_matcher 체크리스트 매칭
from app.agents import analyze_agent
from app.domain.tree_matcher import match_topics


async def analyze_query(state: dict) -> dict:
    """사용자 질문을 분석하여 멀티턴을 재구성하고 라우팅 방향을 결정합니다."""

    # 최근 3턴만 전달하여 토큰 절약
    formatted_messages = "\n".join(
        f"{role}: {content}" for role, content in state.get("messages", [])[-3:]
    )

    result = await analyze_agent.run(
        f"최신 대화 기록 및 질문: {formatted_messages}"
    )
    data = result.output

    # is_situation=True일 때만 체크리스트 매칭 (개념 질문에는 미적용)
    matched = (
        match_topics(data.standalone_query, data.search_keywords)
        if data.is_situation
        else []
    )

    return {
        "routing": data.routing,
        "standalone_query": data.standalone_query,
        "is_situation": data.is_situation,
        "search_keywords": data.search_keywords,
        "matched_topics": matched,
        "confusion_point": data.confusion_point,
        "complexity": data.complexity,
    }

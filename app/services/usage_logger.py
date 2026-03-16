# app/services/usage_logger.py
# 실사용 데이터를 MongoDB usage_logs 컬렉션에 저장 + 규칙 기반 자동 채점.
#
# 호출 지점: chat_service.py — done 이벤트 직후
# 실패해도 답변 흐름에 영향 없도록 예외를 삼킴.
# 규칙 기반 채점은 메모리 내 if/else (~1ms)라 UX 영향 없음.

import logging
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import MongoClient

logger = logging.getLogger(__name__)

_client: MongoClient | None = None
_COLLECTION_NAME = "usage_logs"


def _get_collection():
    """usage_logs 컬렉션을 반환합니다. 첫 호출 시 클라이언트 생성."""
    global _client
    if _client is None:
        from app.config import settings
        _client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=3000)
    from app.config import settings
    return _client[settings.mongo_db_name][_COLLECTION_NAME]


# ── 규칙 기반 자동 채점 (메모리 내 연산, API 호출 없음) ────────────────


def _score_response_time(ms: int) -> float:
    """응답 시간 점수. 빠를수록 높다."""
    if ms <= 15_000:
        return 1.0
    if ms <= 25_000:
        return 0.7
    if ms <= 40_000:
        return 0.4
    return 0.1


def _score_citation_coverage(cited: list[str], answer: str) -> float:
    """인용 커버리지. 근거 문단을 충분히 가져왔는가."""
    n = len(cited)
    if n >= 4:
        base = 1.0
    elif n >= 2:
        base = 0.7
    elif n >= 1:
        base = 0.4
    else:
        return 0.0
    # 답변에서 "문단"을 실제로 언급했는지 보너스
    if answer.count("문단") >= 3:
        base = min(base + 0.1, 1.0)
    return base


def _score_topic_match(
    topics: list[str], is_situation: bool, keywords: list[str],
) -> float:
    """토픽 매칭 적절성."""
    if not is_situation:
        return 0.9 if len(keywords) >= 3 else 0.7
    if not topics:
        return 0.2
    return 1.0 if len(topics) >= 2 else 0.7


def _score_conclusion_safety(
    is_situation: bool, is_conclusion: bool,
    branches: list[str], answer: str,
) -> float:
    """결론 신중성. 성급하게 결론 내리지 않았는가."""
    if not is_situation:
        return 1.0
    if is_conclusion and branches:
        return 1.0
    if is_conclusion and not branches:
        caution = ["추가 정보", "확인이 필요", "판단이 필요", "고려해야"]
        return 0.7 if any(kw in answer for kw in caution) else 0.4
    return 0.9


# 가중치 (규칙 기반 4개, 총합 1.0으로 정규화)
_WEIGHTS = {
    "response_time": 0.20,
    "citation_coverage": 0.35,
    "topic_match": 0.20,
    "conclusion_safety": 0.25,
}


def _auto_score(
    *, answer: str, cited: list[str], topics: list[str],
    keywords: list[str], is_situation: bool, is_conclusion: bool,
    branches: list[str], response_time_ms: int,
) -> dict:
    """규칙 기반 4개 메트릭 채점 + 가중 평균 산출."""
    metrics = {
        "response_time": _score_response_time(response_time_ms),
        "citation_coverage": _score_citation_coverage(cited, answer),
        "topic_match": _score_topic_match(topics, is_situation, keywords),
        "conclusion_safety": _score_conclusion_safety(
            is_situation, is_conclusion, branches, answer,
        ),
    }
    total = sum(metrics[k] * _WEIGHTS[k] for k in metrics) / sum(_WEIGHTS.values())
    return {
        "metrics": metrics,
        "total": round(total, 3),
        "mode": "rule",
        "scored_at": datetime.now(timezone.utc),
    }


# ── 로깅 + 채점 ─────────────────────────────────────────────────────


def log_chat_response(
    *,
    session_id: str,
    question: str,
    answer: str,
    matched_topics: list[str] | None = None,
    search_keywords: list[str] | None = None,
    cited_paragraphs: list[str] | None = None,
    is_situation: bool = False,
    needs_calculation: bool = False,
    is_conclusion: bool = False,
    selected_branches: list[str] | None = None,
    response_time_ms: int = 0,
) -> str | None:
    """채팅 응답 로그 저장 + 규칙 기반 자동 채점.

    Returns:
        str: 저장된 문서의 _id (피드백 연결용). 실패 시 None.
    """
    try:
        cited = cited_paragraphs or []
        topics = matched_topics or []
        keywords = search_keywords or []
        branches = selected_branches or []
        truncated_answer = answer[:2000]

        # 규칙 기반 자동 채점 (~1ms, UX 영향 없음)
        auto_scores = _auto_score(
            answer=truncated_answer,
            cited=cited,
            topics=topics,
            keywords=keywords,
            is_situation=is_situation,
            is_conclusion=is_conclusion,
            branches=branches,
            response_time_ms=response_time_ms,
        )

        doc = {
            "session_id": session_id,
            "question": question,
            "answer": truncated_answer,
            "matched_topics": topics,
            "search_keywords": keywords,
            "cited_paragraphs": cited,
            "is_situation": is_situation,
            "needs_calculation": needs_calculation,
            "is_conclusion": is_conclusion,
            "selected_branches": branches,
            "response_time_ms": response_time_ms,
            "feedback": None,
            "feedback_at": None,
            "auto_scores": auto_scores,
            "timestamp": datetime.now(timezone.utc),
        }
        result = _get_collection().insert_one(doc)
        logger.info(
            "usage_log saved: %s (score: %.2f)",
            result.inserted_id, auto_scores["total"],
        )
        return str(result.inserted_id)
    except Exception as exc:
        logger.warning("usage_log 저장 실패: %s", exc)
        return None


def update_feedback(log_id: str, feedback: str, reason: str = "") -> bool:
    """사용자 피드백(up/down + 사유)을 기존 로그에 업데이트합니다."""
    if feedback not in ("up", "down"):
        return False
    try:
        update_fields: dict = {
            "feedback": feedback,
            "feedback_at": datetime.now(timezone.utc),
        }
        if reason:
            update_fields["feedback_reason"] = reason[:500]
        result = _get_collection().update_one(
            {"_id": ObjectId(log_id)},
            {"$set": update_fields},
        )
        return result.modified_count > 0
    except Exception as exc:
        logger.warning("feedback 업데이트 실패: %s", exc)
        return False

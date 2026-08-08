# app/services/usage_logger.py
# 실사용 데이터를 MongoDB usage_logs 컬렉션에 저장. 채점은 하지 않는다.
#
# 호출 지점: chat_service.py — done 이벤트 직후
# 실패해도 답변 흐름에 영향 없도록 예외를 삼킴.
#
# Why(채점 제거): 규칙 기반 4메트릭 가중 채점(response_time 0.20 / citation 0.35 /
# topic 0.20 / conclusion 0.25)을 폐기했다. 가중치·구간이 전부 임의값이고, 총점이
# 생기면 루프가 "총점을 올리는 방향"으로 최적화되는데 그 방향이 품질 방향이라는
# 보장이 없다. 채점은 오프라인 배치에서 층별로 따로 한다(docs/quality-loop/02).

import logging
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import MongoClient

logger = logging.getLogger(__name__)

_client: MongoClient | None = None
_COLLECTION_NAME = "usage_logs"

# 스키마 버전 — 채점 배치가 호환되지 않는 로그를 제외하는 기준
#   1: 진입 흔적 최초 기록 (via_topic·topic_hints — 주제 지목 시절)
#   2: 진입부 재편 반영 (via_llm·term_hints·unknown_terms — 용어사전 경유)
# Why(올린 이유): 필드 이름만 바뀐 게 아니라 통로 자체가 달라졌다. v1 로그를 v2 판정에
# 넣으면 via_llm이 항상 비어 "사전 통로 실패"로 오탐한다.
SCHEMA_VER = 2

# 답변 저장 상한. 초과분은 잘리므로 인용 판정이 불완전해진다(answer_len으로 표시).
_ANSWER_MAX = 2000


def _get_collection():
    """usage_logs 컬렉션을 반환합니다. 첫 호출 시 클라이언트 생성."""
    global _client
    from app.config import settings

    client = _client
    if client is None:
        client = _client = MongoClient(
            settings.mongo_uri, serverSelectionTimeoutMS=3000
        )
    return client[settings.mongo_db_name][_COLLECTION_NAME]


def log_chat_response(
    *,
    session_id: str,
    question: str,
    answer: str,
    flow: str = "full",
    matched_topics: list[str] | None = None,
    cited_paragraphs: list[str] | None = None,
    is_situation: bool = False,
    needs_calculation: bool = False,
    is_conclusion: bool = False,
    selected_branches: list[str] | None = None,
    response_time_ms: int = 0,
    concept_ids: list[str] | None = None,
    via_llm: list[str] | None = None,
    via_embed: list[str] | None = None,
    matched_terms: list[str] | None = None,
    matched_terms_raw: list[str] | None = None,
    term_hints: list[str] | None = None,
    unknown_terms: list[str] | None = None,
    candidate_paras: list[str] | None = None,
    context_paras: list[str] | None = None,
    concept_path: list[str] | None = None,
    doc_count: int = 0,
) -> str | None:
    """채팅 응답 로그 저장.

    flow: 이 응답이 어느 경로로 나왔는지. 진입 흔적이 없는 경로를 채점에서
        제외하는 데 쓴다 — 없으면 전부 "진입 실패"로 오탐된다.
        full / fast_path(되묻기 후속) / pre_retrieved(이전 검색 재사용) / rejected(범위 밖)

    Returns:
        str: 저장된 문서의 _id (피드백 연결용). 실패 시 None.
    """
    try:
        doc = {
            "schema_ver": SCHEMA_VER,
            "session_id": session_id,
            # outcome: 답변이 끝까지 나왔나. 실패 질의는 log_chat_error가 error로 남긴다.
            "outcome": "ok",
            "flow": flow,
            "question": question,
            "answer": answer[:_ANSWER_MAX],
            "answer_len": len(answer),
            "matched_topics": matched_topics or [],
            "cited_paragraphs": cited_paragraphs or [],
            "is_situation": is_situation,
            "needs_calculation": needs_calculation,
            "is_conclusion": is_conclusion,
            "selected_branches": selected_branches or [],
            "response_time_ms": response_time_ms,
            "entry": {
                "concept_ids": concept_ids or [],
                "via_llm": via_llm or [],
                "via_embed": via_embed or [],
                # matched_terms: 재작성문(standalone_query) 기준 — 실제 진입에 쓰인 매칭
                "matched_terms": matched_terms or [],
                # matched_terms_raw: 사용자 원문 기준 — 용어사전 보강 판단용
                "matched_terms_raw": matched_terms_raw or [],
                # term_hints: LLM이 고른 용어 원본. via_llm이 비었을 때
                # 지시문 문제인지 사전 문제인지 가른다.
                "term_hints": term_hints or [],
                # unknown_terms: LLM이 댔지만 사전에 없던 말 — 사전 보강 대상
                "unknown_terms": unknown_terms or [],
            },
            "retrieval": {
                # paras: 그래프가 찾아낸 문단 후보 전량 (검색이 무엇을 건져왔나)
                "paras": candidate_paras or [],
                # context_paras: generate가 실제로 LLM에 넣은 문단
                # Why: 인용 판정의 기준은 후보가 아니라 LLM이 본 것이다. 계산 질문은
                # IE 적용사례를 컨텍스트에서 제외하므로 두 집합이 어긋난다.
                "context_paras": context_paras or [],
                "concept_path": concept_path or [],
                "doc_count": doc_count,
            },
            "feedback": None,
            "feedback_at": None,
            "timestamp": datetime.now(timezone.utc),
        }
        result = _get_collection().insert_one(doc)
        logger.info(
            "usage_log saved: %s (flow=%s, concepts=%d, paras=%d)",
            result.inserted_id,
            flow,
            len(doc["entry"]["concept_ids"]),
            len(doc["retrieval"]["paras"]),
        )
        return str(result.inserted_id)
    except Exception as exc:
        logger.warning("usage_log 저장 실패: %s", exc)
        return None


def log_chat_error(
    *,
    session_id: str,
    question: str,
    error_type: str,
    error_message: str = "",
    response_time_ms: int = 0,
) -> str | None:
    """실패한 질의를 남긴다.

    Why: 로그가 done 이벤트에만 붙어 있으면 타임아웃·예외로 끝난 질의는 흔적이
    사라지고, 남은 로그는 전부 성공 사례가 된다. 성공한 것만 보고 품질을 논하는
    표본 편향을 막으려면 실패도 같은 컬렉션에 남아야 한다.

    진입·검색 흔적은 담지 않는다 — 실패 지점이 어디였는지 모르므로 채점 대상이
    아니고, outcome != "ok" 인 로그는 채점 배치가 건너뛴다.
    """
    try:
        doc = {
            "schema_ver": SCHEMA_VER,
            "session_id": session_id,
            "outcome": "error",
            "flow": "error",
            "question": question,
            "answer": "",
            "answer_len": 0,
            "error_type": error_type,
            "error_message": (error_message or "")[:500],
            "response_time_ms": response_time_ms,
            "timestamp": datetime.now(timezone.utc),
        }
        result = _get_collection().insert_one(doc)
        logger.info("usage_log(error) saved: %s (%s)", result.inserted_id, error_type)
        return str(result.inserted_id)
    except Exception as exc:
        logger.warning("usage_log(error) 저장 실패: %s", exc)
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

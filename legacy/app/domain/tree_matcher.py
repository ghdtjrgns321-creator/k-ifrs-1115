"""통합 매칭 로직: 키워드 + 임베딩 유사도 + topic_hints 3중 매칭

analyze 노드가 추출한 standalone_query + search_keywords를
trigger_keywords 키워드 매칭 + 토픽 임베딩 코사인 유사도로 스코어링하여
is_situation=True일 때 CLARIFY_PROMPT에 주입할 체크리스트 텍스트를 생성합니다.
"""

import json
import logging
from pathlib import Path

from app.domain.decision_trees import MASTER_DECISION_TREES
from app.domain.summary_matcher import cosine_similarity

logger = logging.getLogger(__name__)

# ── 토픽 임베딩 Lazy 로드 ──────────────────────────────────────────────
_TOPIC_EMBED_PATH = (
    Path(__file__).parent.parent.parent
    / "data"
    / "topic-curation"
    / "topic-embeddings.json"
)
_topic_embeddings: dict[str, list[float]] | None = None

# 임베딩 유사도 가중치 — 상대적 랭킹 보조 신호로 사용
# Why: Upstage 임베딩의 절대 유사도가 0.29~0.47 범위로 낮으므로
#      가중치를 높이고 임계값을 낮춰 keyword 매칭을 보완
_EMBED_WEIGHT = 10.0
# 유사도 임계값 — 절대값이 낮으므로 보수적으로 설정
# 테스트 결과: 정답 토픽 유사도 0.29~0.47, 오답 0.25 이하
_EMBED_THRESHOLD = 0.28


def _load_topic_embeddings():
    global _topic_embeddings
    _topic_embeddings = {}
    if not _TOPIC_EMBED_PATH.exists():
        logger.warning("topic-embeddings.json 없음 — 임베딩 매칭 비활성")
        return
    raw = json.loads(_TOPIC_EMBED_PATH.read_text(encoding="utf-8"))
    for name, data in raw.items():
        _topic_embeddings[name] = data["embedding"]
    logger.info("토픽 임베딩 %d개 로드", len(_topic_embeddings))


def _get_topic_embeddings() -> dict[str, list[float]]:
    if _topic_embeddings is None:
        _load_topic_embeddings()
    return _topic_embeddings


def _calc_embedding_scores(query_vector: list[float]) -> dict[str, float]:
    """쿼리 벡터와 각 토픽 임베딩의 코사인 유사도를 계산합니다."""
    topic_embeds = _get_topic_embeddings()
    if not topic_embeds or not query_vector:
        return {}
    return {
        name: cosine_similarity(query_vector, emb)
        for name, emb in topic_embeds.items()
    }


# ── 메인 매칭 함수 ──────────────────────────────────────────────────


def match_topics(
    standalone_query: str,
    search_keywords: list[str],
    topic_hints: list[str] | None = None,
    user_message: str = "",
) -> list[dict]:
    """3중 매칭: 키워드 + 임베딩 유사도 + topic_hints → 상위 3개 반환.

    스코어 구성:
      - keyword 매칭: 0~수십 (trigger 개수에 비례)
      - topic_hints: +5.0 (LLM이 추론한 토픽)
      - 임베딩 유사도: sim * _EMBED_WEIGHT (임계값 이상만)

    Why: keyword만으로는 일상 언어 질문에서 토픽 매칭 실패.
         임베딩 유사도로 "A→B→C 재판매" ↔ "본인 vs 대리인" 의미적 매칭 보완.
    """
    # 쿼리 임베딩 (Upstage query 모델, ~100ms × 2)
    # Why: standalone_query(LLM 재작성)와 user_message(원본) 두 벡터를 모두 계산하여
    #       토픽별 max 유사도를 취함. LLM 재작성에서 의미가 희석되는 문제를 원본으로 보완.
    from app.embeddings import embed_query_sync

    query_vector = embed_query_sync(standalone_query)
    user_vector = embed_query_sync(user_message) if user_message else []

    query_embed_scores = _calc_embedding_scores(query_vector)
    user_embed_scores = _calc_embedding_scores(user_vector)

    candidates: list[dict] = []
    hint_set = set(topic_hints) if topic_hints else set()

    for topic_name, data in MASTER_DECISION_TREES.items():
        routing = data["1_routing"]
        score = _calc_score(
            standalone_query, search_keywords, routing["trigger_keywords"],
            user_message=user_message,
        )

        # topic_hints 가산: 임베딩(~4.0)보다 낮게 설정
        # Why: LLM hints가 잘못된 토픽을 줄 때 임베딩 매칭을 방해하는 역효과 방지
        if topic_name in hint_set:
            score += 3.0

        # 임베딩 유사도 가산 — standalone_query와 user_message 중 max
        embed_sim = max(
            query_embed_scores.get(topic_name, 0.0),
            user_embed_scores.get(topic_name, 0.0),
        )
        if embed_sim >= _EMBED_THRESHOLD:
            score += embed_sim * _EMBED_WEIGHT

        if score > 0:
            candidates.append(
                {
                    "topic_name": topic_name,
                    "checklist_text": _format_checklist(topic_name, data),
                    "checklist": data["2_checklist"],
                    "judgment_goal": routing["judgment_goal"],
                    "precedents": data.get("4_precedents", {}),
                    "red_flags": data.get("5_red_flags", {}),
                    "calculation_formula": data.get("6_calculation_formula"),
                    "critical_factors": data.get("7_critical_factors", []),
                    "score": score,
                }
            )

    candidates.sort(key=lambda x: x["score"], reverse=True)
    top = candidates[:3]

    if top:
        logger.info(
            "topic match: %s",
            [(c["topic_name"], round(c["score"], 1)) for c in top],
        )

    return top


# ── 매칭 점수 계산 ──────────────────────────────────────────────


def _calc_score(
    query: str, keywords: list[str], triggers: list[str], user_message: str = "",
) -> float:
    """양방향 부분 문자열 매칭으로 점수를 산출합니다.

    - search_keywords 매칭: 가중치 2.0 (LLM이 추출한 핵심 용어이므로 신뢰도 높음)
    - standalone_query 매칭: 가중치 1.0 (전체 문장에서 부분 매칭)
    - user_message 매칭: 가중치 0.5 (원본 메시지에서 결정적 보완)
    - 완전 일치: 추가 보너스 1.0 (부분 매칭보다 정확도 높음)
    - 1자 키워드/트리거: false positive 방지를 위해 스킵
    """
    score = 0.0
    query_lower = query.lower()

    for trigger in triggers:
        trigger_lower = trigger.lower()
        if len(trigger_lower) < 2:
            continue

        for kw in keywords:
            kw_lower = kw.lower()
            if len(kw_lower) < 2:
                continue
            if kw_lower in trigger_lower or trigger_lower in kw_lower:
                score += 2.0
                if kw_lower == trigger_lower:
                    score += 1.0
                break

        if trigger_lower in query_lower:
            score += 1.0

    # 원본 사용자 메시지에서 trigger 매칭 (가중치 0.5)
    # Why: LLM 재작성에서 누락된 키워드를 원본에서 결정적으로 보완
    if user_message:
        user_lower = user_message.lower()
        for trigger in triggers:
            trigger_lower = trigger.lower()
            if len(trigger_lower) < 2:
                continue
            if trigger_lower in user_lower:
                score += 0.5

    return score


# ── 통합 포맷팅 ──────────────────────────────────────────────────


def _format_checklist(topic_name: str, data: dict) -> str:
    """MASTER_DECISION_TREES 항목을 통합 체크리스트 텍스트로 포맷합니다.

    포함: 2_checklist + 3_conclusion_guide + 5_red_flags
    미포함: 4_precedents, 6_calculation_formula (Phase 4에서 generate.py context 주입)
    """
    routing = data["1_routing"]
    lines = [f"[판단 체크리스트: {topic_name}]"]
    lines.append(f"목표: {routing['judgment_goal']}")

    for i, item in enumerate(data["2_checklist"], 1):
        lines.append(f"  {i}. {item}")

    # 결론 가이드
    if data.get("3_conclusion_guide"):
        lines.append("")
        lines.append("[결론 가이드]")
        for guide in data["3_conclusion_guide"]:
            lines.append(f"  {guide}")

    # Red Flags
    red_flags = data.get("5_red_flags")
    if red_flags:
        lines.append("")
        lines.append(red_flags["warning_prefix"])
        for branch_label, questions in red_flags.get(
            "check_items_by_branch", {}
        ).items():
            lines.append(f"  {branch_label}:")
            for q in questions:
                lines.append(f"    {q}")

    return "\n".join(lines)

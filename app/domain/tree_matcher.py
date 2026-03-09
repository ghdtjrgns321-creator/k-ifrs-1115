"""통합 매칭 로직: Decision Tree + QNA Match + Red Flag 패턴에서 키워드 매칭

analyze 노드가 추출한 standalone_query + search_keywords를
3개 dict의 trigger_keywords와 양방향 부분 문자열 매칭하여
is_situation=True일 때 CLARIFY_PROMPT에 주입할 체크리스트 텍스트를 생성합니다.
"""

from app.domain.decision_trees import DECISION_TREES
from app.domain.qna_match_trees import QNA_MATCH_TREES
from app.domain.red_flags import RED_FLAG_PATTERNS


def match_topics(standalone_query: str, search_keywords: list[str]) -> list[dict]:
    """3개 dict에서 키워드 매칭 → 타입별 최고 score 1개 → 상위 2개 반환.

    Returns:
        [{tree_type, topic_name, checklist_text, score}, ...]
        매칭 없으면 빈 리스트 → 기존 동작 100% 호환
    """
    candidates: list[dict] = []

    # 각 데이터 소스를 순회하며 매칭 점수를 계산
    for topic_name, data in DECISION_TREES.items():
        score = _calc_score(standalone_query, search_keywords, data["trigger_keywords"])
        if score > 0:
            candidates.append({
                "tree_type": "decision_tree",
                "topic_name": topic_name,
                "checklist_text": _format_decision_tree(topic_name, data),
                "score": score,
            })

    for topic_name, data in QNA_MATCH_TREES.items():
        score = _calc_score(standalone_query, search_keywords, data["trigger_keywords"])
        if score > 0:
            candidates.append({
                "tree_type": "qna_match",
                "topic_name": topic_name,
                "checklist_text": _format_qna_match(topic_name, data),
                "score": score,
            })

    for topic_name, data in RED_FLAG_PATTERNS.items():
        score = _calc_score(standalone_query, search_keywords, data["trigger_keywords"])
        if score > 0:
            candidates.append({
                "tree_type": "red_flag",
                "topic_name": topic_name,
                "checklist_text": _format_red_flag(topic_name, data),
                "score": score,
            })

    # 타입별 최고 score 1개씩 선발
    best_by_type: dict[str, dict] = {}
    for c in candidates:
        t = c["tree_type"]
        if t not in best_by_type or c["score"] > best_by_type[t]["score"]:
            best_by_type[t] = c

    # 전체를 score 내림차순 → 상위 2개
    result = sorted(best_by_type.values(), key=lambda x: x["score"], reverse=True)
    return result[:2]


# ── 매칭 점수 계산 ──────────────────────────────────────────────

def _calc_score(query: str, keywords: list[str], triggers: list[str]) -> float:
    """양방향 부분 문자열 매칭으로 점수를 산출합니다.

    - search_keywords 매칭: 가중치 2.0 (LLM이 추출한 핵심 용어이므로 신뢰도 높음)
    - standalone_query 매칭: 가중치 1.0 (전체 문장에서 부분 매칭)
    """
    score = 0.0
    query_lower = query.lower()

    for trigger in triggers:
        trigger_lower = trigger.lower()

        # search_keywords와 매칭 (가중치 2.0)
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in trigger_lower or trigger_lower in kw_lower:
                score += 2.0
                break  # 동일 trigger에 대해 중복 가산 방지

        # standalone_query와 매칭 (가중치 1.0)
        if trigger_lower in query_lower or query_lower in trigger_lower:
            score += 1.0

    return score


# ── 타입별 포맷팅 함수 ──────────────────────────────────────────

def _format_decision_tree(topic_name: str, data: dict) -> str:
    """DECISION_TREES 항목을 체크리스트 텍스트로 포맷합니다."""
    lines = [f"[판단 체크리스트: {topic_name}]"]
    lines.append(f"목표: {data['judgment_goal']}")
    for i, item in enumerate(data["checklist"], 1):
        lines.append(f"  {i}. {item}")
    return "\n".join(lines)


def _format_qna_match(topic_name: str, data: dict) -> str:
    """QNA_MATCH_TREES 항목을 condition/question/yes/no 구조로 포맷합니다."""
    lines = [f"[질의회신 기반 체크리스트: {topic_name}]"]
    for i, item in enumerate(data["qna_premise_checklist"], 1):
        lines.append(f"  {i}. 판단 조건: {item['condition']}")
        lines.append(f"     질문: {item['question']}")
        lines.append(f"     Yes → {item['yes_path']}")
        lines.append(f"     No  → {item['no_path']}")
    return "\n".join(lines)


def _format_red_flag(topic_name: str, data: dict) -> str:
    """RED_FLAG_PATTERNS 항목을 경고형 텍스트로 포맷합니다."""
    lines = [f"[감리사례 위험신호: {topic_name}]"]
    lines.append(f"경고: {data['warning_prefix']}")
    for i, item in enumerate(data["red_flag_questions"], 1):
        lines.append(f"  {i}. {item['question']}")
    return "\n".join(lines)

# app/domain/summary_matcher.py
# QNA/감리사례/IE 서머리 임베딩 기반 매칭 모듈.
#
# 쿼리 벡터와 사전 임베딩된 서머리의 코사인 유사도로
# 주제에 관련된 QNA/감리사례/적용사례만 정확하게 필터링합니다.

import json
import math
from pathlib import Path
from app.config import settings

# ── 임베딩 데이터 Lazy 로드 ──────────────────────────────────────────────────
_EMBEDDINGS_PATH = Path(__file__).parent.parent.parent / "data" / "topic-curation" / "summary-embeddings.json"

_qna_entries: dict[str, dict] | None = None      # {id: {desc, topic, embedding}}
_finding_entries: dict[str, dict] | None = None
_ie_entries: dict[str, dict] | None = None        # {id: {desc, topic, title, para_range, embedding}}


def _load():
    """서머리 임베딩 JSON을 로드하여 QNA/감리사례/IE로 분리합니다."""
    global _qna_entries, _finding_entries, _ie_entries
    _qna_entries = {}
    _finding_entries = {}
    _ie_entries = {}
    if not _EMBEDDINGS_PATH.exists():
        return
    raw = json.loads(_EMBEDDINGS_PATH.read_text(encoding="utf-8"))
    for doc_id, data in raw.items():
        entry = {"embedding": data["embedding"], "topic": data["topic"], "desc": data["desc"]}
        if data["type"] == "qna":
            _qna_entries[doc_id] = entry
        elif data["type"] == "finding":
            _finding_entries[doc_id] = entry
        elif data["type"] == "ie":
            entry["title"] = data.get("title", "")
            entry["para_range"] = data.get("para_range", "")
            _ie_entries[doc_id] = entry


def _ensure_loaded():
    if _qna_entries is None:
        _load()


# ── 코사인 유사도 ─────────────────────────────────────────────────────────────

def cosine_similarity(a: list, b: list) -> float:
    """두 벡터의 코사인 유사도. numpy 없이 순수 Python."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── 매칭 함수 ─────────────────────────────────────────────────────────────────

def match_qna_by_summary(
    query_vector: list[float],
    threshold: float | None = None,
    max_count: int | None = None,
) -> list[str]:
    """쿼리 벡터와 QNA 서머리 유사도 비교 → threshold 이상인 parent_id 반환."""
    _ensure_loaded()
    threshold = threshold or settings.qna_summary_threshold
    max_count = max_count or settings.qna_summary_max

    scored = []
    for qid, entry in _qna_entries.items():
        sim = cosine_similarity(query_vector, entry["embedding"])
        if sim >= threshold:
            scored.append((qid, sim))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [qid for qid, _ in scored[:max_count]]


def match_findings_by_summary(
    query_vector: list[float],
    threshold: float | None = None,
) -> dict | None:
    """쿼리 벡터와 감리사례 서머리 유사도 비교 → 최고 유사도 사례 반환."""
    _ensure_loaded()
    threshold = threshold or settings.findings_summary_threshold

    best_id = None
    best_score = 0.0
    best_topic = ""

    for fid, entry in _finding_entries.items():
        sim = cosine_similarity(query_vector, entry["embedding"])
        if sim > best_score:
            best_score = sim
            best_id = fid
            best_topic = entry["topic"]

    if best_score < threshold or best_id is None:
        return None

    return {"parent_id": best_id, "score": round(best_score, 4), "topic": best_topic}


def match_ie_by_summary(
    query_vector: list[float],
    threshold: float | None = None,
    max_count: int | None = None,
) -> list[dict]:
    """쿼리 벡터와 IE 적용사례 서머리 유사도 비교 → 관련 사례 반환.

    Returns:
        [{"title": ..., "para_range": ..., "topic": ..., "score": ...}, ...]
    """
    _ensure_loaded()
    threshold = threshold or settings.ie_summary_threshold
    max_count = max_count or settings.ie_summary_max

    scored = []
    for ie_id, entry in _ie_entries.items():
        sim = cosine_similarity(query_vector, entry["embedding"])
        if sim >= threshold:
            scored.append({
                "title": entry["title"],
                "para_range": entry["para_range"],
                "topic": entry["topic"],
                "desc": entry["desc"],
                "score": round(sim, 4),
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:max_count]

# app/nodes/format.py
# LLM 답변에 감리사례 넛지를 추가합니다.
import asyncio

from app.domain.summary_matcher import match_findings_by_summary
from app.embeddings import embed_query_sync
from app.retriever import _get_db, FINDINGS_PARENT_COLL


def _find_best_findings_case(user_query: str) -> dict | None:
    """서머리 임베딩 기반으로 가장 관련도 높은 감리사례를 반환합니다."""
    query_vector = embed_query_sync(user_query)
    match = match_findings_by_summary(query_vector)
    if not match:
        return None

    db = _get_db()
    parent = db[FINDINGS_PARENT_COLL].find_one({"_id": match["parent_id"]})
    if not parent:
        return None

    hierarchy = parent.get("metadata", {}).get("hierarchy", "")
    case_title = hierarchy.split(">")[-1].strip() if hierarchy else "관련 감리지적사례"

    return {
        "title": case_title,
        "hierarchy": hierarchy,
        "content": parent.get("content", ""),
        "score": match["score"],
    }


async def format_response(state: dict) -> dict:
    """LLM 답변에 감리사례 넛지를 추가합니다."""

    answer = state.get("answer", "")
    user_query = state.get("standalone_query", "")

    nudge_text = ""
    findings_case = None

    if user_query:
        findings_case = await asyncio.to_thread(
            _find_best_findings_case, user_query
        )
        if findings_case:
            case_title = findings_case["title"]
            nudge_text = (
                f"\n\n**[참고]** 금융감독원 지적사례[{case_title}]가 존재합니다. "
                f"클릭하여 확인하세요."
            )

    return {"answer": answer + nudge_text, "findings_case": findings_case}

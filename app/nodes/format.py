# app/nodes/format.py
# LLM 답변에 감리사례 넛지를 추가합니다 (STEP 5-5).
# 그래프 탐색이 이미 관련 감리사례를 retrieved_docs에 넣으므로, 임베딩 매칭
# (summary_matcher)을 제거하고 수집된 문서에서 직접 감리사례를 고른다.


def _pick_findings_case(docs: list[dict]) -> dict | None:
    """수집 문서 중 감리지적사례를 골라 넛지용 메타를 만든다."""
    for doc in docs:
        if "감리" in str(doc.get("source", "")):
            hierarchy = doc.get("hierarchy", "")
            title = (
                hierarchy.split(">")[-1].strip() if hierarchy else "관련 감리지적사례"
            )
            return {
                "title": title,
                "hierarchy": hierarchy,
                "content": doc.get("full_content") or doc.get("content", ""),
            }
    return None


async def format_response(state: dict) -> dict:
    """LLM 답변에 감리사례 넛지를 추가합니다 (그래프 수집 문서 기반)."""

    answer = state.get("answer", "")
    findings_case = _pick_findings_case(state.get("relevant_docs", []))

    nudge_text = ""
    if findings_case:
        nudge_text = (
            f"\n\n**[참고]** 금융감독원 지적사례[{findings_case['title']}]가 존재합니다. "
            f"클릭하여 확인하세요."
        )

    return {"answer": answer + nudge_text, "findings_case": findings_case}

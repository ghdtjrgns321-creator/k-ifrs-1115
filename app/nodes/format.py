# app/nodes/format.py
from app.state import RAGState
from app.retriever import _get_db, FINDINGS_PARENT_COLL


def format_response(state: RAGState):
    """LLM의 답변을 마크다운으로 포맷팅하고, [상황 B] 섀도우 매칭 넛지를 추가합니다."""

    answer = state.get("answer", "")
    cited_sources = state.get("cited_sources", [])

    # 1. 본문 조항 번호 추출 (섀도우 매칭용)
    paragraphs = set()
    for src in cited_sources:
        if src.get("source") == "본문":
            # 메타데이터에 있는 related_paragraphs(예: [31, 32])를 수집
            for p in src.get("related_paragraphs", []):
                paragraphs.add(str(p))

    # 2. 섀도우 매칭 (감리사례 DB 몰래 뒤지기 - 상황 B)
    nudge_text = ""
    if paragraphs:
        db = _get_db()
        # retriever.py의 상수를 사용하여 컬렉션명 불일치를 방지
        coll = db[FINDINGS_PARENT_COLL]

        # 배열 안의 문단 번호 중 하나라도 일치하는 지적사례 찾기
        matched_case = coll.find_one({"related_paragraphs": {"$in": list(paragraphs)}})

        if matched_case:
            case_title = matched_case.get("title", "관련 감리지적사례")
            p_str = ", ".join(list(paragraphs))
            nudge_text = f"\n\n💡 **덧붙임:** 방금 안내해 드린 문단({p_str})과 관련하여, 금융감독원이 지적한 **[{case_title}]**가 DB에 존재합니다. 궁금하시면 클릭해 보세요."

    # 3. 출처 목록 포맷팅
    source_lines = ["\n\n📌 **참고 근거**"]
    for src in cited_sources:
        source_type = src.get("source", "알 수 없음")
        hierarchy = src.get("hierarchy", "출처 정보 없음")
        source_lines.append(f"• [{source_type}] {hierarchy}")

    # 4. 최종 텍스트 조립 (답변 + 넛지 + 출처 + 유의사항)
    final_text = answer + nudge_text + "\n" + "\n".join(source_lines)
    final_text += "\n\n⚠️ **유의사항:** 이 답변은 기준서 본문 기준이며, 구체적 사안은 전문가 상담이 필요합니다."

    return {"answer": final_text}

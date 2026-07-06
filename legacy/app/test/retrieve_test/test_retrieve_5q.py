"""5개 테스트 질문의 pinpoint/retriever 분리 검증 스크립트.

PYTHONPATH=. uv run --env-file .env python app/test/test_retrieve_5q.py
"""
import asyncio
import logging

logging.basicConfig(level=logging.WARNING)

from app.nodes.analyze import analyze_query
from app.retriever import fetch_pinpoint_docs, search_all, _parse_doc_ids_from_text
from app.nodes.retrieve import (
    _expand_with_query_mapping,
    _extract_checklist_keywords,
    _merge_pinpoint_and_retriever,
    RETRIEVAL_LIMIT,
)
from app.nodes.generate import _get_last_human_message

QUESTIONS = [
    {
        "id": "T1",
        "label": "본인/대리인 (A→B→C 재판매)",
        "text": "A가 B에게 재화(완성된 의류)를 100원에 공급하고 이 때 공급가액(100원)으로 세금계산서를 끊음. 이후 B는 최종 고객 C에게 재화를 120원에 판매하는데, 이 경우 A가 인식하여야 할 매출액은 100원인지, 120원인지 궁금합니다.",
    },
    {
        "id": "T2",
        "label": "변동대가 이론 질문",
        "text": "K-IFRS 1115호에서 변동대가는 언제, 어떻게 수익으로 인식해야 해? 그냥 예상되는 금액 전부 다 매출로 잡으면 되는 거야?",
    },
    {
        "id": "T3",
        "label": "볼륨 디스카운트 (완결 사례)",
        "text": "A사는 B사에게 제품 1,000개를 개당 100원에 납품하기로 계약했습니다. 단, 계약서에는 \"B사가 1년 내에 1,000개를 모두 구매하면, 전체 물량에 대해 단가를 90원으로 소급 적용해 준다(볼륨 디스카운트)\"는 조건이 있습니다. 현재 2분기에 B사가 이미 1,000개 구매를 완료하여 대량 구매 조건(불확실성)이 완전히 해소되었습니다. 2분기에 A사는 수익을 어떻게 인식해야 하나요?",
    },
    {
        "id": "T4",
        "label": "가공매출 (회수 가능성)",
        "text": "이번 연말에 목표 실적을 채워야 해서, 평소 거래하던 도매처에 물건을 대량으로 출고했습니다. 도매처 사정이 안 좋아서 대금 지급은 무기한 보류하기로 합의서까지 썼습니다. 일단 세금계산서도 끊었고 물건도 인도했으니 이번 연도 매출로 100% 인식해도 되죠?",
    },
    {
        "id": "T5",
        "label": "진행률 계산 (원가기준 투입법)",
        "text": "A건설사는 B사와 총 5,000만 원 규모의 건물 건설 계약을 맺었습니다. 공사에 소요될 총 예상원가는 4,000만 원입니다. 당기 말까지 실제로 발생한 누적 원가는 총 2,100만 원이며, 이 발생원가 내역에는 다음 두 가지 특수 항목이 포함되어 있습니다. 현장에 인도되어 B사가 통제하고 있으나, 아직 건물에 설치되지는 않은 특수 엘리베이터 대금: 1,500만 원 (A건설사가 직접 제작하지 않고 외부에서 단순 구매함). 건설 현장 직원의 실수로 자재가 파손되어 폐기 처리된 비정상적인 낭비 원가: 100만 원. 원가기준 투입법을 적용하여 이번 당기에 A건설사가 인식해야 할 1) 적절한 공사진행률과 2) 당기 매출(수익) 금액을 계산해 주세요.",
    },
]


def _categorize_doc(d: dict) -> str:
    """문서를 카테고리로 분류"""
    cid = d.get("chunk_id", "")
    cat = d.get("category", "")
    src = d.get("source", "")
    if "IE-case-" in cid or cat == "적용사례IE":
        return "IE사례"
    if src == "QNA" or "QNA" in cid:
        return "QNA"
    if src == "감리사례" or "FSS" in cid or "KICPA" in cid:
        return "감리사례"
    if src == "교육자료" or "EDU" in cid:
        return "교육자료"
    if "B" in cid.replace("1115-", "").split("-")[0] if "-" in cid else "":
        return "적용지침"
    return "본문"


async def test_one(q: dict):
    state = {
        "messages": [("human", q["text"])],
        "standalone_query": q["text"],
        "routing": "IN",
        "is_situation": False,
        "search_keywords": [],
        "matched_topics": [],
        "retrieved_docs": [],
        "reranked_docs": [],
        "relevant_docs": [],
        "needs_calculation": False,
    }

    print(f"\n{'='*70}")
    print(f"  {q['id']}: {q['label']}")
    print(f"{'='*70}")

    # analyze
    analyze_result = await analyze_query(state)
    state.update(analyze_result)

    print(f"  routing={state['routing']} | is_situation={state['is_situation']} | needs_calc={state['needs_calculation']}")
    topics = state["matched_topics"]
    topic_names = [t.get("topic_name", "?") for t in topics]
    print(f"  matched_topics({len(topics)}): {topic_names}")

    if state["routing"] != "IN":
        print("  → OUT: 검색 스킵")
        return

    # pinpoint
    pinpoint_docs = await asyncio.to_thread(fetch_pinpoint_docs, topics)

    # retriever
    keywords = state.get("search_keywords", [])
    search_query = " ".join(keywords) if keywords else state["standalone_query"]
    original_text = _get_last_human_message(state.get("messages", [])) or state["standalone_query"]
    expanded = _expand_with_query_mapping(original_text)
    if expanded:
        search_query += " " + " ".join(expanded)
    if topics:
        ck = _extract_checklist_keywords(topics)
        if ck:
            search_query += " " + " ".join(ck)

    retriever_docs = await asyncio.to_thread(search_all, search_query, RETRIEVAL_LIMIT)
    merged = _merge_pinpoint_and_retriever(pinpoint_docs, retriever_docs)

    # 카테고리별 집계
    pp_cats: dict[str, list[str]] = {}
    for d in pinpoint_docs:
        cat = _categorize_doc(d)
        pp_cats.setdefault(cat, []).append(d.get("chunk_id", "?"))

    rt_cats: dict[str, list[str]] = {}
    for d in retriever_docs:
        cat = _categorize_doc(d)
        rt_cats.setdefault(cat, []).append(d.get("chunk_id", "?"))

    print(f"\n  PINPOINT ({len(pinpoint_docs)}건):")
    for cat, ids in sorted(pp_cats.items()):
        # IE사례는 case-N 형태로 표시
        display = ids[:5]
        suffix = f" +{len(ids)-5}건" if len(ids) > 5 else ""
        print(f"    {cat:8s}: {len(ids):2d}건  {display}{suffix}")

    print(f"\n  RETRIEVER ({len(retriever_docs)}건):")
    for cat, ids in sorted(rt_cats.items()):
        display = ids[:3]
        suffix = f" +{len(ids)-3}건" if len(ids) > 3 else ""
        print(f"    {cat:8s}: {len(ids):2d}건  {display}{suffix}")

    print(f"\n  MERGED: {len(merged)}건 (pinpoint={len(pinpoint_docs)} + retriever={len(retriever_docs)} - 중복)")

    # IE 필터 시뮬레이션
    use_calc = state.get("needs_calculation", False)
    if use_calc:
        filtered = [d for d in merged
                    if not (d.get("chunk_type") == "pinpoint" and d.get("category") == "적용사례IE")]
        ie_skip = len(merged) - len(filtered)
        print(f"  → [calc] IE pinpoint {ie_skip}건 제외 → LLM {len(filtered)}건")
    else:
        print(f"  → [일반] IE 필터 미적용 → LLM {len(merged)}건")


async def main():
    for q in QUESTIONS:
        await test_one(q)
    print(f"\n{'='*70}")
    print("  완료")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())

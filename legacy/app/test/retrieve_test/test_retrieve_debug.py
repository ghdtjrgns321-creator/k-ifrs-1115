"""pinpoint vs retriever 분리 디버그 스크립트.

사용법:
  PYTHONPATH=. uv run --env-file .env python app/test/test_retrieve_debug.py
"""
import asyncio
import json
import logging

logging.basicConfig(level=logging.DEBUG, format="%(name)s | %(levelname)s | %(message)s")

from app.nodes.analyze import analyze_query
from app.retriever import search_all, fetch_pinpoint_docs
from app.nodes.retrieve import (
    _expand_with_query_mapping,
    _extract_checklist_keywords,
    _merge_pinpoint_and_retriever,
    RETRIEVAL_LIMIT,
)
from app.nodes.generate import _get_last_human_message


QUESTION = (
    "A가 B에게 재화(완성된 의류)를 100원에 공급하고 세금계산서를 끊었습니다. "
    "이후 B는 최종 고객 C에게 120원에 판매합니다. "
    "이 경우 A가 인식해야 할 매출액은 100원인지 120원인지 궁금합니다."
)


def _print_docs(label: str, docs: list[dict]):
    """문서 목록을 보기 좋게 출력"""
    print(f"\n{'='*60}")
    print(f"  {label}  ({len(docs)}건)")
    print(f"{'='*60}")
    for i, d in enumerate(docs, 1):
        chunk_id = d.get("chunk_id", "?")
        category = d.get("category", "?")
        chunk_type = d.get("chunk_type", "?")
        source = d.get("source", "?")
        hierarchy = d.get("hierarchy", "")[:80]
        content_preview = d.get("content", "")[:120].replace("\n", " ")
        print(f"  [{i:2d}] {chunk_id}")
        print(f"       type={chunk_type} | category={category} | source={source}")
        print(f"       hierarchy: {hierarchy}")
        print(f"       content: {content_preview}...")
        print()


async def main():
    # ── 1단계: analyze ──
    state = {
        "messages": [("human", QUESTION)],
        "standalone_query": QUESTION,
        "routing": "IN",
        "is_situation": False,
        "search_keywords": [],
        "matched_topics": [],
        "retrieved_docs": [],
        "reranked_docs": [],
        "relevant_docs": [],
        "needs_calculation": False,
    }

    print("\n" + "="*60)
    print("  질문")
    print("="*60)
    print(f"  {QUESTION}\n")

    print(">>> analyze_query 실행 중...")
    analyze_result = await analyze_query(state)
    state.update(analyze_result)

    print(f"\n  routing:          {state['routing']}")
    print(f"  is_situation:     {state['is_situation']}")
    print(f"  needs_calculation:{state['needs_calculation']}")
    print(f"  search_keywords:  {state['search_keywords']}")
    print(f"  standalone_query: {state['standalone_query']}")
    print(f"  matched_topics:   {[t.get('topic_key','?') for t in state['matched_topics']]}")

    if state["routing"] != "IN":
        print("\n  !! routing=OUT → 검색 불필요")
        return

    # ── 2단계: pinpoint 검색 ──
    matched_topics = state.get("matched_topics", [])
    print("\n>>> fetch_pinpoint_docs 실행 중...")
    pinpoint_docs = await asyncio.to_thread(fetch_pinpoint_docs, matched_topics)
    _print_docs("PINPOINT 문서 (큐레이션 직접 조회)", pinpoint_docs)

    # IE pinpoint 확인
    ie_pinpoints = [d for d in pinpoint_docs
                    if d.get("chunk_type") == "pinpoint" and d.get("category") == "적용사례IE"]
    if ie_pinpoints:
        print(f"  ** IE 적용사례 pinpoint: {len(ie_pinpoints)}건 **")
        for d in ie_pinpoints:
            print(f"     - {d['chunk_id']}")

    # ── 3단계: retriever 검색 ──
    keywords = state.get("search_keywords", [])
    search_query = " ".join(keywords) if keywords else state["standalone_query"]

    original_text = _get_last_human_message(state.get("messages", [])) or state["standalone_query"]
    expanded_terms = _expand_with_query_mapping(original_text)
    if expanded_terms:
        search_query += " " + " ".join(expanded_terms)
        print(f"\n  QUERY_MAPPING 확장: {expanded_terms}")

    if matched_topics:
        checklist_kw = _extract_checklist_keywords(matched_topics)
        if checklist_kw:
            search_query += " " + " ".join(checklist_kw)
            print(f"  체크리스트 키워드: {checklist_kw}")

    print(f"\n  최종 검색 쿼리: {search_query}")

    print("\n>>> search_all (벡터+BM25) 실행 중...")
    retriever_docs = await asyncio.to_thread(search_all, search_query, RETRIEVAL_LIMIT)
    _print_docs("RETRIEVER 문서 (벡터+BM25 하이브리드)", retriever_docs)

    # ── 4단계: 병합 ──
    merged = _merge_pinpoint_and_retriever(pinpoint_docs, retriever_docs)
    print(f"\n  병합 결과: pinpoint={len(pinpoint_docs)}, retriever={len(retriever_docs)}, merged={len(merged)}")

    # ── 5단계: generate.py IE 필터 시뮬레이션 ──
    use_calc = state.get("needs_calculation", False)
    if use_calc:
        docs_for_llm = [d for d in merged
                        if not (d.get("chunk_type") == "pinpoint" and d.get("category") == "적용사례IE")]
        ie_skipped = len(merged) - len(docs_for_llm)
        print(f"\n  [calc 경로] IE pinpoint {ie_skipped}건 제외 → LLM에 {len(docs_for_llm)}건 전달")
    else:
        docs_for_llm = merged
        print(f"\n  [일반 경로] IE 필터 미적용 → LLM에 {len(docs_for_llm)}건 전달")

    # IE 문서가 LLM에 도달하는지 최종 확인
    ie_in_llm = [d for d in docs_for_llm
                 if d.get("category") == "적용사례IE"]
    print(f"  LLM 전달 문서 중 IE 적용사례: {len(ie_in_llm)}건")
    for d in ie_in_llm:
        print(f"    - {d['chunk_id']} (type={d.get('chunk_type')})")


if __name__ == "__main__":
    asyncio.run(main())

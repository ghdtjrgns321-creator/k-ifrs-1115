# app/test/test_ie_bypass.py
# IE 적용사례 pinpoint bypass + 상한 제거 테스트
#
# 실행: PYTHONPATH=. uv run --env-file .env python app/test/test_ie_bypass.py
import asyncio
import sys
from pathlib import Path

root = str(Path(__file__).parent.parent.parent)
if root not in sys.path:
    sys.path.insert(0, root)


async def test():
    from app.nodes.analyze import analyze_query
    from app.nodes.retrieve import retrieve_docs
    from app.nodes.rerank import rerank_docs
    from app.nodes.generate import generate_answer

    q = "우리 회사가 온라인 플랫폼에서 제3자 판매자의 상품을 중개하고 있는데, 수수료만 수익으로 인식해야 하나요 아니면 총액으로 인식해야 하나요?"
    state = {
        "messages": [("human", q)],
        "standalone_query": q,
    }

    import time

    # 1. analyze
    t0 = time.perf_counter()
    state.update(await analyze_query(state))
    t_analyze = time.perf_counter() - t0
    print(f"[analyze] {t_analyze:.1f}s | routing={state.get('routing')}, is_situation={state.get('is_situation')}")
    topics = state.get("matched_topics", [])
    print(f"  matched_topics: {[t['topic_name'] for t in topics]}")

    if state.get("routing") != "IN":
        print("OUT OF SCOPE")
        return

    # 2. retrieve
    t0 = time.perf_counter()
    state.update(await retrieve_docs(state))
    t_retrieve = time.perf_counter() - t0
    retrieved = state.get("retrieved_docs", [])
    pinpoint = [d for d in retrieved if d.get("chunk_type") == "pinpoint"]
    ie_pp = [d for d in pinpoint if d.get("category") == "적용사례IE"]
    print(f"[retrieve] {t_retrieve:.1f}s | total={len(retrieved)}, pinpoint={len(pinpoint)} (IE={len(ie_pp)})")

    # 3. rerank
    t0 = time.perf_counter()
    state.update(await rerank_docs(state))
    t_rerank = time.perf_counter() - t0
    reranked = state.get("reranked_docs", [])
    print(f"[rerank] {t_rerank:.1f}s | total={len(reranked)}")

    # 4. generate (풀 테스트)
    state["relevant_docs"] = reranked
    t0 = time.perf_counter()
    state.update(await generate_answer(state))
    t_generate = time.perf_counter() - t0

    # IE bypass 수치
    docs_for_llm = [d for d in reranked
                    if not (d.get("chunk_type") == "pinpoint"
                            and d.get("category") == "적용사례IE")]
    total_chars = sum(
        len((d.get("full_content") if d.get("source", "본문") != "본문" else d.get("content")) or "")
        for d in docs_for_llm
    )

    print(f"[generate] {t_generate:.1f}s | docs={len(docs_for_llm)}, IE제외={len(reranked)-len(docs_for_llm)}, context={total_chars:,}자")
    print(f"\n{'='*60}")
    print(f"[timing] analyze={t_analyze:.1f}s, retrieve={t_retrieve:.1f}s, rerank={t_rerank:.1f}s, generate={t_generate:.1f}s")
    print(f"[timing] TOTAL = {t_analyze + t_retrieve + t_rerank + t_generate:.1f}s")
    print(f"{'='*60}")

    # 답변 미리보기
    answer = state.get("answer", "")
    print(f"\n[답변 미리보기 (500자)]")
    print(answer[:500])
    print(f"\n[꼬리질문] {state.get('follow_up_questions', [])}")
    print(f"[cited_sources] {len(state.get('cited_sources', []))}건")


if __name__ == "__main__":
    asyncio.run(test())

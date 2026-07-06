"""26개 품질 테스트 케이스의 retrieve 검증 스크립트.

analyze → retrieve 단계까지만 실행하여 pinpoint/retriever 결과를 JSON + MD로 저장.
서버 불필요 (파이프라인 직접 호출).

PYTHONPATH=. uv run --env-file .env python app/test/retrieve_test/test_retrieve_26q.py
"""
import asyncio
import json
import logging
import sys
import io
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
logging.basicConfig(level=logging.WARNING)

from app.nodes.analyze import analyze_query
from app.retriever import fetch_pinpoint_docs, search_all
from app.nodes.retrieve import (
    _expand_with_query_mapping,
    _extract_checklist_keywords,
    _merge_pinpoint_and_retriever,
    RETRIEVAL_LIMIT,
)
from app.nodes.generate import _get_last_human_message

# 품질 테스트 케이스 임포트
sys.path.insert(0, str(Path(__file__).parent.parent))
from quality_test.run_quality_test import TEST_CASES

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def _expand_range(spec: str) -> list[str]:
    """'B34~B38' → ['B34','B35','B36','B37','B38'], 'IE239~IE243' → [...] 등."""
    import re
    m = re.match(r"^([A-Za-z]*)(\d+)[~～\-]([A-Za-z]*)(\d+)$", spec.strip())
    if not m:
        return [spec]
    prefix = m.group(1) or m.group(3)
    start, end = int(m.group(2)), int(m.group(4))
    if end - start > 50:
        return [spec]
    return [f"{prefix}{n}" for n in range(start, end + 1)]


def _match_expected(exp: str, all_ids: set[str]) -> bool:
    """expected_docs 항목이 실제 chunk_id 집합에 매칭되는지 확인.

    범위 표기('B34~B38')는 전개 후 하나라도 매칭되면 hit.
    괄호 suffix('9⑴')는 정규화 후 매칭.
    """
    import re
    # 범위 표기 → 전개
    expanded = _expand_range(exp)

    for item in expanded:
        # 괄호 suffix 정규화: "9⑴" → "9", "35⑵" → "35", "95⑴~⑶" → "95"
        clean = re.sub(r"[⑴⑵⑶⑷⑸()（）].*$", "", item).strip()
        candidates = [
            f"1115-{clean}",
            f"1115-IE{clean}" if clean.isdigit() else "",
            clean,
        ]
        for cand in candidates:
            if cand and cand in all_ids:
                return True
        # 부분 매칭: chunk_id에 item이 포함
        for cid in all_ids:
            if clean and clean in cid:
                return True
    return False


def _categorize(d: dict) -> str:
    cid = d.get("chunk_id", "")
    cat = d.get("category", "")
    src = d.get("source", "")
    if "IE-case-" in cid or (cat == "적용사례IE" and "pinpoint" not in cid):
        return "IE사례"
    if src == "QNA" or cid.startswith("QNA"):
        return "QNA"
    if src == "감리사례" or "FSS" in cid or "KICPA" in cid:
        return "감리사례"
    if src == "교육자료" or "EDU" in cid:
        return "교육자료"
    if cat == "적용사례IE":
        return "IE사례"
    return "본문/적용지침"


async def test_one(case: dict) -> dict:
    state = {
        "messages": [("human", case["message"])],
        "standalone_query": case["message"],
        "routing": "IN",
        "is_situation": False,
        "search_keywords": [],
        "matched_topics": [],
        "retrieved_docs": [],
        "reranked_docs": [],
        "relevant_docs": [],
        "needs_calculation": False,
    }

    # analyze
    analyze_result = await analyze_query(state)
    state.update(analyze_result)

    result = {
        "id": case["id"],
        "title": case["title"],
        "group": case["group"],
        "routing": state["routing"],
        "is_situation": state["is_situation"],
        "needs_calculation": state["needs_calculation"],
        "matched_topics": [t.get("topic_name", "?") for t in state["matched_topics"]],
        "expected_docs": case.get("expected_docs", []),
    }

    if state["routing"] != "IN":
        result.update({"pinpoint": [], "retriever": [], "merged": 0})
        return result

    topics = state.get("matched_topics", [])

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
    pp_summary = {}
    for d in pinpoint_docs:
        cat = _categorize(d)
        pp_summary.setdefault(cat, []).append(d.get("chunk_id", "?"))

    rt_summary = {}
    for d in retriever_docs:
        cat = _categorize(d)
        rt_summary.setdefault(cat, []).append(d.get("chunk_id", "?"))

    # IE 필터 시뮬레이션
    use_calc = state.get("needs_calculation", False)
    if use_calc:
        filtered = [d for d in merged
                    if not (d.get("chunk_type") == "pinpoint" and d.get("category") == "적용사례IE")]
        llm_docs = len(filtered)
        ie_excluded = len(merged) - llm_docs
    else:
        llm_docs = len(merged)
        ie_excluded = 0

    # expected_docs 매칭 확인
    all_chunk_ids = {d.get("chunk_id", "") for d in merged}
    # IE 병합 doc의 원본 chunk_ids도 포함
    for d in merged:
        for mid in d.get("_merged_chunk_ids", []):
            all_chunk_ids.add(mid)
    expected_hits = []
    expected_misses = []
    for exp in case.get("expected_docs", []):
        if _match_expected(exp, all_chunk_ids):
            expected_hits.append(exp)
        else:
            expected_misses.append(exp)

    result.update({
        "pinpoint_count": len(pinpoint_docs),
        "pinpoint_by_cat": {cat: len(ids) for cat, ids in pp_summary.items()},
        "pinpoint_ids": {cat: ids[:5] for cat, ids in pp_summary.items()},
        "retriever_count": len(retriever_docs),
        "retriever_by_cat": {cat: len(ids) for cat, ids in rt_summary.items()},
        "merged_count": len(merged),
        "llm_docs": llm_docs,
        "ie_excluded": ie_excluded,
        "expected_hits": expected_hits,
        "expected_misses": expected_misses,
        "hit_rate": f"{len(expected_hits)}/{len(case.get('expected_docs', []))}",
    })

    return result


async def main():
    results = []
    total = len(TEST_CASES)

    print(f"=== Retrieve 검증 ({total}개 케이스) ===\n")

    for i, case in enumerate(TEST_CASES, 1):
        print(f"  [{i:2d}/{total}] {case['id']:12s} {case['title'][:30]:30s} ... ", end="", flush=True)
        try:
            r = await test_one(case)
            status = f"pp={r['pinpoint_count']:2d} rt={r['retriever_count']:2d} merged={r['merged_count']:2d} hit={r['hit_rate']}"
            print(status)
        except Exception as e:
            r = {"id": case["id"], "title": case["title"], "error": str(e)}
            print(f"ERROR: {e}")
        results.append(r)

    # JSON 저장
    json_path = RESULTS_DIR / "retrieve_26q_results.json"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON: {json_path}")

    # MD 리포트 생성
    md_path = RESULTS_DIR / "retrieve_26q_report.md"
    _generate_report(results, md_path)
    print(f"Report: {md_path}")


def _generate_report(results: list[dict], path: Path):
    lines = [
        "# Retrieve 검증 리포트 (26개 케이스)",
        f"\n**실행일**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 요약",
        "",
        "| ID | 제목 | 토픽 매칭 | PP | RT | Merged | LLM | Hit Rate | 누락 |",
        "|---|---|---|---:|---:|---:|---:|---|---|",
    ]

    total_hits = 0
    total_expected = 0
    for r in results:
        if r.get("error"):
            lines.append(f"| {r['id']} | {r['title'][:25]} | ERROR | | | | | | |")
            continue
        topics = ", ".join(r.get("matched_topics", [])[:2])
        if len(r.get("matched_topics", [])) > 2:
            topics += f" +{len(r['matched_topics'])-2}"
        misses = ", ".join(r.get("expected_misses", []))[:30]
        hits = len(r.get("expected_hits", []))
        expected = hits + len(r.get("expected_misses", []))
        total_hits += hits
        total_expected += expected
        lines.append(
            f"| {r['id']} | {r['title'][:25]} | {topics[:30]} | "
            f"{r.get('pinpoint_count', 0)} | {r.get('retriever_count', 0)} | "
            f"{r.get('merged_count', 0)} | {r.get('llm_docs', 0)} | "
            f"{r.get('hit_rate', '')} | {misses} |"
        )

    if total_expected > 0:
        lines.append("")
        lines.append(f"**전체 Hit Rate: {total_hits}/{total_expected} ({total_hits/total_expected*100:.0f}%)**")

    # 카테고리별 상세
    lines.append("")
    lines.append("## 케이스별 상세")
    lines.append("")

    for r in results:
        if r.get("error"):
            continue
        lines.append(f"### {r['id']}: {r['title']}")
        lines.append("")
        lines.append(f"- **routing**: {r.get('routing')} | **is_situation**: {r.get('is_situation')} | **needs_calc**: {r.get('needs_calculation')}")
        lines.append(f"- **matched_topics**: {r.get('matched_topics', [])}")

        pp_cat = r.get("pinpoint_by_cat", {})
        if pp_cat:
            lines.append(f"- **Pinpoint ({r.get('pinpoint_count', 0)}건)**:")
            for cat, count in sorted(pp_cat.items()):
                ids = r.get("pinpoint_ids", {}).get(cat, [])
                display = ", ".join(ids[:3])
                suffix = f" +{len(ids)-3}" if len(ids) > 3 else ""
                lines.append(f"  - {cat}: {count}건 ({display}{suffix})")

        rt_cat = r.get("retriever_by_cat", {})
        if rt_cat:
            lines.append(f"- **Retriever ({r.get('retriever_count', 0)}건)**:")
            for cat, count in sorted(rt_cat.items()):
                lines.append(f"  - {cat}: {count}건")

        lines.append(f"- **Merged→LLM**: {r.get('merged_count', 0)}건 → {r.get('llm_docs', 0)}건")
        if r.get("ie_excluded"):
            lines.append(f"  - IE pinpoint {r['ie_excluded']}건 제외 (calc 경로)")

        expected = r.get("expected_hits", []) + r.get("expected_misses", [])
        if expected:
            hits = r.get("expected_hits", [])
            misses = r.get("expected_misses", [])
            lines.append(f"- **Expected docs hit**: {r.get('hit_rate', '')} — hits={hits}, misses={misses}")

        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())

# app/test/model_comparison/run_production.py
# 프로덕션 파이프라인 품질 테스트 — gemini-flash/gpt-4.1-mini 자동 라우팅 검증
#
# 실행:
#   PYTHONPATH=. uv run --env-file .env python app/test/model_comparison/run_production.py
#   PYTHONPATH=. uv run --env-file .env python app/test/model_comparison/run_production.py --questions T1 --repeat 1
import argparse
import asyncio
import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows UTF-8 강제
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from app.test.model_comparison.model_comparison_question import GOLDEN_QUESTIONS, GoldenQuestion
from app.test.model_comparison.quality_evaluator import (
    check_hallucination, check_format, check_scoring_criteria, check_retrieval_targets,
)

SEP = "═" * 70


# ── 프로덕션 파이프라인 1회 실행 ──────────────────────────────────────────────

async def _run_production_pipeline(question: GoldenQuestion) -> dict:
    """프로덕션 노드를 순서대로 호출하여 결과를 반환합니다.

    Why: generate_answer()를 직접 호출해야 gemini/gpt-mini 자동 라우팅,
    topic_knowledge 주입, paragraph pinpoint fetch가 모두 테스트됨.
    """
    from app.nodes.analyze import analyze_query
    from app.nodes.retrieve import retrieve_docs
    from app.nodes.rerank import rerank_docs
    from app.nodes.generate import generate_answer

    state: dict = {
        "messages": [("human", question.question)],
        "standalone_query": "",
        "routing": "",
        "is_situation": False,
        "search_keywords": [],
        "matched_topics": [],
        "confusion_point": "",
        "complexity": "complex",
        "retry_count": 0,
        "retrieved_docs": [],
        "reranked_docs": [],
        "relevant_docs": [],
        "pre_retrieved_docs": None,
        "answer": "",
        "cited_sources": [],
        "findings_case": None,
        "follow_up_questions": [],
        "is_conclusion": False,
        "force_conclusion": False,
    }

    timings: dict[str, float] = {}
    t_total = time.perf_counter()

    # 1) analyze
    t0 = time.perf_counter()
    state.update(await analyze_query(state))
    timings["analyze"] = time.perf_counter() - t0

    # 2) retrieve
    t0 = time.perf_counter()
    state.update(await retrieve_docs(state))
    timings["retrieve"] = time.perf_counter() - t0

    # 3) rerank
    t0 = time.perf_counter()
    state.update(await rerank_docs(state))
    timings["rerank"] = time.perf_counter() - t0
    state["relevant_docs"] = state.get("reranked_docs", [])

    # 4) generate — 프로덕션 모델 자동 라우팅
    t0 = time.perf_counter()
    state.update(await generate_answer(state))
    timings["generate"] = time.perf_counter() - t0

    timings["total"] = time.perf_counter() - t_total

    # 사용된 모델 판별 — _needs_calculation과 동일한 3조건 AND로 판단
    from app.nodes.generate import _needs_calculation
    question_text = question.question
    use_calc = _needs_calculation(state.get("matched_topics", []), question_text)
    model_used = "gpt-4.1-mini(calc)" if use_calc else "gemini-3-flash(thinking=high)"

    return {
        "state": state,
        "timings": timings,
        "model_used": model_used,
        "is_situation": state.get("is_situation", False),
        "matched_topics": [t.get("topic_name", "") for t in state.get("matched_topics", [])],
    }


# ── 평가 ──────────────────────────────────────────────────────────────────────

def _evaluate(question: GoldenQuestion, state: dict) -> dict:
    """4축 평가를 실행합니다."""
    answer = state.get("answer", "")
    cited_paragraphs = state.get("cited_paragraphs", [])
    selected_branches = state.get("selected_branches", [])
    follow_ups = state.get("follow_up_questions", [])

    return {
        "hallucination": check_hallucination(
            question, answer, cited_paragraphs, selected_branches, is_reasoning=True,
        ),
        "format": check_format(question, answer, follow_ups),
        "scoring": check_scoring_criteria(question, answer, follow_ups),
        "retrieval": check_retrieval_targets(question, state.get("relevant_docs", [])),
    }


# ── 출력 ──────────────────────────────────────────────────────────────────────

def _print_run_result(q: GoldenQuestion, run_idx: int, result: dict, evals: dict):
    state = result["state"]
    t = result["timings"]
    answer = state.get("answer", "")

    # 검색 커버리지
    docs = state.get("relevant_docs", [])
    src_counts = {"본문": 0, "QNA": 0, "IE": 0, "감리사례": 0}
    for doc in docs:
        src = doc.get("source", "본문")
        if src in src_counts:
            src_counts[src] += 1
        elif "IE" in src.upper():
            src_counts["IE"] += 1

    hall = "OK" if evals["hallucination"].passed else "FAIL"
    fmt = "OK" if evals["format"].passed else "FAIL"
    ret = "OK" if evals["retrieval"].passed else "MISS"
    scoring = evals["scoring"]

    print(f"  #{run_idx + 1} | model={result['model_used']:<30} | {t['total']:.1f}s "
          f"(a:{t['analyze']:.1f} r:{t['retrieve']:.1f} rr:{t['rerank']:.1f} g:{t['generate']:.1f})")
    print(f"      topics={result['matched_topics']} | sit={result['is_situation']}")
    print(f"      docs: 본문{src_counts['본문']} QNA{src_counts['QNA']} IE{src_counts['IE']} 감리{src_counts['감리사례']} "
          f"| 환각:{hall} 포맷:{fmt} 검색:{ret} 채점:{scoring.details} (score={scoring.score:.2f})")
    print(f"      answer: {answer[:120].replace(chr(10), ' ')}")


# ── 메인 ──────────────────────────────────────────────────────────────────────

async def main(question_ids: list[str] | None = None, repeat: int = 3):
    questions = GOLDEN_QUESTIONS
    if question_ids:
        questions = [q for q in questions if q.id in question_ids]

    total = len(questions) * repeat
    print(f"\n프로덕션 파이프라인 테스트: {len(questions)}개 질문 x {repeat}회 = {total}회")
    print(f"모델 라우팅: generate→gemini-3-flash(high) / calc→gpt-4.1-mini")
    print(SEP)

    # 전체 결과 수집
    all_results: dict[str, list[dict]] = {}
    summary_rows: list[dict] = []

    for q in questions:
        print(f"\n{SEP}")
        print(f"{q.id}: {q.topic} ({q.question_type}, {q.complexity})")
        print(f"  Q: {q.question[:80]}...")
        print(f"  정답 요약: {q.expected_answer_summary}")
        print(SEP)

        q_results: list[dict] = []
        q_scores: list[float] = []
        q_times: list[float] = []

        for r in range(repeat):
            # Rate limit 방지 — 첫 호출 제외, 호출 간 5초 대기
            if r > 0 or q != questions[0]:
                await asyncio.sleep(5)
            print(f"  [{q.id} #{r + 1}/{repeat}] 실행 중...", end="", flush=True)
            result = await _run_production_pipeline(q)
            evals = _evaluate(q, result["state"])
            print(f" 완료 ({result['timings']['total']:.1f}s)")

            _print_run_result(q, r, result, evals)
            q_results.append({"result": result, "evals": evals})
            q_scores.append(evals["scoring"].score)
            q_times.append(result["timings"]["total"])

        # 질문별 요약
        avg_score = sum(q_scores) / len(q_scores)
        avg_time = sum(q_times) / len(q_times)
        retrieval_eval = q_results[0]["evals"]["retrieval"]
        print(f"\n  [{q.id} 요약] 평균채점={avg_score:.2f} 평균시간={avg_time:.1f}s "
              f"검색타겟={retrieval_eval.details}")

        all_results[q.id] = q_results
        summary_rows.append({
            "id": q.id, "topic": q.topic,
            "avg_score": avg_score, "avg_time": avg_time,
            "scores": q_scores,
            "model_used": q_results[0]["result"]["model_used"],
            "retrieval": retrieval_eval.details,
        })

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("최종 요약 (프로덕션 파이프라인)")
    print(SEP)
    print(f"{'ID':<5} | {'토픽':<16} | {'모델':<32} | {'평균점수':>8} | {'점수들':<20} | {'평균시간':>7} | 검색타겟")
    print("-" * 115)
    for row in summary_rows:
        scores_str = ", ".join(f"{s:.2f}" for s in row["scores"])
        print(f"{row['id']:<5} | {row['topic']:<16} | {row['model_used']:<32} | "
              f"{row['avg_score']:>8.2f} | {scores_str:<20} | {row['avg_time']:>6.1f}s | {row['retrieval']}")

    total_avg = sum(r["avg_score"] for r in summary_rows) / len(summary_rows) if summary_rows else 0
    print(f"\n전체 평균 채점: {total_avg:.2f}")

    # ── JSON 저장 ────────────────────────────────────────────────────────────
    _save_results(all_results, summary_rows)


def _save_results(all_results: dict, summary_rows: list[dict]):
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = results_dir / f"production_{timestamp}.json"

    json_data = {
        "timestamp": timestamp,
        "test_type": "production_pipeline",
        "description": "리트리버 커버리지 개선 후 프로덕션 파이프라인 테스트 (topics.json desc 주입 + 기준서 문단 핀포인트)",
        "summary": summary_rows,
        "questions": {},
    }

    for qid, runs in all_results.items():
        json_data["questions"][qid] = []
        for run in runs:
            result = run["result"]
            evals = run["evals"]
            state = result["state"]
            json_data["questions"][qid].append({
                "model_used": result["model_used"],
                "is_situation": result["is_situation"],
                "matched_topics": result["matched_topics"],
                "timings": {k: round(v, 2) for k, v in result["timings"].items()},
                "answer_preview": state.get("answer", "")[:300],
                "answer_full": state.get("answer", ""),
                "hallucination": {"passed": evals["hallucination"].passed, "details": evals["hallucination"].details},
                "format": {"passed": evals["format"].passed, "details": evals["format"].details},
                "scoring": {"passed": evals["scoring"].passed, "score": round(evals["scoring"].score, 3), "details": evals["scoring"].details},
                "retrieval": {"passed": evals["retrieval"].passed, "score": round(evals["retrieval"].score, 3), "details": evals["retrieval"].details},
                "relevant_docs_count": len(state.get("relevant_docs", [])),
                "relevant_docs_sources": [d.get("source", "") for d in state.get("relevant_docs", [])],
            })

    filepath.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[SAVED] {filepath}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="프로덕션 파이프라인 품질 테스트")
    parser.add_argument("--questions", type=str, default=None, help="질문 ID (콤마 구분)")
    parser.add_argument("--repeat", type=int, default=3, help="반복 횟수 (기본 3)")
    args = parser.parse_args()

    q_ids = args.questions.split(",") if args.questions else None
    asyncio.run(main(question_ids=q_ids, repeat=args.repeat))

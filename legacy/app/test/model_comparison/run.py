# app/test/model_comparison/run.py
# 모델 비교 테스트 — 골든 질문 × 모델 × 반복 회차
#
# 실행:
#   PYTHONPATH=. uv run --env-file .env python app/test/model_comparison/run.py
#   PYTHONPATH=. uv run --env-file .env python app/test/model_comparison/run.py --questions T1 --repeat 4
#   PYTHONPATH=. uv run --env-file .env python app/test/model_comparison/run.py --models gpt-5-mini-low,solar-mini
import argparse
import asyncio
import copy
import io
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Windows cp949 인코딩 깨짐 방지 — stdout을 UTF-8로 강제
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from app.test.model_comparison.model_comparison_question import GOLDEN_QUESTIONS, GoldenQuestion
from app.test.model_comparison.quality_evaluator import (
    check_hallucination, check_format, check_scoring_criteria, check_retrieval_targets,
)


# ── 모델 설정 정의 ───────────────────────────────────────────────────────────

@dataclass
class ModelConfig:
    key: str                    # CLI 필터용 짧은 키
    display_name: str           # 출력용 이름
    model_type: str             # "openai" | "gemini" | "solar"
    model_id: str               # API 모델 ID
    is_reasoning: bool = True   # False: non-reasoning (gpt-4.1-mini, solar-mini)
    model_settings: dict = field(default_factory=dict)
    cost_input: float = 0.0     # $/1M input tokens
    cost_output: float = 0.0    # $/1M output tokens
    requires_env: str = ""      # 필수 환경변수 (없으면 스킵)


MODEL_CONFIGS: list[ModelConfig] = [
    ModelConfig(
        key="gpt-5-mini-low", display_name="gpt-5-mini (low)",
        model_type="openai", model_id="gpt-5-mini",
        is_reasoning=True,
        model_settings={"openai_reasoning_effort": "low", "max_tokens": 8192},
        cost_input=0.125, cost_output=1.00,
    ),
    ModelConfig(
        key="gpt-5-mini-medium", display_name="gpt-5-mini (medium)",
        model_type="openai", model_id="gpt-5-mini",
        is_reasoning=True,
        model_settings={"openai_reasoning_effort": "medium", "max_tokens": 8192},
        cost_input=0.125, cost_output=1.00,
    ),
    # o4-mini 제거: gpt-5-mini 대비 4배 비싸면서 품질 차이 미미 (T1 테스트 결과)
    ModelConfig(
        key="gpt-4.1-mini", display_name="gpt-4.1-mini",
        model_type="openai", model_id="gpt-4.1-mini",
        is_reasoning=False,
        model_settings={"temperature": 0.0},
        cost_input=0.20, cost_output=0.80,
    ),
    ModelConfig(
        key="gemini-3-flash-low", display_name="Gemini 3 Flash (low)",
        model_type="gemini", model_id="gemini-3-flash-preview",
        is_reasoning=True,
        model_settings={"google_thinking_config": {"thinking_level": "low"}},
        cost_input=0.50, cost_output=3.00,
        requires_env="GOOGLE_API_KEY",
    ),
    ModelConfig(
        key="gemini-3-flash-medium", display_name="Gemini 3 Flash (medium)",
        model_type="gemini", model_id="gemini-3-flash-preview",
        is_reasoning=True,
        model_settings={"google_thinking_config": {"thinking_level": "medium"}},
        cost_input=0.50, cost_output=3.00,
        requires_env="GOOGLE_API_KEY",
    ),
    ModelConfig(
        key="gemini-3-flash-high", display_name="Gemini 3 Flash (high)",
        model_type="gemini", model_id="gemini-3-flash-preview",
        is_reasoning=True,
        model_settings={"google_thinking_config": {"thinking_level": "high"}},
        cost_input=0.50, cost_output=3.00,
        requires_env="GOOGLE_API_KEY",
    ),
    # Solar Mini 제거: 한국어 회계 도메인 환각률 높음 (T1 테스트 결과)
]


# ── 모델 인스턴스 생성 ───────────────────────────────────────────────────────

def _build_model(cfg: ModelConfig):
    """ModelConfig → PydanticAI Model 인스턴스를 생성합니다."""
    if cfg.model_type == "openai":
        from pydantic_ai.models.openai import OpenAIChatModel as OpenAIModel
        from app.agents import _provider
        return OpenAIModel(cfg.model_id, provider=_provider)

    elif cfg.model_type == "gemini":
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider
        provider = GoogleProvider(api_key=os.environ["GOOGLE_API_KEY"])
        return GoogleModel(cfg.model_id, provider=provider)

    elif cfg.model_type == "solar":
        from pydantic_ai.models.openai import OpenAIChatModel as OpenAIModel
        from pydantic_ai.providers.openai import OpenAIProvider
        from app.config import settings
        provider = OpenAIProvider(
            base_url="https://api.upstage.ai/v1",
            api_key=settings.upstage_api_key,
        )
        return OpenAIModel(cfg.model_id, provider=provider)

    raise ValueError(f"Unknown model_type: {cfg.model_type}")


# ── 파이프라인 단계별 실행 ───────────────────────────────────────────────────

async def _run_analyze_retrieve_rerank(question: GoldenQuestion) -> tuple[dict, float]:
    """analyze → retrieve → rerank을 1회 실행하고 state + 소요시간을 반환합니다."""
    from app.nodes.analyze import analyze_query
    from app.nodes.retrieve import retrieve_docs
    from app.nodes.rerank import rerank_docs

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
    }

    t0 = time.perf_counter()
    state.update(await analyze_query(state))
    state.update(await retrieve_docs(state))
    state.update(await rerank_docs(state))
    state["relevant_docs"] = state.get("reranked_docs", [])
    elapsed = time.perf_counter() - t0

    return state, elapsed


# ── context/user_msg 구성 헬퍼 (reasoning / non-reasoning 공용) ──────────────

def _build_context_and_messages(state: dict, cfg: ModelConfig) -> tuple[str, str, bool]:
    """state에서 context_str, user_msg, is_situation을 구성합니다.

    Returns:
        (context_str, user_msg, is_situation)
    """
    from app.nodes.generate import (
        _format_precedents_context, _get_last_human_message,
        _get_related_practitioner_terms, GENERATE_DOC_LIMIT, MAX_DOC_CHARS,
    )
    from app.prompts import CLARIFY_USER, GENERATE_USER

    docs = state.get("relevant_docs", [])[:GENERATE_DOC_LIMIT]
    is_situation = state.get("is_situation", False)

    # context 구성
    context_parts = []
    for doc in docs:
        source_type = doc.get("source", "본문")
        raw = doc.get("full_content") if source_type != "본문" else doc.get("content")
        text = raw[:MAX_DOC_CHARS] if raw and len(raw) > MAX_DOC_CHARS else raw
        hierarchy = doc.get("hierarchy", "")
        context_parts.append(f"[{source_type}] {hierarchy}\n{text}")
    context_str = "\n\n---\n\n".join(context_parts)
    confusion_point = state.get("confusion_point", "") or "(없음)"

    if is_situation:
        messages = state.get("messages", [])
        precedents_text = _format_precedents_context(state.get("matched_topics", []))
        if precedents_text:
            context_str = f"[큐레이션 선례·공식]\n{precedents_text}\n\n---\n\n{context_str}"

        original_message = _get_last_human_message(messages)
        user_msg = CLARIFY_USER.format(
            context=context_str,
            confusion_point=confusion_point,
            conversation_history="(첫 질문)",
            original_message=original_message,
            question=state["standalone_query"],
        )

        # non-reasoning: 체크리스트를 user message에 직접 주입
        if not cfg.is_reasoning:
            checklist_text = _build_checklist_user_text(state)
            if checklist_text:
                user_msg = f"{user_msg}\n\n{checklist_text}"
    else:
        complexity = state.get("complexity", "complex")
        user_msg = GENERATE_USER.format(
            complexity=complexity,
            practitioner_terms=_get_related_practitioner_terms(docs),
            context=context_str,
            confusion_point=confusion_point,
            question=state["standalone_query"],
        )

    return context_str, user_msg, is_situation


def _build_checklist_user_text(state: dict) -> str:
    """non-reasoning 모델용: 체크리스트 가이드를 user message 텍스트로 구성."""
    matched_topics = state.get("matched_topics", [])
    if not matched_topics:
        return ""

    lines = [
        "[체크리스트 가이드] 아래 체크리스트 항목 범위 내에서만 분석하세요."
    ]
    for topic in matched_topics:
        if "checklist_text" in topic:
            lines.append(topic["checklist_text"])
    return "\n\n".join(lines)


# ── generate 실행 — reasoning / non-reasoning 분기 ───────────────────────────

async def _run_generate_with_model(
    base_state: dict, question: GoldenQuestion, cfg: ModelConfig,
) -> dict:
    """캐시된 state를 복사하여 특정 모델로 generate/clarify를 실행합니다."""
    state = copy.deepcopy(base_state)
    model = _build_model(cfg)
    _, user_msg, is_situation = _build_context_and_messages(state, cfg)

    result: dict = {
        "answer": "", "elapsed": 0.0,
        "input_tokens": 0, "output_tokens": 0,
        "follow_up_questions": [], "cited_paragraphs": [],
        "selected_branches": [], "error": None,
    }

    t0 = time.perf_counter()
    try:
        if cfg.is_reasoning:
            run_result = await _run_reasoning(state, user_msg, is_situation, model, cfg)
        else:
            run_result = await _run_nonreasoning(user_msg, is_situation, model, cfg)

        output = run_result.output
        result["answer"] = output.answer
        result["cited_paragraphs"] = output.cited_paragraphs
        result["follow_up_questions"] = output.follow_up_questions[:3]

        # selected_branches: reasoning ClarifyOutput에만 존재
        if hasattr(output, "selected_branches"):
            result["selected_branches"] = output.selected_branches

        usage = run_result.usage()
        result["input_tokens"] = usage.input_tokens or 0
        result["output_tokens"] = usage.output_tokens or 0

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["answer"] = f"[ERROR] {result['error']}"

    result["elapsed"] = time.perf_counter() - t0
    return result


async def _run_reasoning(state, user_msg, is_situation, model, cfg):
    """reasoning/thinking 모델 경로 — 프로덕션 agent 재사용."""
    from app.agents import clarify_agent, generate_agent, ClarifyDeps

    if is_situation:
        deps = ClarifyDeps(
            matched_topics=state.get("matched_topics", []),
            checklist_state=state.get("checklist_state"),
        )
        return await clarify_agent.run(
            user_msg, deps=deps,
            model=model, model_settings=cfg.model_settings,
        )
    else:
        return await generate_agent.run(
            user_msg,
            model=model, model_settings=cfg.model_settings,
        )


async def _run_nonreasoning(user_msg, is_situation, model, cfg):
    """non-reasoning 모델 경로 — 테스트 전용 agent (validator 없음)."""
    from app.test.model_comparison.agents_nonreasoning import (
        build_clarify_agent_nr, build_generate_agent_nr,
    )

    if is_situation:
        agent = build_clarify_agent_nr(model, cfg.key)
        return await agent.run(user_msg, model_settings=cfg.model_settings)
    else:
        agent = build_generate_agent_nr(model, cfg.key)
        return await agent.run(user_msg, model_settings=cfg.model_settings)


# ── 비용 계산 ────────────────────────────────────────────────────────────────

def _calc_cost(cfg: ModelConfig, input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * cfg.cost_input + output_tokens * cfg.cost_output) / 1_000_000


# ── 검색 커버리지 분석 ───────────────────────────────────────────────────────

def _analyze_coverage(state: dict) -> dict:
    """검색된 문서의 source 분류 + precedents/formula 존재 여부."""
    docs = state.get("relevant_docs", [])
    coverage = {"본문": 0, "QNA": 0, "IE": 0, "감리사례": 0}
    for doc in docs:
        src = doc.get("source", "본문")
        if src in coverage:
            coverage[src] += 1
        elif "적용" in src or "IE" in src.upper():
            coverage["IE"] += 1

    matched = state.get("matched_topics", [])
    has_precedents = any(t.get("precedents") for t in matched)
    has_formula = any(t.get("calculation_formula") for t in matched)

    return {**coverage, "precedents": has_precedents, "formula": has_formula}


# ── 출력 포맷 ────────────────────────────────────────────────────────────────

SEP = "═" * 70


def _print_question_header(q: GoldenQuestion, analyze_time: float, coverage: dict, retrieval_eval=None):
    print(f"\n{SEP}")
    print(f"{q.id}: {q.topic} — ({q.question_type}, {q.complexity})")
    parts = [f"analyze+retrieve+rerank: {analyze_time:.1f}s"]
    parts.append(f"검색: 본문 {coverage['본문']}, QNA {coverage['QNA']}, IE {coverage['IE']}, 감리 {coverage['감리사례']}")
    prec = "O" if coverage["precedents"] else "-"
    form = "O" if coverage["formula"] else "-"
    parts.append(f"precedents: {prec} | formula: {form}")
    print(f"  {' | '.join(parts)}")
    if retrieval_eval:
        status = "OK" if retrieval_eval.passed else "MISS"
        print(f"  검색타겟: [{status}] {retrieval_eval.details}")
    print(SEP)
    print(f"{'모델':<28} | {'회차':>4} | {'시간':>6} | {'in_tok':>7} | {'out_tok':>7} | {'비용($)':>8} | {'환각':>4} | {'포맷':>4} | 채점")
    print("-" * 90)


def _print_model_row(cfg: ModelConfig, res: dict, evals: dict, repeat_idx: int = 0):
    elapsed = f"{res['elapsed']:.1f}s"
    in_tok = f"{res['input_tokens']:,}"
    out_tok = f"{res['output_tokens']:,}"
    cost = f"${_calc_cost(cfg, res['input_tokens'], res['output_tokens']):.4f}"

    hall = "OK" if evals["hallucination"].passed else "FAIL"
    fmt = "OK" if evals["format"].passed else "FAIL"
    scoring_detail = evals["scoring"].details
    repeat_label = f"#{repeat_idx + 1}"
    print(f"{cfg.display_name:<28} | {repeat_label:>4} | {elapsed:>6} | {in_tok:>7} | {out_tok:>7} | {cost:>8} | {hall:>4} | {fmt:>4} | {scoring_detail}")


def _print_answer_preview(results: list[tuple[ModelConfig, dict, int]]):
    print("\n[답변 미리보기 (처음 80자)]")
    for cfg, res, idx in results:
        preview = res["answer"][:80].replace("\n", " ")
        label = f"{cfg.display_name} #{idx + 1}"
        print(f"  {label:<34}: {preview}")


def _print_coverage_table(coverage_data: list[tuple[str, dict]]):
    print(f"\n{SEP}")
    print("[검색 커버리지]")
    print(SEP)
    print(f"{'질문':<5} | {'본문':>4} | {'QNA':>4} | {'IE':>6} | {'감리':>6} | {'precedents':>10} | {'formula':>7}")
    print("-" * 60)
    for qid, cov in coverage_data:
        prec = "O" if cov["precedents"] else "-"
        form = "O" if cov["formula"] else "-"
        print(f"{qid:<5} | {cov['본문']:>4} | {cov['QNA']:>4} | {cov['IE']:>6} | {cov['감리사례']:>6} | {prec:>10} | {form:>7}")


def _print_retrieval_targets(retrieval_evals: dict):
    """검색 타겟 커버리지 결과를 출력합니다."""
    if not retrieval_evals:
        return
    print(f"\n{SEP}")
    print("[검색 타겟 커버리지] — 리트리버가 필수 문서를 찾았는지 확인")
    print(SEP)
    for qid, ev in retrieval_evals.items():
        status = "OK" if ev.passed else "MISS"
        print(f"  {qid}: [{status}] {ev.details}")


def _print_final_summary(summary: dict[str, dict]):
    print(f"\n{SEP}")
    print("최종 요약")
    print(SEP)
    print(f"{'모델':<28} | {'평균시간':>7} | {'총비용':>8} | {'환각pass':>8} | {'포맷pass':>8} | {'평균채점':>8}")
    print("-" * 80)
    for key, data in summary.items():
        n = data["count"]
        if n == 0:
            continue
        avg_time = f"{data['total_time'] / n:.1f}s"
        total_cost = f"${data['total_cost']:.4f}"
        hall_pass = f"{data['hall_pass']}/{n}"
        fmt_pass = f"{data['fmt_pass']}/{n}"
        avg_score = f"{data['total_score'] / n:.2f}"
        print(f"{data['display_name']:<28} | {avg_time:>7} | {total_cost:>8} | {hall_pass:>8} | {fmt_pass:>8} | {avg_score:>8}")


# ── 메인 실행 ────────────────────────────────────────────────────────────────

async def main(
    question_ids: list[str] | None = None,
    model_keys: list[str] | None = None,
    repeat: int = 1,
):
    # 사용 가능한 모델 필터링
    active_models = []
    for cfg in MODEL_CONFIGS:
        if model_keys and cfg.key not in model_keys:
            continue
        if cfg.requires_env and not os.getenv(cfg.requires_env):
            print(f"  [SKIP] {cfg.display_name} — {cfg.requires_env} 미설정")
            continue
        active_models.append(cfg)

    if not active_models:
        print("[ERROR] 사용 가능한 모델이 없습니다.")
        return

    # 골든 질문 필터링
    questions = GOLDEN_QUESTIONS
    if question_ids:
        questions = [q for q in questions if q.id in question_ids]

    total_calls = len(questions) * len(active_models) * repeat
    print(f"\n모델 비교 테스트 시작: {len(questions)}개 질문 x {len(active_models)}개 모델 x {repeat}회 반복 = {total_calls}회")
    print(f"   모델: {', '.join(m.display_name for m in active_models)}")
    nr_models = [m.display_name for m in active_models if not m.is_reasoning]
    if nr_models:
        print(f"   non-reasoning (전용 프롬프트 적용): {', '.join(nr_models)}")

    # 결과 수집
    all_results: dict[str, list[tuple[ModelConfig, dict, dict, int]]] = {}
    coverage_data: list[tuple[str, dict]] = []
    retrieval_evals: dict[str, object] = {}  # qid → EvalResult
    summary: dict[str, dict] = {}
    for cfg in active_models:
        summary[cfg.key] = {
            "display_name": cfg.display_name,
            "count": 0, "total_time": 0.0, "total_cost": 0.0,
            "hall_pass": 0, "fmt_pass": 0, "total_score": 0.0,
        }

    for q in questions:
        # (a) analyze + retrieve + rerank 1회 (캐시)
        print(f"\n[{q.id}] analyze + retrieve + rerank 실행 중...")
        base_state, analyze_time = await _run_analyze_retrieve_rerank(q)
        coverage = _analyze_coverage(base_state)
        coverage_data.append((q.id, coverage))

        # (a-2) 검색 타겟 커버리지 체크 (질문당 1회, 모든 모델 공유)
        retrieval_eval = check_retrieval_targets(
            q, base_state.get("relevant_docs", []),
        )
        retrieval_evals[q.id] = retrieval_eval

        _print_question_header(q, analyze_time, coverage, retrieval_eval)

        question_results: list[tuple[ModelConfig, dict, int]] = []

        # (b) 각 모델 × 반복 회차
        for cfg in active_models:
            for r in range(repeat):
                label = f"{cfg.display_name} #{r + 1}/{repeat}"
                print(f"  [{label}]...", end="", flush=True)

                res = await _run_generate_with_model(base_state, q, cfg)

                # 에러 발생 시 전체 중단
                if res.get("error"):
                    print(f" FAILED")
                    print(f"\n{'=' * 70}")
                    print(f"[FATAL] {label} 생성 에러 — 전체 테스트 중단")
                    print(f"{'=' * 70}")
                    print(f"질문: {q.id} ({q.topic})")
                    print(f"모델: {cfg.display_name} (is_reasoning={cfg.is_reasoning})")
                    print(f"에러: {res['error']}")
                    if all_results:
                        _save_results_json(all_results, coverage_data, summary, retrieval_evals)
                    return

                print(f" {res['elapsed']:.1f}s", flush=True)

                # 4축 평가
                evals = {
                    "hallucination": check_hallucination(
                        q, res["answer"], res["cited_paragraphs"],
                        res["selected_branches"], is_reasoning=cfg.is_reasoning,
                    ),
                    "format": check_format(q, res["answer"], res["follow_up_questions"]),
                    "scoring": check_scoring_criteria(q, res["answer"], res["follow_up_questions"]),
                }

                _print_model_row(cfg, res, evals, repeat_idx=r)

                # 요약 누적
                s = summary[cfg.key]
                s["count"] += 1
                s["total_time"] += res["elapsed"]
                s["total_cost"] += _calc_cost(cfg, res["input_tokens"], res["output_tokens"])
                s["hall_pass"] += 1 if evals["hallucination"].passed else 0
                s["fmt_pass"] += 1 if evals["format"].passed else 0
                s["total_score"] += evals["scoring"].score

                question_results.append((cfg, res, r))
                all_results.setdefault(q.id, []).append((cfg, res, evals, r))

        _print_answer_preview(question_results)

    # 검색 커버리지 테이블
    _print_coverage_table(coverage_data)

    # 검색 타겟 커버리지
    _print_retrieval_targets(retrieval_evals)

    # 최종 요약
    _print_final_summary(summary)

    # JSON 저장
    _save_results_json(all_results, coverage_data, summary, retrieval_evals)


def _save_results_json(all_results, coverage_data, summary, retrieval_evals=None):
    """결과를 JSON 파일로 저장합니다."""
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = results_dir / f"model_comparison_{timestamp}.json"

    json_data = {
        "timestamp": timestamp,
        "questions": {},
        "coverage": {qid: cov for qid, cov in coverage_data},
        "retrieval_targets": {
            qid: {"passed": ev.passed, "score": ev.score, "details": ev.details}
            for qid, ev in (retrieval_evals or {}).items()
        },
        "summary": summary,
    }

    for qid, entries in all_results.items():
        json_data["questions"][qid] = []
        for cfg, res, evals, repeat_idx in entries:
            json_data["questions"][qid].append({
                "model": cfg.display_name,
                "model_key": cfg.key,
                "is_reasoning": cfg.is_reasoning,
                "repeat": repeat_idx + 1,
                "elapsed": round(res["elapsed"], 2),
                "input_tokens": res["input_tokens"],
                "output_tokens": res["output_tokens"],
                "cost": round(_calc_cost(cfg, res["input_tokens"], res["output_tokens"]), 6),
                "answer_preview": res["answer"][:200],
                "error": res["error"],
                "hallucination": {"passed": evals["hallucination"].passed, "details": evals["hallucination"].details},
                "format": {"passed": evals["format"].passed, "details": evals["format"].details},
                "scoring": {"passed": evals["scoring"].passed, "score": round(evals["scoring"].score, 3), "details": evals["scoring"].details},
            })

    filepath.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[SAVED] {filepath}")


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="K-IFRS 1115 모델 비교 테스트")
    parser.add_argument("--questions", type=str, default=None, help="질문 ID (콤마 구분, 예: T1,T5)")
    parser.add_argument("--models", type=str, default=None, help="모델 키 (콤마 구분, 예: gpt-5-mini-low,solar-mini)")
    parser.add_argument("--repeat", type=int, default=1, help="모델별 반복 횟수 (기본값 1)")
    args = parser.parse_args()

    q_ids = args.questions.split(",") if args.questions else None
    m_keys = args.models.split(",") if args.models else None

    asyncio.run(main(question_ids=q_ids, model_keys=m_keys, repeat=args.repeat))

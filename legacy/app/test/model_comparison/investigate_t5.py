# app/test/model_comparison/investigate_t5.py
# Step 1: T5 컨텍스트 크기 비교 — 2차(run.py) vs 3차(generate.py) 경로
#
# Why: 3차에서 T5 점수가 0.845 → 0.67로 급락.
#      가설: topic_knowledge(~2000자)가 산술 집중도를 분산시킴.
#      이 스크립트로 실제 토큰 수 차이를 정량 측정.
#
# 실행:
#   PYTHONPATH=. uv run --env-file .env python app/test/model_comparison/investigate_t5.py
import asyncio
import io
import sys

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from app.test.model_comparison.model_comparison_question import GOLDEN_QUESTIONS
from app.nodes.generate import (
    _format_precedents_context, _format_topic_knowledge,
    _get_last_human_message, _get_related_practitioner_terms,
    GENERATE_DOC_LIMIT, MAX_DOC_CHARS, _COT_PREFIX, _needs_calculation,
)
from app.prompts import CLARIFY_USER


SEP = "═" * 70


def _count_tokens_approx(text: str) -> int:
    """한국어 근사 토큰 수 — 한글 2.5자 ≈ 1토큰, 영문/숫자는 4자 ≈ 1토큰."""
    # 실제 tiktoken 대신 근사치 사용 (의존성 추가 불필요)
    korean_chars = sum(1 for c in text if '\uac00' <= c <= '\ud7a3')
    other_chars = len(text) - korean_chars
    return int(korean_chars / 2.5 + other_chars / 4)


async def investigate():
    """T5에 대해 2차/3차 경로의 user_msg를 생성하고 토큰 수를 비교합니다."""
    from app.nodes.analyze import analyze_query
    from app.nodes.retrieve import retrieve_docs
    from app.nodes.rerank import rerank_docs

    # T5 질문 찾기
    t5 = next(q for q in GOLDEN_QUESTIONS if q.id == "T5")
    print(f"{SEP}")
    print(f"T5 컨텍스트 크기 조사")
    print(f"질문: {t5.question[:80]}...")
    print(f"{SEP}\n")

    # 파이프라인 실행 (analyze → retrieve → rerank)
    state: dict = {
        "messages": [("human", t5.question)],
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

    print("[1/3] analyze...")
    state.update(await analyze_query(state))
    print(f"  is_situation={state['is_situation']}, matched_topics={[t.get('topic_name','') for t in state.get('matched_topics',[])]}")

    print("[2/3] retrieve...")
    state.update(await retrieve_docs(state))

    print("[3/3] rerank...")
    state.update(await rerank_docs(state))
    state["relevant_docs"] = state.get("reranked_docs", [])

    # calc 라우팅 확인
    original_message = _get_last_human_message(state["messages"])
    use_calc = _needs_calculation(state.get("matched_topics", []), original_message)
    print(f"\n  _needs_calculation={use_calc}")
    print(f"  has_formula={any(t.get('calculation_formula') for t in state.get('matched_topics', []))}")

    # ── 공통 context 구성 ────────────────────────────────────────────────────
    docs = state.get("relevant_docs", [])[:GENERATE_DOC_LIMIT]
    context_parts = []
    for doc in docs:
        source_type = doc.get("source", "본문")
        raw = doc.get("full_content") if source_type != "본문" else doc.get("content")
        text = raw[:MAX_DOC_CHARS] if raw and len(raw) > MAX_DOC_CHARS else raw
        hierarchy = doc.get("hierarchy", "")
        context_parts.append(f"[{source_type}] {hierarchy}\n{text}")
    base_context = "\n\n---\n\n".join(context_parts)
    confusion_point = state.get("confusion_point", "") or "(없음)"

    # ── 2차 경로 (run.py) — topic_knowledge 미포함 ───────────────────────────
    context_2nd = base_context
    precedents_text = _format_precedents_context(state.get("matched_topics", []))
    if precedents_text:
        context_2nd = f"[큐레이션 선례·공식]\n{precedents_text}\n\n---\n\n{context_2nd}"

    user_msg_2nd = CLARIFY_USER.format(
        context=context_2nd,
        confusion_point=confusion_point,
        conversation_history="(첫 질문)",
        original_message=original_message,
        question=state["standalone_query"],
    )

    # ── 3차 경로 (generate.py) — topic_knowledge 포함 + _COT_PREFIX ──────────
    context_3rd = base_context
    topic_knowledge = _format_topic_knowledge(state.get("matched_topics", []))
    if topic_knowledge:
        context_3rd = f"[참고 지식]\n{topic_knowledge}\n\n---\n\n{context_3rd}"
    if precedents_text:
        context_3rd = f"[큐레이션 선례·공식]\n{precedents_text}\n\n---\n\n{context_3rd}"

    user_msg_3rd = _COT_PREFIX + CLARIFY_USER.format(
        context=context_3rd,
        confusion_point=confusion_point,
        conversation_history="(첫 질문)",
        original_message=original_message,
        question=state["standalone_query"],
    )

    # ── 비교 출력 ────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("컨텍스트 크기 비교")
    print(SEP)

    len_2nd = len(user_msg_2nd)
    len_3rd = len(user_msg_3rd)
    tok_2nd = _count_tokens_approx(user_msg_2nd)
    tok_3rd = _count_tokens_approx(user_msg_3rd)

    print(f"{'항목':<30} | {'2차 (run.py)':<20} | {'3차 (generate.py)':<20} | {'차이':<15}")
    print("-" * 90)
    print(f"{'user_msg 글자 수':<30} | {len_2nd:<20,} | {len_3rd:<20,} | +{len_3rd - len_2nd:,}")
    print(f"{'user_msg 토큰 수 (근사)':<30} | {tok_2nd:<20,} | {tok_3rd:<20,} | +{tok_3rd - tok_2nd:,}")
    print(f"{'_COT_PREFIX 글자 수':<30} | {'0':<20} | {len(_COT_PREFIX):<20} | +{len(_COT_PREFIX)}")

    # topic_knowledge 단독 크기
    tk_len = len(topic_knowledge) if topic_knowledge else 0
    tk_tok = _count_tokens_approx(topic_knowledge) if topic_knowledge else 0
    print(f"{'topic_knowledge 글자 수':<30} | {'0':<20} | {tk_len:<20,} | +{tk_len:,}")
    print(f"{'topic_knowledge 토큰 수 (근사)':<30} | {'0':<20} | {tk_tok:<20,} | +{tk_tok:,}")

    # precedents 크기 (양쪽 동일)
    prec_len = len(precedents_text) if precedents_text else 0
    print(f"{'precedents 글자 수 (공통)':<30} | {prec_len:<20,} | {prec_len:<20,} | 0")

    # topic_knowledge 내용 미리보기
    if topic_knowledge:
        print(f"\n[참고 지식 내용 미리보기 (처음 500자)]")
        print(topic_knowledge[:500])
        print("..." if len(topic_knowledge) > 500 else "")

    # _COT_PREFIX 내용
    print(f"\n[_COT_PREFIX 내용]")
    print(_COT_PREFIX)

    # 3차에만 있는 추가 컨텍스트가 포함된 user_msg 비교 (diff 위치)
    print(f"\n{SEP}")
    print("결론")
    print(SEP)
    pct = ((len_3rd - len_2nd) / len_2nd * 100) if len_2nd > 0 else 0
    print(f"3차가 2차 대비 {len_3rd - len_2nd:,}자 ({pct:.1f}%) 더 많은 컨텍스트를 포함.")
    print(f"추가분 구성: topic_knowledge {tk_len:,}자 + _COT_PREFIX {len(_COT_PREFIX)}자")
    if pct > 20:
        print(f"→ 가설 지지: 추가 컨텍스트가 gpt-4.1-mini의 산술 집중도를 분산시킬 가능성 높음.")
    else:
        print(f"→ 추가 컨텍스트가 작아서 산술 분산 원인이 아닐 수 있음. 다른 원인 조사 필요.")


if __name__ == "__main__":
    asyncio.run(investigate())

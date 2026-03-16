"""실사용 데이터 품질 채점 리포트 + LLM 심화 채점 스크립트.

규칙 기반 4개 메트릭은 usage_logger.py에서 **매 응답마다 자동 채점**되어 DB에 저장된다.
이 스크립트는 두 가지 역할:
  1. DB에 저장된 자동 채점 결과로 리포트 생성 (--report-only 또는 기본)
  2. LLM 기반 3개 메트릭 추가 채점 (--with-llm)

사용법:
  # 리포트만 생성 (API 호출 없음, DB에 저장된 자동 채점 결과 사용)
  PYTHONPATH=. uv run --env-file .env python usage-data-collecting/score_usage_logs.py

  # LLM 심화 채점 추가 (OpenAI gpt-4.1-mini API 호출 발생)
  PYTHONPATH=. uv run --env-file .env python usage-data-collecting/score_usage_logs.py --with-llm

  # LLM 전체 재채점
  PYTHONPATH=. uv run --env-file .env python usage-data-collecting/score_usage_logs.py --with-llm --rescore

  # 최근 N건만
  PYTHONPATH=. uv run --env-file .env python usage-data-collecting/score_usage_logs.py --limit 20

출력: usage-data-collecting/score_report.md
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.config import settings

logger = logging.getLogger(__name__)

REPORT_PATH = Path(__file__).parent / "score_report.md"

# ── 규칙 기반 메트릭 임계값 ─────────────────────────────────────────────

# 응답 시간 등급 (밀리초)
_TIME_EXCELLENT = 15_000   # 15초 이하: 1.0
_TIME_GOOD = 25_000        # 25초 이하: 0.7
_TIME_ACCEPTABLE = 40_000  # 40초 이하: 0.4
# 40초 초과: 0.1

# 인용 문단 수 기준
_CITE_EXCELLENT = 4  # 4건 이상: 1.0
_CITE_GOOD = 2       # 2건 이상: 0.7
_CITE_MIN = 1        # 1건: 0.4
# 0건: 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 규칙 기반 메트릭 (DB 데이터만으로 산출, API 호출 없음)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def score_response_time(ms: int) -> float:
    """응답 시간 점수 (0.0~1.0). 빠를수록 높다."""
    if ms <= _TIME_EXCELLENT:
        return 1.0
    if ms <= _TIME_GOOD:
        return 0.7
    if ms <= _TIME_ACCEPTABLE:
        return 0.4
    return 0.1


def score_citation_coverage(cited: list[str], answer: str) -> float:
    """인용 커버리지 점수.

    평가 기준:
    - 인용 문단 수 (많을수록 근거가 풍부)
    - 답변 내 "문단" 키워드 출현 (인용을 실제로 활용했는가)
    """
    n = len(cited)
    if n >= _CITE_EXCELLENT:
        base = 1.0
    elif n >= _CITE_GOOD:
        base = 0.7
    elif n >= _CITE_MIN:
        base = 0.4
    else:
        return 0.0

    # 답변에서 실제로 문단을 언급했는지 보너스 체크
    mention_count = answer.count("문단")
    if mention_count >= 3:
        base = min(base + 0.1, 1.0)
    return base


def score_topic_match(
    matched_topics: list[str],
    is_situation: bool,
    search_keywords: list[str],
) -> float:
    """토픽 매칭 적절성 점수.

    평가 기준:
    - 거래상황 질문인데 토픽 매칭이 없으면 → 낮은 점수
    - 개념 질문은 토픽 매칭 안 해도 정상 → 기본 0.7
    - search_keywords가 풍부하면 분석이 잘 된 것 → 가산
    """
    if not is_situation:
        # 개념 질문: 토픽 매칭 불필요, 키워드 분석 품질로 평가
        if len(search_keywords) >= 3:
            return 0.9
        return 0.7

    # 거래상황: 토픽이 매칭되어야 정상
    if not matched_topics:
        return 0.2
    if len(matched_topics) >= 2:
        return 1.0
    return 0.7


def score_conclusion_safety(
    is_situation: bool,
    is_conclusion: bool,
    selected_branches: list[str],
    answer: str,
) -> float:
    """성급한 결론 방지 점수.

    평가 기준:
    - 거래상황 + 즉시 결론 + 분기 선택 없음 → 성급한 결론 의심
    - 답변에 "추가 정보", "확인이 필요" 등 유보 표현이 있으면 신중한 답변
    - 개념 질문은 즉답이 정상
    """
    if not is_situation:
        return 1.0  # 개념 질문은 즉답이 정상

    # 거래상황인데 결론을 냈고, 분기 선택이 있으면 정상 판단
    if is_conclusion and selected_branches:
        return 1.0

    # 거래상황인데 결론을 냈지만 분기가 없으면 성급할 수 있음
    if is_conclusion and not selected_branches:
        # 유보 표현이 있으면 완화
        caution_keywords = ["추가 정보", "확인이 필요", "판단이 필요", "고려해야"]
        has_caution = any(kw in answer for kw in caution_keywords)
        return 0.7 if has_caution else 0.4

    # 결론을 내지 않았으면 (꼬리질문 중) → 신중한 진행
    return 0.9


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LLM 기반 메트릭 (API 호출 필요, --with-llm 플래그)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _llm_score(system_prompt: str, user_prompt: str) -> float:
    """LLM에게 0.0~1.0 점수를 요청합니다.

    gpt-4.1-mini를 사용하여 비용을 최소화합니다.
    """
    from openai import OpenAI

    client = OpenAI()
    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        max_tokens=10,
    )
    text = resp.choices[0].message.content.strip()
    # "0.85" 또는 "0.85점" 등에서 숫자만 추출
    import re
    m = re.search(r"([01]\.?\d*)", text)
    if m:
        return min(max(float(m.group(1)), 0.0), 1.0)
    return 0.5  # 파싱 실패 시 중간값


_FAITHFULNESS_SYSTEM = """당신은 K-IFRS 1115 회계 전문가입니다.
아래 AI 답변이 인용한 기준서 문단에 근거하여 작성되었는지 평가하세요.

평가 기준:
- 1.0: 답변의 모든 주장이 인용 문단에 근거함
- 0.7: 대부분 근거가 있으나 일부 주장에 근거가 불명확
- 0.4: 근거가 부족하거나 인용과 답변이 괴리
- 0.1: 환각(hallucination)이 의심됨

숫자 하나만 답하세요 (예: 0.85)"""

_RELEVANCY_SYSTEM = """당신은 K-IFRS 1115 회계 전문가입니다.
아래 AI 답변이 사용자의 질문에 적절히 답변했는지 평가하세요.

평가 기준:
- 1.0: 질문의 핵심을 정확히 파악하고 실무적으로 유용한 답변
- 0.7: 질문에 답하긴 했으나 핵심 포인트를 일부 놓침
- 0.4: 질문과 관련은 있지만 직접적인 답이 아님
- 0.1: 질문과 무관하거나 엉뚱한 답변

숫자 하나만 답하세요 (예: 0.85)"""

_COMPLETENESS_SYSTEM = """당신은 K-IFRS 1115 회계 전문가입니다.
아래 AI 답변이 고려해야 할 사항을 빠뜨리지 않았는지 평가하세요.

평가 기준:
- 1.0: 관련 쟁점을 빠짐없이 다룸 (분기별 처리, 주의사항 포함)
- 0.7: 주요 쟁점은 다뤘지만 부수적 고려사항 누락
- 0.4: 중요한 쟁점을 놓침 (예: 양방향 분기에서 한쪽만 설명)
- 0.1: 핵심 쟁점 자체를 파악하지 못함

숫자 하나만 답하세요 (예: 0.85)"""


def score_faithfulness(question: str, answer: str, cited: list[str]) -> float:
    """근거 충실도: 답변이 인용 문단에 기반하는가."""
    user = f"[질문]\n{question}\n\n[답변]\n{answer[:1500]}\n\n[인용 문단]\n{', '.join(cited)}"
    return _llm_score(_FAITHFULNESS_SYSTEM, user)


def score_relevancy(question: str, answer: str) -> float:
    """답변 적절성: 질문에 대한 답변이 적절한가."""
    user = f"[질문]\n{question}\n\n[답변]\n{answer[:1500]}"
    return _llm_score(_RELEVANCY_SYSTEM, user)


def score_completeness(question: str, answer: str, matched_topics: list[str]) -> float:
    """답변 완전성: 고려해야 할 사항을 빠뜨리지 않았는가."""
    topics_str = ", ".join(matched_topics) if matched_topics else "(토픽 없음)"
    user = (
        f"[질문]\n{question}\n\n[답변]\n{answer[:1500]}\n\n"
        f"[매칭된 토픽]\n{topics_str}"
    )
    return _llm_score(_COMPLETENESS_SYSTEM, user)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인 채점 로직
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# 메트릭별 가중치 (총합 1.0)
METRIC_WEIGHTS = {
    # 규칙 기반 (API 없이 즉시 산출)
    "response_time":      0.10,
    "citation_coverage":  0.15,
    "topic_match":        0.10,
    "conclusion_safety":  0.10,
    # LLM 기반 (--with-llm 시에만)
    "faithfulness":       0.20,
    "relevancy":          0.20,
    "completeness":       0.15,
}

METRIC_LABELS = {
    "response_time":      "응답 속도",
    "citation_coverage":  "인용 커버리지",
    "topic_match":        "토픽 매칭",
    "conclusion_safety":  "결론 신중성",
    "faithfulness":       "근거 충실도",
    "relevancy":          "답변 적절성",
    "completeness":       "답변 완전성",
}


def score_one(doc: dict, with_llm: bool = False) -> dict:
    """usage_logs 문서 1건을 채점하여 메트릭별 점수를 반환한다."""
    question = doc.get("question", "")
    answer = doc.get("answer", "")
    cited = doc.get("cited_paragraphs", [])
    topics = doc.get("matched_topics", [])
    keywords = doc.get("search_keywords", [])
    is_sit = doc.get("is_situation", False)
    is_conc = doc.get("is_conclusion", False)
    branches = doc.get("selected_branches", [])
    ms = doc.get("response_time_ms", 0)

    scores = {
        "response_time":     score_response_time(ms),
        "citation_coverage": score_citation_coverage(cited, answer),
        "topic_match":       score_topic_match(topics, is_sit, keywords),
        "conclusion_safety": score_conclusion_safety(is_sit, is_conc, branches, answer),
    }

    if with_llm:
        scores["faithfulness"]  = score_faithfulness(question, answer, cited)
        scores["relevancy"]     = score_relevancy(question, answer)
        scores["completeness"]  = score_completeness(question, answer, topics)

    return scores


def weighted_total(scores: dict) -> float:
    """가중 평균 점수를 계산한다. LLM 메트릭이 없으면 규칙 기반만으로 정규화."""
    total_weight = sum(
        METRIC_WEIGHTS[k] for k in scores if k in METRIC_WEIGHTS
    )
    if total_weight == 0:
        return 0.0
    return sum(
        scores[k] * METRIC_WEIGHTS[k] for k in scores if k in METRIC_WEIGHTS
    ) / total_weight


def generate_report(results: list[dict], with_llm: bool) -> str:
    """마크다운 리포트를 생성한다."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mode = "규칙 기반 + LLM" if with_llm else "규칙 기반만"
    lines = [
        f"# 실사용 데이터 품질 채점 리포트",
        f"",
        f"> {len(results)}건 | {mode} | {now}",
        f"",
    ]

    # ── 전체 평균 ──────────────────────────────────────────────
    if results:
        all_totals = [r["total"] for r in results]
        avg_total = sum(all_totals) / len(all_totals)

        # 메트릭별 평균
        metric_keys = list(results[0]["scores"].keys())
        lines.append("## 전체 평균")
        lines.append("")
        lines.append(f"**종합 점수: {avg_total:.2f}** / 1.0")
        lines.append("")
        lines.append("| 메트릭 | 평균 | 가중치 |")
        lines.append("|--------|------|--------|")
        for k in metric_keys:
            vals = [r["scores"][k] for r in results if k in r["scores"]]
            avg = sum(vals) / len(vals) if vals else 0
            label = METRIC_LABELS.get(k, k)
            weight = METRIC_WEIGHTS.get(k, 0)
            lines.append(f"| {label} | {avg:.2f} | {weight:.0%} |")
        lines.append("")

    # ── 개별 케이스 ─────────────────────────────────────────────
    lines.append("---")
    lines.append("")
    lines.append("## 개별 케이스")
    lines.append("")

    # 점수 낮은 순으로 정렬 (문제 케이스 먼저)
    sorted_results = sorted(results, key=lambda r: r["total"])

    for r in sorted_results:
        q = r["question"][:60]
        total = r["total"]
        fb = r.get("feedback", "-")
        ms = r.get("response_time_ms", 0)
        grade = _grade_emoji(total)

        lines.append(f"### {grade} {q}{'...' if len(r['question']) > 60 else ''}")
        lines.append(f"")
        lines.append(f"종합: **{total:.2f}** | 응답: {ms/1000:.1f}s | 피드백: {fb}")
        lines.append(f"")

        # 메트릭 테이블
        lines.append("| 메트릭 | 점수 |")
        lines.append("|--------|------|")
        for k, v in r["scores"].items():
            label = METRIC_LABELS.get(k, k)
            flag = " ⚠️" if v < 0.5 else ""
            lines.append(f"| {label} | {v:.2f}{flag} |")
        lines.append("")

    # ── 개선 우선순위 ───────────────────────────────────────────
    low_cases = [r for r in sorted_results if r["total"] < 0.6]
    if low_cases:
        lines.append("---")
        lines.append("")
        lines.append("## 개선 우선순위 (종합 0.6 미만)")
        lines.append("")
        for r in low_cases:
            q = r["question"][:80]
            # 가장 낮은 메트릭 찾기
            worst_k = min(r["scores"], key=r["scores"].get)
            worst_label = METRIC_LABELS.get(worst_k, worst_k)
            lines.append(f"- **{q}** → {worst_label} {r['scores'][worst_k]:.2f}")
        lines.append("")

    return "\n".join(lines)


def _grade_emoji(score: float) -> str:
    if score >= 0.8:
        return "A"
    if score >= 0.6:
        return "B"
    if score >= 0.4:
        return "C"
    return "D"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _save_scores_to_db(coll, doc_id, scores: dict, total: float, with_llm: bool):
    """채점 결과를 usage_logs 문서에 저장한다.

    auto_scores 필드로 저장하여 미채점/채점 완료를 구분할 수 있다.
    """
    mode = "rule+llm" if with_llm else "rule"
    coll.update_one(
        {"_id": doc_id},
        {"$set": {
            "auto_scores": {
                "metrics": scores,
                "total": round(total, 3),
                "mode": mode,
                "scored_at": datetime.now(timezone.utc),
            },
        }},
    )


def main():
    parser = argparse.ArgumentParser(description="실사용 데이터 품질 채점")
    parser.add_argument(
        "--with-llm", action="store_true",
        help="LLM 기반 메트릭 포함 (OpenAI API 호출 발생)",
    )
    parser.add_argument(
        "--rescore", action="store_true",
        help="이미 채점된 건도 재채점",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="최근 N건만 채점 (0=전체)",
    )
    args = parser.parse_args()

    client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    db = client[settings.mongo_db_name]
    coll = db["usage_logs"]

    # ── LLM 채점이 아니면 리포트만 생성 ────────────────────────────
    # 규칙 기반은 usage_logger.py에서 매 응답마다 자동 저장됨
    if not args.with_llm:
        scored_docs = list(
            coll.find({"auto_scores": {"$exists": True}}).sort("timestamp", -1)
        )
        if args.limit > 0:
            scored_docs = scored_docs[:args.limit]
        if not scored_docs:
            print("채점된 로그가 없습니다.")
            return
        results = []
        for doc in scored_docs:
            s = doc["auto_scores"]
            results.append({
                "question": doc.get("question", ""),
                "scores": s["metrics"],
                "total": s["total"],
                "feedback": doc.get("feedback", "-"),
                "response_time_ms": doc.get("response_time_ms", 0),
            })
        report = generate_report(results, with_llm=False)
        REPORT_PATH.write_text(report, encoding="utf-8")
        print(f"리포트 생성: {REPORT_PATH} ({len(results)}건)")
        avg = sum(r["total"] for r in results) / len(results)
        print(f"종합 평균: {avg:.2f} / 1.0")
        return

    # ── LLM 심화 채점 대상 필터링 ────────────────────────────────
    # LLM 미채점: auto_scores.mode가 "rule"인 건 (LLM 채점 안 된 것)
    if args.rescore:
        mongo_filter = {}
    else:
        mongo_filter = {
            "auto_scores.mode": {"$ne": "rule+llm"},
        }
    query = coll.find(mongo_filter).sort("timestamp", -1)
    if args.limit > 0:
        query = query.limit(args.limit)

    docs = list(query)

    # 채점 대상 현황 출력
    total_count = coll.count_documents({})
    scored_count = coll.count_documents({"auto_scores": {"$exists": True}})
    unscored_count = total_count - scored_count

    print(f"전체: {total_count}건 | 채점 완료: {scored_count}건 | 미채점: {unscored_count}건")

    if not docs:
        print("새로 채점할 건이 없습니다. --rescore로 재채점하거나 --report-only로 리포트를 생성하세요.")
        return

    print(f"채점 시작: {len(docs)}건 ({'규칙+LLM' if args.with_llm else '규칙 기반'})")

    results = []
    for i, doc in enumerate(docs):
        scores = score_one(doc, with_llm=args.with_llm)
        total = weighted_total(scores)

        # DB에 채점 결과 저장
        _save_scores_to_db(coll, doc["_id"], scores, total, args.with_llm)

        results.append({
            "question": doc.get("question", ""),
            "scores": scores,
            "total": total,
            "feedback": doc.get("feedback", "-"),
            "response_time_ms": doc.get("response_time_ms", 0),
        })

        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(docs)} 완료...")

    # 리포트는 전체 채점 완료 건으로 생성 (방금 채점한 것 + 기존)
    all_scored = list(
        coll.find({"auto_scores": {"$exists": True}}).sort("timestamp", -1)
    )
    all_results = []
    for doc in all_scored:
        s = doc["auto_scores"]
        all_results.append({
            "question": doc.get("question", ""),
            "scores": s["metrics"],
            "total": s["total"],
            "feedback": doc.get("feedback", "-"),
            "response_time_ms": doc.get("response_time_ms", 0),
        })

    report = generate_report(all_results, with_llm=args.with_llm)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"\n리포트 생성: {REPORT_PATH} (전체 {len(all_results)}건)")

    avg = sum(r["total"] for r in all_results) / len(all_results)
    print(f"종합 평균: {avg:.2f} / 1.0")


if __name__ == "__main__":
    main()

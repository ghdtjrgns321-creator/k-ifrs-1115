# app/test/quality_evaluator.py
# 모델 비교용 4축 자동 품질 평가: 환각 / 포맷 / 채점기준 매칭 / 검색 타겟 커버리지
import re
from dataclasses import dataclass

from app.test.model_comparison.model_comparison_question import GoldenQuestion


@dataclass
class EvalResult:
    passed: bool
    score: float       # 0.0 ~ 1.0
    details: str


# ── 1. 환각 체크 ─────────────────────────────────────────────────────────────

def check_hallucination(
    question: GoldenQuestion,
    answer: str,
    cited_paragraphs: list[str],
    selected_branches: list[str],
    is_reasoning: bool = True,
) -> EvalResult:
    """cited_paragraphs 비어있거나, situation인데 branches 비어있으면 FAIL."""
    issues: list[str] = []

    if not cited_paragraphs:
        issues.append("cited_paragraphs 비어있음")

    # selected_branches 체크는 reasoning 모델에만 적용
    if question.question_type == "situation" and not selected_branches and is_reasoning:
        issues.append("situation인데 selected_branches 비어있음")

    # answer 본문에 "(문단 XX)" 인용 패턴이 하나도 없으면 FAIL
    citation_pattern = re.findall(r"문단\s*[A-Z]?\d+", answer)
    if not citation_pattern:
        issues.append("answer 내 문단 인용 패턴 0개")

    passed = len(issues) == 0
    score = 1.0 if passed else max(0.0, 1.0 - len(issues) * 0.34)
    return EvalResult(passed=passed, score=score, details="; ".join(issues) if issues else "OK")


# ── 2. 포맷 준수 ─────────────────────────────────────────────────────────────

def check_format(
    question: GoldenQuestion,
    answer: str,
    follow_up_questions: list[str],
) -> EvalResult:
    """output_contract 포맷 규칙 준수 여부 검증."""
    issues: list[str] = []

    has_conclusion = any(
        marker in answer
        for marker in ["**[결론]**", "**[조건부 결론]**", "**[확인 질문]**"]
    )
    if not has_conclusion:
        issues.append("결론 섹션 미존재")

    if "**[논리적 근거" not in answer and "논리적 근거 및 참조문단" not in answer:
        issues.append("논리적 근거 섹션 미존재")

    if re.search(r"^###\s", answer, re.MULTILINE):
        issues.append("### 헤딩 사용 (format_rules 위반)")

    passed = len(issues) == 0
    score = 1.0 if passed else max(0.0, 1.0 - len(issues) * 0.34)
    return EvalResult(passed=passed, score=score, details="; ".join(issues) if issues else "OK")


# ── 3. 채점기준 매칭 ─────────────────────────────────────────────────────────

def check_scoring_criteria(
    question: GoldenQuestion,
    answer: str,
    follow_up_questions: list[str],
) -> EvalResult:
    """expected_keywords 매칭 + scoring_criteria 키워드 부분 자동 채점."""
    if question.expected_keywords:
        matched_kw = sum(1 for kw in question.expected_keywords if kw in answer)
        kw_ratio = matched_kw / len(question.expected_keywords)
    else:
        kw_ratio = 1.0

    criteria_scores: list[float] = []
    for criterion in question.scoring_criteria:
        score = _score_criterion(question.id, criterion, answer, follow_up_questions)
        criteria_scores.append(score)

    criteria_ratio = sum(criteria_scores) / len(criteria_scores) if criteria_scores else 0.0

    final_score = kw_ratio * 0.4 + criteria_ratio * 0.6
    passed_count = sum(1 for s in criteria_scores if s >= 0.5)
    total = len(criteria_scores)

    return EvalResult(
        passed=final_score >= 0.5,
        score=final_score,
        details=f"{passed_count}/{total} criteria (kw:{kw_ratio:.0%})",
    )


def _score_criterion(qid: str, criterion: str, answer: str, follow_ups: list[str]) -> float:
    """개별 채점기준을 키워드 매칭으로 점수화 (0.0 ~ 1.0)."""

    # T2 특수: "불필요한 꼬리질문 없이 즉답"
    if qid == "T2" and "꼬리질문" in criterion:
        situation_keywords = ["변동대가인가요", "위약금", "장려금", "어떤 종류"]
        has_situation_followup = any(kw in " ".join(follow_ups) for kw in situation_keywords)
        return 0.0 if has_situation_followup else 1.0

    # T3 특수: "불필요한 꼬리질문 없이 즉답"
    if qid == "T3" and "꼬리질문" in criterion:
        bad_keywords = ["가능성이 매우 높은가요", "특정 수행의무", "할인액"]
        has_bad_followup = any(kw in " ".join(follow_ups) for kw in bad_keywords)
        return 0.0 if has_bad_followup else 1.0

    tokens = re.findall(r"[가-힣]{2,}|[\d,.]+[원%]?", criterion)
    if not tokens:
        return 0.5

    matched = sum(1 for t in tokens if t in answer)
    return min(1.0, matched / max(1, len(tokens) * 0.5))


# ── 4. 검색 타겟 커버리지 ────────────────────────────────────────────────────

def check_retrieval_targets(
    question: GoldenQuestion,
    relevant_docs: list[dict],
) -> EvalResult:
    """필수 검색 타겟이 retrieved docs에 포함되어 있는지 검증.

    각 타겟의 identifier를 문서의 content, hierarchy, chunk_id 등에서 검색합니다.
    """
    if not question.retrieval_targets:
        return EvalResult(passed=True, score=1.0, details="타겟 없음")

    # 모든 문서의 텍스트를 하나로 합침 (검색 대상)
    doc_texts = []
    for doc in relevant_docs:
        parts = []
        for key in ("content", "full_content", "hierarchy", "chunk_id", "source"):
            val = doc.get(key, "")
            if val:
                parts.append(str(val))
        doc_texts.append(" ".join(parts))
    combined = "\n".join(doc_texts)

    found: list[str] = []
    missed: list[str] = []
    for target in question.retrieval_targets:
        # identifier에서 핵심 매칭 패턴 추출
        if _target_found_in_docs(target.identifier, combined):
            found.append(f"{target.category}:{target.identifier}")
        else:
            missed.append(f"{target.category}:{target.identifier}")

    total = len(question.retrieval_targets)
    found_count = len(found)
    score = found_count / total if total > 0 else 1.0
    passed = score >= 0.5

    if missed:
        detail = f"{found_count}/{total} (miss: {', '.join(missed)})"
    else:
        detail = f"{found_count}/{total} ALL"

    return EvalResult(passed=passed, score=score, details=detail)


def _target_found_in_docs(identifier: str, combined_text: str) -> bool:
    """identifier가 문서 텍스트에서 발견되는지 유연하게 매칭."""
    # 정확히 일치하는 경우
    if identifier in combined_text:
        return True

    # "문단 53" → "문단 53" or "문단53" 패턴
    if identifier.startswith("문단"):
        num = identifier.replace("문단 ", "").replace("문단", "").strip()
        # "문단 53", "문단53", "53항" 등 유연 매칭
        patterns = [
            f"문단\\s*{re.escape(num)}[^0-9]",
            f"문단\\s*{re.escape(num)}$",
        ]
        for pat in patterns:
            if re.search(pat, combined_text):
                return True

    # "사례 20" → "사례 20", "사례20" 등
    if identifier.startswith("사례"):
        num = identifier.replace("사례 ", "").replace("사례", "").strip()
        patterns = [
            f"사례\\s*{re.escape(num)}[^0-9]",
            f"사례\\s*{re.escape(num)}$",
        ]
        for pat in patterns:
            if re.search(pat, combined_text):
                return True

    # "BC52" → BC52 패턴
    if re.match(r"BC\d+", identifier):
        if re.search(rf"\b{re.escape(identifier)}\b", combined_text):
            return True
        if re.search(rf"BC\s*{identifier[2:]}", combined_text):
            return True

    # 문서 ID 부분 매칭 (QNA-xxx, FSS-CASE-xxx)
    # ID의 핵심 부분만 추출하여 매칭
    if "-" in identifier:
        # FSS-CASE-2023-2405-01 → "2023-2405-01" or "2405-01"
        parts = identifier.split("-")
        if len(parts) >= 3:
            short_id = "-".join(parts[-3:])
            if short_id in combined_text:
                return True
            shorter_id = "-".join(parts[-2:])
            if shorter_id in combined_text:
                return True

    return False

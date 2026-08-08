"""STEP 2 결정적 가드 — LLM 초안을 사람에게 올리기 전에 코드로 걸러낸다.

설계: docs/quality-loop/03-proposals-gate.md §3
사람 승인은 "이게 회계적으로 맞나"에만 쓰여야 한다. 코드로 판정 가능한 것은 여기서 자른다.

Why(질문 포함 검사 폐기): 옛 가드는 "용어가 질문에 글자 그대로 없으면 거부"였다.
진입이 글자매칭 하나였을 때는 맞는 규칙이었다 — 질문에 없는 말은 어떤 질문도 못 잡았다.
지금은 LLM이 용어 목록에서 고르는 통로가 있어서, "선적 후 운임 부담"이라고 돌려 말해도
`CIF`가 잡힌다(docs/entry-traverse/plan.md §4). 글자가 없어도 효과가 있으므로 그 검사는
성립하지 않는다. 대신 제안의 출처를 `unknown_terms`(AI가 실제로 필요하다고 답한 말)로
한정해 근거를 확보한다.
"""

from __future__ import annotations

import re

MIN_TERM_LEN = 2  # graph.py term_index와 동일 기준

# 개념 개수 상한은 두지 않는다.
# Why: 3개로 잘라뒀는데 근거가 없었다. 실측하니 기존 사전 285건의 분포는 1개 46% ·
# 2개 27% · 3개 12%이고 최대는 11개(`인식시기`)다 — 상한 3은 데이터와도 어긋난다.
# 게다가 조용히 자르면 4번째부터 흔적 없이 사라진다. 개수는 제안에 그대로 싣고
# 많으면 사람이 보고 판단한다(근거 없는 임계 금지).


def norm(s: str) -> str:
    """공백 제거 — graph.py `_norm`과 같은 규칙(용어 매칭이 그 규칙으로 돈다)."""
    return re.sub(r"\s+", "", s or "")


def check_term(term: str, existing: set[str]) -> str | None:
    """용어 제안을 검사한다. 통과하면 None, 걸리면 사유 문자열.

    existing = 사전 변환표에 이미 있는 키(용어사전 + 개념 제목, 정규화됨).
    """
    t = norm(term)
    if len(t) < MIN_TERM_LEN:
        return f"용어가 너무 짧음({len(t)}자)"
    if t in existing:
        return "이미 용어 목록에 있음"
    return None


def term_collisions(term: str, existing: set[str]) -> list[str]:
    """기존 용어와 포함 관계인 것들.

    LLM 선택 통로는 정확 일치라 무해하지만, 글자매칭 통로는 substring이라 진입 결과가
    함께 바뀔 수 있다. **자름이 아니라 표시** — 포함 관계가 곧 오류는 아니다.
    """
    t = norm(term)
    return sorted(e for e in existing if e != t and (e in t or t in e))


def valid_concepts(ids: list[str], known: set[str]) -> list[str]:
    """그래프에 실재하는 개념 id만 남긴다(순서 보존, 중복 제거). **자르지 않는다.**"""
    out: list[str] = []
    for i in ids or []:
        if i in known and i not in out:
            out.append(i)
    return out


def literal_hits(term: str, questions: list[str]) -> int:
    """이 용어가 글자 그대로 들어있는 과거 질문 수.

    글자매칭 통로가 곧바로 잡게 되는 건수 — 영향 범위의 하한이다. LLM 선택 통로로
    잡히는 건은 여기 안 세어지므로 실제 영향은 이보다 크다.
    """
    t = norm(term)
    return sum(1 for q in questions if t in norm(q))

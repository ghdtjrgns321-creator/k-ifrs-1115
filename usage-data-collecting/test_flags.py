"""L1 자동 점검 검증 — DB·LLM 없이 순수 판정만 확인.

진입 구조: 용어사전 경유(글자매칭 + LLM 선택) + 임베딩. docs/entry-traverse/plan.md §5

실행: PYTHONPATH=. uv run python usage-data-collecting/test_flags.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from flags import (  # noqa: E402
    is_followup,
    is_unreliable,
    l1_flags,
    l1_observations,
    suspect_layer,
)


def log(**kw) -> dict:
    """기본은 '아무 문제 없는 정상 로그'. 케이스마다 필요한 것만 덮어쓴다."""
    base = {
        "flow": "full",
        "answer": "문단 20에 따르면 ...",
        "answer_len": len("문단 20에 따르면 ..."),
        "cited_paragraphs": ["문단 20"],
        "entry": {
            "concept_ids": ["c1"],
            "via_llm": ["c1"],
            "via_embed": [],
            "matched_terms": ["거래가격"],
            "matched_terms_raw": ["거래가격"],
            "term_hints": ["거래가격"],
            "unknown_terms": [],
        },
        "retrieval": {"paras": ["20", "21"], "context_paras": ["20"], "doc_count": 5},
    }
    for k, v in kw.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


FLAG_CASES = [
    ("정상 로그는 이상 없음", log(), []),
    (
        "fast_path는 판정 대상 아님",
        log(flow="fast_path", entry={"concept_ids": []}),
        [],
    ),
    ("범위밖 거절도 대상 아님", log(flow="rejected", entry={"concept_ids": []}), []),
    (
        "응답 실패 로그는 대상 아님",
        log(outcome="error", flow="error", entry={"concept_ids": []}),
        [],
    ),
    ("outcome 없는 구버전 로그는 성공 취급", log(), []),
    ("진입 0건", log(entry={"concept_ids": []}), ["ENTRY_EMPTY"]),
    ("원문 0건", log(retrieval={"doc_count": 0}), ["NO_DOCS"]),
    (
        "안 읽은 문단 인용",
        log(cited_paragraphs=["문단 20", "문단 35"]),
        ["CITATION_OUT"],
    ),
    (
        "후보엔 있으나 컨텍스트에 없는 문단 인용도 환각",
        log(cited_paragraphs=["문단 21"]),
        ["CITATION_OUT"],
    ),
    ("중분류 괄호는 같은 문단으로 정규화", log(cited_paragraphs=["문단 20⑶"]), []),
    (
        "진입 0 + 원문 0은 층 순서대로",
        log(entry={"concept_ids": []}, retrieval={"doc_count": 0}),
        ["ENTRY_EMPTY", "NO_DOCS"],
    ),
]

OBSERVATION_CASES = [
    ("정상 로그는 보강 후보 없음", log(), []),
    (
        "사전에 없는 용어를 AI가 답함",
        log(entry={"unknown_terms": ["채널스터핑"]}),
        ["TERM_UNKNOWN"],
    ),
    (
        "사전 두 통로 다 실패(임베딩만)",
        log(entry={"via_llm": [], "matched_terms": [], "matched_terms_raw": []}),
        ["DICT_MISS"],
    ),
    (
        "원문은 못 걸리고 재작성문이 걸림",
        log(entry={"matched_terms_raw": []}),
        ["TERM_MISS_RAW"],
    ),
    ("AI가 용어를 하나도 못 고름", log(entry={"term_hints": []}), ["HINT_EMPTY"]),
    (
        "여러 항목이 함께 걸리면 정의 순서대로",
        log(
            entry={
                "unknown_terms": ["채널스터핑"],
                "via_llm": [],
                "matched_terms": [],
                "matched_terms_raw": [],
                "term_hints": [],
            }
        ),
        ["TERM_UNKNOWN", "DICT_MISS", "HINT_EMPTY"],
    ),
    (
        "구버전 로그(원문 매칭 필드 없음)는 원문 판정 보류",
        log(entry={"matched_terms_raw": None}),
        [],
    ),
]

# (이름, 이 로그, 같은 세션의 다음 로그, 재질문인가)
FOLLOWUP_CASES = [
    ("후속 질문 없음", log(), None, False),
    ("정상 답변 뒤 새 질문", log(), {"flow": "full"}, True),
    ("이전 검색 재사용 후속도 재질문", log(), {"flow": "pre_retrieved"}, True),
    # 되묻기(clarify)를 낸 답변에 사용자가 답하는 것은 시스템이 유도한 정상 흐름이다
    ("되묻기 답신은 재질문 아님", log(), {"flow": "fast_path"}, False),
    ("범위밖 질문 후속은 재질문 아님", log(), {"flow": "rejected"}, False),
    (
        "판정 대상 아닌 로그는 재질문도 안 봄",
        log(flow="fast_path"),
        {"flow": "full"},
        False,
    ),
    (
        "응답 실패 로그도 대상 아님",
        log(outcome="error", flow="error"),
        {"flow": "full"},
        False,
    ),
]

LAYER_CASES = [
    (["ENTRY_EMPTY"], [], 1),
    (["NO_DOCS"], [], 4),
    (["CITATION_OUT"], [], 3),
    # 실패가 관찰보다 우선
    (["CITATION_OUT"], ["TERM_UNKNOWN"], 3),
    ([], ["HINT_EMPTY"], 2),
    ([], ["TERM_UNKNOWN"], 1),
    ([], [], None),
]


def main() -> None:
    fails: list[str] = []

    def run(cases, fn, label):
        for name, doc, want in cases:
            got = fn(doc)
            ok = got == want
            print(f"  {'O' if ok else 'X'} [{label}] {name:34s} → {got}")
            if not ok:
                fails.append(f"{name}: got={got} want={want}")

    run(FLAG_CASES, l1_flags, "이상")
    run(OBSERVATION_CASES, l1_observations, "관찰")

    for name, doc, nxt, want in FOLLOWUP_CASES:
        got = is_followup(doc, nxt)
        ok = got == want
        print(f"  {'O' if ok else 'X'} [재질문] {name:34s} → {got}")
        if not ok:
            fails.append(f"{name}: got={got} want={want}")

    for flags, obs, want in LAYER_CASES:
        got = suspect_layer(flags, obs)
        if got != want:
            fails.append(f"suspect_layer({flags},{obs}): got={got} want={want}")

    if not is_unreliable({"answer": "x" * 2000, "answer_len": 2514}):
        fails.append("is_unreliable: 절단된 답변을 못 잡음")
    if is_unreliable({"answer": "x" * 100, "answer_len": 100}):
        fails.append("is_unreliable: 안 잘린 답변을 잘못 잡음")

    total = (
        len(FLAG_CASES)
        + len(OBSERVATION_CASES)
        + len(FOLLOWUP_CASES)
        + len(LAYER_CASES)
        + 2
    )
    print(f"\n결과 {total - len(fails)}/{total} PASS")
    if fails:
        for f in fails:
            print("  실패:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()

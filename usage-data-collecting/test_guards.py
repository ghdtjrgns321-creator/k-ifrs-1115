"""STEP 2 가드 검증 — LLM·DB 없이 순수 판정만 확인.

실행: PYTHONPATH=. uv run python usage-data-collecting/test_guards.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import guards  # noqa: E402

# 사전 변환표에 이미 있는 키(용어사전 + 개념 제목), 정규화된 형태
EXISTING = {guards.norm(t) for t in {"밀어내기", "거래가격", "매출", "보증"}}

TERM_CASES = [
    ("새 용어는 통과", "채널스터핑", None),
    ("공백 차이는 같은 말로 본다", "거래 가격", "이미 용어 목록에 있음"),
    ("한 글자는 거부", "물", "용어가 너무 짧음"),
    ("이미 있는 용어는 거부", "매출", "이미 용어 목록에 있음"),
    (
        "질문에 없는 말도 통과 — LLM 선택 통로가 잡는다",
        "CIF",
        None,
    ),
]

OTHER_CASES = [
    (
        "포함 관계 용어를 충돌로 표시",
        lambda: guards.term_collisions("매출채권", EXISTING),
        ["매출"],
    ),
    (
        "모르는 개념 id는 버린다",
        lambda: guards.valid_concepts(["c1", "없는거", "c2"], {"c1", "c2"}),
        ["c1", "c2"],
    ),
    (
        "개념 id 순서·중복 정리",
        lambda: guards.valid_concepts(["c2", "c1", "c2"], {"c1", "c2"}),
        ["c2", "c1"],
    ),
    (
        "개념 개수는 자르지 않는다",
        lambda: guards.valid_concepts(
            ["c1", "c2", "c3", "c4"], {"c1", "c2", "c3", "c4"}
        ),
        ["c1", "c2", "c3", "c4"],
    ),
    (
        "글자 그대로 걸리는 과거 질문 수",
        lambda: guards.literal_hits(
            "채널스터핑",
            ["채널 스터핑 한 물량도 매출인가", "채널스터핑이 뭔가요", "무관한 질문"],
        ),
        2,
    ),
]


def main() -> None:
    fails = []
    for name, term, want in TERM_CASES:
        got = guards.check_term(term, EXISTING)
        ok = (got is None and want is None) or (got and want and want in got)
        print(f"  {'O' if ok else 'X'} {name:38s} → {got}")
        if not ok:
            fails.append(f"{name}: got={got} want={want}")

    for name, fn, want in OTHER_CASES:
        got = fn()
        ok = got == want
        print(f"  {'O' if ok else 'X'} {name:38s} → {got}")
        if not ok:
            fails.append(f"{name}: got={got} want={want}")

    total = len(TERM_CASES) + len(OTHER_CASES)
    print(f"\n결과 {total - len(fails)}/{total} PASS")
    if fails:
        for f in fails:
            print("  실패:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()

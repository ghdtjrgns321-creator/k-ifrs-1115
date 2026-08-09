"""확정 라벨 검증 — 08-FINAL-LABEL.md의 수치가 데이터와 일치하는지 강제한다.

문장으로 "확정했다"고 쓰지 않는다. 이 스크립트가 exit 0이어야 확정이다.
어긋나면 어디가 틀렸는지 찍고 exit 1.

라벨 사양 원본은 `docs/eval-v2/08-FINAL-LABEL.md`(로컬 문서). 이 스크립트는 그 수치를
하드코딩해 데이터와 대조하므로, 문서가 없어도 게이트는 단독으로 작동한다.

실행: PYTHONPATH=. uv run python app/test/qna_holdout/verify_labels.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_E = _ROOT / "data" / "testdata" / "gold_extract"
_GOLD = _E / "gold_paragraphs.json"
_ADJ = _E / "adjudication.json"
_TESTSET = _ROOT / "data" / "testdata" / "qna_testset.json"
_CHUNKS = _ROOT / "data" / "web" / "kifrs-1115-chunks.json"

# 08-FINAL-LABEL.md 의 정본 수치
EXPECT = {
    "total_cases": 92,
    "excluded_cases": 2,
    "conclusion_cases": 90,
    "recall_cases": 72,
    "no_para_cases": 18,
    "essential_paras": 164,
    "cited_paras": 229,
    "bc_paras": 11,
}

_WS = re.compile(r"\s+")


def squash(s: str) -> str:
    return _WS.sub("", s or "")


def main() -> None:
    fail: list[str] = []

    gold = json.loads(_GOLD.read_text(encoding="utf-8"))
    testset = {c["id"]: c for c in json.loads(_TESTSET.read_text(encoding="utf-8"))}
    real = {
        str(c["metadata"]["paraNum"]).upper()
        for c in json.loads(_CHUNKS.read_text(encoding="utf-8"))
    }
    adj = json.loads(_ADJ.read_text(encoding="utf-8"))

    # 1. 케이스 수 — 테스트셋과 라벨이 1:1
    if len(gold) != EXPECT["total_cases"]:
        fail.append(f"라벨 케이스 {len(gold)} != {EXPECT['total_cases']}")
    if {c["id"] for c in gold} != set(testset):
        fail.append("라벨 케이스 id 집합이 테스트셋과 다르다")

    # 2. 분모 층화
    scored = [c for c in gold if c.get("scope") != "excluded"]
    ex = [c for c in gold if c.get("scope") == "excluded"]
    no_para = [c for c in scored if not c["paragraphs"]]

    # 회수율 분모 = 1115호이고 LLM 컨텍스트에 들어갈 수 있는 문단.
    # BC는 답변 생성에 미투입(README 한계 8)이라 이 지표의 사정거리 밖이다.
    def in_scope(p):
        return p["standard"] == "1115" and p.get("scope") != "bc_not_in_context"

    recall = [
        c
        for c in scored
        if any(in_scope(p) and p.get("essential") for p in c["paragraphs"])
    ]
    got = {
        "excluded_cases": len(ex),
        "conclusion_cases": len(scored),
        "recall_cases": len(recall),
        "no_para_cases": len(no_para),
        "essential_paras": sum(
            1
            for c in scored
            for p in c["paragraphs"]
            if in_scope(p) and p.get("essential") is True
        ),
        "cited_paras": sum(1 for c in scored for p in c["paragraphs"] if in_scope(p)),
        "bc_paras": sum(
            1
            for c in scored
            for p in c["paragraphs"]
            if p.get("scope") == "bc_not_in_context"
        ),
    }
    for k, v in got.items():
        if v != EXPECT[k]:
            fail.append(f"{k}: {v} != 정본 {EXPECT[k]}")

    # 층화 합계가 맞물리는지
    if len(scored) + len(ex) != len(gold):
        fail.append("제외 + 채점 대상 != 전체")
    if len(recall) + len(no_para) != len(scored):
        fail.append("회수율 분모 + 문단없음 != 결론 재현 분모")

    # 3. quote 실재 — 환각 차단
    for c in scored:
        src = squash(testset[c["id"]]["question"] + testset[c["id"]]["answer_gold"])
        for p in c["paragraphs"]:
            q = squash(p.get("quote", ""))
            if not q or q not in src:
                fail.append(f"quote 미실재: {c['id']} {p['standard']}:{p['para']}")

    # 4. 1115호 문단은 코퍼스에 실재
    for c in scored:
        for p in c["paragraphs"]:
            if p["standard"] == "1115" and p["para"].upper() not in real:
                fail.append(f"실재하지 않는 문단: {c['id']} {p['para']}")

    # 5. 미확정 잔존 금지
    open_ = [
        (c["id"], p["para"])
        for c in scored
        for p in c["paragraphs"]
        if p.get("source") == "unresolved"
    ]
    if open_:
        fail.append(f"미확정 {len(open_)}건 잔존: {open_[:5]}")

    # 6. 제외 케이스가 사유를 갖는지
    reasons = {e["id"] for e in adj.get("excluded_cases", [])}
    for c in ex:
        if c["id"] not in reasons or not c.get("exclude_reason"):
            fail.append(f"제외 사유 없음: {c['id']}")

    if fail:
        print("검증 실패:")
        for f in fail:
            print(f"  - {f}")
        sys.exit(1)

    print("라벨 검증 통과")
    print(
        f"  전체 {len(gold)} · 제외 {len(ex)} · 결론 재현 {len(scored)} · 회수율 {len(recall)}"
    )
    print(
        f"  필수 문단 {got['essential_paras']} · 전사 문단 {got['cited_paras']}"
        f" · BC 분모밖 {got['bc_paras']}"
    )
    print("  quote 실재 · 문단 실재 · 미확정 0 — 전부 통과")


if __name__ == "__main__":
    main()

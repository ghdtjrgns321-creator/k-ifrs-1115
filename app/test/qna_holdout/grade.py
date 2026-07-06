"""STEP 6 채점기 — 하드지표(인용 재현율, 자동) + 소프트지표(Sonnet scores.json) 병합 → report.md.

하드: gold_cited ∩ 답변 인용문단 / gold_cited (문단 0개 케이스는 하드 제외·소프트만).
소프트: 서브에이전트가 scores.json에 rubric 3축(conclusion/paragraph/branch 0~2)+evidence 기록.
재현 판정: conclusion≥1 AND 총점(3축 합)≥4.

실행: PYTHONPATH=. uv run python app/test/qna_holdout/grade.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_HERE = Path(__file__).parent
RESULTS = _HERE / "results.json"
SCORES = _HERE / "scores.json"
REPORT = _HERE / "report.md"


def norm_para(p: str) -> str:
    """'문단 35⑶'→'35', '문단 B34'→'B34' — 핵심 번호만(중분류 괄호 무시)."""
    m = re.search(r"([Bb]?\d+[A-Z]?)", str(p))
    return m.group(1).upper() if m else str(p)


def hard_recall(gold: list[str], resp: list[str]) -> float | None:
    """인용 재현율. gold 인용 0개면 None(하드 채점 제외)."""
    gn = {norm_para(x) for x in (gold or [])}
    if not gn:
        return None
    rn = {norm_para(x) for x in (resp or [])}
    return len(gn & rn) / len(gn)


def load(path: Path) -> list | dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def main() -> None:
    results = load(RESULTS)
    scores = {s["id"]: s for s in load(SCORES)} if SCORES.exists() else {}
    n = len(results)

    rows = []
    for r in results:
        hr = hard_recall(r["gold_cited"], r["resp_cited"])
        s = scores.get(r["id"])
        soft = None
        reproduced = None
        if s:
            total = s["conclusion"] + s["paragraph"] + s["branch"]
            reproduced = s["conclusion"] >= 1 and total >= 4
            soft = (s["conclusion"], s["paragraph"], s["branch"], total)
        rows.append(
            {
                "id": r["id"],
                "title": r["title"],
                "hard": hr,
                "soft": soft,
                "repro": reproduced,
                "err": r.get("error"),
            }
        )

    # 통계
    hards = [x["hard"] for x in rows if x["hard"] is not None]
    graded = [x for x in rows if x["soft"] is not None]
    repro = [x for x in graded if x["repro"]]
    errs = [x for x in rows if x["err"]]

    L = ["# STEP 6 — QNA-off 홀드아웃 채점 리포트\n"]
    avg_hard = f"{sum(hards) / len(hards):.1%}" if hards else "N/A"
    L.append(
        f"> 케이스 **{n}건** | 하드 채점 {len(hards)}건(인용0 제외 {n - len(hards)}) "
        f"평균 재현율 **{avg_hard}** | 소프트 채점 {len(graded)}/{n} | "
        f"재현 **{len(repro)}/{len(graded)}** | 에러 {len(errs)}\n"
    )
    if not scores:
        L.append(
            "\n※ scores.json 없음 — 하드지표만. 소프트 채점(Sonnet) 후 재실행 필요.\n"
        )

    # 미재현 진단
    if graded:
        miss = [x for x in graded if not x["repro"]]
        L.append(f"\n## 미재현 {len(miss)}건 (결론축<1 또는 총점<4)\n")
        L.append("| id | 하드 | 결론 | 문단 | 분기 | 총점 |")
        L.append("|---|---|---|---|---|---|")
        for x in miss:
            c, p, b, t = x["soft"]
            hd = f"{x['hard']:.0%}" if x["hard"] is not None else "-"
            L.append(f"| {x['id']} | {hd} | {c} | {p} | {b} | {t} |")

    # 전체 표
    L.append("\n## 전체 케이스\n")
    L.append("| id | 하드재현율 | 결론 | 문단 | 분기 | 총점 | 재현 |")
    L.append("|---|---|---|---|---|---|---|")
    for x in rows:
        hd = f"{x['hard']:.0%}" if x["hard"] is not None else "-"
        if x["soft"]:
            c, p, b, t = x["soft"]
            rp = "O" if x["repro"] else "X"
        else:
            c = p = b = t = rp = "-"
        L.append(f"| {x['id']} | {hd} | {c} | {p} | {b} | {t} | {rp} |")

    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(
        f"하드 평균 재현율 {avg_hard} ({len(hards)}건) | 소프트 {len(graded)}/{n} | "
        f"재현 {len(repro)}/{len(graded)}"
    )
    print(f"→ {REPORT}")


if __name__ == "__main__":
    main()

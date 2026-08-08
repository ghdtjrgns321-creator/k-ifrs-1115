"""채점자를 채점한다 — 사람 라벨 20건으로 judge 프롬프트·모델을 고른다.

왜: 결론 채점은 LLM이 한다. 그 숫자가 맞는지 확인할 유일한 방법은 사람 판정과의
일치율이다. 검증 없이 모델을 고르면(예 "sonnet이 나을 것") 그것도 추측이다.

sheet  — 층화 표본 20건을 사람이 채점할 md로 뽑는다(확정형 10 · 분기형 10).
score  — 사람 라벨이 채워지면 모델별 일치율을 낸다.

표본은 채점 기준·모델 선정용이므로 확정/분기를 반반 넣는다. 전체 일치율의
불편추정이 아니다 — 어려운 쪽(분기형)에서 갈리므로 진단력을 우선했다.

답변은 기존 산출물(results*.json)을 쓴다. 검증 대상은 답변 품질이 아니라
"사람과 judge가 같은 판정을 하는가"라서 옛 답변으로도 성립한다.

실행:
  PYTHONPATH=. uv run python app/test/qna_holdout/exp_judge_eval.py sheet
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.test.qna_holdout import exp_common as C

_HERE = Path(__file__).parent
SHAPE = _HERE / "answer_shape.json"
ANSWERS = _HERE / "results.json"  # 옛 파이프라인 산출물 — 판정 대상으로만 사용
SHEET = _HERE / "judge_human_sheet.md"
IN_DIR = _HERE / "judge_input"
OUT_DIR = _HERE / "judge_out"
OUT2_DIR = _HERE / "judge_out_v2"
OUT3_DIR = _HERE / "judge_out_v3"
OUT4_DIR = _HERE / "judge_out_v4"
OUT5_DIR = _HERE / "judge_out_v5"
N_PER_KIND = 10


def pick(shape: dict, kind: str, n: int) -> list[str]:
    """결정적 층화 추출 — id 정렬 후 균등 간격. 시드 없이 재현된다."""
    ids = sorted(i for i, v in shape.items() if v["kind"] == kind)
    if len(ids) <= n:
        return ids
    step = len(ids) / n
    return [ids[int(k * step)] for k in range(n)]


def build_batches(per_batch: int = 5) -> None:
    """서브에이전트 채점용 입력 배치 — 케이스별 원문을 파일로 고정한다.

    Why(파일로 고정): 채점 입력이 대화에만 있으면 재검산도 감사도 안 된다.
    분모를 파일로 박아야 뒤에서 차집합으로 전수를 증명할 수 있다(census).
    """
    shape = json.loads(SHAPE.read_text("utf-8"))
    answers = {r["id"]: r for r in json.loads(ANSWERS.read_text("utf-8"))}
    ts = C.testset_map()
    ids = pick(shape, "fixed", N_PER_KIND) + pick(shape, "branched", N_PER_KIND)

    IN_DIR.mkdir(exist_ok=True)
    rows = [
        {
            "id": cid,
            "kind": shape[cid]["kind"],
            "axis": shape[cid]["axis"],
            "options": shape[cid]["options"],
            "question": (ts[cid]["question"] or "").strip(),
            "answer_gold": (answers[cid].get("answer_gold") or "").strip(),
            "answer_text": (answers[cid].get("answer_text") or "").strip(),
        }
        for cid in ids
    ]
    batches = [rows[i : i + per_batch] for i in range(0, len(rows), per_batch)]
    for n, b in enumerate(batches, 1):
        p = IN_DIR / f"batch{n}.json"
        p.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{p.name}: {len(b)}건 — {[r['id'] for r in b]}")
    (IN_DIR / "denominator.json").write_text(
        json.dumps({"ids": ids}, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n분모 {len(ids)}건 고정 → {IN_DIR.name}/denominator.json")


def collect() -> None:
    """서브에이전트 판정 취합 — 분모 차집합으로 전수를 증명한다(census).

    "20건 다 했다"를 문장으로 쓰지 않는다. 누락이 있으면 exit 1.
    인용(evidence)이 answer_text에 실제로 있는지도 검사한다 — 창작 인용 차단.
    """
    denom = json.loads((IN_DIR / "denominator.json").read_text("utf-8"))["ids"]
    answers = {r["id"]: r for r in json.loads(ANSWERS.read_text("utf-8"))}
    rows: dict[str, dict] = {}
    for p in sorted(OUT_DIR.glob("batch*.json")):
        for r in json.loads(p.read_text("utf-8")):
            rows[r["id"]] = r

    missing = [i for i in denom if i not in rows]
    extra = [i for i in rows if i not in denom]
    bad_quote = []
    for cid, r in rows.items():
        src = (answers.get(cid, {}).get("answer_text") or "").replace("\n", " ")
        for k in ("A_evidence", "B_evidence", "C_evidence"):
            q = (r.get(k) or "").strip().replace("\n", " ")
            if q and q not in src:
                bad_quote.append(f"{cid}.{k}")

    print(
        f"분모 {len(denom)} · 판정 {len(rows)} · 누락 {len(missing)} · 초과 {len(extra)}"
    )
    if missing:
        print(f"  누락: {missing}")
    if extra:
        print(f"  초과: {extra}")
    print(f"인용 원문 불일치 {len(bad_quote)}건 {bad_quote[:6]}")

    ok = [r for r in rows.values() if r["id"] in denom]
    a = sum(1 for r in ok if r.get("A_direction") == 1)
    c = sum(1 for r in ok if r.get("C_no_misassertion") == 1)
    b_rows = [r for r in ok if r.get("B_criterion") is not None]
    b = sum(1 for r in b_rows if r.get("B_criterion") == 1)
    print(f"\nA 방향   {a}/{len(ok)}")
    print(
        f"B 기준   {b}/{len(b_rows)}  (분기 제시 답변만; 확정형 {len(ok) - len(b_rows)}건 제외)"
    )
    print(f"C 오단정 {c}/{len(ok)}")
    print("\n조합 분포 (A,B,C):")
    combo: dict = {}
    for r in ok:
        k = (r.get("A_direction"), r.get("B_criterion"), r.get("C_no_misassertion"))
        combo.setdefault(str(k), []).append(r["id"])
    for k, v in sorted(combo.items()):
        print(f"  {k}: {len(v)}건 {v}")
    notes = [(r["id"], r["note"]) for r in ok if (r.get("note") or "").strip()]
    if notes:
        print(f"\n애매 판정 {len(notes)}건:")
        for i, n in notes:
            print(f"  {i}: {n[:90]}")
    if missing or extra or bad_quote:
        raise SystemExit(1)


def compare() -> None:
    """v1(A/B/C 3항목) vs v2(흐름 일치 단일 판정) 대조.

    핵심 시험: v1이 못 잡던 유형(정답의 예외·조건 누락, 허용→의무 격상)을
    v2가 실제로 잡는가. 그 4건은 GAPS에 이름으로 박아 판정을 눈으로 본다.
    """
    GAPS = {
        "QNA-SSI-202511018": "판정 관대 의심(부채 인식 시점 원칙 누락)",
        "QNA-2018-I-KQA004": "허용→의무 격상",
        "QNA-2019-I-KQA009-Q1": "예외 갈래 누락",
        "QNA-SSI-36993": "대안 갈래(지속 검토) 누락",
    }
    denom = json.loads((IN_DIR / "denominator.json").read_text("utf-8"))["ids"]
    answers = {r["id"]: r for r in json.loads(ANSWERS.read_text("utf-8"))}
    v1, v2 = {}, {}
    for p in sorted(OUT_DIR.glob("batch*.json")):
        for r in json.loads(p.read_text("utf-8")):
            v1[r["id"]] = r
    for p in sorted(OUT2_DIR.glob("batch*.json")):
        for r in json.loads(p.read_text("utf-8")):
            v2[r["id"]] = r

    missing = [i for i in denom if i not in v2]
    bad = [
        i
        for i, r in v2.items()
        if (r.get("evidence") or "").strip()
        and (r["evidence"]).strip() not in (answers[i].get("answer_text") or "")
    ]
    print(
        f"v2 분모 {len(denom)} · 판정 {len(v2)} · 누락 {len(missing)} · 인용 불일치 {len(bad)}"
    )
    if missing:
        print(f"  누락 {missing}")
    if bad:
        print(f"  인용 불일치 {bad}")

    # v1 통과 = A와 C가 모두 1 (B는 변별력 0으로 확인됨)
    def v1_pass(r) -> int:
        return int(r["A_direction"] == 1 and r["C_no_misassertion"] == 1)

    p1 = sum(v1_pass(v1[i]) for i in denom)
    p2 = sum(v2[i]["verdict"] for i in denom if i in v2)
    print(f"\nv1 통과(A=1 and C=1) {p1}/{len(denom)}   v2 통과 {p2}/{len(v2)}")

    flipped = [i for i in denom if i in v2 and v1_pass(v1[i]) != v2[i]["verdict"]]
    print(f"\n판정이 갈린 {len(flipped)}건:")
    for i in flipped:
        print(f"  {i}: v1={v1_pass(v1[i])} → v2={v2[i]['verdict']}")
        print(f"    v2 사유: {(v2[i].get('reason') or '')[:150]}")

    print("\n[핵심 시험] v1이 못 잡던 4건의 v2 판정:")
    for i, why in GAPS.items():
        r = v2.get(i)
        if not r:
            print(f"  {i}: v2 판정 없음")
            continue
        mark = "잡음" if r["verdict"] == 0 else "여전히 통과"
        print(f"  {i} [{why}] → v2={r['verdict']} ({mark})")
        print(f"    {(r.get('reason') or '')[:170]}")
    if missing or bad:
        raise SystemExit(1)


def repro() -> None:
    """같은 기준·같은 입력 2회차 판정 일치율 — 채점기의 재현성.

    Why: LLM 채점의 신뢰도는 사람 대조 전에 자기 일관성부터다. 같은 입력에
    같은 답이 안 나오는 채점기는 무엇과 대조해도 의미가 없다.
    갈린 건은 곧 기준이 모호한 지점이므로 이름으로 남긴다.
    """
    denom = json.loads((IN_DIR / "denominator.json").read_text("utf-8"))["ids"]
    runs = []
    for d in (OUT2_DIR, OUT3_DIR):
        got = {}
        for p in sorted(d.glob("batch*.json")):
            for r in json.loads(p.read_text("utf-8")):
                got[r["id"]] = r
        runs.append(got)
    r2, r3 = runs

    missing = [i for i in denom if i not in r3]
    if missing:
        print(f"2회차 누락 {len(missing)}: {missing}")
        raise SystemExit(1)

    same = [i for i in denom if r2[i]["verdict"] == r3[i]["verdict"]]
    diff = [i for i in denom if r2[i]["verdict"] != r3[i]["verdict"]]
    print(f"1회차 통과 {sum(r2[i]['verdict'] for i in denom)}/{len(denom)}")
    print(f"2회차 통과 {sum(r3[i]['verdict'] for i in denom)}/{len(denom)}")
    print(f"판정 일치 {len(same)}/{len(denom)} ({len(same) / len(denom):.0%})")
    if diff:
        print(f"\n갈린 {len(diff)}건 — 기준이 모호한 지점:")
        for i in diff:
            print(f"  {i}: 1회차={r2[i]['verdict']} 2회차={r3[i]['verdict']}")
            print(f"    1회차 사유: {(r2[i].get('reason') or '')[:120]}")
            print(f"    2회차 사유: {(r3[i].get('reason') or '')[:120]}")
    else:
        print("\n전건 동일 — 재현성 확인")


def allruns() -> None:
    """v1(A/C 2항목) · v2 · v3(v2 재현) · v4(최소 기준) 판정 전체 대조.

    기준을 조일수록 통과가 줄었지만 그게 정확해진 것은 아니었다. 원문 검토에서
    v2가 깎은 5건 중 4건이 과잉으로 확인됐다. 이 표는 그 궤적을 남긴다.
    """
    denom = json.loads((IN_DIR / "denominator.json").read_text("utf-8"))["ids"]
    answers = {r["id"]: r for r in json.loads(ANSWERS.read_text("utf-8"))}

    def load(d: Path) -> dict:
        got = {}
        for p in sorted(d.glob("batch*.json")):
            for r in json.loads(p.read_text("utf-8")):
                got[r["id"]] = r
        return got

    v1, v2, v3, v4, v5 = (
        load(d) for d in (OUT_DIR, OUT2_DIR, OUT3_DIR, OUT4_DIR, OUT5_DIR)
    )
    missing = [i for i in denom if i not in v4 or i not in v5]
    bad = [
        i
        for run in (v4, v5)
        for i, r in run.items()
        if (r.get("evidence") or "").strip()
        and r["evidence"].strip() not in (answers[i].get("answer_text") or "")
    ]
    print(
        f"분모 {len(denom)} · v4 {len(v4)} · v5 {len(v5)} · 누락 {len(missing)} · 인용 불일치 {len(bad)}"
    )
    if missing or bad:
        print(f"  누락 {missing} / 인용 {bad}")

    def p1(i):
        r = v1[i]
        return int(r["A_direction"] == 1 and r["C_no_misassertion"] == 1)

    print(f"\n{'id':24} {'v1':>3} {'v2':>3} {'v3':>3} {'v4':>3} {'v5':>3}")
    for i in denom:
        row = (
            p1(i),
            v2[i]["verdict"],
            v3[i]["verdict"],
            v4.get(i, {}).get("verdict"),
            v5.get(i, {}).get("verdict"),
        )
        mark = "" if len(set(row)) == 1 else "   ←갈림"
        cells = " ".join(f"{str(x):>3}" for x in row)
        print(f"{i:24} {cells}{mark}")
    # v4·v5는 같은 기준 2회차 — 여기 일치율이 채점기의 재현성이다.
    agree = [
        i for i in denom if v4.get(i, {}).get("verdict") == v5.get(i, {}).get("verdict")
    ]
    print(
        f"\nv4 vs v5 재현성 {len(agree)}/{len(denom)} ({len(agree) / len(denom):.0%})"
    )
    for i in denom:
        if i not in agree:
            print(f"  갈림 {i}: v4={v4[i]['verdict']} v5={v5[i]['verdict']}")
            print(f"    v4: {(v4[i].get('reason') or '')[:110]}")
            print(f"    v5: {(v5[i].get('reason') or '')[:110]}")
    tot = len(denom)
    print(
        f"\n통과  v1 {sum(p1(i) for i in denom)}/{tot}"
        f"  v2 {sum(v2[i]['verdict'] for i in denom)}/{tot}"
        f"  v3 {sum(v3[i]['verdict'] for i in denom)}/{tot}"
        f"  v4 {sum(v4[i]['verdict'] for i in denom if i in v4)}/{tot}"
    )
    zeros = [i for i in denom if i in v4 and v4[i]["verdict"] == 0]
    print(f"\nv4 불합격 {len(zeros)}건:")
    for i in zeros:
        print(f"  {i}: {(v4[i].get('reason') or '')[:130]}")
    if missing or bad:
        raise SystemExit(1)


def build_sheet() -> None:
    shape = json.loads(SHAPE.read_text("utf-8"))
    answers = {r["id"]: r for r in json.loads(ANSWERS.read_text("utf-8"))}
    ts = C.testset_map()
    ids = pick(shape, "fixed", N_PER_KIND) + pick(shape, "branched", N_PER_KIND)

    L = [
        "# judge 검증용 사람 채점 시트",
        "",
        f"> 표본 {len(ids)}건 (확정형 {N_PER_KIND} · 분기형 {N_PER_KIND}).",
        f"> 답변 출처 `{ANSWERS.name}`. 유형 출처 `{SHAPE.name}`(LLM 1회 분류 — 틀렸으면 고쳐 적을 것).",
        "",
        "## 채점 방법",
        "",
        "각 항목에 `1`/`0`을 적는다. 판단이 애매하면 `?`로 두고 메모를 남긴다.",
        "",
        "| 항목 | 묻는 것 |",
        "| --- | --- |",
        "| A. 방향 | 정답과 같은 방향이 답변에 들어 있나 (확정이든 분기의 한 갈래든) |",
        "| B. 기준 | 분기라면 어느 갈래인지 가릴 기준이 제시됐나 (확정형이면 `-`) |",
        "| C. 오단정 | 오답 방향을 정답처럼 단정하지 **않았**나 (안 했으면 1) |",
        "",
        "마지막에 `종합`으로 이 답변이 사용자에게 쓸모 있었는지 1/0을 적는다.",
        "세 항목을 어떻게 합칠지는 아직 정하지 않았다 — 사람 종합 판정과 대조해서 정한다.",
        "",
        "---",
        "",
    ]
    for n, cid in enumerate(ids, 1):
        sh, a = shape[cid], answers.get(cid, {})
        L += [
            f"## {n}. {cid}",
            "",
            f"- 유형: **{sh['kind']}** · 축: {sh['axis']} · 갈래: {sh['options']}",
            "",
            "**질문**",
            "",
            (ts[cid]["question"] or "").strip(),
            "",
            "**정답 (질의회신 원문 결론)**",
            "",
            (a.get("answer_gold") or "").strip(),
            "",
            "**답변 (챗봇)**",
            "",
            (a.get("answer_text") or "(빈 답변)").strip(),
            "",
            "**채점**",
            "",
            "```",
            "A. 방향   : ",
            "B. 기준   : ",
            "C. 오단정 : ",
            "종합      : ",
            "메모      : ",
            "```",
            "",
            "---",
            "",
        ]
    SHEET.write_text("\n".join(L), encoding="utf-8")
    print(f"표본 {len(ids)}건 → {SHEET.name}")
    print(f"  확정형 {N_PER_KIND} · 분기형 {N_PER_KIND}")
    print(f"  답변 출처 {ANSWERS.name} (옛 파이프라인 — 판정 대상으로만 사용)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "cmd",
        choices=["sheet", "batch", "collect", "compare", "repro", "all"],
        help="batch: 입력 배치 / collect: v1 취합 / compare: v1vs v2 / repro: 재현성 / all: 전체 대조",
    )
    args = ap.parse_args()
    {
        "sheet": build_sheet,
        "batch": build_batches,
        "collect": collect,
        "compare": compare,
        "repro": repro,
        "all": allruns,
    }[args.cmd]()


if __name__ == "__main__":
    main()

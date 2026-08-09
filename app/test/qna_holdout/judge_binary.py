"""결론 채점 — 여러 회차의 답변을 v4 기준으로 이진 판정하고 집계한다.

기준 정본은 `docs/eval-v2/11-judge-design.md` §3 (v4). 재현성 95%·과잉감점 0으로
확정된 것이고, 여기 RUBRIC이 그 사본이다. **옛 조항("양쪽 다 가능하다고만 하면 0")은
폐기됐다** — 질의회신 원문 90건 중 41%가 조건부 분기라 챗봇에 확정을 요구하면 부당하다.

판정자는 Claude Code 서브에이전트다. 스크립트가 맡는 것은 재현 가능한 부분 전부다:
분모 고정 · 회차 은닉 · 배치 분할 · 취합 · census · 인용 검증 · 집계.

**회차를 숨긴다.** 나란히 보여주면 채점이 상대 비교로 변한다. 답변을 해시 순으로
섞고 라벨을 지운 뒤 판정받고, 집계할 때 스크립트가 되돌린다. 같은 케이스의 회차별
답변이 서로 다른 배치로 흩어지므로 판정이 서로 영향을 주지 않는다.

**분모는 gold 라벨이 정한다.** `scope: "excluded"` 케이스(1115호 밖이 정답이라 원리적
도달 불가)는 자동으로 빠진다 — 90건.

    # A/B 비교 (2회차)
    judge_binary.py batch --runs runs/run_none.json runs/run_kin1.json --tag ab
    # 반복 측정 (3회차)
    judge_binary.py batch --runs runs/run_none.json runs/run_none2.json \\
        runs/run_none3.json --tag r3 --per 30
    # 서브에이전트가 judge_<tag>_in/rubric.md 기준으로 채점 → judge_<tag>_out/
    judge_binary.py collect --tag r3
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import median

_HERE = Path(__file__).parent
_GOLD = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "testdata"
    / "gold_extract"
    / "gold_paragraphs.json"
)

RUBRIC = """# 결론 채점 기준 (v4)

`judge_*_in/batchN.json`의 각 항목을 아래 기준으로 판정해
`judge_*_out/batchN.json`에 같은 순서로 저장한다.

## 판정

verdict 1 또는 0. 답변이 정답과 같은 결론에 도달했는가.

- 1: 정답 결론이 답변에 있다. 확정으로 냈든 조건부 갈래의 하나로 냈든 상관없다.
- 0: 결론 방향이 정답과 다르다.
- 0: 갈래만 나열하고 어느 갈래인지 가릴 기준이 없다.
- 0: 답변을 거절했거나 답을 내지 않았다.

## 감점하지 않는 것

- 근거 조문이 정답과 달라도 결론이 같으면 1
- 표현이 달라도 같은 개념이면 1
- 정답이 1115호 밖 기준서(1021·1037·1109·1002·1038 등)에 근거한 내용을 담고 있다면,
  답변이 그 부분을 다루지 않았다고 감점하지 않는다 — 이 챗봇은 1115호만 검색한다
- 정답보다 설명이 짧거나 부수 내용을 생략한 것은 감점 사유가 아니다

판단이 반반이면 1로 둔다.

## 출력 형식

```json
[{"key": "<입력의 key 그대로>", "verdict": 0, "evidence": "...", "reason": "...", "note": ""}]
```

- `evidence`: 판정 근거가 된 **answer의 연속 substring을 글자 그대로**(마크다운 기호 포함),
  120자 이내. 창작 인용은 스크립트가 잡아낸다.
- `reason`: 한두 문장. 0이면 결론이 어떻게 다른지 구체적으로.
- `note`: 판단이 애매했으면 왜 애매했는지. 없으면 빈 문자열.

## 주의

각 항목이 어느 회차에서 나온 답변인지는 **의도적으로 숨겼다.** 항목 사이를 비교하지
말고 각각을 정답과만 대조한다.
"""


def _dirs(tag: str) -> tuple[Path, Path]:
    return _HERE / f"judge_{tag}_in", _HERE / f"judge_{tag}_out"


def _key(cid: str, cond: str) -> str:
    """회차를 숨긴 결정적 식별자. 정렬해도 회차가 섞이도록 해시를 쓴다."""
    return hashlib.sha1(f"{cid}|{cond}".encode()).hexdigest()[:12]


def _scored_ids() -> set[str]:
    """채점 분모 — gold 라벨에서 scope=excluded를 뺀 케이스."""
    gold = json.loads(_GOLD.read_text("utf-8"))
    return {c["id"] for c in gold if c.get("scope") != "excluded"}


def build(paths: list[Path], tag: str, per: int) -> None:
    in_dir, out_dir = _dirs(tag)
    runs = {
        p.stem: {r["id"]: r for r in json.loads(p.read_text("utf-8"))} for p in paths
    }
    conds = list(runs)

    ids = set.intersection(*(set(v) for v in runs.values())) & _scored_ids()
    dropped = set.union(*(set(v) for v in runs.values())) - ids
    ids = sorted(ids)
    if dropped:
        print(f"분모 제외 {len(dropped)}건: {sorted(dropped)}")

    rows, mapping = [], {}
    for cid in ids:
        for cond in conds:
            k = _key(cid, cond)
            mapping[k] = {"id": cid, "cond": cond}
            src = runs[cond][cid]
            rows.append(
                {
                    "key": k,
                    "question": (src.get("question") or "").strip(),
                    "answer_gold": (src.get("answer_gold") or "").strip(),
                    "answer": (src.get("answer_text") or "").strip(),
                }
            )
    rows.sort(key=lambda r: r["key"])  # 해시 순 = 회차가 섞인 순서

    in_dir.mkdir(exist_ok=True)
    out_dir.mkdir(exist_ok=True)
    for n in range(0, len(rows), per):
        (in_dir / f"batch{n // per + 1}.json").write_text(
            json.dumps(rows[n : n + per], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    (in_dir / "rubric.md").write_text(RUBRIC, encoding="utf-8")
    (in_dir / "denominator.json").write_text(
        json.dumps({"conds": conds, "map": mapping}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"케이스 {len(ids)} × {len(conds)}회차 = {len(rows)}건")
    print(f"배치 {(len(rows) + per - 1) // per}개 · {per}건씩 → {in_dir.name}/")
    print(f"분모·회차표 고정 → {in_dir.name}/denominator.json")


def collect(tag: str) -> None:
    in_dir, out_dir = _dirs(tag)
    d = json.loads((in_dir / "denominator.json").read_text("utf-8"))
    mapping, conds = d["map"], d["conds"]
    src = {
        r["key"]: r
        for p in sorted(in_dir.glob("batch*.json"))
        for r in json.loads(p.read_text("utf-8"))
    }
    got = {
        r["key"]: r
        for p in sorted(out_dir.glob("batch*.json"))
        for r in json.loads(p.read_text("utf-8"))
    }

    missing = sorted(set(mapping) - set(got))
    extra = sorted(set(got) - set(mapping))
    bad_v = [k for k, r in got.items() if r.get("verdict") not in (0, 1)]
    # 인용 환각 차단 — evidence는 answer의 연속 substring이어야 한다
    bad_q = [
        k
        for k, r in got.items()
        if (r.get("evidence") or "").strip()
        and r["evidence"].strip() not in (src.get(k, {}).get("answer") or "")
    ]
    print(
        f"분모 {len(mapping)} · 판정 {len(got)} · 누락 {len(missing)} · 초과 {len(extra)}"
    )
    print(f"verdict 형식 오류 {len(bad_v)} · 인용 원문 불일치 {len(bad_q)}")
    for label, xs in (
        ("누락", missing),
        ("초과", extra),
        ("형식", bad_v),
        ("인용", bad_q),
    ):
        if xs:
            print(f"  {label}: {xs[:8]}")
    if missing or extra or bad_v or bad_q:
        raise SystemExit(1)

    score: dict[str, dict[str, int]] = {}
    for k, m in mapping.items():
        score.setdefault(m["id"], {})[m["cond"]] = got[k]["verdict"]
    n = len(score)

    totals = {c: sum(v[c] for v in score.values()) for c in conds}
    print(f"\nN={n}")
    for c in conds:
        print(f"  {c:14} {totals[c]:>3}/{n} ({totals[c] / n:.1%})")
    vals = list(totals.values())
    if len(conds) > 2:
        print(
            f"  중앙값 {median(vals):.0f}/{n} ({median(vals) / n:.1%})  범위 {min(vals)}~{max(vals)}"
        )
        # 회차마다 갈린 케이스 — 파이프라인 비결정성의 실체
        split = sorted(i for i, v in score.items() if 0 < sum(v.values()) < len(conds))
        allfail = sorted(i for i, v in score.items() if sum(v.values()) == 0)
        print(f"  회차별로 갈린 케이스 {len(split)}건 {split}")
        print(f"  3회 모두 실패 {len(allfail)}건 {allfail}")
    elif len(conds) == 2:
        a, b = conds
        up = sorted(i for i, v in score.items() if v[b] > v[a])
        dn = sorted(i for i, v in score.items() if v[b] < v[a])
        print(
            f"  Δ={totals[b] - totals[a]:+d} · 개선 {len(up)}건 {up} · 악화 {len(dn)}건 {dn}"
        )
    notes = [(k, r["note"]) for k, r in got.items() if (r.get("note") or "").strip()]
    print(f"  애매 판정 {len(notes)}건")

    out = _HERE / f"judge_{tag}_scores.json"
    out.write_text(
        json.dumps({"conds": conds, "scores": score}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"→ {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    bp = sub.add_parser("batch")
    bp.add_argument("--runs", nargs="+", required=True, help="결과 파일 (_HERE 기준)")
    bp.add_argument("--tag", default="ab", help="산출 디렉터리 이름 judge_<tag>_in/out")
    bp.add_argument("--per", type=int, default=20, help="배치당 항목 수")
    cp = sub.add_parser("collect")
    cp.add_argument("--tag", default="ab")
    args = ap.parse_args()
    if args.cmd == "batch":
        build([_HERE / r for r in args.runs], args.tag, args.per)
    else:
        collect(args.tag)


if __name__ == "__main__":
    main()

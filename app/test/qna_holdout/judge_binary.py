"""결론 채점 A/B — 두 회차 답변을 v4 기준으로 이진 판정하고 차이를 낸다.

기준 정본은 `docs/eval-v2/11-judge-design.md` §3 (v4). 재현성 95%·과잉감점 0으로
확정된 것이고, 여기 RUBRIC이 그 사본이다. **옛 조항("양쪽 다 가능하다고만 하면 0")은
폐기됐다** — 질의회신 원문 90건 중 41%가 조건부 분기라 챗봇에 확정을 요구하면 부당하다.

판정자는 Claude Code 서브에이전트다. 스크립트가 맡는 것은 재현 가능한 부분 전부다:
분모 고정 · 조건 은닉 · 배치 분할 · 취합 · census · 인용 검증 · 집계.

**조건을 숨긴다.** A/B를 나란히 보여주면 채점이 상대 비교로 변한다. 두 회차 답변을
섞고 라벨을 지운 뒤 판정받고, 집계할 때 스크립트가 되돌린다.

    # 1) 배치 생성 (분모·기준 파일 고정)
    PYTHONPATH=. uv run python app/test/qna_holdout/judge_binary.py batch \\
        --a runs/run_none.json --b runs/run_kin1.json --per 20
    # 2) 서브에이전트가 judge_ab_in/rubric.md 기준으로 batchN.json 채점 → judge_ab_out/
    # 3) 취합·검증·집계
    PYTHONPATH=. uv run python app/test/qna_holdout/judge_binary.py collect
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

_HERE = Path(__file__).parent
IN_DIR = _HERE / "judge_ab_in"
OUT_DIR = _HERE / "judge_ab_out"

RUBRIC = """# 결론 채점 기준 (v4)

`judge_ab_in/batchN.json`의 각 항목을 아래 기준으로 판정해
`judge_ab_out/batchN.json`에 같은 순서로 저장한다.

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

각 항목이 어느 설정에서 나온 답변인지는 **의도적으로 숨겼다.** 항목 사이를 비교하지
말고 각각을 정답과만 대조한다.
"""


def _key(cid: str, cond: str) -> str:
    """조건을 숨긴 결정적 식별자. 정렬해도 A/B가 섞이도록 해시를 쓴다."""
    return hashlib.sha1(f"{cid}|{cond}".encode()).hexdigest()[:12]


def build(pa: Path, pb: Path, per: int) -> None:
    a = {r["id"]: r for r in json.loads(pa.read_text("utf-8"))}
    b = {r["id"]: r for r in json.loads(pb.read_text("utf-8"))}
    ids = sorted(set(a) & set(b))
    skipped = sorted((set(a) | set(b)) - set(ids))
    if skipped:
        print(f"한쪽에만 있는 케이스 {len(skipped)}건 제외: {skipped[:5]}")

    rows, mapping = [], {}
    for cid in ids:
        for cond, src in (("A", a), ("B", b)):
            k = _key(cid, cond)
            mapping[k] = {"id": cid, "cond": cond}
            rows.append(
                {
                    "key": k,
                    "question": (src[cid].get("question") or "").strip(),
                    "answer_gold": (src[cid].get("answer_gold") or "").strip(),
                    "answer": (src[cid].get("answer_text") or "").strip(),
                }
            )
    rows.sort(key=lambda r: r["key"])  # 해시 순 = 조건이 섞인 순서

    IN_DIR.mkdir(exist_ok=True)
    OUT_DIR.mkdir(exist_ok=True)
    for n in range(0, len(rows), per):
        p = IN_DIR / f"batch{n // per + 1}.json"
        p.write_text(
            json.dumps(rows[n : n + per], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    (IN_DIR / "rubric.md").write_text(RUBRIC, encoding="utf-8")
    (IN_DIR / "denominator.json").write_text(
        json.dumps(
            {"a_file": pa.name, "b_file": pb.name, "map": mapping},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"케이스 {len(ids)} × 2조건 = {len(rows)}건")
    print(f"배치 {(len(rows) + per - 1) // per}개 · {per}건씩 → {IN_DIR.name}/")
    print(f"분모·조건표 고정 → {IN_DIR.name}/denominator.json")


def collect() -> None:
    d = json.loads((IN_DIR / "denominator.json").read_text("utf-8"))
    mapping = d["map"]
    src = {}
    for p in sorted(IN_DIR.glob("batch*.json")):
        for r in json.loads(p.read_text("utf-8")):
            src[r["key"]] = r
    got: dict[str, dict] = {}
    for p in sorted(OUT_DIR.glob("batch*.json")):
        for r in json.loads(p.read_text("utf-8")):
            got[r["key"]] = r

    missing = sorted(set(mapping) - set(got))
    extra = sorted(set(got) - set(mapping))
    bad_v = [k for k, r in got.items() if r.get("verdict") not in (0, 1)]
    bad_q = [
        k
        for k, r in got.items()
        if (r.get("evidence") or "").strip()
        and (r["evidence"]).strip() not in (src.get(k, {}).get("answer") or "")
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
    sa = sum(v["A"] for v in score.values())
    sb = sum(v["B"] for v in score.values())
    up = sorted(i for i, v in score.items() if v["B"] > v["A"])
    dn = sorted(i for i, v in score.items() if v["B"] < v["A"])
    print(f"\nN={n}  (A={d['a_file']} · B={d['b_file']})")
    print(f"  A {sa}/{n} ({sa / n:.1%})")
    print(f"  B {sb}/{n} ({sb / n:.1%})   Δ={sb - sa:+d}")
    print(f"  A→B 개선 {len(up)}건 {up}")
    print(f"  A→B 악화 {len(dn)}건 {dn}")
    notes = [(k, r["note"]) for k, r in got.items() if (r.get("note") or "").strip()]
    print(f"  애매 판정 {len(notes)}건")
    out = _HERE / "judge_ab_scores.json"
    out.write_text(
        json.dumps(
            {"a_file": d["a_file"], "b_file": d["b_file"], "scores": score},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"→ {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    bp = sub.add_parser("batch")
    bp.add_argument("--a", required=True, help="A 결과 파일 (_HERE 기준 상대경로)")
    bp.add_argument("--b", required=True, help="B 결과 파일")
    bp.add_argument("--per", type=int, default=20, help="배치당 항목 수")
    sub.add_parser("collect")
    args = ap.parse_args()
    if args.cmd == "batch":
        build(_HERE / args.a, _HERE / args.b, args.per)
    else:
        collect()


if __name__ == "__main__":
    main()

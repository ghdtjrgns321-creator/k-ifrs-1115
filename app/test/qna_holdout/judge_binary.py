"""이진 결론 채점 — 답변이 gold와 같은 방향의 결론에 도달했는가만 본다.

부분점수(3축 rubric) 폐기 이유: 헤지 답변의 branch 축을 채점자마다 2 vs 0으로
달리 매겨 성적이 ±14까지 흔들렸다(8_TEST-DECISIONS.md). QNA에는 확정 정답이
있으므로 방향 대조 이진이면 충분하다.

두 결과 파일을 **같은 채점기·같은 호출**로 나란히 채점한다. 기록된 80/92는
다른 채점 회차의 값이라 직접 비교하면 채점자 차이가 섞이므로, A/B를 동시에
재채점해 통제한다.

실행:
  PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/judge_binary.py \
      --a results_treeA_via_topic.json --b results.json --out binscores_treeA_vs_B.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from app.agents import _front_model

_HERE = Path(__file__).parent
CONCURRENCY = 6

SYSTEM = """너는 K-IFRS 제1115호 회계기준 답변의 채점자다.
[정답]은 질의회신 원문이 내린 확정 결론이다. [답변]이 그 결론과 **같은 방향**에
도달했는지만 판정한다.

판정 규칙:
- 결론 방향이 정답과 같으면 1, 다르거나 결론을 내지 않았으면 0.
- 문단 번호 인용 여부·설명 분량·서술 순서는 채점하지 않는다.
- 정답이 조건부 분기(예: A면 X, B면 Y)면, 답변이 같은 분기 구조를 제시하면 1.
- 답변이 양쪽 다 가능하다고만 하고 정답 방향을 특정하지 못하면 0.
- reason은 한국어 두 문장 이내로 근거를 쓴다."""


class Verdict(BaseModel):
    match: int = Field(ge=0, le=1, description="정답 결론과 같은 방향이면 1, 아니면 0")
    reason: str


judge = Agent(_front_model(), output_type=Verdict, system_prompt=SYSTEM)


def _prompt(case: dict, answer: str) -> str:
    return (
        f"[질문]\n{case['question']}\n\n"
        f"[정답]\n{case['answer_gold']}\n\n"
        f"[답변]\n{answer or '(빈 답변)'}"
    )


async def _score(sem: asyncio.Semaphore, case: dict, answer: str) -> Verdict:
    async with sem:
        try:
            r = await judge.run(_prompt(case, answer))
            return r.output
        except Exception as e:
            return Verdict(match=0, reason=f"채점 실패: {type(e).__name__}: {e}")


async def main_async(pa: Path, pb: Path, out: Path) -> None:
    a = {r["id"]: r for r in json.loads(pa.read_text(encoding="utf-8"))}
    b = {r["id"]: r for r in json.loads(pb.read_text(encoding="utf-8"))}
    ids = [i for i in a if i in b]
    missing = (set(a) | set(b)) - set(ids)
    if missing:
        print(f"양쪽에 없는 케이스 {len(missing)}건 제외: {sorted(missing)[:5]}")

    sem = asyncio.Semaphore(CONCURRENCY)
    va, vb = await asyncio.gather(
        asyncio.gather(*(_score(sem, a[i], a[i]["answer_text"]) for i in ids)),
        asyncio.gather(*(_score(sem, b[i], b[i]["answer_text"]) for i in ids)),
    )

    rows = [
        {
            "id": i,
            "title": a[i]["title"],
            "A": x.match,
            "B": y.match,
            "reason_A": x.reason,
            "reason_B": y.reason,
        }
        for i, x, y in zip(ids, va, vb)
    ]
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    n = len(rows)
    sa = sum(r["A"] for r in rows)
    sb = sum(r["B"] for r in rows)
    flip_up = [r["id"] for r in rows if r["B"] > r["A"]]
    flip_dn = [r["id"] for r in rows if r["B"] < r["A"]]
    print(f"\n동일 채점기 · N={n}")
    print(f"  A ({pa.name}) : {sa}/{n} ({sa / n:.1%})")
    print(f"  B ({pb.name}) : {sb}/{n} ({sb / n:.1%})   Δ={sb - sa:+d}")
    print(f"  A→B 개선 {len(flip_up)}건 {flip_up}")
    print(f"  A→B 악화 {len(flip_dn)}건 {flip_dn}")
    print(f"→ {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="기준 결과 파일명(_HERE 기준)")
    ap.add_argument("--b", required=True, help="비교 결과 파일명(_HERE 기준)")
    ap.add_argument("--out", default="binscores_ab.json")
    args = ap.parse_args()
    asyncio.run(main_async(_HERE / args.a, _HERE / args.b, _HERE / args.out))


if __name__ == "__main__":
    main()

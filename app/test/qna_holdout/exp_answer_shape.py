"""정답(answer_gold)이 확정형인가 분기형인가 — 채점 기준 설계용 사전 분류.

왜 필요했나(2026-07): 그때 judge_binary는 "정답 방향을 특정하지 못하면 0"으로
채점했다. 그런데 질의회신 원문 자체가 조건부 분기로 끝나는 케이스가 있다. 원문이
확정하지 않는데 답변에 확정을 요구하면 부당하게 0이 된다. 그 케이스가 몇 건인지
세어 채점 기준 변경의 크기를 확인했고(90건 중 37건 = 41%), 그 결과로 그 조항이
폐기됐다(v4 · docs/eval-v2/11-judge-design.md).

분류는 표본 선정용이라 1회만 돌린다(판정이 아니라 층화 추출의 입력).
사람이 검수할 수 있게 원문 인용(evidence)을 함께 남긴다.

실행: PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/exp_answer_shape.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from app.agents import _front_model
from app.test.qna_holdout import exp_common as C

_HERE = Path(__file__).parent
OUT = _HERE / "answer_shape.json"
CONCURRENCY = 6

SYSTEM = """너는 K-IFRS 제1115호 질의회신 원문의 **결론 형태**를 분류한다.
답변의 옳고 그름이 아니라 결론이 어떤 모양인지만 본다.

- fixed(확정형): 원문이 하나의 결론을 확정한다. 예 "한 시점에 이행하는 수행의무다"
- branched(분기형): 원문이 조건에 따라 갈리는 결론을 제시한다.
  예 "고객이 종료할 수 있는 기간에는 A, 없는 기간에는 B"

주의:
- 설명이 길거나 여러 문단을 인용한다고 분기형이 아니다. **결론이 갈리는지**만 본다.
- 판단 요소를 나열했더라도 최종 결론이 하나면 fixed다.
- axis는 결론이 답하는 축을 짧은 명사구로 쓴다. 예 "수익 인식 시점", "본인/대리인"
- options는 결론의 갈래를 짧게 나열한다. fixed면 1개.
- evidence는 판단 근거가 된 원문 구절을 **그대로** 따온다(창작 금지, 40자 내외)."""


class Shape(BaseModel):
    kind: str = Field(description="fixed 또는 branched")
    axis: str = Field(description="결론이 답하는 축 (짧은 명사구)")
    options: list[str] = Field(description="결론 갈래. fixed면 1개")
    evidence: str = Field(description="원문에서 그대로 따온 근거 구절")


agent = Agent(_front_model(), output_type=Shape, system_prompt=SYSTEM)


async def _one(sem: asyncio.Semaphore, cid: str, case: dict) -> tuple:
    async with sem:
        r = await agent.run(
            f"[질문]\n{case['question']}\n\n[질의회신 결론]\n{case['answer_gold']}"
        )
        return cid, r.output.model_dump()


async def main_async() -> None:
    ts = C.testset_map()
    # 결론 재현 분모 90건 — gold 문단 유무와 무관하다(문단 없는 18건도 결론은 채점).
    excluded = {
        x["id"]
        for x in C.load_json(C.GOLD)
        if x.get("scope") or x.get("exclude_reason")
    }
    ids = sorted(i for i in ts if i not in excluded)
    print(f"분류 대상 {len(ids)}건 (전체 {len(ts)} − 제외 {len(excluded)})")

    sem = asyncio.Semaphore(CONCURRENCY)
    pairs = await asyncio.gather(*(_one(sem, i, ts[i]) for i in ids))
    got = dict(pairs)
    OUT.write_text(json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8")

    fixed = [i for i, v in got.items() if v["kind"] == "fixed"]
    branched = [i for i, v in got.items() if v["kind"] == "branched"]
    print(f"\nfixed(확정형)   {len(fixed)}건")
    print(f"branched(분기형) {len(branched)}건")
    other = [i for i, v in got.items() if v["kind"] not in ("fixed", "branched")]
    if other:
        print(f"미분류 {len(other)}건: {other}")
    print("\n분기형 예시 (사람 검수용)")
    for i in branched[:5]:
        v = got[i]
        print(f"  {i} · {v['axis']} · {v['options']}")
        print(f"    근거: {v['evidence'][:70]}")
    print(f"\n저장 → {OUT.name}")


if __name__ == "__main__":
    asyncio.run(main_async())

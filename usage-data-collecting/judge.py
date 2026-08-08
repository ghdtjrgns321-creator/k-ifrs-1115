"""L2 LLM 판정 — 근거충족 하나만. 정답 없이 채점한다.

설계: docs/quality-loop/02-scoring.md §4

  판정 A 근거충족 — 답변이 준 문단 원문을 벗어났는가 (폐쇄형 대조)

Why(자료충분 판정 폐기 · ADR-47): "이 문단들로 답할 수 있나"를 묻는 판정을 뒀다가
뺐다. ① 신뢰도를 재려면 정답이 필요한데, 정답이 있는 셋에서는 이미 검증된 결론
채점기 v4(재현성 95% · docs/eval-v2/11-judge-design.md)를 쓰면 된다 — 즉 이 판정만
검증 경로가 없다. ② 실측 3건에서 1/3만 통과시켜 짜게 매기는 쪽으로 의심되는데
확인할 방법이 없다. ③ 빼도 루프는 돈다 — L1(오판 0) + 근거충족 + 사람 피드백으로
제안이 나온다. 근거 없는 신호를 쌓아두지 않는다.

근거충족만 남긴 이유: 답변과 함께 준 문단만 대조하는 폐쇄형이라 채점자의 외부 지식이
개입하지 않는다. "지어냈는가"는 자료 안에서 판정된다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from app.agents import _front_model

GROUNDED_SYSTEM = """너는 회계 답변이 제시된 근거를 벗어났는지 검사하는 검사관이다.
[문단]은 답변 작성에 실제로 주어진 기준서 원문 전부다.

판정 규칙:
- 답변의 사실 주장이 모두 [문단] 안에서 확인되면 grounded=1.
- [문단]에 없는 내용을 사실처럼 단정한 문장이 하나라도 있으면 grounded=0.
- 일반적 상식·용어 풀이·"추가 검토가 필요하다" 같은 유보 표현은 위반이 아니다.
- unsupported에는 위반 문장을 원문 그대로 옮긴다(없으면 빈 배열).
- 너의 회계 지식으로 답변이 옳은지는 판정하지 않는다. 오직 [문단] 대조만 한다.
- reason은 한국어 두 문장 이내."""


class Grounded(BaseModel):
    grounded: int = Field(
        ge=0, le=1, description="답변이 문단 범위를 벗어나지 않으면 1"
    )
    unsupported: list[str] = Field(default_factory=list, description="근거 없는 문장")
    reason: str


grounded_agent = Agent(
    _front_model(), output_type=Grounded, system_prompt=GROUNDED_SYSTEM
)


async def judge_grounded(answer: str, para_text: str) -> Grounded:
    prompt = f"[문단]\n{para_text}\n\n[답변]\n{answer or '(빈 답변)'}"
    return (await grounded_agent.run(prompt)).output

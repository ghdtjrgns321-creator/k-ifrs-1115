"""STEP 2 제안 초안 — "이 용어를 어느 개념에 연결하나"만 LLM에게 묻는다.

설계: docs/quality-loop/03-proposals-gate.md

**용어를 뽑는 일은 LLM에게 묻지 않는다.** 진입부가 이미 답을 준다 — analyze가 용어
목록에서 고른 값 중 사전에 없던 것이 `unknown_terms`로 로그에 남는다. 즉 "AI가
필요하다고 판단했는데 사전에 없는 말"이 결정적으로 확보된다. 여기서 남는 판단은
그 용어를 어느 기준서 개념에 걸지 하나뿐이다.

그래서 프롬프트는 창의성이 아니라 **범위 제한**에 집중한다 — 그래프에 없는 개념 id를
만들지 못하게 막는다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from app.agents import _front_model
from app.domain.graph import get_graph

LINK_SYSTEM = """너는 회계 검색 시스템의 용어사전을 보강하는 사서다.
용어사전은 **실무에서 쓰는 말 → K-IFRS 제1115호 개념**을 잇는 번역표다
(예: CIF → 한 시점에 이행하는 수행의무 · 본인 대 대리인의 고려사항).

[용어]는 AI가 이 질문에 필요하다고 판단했지만 사전에 없어서 버려진 말이다.
할 일: 이 용어를 [개념목록]의 개념 id에 연결한다.

규칙:
- concept_ids는 [개념목록]의 id만 쓴다. 목록에 없는 id는 절대 만들지 않는다.
- 그 용어가 실무에서 가리키는 거래의 **직접 쟁점 개념만** 고른다. 개수 제한은 없다.
  사람이 만든 기존 사전 285건은 개념 **1개가 46% · 2개가 27%**다 — 대부분 한둘이다.
  넓게 담지 않는다. 사전 한 줄이 그 용어가 나오는 모든 질문의 검색을 바꾼다.
- 그 용어가 회계 개념이 아니거나(회사명·일반 명사), 1115호와 무관하거나,
  어느 개념에 걸지 모호하면 **빈 배열**을 반환한다. 억지로 채우지 않는다.
- why는 한국어 한 문장. "이 용어가 가리키는 거래가 무엇이고 왜 그 개념인가"."""


class TermLink(BaseModel):
    concept_ids: list[str] = Field(default_factory=list, description="개념 id만")
    why: str = ""


link_agent = Agent(_front_model(), output_type=TermLink, system_prompt=LINK_SYSTEM)


def concept_catalog() -> str:
    """연결 가능한 개념 목록. 그래프가 유일한 출처."""
    g = get_graph()
    return "\n".join(f"- {cid}: {node['title']}" for cid, node in g.concepts.items())


async def link_term(term: str, question: str, catalog: str) -> TermLink:
    prompt = (
        f"[용어]\n{term}\n\n[이 용어가 나온 질문]\n{question}\n\n[개념목록]\n{catalog}"
    )
    return (await link_agent.run(prompt)).output

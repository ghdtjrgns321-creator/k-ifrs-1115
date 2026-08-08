"""온톨로지 STEP 7: 사례 '주제' 간선 — 인용했다와 쟁점이다를 분리한다

사용법:
  PYTHONPATH=. uv run --env-file .env python app/preprocessing/21-ontology-case-topics.py
  (--limit N 으로 소량 시범 · 이미 처리한 사례는 건너뛴다)

Why: case_links.json의 링크는 "이 사례가 이 문단을 인용했다"는 출처 표시인데,
     순회가 그것을 "이 사례는 이 쟁점을 다룬다"로 쓰고 있었다. 링크 323개 중 54%가
     문단 하나 근거이고, 사례당 배정 개념이 2.94개인데 실제 쟁점은 1.68개다
     (dev/entry-traverse/results-traverse.md). 인용 간선은 근거 표시로 남기고,
     순회는 여기서 만드는 주제 간선만 탄다.

Why(울타리): 후보를 그 사례가 인용한 문단의 개념으로 닫는다. 산출물이 항상 기존
     링크의 부분집합이라 없던 링크를 만들 수 없다 — 검증이 구조적으로 보장된다.

Why(IE는 AI 판정을 안 쓴다): IE는 **기준서가 직접 쓴 예시**이고, 어느 절에 넣을지도
     저자가 편성했다(IE 목차 level-2 → ie-group-concept-map.json, 사용자 21/21 승인).
     그건 1차 자료이고 AI 판정은 그 위의 추정이다. 실제로 AI 판정을 돌렸더니
     **`라이선싱` 개념에 걸린 IE가 8건 → 0건**이 됐다 — 라이선싱 사례들이 라이선싱
     문단(B52~B63B)을 인용하지 않아 울타리에 후보가 없었기 때문이다. 상세도 차이
     (그룹이 부모, 실제 쟁점이 자식인 16건)는 순회의 개념 넓히기가 흡수한다.
     근거: dev/entry-traverse/results-traverse.md §17.

Why(별도 파일): 16-ontology-cases.py가 case_links.json을 통째로 덮어쓴다. 거기에
     필드를 얹으면 재생성 시 소실된다(aliases.json에서 겪은 함정).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from app.config import settings
from app.domain.graph_fetch import fetch_case
from app.prompts import CASE_TOPIC_SYSTEM, CASE_TOPIC_USER

ONT = Path("data/ontology")
CONCEPTS_PATH = ONT / "concepts.json"
CASES_PATH = ONT / "case_links.json"
OUTPUT_PATH = ONT / "case_topics.json"
MAX_BODY = 6000  # QNA parent 최대 11,623자 — 앞부분에 질의요지·회신이 온다


class TopicPick(BaseModel):
    concept_ids: list[str] = Field(description="후보 목록에 있는 개념 id만")
    reason: str = Field(description="왜 그 쟁점인지 한 문장")


agent = Agent(
    GoogleModel(
        settings.llm_generate_model,
        provider=GoogleProvider(api_key=settings.google_api_key),
    ),
    output_type=TopicPick,
    retries=2,
    system_prompt=CASE_TOPIC_SYSTEM,
    model_settings={"google_thinking_config": {"thinking_level": "medium"}},
)


def fence_of(case: dict, p2c: dict) -> list[str]:
    """후보 개념 = 그 사례가 인용한 문단의 관할 개념 + concepts 직결 필드(6건).

    QNA·감리 전용이다. IE는 판정을 하지 않으므로 울타리가 필요 없다.
    """
    hit = {p2c[p] for p in case.get("paras", []) if p in p2c}
    return sorted(hit | set(case.get("concepts", [])))


def body_of(case: dict) -> str:
    text = (fetch_case(case["db_parent_id"]) or {}).get("content") or ""
    return f"\n[사례 전문]\n{text[:MAX_BODY]}\n" if text.strip() else ""


def pick(case: dict, fence: list[str], titles: dict) -> tuple[list, str]:
    cands = "\n".join(f"- {cid} : {titles[cid]['title']}" for cid in fence)
    r = agent.run_sync(
        CASE_TOPIC_USER.format(title=case["title"], body=body_of(case), cands=cands)
    ).output
    got = [c for c in r.concept_ids if c in fence]
    # 울타리 밖만 답했거나 빈 답 — 판정 실패다. 임의로 좁히지 않고 울타리를 그대로 둔다.
    return (got or fence), r.reason


def main() -> None:
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    concepts = json.loads(CONCEPTS_PATH.read_text("utf-8"))
    p2c, titles = concepts["para_to_concept"], concepts["concepts"]
    links = json.loads(CASES_PATH.read_text("utf-8"))

    done = (
        json.loads(OUTPUT_PATH.read_text("utf-8")).get("topics", {})
        if OUTPUT_PATH.exists()
        else {}
    )
    out: dict[str, dict] = dict(done)
    stats = {"auto": 0, "llm": 0, "ie_group": 0, "empty": 0, "skip": 0, "cached": 0}
    n = 0

    # ── IE: 기준서 목차가 편성한 절을 그대로 쓴다 (LLM 판정 없음) ──────────
    # 캐시를 타지 않는다 — 결정적이고 공짜이며, 옛 LLM 판정본을 덮어써야 한다.
    for case in links["ie"]:
        cid = case.get("concept")
        if not cid:
            stats["empty"] += 1
            continue
        out[case["id"]] = {
            "kind": "ie",
            "title": case["title"],
            "topics": [cid],
            "fence": [cid],
            "method": "ie_group",
            "reason": f"기준서 IE 목차 '{case.get('group', '')}' 절 (사용자 승인 21/21)",
        }
        stats["ie_group"] += 1

    # ── QNA·감리: 인용 문단을 울타리로 두고 AI가 쟁점을 고른다 ────────────
    for kind in ("qna", "findings"):
        for case in links[kind]:
            key = case["db_parent_id"]
            if key in out:
                stats["cached"] += 1
                continue
            if limit and n >= limit:
                stats["skip"] += 1
                continue
            fence = fence_of(case, p2c)
            if not fence:
                stats["empty"] += 1
                continue
            if len(fence) == 1:
                topics, reason, method = fence, "(울타리 1개 · 자동)", "auto"
                stats["auto"] += 1
            else:
                topics, reason = pick(case, fence, titles)
                method = "llm"
                stats["llm"] += 1
                n += 1
                print(f"  {stats['llm']:>3} {kind:8} {case['title'][:34]}", end="\r")
            out[key] = {
                "kind": kind,
                "title": case["title"],
                "topics": topics,
                "fence": fence,
                "method": method,
                "reason": reason,
            }
    print(" " * 70, end="\r")

    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "_meta": {
                    "generated_by": "app/preprocessing/21-ontology-case-topics.py",
                    "model": settings.llm_generate_model,
                    "prompt": "app/prompts.py CASE_TOPIC_SYSTEM/USER (게이트 통과본, 수정 금지)",
                    "gate": "홀드아웃 72건 · 제목만 94.4% · 전문 100% · 자동방식 83.3%",
                    "ie": "IE는 AI 판정을 쓰지 않는다 — 기준서 목차 편성이 1차 자료",
                    "stats": stats,
                },
                "topics": out,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    total = sum(len(links[k]) for k in ("qna", "findings", "ie"))
    per = sum(len(v["topics"]) for v in out.values()) / max(1, len(out))
    print(
        f"{stats}\n{len(out)}/{total}건 기록 · 사례당 주제 {per:.2f}개 → {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()

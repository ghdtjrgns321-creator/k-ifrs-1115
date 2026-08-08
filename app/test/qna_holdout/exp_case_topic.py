"""2-0 게이트 — 사례의 '핵심 주제' 간선을 AI로 뽑을 수 있나.

홀드아웃 72건은 gold 문단(사람이 회신문 답변에서 추출)이 있어 자기 쟁점 개념을 안다.
AI 판정을 여기에 1회 돌려 자동 방식(B1 최다 인용)의 83%를 넘는지 본다.

**프롬프트는 재기 전에 확정한다.** 점수를 보고 고치면 이 홀드아웃으로 재는 것이
무의미해진다(results-entry.md §8과 같은 이유). 1회 측정으로 종료.

두 조건을 각 1회씩 돌린다 — 어느 쪽도 사후에 고르지 않는다.
  title  : 제목만. gold와 출처가 겹치지 않아 **하한**
  full   : 제목 + 회신문 전문. gold가 이 텍스트에서 추출됐으므로 **상한**
감리·IE의 실제 성적은 두 값 사이에 있다고 본다.

    PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/exp_case_topic.py
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from app.config import settings
from app.domain.graph_fetch import fetch_case
from app.prompts import CASE_TOPIC_SYSTEM, CASE_TOPIC_USER
from app.test.qna_holdout import exp_common as EC

HERE = Path(__file__).parent
ONT = Path(__file__).resolve().parents[3] / "data" / "ontology"
OUT = HERE / "case_topic.json"
MAX_BODY = 6000  # QNA parent 최대 11,623자 — 앞부분에 질의요지·회신이 온다

# 프롬프트 정본은 app/prompts.py — 측정 당시 문자열과 바이트 동일함을 확인하고 옮겼다.
SYSTEM, USER = CASE_TOPIC_SYSTEM, CASE_TOPIC_USER


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
    system_prompt=SYSTEM,
    model_settings={"google_thinking_config": {"thinking_level": "medium"}},
)


def load() -> tuple[list, dict]:
    """(홀드아웃 행, 개념 사전). 행 = (case_id, 사례, gold개념, 울타리)."""
    concepts = json.loads((ONT / "concepts.json").read_text("utf-8"))
    p2c = concepts["para_to_concept"]
    links = json.loads((ONT / "case_links.json").read_text("utf-8"))
    qmap = {x["db_parent_id"]: x for x in links["qna"]}
    rows = []
    for cid, recs in EC.gold_cases().items():
        case = qmap.get(re.sub(r"-Q\d+$", "", cid))
        if not case:
            continue
        gold = {
            p2c[EC.norm_para(r["para"])]
            for r in recs
            if r.get("essential") and EC.norm_para(r["para"]) in p2c
        }
        fence = {p2c[p] for p in case.get("paras", []) if p in p2c} | set(
            case.get("concepts", [])
        )
        if gold and fence:
            rows.append((cid, case, gold, fence))
    return rows, concepts["concepts"]


def argmax(case: dict, p2c: dict) -> set[str]:
    """B1 — 인용 문단이 가장 많이 몰린 개념. 임계 없음."""
    cnt = Counter(p2c[p] for p in case.get("paras", []) if p in p2c)
    if not cnt:
        return set(case.get("concepts", []))
    top = max(cnt.values())
    return {k for k, v in cnt.items() if v == top}


def ask(case: dict, fence: set[str], titles: dict, with_body: bool) -> tuple[set, str]:
    body = ""
    if with_body:
        doc = fetch_case(case["db_parent_id"]) or {}
        body = f"\n[사례 전문]\n{(doc.get('content') or '')[:MAX_BODY]}\n"
    cands = "\n".join(f"- {cid} : {titles[cid]['title']}" for cid in sorted(fence))
    r = agent.run_sync(USER.format(title=case["title"], body=body, cands=cands)).output
    picked = {c for c in r.concept_ids if c in fence}
    return picked, r.reason


def score(name: str, picks: dict, rows: list) -> dict:
    hit = full = total = outside = 0
    for cid, _case, gold, _fence in rows:
        s = picks[cid]
        hit += bool(gold & s)
        full += gold <= s
        total += len(s)
        outside += len(s - gold)
    n = len(rows)
    r = {
        "name": name,
        "hit": hit,
        "hit_pct": round(hit / n * 100, 1),
        "full": full,
        "per_case": round(total / n, 2),
        "outside": outside,
        "outside_pct": round(outside / max(1, total) * 100, 1),
    }
    print(
        f"{name:14} 적중 {hit}/{n} = {r['hit_pct']:>5}%  · 전부 {full:>2}"
        f"  · 사례당 {r['per_case']:>4}  · 쟁점 밖 {outside}/{total} = {r['outside_pct']}%"
    )
    return r


def main() -> None:
    rows, titles = load()
    p2c = json.loads((ONT / "concepts.json").read_text("utf-8"))["para_to_concept"]
    need = [r for r in rows if len(r[3]) >= 2]
    print(f"홀드아웃 {len(rows)}건 · 울타리 2개 이상(판정 필요) {len(need)}건\n")

    base_a = {cid: set(fence) for cid, _c, _g, fence in rows}
    base_b1 = {cid: argmax(case, p2c) for cid, case, _g, _f in rows}

    results, detail = {}, {}
    results["A_인용전부"] = score("A 인용전부", base_a, rows)
    results["B1_최다인용"] = score("B1 최다인용", base_b1, rows)

    for cond in ("title", "full"):
        picks, reasons = {}, {}
        for i, (cid, case, _gold, fence) in enumerate(rows, 1):
            if len(fence) < 2:  # 선택지 하나 — 판정 없이 확정
                picks[cid] = set(fence)
                continue
            picks[cid], reasons[cid] = ask(case, fence, titles, cond == "full")
            print(f"  [{cond}] {i}/{len(rows)} {case['title'][:24]}", end="\r")
        print(" " * 70, end="\r")
        results[f"AI_{cond}"] = score(f"AI {cond}", picks, rows)
        detail[cond] = {
            cid: {
                "title": case["title"],
                "gold": sorted(gold),
                "fence": sorted(fence),
                "pick": sorted(picks[cid]),
                "reason": reasons.get(cid, "(울타리 1개 · 자동)"),
            }
            for cid, case, gold, fence in rows
        }

    bar = results["B1_최다인용"]["hit_pct"]
    print(f"\n합격선(B1) {bar}%")
    for k in ("AI_title", "AI_full"):
        v = results[k]["hit_pct"]
        print(f"  {k:10} {v}%  {'통과' if v >= bar else '미달'}")
    OUT.write_text(
        json.dumps(
            {"summary": results, "detail": detail}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()

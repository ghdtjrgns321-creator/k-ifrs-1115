"""진입 ablation용 경량 캡처 — analyze_agent만 호출한다(retrieve·generate 없음).

ablation이 필요로 하는 건 LLM이 만든 두 값뿐이다.
  term_hints       → LLM 용어 선택 통로의 입력
  standalone_query → 글자매칭 통로의 입력

capture.py는 run_rag_pipeline 전체를 돌려 generate까지 호출하므로 회당 비용이
수십 배다. 진입만 재는 데 답변 생성은 필요 없다.

회차를 나누는 이유: LLM 경유 통로는 회차마다 흔들린다(옛 구조 실측 3회 완전 동일
11/57). 같은 회차 안에서는 모든 조합이 같은 입력을 보므로 조합 비교는 공정하고,
회차를 여러 번 떠서 판정 방향이 일치하는지 본다.

**출력이 entry_capture_v2.json인 이유**: entry_capture.json은 옛 프롬프트(35개 토픽
목록) 기준 3회차이고 baseline 142/143/144의 입력이다. 프롬프트가 용어 목록으로
바뀐 지금 같은 파일에 덮으면 비교 기준선을 잃는다. 옛 파일은 읽기 전용으로 둔다.

실행:
  PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/exp_entry_capture.py --round 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.agents import analyze_agent
from app.test.qna_holdout import exp_common as C

_HERE = Path(__file__).parent
OUT = _HERE / "entry_capture_v2.json"
CONCURRENCY = 6  # gpt-4.1-mini RPM 여유. 올리면 429 위험


async def _capture_one(sem: asyncio.Semaphore, cid: str, question: str) -> tuple:
    """analyze_agent 1회. 프롬프트 형식은 analyze_query와 동일해야 한다.

    analyze_query(app/nodes/analyze.py:53)가 messages를 "role: content"로 엮어
    "최신 대화 기록 및 질문: ..."에 넣는다. 홀드아웃은 단일 턴이라 human 1줄.
    """
    async with sem:
        result = await analyze_agent.run(f"최신 대화 기록 및 질문: human: {question}")
        d = result.output
        return cid, {
            "routing": d.routing,
            "standalone_query": d.standalone_query,
            "term_hints": list(d.term_hints or []),
        }


async def capture_round(ids: list[str], ts: dict) -> dict:
    sem = asyncio.Semaphore(CONCURRENCY)
    pairs = await asyncio.gather(
        *(_capture_one(sem, i, ts[i]["question"]) for i in ids)
    )
    return dict(pairs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True, help="회차 번호(1,2,3…)")
    ap.add_argument("--limit", type=int, default=0, help="스모크용 — 앞 N건만")
    args = ap.parse_args()

    ts = C.testset_map()
    ids = sorted(C.gold_cases())  # 1115호 gold 문단 보유 72건
    if args.limit:
        ids = ids[: args.limit]
    print(f"캡처 대상 {len(ids)}건 · 회차 {args.round}")

    data = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {"rounds": {}}
    got = asyncio.run(capture_round(ids, ts))

    # 회차 덮어쓰기는 허용 — 실패 회차를 다시 뜨는 게 정상 경로다.
    data["rounds"][str(args.round)] = got
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    # 미등재 = LLM이 답했지만 사전에 없는 말. 사전 보강 대상이자, 지시문("목록에
    # 글자 그대로 있는 값만")을 LLM이 지키는지 보는 지표다.
    from app.domain.graph import get_graph

    g = get_graph()
    hint0 = [i for i, v in got.items() if not v["term_hints"]]
    out_r = [i for i, v in got.items() if v["routing"] != "IN"]
    picks = [len(v["term_hints"]) for v in got.values()]
    unknown: dict[str, int] = {}
    for v in got.values():
        for t in g.concepts_of_terms(v["term_hints"])[1]:
            unknown[t] = unknown.get(t, 0) + 1
    print(f"저장 {OUT.name} · 회차 {sorted(data['rounds'])}")
    print(f"  term_hints 0개: {len(hint0)}건 {hint0[:5]}")
    print(f"  routing != IN : {len(out_r)}건 {out_r[:5]}")
    print(f"  용어 선택 개수: 평균 {sum(picks) / len(picks):.1f} · 최대 {max(picks)}")
    print(f"  사전 미등재 답변: {sum(unknown.values())}회 · 고유 {len(unknown)}종")
    for t, n in sorted(unknown.items(), key=lambda kv: -kv[1])[:10]:
        print(f"    {n:>3}  {t}")


if __name__ == "__main__":
    main()

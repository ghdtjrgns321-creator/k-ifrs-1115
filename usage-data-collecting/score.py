"""STEP 1 채점 배치 — usage_logs → L1 자동 점검 + L2 이진 판정 → scored_logs.

설계: docs/quality-loop/02-scoring.md
답변 경로에는 아무것도 추가하지 않는다(오프라인 전용).

실행:
  PYTHONPATH=. uv run --env-file .env python usage-data-collecting/score.py --limit 50
  PYTHONPATH=. uv run --env-file .env python usage-data-collecting/score.py --skip-l2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from flags import (  # noqa: E402
    SCORABLE_FLOW,
    is_followup,
    is_unreliable,
    l1_flags,
    l1_observations,
    suspect_layer,
)
from judge import judge_grounded  # noqa: E402

from app.domain.graph_fetch import fetch_para  # noqa: E402
from app.services.usage_logger import SCHEMA_VER, _get_collection  # noqa: E402

_HERE = Path(__file__).parent
CONCURRENCY = 6  # judge_binary.py와 동일
# 프롬프트 크기 가드. 초과분은 잘리며, 잘린 건은 para_text_truncated로 표시한다
# (조용한 절단 금지 — 판정 신뢰도에 영향이 있으므로 결과에 남긴다).
PARA_TEXT_MAX = 40_000


@lru_cache(maxsize=2048)
def _para_text(para_num: str) -> str:
    d = fetch_para(para_num)
    if not d:
        return ""
    body = d.get("text") or d.get("content") or d.get("fullContent") or ""
    return f"[문단 {para_num}] {body}"


def build_para_text(paras: list[str]) -> tuple[str, bool]:
    """문단 번호 목록 → 원문 블록. (텍스트, 절단여부)"""
    blocks: list[str] = []
    total = 0
    for p in paras:
        t = _para_text(p)
        if not t:
            continue
        if total + len(t) > PARA_TEXT_MAX:
            return "\n\n".join(blocks), True
        blocks.append(t)
        total += len(t)
    return "\n\n".join(blocks), False


def followup_map(logs_col, logs: list[dict]) -> dict[str, dict]:
    """로그 id → 같은 세션에서 바로 다음에 온 질문 로그.

    Why 컬렉션 전체를 다시 묻나: 후속 질문이 `--limit`으로 자른 배치 안에 있으리란
    보장이 없다. 배치 범위만 보면 재질문이 조용히 0건이 된다.
    """
    sids = {lg.get("session_id") for lg in logs if lg.get("session_id")}
    if not sids:
        return {}
    proj = {"session_id": 1, "timestamp": 1, "flow": 1, "question": 1}
    by_session: dict[str, list[dict]] = defaultdict(list)
    cur = logs_col.find({"session_id": {"$in": list(sids)}}, proj).sort("timestamp", 1)
    for d in cur:
        by_session[d["session_id"]].append(d)

    nxt: dict[str, dict] = {}
    for docs in by_session.values():
        for this, following in zip(docs, docs[1:]):
            nxt[str(this["_id"])] = following
    return nxt


async def score_one(
    sem: asyncio.Semaphore, log: dict, skip_l2: bool, next_log: dict | None = None
) -> dict:
    flags = l1_flags(log)
    observations = l1_observations(log)
    entry = log.get("entry") or {}
    followup = (
        {"question": next_log.get("question", ""), "log_id": str(next_log["_id"])}
        if next_log and is_followup(log, next_log)
        else None
    )
    row = {
        "log_id": str(log["_id"]),
        # schema_ver: 채점 결과에도 남긴다 — 진입부가 바뀌면 옛 채점 결과가 제안
        # 단계로 흘러들어 없는 이상을 만들어낸다(실측: 구버전 1건 혼입).
        "schema_ver": log.get("schema_ver", 0),
        "question": log.get("question", ""),
        "outcome": log.get("outcome", "ok"),
        "flow": log.get("flow"),
        "flags": flags,
        # observations: 이상은 아니지만 사전·지시문 보강 후보
        "observations": observations,
        # unknown_terms: LLM이 답했지만 사전에 없던 말 — STEP 2 사전 제안의 입력 그 자체
        "unknown_terms": entry.get("unknown_terms") or [],
        # term_hints: LLM이 목록에서 고른 용어 원본 (승인 화면 표시용)
        "term_hints": entry.get("term_hints") or [],
        "suspect_layer": suspect_layer(flags, observations),
        "unreliable": is_unreliable(log),
        # human: 정답이 없는 실사용 로그에서 정답을 대신하는 유일한 것 — 사용자 행동.
        # 기록만 하지 않고 제안 대기열의 진입 조건으로 쓴다(03 문서 §3).
        "human": {
            "feedback": log.get("feedback"),
            "reason": log.get("feedback_reason", ""),
            "followup": followup,
        },
        "verdict_a": None,
    }
    context_paras = (log.get("retrieval") or {}).get("context_paras") or []
    if (
        skip_l2
        or row["outcome"] != "ok"
        or log.get("flow") != SCORABLE_FLOW
        or not context_paras
    ):
        return row

    text, truncated = await asyncio.to_thread(build_para_text, context_paras)
    row["para_text_truncated"] = truncated
    async with sem:
        try:
            a = await judge_grounded(log.get("answer", ""), text)
            row["verdict_a"] = a.model_dump()
        except Exception as exc:  # 채점 실패는 0점이 아니라 미채점으로 남긴다
            row["judge_error"] = f"{type(exc).__name__}: {exc}"
    return row


async def main_async(args) -> None:
    logs_col = _get_collection()
    query: dict = {"schema_ver": {"$gte": SCHEMA_VER}}
    if args.since:
        query["timestamp"] = {
            "$gte": datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
        }
    logs = list(logs_col.find(query).sort("timestamp", -1).limit(args.limit))
    if not logs:
        print(
            f"채점 대상 없음 (schema_ver>={SCHEMA_VER}). STEP 0 이후 로그가 필요합니다."
        )
        return

    nxt = followup_map(logs_col, logs)
    sem = asyncio.Semaphore(CONCURRENCY)
    rows = await asyncio.gather(
        *(score_one(sem, lg, args.skip_l2, nxt.get(str(lg["_id"]))) for lg in logs)
    )

    out = _HERE / args.out
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    scored_col = logs_col.database["scored_logs"]
    for r in rows:
        scored_col.update_one(
            {"log_id": r["log_id"]},
            {"$set": {**r, "scored_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    _report(rows)
    print(f"→ {out} · scored_logs {len(rows)}건 upsert")


def _report(rows: list[dict]) -> None:
    n = len(rows)
    flow = Counter(r["flow"] for r in rows)
    failed = [r for r in rows if r["outcome"] != "ok"]
    ok = [r for r in rows if r["outcome"] == "ok"]
    flagged = [r for r in ok if r["flags"]]
    fc = Counter(f for r in ok for f in r["flags"])
    judged = [r for r in rows if r["verdict_a"]]
    print(f"\n대상 {n}건 · flow {dict(flow)}")
    print(f"응답 실패 {len(failed)}/{n} (점검 대상 아님)")
    print(f"L1 점검 이상 {len(flagged)}/{len(ok)}")
    for f, c in fc.most_common():
        print(f"    {f:18s} {c}")
    oc = Counter(o for r in ok for o in (r.get("observations") or []))
    if oc:
        print(f"L1 보강 후보 {sum(oc.values())}건 (이상 아님)")
        for o, c in oc.most_common():
            print(f"    {o:18s} {c}")
    if judged:
        ga = sum(r["verdict_a"]["grounded"] for r in judged)
        print(f"L2 근거충족 {ga}/{len(judged)} (채점 {len(judged)}/{n})")
    down = [r for r in rows if (r["human"] or {}).get("feedback") == "down"]
    fup = [r for r in rows if (r["human"] or {}).get("followup")]
    print(f"L3 사람 신호 — 👎 {len(down)}건 · 재질문 {len(fup)}건")
    err = [r for r in rows if r.get("judge_error")]
    if err:
        print(f"채점 실패 {len(err)}건 (미채점 처리)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="ISO 날짜 (예 2026-08-01)")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--skip-l2", action="store_true", help="LLM 판정 없이 L1만")
    ap.add_argument("--out", default="scored.json")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()

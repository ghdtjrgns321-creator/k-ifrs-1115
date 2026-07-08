"""STEP 0/1/4 계측용 인프로세스 캡처 러너.

run.py(SSE 서버 경유)와 달리 run_rag_pipeline을 직접 호출해 서버 없이 실행하고,
버킷 분류·개념 재현율 측정에 필요한 진입/회수 내부 상태를 케이스별로 남긴다.

  - routing / topic_hints / via_topic / concept_ids : 진입(analyze) 내부
  - retrieved_paras : 회수된 문단 번호(A/D 버킷 구분의 핵심)
  - resp_cited / gold_cited / answer_text : 결론 프레임 판정용

QNA-off(홀드아웃 조건)를 맞추기 위해 import 전에 EXCLUDE_QNA=1을 강제한다.

실행:
  PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/capture.py --cases QNA-SSI-38676
  PYTHONPATH=. uv run --env-file .env python app/test/qna_holdout/capture.py --failed --out capture_step0.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

os.environ.setdefault("EXCLUDE_QNA", "1")  # 홀드아웃 조건: QNA 순환 격리

_HERE = Path(__file__).parent
TESTSET = Path(__file__).resolve().parents[3] / "data" / "testdata" / "qna_testset.json"

# report.md 미재현 14건 (STEP 0 버킷 대상)
FAILED_14 = [
    "QNA-2017-I-KQA014",
    "QNA-2020-I-KQA006-Q2",
    "QNA-202003D",
    "QNA-2021-I-KQA008",
    "QNA-2022-I-KQA007",
    "QNA-SSI-202503008",
    "QNA-SSI-202511018",
    "QNA-SSI-35565",
    "QNA-SSI-35567",
    "QNA-SSI-38648",
    "QNA-SSI-38673",
    "QNA-SSI-38675",
    "QNA-SSI-38676",
    "QNA-SSI-38680",
]

_PARA_RE = re.compile(r"문단\s*([0-9]+[A-Z]?|B[0-9]+[A-Z]?)")


def _norm_para(raw: str) -> str:
    """'문단 92' / '92' / '1115-92' → '92' 로 정규화(비교 키)."""
    s = str(raw).strip()
    s = s.replace("문단", "").strip()
    if "-" in s:  # '1115-92' 류 접두 제거
        s = s.split("-")[-1]
    return s


def _extract_paras(docs: list[dict] | None) -> list[str]:
    """회수 문서의 paraNum/chunk_id(본문 문단번호)를 추출(중복 제거, 순서 보존).

    본문 문단은 paraNum에 번호가 담김. 사례/IE는 paraNum이 비어 hierarchy 정규식 폴백.
    """
    seen: dict[str, None] = {}
    for d in docs or []:
        raw = d.get("paraNum") or d.get("chunk_id") or ""
        if raw:
            seen.setdefault(_norm_para(raw), None)
        else:  # 사례/부록 등 paraNum 없는 문서는 hierarchy에서 '문단 N' 폴백
            blob = f"{d.get('hierarchy', '')}"
            for m in _PARA_RE.findall(blob):
                seen.setdefault(_norm_para(m), None)
    seen.pop("", None)
    return list(seen)


def _doc_sample(docs: list[dict] | None, n: int = 8) -> list[dict]:
    """형식 검증용 원시 식별자 샘플."""
    return [
        {
            "source": d.get("source"),
            "paraNum": d.get("paraNum"),
            "chunk_id": d.get("chunk_id"),
            "hierarchy": d.get("hierarchy", "")[:60],
        }
        for d in (docs or [])[:n]
    ]


async def _run_one(case: dict) -> dict:
    from app.services.chat_service import _build_initial_state
    from app.pipeline import run_rag_pipeline

    state = _build_initial_state(
        session_id=f"cap-{case['id']}",
        prev_messages=[],
        new_message=case["question"],
    )
    err = None
    try:
        async for _ in run_rag_pipeline(state):
            pass
    except Exception as e:  # 한 건 실패가 전체 중단 금지
        err = f"{type(e).__name__}: {e}"

    docs = state.get("relevant_docs") or []
    return {
        "id": case["id"],
        "title": case.get("title", ""),
        "routing": state.get("routing", ""),
        "topic_hints": state.get("topic_hints", []),
        "via_topic": state.get("via_topic", []),
        "concept_ids": state.get("concept_ids", []),
        "retrieved_paras": _extract_paras(docs),
        "retrieved_count": len(docs),
        "doc_sample": _doc_sample(docs),
        "resp_cited": state.get("cited_paragraphs", []),
        "gold_cited": case.get("cited_paragraphs", []),
        "answer_text": state.get("answer", ""),
        "error": err,
    }


async def _main(case_ids: list[str], out: str) -> None:
    cases = {c["id"]: c for c in json.loads(TESTSET.read_text(encoding="utf-8"))}
    rows = []
    for cid in case_ids:
        c = cases.get(cid)
        if c is None:
            print(f"  [MISS] {cid} testset에 없음")
            continue
        print(f"  [{cid}] ...", end="", flush=True)
        row = await _run_one(c)
        rows.append(row)
        status = "ERROR" if row["error"] else "OK"
        print(f" {status} routing={row['routing']} paras={len(row['retrieved_paras'])}")

    out_path = _HERE / out
    out_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    errs = [r["id"] for r in rows if r["error"]]
    print(f"\n완료 {len(rows)}건, 에러 {len(errs)}건 {errs or ''}\n→ {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=str, default="", help="쉼표구분 id")
    ap.add_argument("--failed", action="store_true", help="미재현 14건")
    ap.add_argument("--out", type=str, default="capture.json")
    args = ap.parse_args()
    if args.failed:
        ids = FAILED_14
    else:
        ids = [x.strip() for x in args.cases.split(",") if x.strip()]
    if not ids:
        ap.error("--cases 또는 --failed 필요")
    asyncio.run(_main(ids, args.out))


if __name__ == "__main__":
    main()

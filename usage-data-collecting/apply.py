"""STEP 3 반영 — 승인된 제안을 파일에 적용하고 게이트를 건다. 커밋은 하지 않는다.

설계: docs/quality-loop/03-proposals-gate.md §6

세 단계로 나눈 이유: 게이트가 둘인데 성격이 다르다.
  ① census      — 스크립트가 즉시 돌린다 (결정적, 초 단위)
  ② 홀드아웃 회귀 — 파이프라인 전량 재실행이 필요해 이 스크립트가 대신 돌릴 수 없다
그래서 ①까지 자동으로 확인하고 작업 트리에 올려둔(staged) 뒤, ②는 개발자가 돌리고
그 결과 파일을 근거로 confirm한다. "게이트를 통과해야 반영"을 지키면서 거짓 통과를
만들지 않는 유일한 방법이다.

실행:
  PYTHONPATH=. uv run python usage-data-collecting/apply.py stage
  PYTHONPATH=. uv run python usage-data-collecting/apply.py confirm --evidence <회귀결과.json>
  PYTHONPATH=. uv run python usage-data-collecting/apply.py rollback
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.domain.graph import get_graph  # noqa: E402

_HERE = Path(__file__).parent
_ROOT = _HERE.parent
ALIASES = _ROOT / "data" / "ontology" / "aliases.json"
BACKUP = _HERE / "aliases.before-loop.json"
CENSUS = _ROOT / "app" / "preprocessing" / "20-ontology-census.py"
PROPOSALS = _HERE / "proposals.json"

# 실제 파일을 고칠 수 있는 action. 나머지는 보고 전용이라 반영 대상이 아니다.
APPLICABLE = {"add_alias"}

# 홀드아웃 A/B는 3단계다(배치 생성 → 서브에이전트 채점 → 취합). 스크립트가 대신
# 돌릴 수 없는 이유가 2단계에 있다. 기준 정본은 docs/eval-v2/11-judge-design.md §3(v4).
HOLDOUT_CMD = """1) 변경 전/후 답변 회차를 각각 만든다 (app/test/qna_holdout/run.py)
  2) 배치 생성:
       PYTHONPATH=. uv run python app/test/qna_holdout/judge_binary.py batch \\
           --a <변경전.json> --b <변경후.json> --per 20
  3) 서브에이전트가 judge_ab_in/rubric.md 기준으로 채점 → judge_ab_out/
  4) 취합:
       PYTHONPATH=. uv run python app/test/qna_holdout/judge_binary.py collect
     → app/test/qna_holdout/judge_ab_scores.json (악화 건수는 출력의 "A→B 악화")"""
# confirm의 근거로 받을 파일
HOLDOUT_EVIDENCE = _ROOT / "app" / "test" / "qna_holdout" / "judge_ab_scores.json"


def _load() -> list[dict]:
    if not PROPOSALS.exists():
        print(f"{PROPOSALS} 없음 — propose.py를 먼저 실행하세요.")
        sys.exit(1)
    return json.loads(PROPOSALS.read_text(encoding="utf-8"))


def _save(proposals: list[dict]) -> None:
    PROPOSALS.write_text(
        json.dumps(proposals, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _entry(p: dict) -> dict:
    """aliases.json 스키마에 맞는 항목. 출처를 남겨 루프 산출물임을 추적 가능하게 한다."""
    g = get_graph()
    cids = p["change"]["concept_ids"]
    return {
        "term": p["change"]["term"],
        "sources": ["quality-loop"],
        "grade": "품질루프(사람 승인)",
        "concepts": [g.concepts[c]["title"] for c in cids if c in g.concepts],
        "concept_ids": cids,
        "cases": [],
        "note": f"품질 루프 제안 {p['id']} — 사람 승인",
        "decision": {
            "by": f"quality-loop {p['id']} · 사람 승인",
            "reason": p.get("why", ""),
            "log_ids": (p.get("evidence") or {}).get("log_ids", []),
            "at": _now(),
        },
    }


def _census() -> bool:
    print("① census 실행...")
    r = subprocess.run(
        ["uv", "run", "python", str(CENSUS)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
    )
    tail = (r.stdout or r.stderr).strip().splitlines()[-3:]
    for ln in tail:
        print(f"   {ln}")
    print(f"   exit={r.returncode}")
    return r.returncode == 0


def _restore() -> bool:
    if not BACKUP.exists():
        return False
    shutil.copy2(BACKUP, ALIASES)
    BACKUP.unlink()
    return True


def cmd_stage(_args) -> None:
    proposals = _load()
    approved = [p for p in proposals if p.get("status") == "approved"]
    if not approved:
        print(
            "승인된 제안이 없습니다. proposals.md를 읽고 status를 approved로 바꾸세요."
        )
        return
    if BACKUP.exists():
        print(f"이미 staged 상태입니다({BACKUP.name}). confirm 또는 rollback 먼저.")
        return

    targets = [p for p in approved if p["action"] in APPLICABLE]
    skipped = [p for p in approved if p["action"] not in APPLICABLE]
    for p in skipped:
        print(f"  건너뜀 [{p['id']}] {p['action']} — 보고 전용(사람이 직접 수정)")
    if not targets:
        print("반영 가능한 제안이 없습니다.")
        return

    shutil.copy2(ALIASES, BACKUP)
    data = json.loads(ALIASES.read_text(encoding="utf-8"))
    existing = {t["term"] for t in data["terms"]}
    added = []
    for p in targets:
        term = p["change"]["term"]
        if term in existing:
            print(f"  건너뜀 [{p['id']}] '{term}' — 이미 사전에 있음")
            continue
        data["terms"].append(_entry(p))
        existing.add(term)
        added.append(p)
        print(f"  추가 [{p['id']}] '{term}' → {p['change']['concept_ids']}")
    if not added:
        _restore()
        print("추가된 항목이 없어 원상복구했습니다.")
        return
    ALIASES.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    if not _census():
        _restore()
        for p in added:
            p["status"] = "rolled_back"
            p["gate"] = {"census": "fail", "at": _now()}
        _save(proposals)
        print("\n❌ census 실패 → 원상복구했습니다. 반영하지 않았습니다.")
        return

    for p in added:
        p["status"] = "staged"
        p["gate"] = {"census": "pass", "holdout": "미실행", "at": _now()}
    _save(proposals)
    print(f"\n✅ census 통과 · {len(added)}건을 작업 트리에 올렸습니다(커밋 안 함).")
    print(
        "\n② 홀드아웃 회귀는 이 스크립트가 대신 돌릴 수 없습니다(채점자가 서브에이전트)."
    )
    print(f"\n  {HOLDOUT_CMD}\n")
    print("  악화 0건이면:  apply.py confirm       (근거 기본값 judge_ab_scores.json)")
    print("  악화가 있으면: apply.py rollback")


def cmd_confirm(args) -> None:
    proposals = _load()
    staged = [p for p in proposals if p.get("status") == "staged"]
    if not staged:
        print("staged 상태인 제안이 없습니다.")
        return
    ev = Path(args.evidence)
    if not ev.exists():
        print(f"회귀 결과 파일이 없습니다: {ev}")
        print("게이트 ②의 근거 없이 confirm할 수 없습니다.")
        return
    for p in staged:
        p["status"] = "applied"
        p["gate"] = {
            **(p.get("gate") or {}),
            "holdout": "pass(사람 확인)",
            "holdout_evidence": str(ev),
            "at": _now(),
        }
    _save(proposals)
    if BACKUP.exists():
        BACKUP.unlink()
    print(f"✅ {len(staged)}건 반영 확정. 근거: {ev}")
    print("커밋은 하지 않았습니다 — git diff로 확인 후 직접 커밋하세요.")


def cmd_rollback(_args) -> None:
    proposals = _load()
    staged = [p for p in proposals if p.get("status") == "staged"]
    if not _restore():
        print("복구할 백업이 없습니다.")
        return
    for p in staged:
        p["status"] = "rolled_back"
        p["gate"] = {**(p.get("gate") or {}), "holdout": "fail", "at": _now()}
    _save(proposals)
    print(f"↩ 원상복구했습니다. {len(staged)}건을 rolled_back으로 기록.")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stage")
    c = sub.add_parser("confirm")
    c.add_argument(
        "--evidence",
        default=str(HOLDOUT_EVIDENCE),
        help=f"홀드아웃 A/B 취합 결과 (기본 {HOLDOUT_EVIDENCE.name})",
    )
    sub.add_parser("rollback")
    args = ap.parse_args()
    {"stage": cmd_stage, "confirm": cmd_confirm, "rollback": cmd_rollback}[args.cmd](
        args
    )


if __name__ == "__main__":
    main()

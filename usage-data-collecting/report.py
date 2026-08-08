"""STEP 3 개발자 리포트 — proposals.json → proposals.md. 읽기 전용, UI 없음.

설계: docs/quality-loop/03-proposals-gate.md §5
챗봇 UI에는 아무것도 붙이지 않는다. 개발자만 보는 파일이다.

승인 방법: 이 리포트를 읽고 `proposals.json`에서 해당 제안의 `status`를
"pending" → "approved"(반영) 또는 "rejected"(거절)로 바꾼다. 그 뒤 apply.py 실행.

실행: PYTHONPATH=. uv run python usage-data-collecting/report.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from flags import HUMAN_TEXT  # noqa: E402

from app.domain.graph import get_graph  # noqa: E402

_HERE = Path(__file__).parent

LAYER_NAME = {
    1: "1층 용어사전",
    2: "2층 용어 지목 지시문",
    3: "3층 답변 생성 지시문",
    4: "4층 노드·간선 (기준서 원문 파생)",
}

WARN_L4 = """> ⚠️ **기준서 원문에서 기계로 추출한 관계입니다.**
>
> - `edges.json`의 문단 상호참조는 원문의 "문단 XX에 따라" 표기를 정규식으로 뽑은 것입니다.
>   손으로 넣은 간선은 전처리 재실행(`15-ontology-edges.py`) 때 사라집니다.
> - `judgment_trees.json`에는 "기준서 본문 원문 추출 · AI 창작 아님"이 명시돼 있습니다.
> - `20-ontology-census.py`가 원문 대비 누락 0을 이미 증명한 영역입니다.
>
> 승인 전에 근거 문단 번호를 직접 확인하십시오."""


def _concept_titles(cids: list[str]) -> str:
    g = get_graph()
    return " · ".join(
        f"{g.concepts[c]['title']}(`{c}`)" for c in cids if c in g.concepts
    )


SIGNAL_NAME = {"down": "👎 나쁨 표시", "followup": "같은 세션 재질문"}


def _trace_rows(c: dict) -> list[str]:
    """진입 → 수집 → 인용을 한 화면에 편다. 어느 단계에서 틀어졌는지 사람이 본다."""
    e, r = c["entry"], c["retrieval"]
    paths = [
        f"LLM 선택 {e['via_llm']}" if e["via_llm"] else "",
        f"글자매칭 {e['matched_terms']}" if e["matched_terms"] else "",
        f"임베딩 {e['via_embed']}" if e["via_embed"] else "",
    ]
    return [
        "| 단계 | 무엇이 남았나 |",
        "|---|---|",
        f"| 진입 | 개념 {len(e['concept_ids'])}개 — "
        f"{' · '.join(p for p in paths if p) or '**아무 통로도 못 냄**'} |",
        f"| 진입(버린 말) | {e['unknown_terms'] or '—'} |",
        f"| 수집 | 원문 {r['doc_count']}건 · 컨텍스트 문단 {len(r['context_paras'])}개 "
        f"{r['context_paras'][:12]}{' …' if len(r['context_paras']) > 12 else ''} |",
        f"| 인용 | {c['cited_paragraphs'] or '**인용 0건**'} |",
        f"| 근거 경로 | {' → '.join(r['concept_path']) if r['concept_path'] else '—'} |",
    ]


def _feedback_one(i: int, c: dict) -> list[str]:
    L = [
        f"### [F-{i}] {SIGNAL_NAME.get(c['signal'], c['signal'])} — {c['question']}",
        "",
    ]
    if c.get("reason"):
        L += [f"**사용자 사유**: {c['reason']}", ""]
    if c.get("followup_question"):
        L += [f"**이어서 물은 것**: {c['followup_question']}", ""]

    sigs = (c["flags"] or []) + (c["observations"] or [])
    if sigs:
        L.append("**코드가 잡은 것**")
        L += [f"- {HUMAN_TEXT.get(s, s)}" for s in sigs]
    else:
        L.append(
            "**코드가 잡은 것**: 없음 — 사람은 나쁘다는데 자동 점검은 통과했다. "
            "지금 루프가 못 보는 실패다."
        )
    L.append("")
    if c.get("grounded") == 0:
        L += ["**근거충족(L2)**: 준 문단 밖에서 답했다", ""]

    L += _trace_rows(c)
    L += [
        "",
        f"<details><summary>답변 전문</summary>\n\n{c['answer']}\n\n</details>",
        "",
        f"`log_id` {c['log_id']}",
        "",
        "---",
        "",
    ]
    return L


def _feedback_block(cases: list[dict]) -> list[str]:
    if not cases:
        return []
    blind = [c for c in cases if not c["flags"] and not c["observations"]]
    return [
        f"## 사람이 나쁘다고 한 답변 — {len(cases)}건",
        "",
        f"> 그중 **코드로는 이상 없음 {len(blind)}건**. 승인 대상이 아니라 "
        "개발자가 읽고 직접 손볼 원자료다 — 층 추정은 코드 신호가 있을 때만 붙였다.",
        "",
        "---",
        "",
    ] + [line for i, c in enumerate(cases, 1) for line in _feedback_one(i, c)]


def _one(p: dict) -> list[str]:
    L = [
        f"### [{p['id']}] {LAYER_NAME.get(p['layer'], p['layer'])} — `{p['action']}`",
        "",
    ]
    if p["layer"] == 4:
        L += [WARN_L4, ""]

    ev = p.get("evidence") or {}
    items = ev.get("flags") or []
    L.append("**무슨 일이 있었나**")
    for it in items:
        L.append(f"- {HUMAN_TEXT.get(it, it)}")
    L.append("")

    qs = ev.get("questions") or []
    if qs:
        L.append("**어떤 질문에서**")
        L += [f"- {q}" for q in qs]
        L.append("")

    chg = p.get("change")
    if chg:
        L.append("**바꾸면**")
        L.append("")
        L.append("```")
        L.append(f'용어사전에 추가:  "{chg["term"]}"')
        L.append(f"연결할 개념:      {_concept_titles(chg['concept_ids'])}")
        L.append("```")
    else:
        L.append(f"**볼 곳**: {p.get('target', '—')} — 변경안은 사람이 정한다")
    L.append("")

    imp = p.get("impact") or {}
    bits = [f"근거 로그 {imp.get('affected_logs', 0)}건"]
    if "literal_hits" in imp:
        bits.append(
            f"글자매칭으로 곧바로 걸리는 과거 질문 {imp['literal_hits']}건(하한)"
        )
    col = imp.get("term_collision") or []
    bits.append(f"용어 충돌 {len(col)}건" + (f" — {col}" if col else ""))
    L.append(f"**영향 범위**: {' · '.join(bits)}")
    L.append("")
    if p.get("why"):
        L.append(f"**판단 근거**: {p['why']}")
        L.append("")
    L.append(f"<details><summary>로그 id {len(ev.get('log_ids') or [])}건</summary>\n")
    L.append("```")
    L += ev.get("log_ids") or []
    L.append("```")
    L.append("</details>")
    L.append("")
    L.append(
        f"**승인**: `proposals.json`에서 `{p['id']}`의 `status`를 `approved` / `rejected`로"
    )
    L.append("")
    L.append("---")
    L.append("")
    return L


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="proposals.json")
    ap.add_argument("--feedback", default="feedback.json")
    ap.add_argument("--out", default="proposals.md")
    args = ap.parse_args()

    src = _HERE / args.src
    if not src.exists():
        print(f"{src} 없음 — propose.py를 먼저 실행하세요.")
        return
    proposals = json.loads(src.read_text(encoding="utf-8"))

    fb_src = _HERE / args.feedback
    cases = json.loads(fb_src.read_text(encoding="utf-8")) if fb_src.exists() else []
    if not proposals and not cases:
        print("제안·사람 신호 0건 — 리포트를 쓰지 않았습니다.")
        return

    pending = [p for p in proposals if p.get("status") == "pending"]
    L = [
        "# 품질 루프 — 개발자 검토용",
        "",
        f"> 사람 신호 **{len(cases)}건** · 제안 **{len(proposals)}건**"
        f"(검토 대기 {len(pending)}건) · 챗봇 UI에는 노출되지 않는다 · 점수는 없다",
        "",
        "---",
        "",
    ]
    # 사람 신호를 맨 위에 둔다 — 정답이 없는 실사용 로그에서 실패를 말해주는 건
    # 사용자 행동뿐이고, 코드 신호는 그 뒤에 "어디서"를 말한다(02 문서 §3).
    L += _feedback_block(cases)

    if proposals:
        L += [
            "## 제안",
            "",
            "| id | 층 | action | 근거 로그 | 상태 |",
            "|---|---|---|---|---|",
        ]
        for p in proposals:
            L.append(
                f"| {p['id']} | {p['layer']} | `{p['action']}` | "
                f"{(p.get('impact') or {}).get('affected_logs', 0)} | {p.get('status')} |"
            )
        L += ["", "---", ""]
        for p in sorted(proposals, key=lambda x: (x["layer"], x["id"])):
            L += _one(p)

    out = _HERE / args.out
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(
        f"사람 신호 {len(cases)}건 · 제안 {len(proposals)}건 (대기 {len(pending)}) → {out}"
    )


if __name__ == "__main__":
    main()

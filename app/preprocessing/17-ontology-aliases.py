"""온톨로지 STEP 4: 용어 사전 초안 — 사람이 만든 1차 자료 3원천에서 생성

사용법:
  PYTHONPATH=. uv run python app/preprocessing/17-ontology-aliases.py

Why: 용어(실무 언어)는 일상어 질문과 개념·사례를 잇는 결정적 진입점.
     원천은 ①query-mapping 288(기존 용어→확장키워드) ②QNA·감리 제목 123
     ③부록A 공식 정의 9 — 전부 사람이 만든 자료이며 AI 신규 창작 용어 0건.
     개념 목적지 매핑만 기계 초안(제목 문자열 일치) + 사용자 검수로 확정.
     (설계: docs/ontology/00-overview.md 결정 4, HANDOFF.md)
"""

import difflib
import json
import re
from pathlib import Path

MAPPING_PATH = Path("data/web/query-mapping-generated.json")
CASES_PATH = Path("data/ontology/case_links.json")
DEFS_PATH = Path("data/web/kifrs-1115-definitions.json")
CONCEPTS_PATH = Path("data/ontology/concepts.json")
OUTPUT_PATH = Path("data/ontology/aliases.draft.json")


def match_concepts(candidates: list[str], titles: list[str]) -> list[str]:
    """후보 문자열들을 개념 제목과 대조 — 부분 포함(3자+) 또는 difflib 0.8+."""
    hits: list[str] = []
    for cand in candidates:
        c = cand.strip()
        if len(c) < 3:
            continue
        for t in titles:
            if (c in t or t in c) and t not in hits:
                hits.append(t)
        for t in difflib.get_close_matches(c, titles, n=2, cutoff=0.8):
            if t not in hits:
                hits.append(t)
        # 토큰 규칙: 조사(과/와/의 등) 차이 흡수 — "본인과 대리인" ↔ "본인 대 대리인의 고려사항"
        # 다중 토큰 후보의 모든 핵심 토큰(2자+)이 제목에 포함되면 매칭
        tokens = [re.sub(r"(과|와|의|을|를|은|는|이|가)$", "", w) for w in c.split()]
        tokens = [w for w in tokens if len(w) >= 2]
        if len(tokens) >= 2:
            for t in titles:
                if t not in hits and all(w in t for w in tokens):
                    hits.append(t)
    return hits


def main():
    cj = json.loads(CONCEPTS_PATH.read_text(encoding="utf-8"))
    concepts = cj["concepts"]
    p2c = cj["para_to_concept"]
    titles = [v["title"] for v in concepts.values()]
    t2id = {v["title"]: k for k, v in concepts.items()}

    rows: dict[str, dict] = {}  # term(정규화) → row

    def add(term, source, grade, concepts_hit=None, case=None, note=""):
        key = re.sub(r"\s+", " ", term).strip()
        if not key:
            return False
        row = rows.setdefault(
            key,
            {
                "term": key,
                "sources": [],
                "grade": grade,
                "concepts": [],
                "concept_ids": [],
                "cases": [],
                "note": note,
            },
        )
        if source not in row["sources"]:
            row["sources"].append(source)
        for ct in concepts_hit or []:
            if ct not in row["concepts"]:
                row["concepts"].append(ct)
                row["concept_ids"].append(t2id[ct])
        if case and case not in row["cases"]:
            row["cases"].append(case)
        # 등급은 보수적으로: 하나라도 검토면 검토 (자동 < 검토)
        if grade == "검토" or row["grade"] == "검토":
            row["grade"] = (
                "검토" if not (row["cases"] and not row["concepts"]) else row["grade"]
            )
        return True

    # ── 원천 ①: query-mapping 288 — 확장 키워드 ↔ 개념 제목 일치로 초안 ──
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    n1 = 0
    for term, keywords in mapping.items():
        hits = match_concepts([term] + list(keywords), titles)
        grade = "자동" if hits else "검토"
        n1 += add(
            term,
            "query-mapping",
            grade,
            concepts_hit=hits,
            note="" if hits else "개념 미매칭 — 목적지 지정 필요",
        )
    # ── 원천 ②: QNA·감리 제목 123 — 제목 그 자체 = 사례 별칭 (기계적) ──
    cl = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    n2 = 0
    for src in ("qna", "findings"):
        for c in cl[src]:
            title = re.sub(r"\s*\(\d{4}\)$", "", c["title"]).strip()
            n2 += add(title, f"제목({src})", "자동", case=c["db_parent_id"])
    # ── 원천 ③: 부록A 정의 9 — 공식 용어, 개념 목적지는 검수 대상 ──
    defs = json.loads(DEFS_PATH.read_text(encoding="utf-8"))
    n3 = 0
    for d in defs:
        term = re.sub(
            r"^\([^)]*\)\s*", "", d["term"]
        ).strip()  # "(광의의) 수익" → "수익"
        hits = match_concepts([term], titles)
        n3 += add(
            term,
            "부록A정의",
            "검토",
            concepts_hit=hits,
            note="공식 정의 보유 — 개념 목적지 확인 필요",
        )
        rows[re.sub(r"\s+", " ", term).strip()]["definition"] = d["definition"]

    # ── 검토 행 제안 생성: 용어의 본문 원문 출현 → 소속 개념 상위 2 제안 ──
    # Why: 검토자가 목적지를 백지에서 쓰게 하지 않기 위해 "→ A or B?" 수준의
    # 근거 있는 제안을 붙인다. 근거 = 용어(+확장어)가 실제 출현하는 본문 문단.
    # 예: "렌탈"의 확장어 "리스"가 문단 5(적용범위 제외 조항)에 출현 → [적용범위] 제안.
    raw_std = json.loads(
        Path("data/web/kifrs-1115-all.json").read_text(encoding="utf-8")
    )
    para_text: dict[str, str] = {}
    for item in raw_std:
        if item.get("type") == "paragraph" and item.get("sectionTitle") in (
            "본문",
            "부록 B 적용지침",
        ):
            pn = item.get("paraNum", "")
            if pn and pn not in para_text:
                para_text[pn] = item.get("fullContent", "")

    def occurrence_proposals(cands: list[str]) -> list[dict]:
        tally: dict[str, list] = {}
        for pn, text in para_text.items():
            cid = p2c.get(pn)
            if not cid:
                continue
            n = sum(text.count(c) for c in cands if len(c) >= 2)
            if n:
                e = tally.setdefault(cid, [0, []])
                e[0] += n
                e[1].append(pn)
        top = sorted(tally.items(), key=lambda x: -x[1][0])[:3]
        return [
            {
                "concept": concepts[cid]["title"],
                "concept_id": cid,
                "hits": v[0],
                "paras": v[1][:4],
            }
            for cid, v in top
        ]

    n_prop, n_zero = 0, 0
    for r in rows.values():
        if r["grade"] != "검토":
            continue
        cands = [r["term"]] + [k for k in mapping.get(r["term"], []) if k != r["term"]]
        props = occurrence_proposals(cands)
        r["proposals"] = props
        if props:
            n_prop += 1
        else:
            n_zero += 1
            r["note"] = (
                r["note"] + " / " if r["note"] else ""
            ) + "본문 출현 0 — 제외 제안"
    print(
        f"검토 행 제안: 제안 보유 {n_prop} + 출현 0(제외 제안) {n_zero} = {n_prop + n_zero} (검토 전수와 일치해야 PASS)"
    )

    # ── 회계·통계 ──────────────────────────────────────────────────
    total = len(rows)
    auto = sum(1 for r in rows.values() if r["grade"] == "자동")
    review = total - auto
    print(
        f"원천 반영: ①{n1}/{len(mapping)} ②{n2}/123 ③{n3}/{len(defs)} (누락 0이어야 PASS)"
    )
    print(
        f"용어 행: {total} (중복 통합 {n1 + n2 + n3 - total}건) = 자동 {auto} + 검토 {review}"
    )

    out = {
        "_meta": {
            "generated_by": "app/preprocessing/17-ontology-aliases.py",
            "status": "draft_pending_review",
            "sources": {"query-mapping": n1, "titles": n2, "appendixA": n3},
            "rows": total,
            "auto": auto,
            "review": review,
        },
        "terms": sorted(rows.values(), key=lambda r: (r["grade"] != "검토", r["term"])),
    }
    OUTPUT_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"저장: {OUTPUT_PATH}")

    # ── ripple ─────────────────────────────────────────────────────
    r1 = rows.get("가격결정권")
    ok1 = r1 and "본인 대 대리인의 고려사항" in r1["concepts"]
    print(
        f"{'✅' if ok1 else '❌'} ripple: 가격결정권 → [본인 대 대리인의 고려사항] ({r1['concepts'] if r1 else '없음'})"
    )
    r2 = rows.get("장기할부판매")
    ok2 = r2 and any("SSI-38700" in c for c in r2["cases"])
    print(
        f"{'✅' if ok2 else '❌'} ripple: 장기할부판매 → 사례 QNA-SSI-38700 ({r2['cases'] if r2 else '없음'})"
    )
    # 검토 행 제안 품질 (사용자 지적 2사례): 렌탈→적용범위(¶5 '리스'), 계약부채→표시/계약 잔액
    r3 = rows.get("렌탈")
    p3 = [p["concept"] for p in (r3 or {}).get("proposals", [])]
    ok3 = "적용범위" in p3
    print(f"{'✅' if ok3 else '❌'} ripple 제안: 렌탈 → 제안 {p3} (적용범위 포함 기대)")
    r4 = rows.get("계약부채")
    p4 = [p["concept"] for p in (r4 or {}).get("proposals", [])]
    ok4 = any(c in ("표시", "계약 잔액") for c in p4)
    print(
        f"{'✅' if ok4 else '❌'} ripple 제안: 계약부채 → 제안 {p4} (표시/계약 잔액 포함 기대)"
    )


if __name__ == "__main__":
    main()

"""DEAD-END 11단어 등재 + 섬 사례 6건 개념 직결 (2026-07-04 사용자 승인)

사용법:
  PYTHONPATH=. uv run python app/preprocessing/17d-aliases-supplement.py

Why: 제목→주제 전수 감사(04b)에서 사전 어휘 구멍 19건 발견 — 그중 실무 진입어로
     유효한 11단어를 등재한다. 정합성 3제한: ①단어는 사례 제목에서만 추출(AI 창작 0)
     ②목적지는 그 단어를 제목에 포함한 사례들의 감사본 주제 합집합(수기 지정 금지)
     ③사례 자체도 목적지에 포함(후보 진입점, 다중 목적지 허용).
     추가로 paras=0인 섬 6건은 17c 지정 개념을 case_links의 concepts 필드로 직결해
     뷰어 기본 화면(용어 꺼짐)에서도 사례→개념 선이 보이게 한다(IE example 간선과 동일 구조).
"""

import json
import re
from pathlib import Path

ALIASES_PATH = Path("data/ontology/aliases.json")
CASES_PATH = Path("data/ontology/case_links.json")
CONCEPTS_PATH = Path("data/ontology/concepts.json")

# 사용자 승인 11단어 (2026-07-04). 목적지는 규칙으로 산출 — 여기 개념을 적지 않는다.
NEW_WORDS = [
    "부가가치세",
    "숙박권",
    "수강권",
    "암호자산",
    "개별소비세",
    "연착",
    "민간투자사업",
    "부담금",
    "인식시기",
    "순액",
    "과대계상",
]


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def main():
    aj = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    cl = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cj = json.loads(CONCEPTS_PATH.read_text(encoding="utf-8"))
    concepts, p2c = cj["concepts"], cj["para_to_concept"]

    # 제목 용어의 개념(17c) 역인덱스 — paras=0 사례의 주제 원천
    title_term_concepts = {
        c: t.get("concept_ids", [])
        for t in aj["terms"]
        if any(s.startswith("제목(") for s in t["sources"])
        for c in t.get("cases", [])
    }

    all_cases = [("qna", c) for c in cl["qna"]] + [
        ("findings", c) for c in cl["findings"]
    ]

    # ── ① 11단어 등재 (신규 추가 또는 제외 행 부활) ─────────────
    # 부가가치세·숙박권·부담금은 query-mapping 출신이나 "본문 출현 0"으로 제외됐던 행 —
    # 이번 감사가 목적지(사례 주제)를 찾았으므로 새 행이 아니라 기존 행을 부활시킨다.
    idx = {norm(t["term"]): t for t in aj["terms"]}
    added_rows, revived_rows, edge_sum = 0, 0, 0
    touched = []
    for w in NEW_WORDS:
        old = idx.get(norm(w))
        assert old is None or not (old["concepts"] or old["cases"]), (
            f"{w}: 이미 등재(목적지 보유) — 재실행 중복 방지"
        )
        hit_cases, cid_union = [], set()
        for _, c in all_cases:
            if norm(w) in norm(c["title"]):
                hit_cases.append(c["db_parent_id"])
                topics = {p2c[p] for p in c.get("paras", []) if p in p2c}
                if not topics:  # 섬 6건: 17c 지정 개념이 주제
                    topics = set(title_term_concepts.get(c["db_parent_id"], []))
                cid_union |= topics
        assert hit_cases, f"{w}: 제목 포함 사례 0건 — 추출 원천 위반"
        cids = sorted(cid_union)
        decision = {
            "by": "AI 위임 판단 (DEAD-END 보강, 사용자 승인 2026-07-04)",
            "dropped": [],
            "added": [concepts[x]["title"] for x in cids],
            "reason": f"제목에 '{w}' 포함 사례 {len(hit_cases)}건의 감사본 주제 합집합"
            + (" — 본문 출현 0 제외 행 부활(제목이 목적지 제공)" if old else ""),
        }
        if old:
            old.update(
                concepts=[concepts[x]["title"] for x in cids],
                concept_ids=cids,
                cases=hit_cases,
                grade="자동(위임판단)",
                decision=decision,
            )
            old["sources"].append("제목추출(04b 감사 보강)")
            revived_rows += 1
            touched.append(old)
        else:
            row = {
                "term": w,
                "sources": ["제목추출(04b 감사 보강)"],
                "grade": "자동(위임판단)",
                "concepts": [concepts[x]["title"] for x in cids],
                "concept_ids": cids,
                "cases": hit_cases,
                "note": "",
                "decision": decision,
            }
            aj["terms"].append(row)
            added_rows += 1
            touched.append(row)
        edge_sum += len(cids) + len(hit_cases)
        print(
            f"  {w}: 사례 {len(hit_cases)} + 개념 {len(cids)}"
            + (" [부활]" if old else "")
        )

    ghost = [x for t in touched for x in t["concept_ids"] if x not in concepts]
    print(
        f"등재: 신규 {added_rows} + 부활 {revived_rows} = {added_rows + revived_rows}/11 / "
        f"신규 간선 합 {edge_sum} / 유령 개념 {len(ghost)} (0이어야 PASS)"
    )

    # ── ② 섬 6건 개념 직결 (case_links.concepts) ────────────────
    direct = 0
    for _, c in all_cases:
        if c.get("paras"):
            continue
        cids = title_term_concepts.get(c["db_parent_id"], [])
        assert cids, f"{c['id']}: paras=0인데 17c 개념 없음 — FAIL"
        c["concepts"] = cids
        direct += len(cids)
    n_zero = sum(1 for _, c in all_cases if not c.get("paras"))
    print(
        f"직결: paras=0 사례 {n_zero}/6 에 concepts 필드, example 간선 예정 {direct} (9여야 PASS)"
    )

    ALIASES_PATH.write_text(
        json.dumps(aj, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    CASES_PATH.write_text(
        json.dumps(cl, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"저장: {ALIASES_PATH} / {CASES_PATH}")


if __name__ == "__main__":
    main()

"""사전을 진입 어휘 그 자체로 정리 (2026-08-09 사용자 승인)

사용법:
  PYTHONPATH=. uv run python app/preprocessing/17e-aliases-entry.py

Why: aliases.json(423행)과 LLM에게 보여주는 진입 어휘(349개)가 달라, 파일을 열어도
     실제 목록을 알 수 없었다. 차이의 원인은 둘 — ①개념이 안 걸린 행 138개는 진입에
     쓰이지 않고 ②기준서 목차 제목은 사전에 없어 graph.py가 실행 중에 합쳐 넣었다.
     ①을 지우고 ②를 행으로 등재해 파일 = 진입 어휘가 되게 한다. 합쳐 넣던 로직은
     graph.py에서 제거된다.

     글자 매칭 제외를 새 필드로 표시하지 않는 이유: 모든 행이 이미 sources를 갖는다.
     목차 제목은 "적용"·"목적"·"측정"처럼 뭉뚱그린 말이라 질문 본문에 글자로 걸리면
     노이즈다(홀드아웃 92건 중 17건에서 오염 실측). 출처가 SOURCE_TOC 하나뿐인 행을
     글자 매칭에서 빼면 되고, 그건 표시가 아니라 출처의 자연스러운 귀결이다.

     paras가 없는 개념(기준서 루트·인식·계약원가)은 등재하지 않는다 — 골라도 가져올
     문단이 없다. graph.py의 기존 조건과 같다.
"""

import json
import re
from pathlib import Path

ALIASES_PATH = Path("data/ontology/aliases.json")
CONCEPTS_PATH = Path("data/ontology/concepts.json")

SOURCE_TOC = "기준서목차"


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def main():
    aj = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    concepts = json.loads(CONCEPTS_PATH.read_text(encoding="utf-8"))["concepts"]

    before = len(aj["terms"])

    # ── ① 개념이 안 걸린 행 제거 ──────────────────────────────
    # 사례 제목 115행(문장이라 글자로 걸릴 일이 없음, 실측 기여 72건 중 2건) +
    # 본문 출현 0으로 제외된 20행 + 부록A 범용어 3행(고객·수익).
    kept = [t for t in aj["terms"] if t.get("concept_ids")]
    dropped = before - len(kept)

    # ── ② norm 중복 행 병합 ───────────────────────────────────
    # "개별 판매가격"/"개별판매가격"처럼 공백만 다른 행이 따로 등재돼 있다.
    # graph.py는 norm 기준으로 읽으므로 파일에서도 한 행이어야 수가 맞는다.
    merged: dict[str, dict] = {}
    for t in kept:
        key = norm(t["term"])
        if key not in merged:
            merged[key] = t
            continue
        into = merged[key]
        for cid, title in zip(t["concept_ids"], t["concepts"]):
            if cid not in into["concept_ids"]:
                into["concept_ids"].append(cid)
                into["concepts"].append(title)
        for s in t["sources"]:
            if s not in into["sources"]:
                into["sources"].append(s)
    dedup = len(kept) - len(merged)

    # ── ③ 기준서 목차 제목 등재 ───────────────────────────────
    # 사전은 실무 질의에서 뽑아 만든 번역표라 "변동대가"·"라이선싱" 같은 공식 용어가
    # term으로 없다. LLM이 알아봐도 목록에 없으면 고를 수 없어 여기서 채운다.
    added, linked = 0, 0
    for cid, node in concepts.items():
        if not node.get("paras"):
            continue
        key = norm(node["title"])
        row = merged.get(key)
        if row is None:
            merged[key] = {
                "term": node["title"],
                "sources": [SOURCE_TOC],
                "grade": "목차(기준서 소제목)",
                "concepts": [node["title"]],
                "concept_ids": [cid],
                "cases": [],
                "note": "",
            }
            added += 1
            continue
        # 이미 실무어로 등재된 제목(수행의무·환불부채…)은 개념만 합친다.
        if SOURCE_TOC not in row["sources"]:
            row["sources"].append(SOURCE_TOC)
        if cid not in row["concept_ids"]:
            row["concept_ids"].append(cid)
            row["concepts"].append(node["title"])
            linked += 1

    rows = sorted(merged.values(), key=lambda t: t["term"])
    aj["terms"] = rows
    aj["_meta"]["entry_pruned"] = {
        "before": before,
        "dropped_no_concept": dropped,
        "merged_norm_dup": dedup,
        "added_toc": added,
        "linked_existing": linked,
        "rows": len(rows),
    }
    print(f"{before}행 → 개념없음 -{dropped} / norm중복 -{dedup} / 목차 +{added}")
    print(f"  목차 개념을 기존 행에 합침: {linked}건")
    print(
        f"진입 어휘: {len(rows)}행 (전부 개념 보유: {all(t['concept_ids'] for t in rows)})"
    )
    match_only = [t for t in rows if t["sources"] != [SOURCE_TOC]]
    print(f"  └ 글자 매칭 대상(목차 전용 행 제외): {len(match_only)}행")

    ALIASES_PATH.write_text(
        json.dumps(aj, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"저장: {ALIASES_PATH}")


if __name__ == "__main__":
    main()

"""섬 사례 6건 개념 연결 (2026-07-04 사용자 승인 A안)

사용법:
  PYTHONPATH=. uv run python app/preprocessing/17c-aliases-islands.py

Why: 제목 유래 용어(원천 ②)는 사례 별칭으로만 등재되어 개념 매칭을 타지 않았고
     (17번 스크립트 원천 ② 처리부), 문단 인용이 0인 QNA 6건은 어느 개념에서도
     도달 불가한 2노드 섬이 됐다(개념→사례 도달성 전수 측정: 117/117 vs 섬 6).
     질의 원문을 근거로 6건의 제목 용어에 개념 후보를 지정한다(후보 진입점 원칙).
     개념은 제목이 아닌 ID로 지정 — "기간에 걸쳐 이행하는 수행의무"는 본문/부록B
     중복 제목이라 제목 역인덱스는 함정(IE 매핑에서 동일 함정 전례).
"""

import json
from pathlib import Path

ALIASES_PATH = Path("data/ontology/aliases.json")
CONCEPTS_PATH = Path("data/ontology/concepts.json")

# 용어(=사례 제목) → 개념 ID 지정. reason = 질의 원문 근거.
ISLAND_FIX: dict[str, dict] = {
    "수업료 수익의 인식": {
        "concept_ids": ["5HDlPF", "bz3jWR"],  # 기간에 걸쳐(본문)·진행률을 측정함
        "reason": "쟁점=수익을 '어느 기간에 걸쳐' 인식하는가(10개월 vs 12개월) — "
        "기간에 걸쳐 이행(35~37)과 진행률 측정(39~43)이 정면 조항",
    },
    "공동영업자의 산출물 판매": {
        "concept_ids": ["AQB8cb"],  # 수행의무의 이행
        "reason": "회신 결론=고객에게 '이전한' 산출물만 수익 인식 — 이전(31~45)이 근거"
        " (IFRS 11 몫 산정은 외부 기준서 영역)",
    },
    "장기할부판매": {
        "concept_ids": ["lIlmTb", "Ag62GJ"],  # 한 시점 이행·유의적인 금융요소
        "reason": "회신=할부기간 무관 통제 이전 시점(38) 인식 + 장기할부=금융요소(60~65) 쟁점",
    },
    "반품의 회계처리": {
        "concept_ids": ["1IdzfY", "XLz6Gv"],  # 반품권이 있는 판매·본인 대 대리인
        "reason": "쟁점=반품·환불부채(B20~27) + 회신 논거='본인으로서 책임'(B34~38)",
    },
    "계약변경과 수익인식": {
        "concept_ids": ["xYL1TP"],  # 계약변경
        "reason": "구별되지 않는 계약변경의 누적효과 조정 — 계약변경(18~21) 정면 조항",
    },
    "제품 판매 후 재매입": {
        "concept_ids": ["vw8tzF"],  # 재매입약정
        "reason": "쟁점=사후 합의 재매입이 재매입약정(B64~76)에 해당하는지",
    },
}


def main():
    aj = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    concepts = json.loads(CONCEPTS_PATH.read_text(encoding="utf-8"))["concepts"]

    applied, new_edges = 0, 0
    for t in aj["terms"]:
        fix = ISLAND_FIX.get(t["term"])
        if not fix:
            continue
        # 제목 유래 행만 대상 (동명 일반 용어 오염 방지)
        if not any(s.startswith("제목(") for s in t["sources"]):
            continue
        assert not t["concepts"], f"{t['term']}: 이미 개념 보유 — 재실행 중복 방지"
        t["concept_ids"] = fix["concept_ids"]
        t["concepts"] = [concepts[c]["title"] for c in fix["concept_ids"]]
        t["decision"] = {
            "by": "AI 위임 판단 (섬 6건 개념 연결, 사용자 승인 2026-07-04)",
            "dropped": [],
            "added": t["concepts"],
            "reason": fix["reason"],
        }
        applied += 1
        new_edges += len(fix["concept_ids"])

    ghost = [
        c
        for term in ISLAND_FIX.values()
        for c in term["concept_ids"]
        if c not in concepts
    ]
    print(f"판단 반영: {applied}/6 (6 아니면 FAIL) / 신규 간선 {new_edges}")
    print(f"유령 개념 ID: {len(ghost)}건 {ghost} (0이어야 PASS)")
    for t in aj["terms"]:
        if t["term"] in ISLAND_FIX:
            assert len(t["concepts"]) == len(t["concept_ids"])

    aj["_meta"]["island_fix"] = {"terms": applied, "edges": new_edges}
    ALIASES_PATH.write_text(
        json.dumps(aj, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"저장: {ALIASES_PATH}")


if __name__ == "__main__":
    main()

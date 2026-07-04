"""용어 검토 78건 위임 판단 반영 (사용자 지시 2026-07-04: 다중 목적지 허용,
AI가 전수 판단하되 애매 건만 에스컬레이션)

사용법:
  PYTHONPATH=. uv run python app/preprocessing/17b-aliases-finalize.py

규칙: 기본 = 출현 근거 제안 전부 채택. OVERRIDES = 회계 판단이 개입된 행
(기각·추가·간선0)으로 전건 사유 기록. ESCALATE = 판단 불가 3건(사용자 대기).
"""

import json
from pathlib import Path

DRAFT_PATH = Path("data/ontology/aliases.draft.json")
CONCEPTS_PATH = Path("data/ontology/concepts.json")

# 행별 판단 (없으면 기본: 제안 전부 채택)
# adopt=제안 중 채택할 개념(생략=전부), add=제안 외 판단 추가, reason 필수
OVERRIDES: dict[str, dict] = {
    "MOU": {
        "adopt": ["계약을 식별함"],
        "reason": "MOU는 계약 성립 여부 쟁점 — 변경 무관",
    },
    "가계약": {"adopt": ["계약을 식별함"], "reason": "동상"},
    "계약강제력": {
        "adopt": ["계약을 식별함"],
        "reason": "집행가능성=식별 요건(문단 9)",
    },
    "계약서미작성": {"adopt": ["계약을 식별함"], "reason": "구두계약 쟁점=식별"},
    "계약서없는거래": {"adopt": ["계약을 식별함"], "reason": "동상"},
    "계약식별": {"adopt": ["계약을 식별함"], "reason": "동어"},
    "구두계약": {"adopt": ["계약을 식별함"], "reason": "식별 쟁점"},
    "집행가능성": {"adopt": ["계약을 식별함"], "reason": "문단 9 요건"},
    "취소불가능": {"adopt": ["계약을 식별함"], "reason": "위약 조건=식별 쟁점"},
    "계약": {
        "adopt": ["계약을 식별함"],
        "reason": "일반 용어 — 단어 빈도 제안은 노이즈, 정의의 뿌리인 식별만",
    },
    "고객": {
        "adopt": [],
        "reason": "불용어급 일반 용어 — 간선 무의미, 부록A 정의만 노드 속성으로 보존",
    },
    "수익(Income)": {"adopt": [], "reason": "동상 (정의 보존)"},
    "수익(Revenue)": {"adopt": [], "reason": "동상 (정의 보존)"},
    "수행의무": {
        "adopt": [],
        "add": ["수행의무를 식별함", "수행의무의 이행"],
        "reason": "일반 용어 — 빈도 제안 노이즈, 정의상 핵심 두 개념 지정",
    },
    "검수기준": {
        "add": ["고객의 인수"],
        "reason": "검수 조건=B83~86 고객의 인수가 정면 조항",
    },
    "인수절차": {"add": ["고객의 인수"], "reason": "동상"},
    "고객충성제도": {
        "adopt": [],
        "add": ["추가 재화나 용역에 대한 고객의 선택권"],
        "reason": "C10 출현은 1113 폐지 언급 노이즈 — 충성제도=B40 선택권",
    },
    "리워드": {
        "adopt": [],
        "add": ["추가 재화나 용역에 대한 고객의 선택권"],
        "reason": "동상(마일리지 계열)",
    },
    "마일리지": {
        "adopt": [],
        "add": ["추가 재화나 용역에 대한 고객의 선택권"],
        "reason": "동상",
    },
    "포인트": {
        "adopt": [],
        "add": ["추가 재화나 용역에 대한 고객의 선택권"],
        "reason": "동상",
    },
    "상품권": {
        "add": ["고객이 행사하지 아니한 권리"],
        "reason": "미행사 상품권=B44~47 정면 조항",
    },
    "선수금": {"add": ["계약 잔액"], "reason": "선수금=계약부채(116~118)"},
    "기성청구": {
        "adopt": ["표시", "계약 잔액"],
        "reason": "금융요소 출현(¶65)은 부수 언급",
    },
    "미수수익": {"adopt": ["표시", "계약 잔액"], "reason": "동상"},
    "누적수익조정": {"adopt": ["계약변경"], "reason": "누적효과 일괄조정=문단 21"},
    "손실충당금": {
        "adopt": ["원가 기준 투입법 적용 계약의 추가 공시", "상각과 손상"],
        "reason": "한129 공사손실충당 공시가 정면, 금융요소 제외",
    },
    "회수가능성": {
        "adopt": [],
        "add": ["계약을 식별함"],
        "reason": "회수가능성=문단 9⑸ 식별 요건이 정면 — 출현 제안(64·102)은 부수",
    },
    "설계시공": {
        "add": ["기간에 걸쳐 이행하는 수행의무"],
        "reason": "건설계약 핵심 쟁점 추가",
    },
    "턴키": {"add": ["기간에 걸쳐 이행하는 수행의무"], "reason": "동상"},
    "준공": {"add": ["기간에 걸쳐 이행하는 수행의무"], "reason": "동상"},
    "실질지배": {"add": ["수행의무의 이행"], "reason": "통제 정의(31~33) 추가"},
    "통제권": {"add": ["수행의무의 이행"], "reason": "동상"},
    "통제이전": {"add": ["수행의무의 이행"], "reason": "동상"},
    "위험과보상": {"add": ["수행의무의 이행"], "reason": "문단 33 위험·보상 지표"},
}
# 판단 불가 — 사용자 에스컬레이션 (검토 유지)
ESCALATE = {
    "시상품": "경품·사은품 성격 — [고객에게 지급할 대가]인지 [고객의 선택권]인지 거래 유형에 따라 갈림",
    "아이템": "게임 아이템 — [라이선싱] 계열인지 [한 시점 이행](디지털 재화 판매)인지 판단 필요",
    "항공": "업종 태그 단독 — 마일리지([선택권])로 볼지 용어 자체를 제외할지",
}


def main():
    d = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
    concepts = json.loads(CONCEPTS_PATH.read_text(encoding="utf-8"))["concepts"]
    t2id = {v["title"]: k for k, v in concepts.items()}

    full, partial, escal = 0, 0, 0
    for t in d["terms"]:
        if t["grade"] != "검토" or not t.get("proposals"):
            continue
        term = t["term"]
        if term in ESCALATE:
            t["note"] = "에스컬레이션: " + ESCALATE[term]
            escal += 1
            continue
        ov = OVERRIDES.get(term, {})
        adopt = ov.get("adopt", [p["concept"] for p in t["proposals"]])
        adopt = list(dict.fromkeys(adopt + ov.get("add", [])))
        dropped = [p["concept"] for p in t["proposals"] if p["concept"] not in adopt]
        t["concepts"] = adopt
        t["concept_ids"] = [t2id[c] for c in adopt]
        t["grade"] = "자동(위임판단)"
        t["decision"] = {
            "by": "AI 위임 판단 (사용자 지시 2026-07-04, 다중 목적지 허용)",
            "dropped": dropped,
            "added": ov.get("add", []),
            "reason": ov.get("reason", "출현 근거 제안 전부 채택"),
        }
        if term in OVERRIDES:
            partial += 1
        else:
            full += 1
    print(
        f"판단 회계: 전부채택 {full} + 판단개입 {partial} + 에스컬레이션 {escal} = {full + partial + escal} (78이어야 PASS)"
    )
    unknown = [
        c
        for t in d["terms"]
        for c in t.get("concepts", [])
        if t["grade"] == "자동(위임판단)" and c not in t2id
    ]
    print(f"미해소 개념명: {len(unknown)}건 {unknown[:5]} (0이어야 PASS)")

    d["_meta"]["delegated_review"] = {
        "full": full,
        "partial": partial,
        "escalated": escal,
    }
    DRAFT_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {DRAFT_PATH}")

    # ripple: 렌탈(전부채택 3종) / 회수가능성(제안 기각→식별 지정)
    r1 = next(t for t in d["terms"] if t["term"] == "렌탈")
    print(
        f"{'✅' if len(r1['concepts']) == 3 else '❌'} ripple: 렌탈 → {r1['concepts']}"
    )
    r2 = next(t for t in d["terms"] if t["term"] == "회수가능성")
    ok2 = r2["concepts"] == ["계약을 식별함"] and r2["decision"]["dropped"]
    print(
        f"{'✅' if ok2 else '❌'} ripple: 회수가능성 → {r2['concepts']} (기각 {r2['decision']['dropped']})"
    )


if __name__ == "__main__":
    main()

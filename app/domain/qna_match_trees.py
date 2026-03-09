# app/domain/qna_match_trees.py
# 질의회신 기반 판단 체크리스트 — condition/question/yes_path/no_path 구조
#
# tree_matcher.py가 trigger_keywords 매칭 후 CLARIFY 프롬프트에 주입합니다.

QNA_MATCH_TREES: dict[str, dict] = {
    "위탁판매 수익 인식 시점": {
        "trigger_keywords": [
            "위탁판매", "수탁자", "위탁자", "탁송", "재판매",
        ],
        "qna_premise_checklist": [
            {
                "condition": "수탁자가 재화를 인도받았으나 아직 최종 고객에게 판매하지 않음",
                "question": "수탁자가 재화를 반품할 수 있는 권리가 있나요?",
                "yes_path": "위탁자(본인)는 수탁자의 최종 판매 시점에 수익 인식 (문단 B77)",
                "no_path": "수탁자에 대한 인도 시점에 통제 이전 여부를 추가 판단 필요",
            },
            {
                "condition": "수탁자가 가격결정권 없이 위탁자 지정 가격으로만 판매",
                "question": "수탁자가 판매가격을 독자적으로 결정할 수 있나요?",
                "yes_path": "수탁자가 통제권을 보유할 가능성 → 인도 시 수익 인식 가능",
                "no_path": "위탁자가 통제 유지 → 최종 판매 시 수익 인식 (문단 B77~B78)",
            },
        ],
    },
    "고객에게 지급하는 대가": {
        "trigger_keywords": [
            "고객에게 지급", "판매장려금", "입점수수료", "리스팅피", "슬로팅피",
        ],
        "qna_premise_checklist": [
            {
                "condition": "기업이 고객(또는 고객의 고객)에게 현금/크레딧을 지급",
                "question": "고객으로부터 구별되는 재화/용역을 받나요?",
                "yes_path": "별도 구매로 회계처리 (문단 70)",
                "no_path": "거래가격에서 차감 (문단 70~72)",
            },
            {
                "condition": "거래가격 차감으로 결정된 경우",
                "question": "지급 시점이 수익 인식 시점보다 이른가요?",
                "yes_path": "선급금(자산)으로 인식 후 수익 인식 시 차감 (문단 72)",
                "no_path": "수익 인식 시 거래가격에서 직접 차감",
            },
        ],
    },
}

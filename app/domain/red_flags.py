# app/domain/red_flags.py
# 감리사례 위험신호 패턴 — 주의가 필요한 거래 유형별 체크리스트
#
# tree_matcher.py가 trigger_keywords 매칭 후 CLARIFY 프롬프트에 경고를 주입합니다.

RED_FLAG_PATTERNS: dict[str, dict] = {
    "밀어내기 매출 위험": {
        "trigger_keywords": [
            "밀어내기", "채널스터핑", "분기말", "기말", "대리점 재고",
            "반품률 급증", "허위매출",
        ],
        "warning_prefix": "밀어내기 매출은 감리지적 빈출 유형입니다.",
        "red_flag_questions": [
            {"question": "분기말/기말에 매출이 집중되는 패턴이 있나요?"},
            {"question": "대리점/유통업체에 반품 조건부로 대량 출하했나요?"},
            {"question": "출하 후 실질적 반품률이 과거 평균 대비 높아졌나요?"},
        ],
    },
    "수행의무 미식별 위험": {
        "trigger_keywords": [
            "무상", "무료", "사은품", "경품", "추가 제공", "서비스 번들",
        ],
        "warning_prefix": "무상 제공 약속도 별도 수행의무일 수 있습니다.",
        "red_flag_questions": [
            {"question": "무상 제공되는 재화/용역이 계약에 명시되어 있나요?"},
            {"question": "고객이 무상 항목 없이도 나머지에서 효익을 얻을 수 있나요?"},
            {"question": "무상 항목의 독립판매가격을 추정할 수 있나요?"},
        ],
    },
}

# app/ui/constants.py
# 환경 설정, 키워드 칩, 그룹 매핑, 진행률 등 변경이 드문 상수 모음.
# 다른 모든 모듈이 이 파일을 임포트합니다 — 순환 임포트가 생기지 않도록
# 이 파일은 외부 의존성을 갖지 않아야 합니다.

import os

# ── API 엔드포인트 ───────────────────────────────────────────────────────────────
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8002")
CHAT_URL = f"{API_BASE}/chat"
FEEDBACK_URL = f"{API_BASE}/feedback"
API_TIMEOUT = 120  # 초

# ── 키워드 칩 ────────────────────────────────────────────────────────────────────
# 선정 기준: QNA 빈출 빈도(101건 분석) + 기준서 핵심 쟁점 + 실무 중요도
# 사용자가 무엇을 물어봐야 할지 모를 때 첫 진입점을 제공합니다.
KEYWORD_CHIPS = [
    "수익인식 시기",  # QNA 최빈출 (10건 이상)
    "수행의무 식별",  # 5단계 모형의 핵심
    "반품권",  # QNA 4건
    "변동대가",  # 거래가격 산정의 핵심
    "본인 vs 대리인",  # 실무 중요도 최상위
    "라이선스",  # 기준서 전용 섹션 (문단 B52~B63)
    "진행률 측정",  # QNA 4건 (건설·서비스 모두 해당)
    "계약자산 vs 수취채권",  # QNA 4건 + 분개 처리 혼동 多
    "할인권·추가구매선택권",  # 할인 관련 QNA 6건
    "유상사급",  # 제조업 QNA 2건
    "소프트웨어 구독",  # 시간 경과 이전의 대표 사례
    "계약변경",  # 실무 계약 수정 시 빈번
]

# ── 홈 예시 질문 ─────────────────────────────────────────────────────────────
# 선정 기준: qna_holdout 골든테스트 3축(conclusion·paragraph·branch) 만점 50문항 중
# 짧고 자기완결적인 실제 질의회신 원문 3건 — 만점 문항이라 데모 품질이 보장됨.
# 카드에 [굵은 주제어 + 질문 원문]을 함께 노출 — 주제어가 '예시'임을 드러내고
# 원문이 '어떻게 묻는지'를 보여줌. 클릭 시 question이 곧바로 실행됨.
HOME_EXAMPLE_QUERIES = [
    {
        "topic": "반품조건부 판매",  # QNA-SSI-38697 6/6
        "question": (
            "반품조건부 판매 시 반품금액을 합리적으로 추정하는 것이 "
            "불가능한 경우, 언제 해당 재고자산을 제거하는지?"
        ),
    },
    {
        "topic": "총액 vs 순액",  # QNA-SSI-35578 6/6 (본인-대리인)
        "question": (
            "회사가 고객의 주문을 받아 특정 회사의 소프트웨어를 매입한 후 "
            "판매하는 경우, 수익을 총액으로 인식하는지 아니면 순액으로 인식하는지?"
        ),
    },
    {
        "topic": "상품권 수익인식",  # QNA-SSI-36948 6/6
        "question": (
            "A사는 고객에게 자신이 운용하는 워터파크를 이용할 수 있는 상품권을 "
            "판매하였음. A사는 상품권 판매 시 수익을 인식할 수 있는지?"
        ),
    },
]

# ── 문서 source 문자열 상수 ───────────────────────────────────────────────────
# Why: 10+ 파일에서 하드코딩되던 source 문자열을 중앙화하여
#       한 곳 변경 시 나머지가 미변경되어 그룹핑/필터링 실패하는 문제 방지
SRC_BODY = "본문"
SRC_APPENDIX_B = "적용지침B"
SRC_BC = "결론도출근거"
SRC_DEFINITION = "용어정의"
SRC_EFFECTIVE = "시행일"
SRC_IE = "적용사례IE"
SRC_QNA = "질의회신"
SRC_QNA_SHORT = "QNA"  # retriever에서 classify_source가 반환하는 단축형
SRC_FINDING = "감리사례"

# ── Document ID 접두어 상수 ────────────────────────────────────────────────────
# Why: retriever, db, evidence에서 parent_id 접두어 비교가 분산되어 있어 중앙화
DOC_PREFIX_QNA = "QNA-"
DOC_PREFIX_FSS = "FSS-"
DOC_PREFIX_KICPA = "KICPA-"
DOC_PREFIX_FSS_CASE = "FSS-CASE-"
DOC_PREFIX_KICPA_CASE = "KICPA-CASE-"
# 감리사례 접두어 튜플 (startswith에서 사용)
DOC_PREFIXES_FINDING = (DOC_PREFIX_FSS, DOC_PREFIX_KICPA)
DOC_PREFIXES_FINDING_CASE = (DOC_PREFIX_FSS_CASE, DOC_PREFIX_KICPA_CASE)

# ── 문서 카테고리 → 아코디언 그룹 매핑 ──────────────────────────────────────────
# source 값 하나가 여러 그룹에 속할 수 없도록 우선순위 순서로 정렬합니다.
ACCORDION_GROUPS: dict[str, list[str]] = {
    "📘 기준서 본문 및 적용지침": [
        SRC_BODY,
        SRC_APPENDIX_B,
        SRC_DEFINITION,
        SRC_EFFECTIVE,
    ],
    "🔍 결론도출근거(BC)": [SRC_BC],
    "📋 적용사례(IE)": [SRC_IE],
    "💬 질의회신(QNA)": [SRC_QNA, SRC_QNA_SHORT],
    "🚨 감리지적사례": [SRC_FINDING],
}

# ── RAG 노드 → 진행률 매핑 ──────────────────────────────────────────────────────
# pre_retrieved 분기 시 retrieve/rerank 노드가 건너뛰어져 진행률이 빠르게 올라갑니다.
_STEP_PROGRESS: dict[str, int] = {
    "analyze": 15,
    "retrieve": 35,
    "rerank": 55,
    "grade": 70,
    "rewrite": 75,
    "hyde": 78,
    "generate": 85,
    "format": 95,
}

# ── RAG 노드 → 사용자 친화적 라벨 ────────────────────────────────────────────────
# st.status() 위젯에 단계별 진행 상황을 표시합니다.
_STEP_LABELS: dict[str, str] = {
    "analyze": "질문을 분석하고 있어요",
    "retrieve": "관련 조항을 검색하고 있어요",
    "rerank": "가장 관련성 높은 조항을 선별하고 있어요",
    "grade": "검색 결과 품질을 평가하고 있어요",
    "rewrite": "더 나은 검색을 위해 질문을 재구성하고 있어요",
    "hyde": "가상 문서를 생성하여 재검색하고 있어요",
    "generate": "AI가 답변을 생성하고 있어요 (약 15~20초 소요)",
    "format": "답변을 정리하고 있어요",
}

# 교차 링크 정규화 — 토픽 표시명의 미세 변형을 통일된 키로 매핑
# cross_links.py에서 사용
CROSS_LINK_NORMALIZE: dict[str, str | None] = {
    # 값이 None이면 링크 비활성, 문자열이면 해당 토픽으로 연결
}

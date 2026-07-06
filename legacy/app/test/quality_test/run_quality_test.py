"""
K-IFRS 1115 챗봇 품질 테스트 스크립트

26개 테스트 케이스 × 3회 순차 실행 → JSON 결과 저장 → 채점 리포트 생성

실행:
  PYTHONPATH=. uv run --env-file .env python app/test/quality_test/run_quality_test.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

# ── 설정 ────────────────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8002"
RUNS_PER_CASE = 3
RESULTS_FILE = Path(__file__).parent / "quality_results.json"
REPORT_FILE = Path(__file__).parent / "quality_report.md"
TIMEOUT = 120  # 초 — 호출당 최대 대기


# ── 테스트 케이스 정의 ──────────────────────────────────────────────────────────
# (test_id, user_message, expected_retriever_docs, grading_criteria)

TEST_CASES: list[dict[str, Any]] = [
    # ─── 유연성/사각지대 (TEST 0~5) ─────────────────────────────────────────────
    {
        "id": "TEST-0",
        "group": "유연성/사각지대",
        "title": "핵심사례 — 본인 vs 대리인(위탁판매)",
        "message": (
            "A가 B에게 재화(완성된 의류)를 100원에 공급하고 이 때 공급가액(100원)으로 "
            "세금계산서를 끊음. 이후 B는 최종 고객 C에게 재화를 120원에 판매하는데, "
            "이 경우 A가 인식하여야 할 매출액은 100원인지, 120원인지 궁금합니다."
        ),
        "expected_docs": ["B77", "B34~B38", "B35", "IE239~IE243", "IE231~IE233"],
        "criteria": [
            "통제권 확인 (가격결정권, 재고위험)",
            "본인인 경우 120원 총액 제시",
            "세금계산서 혼동요인 지적",
        ],
    },
    {
        "id": "TEST-1",
        "group": "유연성/사각지대",
        "title": "단순 이론 질의 — 불필요 꼬리질문 방어",
        "message": (
            "K-IFRS 1115호에서 변동대가는 언제, 어떻게 수익으로 인식해야 해? "
            "그냥 예상되는 금액 전부 다 매출로 잡으면 되는 거야?"
        ),
        "expected_docs": ["50~52", "53", "56~58", "55"],
        "criteria": [
            "불필요한 꼬리질문 없이 즉답",
            "기댓값/최빈값 추정 방법 설명",
            "유의적 환원 제약 개념 설명",
        ],
    },
    {
        "id": "TEST-2",
        "group": "유연성/사각지대",
        "title": "완결된 복합 사례 — 불필요 체크리스트 방어",
        "message": (
            "A사는 B사에게 제품 1,000개를 개당 100원에 납품하기로 계약했습니다. "
            '단, 계약서에는 "B사가 1년 내에 1,000개를 모두 구매하면, 전체 물량에 '
            '대해 단가를 90원으로 소급 적용해 준다(볼륨 디스카운트)"는 조건이 있습니다. '
            "현재 2분기에 B사가 이미 1,000개 구매를 완료하여 대량 구매 조건(불확실성)이 "
            "완전히 해소되었습니다. 2분기에 A사는 수익을 어떻게 인식해야 하나요?"
        ),
        "expected_docs": ["50~56", "87~89"],
        "criteria": [
            "불필요 체크리스트 없이 바로 계산/회계처리",
            "당기(2분기) 수익에서 가감(차감) 원칙",
        ],
    },
    {
        "id": "TEST-3",
        "group": "유연성/사각지대",
        "title": "신종/하이브리드 사업 — Gray Area 경고",
        "message": (
            "우리 회사는 자체 개발한 메타버스 플랫폼 내에서 '가상 부동산(Land)'을 "
            "NFT 형태로 분양하고 있습니다. 고객은 가상화폐(토큰)로 분양대금을 결제하며, "
            "우리 회사는 분양받은 고객들에게 플랫폼 내에서 발생하는 거래 수수료의 5%를 "
            "매일 이자처럼 배당(Staking Yield)해주기로 약정했습니다. "
            "가상 부동산을 고객의 지갑으로 전송한 오늘, 받은 가상화폐 가치만큼 100% "
            "분양 매출로 잡고, 나중에 주는 5% 배당금은 지급수수료 비용으로 처리하면 문제가 없겠죠?"
        ),
        "expected_docs": ["6", "9"],
        "criteria": [
            "단정적 환각 답변 회피",
            "❗ [전문가 판단 필요(Gray Area)] 경고 출력",
        ],
    },
    {
        "id": "TEST-4",
        "group": "유연성/사각지대",
        "title": "정보 부족 — 꼬리질문 필수 (라이선스)",
        "message": (
            "우리 회사가 A사에 자체 개발한 소프트웨어 라이선스를 3년간 제공하기로 하고, "
            "대금을 일시불로 30억 원을 수취했습니다. "
            "돈을 한 번에 다 받았으니 이번 연도에 수익으로 전액 인식해도 되나요?"
        ),
        "expected_docs": ["B54~B63", "B56", "B58", "B61"],
        "criteria": [
            "섣불리 일시 인식 결론 내리지 않음",
            "접근권 vs 사용권 핵심 분기 꼬리질문 생성",
        ],
    },
    {
        "id": "TEST-5",
        "group": "유연성/사각지대",
        "title": "오도된 질문 — 단호히 비용 처리",
        "message": (
            "대형 프로젝트를 수주하기 위해 외부 법무법인에 법률 실사 수수료로 2,000만 원을 "
            "썼습니다. 아쉽게도 입찰 경쟁에서 떨어져서 수주에 실패했습니다. "
            "수주에는 실패했지만, 어쨌든 계약을 체결하려고 노력하면서 쓴 돈이니까 "
            "'계약체결 증분원가(자산)'로 잡아두고 나중에 다른 프로젝트에서 이익이 나면 "
            "상각해도 되죠?"
        ),
        "expected_docs": ["91~93", "94"],
        "criteria": [
            "불필요 꼬리질문 없이 단호히 비용 처리 결론",
            "계약 체결 여부 무관 원가 원칙 지적",
        ],
    },
    # ─── 섹션별 커버리지 (SECTION 1~20) ──────────────────────────────────────────
    {
        "id": "SECTION-1",
        "group": "섹션별 커버리지",
        "title": "라이선싱 (접근권 vs 사용권)",
        "message": (
            "우리 회사가 자체 개발한 소프트웨어 기술 라이선스를 A사에 3년간 "
            "제공하기로 하고, 대금을 일시불로 30억 원 받았습니다. "
            "돈을 한 번에 다 받았으니 이번 연도에 영업수익으로 전액 인식해도 되나요?"
        ),
        "expected_docs": ["B54~B63", "B58", "B61"],
        "criteria": [
            "접근권 vs 사용권 꼬리질문 생성",
            "조건별 정답 제시 가능",
        ],
    },
    {
        "id": "SECTION-2",
        "group": "섹션별 커버리지",
        "title": "계약변경 (별도 계약 vs 기존 계약 수정)",
        "message": (
            "기존에 제품 100개를 납품하는 계약을 진행 중인데, 고객이 30개를 추가로 "
            "주문했습니다. 저희가 추가 물량 30개에 대해서는 단가를 기존보다 20% 크게 "
            "할인해 주기로 합의했습니다. "
            "이 추가 건은 기존 계약과 분리해서 '별도 계약'으로 수익을 잡으면 되죠?"
        ),
        "expected_docs": ["18~21", "20", "21⑴"],
        "criteria": [
            "개별 판매가격 반영 여부 꼬리질문",
            "별도 계약 vs 전진적 처리 조건별 정답",
        ],
    },
    {
        "id": "SECTION-3",
        "group": "섹션별 커버리지",
        "title": "본인 대 대리인 (SW 유통)",
        "message": (
            "고객의 요구사항에 맞는 타사 소프트웨어를 파악해서 제조사에 주문을 넣고 "
            "고객에게 판매하는 계약을 맺었습니다. 제조사가 고객에게 라이선스 키를 직접 "
            "발급해 줍니다. 저희가 고객에게 청구한 전체 금액을 매출(총액)로 잡아도 되나요?"
        ),
        "expected_docs": ["B34~B38", "B35"],
        "criteria": [
            "재고위험/가격결정권 꼬리질문",
            "본인(총액) vs 대리인(순액) 조건별 정답",
        ],
    },
    {
        "id": "SECTION-4",
        "group": "섹션별 커버리지",
        "title": "미인도청구약정 (Bill-and-Hold)",
        "message": (
            "D업체에 여름 시즌 제품을 5,000만 원에 판매하고 세금계산서도 발행했습니다. "
            "대금도 일부 받았고요. 그런데 제품은 아직 인도하지 않고 우리 회사 창고에 "
            "그대로 보관 중입니다. 이거 당장 수익으로 인식해도 됩니까?"
        ),
        "expected_docs": ["B79~B82", "B81"],
        "criteria": [
            "미인도청구약정 4요건 꼬리질문",
            "충족/미충족 조건별 정답",
        ],
    },
    {
        "id": "SECTION-5",
        "group": "섹션별 커버리지",
        "title": "재매입약정 (콜옵션)",
        "message": (
            "우리 회사가 생산 설비를 고객에게 1억 원에 판매했습니다. 그런데 계약 조건에 "
            "2년 뒤에 우리 회사가 원할 경우 이 설비를 다시 사올 수 있는 '콜옵션'이 포함되어 "
            "있습니다. 설비를 다시 사 올 가능성은 적은데, 일단 1억 원을 판매 시점에 매출로 "
            "잡으면 되나요?"
        ),
        "expected_docs": ["B64~B76", "B66", "B68"],
        "criteria": [
            "콜옵션 있으면 수익 인식 불가 명확히 지적",
            "행사가격 꼬리질문 (리스 vs 금융약정)",
        ],
    },
    {
        "id": "SECTION-6",
        "group": "섹션별 커버리지",
        "title": "고객에게 지급할 대가",
        "message": (
            "저희 플랫폼을 이용하는 유저(방송 크리에이터)들의 이탈을 막기 위해 "
            "활동지원금(캐시백 리워드) 명목으로 현금 1,000만 원을 지급했습니다. "
            "마케팅 목적이니까 당연히 '광고선전비(비용)'로 처리하려고 합니다. "
            "맞게 하는 건가요?"
        ),
        "expected_docs": ["70~72", "71"],
        "criteria": [
            "고객 해당 여부 + 구별되는 용역 꼬리질문",
            "수익 차감 vs 비용 처리 조건별 정답",
        ],
    },
    {
        "id": "SECTION-7",
        "group": "섹션별 커버리지",
        "title": "진행률 측정 (미설치 고가 자재)",
        "message": (
            "총 공사예정원가가 100억 원인 건설 계약을 진행 중입니다. 이번 달에 현장에 "
            "30억 원짜리 고가 특수 장비(엘리베이터)가 입고되어 대금을 지급했습니다. "
            "아직 설치는 안 했지만 원가가 발생했으니 (30억/100억) = 30%만큼 공사진행률을 "
            "잡고 마진을 얹어서 매출을 인식하려고 합니다. 문제없죠?"
        ),
        "expected_docs": ["B19⑵", "B19⑴"],
        "criteria": [
            "유의적 관여 여부 꼬리질문",
            "진행률 제외 + 마진 0% 원칙 설명",
        ],
    },
    {
        "id": "SECTION-8",
        "group": "섹션별 커버리지",
        "title": "유의적인 금융요소 (선수금)",
        "message": (
            "고객과 3년간의 IT 시스템 유지보수 계약을 맺고, 오늘 3년 치 대금 3천만 원을 "
            "한 번에 선불로 다 받았습니다. 재화 이전 시점과 돈 받는 시점이 1년을 초과해서 "
            "차이가 나니까 무조건 이자비용을 인식해서 거래가격을 조정(유의적인 금융요소)"
            "해야 하죠?"
        ),
        "expected_docs": ["60~63", "62⑶", "63"],
        "criteria": [
            "상업적 목적 vs 금융 목적 꼬리질문",
            "예외 적용 가능 설명",
        ],
    },
    {
        "id": "SECTION-9",
        "group": "섹션별 커버리지",
        "title": "고객의 권리 (중요한 권리 vs 마케팅)",
        "message": (
            "오늘 10만 원짜리 화장품 세트를 구매한 고객에게 다음번 구매 시 사용할 수 있는 "
            "'30% 할인 쿠폰'을 지급했습니다. 쿠폰을 줬으니 10만 원 중 일부 금액을 떼어서 "
            "계약부채(이연수익)로 잡아둬야 하나요?"
        ),
        "expected_docs": ["B39~B41", "B40", "B41"],
        "criteria": [
            "구매자 한정 vs 일반 고객 꼬리질문",
            "중요한 권리 판단 기준 설명",
        ],
    },
    {
        "id": "SECTION-10",
        "group": "섹션별 커버리지",
        "title": "계약의 결합 (특수관계자)",
        "message": (
            "A사와 제품 공급 계약을 체결하고, 일주일 뒤 A사의 100% 자회사인 B사와 해당 "
            "제품에 대한 3년짜리 유지보수 계약을 맺었습니다. 계약서도 2장이고 맺은 회사"
            "(법인)도 다르니까 무조건 개별 계약으로 분리해서 각각 수익을 인식하면 되겠죠?"
        ),
        "expected_docs": ["17", "17⑴", "17⑵"],
        "criteria": [
            "일괄 협상/대가 상호의존성 꼬리질문",
            "결합 vs 개별 조건별 정답",
        ],
    },
    {
        "id": "SECTION-11",
        "group": "섹션별 커버리지",
        "title": "계약의 식별 (가공매출/회수가능성)",
        "message": (
            "이번 연말에 목표 실적을 채워야 해서, 평소 거래하던 도매처에 물건을 대량으로 "
            "출고했습니다. 도매처 사정이 안 좋아서 대금 지급은 무기한 보류하기로 합의서까지 "
            "썼습니다. 일단 세금계산서도 끊었고 물건도 인도했으니 이번 연도 매출로 100% "
            "인식해도 되죠?"
        ),
        "expected_docs": ["9", "9⑷", "9⑸", "15", "16"],
        "criteria": [
            "회수 가능성 꼬리질문",
            "수익 인식 불가 결론 (감리 지적 위험 경고)",
        ],
    },
    {
        "id": "SECTION-12",
        "group": "섹션별 커버리지",
        "title": "기간에 걸쳐 vs 한 시점 (창정비)",
        "message": (
            "고객이 소유한 대형 군용 장비를 저희 공장으로 가져와서 2년 동안 부품도 교체하고 "
            "성능을 전면 개량하는 정비 용역을 수행하고 있습니다. 2년 뒤에 정비가 완벽히 "
            "끝나서 고객에게 인도할 때 한 번에 일괄로 매출을 인식하려고 하는데 문제없나요?"
        ),
        "expected_docs": ["35", "35⑵", "35⑶", "38"],
        "criteria": [
            "고객 자산 통제 여부 꼬리질문",
            "기간에 걸쳐 인식 원칙 설명",
        ],
    },
    {
        "id": "SECTION-13",
        "group": "섹션별 커버리지",
        "title": "수행의무 식별 (ESS 계약 쪼개기)",
        "message": (
            "고객에게 특수 장비인 에너지저장장치(ESS)를 납품하는 계약 1건과, 그 장비를 "
            "설치 및 시운전하는 계약 1건을 별도의 문서로 각각 체결했습니다. 계약서가 2개로 "
            "나뉘어 있으니, 일단 장비를 공장 상차 조건으로 출고한 오늘, 납품 계약에 대한 "
            "수익을 먼저 앞당겨 인식해도 되나요?"
        ),
        "expected_docs": ["27", "29", "30"],
        "criteria": [
            "상호관련성 꼬리질문",
            "단일 수행의무 결합 원칙 설명",
        ],
    },
    {
        "id": "SECTION-14",
        "group": "섹션별 커버리지",
        "title": "보증 (확신 vs 용역 유형)",
        "message": (
            "저희가 판매하는 기계에 대해 국내 거래처에는 기본적으로 3년간 무상 부품 교체와 "
            "수리를 해주는 A/S 보증을 제공합니다. 이 보증 부분의 금액을 따로 떼어내서"
            "(계약부채) 3년 동안 수익으로 나눠서 인식해야 하는 것 맞죠?"
        ),
        "expected_docs": ["B29~B33", "B29", "B30", "B31"],
        "criteria": [
            "확신 vs 용역 유형 구분 꼬리질문",
            "충당부채 vs 이연수익 조건별 정답",
        ],
    },
    {
        "id": "SECTION-15",
        "group": "섹션별 커버리지",
        "title": "계약체결 증분원가 (수주 비용)",
        "message": (
            "대형 프로젝트를 수주하기 위해 외부 법무법인에 실사 수수료로 1,500만 원을 "
            "썼고, 최종적으로 수주에 성공해서 저희 영업사원에게 인센티브로 1,000만 원을 "
            "지급했습니다. 이 총 2,500만 원을 전부 '계약자산(또는 선급비용)'으로 잡아두고 "
            "공사 기간 동안 나눠서 상각해도 되나요?"
        ),
        "expected_docs": ["91~93", "94", "99"],
        "criteria": [
            "증분원가 분리 판단 (법률비용 vs 인센티브)",
            "법률비용 즉시 비용, 인센티브 자산화 결론",
        ],
    },
    {
        "id": "SECTION-16",
        "group": "섹션별 커버리지",
        "title": "할인액 배분 (렌탈)",
        "message": (
            "정수기 렌탈 기기(제품매출)와 방문 관리(용역매출)를 묶어서 3년 약정으로 "
            "팔았습니다. 원래 따로 팔면 총 150만 원인데 묶음 할인으로 120만 원에 "
            "계약했어요. 어차피 렌탈 관리가 주 목적이니까, 할인해 준 30만 원은 전부 "
            "'방문 관리(용역매출)' 대가에서만 깎아서 회계처리해도 문제없죠?"
        ),
        "expected_docs": ["81", "82"],
        "criteria": [
            "명백한 관측 증거 꼬리질문",
            "비례 배분 원칙 설명",
        ],
    },
    {
        "id": "SECTION-17",
        "group": "섹션별 커버리지",
        "title": "반품권이 있는 판매 (신제품)",
        "message": (
            "이번에 완전히 새로운 기술이 적용된 신제품 100개를 고객들에게 인도하고 대금을 "
            "전액 수취했습니다. 고객 만족을 위해 3개월 내 무조건 반품 가능 조건을 "
            "걸어두었습니다. 물건은 이미 넘어갔으니 일단 100개 모두 매출로 잡고, 나중에 "
            "반품 들어오면 그때 수익을 취소하면 되나요?"
        ),
        "expected_docs": ["B20~B27", "B21", "B23", "55~58"],
        "criteria": [
            "반품률 추정 가능성 꼬리질문",
            "추정 불가 시 환불부채 전액 처리 설명",
        ],
    },
    {
        "id": "SECTION-18",
        "group": "섹션별 커버리지",
        "title": "계약자산과 계약부채 표시 (순액 상계)",
        "message": (
            "국방부와 대형 무기 체계 개발 프로젝트(진행기준 적용)를 진행 중입니다. "
            "동일한 계약인데, 저희가 기성 청구를 해서 받을 돈(매출채권) 100억 원이 있고, "
            "초기에 미리 받은 선수금 50억 원이 장부에 남아있습니다. 회사 내부 지급규칙에 "
            "따라 두 개를 퉁치지 않고 자산 100억, 부채 50억으로 각각 총액으로 재무상태표에 "
            "표시해도 될까요?"
        ),
        "expected_docs": ["105", "106", "107", "108"],
        "criteria": [
            "동일 계약 여부 꼬리질문",
            "순액 상계 원칙 설명",
        ],
    },
    {
        "id": "SECTION-19",
        "group": "섹션별 커버리지",
        "title": "계약이행원가 (교육훈련비)",
        "message": (
            "저희가 3년짜리 IT 아웃소싱 용역을 수주했습니다. 성공적인 용역 제공을 위해 "
            "투입될 저희 직원들을 대상으로 대대적인 '소프트웨어 코딩 교육'을 실시하고 "
            "5천만 원을 썼습니다. 이 교육비는 계약을 이행하기 위해 쓴 돈이니까 "
            "'계약이행원가(자산)'로 잡고 3년간 상각처리 할 수 있죠?"
        ),
        "expected_docs": ["95", "95⑴~⑶", "96", "98"],
        "criteria": [
            "타 기준서(IAS 38) 우선 적용 지적",
            "교육훈련비 즉시 비용 처리 결론",
        ],
    },
    {
        "id": "SECTION-20",
        "group": "섹션별 커버리지",
        "title": "잔여접근법 적용 한계",
        "message": (
            "총 105원짜리 계약에서 A, B, C, D 네 가지 제품을 묶어 팝니다. "
            "A, B, C는 평소 개별 판매가격의 합계가 딱 100원이라는 걸 압니다. "
            "근데 D는 가격 변동이 심해서 얼마인지 몰라요. "
            "그러니까 '잔여접근법'을 써서 (총대가 105원 - A,B,C 100원) = 5원을 "
            "제품 D의 가격으로 배분해서 수익 잡으면 되죠?"
        ),
        "expected_docs": ["76~79", "79⑶", "78"],
        "criteria": [
            "5원이 합리적 범위인지 꼬리질문",
            "가치 충실성 위배 시 대안 기법 설명",
        ],
    },
]


# ── 단일 호출 ───────────────────────────────────────────────────────────────────


def call_chat(message: str) -> tuple[dict[str, Any], float]:
    """POST /chat 호출 → (done_event, response_time_sec)

    SSE 스트리밍을 line-by-line으로 소비하여 done 이벤트를 추출한다.
    stream 모드로 읽어야 서버가 스트림을 닫을 때까지 blocking되지 않는다.
    """
    start = time.time()
    done_event: dict[str, Any] | None = None
    error_msg: str | None = None

    with httpx.Client(timeout=httpx.Timeout(TIMEOUT, connect=10)) as client:
        with client.stream(
            "POST",
            f"{BASE_URL}/chat",
            json={"message": message},
            headers={"Accept": "text/event-stream"},
        ) as resp:
            for line in resp.iter_lines():
                line = line.strip()
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "done":
                    done_event = event
                elif event.get("type") == "error":
                    error_msg = event.get("message", "unknown error")

    elapsed = time.time() - start

    if done_event:
        return done_event, elapsed
    if error_msg:
        return {"type": "error", "message": error_msg}, elapsed
    return {"type": "error", "message": "no done event received"}, elapsed


# ── 결과 저장/로드 (중단 재개용) ──────────────────────────────────────────────────


def load_results() -> list[dict[str, Any]]:
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    return []


def save_results(results: list[dict[str, Any]]) -> None:
    RESULTS_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def already_done(results: list[dict[str, Any]], test_id: str, run: int) -> bool:
    """이미 완료된 (test_id, run) 쌍인지 확인."""
    return any(
        r["test_id"] == test_id and r["run"] == run
        for r in results
    )


# ── 메인 실행 ───────────────────────────────────────────────────────────────────


def run_tests() -> None:
    results = load_results()
    total = len(TEST_CASES) * RUNS_PER_CASE
    done_count = len(results)

    print(f"=== K-IFRS 1115 품질 테스트 시작 ===")
    print(f"총 {total}회 호출 (이미 완료: {done_count}회)")
    print()

    for case in TEST_CASES:
        for run in range(1, RUNS_PER_CASE + 1):
            if already_done(results, case["id"], run):
                print(f"  [SKIP] {case['id']} run {run}")
                continue

            print(f"  [{case['id']}] run {run}/{RUNS_PER_CASE} ... ", end="", flush=True)
            try:
                event, elapsed = call_chat(case["message"])
            except Exception as e:
                event = {"type": "error", "message": str(e)}
                elapsed = 0.0

            result = {
                "test_id": case["id"],
                "run": run,
                "group": case["group"],
                "title": case["title"],
                "response_time": round(elapsed, 2),
                "answer_text": event.get("text", ""),
                "cited_paragraphs": event.get("cited_paragraphs", []),
                "follow_up_questions": event.get("follow_up_questions", []),
                "is_conclusion": event.get("is_conclusion", False),
                "findings_case": event.get("findings_case"),
                "is_situation": event.get("is_situation", False),
                "matched_topic_keys": event.get("matched_topic_keys", []),
                "selected_branches": event.get("selected_branches", []),
                "retrieved_docs": _summarize_docs(event.get("retrieved_docs", [])),
                "error": event.get("message") if event.get("type") == "error" else None,
            }

            results.append(result)
            save_results(results)

            status = "ERROR" if result["error"] else "OK"
            print(f"{status} ({elapsed:.1f}s)")

    print()
    print(f"=== 테스트 완료: {len(results)}/{total}회 ===")
    print(f"결과 파일: {RESULTS_FILE}")


def _summarize_docs(docs: list[dict] | None) -> list[dict[str, str]]:
    """retrieved_docs에서 source, chunk_id, hierarchy만 추출하여 경량화."""
    if not docs:
        return []
    return [
        {
            "source": d.get("source", ""),
            "chunk_id": d.get("chunk_id", ""),
            "hierarchy": d.get("hierarchy", ""),
        }
        for d in docs
    ]


# ── 채점 & 리포트 ───────────────────────────────────────────────────────────────


def grade_and_report() -> None:
    """quality_results.json을 읽어 채점 리포트를 생성한다."""
    results = load_results()
    if not results:
        print("결과 파일이 없습니다. 먼저 테스트를 실행하세요.")
        return

    # test_id별 그룹핑
    by_test: dict[str, list[dict]] = {}
    for r in results:
        by_test.setdefault(r["test_id"], []).append(r)

    lines: list[str] = []
    lines.append("# K-IFRS 1115 챗봇 품질 테스트 리포트\n")
    lines.append(f"**실행일**: 2026-03-12\n")
    lines.append(f"**총 호출**: {len(results)}회 ({len(by_test)}개 케이스 × {RUNS_PER_CASE}회)\n")
    lines.append("")

    # ── 요약 통계 ────────────────────────────────────────────────────────────────
    all_times = [r["response_time"] for r in results if not r.get("error")]
    if all_times:
        lines.append("## 응답 시간 통계\n")
        lines.append(f"| 지표 | 값 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 평균 | {sum(all_times)/len(all_times):.1f}초 |")
        lines.append(f"| 최소 | {min(all_times):.1f}초 |")
        lines.append(f"| 최대 | {max(all_times):.1f}초 |")
        lines.append(f"| 에러 | {sum(1 for r in results if r.get('error'))}건 |")
        lines.append("")

    # ── 케이스별 상세 ────────────────────────────────────────────────────────────
    lines.append("## 케이스별 상세\n")

    # 테스트 케이스 메타데이터 매핑
    case_meta = {c["id"]: c for c in TEST_CASES}

    for test_id in sorted(by_test.keys(), key=_sort_key):
        runs = by_test[test_id]
        meta = case_meta.get(test_id, {})
        times = [r["response_time"] for r in runs if not r.get("error")]

        lines.append(f"### {test_id}: {meta.get('title', '')}\n")
        lines.append(f"**그룹**: {meta.get('group', '')}\n")

        if times:
            lines.append(f"**응답시간**: 평균 {sum(times)/len(times):.1f}초 "
                         f"(min {min(times):.1f}, max {max(times):.1f})\n")

        # 각 run 요약
        for r in sorted(runs, key=lambda x: x["run"]):
            lines.append(f"#### Run {r['run']}\n")
            if r.get("error"):
                lines.append(f"**ERROR**: {r['error']}\n")
                continue

            # 꼬리질문
            fq = r.get("follow_up_questions", [])
            lines.append(f"- **꼬리질문**: {fq if fq else '없음'}")
            lines.append(f"- **결론 도달**: {'Yes' if r.get('is_conclusion') else 'No'}")
            lines.append(f"- **is_situation**: {'Yes' if r.get('is_situation') else 'No'}")
            lines.append(f"- **감리사례**: {'있음' if r.get('findings_case') else '없음'}")
            lines.append(f"- **인용 문단**: {r.get('cited_paragraphs', [])}")
            lines.append(f"- **매칭 토픽**: {r.get('matched_topic_keys', [])}")
            lines.append(f"- **선택 분기**: {r.get('selected_branches', [])}")

            # 리트리버 문서
            docs = r.get("retrieved_docs", [])
            if docs:
                doc_summaries = [f"{d.get('source', '')}:{d.get('hierarchy', '')}" for d in docs[:5]]
                lines.append(f"- **검색 문서(상위5)**: {doc_summaries}")

            # 답변 (200자 미리보기)
            answer = r.get("answer_text", "")
            preview = answer[:200].replace("\n", " ") + ("..." if len(answer) > 200 else "")
            lines.append(f"- **답변 미리보기**: {preview}")
            lines.append("")

        # 기대 문서 vs 실제 인용
        expected = meta.get("expected_docs", [])
        if expected:
            # 3회 run에서 나온 모든 인용 문단 합집합
            all_cited = set()
            for r in runs:
                for p in r.get("cited_paragraphs", []) or []:
                    all_cited.add(p)
            lines.append(f"**기대 문서**: {expected}")
            lines.append(f"**실제 인용(합집합)**: {sorted(all_cited)}")
            lines.append("")

        # 채점기준
        criteria = meta.get("criteria", [])
        if criteria:
            lines.append("**채점기준**:")
            for c in criteria:
                lines.append(f"- [ ] {c}")
            lines.append("")

        lines.append("---\n")

    # ── 파일 저장 ────────────────────────────────────────────────────────────────
    report = "\n".join(lines)
    REPORT_FILE.write_text(report, encoding="utf-8")
    print(f"리포트 생성 완료: {REPORT_FILE}")


def _sort_key(test_id: str) -> tuple[int, int]:
    """TEST-0~5 → (0, n), SECTION-1~20 → (1, n) 순서로 정렬."""
    if test_id.startswith("TEST-"):
        return (0, int(test_id.split("-")[1]))
    elif test_id.startswith("SECTION-"):
        return (1, int(test_id.split("-")[1]))
    return (2, 0)


# ── 엔트리 포인트 ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "report":
        # 채점 리포트만 생성
        grade_and_report()
    else:
        # 테스트 실행 → 리포트 생성
        run_tests()
        grade_and_report()

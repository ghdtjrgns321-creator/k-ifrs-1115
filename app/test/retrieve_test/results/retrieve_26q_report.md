# Retrieve 검증 리포트 (26개 케이스)

**실행일**: 2026-03-16 10:59

## 요약

| ID | 제목 | 토픽 매칭 | PP | RT | Merged | LLM | Hit Rate | 누락 |
|---|---|---|---:|---:|---:|---:|---|---|
| TEST-0 | 핵심사례 — 본인 vs 대리인(위탁판매) | 본인 vs 대리인, 거래가격 배분 +1 | 46 | 46 | 87 | 87 | 3/5 | B77, IE239~IE243 |
| TEST-1 | 단순 이론 질의 — 불필요 꼬리질문 방어 |  | 0 | 53 | 51 | 51 | 4/4 |  |
| TEST-2 | 완결된 복합 사례 — 불필요 체크리스트 방어 | 변동대가, 거래가격의 후속 변동 +1 | 40 | 43 | 82 | 82 | 2/2 |  |
| TEST-3 | 신종/하이브리드 사업 — Gray Area 경 | 변동대가, 신종 비즈니스 및 복합 쟁점 (Gray Ar | 31 | 44 | 71 | 71 | 2/2 |  |
| TEST-4 | 정보 부족 — 꼬리질문 필수 (라이선스) | 거래가격 배분, 기간에 걸쳐 vs 한 시점 인식 +1 | 42 | 46 | 81 | 81 | 4/4 |  |
| TEST-5 | 오도된 질문 — 단호히 비용 처리 | 계약체결 증분원가, 계약의 식별 +1 | 35 | 56 | 70 | 70 | 2/2 |  |
| SECTION-1 | 라이선싱 (접근권 vs 사용권) | 기간에 걸쳐 vs 한 시점 인식, 라이선싱 +1 | 52 | 56 | 97 | 97 | 3/3 |  |
| SECTION-2 | 계약변경 (별도 계약 vs 기존 계약 수정) | 거래가격 배분, 수행의무 식별 +1 | 42 | 44 | 79 | 79 | 3/3 |  |
| SECTION-3 | 본인 대 대리인 (SW 유통) | 본인 vs 대리인, 기간에 걸쳐 vs 한 시점 인식 + | 55 | 54 | 98 | 98 | 2/2 |  |
| SECTION-4 | 미인도청구약정 (Bill-and-Hold) | 미인도청구약정, 고객의 인수 +1 | 31 | 64 | 74 | 74 | 2/2 |  |
| SECTION-5 | 재매입약정 (콜옵션) | 재매입약정, 수행의무 식별 +1 | 40 | 55 | 81 | 81 | 3/3 |  |
| SECTION-6 | 고객에게 지급할 대가 | 고객에게 지급할 대가, 본인 vs 대리인 +1 | 43 | 59 | 89 | 89 | 2/2 |  |
| SECTION-7 | 진행률 측정 (미설치 고가 자재) | 진행률 측정, 기간에 걸쳐 vs 한 시점 인식 +1 | 41 | 51 | 86 | 86 | 2/2 |  |
| SECTION-8 | 유의적인 금융요소 (선수금) | 유의적인 금융요소, 기간에 걸쳐 vs 한 시점 인식 + | 48 | 59 | 92 | 92 | 3/3 |  |
| SECTION-9 | 고객의 권리 (중요한 권리 vs 마케팅) | 거래가격 배분, 변동대가 +1 | 39 | 43 | 81 | 81 | 0/3 | B39~B41, B40, B41 |
| SECTION-10 | 계약의 결합 (특수관계자) | 수행의무 식별, 계약의 식별 +1 | 36 | 51 | 79 | 79 | 3/3 |  |
| SECTION-11 | 계약의 식별 (가공매출/회수가능성) | 계약의 식별, 기간에 걸쳐 vs 한 시점 인식 +1 | 39 | 58 | 80 | 80 | 5/5 |  |
| SECTION-12 | 기간에 걸쳐 vs 한 시점 (창정비) | 기간에 걸쳐 vs 한 시점 인식, 고객의 인수 +1 | 33 | 54 | 79 | 79 | 4/4 |  |
| SECTION-13 | 수행의무 식별 (ESS 계약 쪼개기) | 기간에 걸쳐 vs 한 시점 인식, 계약의 식별 +1 | 50 | 54 | 96 | 96 | 3/3 |  |
| SECTION-14 | 보증 (확신 vs 용역 유형) | 보증, 거래가격 배분 +1 | 32 | 49 | 69 | 69 | 4/4 |  |
| SECTION-15 | 계약체결 증분원가 (수주 비용) | 계약이행원가, 계약체결 증분원가 +1 | 28 | 59 | 69 | 69 | 3/3 |  |
| SECTION-16 | 할인액 배분 (렌탈) | 할인액의 배분, 수행의무 식별 +1 | 26 | 47 | 64 | 64 | 2/2 |  |
| SECTION-17 | 반품권이 있는 판매 (신제품) | 반품권이 있는 판매, 변동대가 +1 | 50 | 56 | 93 | 93 | 4/4 |  |
| SECTION-18 | 계약자산과 계약부채 표시 (순액 상계) | 표시, 계약의 식별 +1 | 49 | 66 | 97 | 97 | 4/4 |  |
| SECTION-19 | 계약이행원가 (교육훈련비) | 계약체결 증분원가, 계약이행원가 +1 | 34 | 57 | 73 | 73 | 4/4 |  |
| SECTION-20 | 잔여접근법 적용 한계 | 거래가격 배분, 변동대가 +1 | 35 | 43 | 74 | 74 | 3/3 |  |

**전체 Hit Rate: 76/81 (94%)**

## 케이스별 상세

### TEST-0: 핵심사례 — 본인 vs 대리인(위탁판매)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['본인 vs 대리인', '거래가격 배분', '계약의 식별']
- **Pinpoint (46건)**:
  - IE사례: 12건 (1115-IE-case-46, 1115-IE-case-46A, 1115-IE-case-47 +2)
  - QNA: 9건 (QNA-SSI-36941_pinpoint, QNA-SSI-38695_pinpoint, QNA-221109A_pinpoint +2)
  - 감리사례: 10건 (FSS-CASE-2024-2505-03_pinpoint, FSS-CASE-2024-2409-02_pinpoint, FSS-CASE-2022-2311-03_pinpoint +2)
  - 교육자료: 1건 (EDU-KASB-BC46_pinpoint)
  - 본문/적용지침: 14건 (1115-6, 1115-9, 1115-15 +2)
- **Retriever (46건)**:
  - IE사례: 10건
  - QNA: 4건
  - 감리사례: 2건
  - 본문/적용지침: 30건
- **Merged→LLM**: 87건 → 87건
- **Expected docs hit**: 3/5 — hits=['B34~B38', 'B35', 'IE231~IE233'], misses=['B77', 'IE239~IE243']

### TEST-1: 단순 이론 질의 — 불필요 꼬리질문 방어

- **routing**: IN | **is_situation**: False | **needs_calc**: False
- **matched_topics**: []
- **Retriever (53건)**:
  - IE사례: 10건
  - QNA: 12건
  - 감리사례: 1건
  - 본문/적용지침: 30건
- **Merged→LLM**: 51건 → 51건
- **Expected docs hit**: 4/4 — hits=['50~52', '53', '56~58', '55'], misses=[]

### TEST-2: 완결된 복합 사례 — 불필요 체크리스트 방어

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['변동대가', '거래가격의 후속 변동', '수행의무 식별']
- **Pinpoint (40건)**:
  - IE사례: 9건 (1115-IE-case-20, 1115-IE-case-21, 1115-IE-case-23 +2)
  - QNA: 12건 (QNA-SSI-202312058_pinpoint, QNA-SSI-202312048_pinpoint, QNA-SSI-38465_pinpoint +2)
  - 감리사례: 2건 (FSS-CASE-2023-2405-01_pinpoint, FSS-CASE-2023-2405-06_pinpoint)
  - 본문/적용지침: 17건 (1115-24, 1115-25, 1115-27 +2)
- **Retriever (43건)**:
  - IE사례: 8건
  - QNA: 5건
  - 본문/적용지침: 30건
- **Merged→LLM**: 82건 → 82건
- **Expected docs hit**: 2/2 — hits=['50~56', '87~89'], misses=[]

### TEST-3: 신종/하이브리드 사업 — Gray Area 경고

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['변동대가', '신종 비즈니스 및 복합 쟁점 (Gray Area)', '거래가격 배분']
- **Pinpoint (31건)**:
  - IE사례: 6건 (1115-IE-case-20, 1115-IE-case-21, 1115-IE-case-23 +2)
  - QNA: 7건 (QNA-SSI-202312058_pinpoint, QNA-SSI-202312048_pinpoint, QNA-SSI-38465_pinpoint +2)
  - 감리사례: 2건 (FSS-CASE-2023-2405-01_pinpoint, FSS-CASE-2024-2505-04_pinpoint)
  - 본문/적용지침: 16건 (1115-6, 1115-47, 1115-50 +2)
- **Retriever (44건)**:
  - IE사례: 5건
  - QNA: 7건
  - 감리사례: 2건
  - 본문/적용지침: 30건
- **Merged→LLM**: 71건 → 71건
- **Expected docs hit**: 2/2 — hits=['6', '9'], misses=[]

### TEST-4: 정보 부족 — 꼬리질문 필수 (라이선스)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['거래가격 배분', '기간에 걸쳐 vs 한 시점 인식', '라이선싱']
- **Pinpoint (42건)**:
  - IE사례: 9건 (1115-IE-case-33, 1115-IE-case-34, 1115-IE-case-13 +2)
  - QNA: 10건 (QNA-SSI-38671_pinpoint, QNA-2017-I-KAQ015_pinpoint, QNA-2017-I-KQA014_pinpoint +2)
  - 감리사례: 5건 (FSS-CASE-2024-2505-04_pinpoint, KICPA-CASE-2025-07_pinpoint, FSS-CASE-2023-2405-05_pinpoint +2)
  - 교육자료: 1건 (EDU-KASB-180426_pinpoint)
  - 본문/적용지침: 17건 (1115-35, 1115-37, 1115-38 +2)
- **Retriever (46건)**:
  - IE사례: 20건
  - QNA: 5건
  - 감리사례: 1건
  - 본문/적용지침: 20건
- **Merged→LLM**: 81건 → 81건
- **Expected docs hit**: 4/4 — hits=['B54~B63', 'B56', 'B58', 'B61'], misses=[]

### TEST-5: 오도된 질문 — 단호히 비용 처리

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['계약체결 증분원가', '계약의 식별', '계약이행원가']
- **Pinpoint (35건)**:
  - IE사례: 6건 (1115-IE-case-36, 1115-IE-case-37, 1115-IE-case-2 +2)
  - QNA: 10건 (QNA-SSI-38676_pinpoint, QNA-SSI-202511018_pinpoint, QNA-SSI-35584_pinpoint +2)
  - 감리사례: 5건 (FSS-CASE-2024-2505-02_pinpoint, FSS-CASE-2025-2512-01_pinpoint, FSS-CASE-2024-2409-01_pinpoint +2)
  - 교육자료: 1건 (EDU-KASB-BC46_pinpoint)
  - 본문/적용지침: 13건 (1115-6, 1115-9, 1115-15 +2)
- **Retriever (56건)**:
  - IE사례: 8건
  - QNA: 15건
  - 감리사례: 7건
  - 교육자료: 1건
  - 본문/적용지침: 25건
- **Merged→LLM**: 70건 → 70건
- **Expected docs hit**: 2/2 — hits=['91~93', '94'], misses=[]

### SECTION-1: 라이선싱 (접근권 vs 사용권)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['기간에 걸쳐 vs 한 시점 인식', '라이선싱', '계약의 식별']
- **Pinpoint (52건)**:
  - IE사례: 11건 (1115-IE-case-13, 1115-IE-case-14, 1115-IE-case-16 +2)
  - QNA: 13건 (QNA-2017-I-KAQ015_pinpoint, QNA-2017-I-KQA014_pinpoint, QNA-2020-I-KQA003_pinpoint +2)
  - 감리사례: 9건 (KICPA-CASE-2025-07_pinpoint, FSS-CASE-2023-2405-05_pinpoint, FSS-CASE-2023-2405-06_pinpoint +2)
  - 교육자료: 2건 (EDU-KASB-180426_pinpoint, EDU-KASB-BC46_pinpoint)
  - 본문/적용지침: 17건 (1115-6, 1115-9, 1115-15 +2)
- **Retriever (56건)**:
  - IE사례: 18건
  - QNA: 11건
  - 감리사례: 5건
  - 본문/적용지침: 22건
- **Merged→LLM**: 97건 → 97건
- **Expected docs hit**: 3/3 — hits=['B54~B63', 'B58', 'B61'], misses=[]

### SECTION-2: 계약변경 (별도 계약 vs 기존 계약 수정)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['거래가격 배분', '수행의무 식별', '계약의 식별']
- **Pinpoint (42건)**:
  - IE사례: 9건 (1115-IE-case-33, 1115-IE-case-34, 1115-IE-case-11 +2)
  - QNA: 10건 (QNA-SSI-38671_pinpoint, QNA-2018-I-KQA009_pinpoint, QNA-SSI-35609_pinpoint +2)
  - 감리사례: 7건 (FSS-CASE-2024-2505-04_pinpoint, FSS-CASE-2023-2405-06_pinpoint, FSS-CASE-2024-2505-02_pinpoint +2)
  - 교육자료: 1건 (EDU-KASB-BC46_pinpoint)
  - 본문/적용지침: 15건 (1115-6, 1115-9, 1115-15 +2)
- **Retriever (44건)**:
  - IE사례: 5건
  - QNA: 6건
  - 감리사례: 3건
  - 본문/적용지침: 30건
- **Merged→LLM**: 79건 → 79건
- **Expected docs hit**: 3/3 — hits=['18~21', '20', '21⑴'], misses=[]

### SECTION-3: 본인 대 대리인 (SW 유통)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['본인 vs 대리인', '기간에 걸쳐 vs 한 시점 인식', '계약의 식별']
- **Pinpoint (55건)**:
  - IE사례: 13건 (1115-IE-case-46, 1115-IE-case-46A, 1115-IE-case-47 +2)
  - QNA: 13건 (QNA-SSI-36941_pinpoint, QNA-SSI-38695_pinpoint, QNA-221109A_pinpoint +2)
  - 감리사례: 12건 (FSS-CASE-2024-2505-03_pinpoint, FSS-CASE-2024-2409-02_pinpoint, FSS-CASE-2022-2311-03_pinpoint +2)
  - 교육자료: 2건 (EDU-KASB-180426_pinpoint, EDU-KASB-BC46_pinpoint)
  - 본문/적용지침: 15건 (1115-6, 1115-9, 1115-15 +2)
- **Retriever (54건)**:
  - IE사례: 13건
  - QNA: 11건
  - 감리사례: 3건
  - 본문/적용지침: 27건
- **Merged→LLM**: 98건 → 98건
- **Expected docs hit**: 2/2 — hits=['B34~B38', 'B35'], misses=[]

### SECTION-4: 미인도청구약정 (Bill-and-Hold)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['미인도청구약정', '고객의 인수', '본인 vs 대리인']
- **Pinpoint (31건)**:
  - IE사례: 7건 (1115-IE-case-63, 1115-IE-case-46, 1115-IE-case-46A +2)
  - QNA: 7건 (QNA-SSI-36949_pinpoint, QNA-SSI-38679_pinpoint, QNA-SSI-38611_pinpoint +2)
  - 감리사례: 5건 (FSS-CASE-2023-2405-05_pinpoint, FSS-CASE-2024-2505-03_pinpoint, FSS-CASE-2024-2409-02_pinpoint +2)
  - 본문/적용지침: 12건 (1115-38, 1115-B35, 1115-B36 +2)
- **Retriever (64건)**:
  - IE사례: 12건
  - QNA: 17건
  - 감리사례: 8건
  - 교육자료: 1건
  - 본문/적용지침: 26건
- **Merged→LLM**: 74건 → 74건
- **Expected docs hit**: 2/2 — hits=['B79~B82', 'B81'], misses=[]

### SECTION-5: 재매입약정 (콜옵션)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['재매입약정', '수행의무 식별', '기간에 걸쳐 vs 한 시점 인식']
- **Pinpoint (40건)**:
  - IE사례: 7건 (1115-IE-case-62, 1115-IE-case-11, 1115-IE-case-10 +2)
  - QNA: 13건 (QNA-SSI-202412042_pinpoint, QNA-SSI-36951_pinpoint, QNA-2020-I-KQA006_pinpoint +2)
  - 감리사례: 4건 (FSS-CASE-2022-2311-03_pinpoint, FSS-CASE-2023-2405-06_pinpoint, KICPA-CASE-2025-07_pinpoint +1)
  - 교육자료: 2건 (EDU-KASB-181114_pinpoint, EDU-KASB-180426_pinpoint)
  - 본문/적용지침: 14건 (1115-24, 1115-25, 1115-27 +2)
- **Retriever (55건)**:
  - IE사례: 7건
  - QNA: 15건
  - 감리사례: 6건
  - 교육자료: 1건
  - 본문/적용지침: 26건
- **Merged→LLM**: 81건 → 81건
- **Expected docs hit**: 3/3 — hits=['B64~B76', 'B66', 'B68'], misses=[]

### SECTION-6: 고객에게 지급할 대가

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['고객에게 지급할 대가', '본인 vs 대리인', '라이선싱']
- **Pinpoint (43건)**:
  - IE사례: 11건 (1115-IE-case-32, 1115-IE-case-46, 1115-IE-case-46A +2)
  - QNA: 13건 (QNA-SSI-35617_pinpoint, QNA-SSI-202511020_pinpoint, QNA-SSI-36964_pinpoint +2)
  - 감리사례: 6건 (KICPA-CASE-2024-28_pinpoint, FSS-CASE-2024-2505-03_pinpoint, FSS-CASE-2024-2409-02_pinpoint +2)
  - 본문/적용지침: 13건 (1115-6, 1115-70, 1115-71 +2)
- **Retriever (59건)**:
  - IE사례: 10건
  - QNA: 15건
  - 감리사례: 4건
  - 본문/적용지침: 30건
- **Merged→LLM**: 89건 → 89건
- **Expected docs hit**: 2/2 — hits=['70~72', '71'], misses=[]

### SECTION-7: 진행률 측정 (미설치 고가 자재)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['진행률 측정', '기간에 걸쳐 vs 한 시점 인식', '수행의무 식별']
- **Pinpoint (41건)**:
  - IE사례: 8건 (1115-IE-case-18, 1115-IE-case-19, 1115-IE-case-13 +2)
  - QNA: 14건 (QNA-SSI-202506004_pinpoint, QNA-202504C_pinpoint, QNA-SSI-38698_pinpoint +2)
  - 감리사례: 4건 (KICPA-CASE-2025-07_pinpoint, KICPA-CASE-2025-33_pinpoint, FSS-CASE-2023-2405-05_pinpoint +1)
  - 교육자료: 1건 (EDU-KASB-180426_pinpoint)
  - 본문/적용지침: 14건 (1115-24, 1115-25, 1115-27 +2)
- **Retriever (51건)**:
  - IE사례: 20건
  - QNA: 8건
  - 감리사례: 3건
  - 본문/적용지침: 20건
- **Merged→LLM**: 86건 → 86건
- **Expected docs hit**: 2/2 — hits=['B19⑵', 'B19⑴'], misses=[]

### SECTION-8: 유의적인 금융요소 (선수금)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['유의적인 금융요소', '기간에 걸쳐 vs 한 시점 인식', '계약의 식별']
- **Pinpoint (48건)**:
  - IE사례: 12건 (1115-IE-case-26, 1115-IE-case-29, 1115-IE-case-28 +2)
  - QNA: 10건 (QNA-SSI-36991_pinpoint, QNA-2017-I-KAQ015_pinpoint, QNA-2017-I-KQA014_pinpoint +2)
  - 감리사례: 8건 (KICPA-CASE-2025-07_pinpoint, FSS-CASE-2023-2405-05_pinpoint, FSS-CASE-2023-2405-06_pinpoint +2)
  - 교육자료: 2건 (EDU-KASB-180426_pinpoint, EDU-KASB-BC46_pinpoint)
  - 본문/적용지침: 16건 (1115-6, 1115-9, 1115-15 +2)
- **Retriever (59건)**:
  - IE사례: 13건
  - QNA: 15건
  - 감리사례: 9건
  - 교육자료: 1건
  - 본문/적용지침: 21건
- **Merged→LLM**: 92건 → 92건
- **Expected docs hit**: 3/3 — hits=['60~63', '62⑶', '63'], misses=[]

### SECTION-9: 고객의 권리 (중요한 권리 vs 마케팅)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['거래가격 배분', '변동대가', '표시']
- **Pinpoint (39건)**:
  - IE사례: 9건 (1115-IE-case-33, 1115-IE-case-34, 1115-IE-case-20 +2)
  - QNA: 10건 (QNA-SSI-38671_pinpoint, QNA-SSI-202312058_pinpoint, QNA-SSI-202312048_pinpoint +2)
  - 감리사례: 3건 (FSS-CASE-2024-2505-04_pinpoint, FSS-CASE-2023-2405-01_pinpoint, KICPA-CASE-2025-33_pinpoint)
  - 본문/적용지침: 17건 (1115-47, 1115-50, 1115-51 +2)
- **Retriever (43건)**:
  - IE사례: 7건
  - QNA: 6건
  - 본문/적용지침: 30건
- **Merged→LLM**: 81건 → 81건
- **Expected docs hit**: 0/3 — hits=[], misses=['B39~B41', 'B40', 'B41']

### SECTION-10: 계약의 결합 (특수관계자)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['수행의무 식별', '계약의 식별', '계약의 결합']
- **Pinpoint (36건)**:
  - IE사례: 7건 (1115-IE-case-11, 1115-IE-case-10, 1115-IE-case-12 +2)
  - QNA: 10건 (QNA-2018-I-KQA009_pinpoint, QNA-SSI-35609_pinpoint, QNA-SSI-36987_pinpoint +2)
  - 감리사례: 7건 (FSS-CASE-2023-2405-06_pinpoint, FSS-CASE-2024-2505-02_pinpoint, FSS-CASE-2025-2512-01_pinpoint +2)
  - 교육자료: 1건 (EDU-KASB-BC46_pinpoint)
  - 본문/적용지침: 11건 (1115-6, 1115-9, 1115-15 +2)
- **Retriever (51건)**:
  - IE사례: 10건
  - QNA: 8건
  - 감리사례: 3건
  - 본문/적용지침: 30건
- **Merged→LLM**: 79건 → 79건
- **Expected docs hit**: 3/3 — hits=['17', '17⑴', '17⑵'], misses=[]

### SECTION-11: 계약의 식별 (가공매출/회수가능성)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['계약의 식별', '기간에 걸쳐 vs 한 시점 인식', '고객의 인수']
- **Pinpoint (39건)**:
  - IE사례: 7건 (1115-IE-case-2, 1115-IE-case-3, 1115-IE-case-1 +2)
  - QNA: 10건 (QNA-SSI-36917_pinpoint, QNA-SSI-36993_pinpoint, QNA-2021-I-KQA008_pinpoint +2)
  - 감리사례: 8건 (FSS-CASE-2024-2505-02_pinpoint, FSS-CASE-2025-2512-01_pinpoint, FSS-CASE-2024-2409-01_pinpoint +2)
  - 교육자료: 2건 (EDU-KASB-BC46_pinpoint, EDU-KASB-180426_pinpoint)
  - 본문/적용지침: 12건 (1115-6, 1115-9, 1115-15 +2)
- **Retriever (58건)**:
  - IE사례: 12건
  - QNA: 15건
  - 감리사례: 11건
  - 교육자료: 1건
  - 본문/적용지침: 19건
- **Merged→LLM**: 80건 → 80건
- **Expected docs hit**: 5/5 — hits=['9', '9⑷', '9⑸', '15', '16'], misses=[]

### SECTION-12: 기간에 걸쳐 vs 한 시점 (창정비)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['기간에 걸쳐 vs 한 시점 인식', '고객의 인수', '수행의무 식별']
- **Pinpoint (33건)**:
  - IE사례: 6건 (1115-IE-case-13, 1115-IE-case-14, 1115-IE-case-16 +2)
  - QNA: 11건 (QNA-2017-I-KAQ015_pinpoint, QNA-2017-I-KQA014_pinpoint, QNA-2020-I-KQA003_pinpoint +2)
  - 감리사례: 3건 (KICPA-CASE-2025-07_pinpoint, FSS-CASE-2023-2405-05_pinpoint, FSS-CASE-2023-2405-06_pinpoint)
  - 교육자료: 1건 (EDU-KASB-180426_pinpoint)
  - 본문/적용지침: 12건 (1115-24, 1115-25, 1115-27 +2)
- **Retriever (54건)**:
  - IE사례: 19건
  - QNA: 11건
  - 감리사례: 4건
  - 본문/적용지침: 20건
- **Merged→LLM**: 79건 → 79건
- **Expected docs hit**: 4/4 — hits=['35', '35⑵', '35⑶', '38'], misses=[]

### SECTION-13: 수행의무 식별 (ESS 계약 쪼개기)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['기간에 걸쳐 vs 한 시점 인식', '계약의 식별', '수행의무 식별']
- **Pinpoint (50건)**:
  - IE사례: 10건 (1115-IE-case-13, 1115-IE-case-14, 1115-IE-case-16 +2)
  - QNA: 14건 (QNA-2017-I-KAQ015_pinpoint, QNA-2017-I-KQA014_pinpoint, QNA-2020-I-KQA003_pinpoint +2)
  - 감리사례: 8건 (KICPA-CASE-2025-07_pinpoint, FSS-CASE-2023-2405-05_pinpoint, FSS-CASE-2023-2405-06_pinpoint +2)
  - 교육자료: 2건 (EDU-KASB-180426_pinpoint, EDU-KASB-BC46_pinpoint)
  - 본문/적용지침: 16건 (1115-6, 1115-9, 1115-15 +2)
- **Retriever (54건)**:
  - IE사례: 20건
  - QNA: 10건
  - 감리사례: 4건
  - 본문/적용지침: 20건
- **Merged→LLM**: 96건 → 96건
- **Expected docs hit**: 3/3 — hits=['27', '29', '30'], misses=[]

### SECTION-14: 보증 (확신 vs 용역 유형)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['보증', '거래가격 배분', '수행의무 식별']
- **Pinpoint (32건)**:
  - IE사례: 6건 (1115-IE-case-44, 1115-IE-case-33, 1115-IE-case-34 +2)
  - QNA: 7건 (QNA-SSI-35609_pinpoint, QNA-SSI-38702_pinpoint, QNA-SSI-38671_pinpoint +2)
  - 감리사례: 3건 (FSS-CASE-2023-2405-05_pinpoint, FSS-CASE-2024-2505-04_pinpoint, FSS-CASE-2023-2405-06_pinpoint)
  - 교육자료: 1건 (EDU-KASB-180517-2_pinpoint)
  - 본문/적용지침: 15건 (1115-24, 1115-25, 1115-27 +2)
- **Retriever (49건)**:
  - IE사례: 10건
  - QNA: 7건
  - 감리사례: 1건
  - 교육자료: 1건
  - 본문/적용지침: 30건
- **Merged→LLM**: 69건 → 69건
- **Expected docs hit**: 4/4 — hits=['B29~B33', 'B29', 'B30', 'B31'], misses=[]

### SECTION-15: 계약체결 증분원가 (수주 비용)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['계약이행원가', '계약체결 증분원가', '표시']
- **Pinpoint (28건)**:
  - IE사례: 5건 (1115-IE-case-36, 1115-IE-case-37, 1115-IE-case-39 +2)
  - QNA: 10건 (QNA-202003D_pinpoint, QNA-SSI-202412041_pinpoint, QNA-201906D_pinpoint +2)
  - 감리사례: 1건 (KICPA-CASE-2025-33_pinpoint)
  - 본문/적용지침: 12건 (1115-91, 1115-92, 1115-93 +2)
- **Retriever (59건)**:
  - IE사례: 10건
  - QNA: 15건
  - 감리사례: 6건
  - 본문/적용지침: 28건
- **Merged→LLM**: 69건 → 69건
- **Expected docs hit**: 3/3 — hits=['91~93', '94', '99'], misses=[]

### SECTION-16: 할인액 배분 (렌탈)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['할인액의 배분', '수행의무 식별', '거래가격 배분']
- **Pinpoint (26건)**:
  - IE사례: 5건 (1115-IE-case-34, 1115-IE-case-11, 1115-IE-case-10 +2)
  - QNA: 7건 (QNA-SSI-38672_pinpoint, QNA-2018-I-KQA009_pinpoint, QNA-SSI-35609_pinpoint +2)
  - 감리사례: 2건 (FSS-CASE-2024-2505-04_pinpoint, FSS-CASE-2023-2405-06_pinpoint)
  - 본문/적용지침: 12건 (1115-24, 1115-25, 1115-27 +2)
- **Retriever (47건)**:
  - IE사례: 22건
  - QNA: 4건
  - 감리사례: 3건
  - 본문/적용지침: 18건
- **Merged→LLM**: 64건 → 64건
- **Expected docs hit**: 2/2 — hits=['81', '82'], misses=[]

### SECTION-17: 반품권이 있는 판매 (신제품)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['반품권이 있는 판매', '변동대가', '기간에 걸쳐 vs 한 시점 인식']
- **Pinpoint (50건)**:
  - IE사례: 9건 (1115-IE-case-22, 1115-IE-case-26, 1115-IE-case-20 +2)
  - QNA: 15건 (QNA-SSI-38485_pinpoint, QNA-SSI-38612_pinpoint, QNA-SSI-35567_pinpoint +2)
  - 감리사례: 5건 (FSS-CASE-2024-2505-03_pinpoint, FSS-CASE-2023-2405-01_pinpoint, KICPA-CASE-2025-07_pinpoint +2)
  - 교육자료: 1건 (EDU-KASB-180426_pinpoint)
  - 본문/적용지침: 20건 (1115-35, 1115-37, 1115-38 +2)
- **Retriever (56건)**:
  - IE사례: 8건
  - QNA: 15건
  - 감리사례: 6건
  - 교육자료: 1건
  - 본문/적용지침: 26건
- **Merged→LLM**: 93건 → 93건
- **Expected docs hit**: 4/4 — hits=['B20~B27', 'B21', 'B23', '55~58'], misses=[]

### SECTION-18: 계약자산과 계약부채 표시 (순액 상계)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['표시', '계약의 식별', '기간에 걸쳐 vs 한 시점 인식']
- **Pinpoint (49건)**:
  - IE사례: 10건 (1115-IE-case-39, 1115-IE-case-38, 1115-IE-case-40 +2)
  - QNA: 13건 (QNA-SSI-202511019_pinpoint, QNA-SSI-38675_pinpoint, QNA-SSI-202312049_pinpoint +2)
  - 감리사례: 9건 (KICPA-CASE-2025-33_pinpoint, FSS-CASE-2024-2505-02_pinpoint, FSS-CASE-2025-2512-01_pinpoint +2)
  - 교육자료: 2건 (EDU-KASB-BC46_pinpoint, EDU-KASB-180426_pinpoint)
  - 본문/적용지침: 15건 (1115-6, 1115-9, 1115-15 +2)
- **Retriever (66건)**:
  - IE사례: 19건
  - QNA: 15건
  - 감리사례: 10건
  - 교육자료: 1건
  - 본문/적용지침: 21건
- **Merged→LLM**: 97건 → 97건
- **Expected docs hit**: 4/4 — hits=['105', '106', '107', '108'], misses=[]

### SECTION-19: 계약이행원가 (교육훈련비)

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['계약체결 증분원가', '계약이행원가', '기간에 걸쳐 vs 한 시점 인식']
- **Pinpoint (34건)**:
  - IE사례: 5건 (1115-IE-case-36, 1115-IE-case-37, 1115-IE-case-13 +2)
  - QNA: 11건 (QNA-SSI-38676_pinpoint, QNA-SSI-202511018_pinpoint, QNA-SSI-35584_pinpoint +2)
  - 감리사례: 3건 (KICPA-CASE-2025-07_pinpoint, FSS-CASE-2023-2405-05_pinpoint, FSS-CASE-2023-2405-06_pinpoint)
  - 교육자료: 1건 (EDU-KASB-180426_pinpoint)
  - 본문/적용지침: 14건 (1115-35, 1115-37, 1115-38 +2)
- **Retriever (57건)**:
  - IE사례: 17건
  - QNA: 15건
  - 감리사례: 2건
  - 본문/적용지침: 23건
- **Merged→LLM**: 73건 → 73건
- **Expected docs hit**: 4/4 — hits=['95', '95⑴~⑶', '96', '98'], misses=[]

### SECTION-20: 잔여접근법 적용 한계

- **routing**: IN | **is_situation**: True | **needs_calc**: False
- **matched_topics**: ['거래가격 배분', '변동대가', '변동대가의 배분']
- **Pinpoint (35건)**:
  - IE사례: 7건 (1115-IE-case-33, 1115-IE-case-34, 1115-IE-case-20 +2)
  - QNA: 7건 (QNA-SSI-38671_pinpoint, QNA-SSI-202312058_pinpoint, QNA-SSI-202312048_pinpoint +2)
  - 감리사례: 2건 (FSS-CASE-2024-2505-04_pinpoint, FSS-CASE-2023-2405-01_pinpoint)
  - 본문/적용지침: 19건 (1115-47, 1115-50, 1115-51 +2)
- **Retriever (43건)**:
  - IE사례: 19건
  - QNA: 3건
  - 본문/적용지침: 21건
- **Merged→LLM**: 74건 → 74건
- **Expected docs hit**: 3/3 — hits=['76~79', '79⑶', '78'], misses=[]

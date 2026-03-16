# 디버깅 교훈

> 최종 업데이트: 2026-03-16 (F11 IE 테이블 가독성 추가)
>
> Streamlit 관련 교훈은 [STREAMLIT.md](STREAMLIT.md) §8로 이동됨.

---

## 0. 핵심 원칙: 정규식은 최후의 수단, 근본 원인을 먼저 해결

| 우선순위 | 방법 | 예시 |
|---------|------|------|
| **1순위** | **데이터 원본 수정** | `topics.json` 공백 정규화, cross_links 키 수정 |
| **2순위** | **전처리 파이프라인에서 정규화** | 크롤링 단계에서 인라인 태그 보존, 물결표 3종 통일 |
| **3순위** | **구조적 접근으로 대체** | 문단 번호 매칭 → 서머리 임베딩, reranker → bypass |
| **4순위** | **정규식 (최후 수단)** | 위 3가지로 해결 불가한 경우에만. 반드시 테스트 전수 검증 동반 |

**정규식 체크리스트**: (1) 데이터 원본에서 해결 가능? (2) 전처리 1회로 끝나지 않나? (3) 유사 정규식이 같은 파일에 이미? → 통합 (4) 커버 못하는 패턴 반례를 먼저 나열 (5) 에지 케이스 3개 이상이면 설계 재검토

---

## A. 데이터 품질 / 정합성

### A1. 외부 데이터의 숨겨진 문자 패턴

- **JSON 공백**: `topics.json`에 `"합니다 ."` (공백+마침표) → `repr()`로 확인 후 정규화
- **Unicode 물결표 3종**: `~`(U+007E) / `∼`(U+223C) / `～`(U+FF5E) → 모든 문자 클래스에 `[~～∼]`
- **교훈**: 외부 데이터의 유사 문자는 `repr()` + `ord()`로 코드포인트 반드시 확인

### A2. 데이터 정합성 문제는 데이터에서 해결

- **cross_links 불일치**: JSON 데이터 자체를 수정. 코드에서 퍼지 매칭은 복잡도만 증가.
- **토픽 별칭 해석**: 빈 스텁이 존재하면 정확 매칭이 잘못된 결과 반환 → 별칭 매핑을 최우선 체크

### A3. LLM 생성 텍스트 유출 (`finding_descs`)

큐레이션 데이터 생성 시 `💡 크로스 링크 추천` / LLM 전문(preamble) / 숨겨진 공백(247건)이 desc에 혼입.
→ `topics.json` 원본 정리 + `summary-embeddings.json` 재생성
- **교훈**: LLM으로 큐레이션 데이터 생성 시, 저장 전 후처리(separator 이후 잘라내기, 메타 텍스트 제거)가 필수

### A4. cross_links 토픽명 불일치 34건

수동 입력으로 띄어쓰기/조사/표현/약칭 차이 발생. Python 스크립트로 일괄 수정 + `assert link in data.keys()` 전수 검증.
- **교훈**: 큐레이션 데이터의 cross-reference는 파이프라인에 검증 로직 포함 필수

### A5. topics.json 파이프라인 덮어쓰기 사고

`git checkout -- topics.json`으로 HEAD 복원 후 `_add_topics.py` 미실행 → 30개→24개 토픽으로 회귀.
- **교훈**: 파이프라인 중간 산출물을 복원할 때 반드시 후속 스크립트도 실행. topics.json 정합성은 (1) 토픽 키 ↔ UI 표시명, (2) cross_links ↔ 실제 키, (3) decision_trees 토픽명 ↔ 실제 키 3축 검증

### A6. 프로젝트 전체 데이터 정합성 감사 — 6개 취약점

| 취약점 | 해결 |
|--------|------|
| summary-embeddings orphaned ID 4건 | `12-summary-embed.py`에서 자동 제외 |
| topic-embeddings orphaned 토픽 2건 | `13-topic-embed.py`에서 자동 제외 |
| `_split_merged_topics()` desc 덮어쓰기 | 기존 split 토픽 desc 보존 |
| source 문자열 10+파일 하드코딩 | `constants.py`에 상수 중앙화 |
| BM25 빌드 실패 시 서버 미시작 | graceful degradation |
| `_go_home()` 캐시 키 미정리 | reset_keys에 7개 추가 |

- **교훈**: 데이터 파이프라인은 교차 검증 없으면 orphaned/stale 데이터 누적. `verify_data_consistency()` 자동 호출
- **참조**: `app/preprocessing/10-parse-curation.py`, `app/ui/constants.py`

### A7. 토픽 브라우즈 빈 탭에 엉뚱한 summary 표시

`summary or fallback` 패턴에서 summary 데이터가 오염되면 UI 버그 직결 → 데이터 없으면 항상 `fallback` 사용. topics.json에 누락 IE/QNA/감리 추가.

---

## B. 크롤링 / 전처리

### B1. 청킹 시 번호 목록 `(1)(2)(3)` 누락

`para-inner-number-item` HTML 구조 미처리 + 조사 이음 정규식이 번호 항목을 병합 + 마크다운 단일 `\n` 줄바꿈 안 됨.
→ 부모 div 단위로 `\n\n` 조립 + 후처리로 번호 항목 앞 `\n\n` 보장
- **교훈**: HTML 파싱 후 반드시 원본(`fullContent`)과 비교 검증

### B2. `paraContent` < `fullContent` 텍스트 유실

일부 문단에서 `paraContent`에 본문 일부만 제공 → **30% 이상 유실이면 `fullContent`로 폴백**

### B3. 외부 테이블/분개 `.htm` 미처리

IE 적용사례 ~29개 문단에 `data-file-name`으로 외부 HTML 참조 → `11-fix-external-tables.py`로 크롤링·주입
- **교훈**: 크롤링 데이터에 외부 파일 참조 있으면 전처리에서 반드시 크롤링. 마크다운 테이블은 `\n`(단일)으로 행 연결 → `\n→\n\n` 변환 시 테이블 행 보호 필수

---

## C. 파싱 / 정규식

### C1. `_expand_para_range` — 문단 범위 확장 로직

| 패턴 | 예시 | 확장 결과 |
|------|------|-----------|
| 소수점 하위번호 | `한129.1~5` | `한129.1` ~ `한129.5` |
| 접미사 없음→있음 | `B63~B63B` | `B63`, `B63A`, `B63B` |
| 양쪽 알파벳 접미사 | `IE238A~IE238G` | `IE238A` ~ `IE238G` |
| 숫자 범위 | `B20~B27` | `B20` ~ `B27` |

- 접두사: `[A-Za-z가-힣]*?`, 물결표: `[~～∼\-]`, 하위 문단: `re.sub(r"\([0-9가-힣]+\)$", "", raw_num)`
- **교훈**: 새 데이터 추가 시 `99-verify-chunks.py`로 전수 검증

### C2. 문단 참조 볼드 강조 — 체이닝 에지 케이스

범위 표기(`~`), 루프 횟수(3→15), `와` 접속사, 괄호 suffix — 4가지 수정.
- **교훈**: 정규식 체이닝은 루프 횟수가 실데이터 최대 나열 수를 커버해야 함

### C3. 핀포인트 문서 ID 파싱 — decision_trees 참조 패턴

| 패턴 | 처리 |
|------|------|
| `[IE 사례 20, 21]` | IE 전용 분기에서 숫자만 추출 |
| `[IE 사례 5-A, QNA-SSI-38672]` | named_ref 먼저 추출 후 제거 |
| FSS 콤마 접두어 복원 | `current_prefix` 추적 |
| 5자리+ 숫자 필터 | QNA ID 잔재 스킵 |

- **교훈**: 큐레이션 참조 패턴은 사람이 쓴 텍스트라 일관성 없음. `_parse_doc_ids_from_text()` 단위 테스트로 전수 검증

### C4. 소괄호 참조 + 축약 ID + critical_factors 3중 Gap

| Gap | 원인 | 해결 |
|-----|------|------|
| 소괄호 미파싱 | `[대괄호]`만 파싱, section 2는 `(소괄호)` | 양쪽 파싱 |
| 축약 ID | `FSS-2022-...` vs `FSS-CASE-2022-...` | 자동 정규화 |
| critical_factors 미수집 | section 7 텍스트 미수집 | 수집 추가 |

- **교훈**: 같은 데이터 소스에서도 섹션마다 참조 형식 다름 → 통합 처리 + 테스트

### C5. 문단 참조 괄호 suffix 뒤 줄바꿈 잔류

`text.py`의 교차참조 정규식에 `(?:\([0-9가-힣]+\))?` 누락 → 동일 파일 내 유사 정규식 수정 시 나머지도 반드시 확인

### C6. 여는 괄호 직후 줄바꿈 잔류

크롤링 `get_text(separator="\n")`가 `<a>` 인라인 태그 경계에서 줄바꿈 삽입 → `\(\s*\n+\s*(문단)` → `(\1`로 범용 제거
- **교훈**: #C5와 동일 근본 원인(크롤링 줄바꿈 파편화). 개별 땜질보다 구조적 패턴 단위 범용 규칙

### C7. summary 줄바꿈 — 범용 한국어 어미 처리

`다.`만 매칭하면 `함.`, `됨.` 등 누락 → `(?<=[가-힣])\.` 범용 패턴 사용

---

## D. LLM / AI 품질

### D1. user msg에 CoT prefix 추가 시 산술 정확도 하락

gpt-4.1-mini(calc)에서 `_COT_PREFIX`(포맷 지시)가 시스템 프롬프트와 중복 → attention 분산 → 정답률 0.67→0.83 (제거 후).
- **교훈**: non-reasoning 모델에 system/user 양쪽 포맷 지시 중복 금지. 포맷은 system에 1회, user는 데이터에 집중

### D2. 품질 테스트 Partial 4건 구조적 개선

| 문제 | 해결 |
|------|------|
| API timeout 시 에러 종료 | `_retry_node()` 지수 백오프 (max 2회) |
| 양방향 분기에서 미확인 요소에 결론 | `7_critical_factors` + `ModelRetry` 검증 |
| 진행률 체크리스트 선행 판단 누락 | `2_checklist` 첫 항목 추가 |
| 불필요 꼬리질문 | `provided_info` 전달 (analyze→clarify) |

- **교훈**: LLM 품질은 **데이터 구조(critical_factors) + 정보 흐름(provided_info) + 검증(validator)** 3계층 접근

### D3. 라우팅/계산/멀티턴 품질 개선 2차

| 문제 | 해결 |
|------|------|
| calc 라우팅 regex 비결정성 | regex → `AnalyzeResult.needs_calculation` LLM 판단 (42/42 정확) |
| 결론 후 추가 질문 | `concluded` 플래그 + [결론 확인 모드] 강제 |
| 타 기준서 오매칭 | ANALYZE_PROMPT에 negative list (1116/1109/1037호 전용 개념) |

- **교훈**: (1) LLM 토픽 매칭에 의존하는 routing은 비결정적 (2) 멀티턴에서 결론 상태 추적 필수 (3) 기준서 간 유사 용어는 명시적 negative list

### D5. 골든 테스트 라우팅 진단 — `_infer_routing()` calc/clarify 미구분

파이프라인 내부에서는 `needs_calculation` 플래그로 calc/clarify를 정확히 라우팅하지만, SSE done 이벤트에 이 값을 포함하지 않아 테스트 진단 함수가 판별 불가 (항상 `"clarify"` 반환).

| 수정 | 내용 |
|------|------|
| `SSEEvent` 스키마 | `needs_calculation: bool = False` 필드 추가 |
| `_done_event()` | `state["needs_calculation"]`을 SSE 이벤트에 전달 |
| `_infer_routing()` | `needs_calculation` 기반 3-way 분기 (generate/calc/clarify) |
| R04 `expected_routing` | `"not_calc"` → `"clarify"` (프로덕션에 없는 경로명 정리) |

- **교훈**: 파이프라인 내부 상태가 외부(테스트/UI)에서 필요하면 SSE 이벤트 스키마에 반드시 포함. 내부에서 잘 동작해도 출력에 빠지면 검증 불가
- **참조**: `app/api/schemas.py`, `app/pipeline.py`, `app/test/quality_test/run_golden_test.py`

### D4. LLM topic_hints가 임베딩 매칭 방해

hints 가산점(5.0) > 임베딩 최대 점수(~4.7) → 잘못된 hint가 정답 신호 압도.
→ hints 5.0→**3.0**으로 하향. 0% Hit 5건→1건 감소.
- **교훈**: 다중 신호 합산 시 가중치는 신뢰도 순. 불안정(LLM) < 안정(embedding)

---

## E. 검색 / 리트리버

### E1. Cohere Reranker가 큐레이션 문서 탈락시키는 문제

Cohere reranker는 query-document 의미 유사도 기반 → 도메인 전문가 큐레이션 문서는 유사도 낮음 (105건 중 103건 탈락).
→ pinpoint 문서는 **reranker bypass** 처리
- **교훈**: 큐레이션 데이터는 유사도 필터에 통과시키면 안 됨. 별도 경로(bypass)

### E2. 감리사례 매칭 — 문단 번호 → 서머리 임베딩 전환

문단 번호 추출→매칭은 범용 문단(9, 12, 22)에 노이즈 → `summary-embeddings.json` 사전 임베딩 + query 직접 비교
- **교훈**: 간접 매칭(문단→문서→유사도)보다 서머리 직접 비교가 안정적

### E3. IE 적용사례 — 문단 개별 반환 → 사례 단위 병합

사례 1건(IE48, IE48A, IE48B, IE48C)이 개별 doc으로 반환 → `GENERATE_DOC_LIMIT` 과다 점유.
→ 같은 사례 번호 문단들을 하나의 doc으로 병합 (47개 문단 → 8개 사례)
- **교훈**: 리트리버 반환 단위(granularity)가 LLM 컨텍스트 효율에 직접 영향

### E4. MongoDB Atlas 한글 `$regex`/`$in` 미동작

`{"case_group_title": {"$regex": "^사례 24"}}` → 0건. 정확 매칭은 정상.
→ Python prefix 매칭 + `$or` 정확 매칭
- **교훈**: MongoDB Atlas는 한글 `$regex`/`$in`이 비정상 동작할 수 있음. Python 전처리 + 정확 매칭이 안전
- **참조**: `app/ui/db.py`

---

## F. UI / Streamlit

### F1. 페이지 전환 깜빡임(flicker) — CSS 셀렉터 방향 오류

`data-stale="true"`는 `.block-container`의 **자식** `.element-container`에 설정. `[data-stale] .block-container`는 조상→자손 방향이라 매칭 불가.
→ `.element-container[data-stale="true"] { visibility: hidden }` 직접 타겟
- **교훈**: Streamlit DOM 구조 추측 금지 → Playwright/DevTools로 확인

### F2. stale 위젯 CSS `display: none` → fragment rerun 시 스크롤 점프

`display: none`은 레이아웃 공간 제거 → `@st.fragment` rerun 시 스크롤 점프.
→ `visibility: hidden`으로 변경 (공간 유지 + 시각적 숨김)

### F3. st.status 클릭 시 빈 칸 펼침

`st.status(expanded=False)` + CSS `pointer-events: none`도 `<details>/<summary>` 차단 불가.
→ `st.empty()` + HTML 스피너(CSS `@keyframes`)로 교체

### F4. 검색 폼 제출 시 최상단 스크롤

`st.form` 제출은 `@st.fragment` 안에서도 **항상 전체 앱 rerun**.
→ `st.form` 제거 → `@st.fragment` + 일반 `st.button` 사용
- **교훈**: `@st.fragment` + `st.form`은 스크롤 유지에 무효. fragment 내 스크롤 유지 → 일반 위젯만 사용

### F5. title 없는 문단의 expander/캡션 표시

MongoDB `title`이 빈 문자열이면 `doc.get("title", fallback)`은 빈 문자열 반환(기본값 미적용).
→ `doc.get("title") or ""` + falsy 체크 + content 첫 문장(80자) 폴백

### F6. AI 답변 인용 문단 하이라이트

`_get_cited_ids()` 헬퍼: 문단 + QNA + 감리/교육 ID 통합 추출 → `cited_ids` set을 렌더러에 전파 → 인용된 항목만 `:blue[**문단 XX**]`
- `page_state == "ai_answer"`일 때만 계산 (1/2단계 무영향)

### F7. bare 문서 ID 파란색 강조 누락

AI 답변이 `(문단 38, EDU-KASB-180426)` 형태로 bare ID 사용 — 대괄호 패턴에만 의존하면 누락.
→ bare ID 패턴 + `EDU-` 접두사 추가
- **교훈**: LLM은 프롬프트 지시(`[QNA-xxx]` 형식)를 항상 따르지 않으므로, bare 패턴도 처리

### F8. `_fill_missing_docs` 섹션 매칭 실패

hierarchy 소소제목 ≠ topics.json title (문자열이 다름). 부분 매칭은 동일 키워드 섹션 2개("지급청구권" 본문 vs 적용지침)에서 오매칭.
→ 문단번호 기반 역인덱스 조회 (`get_section_for_para()`)
- **교훈**: 문자열 비교보다 **문단번호를 키로 한 역인덱스 조회**가 확실

### F9. IE 중복 렌더링 + 제목 과다 길이

`_render_supp_extra()`가 동일 `case_group_title` 사례를 중복 렌더링 → `ie_seen` set으로 dedup.
`_make_label()`의 IE 제목에서 `[사례 N: 제목]` 중복 접두사 → `re.sub`으로 제거.

### F10. 마크다운 테이블 깨짐 + 이중 줄띄움

`\n→<br>` 변환이 파이프 테이블 행 구분자 파괴 → `md_tables_to_html()` 함수로 테이블을 먼저 HTML 변환.
연속 `\n` → `re.sub(r"\n+", "<br>")` 단일 치환.
- **교훈**: `\n→<br>` 변환은 마크다운 테이블과 양립 불가 — 테이블 먼저 HTML 변환

### F11. IE 외부 테이블 가독성 — 3중 제약 돌파

**문제**: `11-fix-external-tables.py`가 HTML `colspan/rowspan` 무시 → 7열 파이프 테이블(빈 열·빈 행 대량) → 설명 텍스트가 좁은 셀에 갇혀 줄바꿈

**제약 3가지**:

| 제약 | 원인 | 시도 → 실패 |
|------|------|------------|
| Streamlit CSS 덮어쓰기 | `<table>`/`<td>` 인라인 스타일을 `!important`로 무시 | 빨간 border 테스트 → 미반영 |
| `\n→<br>` 파이프 파괴 | `md_tables_to_html` 출력의 파이프 테이블을 `\n→<br>`가 파괴 | 마크다운 파이프 재조립 → 깨짐 |
| 렌더링 경로 누락 | `topic_tabs.py`가 `md_tables_to_html()` 미호출 | `doc_renderers.py`만 수정 → 무효 |

**해결**:
1. `text.py` `_md_table_to_html()`: 빈 열·빈 행 제거 + 설명 행(≤2셀)은 `<div>` 텍스트, 분개 행(≥3셀)은 `<div>` CSS grid로 변환 (Streamlit CSS 회피)
2. `topic_tabs.py` 3곳에 `md_tables_to_html()` 호출 추가 (누락된 렌더링 경로)

- **교훈**: (1) Streamlit은 `<table>` 인라인 스타일을 덮어씀 → `<div>` 대체 필수 (2) 텍스트 변환 함수는 **모든 렌더링 경로**에서 호출되어야 함 — 한 곳만 수정하면 다른 경로에서 미적용 (3) Python 테스트 통과 ≠ 브라우저 반영, 디버그 마커로 실제 경로 확인 필수
- **참조**: `app/ui/text.py`, `app/ui/topic_tabs.py`

---

## G. 시스템 / 아키텍처

### G1. QNA/감리사례 parent 문서 처리

- parent 컬렉션은 `metadata` dict 안에 중첩 저장 → `doc.get("metadata", {}).get("title", "")` 방어적 접근
- ID 접두사(`QNA-`, `FSS-`, `KICPA-`)로 컬렉션 라우팅
- 감리지적사례 제목 비일관성 → `_build_pdr_label()`로 방어적 처리

### G2. for 루프 잔류 변수 참조 (evidence.py)

Python for 루프 변수는 루프 밖에서도 살아있음 → 중첩 조건 분기에서 stale reference.
→ 명시적 dict 조회 `ACCORDION_GROUPS.get(group_name, [])`

### G3. Cohere 클라이언트 매 요청 재생성

함수 내부에서 `cohere.ClientV2()` 매 호출 → HTTP 커넥션 풀 낭비.
→ 모듈 레벨 싱글턴 패턴
- **교훈**: API 클라이언트(HTTP 기반)는 싱글턴/팩토리 패턴으로 커넥션 풀 재사용

### G4. `logging.basicConfig`을 config.py에 두면 import 부작용

설정 파일 import 시점에 전역 로깅 설정 강제 적용 → 단위 테스트 격리 불가.
→ `main.py`(진입점)로 이동. 설정 파일은 순수 데이터 선언만.
- **교훈**: 설정 파일에 전역 상태 변경 코드(`logging.basicConfig`, DB 초기화) 금지

### G5. raw string `\x00` regex escape 버그

`r"\1\x00"` — raw string에서 `\x00`은 리터럴 4문자 → `re.error: bad escape \x`.
→ `lambda m: m.group(1) + "\x00"` 함수로 변경

### G6. KAI 교육자료 evidence 패널 오분류

`ACCORDION_GROUPS` 미등록 → catch-all 그룹으로 오분류.
새 문서 유형 추가 시: (1) ACCORDION_GROUPS 등록, (2) 렌더러 경로 지정, (3) 인용 감지 패턴 추가 — 3가지 동시 처리
- **교훈**: catch-all 패턴은 디버깅 어렵게 함 → 지양

### G7. pinpoint 문서가 AI 답변 패널에 미표시 (7건 통합 수정)

| 문제 | 해결 |
|------|------|
| `DocResult` 스키마에 `chunk_type` 누락 | 필드 추가 + `_to_doc_result` 전달 |
| IE pinpoint source "본문" 하드코딩 | `"적용사례IE"`로 변경 |
| pinpoint 미인용 문서 일괄 제거 | `_supp_by_group`에 포함 → "참고 추가 문서" 더보기 |
| 그룹 0건 시 더보기 미렌더 | `has_supp` 확인 후 렌더 |
| `fetch_ie_case_docs` 한글 매칭 실패 | Python prefix + `$or` 정확 매칭 |
| IE 반환값에 `source` 누락 | `d["source"] = SRC_IE` 설정 |
| IE desc 인덱스 키 불일치 | `:` split 정규화 |

표시 계층: ① AI 인용 본문/적용지침 ② AI 인용 QNA/감리 ③ AI 인용 IE ④ "📂 참고하면 좋은 추가 문서" (pinpoint 우선 + retriever 보충)

- **교훈**: 파이프라인 메타데이터(`chunk_type`)가 API 스키마→프론트엔드까지 전달되려면 중간 변환 함수와 직렬화 스키마 모두에 필드 필요
- **참조**: `app/ui/evidence.py`, `app/api/schemas.py`, `app/retriever.py`, `app/ui/db.py`

### G8. SECTION-4 Timeout + 파이프라인 속도 최적화

| 변경 | 내용 |
|------|------|
| Cohere timeout | `reranker_timeout=30` + `request_options` |
| retrieve 2중 병렬 | 핀포인트+리트리버 `asyncio.gather`, vector+keyword `ThreadPoolExecutor` |
| MongoDB 배치 조회 | 개별 `find_one()` N회 → source별 `$in` 3회 |
| 파이프라인 deadline | `pipeline_timeout=100` + 모든 노드 전파 |

| 단계 | 변경 전 | 변경 후 |
|------|--------|--------|
| retrieve | 3.7s | **0.6s** |
| total | 33.4s | **25.9s** (-22%) |

- **교훈**: `find_one()` N회 → `$in` 배치로 네트워크 왕복 극적 감소. 외부 API timeout 미설정은 production 간헐 장애 원인
- **참조**: `app/config.py`, `app/reranker.py`, `app/retriever.py`, `app/pipeline.py`

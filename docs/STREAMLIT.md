# Streamlit 규칙

> 최종 업데이트: 2026-03-16 (§2 테이블 스타일링, §7 Streamlit 테이블 제약 추가)

---

## 1. 디자인 시스템

### 컬러 팔레트 (Slate Gray 계열)

| 역할 | 색상 코드 | 용도 |
|------|----------|------|
| **Primary** | `#0F172A` | 텍스트, 버튼, 링크 (config.toml `primaryColor`) |
| **Emphasis** | `#334155` | 강조 제목, 문단 참조 링크 |
| **Border** | `#E2E8F0` | 테두리, 구분선, 카드 border |
| **Background** | `#FFFFFF` | 메인 배경 |
| **Surface** | `#F8FAFC` | 사이드바 배경, 출처 푸터, 블록쿼트 |
| **Surface Hover** | `#F1F5F9` | 칩 호버, 사이드바 secondary |
| **Secondary Text** | `#64748B` | 보조 설명, 라벨, 푸터 텍스트 |
| **Muted** | `#94A3B8` | 비활성 링크, 외부 참조 |
| **Highlight** | `#1f77b4` | 문단 참조 볼드 강조 (파란색) |
| **Button Navy** | `#1E293B` | 폼 제출 버튼 배경 |

### 타이포그래피

| 요소 | 폰트 | 크기 | 비고 |
|------|------|------|------|
| 본문 | Plus Jakarta Sans | 14px (base) | Google Fonts CDN |
| 코드 | JetBrains Mono | 13px | |
| H1 | Plus Jakarta Sans | 26px / 700 | |
| H2 | Plus Jakarta Sans | 20px / 600 | |
| H3 | Plus Jakarta Sans | 17px / 600 | |
| 문단 본문 | — | 0.95em / line-height 1.85 | `.doc-body p.doc-para` |
| 출처 푸터 | — | 0.82em | `.source-footer` |
| 칩 | — | 0.8em / 500 | `.quick-chip` |

### 기본 스타일 설정 (`config.toml`)

```toml
[theme]
base = "light"
primaryColor = "#0F172A"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F8FAFC"
borderColor = "#E2E8F0"
showWidgetBorder = false
baseRadius = "small"
buttonRadius = "small"
linkUnderline = false
```

---

## 2. CSS 규칙

### 원칙: CSS는 레이아웃 보정 전용
- **색상/테마** → `config.toml`에서 관리
- **CSS** → 간격, 테두리, 그림자 등 레이아웃 미세 조정만
- `st.markdown(unsafe_allow_html=True)`로 주입

### CSS 셀렉터 패턴

| 패턴 | 용도 | 예시 |
|------|------|------|
| `div[data-testid="stExpander"]` | Streamlit 내부 컴포넌트 | 카드 스타일 |
| `div[class*="st-key-xxx"]` | `key=` 기반 위젯 선택 | 특정 버튼/컨테이너 |
| `[data-testid="stFormSubmitButton"]` | 폼 제출 버튼 | 네이비 배경 |

### 카드 스타일 (Expander)
```css
div[data-testid="stExpander"] {
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    transition: border-color 0.15s, box-shadow 0.15s;
}
div[data-testid="stExpander"]:hover {
    border-color: #CBD5E1;
    box-shadow: 0 2px 6px rgba(0,0,0,0.06);
}
```

### Rerun 중 stale 위젯 숨김
```css
/* Why: visibility:hidden은 공간 유지 + 시각적으로만 숨김 → 스크롤 안정 */
.element-container[data-stale="true"] {
    visibility: hidden !important;
}
```
> `display: none` 금지 — §7 참조

### Streamlit의 `<table>` 인라인 스타일 덮어쓰기

`st.markdown(unsafe_allow_html=True)`로 삽입한 `<table>`/`<td>` 인라인 스타일은 Streamlit CSS가 `!important`로 덮어씀.
→ 테이블 스타일 커스터마이징은 **`<div>` + CSS grid**로 대체.

```python
# X — Streamlit이 border/padding 등 인라인 스타일 무시
'<table><td style="border:2px solid red;">내용</td></table>'

# O — <div>는 인라인 스타일 정상 적용
'<div style="display:grid; grid-template-columns:1fr 1fr 1fr 1fr;">'
'  <div style="border:1px solid #e2e8f0; padding:4px 10px;">내용</div>'
'</div>'
```

### 숨김 처리
```css
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
```

---

## 3. 컴포넌트 패턴

### 페이지 State Machine (4단계)

```
HOME → TOPIC_BROWSE (토픽 버튼 클릭)
HOME → EVIDENCE (검색 제출)
TOPIC_BROWSE → EVIDENCE (질문 제출)
EVIDENCE → AI_ANSWER (AI 질문 제출)
AI_ANSWER → AI_ANSWER (후속 질문)
```

`st.session_state.page_state`로 관리.

### 네비게이션: on_click 콜백 패턴 (필수)

```python
# O — 1회 rerun, 깜빡임 없음
st.button("Label", on_click=_callback_func, args=(arg1,))
```
> `if st.button: st.rerun()` 금지 — §7 참조

### 폼 제출 시 스크롤 유지: `@st.fragment` + 일반 위젯 (필수)

```python
# O — fragment 내 일반 위젯: 부분 rerun → 스크롤 유지
@st.fragment
def _search_fragment():
    query = st.text_area(..., key="search_input")
    if st.button("검색하기", key="search_btn"):
        if query and query.strip():
            _call_chat(query)
_search_fragment()
```

**원리**: `@st.fragment` 내부 일반 위젯 인터랙션 → fragment만 rerun → 스크롤 유지.
> `st.form` + `@st.fragment` 조합 금지 — §7 참조

### 헤더 레이아웃
- `st.html()`로 중앙 정렬 렌더링
- 배지(K-IFRS 1115) + 제목 + 설명 + 구분선
- 사이드바: 제목 + 설명 + "처음으로" 버튼 + 일러두기 + 고정 푸터

### 키워드 칩 (홈 화면)
- `constants.py`의 `KEYWORD_CHIPS` 배열
- CSS pill 스타일: `border-radius: 999px`, `#E2E8F0` 테두리

### 아코디언 그룹 (근거 패널)
```python
ACCORDION_GROUPS = {
    "📘 기준서 본문 및 적용지침": ["본문", "적용지침B", "용어정의", "시행일"],
    "🔍 결론도출근거(BC)":      ["결론도출근거"],
    "📋 적용사례(IE)":          ["적용사례IE"],
    "💬 질의회신(QNA)":         ["질의회신", "QNA"],
    "🚨 감리지적사례":           ["감리사례"],
    "📖 한국회계기준원 교육자료": ["교육자료"],
}
```

### 문서 카드 3종

| 유형 | 함수 | 구조 |
|------|------|------|
| 표준 문서 (본문/적용지침/BC) | `_render_document_expander()` | 라벨 → 배지(문단 XX) → 본문 → 칩 → 푸터 |
| PDR 문서 (QNA/감리사례) | `_render_pdr_expander()` | parent 문서 fetch → `[QNA-xxx] 제목` 라벨 |
| IE 적용사례 | 그룹별 렌더링 | `case_group_title`로 그룹화, 하위 사례(1A, 1B) 정렬 |

### 문단 참조 인터랙션
- 텍스트 내 `문단 23`, `문단 B2~B89` → 파란 볼드 강조
- 칩: `st.pills()`로 클릭 가능한 문단 참조 표시
- 모달: `@st.dialog`로 문단 원문 표시 + 브레드크럼 네비게이션 (중첩 없음)

### AI 인용 하이라이트 (ai_answer 전용)
- expander 라벨에서 AI가 실제 인용한 문단만 `:blue[**문단 XX**]` 파란색 볼드
- `evidence.py:_get_cited_ids()` → 문단/QNA/감리 ID 통합 set 추출
- `cited_ids` 파라미터가 `grouping.py` → `doc_renderers.py`로 전파
- `page_state != "ai_answer"`이면 `cited_ids=None` → 1/2단계 무영향

---

## 4. 간격 관리

### Streamlit 네이티브 gap 사용 (CSS보다 우선)

```python
st.container(gap="small")  # 기본값, 1rem
```

| 값 | rem |
|----|-----|
| `None` | 0 |
| `"xxsmall"` | 0.25 |
| `"xsmall"` | 0.5 |
| `"small"` | 1 (기본) |
| `"medium"` | 2 |
| `"large"` | 4 |

### CSS 간격 보정 (네이티브로 불가능할 때만)
```css
div[data-testid="stVerticalBlock"] > div { gap: 0 !important; }
h3 { margin-top: 0.4rem; margin-bottom: 0.1rem; }
```

---

## 5. 캐싱 전략

| 대상 | 데코레이터 | TTL | 비고 |
|------|-----------|-----|------|
| MongoDB 커넥션 | `@st.cache_resource` | 세션 전체 | 싱글턴 |
| 배치 문단 조회 | `@st.cache_data` | 300초 | 탭 전환 시 재사용 |
| 인용 문서 추출 | Session state | 답변당 1회 | `cited_docs_cache_key` |
| IE 사례 문서 | Session state | 답변당 1회 | 중복 렌더링 방지 |

---

## 6. API 통신 패턴

### Search (동기)
```python
_call_search(query) → POST /search → st.spinner() → session_state 업데이트 → st.rerun()
```

### Chat (SSE 스트리밍)
```python
_call_chat(question) → POST /chat (httpx.stream) → SSE 파싱:
  - type="status" → st.empty().markdown(HTML 스피너 + 텍스트)
  - type="done"   → answer, cited_sources, follow_up_questions
  - type="error"  → error message
```
**Why HTML 스피너** (`st.status`/`st.info` 아님):
- `st.status`: `<details>` 기반 → 클릭 시 빈 칸 펼쳐짐, CSS로 차단 불가 (§7 참조)
- `st.info()`: 파란 배경 박스 → 시각적으로 과함
- HTML 스피너: CSS 애니메이션 + 텍스트만, 배경 없음, 클릭 불가

---

## 7. 금지사항 & 디버깅 교훈

| 금지 | 이유 | 대안 |
|------|------|------|
| `st.form` + `@st.fragment` 조합 | `form_submit_button`은 fragment 안에서도 전체 rerun 강제 | `@st.fragment` 내 일반 `st.button` 사용 |
| `st.status` (진행 표시 용도) | `<details>` 기반 → 클릭 시 빈 칸 펼쳐짐, CSS 차단 불가 | `st.empty()` + HTML 스피너 |
| `display: none` (stale 위젯) | fragment rerun 시 공간 제거 → 레이아웃 시프트 → 스크롤 점프 (debugging.md #24) | `visibility: hidden` |
| JavaScript / iframe | Streamlit 샌드박스 제한 | 네이티브 위젯 |
| `<table>` 인라인 스타일 의존 | Streamlit CSS가 `!important`로 덮어씀 | `<div>` + CSS grid 사용 (§2 참조) |
| `st.error()` in `@st.cache_data` | 에러가 캐시에 녹아 TTL 동안 반복 재생 | `logging.warning()` |
| `if st.button: st.rerun()` | 이중 rerun(2회) → 깜빡임 | `on_click` 콜백 (1회 rerun) |
| 내부 레이아웃 CSS 직접 수정 | 불안정, 버전 변경 시 깨짐 | 네이티브 파라미터 우선 |
| 위젯 키 직접 수정 | `st.session_state["key"] = val` → `StreamlitAPIException` | `on_change` 콜백 내에서 처리 |
| `[data-stale] .block-container` 셀렉터 | `data-stale`은 `.element-container`에 설정 (조상→자손 방향 반대, debugging.md #21) | `.element-container[data-stale="true"]` |

### 위젯 키 수정 — 올바른 패턴

```python
def _on_change():
    if st.session_state.get("my_pills"):
        st.session_state["my_pills"] = None
st.pills("label", options=opts, key="my_pills", on_change=_on_change)
```

### CSS 커스터마이징 한계

Streamlit은 CSS 커스터마이징을 공식 지원하지 않음.

- **O**: `key=` 기반 셀렉터로 위젯 자체 스타일 변경
- **X**: 내부 레이아웃 속성 (`gap`, `margin`), `stVerticalBlock` 등 프레임워크 내부 컴포넌트

**접근 순서**: 네이티브 파라미터 확인 → 불가 시 CSS → 빨간 테두리 디버그로 셀렉터 매칭 확인

---

## 8. 파일 구조

```
app/
├── streamlit_app.py          # 진입점 (페이지 라우터)
└── ui/
    ├── layout.py              # CSS 주입, 헤더, 사이드바
    ├── session.py             # 세션 상태 초기화/리셋
    ├── pages.py               # 3개 메인 페이지 렌더러
    ├── client.py              # API 통신 (search, chat SSE)
    ├── constants.py           # 상수 (URL, 칩, 그룹, 진행률)
    ├── text.py                # 텍스트 정규화 + 테이블 변환 (md_tables_to_html)
    ├── doc_helpers.py         # 순수 Python 문서 헬퍼
    ├── doc_renderers.py       # 문서 카드 렌더링
    ├── evidence.py            # 아코디언 패널 오케스트레이터
    ├── topic_browse.py        # 토픽 큐레이션 뷰 (4탭)
    ├── topic_tabs.py          # 탭 구현체
    ├── grouping.py            # 2레벨 계층 그룹핑
    ├── modal.py               # 문단 참조 모달 다이얼로그
    ├── cross_links.py         # 관련 토픽 pill 컴포넌트
    ├── pinpoint_panel.py      # AI 답변 근거 패널
    ├── db.py                  # MongoDB 유틸리티
    └── components.py          # 하위 호환 barrel file
.streamlit/
└── config.toml               # 테마 설정
```

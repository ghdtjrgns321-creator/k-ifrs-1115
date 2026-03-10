# Streamlit 디버깅 교훈 (k-ifrs-1115-chatbot)

> 최종 업데이트: 2026-03-10 (이중 rerun + DB 에러 캐시 재생 수정)

---

## 1. CSS로 컨테이너 내부 간격 조정 시도 (실패)

### 문제
홈 화면 토픽 버튼들(`st.container(border=True)` 내부) 간 세로 간격이 너무 넓었음.

### 시도한 방법들 (전부 실패)

| 시도 | CSS 셀렉터 | 결과 |
|------|-----------|------|
| 1 | `div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlock"]` | 무반응 |
| 2 | `div[class*="st-key-home_topics_"] div[data-testid="stVerticalBlock"]` | 무반응 |
| 3 | `div.st-key-home_topics_L div[data-testid="stVerticalBlock"]` | 무반응 |
| 4 | `div.st-key-home_topics_L *` (와일드카드) | 무반응 |
| 5 | 컨테이너 내부에서 `st.markdown(<style>...)` 직접 주입 | 무반응 |

### 근본 원인
**Streamlit은 CSS 커스터마이징을 공식 지원하지 않음.** `st.markdown(unsafe_allow_html=True)`로 주입한 CSS는 내부 레이아웃 컴포넌트에 안정적으로 적용되지 않음.

### 올바른 해결법
```python
# Streamlit 네이티브 gap 파라미터 사용
with st.container(border=True, gap="xsmall"):
    ...
```

`st.container()`의 `gap` 파라미터 (**기본값 = `"small"` = 1rem**):
- `None` — 간격 제거 (0)
- `"xxsmall"` — 0.25rem
- `"xsmall"` — 0.5rem
- **`"small"` (기본값)** — **1rem**
- `"medium"` — 2rem / `"large"` — 4rem

### 주의: `gap="small"`은 기본값이므로 변화 없음
간격을 줄이려면 **`"xsmall"` 이하**를 사용해야 함.

---

## 2. CSS가 먹히는 범위 vs 안 먹히는 범위

### CSS 작동 O
- `key=` 기반 셀렉터로 **위젯 자체** 스타일 변경 (예: `div.st-key-xxx button`)

### CSS 작동 X
- Streamlit **내부 레이아웃** 속성 (`gap`, `margin`)
- `stVerticalBlock` 등 프레임워크 내부 컴포넌트

### 디버깅 순서
1. Streamlit API docs에서 네이티브 파라미터 확인
2. 네이티브로 불가능할 때만 CSS 시도
3. CSS 시도 시 빨간 테두리 디버그로 셀렉터 매칭부터 확인

---

## 3. Streamlit 위젯 키 수정 제한

### 문제
`st.pills(key="xlink_pills")` 인스턴스화 후 `st.session_state["xlink_pills"] = None` → `StreamlitAPIException`

### 올바른 해결법
```python
# on_change 콜백은 위젯 렌더링 전에 실행되므로 키 수정 가능
def _on_xlink_change():
    picked = st.session_state.get("xlink_pills")
    if picked:
        st.session_state.selected_topic = picked
        st.session_state["xlink_pills"] = None

st.pills("관련 토픽", options=cross_links, key="xlink_pills",
         on_change=_on_xlink_change)
```

**핵심**: 위젯 값을 리셋하려면 `on_change` 콜백 안에서 처리.

---

## 4. JSON 데이터의 숨겨진 공백 패턴

### 문제
`_md_to_html()`에서 `(?<=[가-힣])다\.` 정규식이 문장 종결을 전혀 매칭하지 못함.

### 근본 원인
`topics.json`의 desc/summary 필드가 `"합니다 ."` (다와 . 사이 공백)으로 저장됨.
`repr()` 확인으로 발견.

### 올바른 해결법
```python
# 먼저 "다 ." → "다." 정규화
t = re.sub(r"(?<=[가-힣])다\s+\.", "다.", t)
# 그 후 줄바꿈 삽입
t = re.sub(r"(?<=[가-힣])다\.\s+", "다.<br>", t)
```

**교훈**: 정규식이 안 먹히면 `repr()`로 실제 데이터 확인.

---

## 5. cross_links 불일치 — 코드가 아닌 데이터 수정

### 문제
cross_link 값이 topics.json의 실제 키와 불일치 (예: `"본인 대 대리인 판단"` → 키: `"본인 vs 대리인"`)

### 올바른 해결법
**JSON 데이터 자체를 수정**. 코드에서 퍼지 매칭은 복잡도만 증가.

**교훈**: 데이터 정합성 문제는 데이터에서 고치는 것이 근본 해결.

---

## 6. `_expand_para_range` — 하위 문단 접미사

### 문제
`B19(1)` 문단 조회 시 DB에서 못 찾음. DB는 `B19`로 저장.

### 해결
```python
cleaned = re.sub(r"\([0-9가-힣]+\)$", "", raw_num.strip())
```

---

## 7. 토픽 별칭 해석 순서

### 문제
"재매입약정" 클릭 시 빈 스텁 표시. 정확 매칭(빈 스텁)이 별칭보다 먼저 수행됨.

### 해결
별칭 매핑을 **최우선**으로 체크:
```python
def _resolve_topic_key(button_name, topic_map):
    alias = _TOPIC_ALIAS.get(button_name)  # 1) 별칭 최우선
    if alias and alias in topic_map:
        return alias
    # 2) 정확 매칭, 3) 괄호 제거 매칭
```

**교훈**: 빈 스텁이 존재하면 정확 매칭이 잘못된 결과를 반환할 수 있음.

---

## 8. 청킹 시 번호 목록 `(1)(2)(3)` 누락/합침 버그

### 문제
B43 문단에서 `(2) 이 재화나 용역은...`이 `(1)` 줄에 붙어서 표시됨. `(가)`, `(나)` 항목도 일부 문단에서 누락.

### 근본 원인 (3가지)

**1) `para-inner-number-item` HTML 구조 미처리**
kifrs.com API의 번호 목록은 `idt-1` 클래스가 아니라 별도 구조를 사용:
```html
<div class="para-inner-number">
  <div class="para-inner-number-item">
    <div class="para-number-para-num">(1)</div>
    <div class="para-num-item-para-con">고객에게...</div>
  </div>
</div>
```
`clean_html_to_md()`가 `idt-1`만 처리하고 이 구조는 무시 → `get_text(separator="\n")`으로 추출 시 번호와 내용이 뒤섞임.

**2) 조사 이음 정규식이 번호 항목을 먹음**
```python
# ")\n이" 패턴 → "(2)\n이 재화나" → "(2)이 재화나"로 합침
re.sub(r"([A-Za-z0-9)])\n([의을를이가])\s", r"\1\2 ", text)
```

**3) 마크다운 단일 `\n`은 줄바꿈 아님**
Streamlit 마크다운에서 `\n`은 무시되고 `\n\n`(이중 줄바꿈)만 단락 분리. `para-inner-number-item`에서 `\n`만 넣으면 (1)(2)(3)이 한 줄로 렌더링.

### 해결 (`03-chunk-with-weight.py`)

```python
# 1) 부모 div 단위로 모든 자식(number-item + hanguel-item) 텍스트 조립
_NUM_ITEM_CLASSES = {"para-inner-number-item", "para-inner-number-hanguel-item"}
for number_div in soup.find_all("div", class_="para-inner-number"):
    lines = []
    for child in number_div.find_all("div", recursive=False):
        if set(child.get("class", [])) & _NUM_ITEM_CLASSES:
            num = child.find("div", class_="para-number-para-num").get_text(strip=True)
            con = child.find("div", class_="para-num-item-para-con").get_text(separator=" ", strip=True)
            lines.append(f"{num} {con}")
    new_tag = soup.new_tag("p")
    new_tag.string = "\n\n" + "\n\n".join(lines) + "\n\n"
    number_div.replace_with(new_tag)

# 2) 후처리: strip=True가 앞뒤 \n을 제거하므로, 번호 항목 앞 \n\n 보장
final_md = re.sub(r"(?<!\n)\n(\((?:\d+|[가-힣])\) [가-힣])", r"\n\n\1", final_md)
```

### 영향 범위
- `para-inner-number-item` 사용 문단: **214개** (전체 1298개 중 16%)
- `hanguel-item` (`(가)(나)` 등) 복원: **25건**

### 검증
```bash
PYTHONPATH=. uv run python app/preprocessing/99-verify-chunks.py
```

**교훈**: HTML 파싱 후 반드시 원본(`fullContent`)과 비교 검증. `get_text(strip=True)`는 앞뒤 공백/줄바꿈을 제거하므로, 태그 내 `\n\n`에 의존하면 안 됨.

---

## 9. `paraContent` < `fullContent` 텍스트 유실

### 문제
BC445I, BC445L 문단에서 뒷부분 문장이 잘림. 웩12는 97% 유실.

### 근본 원인
kifrs.com API가 일부 문단에서 `paraContent`(HTML)에 본문 일부만 넣고, `fullContent`에 전체 텍스트를 제공.
`clean_html_to_md()`가 `paraContent` HTML을 우선 파싱하므로 나머지가 누락.

### 해결
HTML 파싱 후 `fullContent` 키워드 비교 → 30% 이상 유실이면 `fullContent`로 폴백:
```python
if full_content:
    fc_words = set(re.findall(r"[가-힣]{3,}", re.sub(r"\s+", "", full_content)))
    md_words = set(re.findall(r"[가-힣]{3,}", re.sub(r"\s+", "", final_md)))
    if fc_words and len(fc_words - md_words) / len(fc_words) > 0.3:
        final_md = "\n".join(l.strip() for l in full_content.split("\n") if l.strip())
```

### 영향 범위
- 실제 텍스트 유실: **2건** (BC445I, BC445L) + 웩12(메타 정보)

**교훈**: `paraContent`와 `fullContent`가 항상 동일하다고 가정하면 안 됨. 재청킹 후 `99-verify-chunks.py`로 전수 검증 필수.

---

## 10. 문단 참조 볼드 강조 — 접속사 체이닝 에지 케이스 4건

### 문제
`clean_text()` (app/ui/text.py)의 step 2.5가 쉼표/접속사로 연결된 문단 번호를 파란색 볼드로 강조하는데, 특정 패턴에서 누락 발생.

**스크린샷**: `문단 89, 99, 100~102` — "102"만 볼드 미적용.

### 근본 원인 (4건)

**1) 범위 표기(`~`) 미처리**
step 2.5 정규식이 `(\d+[A-Za-z]*)` → `100`만 매칭하고 `~102`를 놓침.
```
<span>99</span>, 100~102
                  ^^^  ← 100만 잡고 ~102 누락
```

**2) 루프 3회 제한**
`re.subn`은 1회 실행에 `</span>` 바로 뒤의 번호 1개만 매칭 (체이닝 특성). 13개 나열된 실데이터 존재 (변경이력 C1B).
```
문단 26, 27, 29, B1, B34~B38, B52~B54, B56, B58, B59, B63, C2, C5, C7
         ^^  ^^  ^^  ← 3회 반복으로 여기까지만 처리, 이후 전부 누락
```

**3) "와" 접속사 누락**
한국어에서 "과"(받침 뒤)와 "와"(모음 뒤)는 같은 접속사. 기존 정규식에 "과"만 있고 "와" 누락.

**4) 괄호 suffix가 체이닝 단절**
`문단 35(3), 37` → step 2가 `문단 35`만 감싸서 `<span>문단 35</span>(3), 37` 생성.
`</span>` 바로 뒤에 `(3)`이 와서 쉼표 매칭 실패 → `37` 미처리.

### 해결 (`app/ui/text.py` step 2.5)

```python
# Before
for _ in range(3):
    text, n = re.subn(
        r'(</span>\s*(?:[,，]|및|과|또는|그리고)\s*)(\d+[A-Za-z]*)',
        ...
    )

# After
_CONJ = r'(?:[,，]|및|과|와|또는|그리고)'
_NUM_RANGE = r'(?:IE|BC|B)?\d+[A-Za-z]*(?:[~～\-](?:IE|BC|B)?\d+[A-Za-z]*)?'
for _ in range(15):  # 실데이터 13개 나열 대응
    text, n = re.subn(
        # 괄호 suffix 건너뛰기 + 범위 표기 한 덩어리 처리
        rf'(</span>(?:\([0-9가-힣]+\))?\s*{_CONJ}\s*)({_NUM_RANGE})',
        ...
    )
```

| 변경 | Before | After |
|------|--------|-------|
| 범위 표기 | `\d+[A-Za-z]*` | `\d+[A-Za-z]*(?:[~～\-](...)\d+[A-Za-z]*)?` |
| 루프 횟수 | 3 | 15 (`n==0`이면 즉시 탈출, 성능 영향 없음) |
| 접속사 | `및\|과\|또는\|그리고` | `및\|과\|와\|또는\|그리고` |
| 괄호 | 미처리 | `(?:\([0-9가-힣]+\))?` 건너뛰기 |

`_PARA_CONJ_RE` (칩 추출용)에도 "와" 접속사 추가.

**교훈**: 정규식 체이닝 로직은 한 번에 한 단계씩만 진행하므로, 루프 횟수가 실데이터의 최대 나열 수를 커버해야 함. 실데이터를 `grep`으로 확인하고 상한을 설정할 것.

---

## 11. QNA/감리사례 parent 문서 조회 실패 — 별도 컬렉션 라우팅

### 문제
토픽 브라우즈의 질의회신·감리지적사례 탭에서 "문서를 DB에서 찾을 수 없습니다" 오류 발생.

### 근본 원인
QNA/감리사례 parent 문서는 메인 컬렉션(`k-ifrs-1115-chatbot`)이 아닌 **별도 컬렉션**에 저장:
- QNA → `k-ifrs-1115-qna-parents` (키: `_id`)
- 감리사례 → `k-ifrs-1115-findings-parents` (키: `_id`)

기존 `fetch_parent_doc()`은 메인 컬렉션에서 `chunk_id`로만 조회 → 항상 `None` 반환.

### 해결 (`app/ui/db.py`)
```python
def fetch_parent_doc(parent_id: str) -> dict | None:
    db = _get_mongo_db()
    if parent_id.startswith("QNA-"):
        doc = db[_QNA_PARENT_COLL].find_one({"_id": parent_id}, {"embedding": 0})
    elif parent_id.startswith(("FSS-", "KICPA-")):
        doc = db[_FINDINGS_PARENT_COLL].find_one({"_id": parent_id}, {"embedding": 0})
    else:
        doc = coll.find_one({"chunk_id": parent_id}, {"embedding": 0})
```

**교훈**: PDR(Parent Document Retrieval) 구조에서 parent와 child가 서로 다른 컬렉션에 있을 수 있음. ID 접두사로 라우팅하면 확장성 있게 처리 가능.

---

## 12. parent 문서 메타데이터 중첩 (`metadata` dict)

### 문제
QNA/감리사례 parent 문서의 `title`, `hierarchy` 필드가 표시 안 됨.

### 근본 원인
parent 컬렉션은 `title`, `hierarchy`가 **top-level이 아닌 `metadata` dict 안에** 중첩 저장:
```python
# 메인 컬렉션 (본문)
{"chunk_id": "...", "title": "...", "hierarchy": "..."}

# QNA/감리 parent 컬렉션
{"_id": "QNA-...", "metadata": {"title": "...", "hierarchy": "..."}}
```

### 해결 (`app/ui/topic_tabs.py`)
```python
def _get_parent_field(parent: dict, field: str, default: str = "") -> str:
    val = parent.get(field)          # top-level 먼저
    if val:
        return val
    meta = parent.get("metadata") or {}
    return meta.get(field, default)  # metadata 안에서 찾기
```

**교훈**: 같은 프로젝트라도 컬렉션마다 스키마가 다를 수 있음. 조회 후 `repr(doc.keys())`로 실제 구조를 확인할 것.

---

## 13. `_expand_para_range` — 알파벳 접미사 범위 미지원

### 문제
`IE238A~IE238G` 범위의 적용사례 문단이 DB에서 조회 안 됨.

### 근본 원인
기존 정규식 `r"^([A-Za-z]*?)(\d+)[~～\-]([A-Za-z]*?)(\d+)$"`은 숫자 범위만 처리.
`IE238A`에서 `\d+`가 `238`만 매칭하고 `A` 접미사를 처리 못함.

### 해결 (`app/ui/db.py`)
알파벳 접미사 범위를 숫자 범위보다 **먼저** 체크:
```python
# 알파벳 접미사: IE238A~IE238G → prefix=IE, num=238, A~G
m_alpha = re.match(
    r"^([A-Za-z]*?)(\d+)([A-Za-z])[~～\-]\1\2([A-Za-z])$", cleaned
)
if m_alpha:
    # chr(ord('A')) ~ chr(ord('G')) 범위 생성
    return [f"{prefix}{num}{chr(c)}" for c in range(ord(start_ch), ord(end_ch) + 1)]
```

결과: `IE238A~IE238G` → `['IE238A', 'IE238B', ..., 'IE238G']`

**교훈**: 범위 확장 로직은 실데이터의 모든 패턴을 커버해야 함. 새 데이터 추가 시 `_expand_para_range` 출력을 검증할 것.

---

## 14. 감리지적사례 제목 — "레퍼런스" 접두어 + 빈 title 폴백

### 문제
감리지적사례 expander 제목이 일관되지 않음:
- 일부: `레퍼런스 [FSS-CASE-...] 제목` (DB title에 "레퍼런스" 포함)
- 일부: `FSS-CASE-2022-2311-02` (title이 빈값이라 fid 폴백)
- 일부: `지급 능력이 낮은 고객과의...` (title은 있지만 ID 미포함)

### 해결 (`_build_pdr_label`)
QNA/감리사례 공용 제목 빌더:
```python
def _build_pdr_label(doc_id, title, content):
    clean = re.sub(r"^레퍼런스\s*", "", title)  # 접두어 제거
    if f"[{doc_id}]" in clean: return clean     # A) [ID] 이미 포함
    if not clean or clean == doc_id:             # C) 빈값 → content 첫 줄에서 추출
        m = re.match(r"^(?:레퍼런스\s*)?\[?ID\]?\s*(.+)", first_line)
        return f"[{doc_id}] {desc}"
    return f"[{doc_id}] {clean}"                # B) 설명만 → [ID] prepend
```

**교훈**: DB 데이터가 비일관적일 때, 코드에서 여러 케이스를 방어적으로 처리해야 함. 단일 패턴만 가정하면 일부 문서에서 깨짐.

---

## 15. summary 줄바꿈 — `다.` 이외 한국어 어미 누락

### 문제
`_summary_box()`의 summary 텍스트에서 문장 사이 줄바꿈이 안 되어 벽돌 텍스트로 표시.
- "확약**함**." / "식별할 수 **있음**." / "**높음**." 뒤에 줄바꿈 없음
- "**합니다**." 뒤에만 줄바꿈 삽입됨

### 근본 원인
`_md_to_html()` (app/ui/topic_tabs.py)의 정규식이 **`다.`로 끝나는 문장만** 처리:
```python
# 기존 — "다." 한 패턴만 매칭
t = re.sub(r"(?<=[가-힣])다\s+\.", "다.", t)  # 공백 정규화
t = re.sub(r"(?<=[가-힣])다\.\s+", "다.<br>", t)  # 줄바꿈
```
한국어는 `함.`, `음.`, `됨.`, `임.` 등 다양한 어미로 종결하므로 대부분 누락.

### 해결 (`app/ui/topic_tabs.py`)
**한글 뒤 마침표** 전체를 범용 패턴으로 변경:
```python
# 변경 후 — 모든 한글 어미 + 마침표 패턴 처리
t = re.sub(r"(?<=[가-힣])\s+\.", ".", t)       # 공백 정규화
t = re.sub(r"(?<=[가-힣])\.\s+", ".<br>", t)   # 줄바꿈
```

| 변경 | Before | After |
|------|--------|-------|
| 공백 정규화 | `(?<=[가-힣])다\s+\.` | `(?<=[가-힣])\s+\.` |
| 줄바꿈 삽입 | `(?<=[가-힣])다\.\s+` | `(?<=[가-힣])\.\s+` |

영문/숫자 뒤 마침표(예: `v3.0`, `1115.`)는 lookbehind `[가-힣]`로 영향받지 않음.

**교훈**: 정규식으로 한국어 문장 종결을 처리할 때, 특정 어미(`다`)가 아닌 **한글 + 마침표** 범용 패턴을 사용해야 모든 어미를 커버함.

---

## 16. 물결표(~) Unicode 변형 — U+223C TILDE OPERATOR

### 문제
QNA "관련 회계기준" 섹션의 `문단 50~54, 56~58, B63~B63B`에서 파란색 볼드가 적용되지 않음. `clean_text` step 2 regex가 매칭 실패.

### 근본 원인
kifrs.com 원본 데이터에 **3종류의 물결표**가 혼재:

| 문자 | 코드포인트 | 이름 | DB 출현 수 |
|------|-----------|------|-----------|
| `~` | U+007E | TILDE (ASCII) | 108건 |
| `∼` | U+223C | TILDE OPERATOR | **28건** |
| `～` | U+FF5E | FULLWIDTH TILDE | 3건 |

기존 regex `[~～\-]`가 U+007E(`~`)와 U+FF5E(`～`)만 처리하고, **U+223C(`∼`)를 누락**.

### 해결
모든 물결표 문자 클래스에 `∼`(U+223C) 추가:

```python
# Before
[~～\-]   # 2종만
[~～]     # 2종만

# After
[~～∼\-]  # 3종 모두
[~～∼]    # 3종 모두
```

수정 파일: `text.py`, `db.py`, `pinpoint_panel.py`, `doc_helpers.py`

### 영향 범위
- QNA parents 28건의 문단 범위 표기가 정상 매칭

**교훈**: 외부 데이터의 유사 문자(tilde, dash, quote 등)는 항상 여러 Unicode 변형이 혼재할 수 있음. `repr()` + `ord()` + `U+XXXX`로 실제 코드포인트를 반드시 확인할 것. `grep`만으로는 시각적으로 동일한 변형을 구분할 수 없음.

## 17. `_expand_para_range` — 접미사 없음→있음 범위 + 한글접두사 + 소수점 하위번호 미지원

### 문제
토픽 브라우즈에서 **기준서 원문이 비어있는** 섹션 다수 발견:
- "3단계: 판매/사용 기준 로열티의 제약 (문단 B63~B63B)" — 원문 없음
- "발생원가 투입법 추가 공시 (문단 한129.1~5)" — 원문 없음
- "거래가격 배분 (문단 B34~B34A)" — 원문 없음

### 근본 원인 (3가지)

**1) 접미사 없음→있음 범위 미처리**
`_expand_para_range("B63~B63B")`가 범위 확장에 실패하고 `["B63~B63B"]` 그대로 반환.
기존 알파벳 접미사 정규식은 **양쪽 모두** 접미사가 있어야 매칭 (예: `IE238A~IE238G`).
`B63~B63B`는 시작(`B63`)에 접미사가 없으므로 어느 정규식에도 매칭 안 됨.

**2) 한글 접두사 미지원**
모든 정규식의 접두사 패턴이 `[A-Za-z]*?`로 되어있어 `한129.1~5`의 한글 접두사(`한`)를 매칭 못함.
DB에는 `한129.1`, `한129.2`, ..., `한129.5`가 개별 문서로 존재.

**3) 소수점 하위번호 범위 미지원**
`한129.1~5` 형태의 `prefix + base.start ~ end` 패턴을 처리하는 정규식이 없음.

영향받는 데이터: `B63~B63B` (2곳), `B34~B34A` (1곳), `한129.1~5` (1곳)

### 해결 (`app/ui/db.py`)

**a) 접두사 패턴 범용화**: `[A-Za-z]*?` → `[A-Za-z가-힣]*?` (한글 포함)
```python
_PFX = r"[A-Za-z가-힣]*?"  # 모든 정규식에서 공통 사용
```

**b) 소수점 하위번호 범위 추가** (최우선 체크):
```python
# 한129.1~5 → ["한129.1", "한129.2", ..., "한129.5"]
m_dot = re.match(rf"^({_PFX})(\d+)\.(\d+)[~～\-](\d+)$", cleaned)
if m_dot:
    prefix, base = m_dot.group(1), m_dot.group(2)
    start_sub, end_sub = int(m_dot.group(3)), int(m_dot.group(4))
    return [f"{prefix}{base}.{n}" for n in range(start_sub, end_sub + 1)]
```

**c) 접미사 없음→있음 범위 추가**:
```python
# B63~B63B → ["B63", "B63A", "B63B"]
m_no_to_alpha = re.match(rf"^({_PFX})(\d+)[~～\-]\1\2([A-Za-z])$", cleaned)
if m_no_to_alpha:
    result = [f"{prefix}{num}"]  # 원본(접미사 없음) 포함
    result.extend(f"{prefix}{num}{chr(c)}" for c in range(ord("A"), ord(end_ch) + 1))
```

### 정규식 매칭 순서 (위→아래 우선)

| 순서 | 패턴 | 예시 |
|------|------|------|
| 1 | 소수점 하위번호 | `한129.1~5` |
| 2 | 접미사 없음→있음 | `B63~B63B` |
| 3 | 양쪽 알파벳 접미사 | `IE238A~IE238G` |
| 4 | 숫자 범위 | `B20~B27`, `IE2~IE6` |

### 검증 결과
topics.json 전체 범위 참조 51건 전수 검증 → **ALL RANGES OK**

| 입력 | Before | After |
|------|--------|-------|
| `B63~B63B` | `["B63~B63B"]` (실패) | `["B63", "B63A", "B63B"]` |
| `B34~B34A` | `["B34~B34A"]` (실패) | `["B34", "B34A"]` |
| `한129.1~5` | `["한129.1~5"]` (실패) | `["한129.1", ..., "한129.5"]` |
| `IE238A~IE238G` | 정상 | 정상 |

**교훈**: 범위 확장 로직에서 (1) 접두사 문자셋은 실데이터의 모든 언어를 커버해야 하고, (2) 시작/끝의 접미사 유무 조합, (3) 숫자 체계(정수/소수점)를 모두 고려해야 함. 새 데이터 추가 시 전수 검증 스크립트로 확인할 것.

---

## 18. `finding_descs`에 LLM 생성 텍스트 유출 — 크로스 링크 + 전문 + 깨진 bold

### 문제
토픽 브라우즈 감리지적사례 탭에서 desc 텍스트에 이상하게 짤린 문장이 표시됨.
- "**제공된 지적사례 문서를 검토한 결과, 할인액의 배분 오류**: 에 대한 지적 사례는 있으나..." → bold 닫힘 후 `: 에`가 짤린 것처럼 보임
- "💡 [🔗 크로스 링크 추천] 이 조서를 검토하는..." 텍스트가 desc 안에 포함

### 근본 원인 (3가지)

**1) 크로스 링크 추천 텍스트 유출 (21건)**
`topics.json` 큐레이션 시 LLM이 생성한 응답 전체를 `finding_descs`에 저장.
응답 말미의 `"------💡 [🔗 크로스 링크 추천]..."` 구간까지 포함됨.

**2) LLM 전문(preamble) 포함 ("변동대가의 배분")**
LLM이 "관련 사례가 없다"는 메타 응답을 desc에 그대로 저장:
```
"제공된 지적사례 문서를 검토한 결과, 할인액의 배분 오류: 에 대한 지적 사례는 있으나..."
```
이 텍스트가 `_summary_box()`와 `_desc_blockquote()`로 렌더링되어 UI에 노출.

**3) 깨진 bold 패턴 ("계약의 식별" FSS-CASE-2025-2512-01)**
```
"**목표 달성을 위해 연말에 협력업체에 발주서만 받고 초과 물량을 출고하거나**: ."
```
bold 닫힘 후 `**: .`로 의미 없는 문장이 생성됨.

### 해결 (`data/topic-curation/topics.json`)

**1) 크로스 링크 텍스트 일괄 제거**
```python
# ----- 구분선 이후 전체 삭제
CROSS_LINK_RE = re.compile(r'\s*-{10,}\s*.*$', re.DOTALL)
cleaned = CROSS_LINK_RE.sub('', desc).rstrip()

# ----- 없이 💡 직접 포함된 케이스도 처리
XLINK_RE = re.compile(r'\s*💡\s*\[🔗\s*크로스\s*링크\s*추천\].*$', re.DOTALL)
cleaned = XLINK_RE.sub('', cleaned).rstrip()
```

**2) "변동대가의 배분" finding_desc + summary 교체**
LLM 전문이 포함된 desc를 "할인액의 배분" 토픽의 정상 desc로 교체.
summary도 간결한 사례 설명으로 교체.

**3) "계약의 식별" FSS-CASE-2025-2512-01 교체**
깨진 bold 패턴을 정상 문장으로 전면 교체.

**4) 숨겨진 공백 일괄 정규화 (247건)**
```python
# "다 ." → "다." — _md_to_html()에서 이미 렌더링 시 처리하지만 원본도 정리
SPACE_DOT_RE = re.compile(r'(?<=[가-힣])\s+\.')
cleaned = SPACE_DOT_RE.sub('.', val)
```

**5) summary-embeddings.json 재생성**
```bash
PYTHONPATH=. uv run --env-file .env python app/preprocessing/12-summary-embed.py
```
topics.json의 desc가 변경되었으므로 임베딩(QNA 64건 + 감리사례 18건)도 갱신.

| 수정 항목 | 건수 |
|-----------|------|
| 크로스 링크 텍스트 제거 | 21건 |
| LLM 전문 교체 | 2건 (변동대가의 배분 desc + summary) |
| 깨진 bold 패턴 교체 | 1건 (계약의 식별) |
| 숨겨진 공백 정규화 | 247건 |
| summary-embeddings 재생성 | 82건 |

### 검증 스크립트
```python
# finding_descs 전수 검사
for topic, tdata in data.items():
    for fid, desc in tdata.get("findings", {}).get("finding_descs", {}).items():
        assert "크로스 링크" not in desc
        assert not ("제공된" in desc and "검토한 결과" in desc)
        assert "**: ." not in desc
        assert not re.search(r"[가-힣]\s+\.", desc)
```

**교훈**: LLM으로 큐레이션 데이터를 생성할 때, 응답 전문을 그대로 저장하면 메타 텍스트(전문, 크로스 링크 추천, 면책 문구)가 함께 저장됨. 저장 전 후처리(separator 이후 잘라내기)가 필수.

---

## 19. 버튼 클릭 시 에러/깜빡임 — 이중 rerun + DB 에러 캐시 재생

### 문제
홈 화면 토픽 버튼 클릭 시 에러가 순간 표시된 후 페이지가 전환됨.

### 근본 원인 (3가지)

**1) 이중 rerun 패턴 (`pages.py`, `layout.py`, `topic_browse.py`)**

기존 코드:
```python
if st.button("토픽명", key=safe_key):
    st.session_state.page_state = "topic_browse"
    st.rerun()  # ← 명시적 rerun 호출
```

이 패턴은 **2번 rerun**을 발생시킴:
1. 1차 rerun: 버튼 True → state 변경 → `st.rerun()` → 스크립트 중단
2. 2차 rerun: 새 page_state로 렌더링

1차 rerun 중 **페이지가 절반만 그려진 상태에서 중단**되고, 그 사이 에러/깜빡임이 노출됨.

**2) `st.error()`가 `@st.cache_data` 안에서 호출 (`db.py:88`)**

```python
@st.cache_data(ttl=300)
def _validate_refs_against_db(refs_tuple):
    ...
    doc = _fetch_para_from_db(num)  # 이 안에서 st.error() 호출
```

`@st.cache_data`는 함수 실행 중 `st.error()` 호출을 **기록(녹음)**해두고, 캐시 히트 시마다 **재생**함. 한 번 DB 에러가 나면 **TTL(300초) 동안 매번 같은 에러가 반복 표시**.

**3) 존재하지 않는 함수 참조 (`doc_renderers.py:243`)**

```python
from app.ui.db import fetch_ie_case_docs, find_sub_case_parent_titles
# → find_sub_case_parent_titles는 db.py에 없음 → ImportError
```

IE 적용사례 서브 케이스 렌더링 시 `ImportError` 발생.

### 해결

**a) `on_click` 콜백 패턴으로 전환 → 1회 rerun만 발생**

```python
# Before — 2회 rerun
if st.button("토픽명", key=safe_key):
    _navigate_to_topic(topic)  # 안에서 st.rerun() 호출

# After — 1회 rerun (on_click은 rerun 전에 실행됨)
st.button("토픽명", key=safe_key, on_click=_navigate_to_topic, args=(topic,))

def _navigate_to_topic(topic):
    st.session_state.selected_topic = topic
    st.session_state.page_state = "topic_browse"
    # st.rerun() 불필요 — Streamlit이 콜백 후 자동 rerun
```

수정 파일: `pages.py` (토픽 버튼 + 새 검색 ×2), `layout.py` (처음으로), `topic_browse.py` (새 검색), `session.py` (`_go_home`에서 `st.rerun()` 제거)

**b) `st.error()` → `logging.warning()`으로 교체 (`db.py`)**

```python
# Before — 빨간 에러 박스가 캐시에 녹음됨
except Exception as e:
    st.error(f"DB 조회 중 오류: {e}\n{traceback.format_exc()}")

# After — 서버 로그에만 기록, UI 노출 없음
except Exception as e:
    import logging
    logging.warning("_fetch_para_from_db(%s) 오류: %s", para_num, e)
    return None
```

**c) 존재하지 않는 함수 → regex로 직접 추출 (`doc_renderers.py`)**

```python
# Before — ImportError
from app.ui.db import find_sub_case_parent_titles
parent_map = find_sub_case_parent_titles((case_group_title,))

# After — "사례 1A" → "사례 1" regex 추출
m_sub = re.match(r"^(사례\s+\d+)[A-Za-z]", case_group_title)
parent_cgt = m_sub.group(1)  # "사례 1"
```

### 핵심 원칙

| 패턴 | rerun 횟수 | 깜빡임 |
|------|-----------|--------|
| `if st.button: st.rerun()` | **2회** | 있음 |
| `st.button(on_click=callback)` | **1회** | 없음 |

**교훈**: Streamlit에서 페이지 전환/상태 변경은 반드시 `on_click` 콜백 패턴을 사용할 것. `if st.button: st.rerun()` 패턴은 이중 rerun으로 인해 깜빡임/에러가 발생함. `@st.cache_data` 함수 안에서 `st.error()` 등 UI 출력 함수를 호출하면 캐시에 녹음되어 의도치 않게 반복 재생됨.

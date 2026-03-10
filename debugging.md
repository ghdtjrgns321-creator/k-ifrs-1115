# Streamlit 디버깅 교훈 (k-ifrs-1115-chatbot)

> 최종 업데이트: 2026-03-10

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

# app/ui/text.py
# 문서 텍스트 정규화 파이프라인.
#
# 소스 유형별로 원본 포맷이 다릅니다:
#   본문/적용지침 — "[문맥: ...]" 접두어 + 조항 텍스트
#   질의회신      — "관련 회계기준 / 질의 / 회신" 섹션 (줄바꿈 누락된 경우 많음)
#   감리사례      — "# 배경 및 질의 / # 감리지적내용" 마크다운 헤딩
# 이 모듈의 함수들이 이들을 일관된 형태로 정리합니다.

import re

# ── 정규식 상수 ──────────────────────────────────────────────────────────────────

# 임베딩 시 삽입된 "[문맥: ...]" 접두어 제거용
_CONTEXT_PREFIX_RE = re.compile(r"^\[문맥:.*?\]\s*", re.MULTILINE)

# 헤딩 축소: # → ####, ## → ##### (모달 내 큰 헤딩이 레이아웃을 깨는 것 방지)
_HEADING_RE = re.compile(r"^(#{1,3})\s", re.MULTILINE)

# QNA 섹션 마커 — 줄바꿈이 누락된 wall-of-text에서도 섹션을 분리합니다.
# 06-qna-embed.py의 전처리 패턴과 동일한 로직을 표시 계층에서 재적용합니다.
_QNA_SECTION_INJECT_RE = re.compile(
    r"(?<=[.?!)\]됨함음다])\s*"       # 문장 끝 뒤에
    r"(?=(?:회\s*신|관련\s*회계\s*기준|질\s*의|본문|판단\s*근거|참고\s*자료|검토\s*과정)"
    r"(?:\s|[□ㅇ▶#\[:]))",            # 섹션 마커가 올 때
)

# 번호 목차 패턴 — "1. 질의 내용", "2. 검토 결과와 결론" 등
_QNA_NUMBERED_SECTION_RE = re.compile(
    r"(?:^|\n)\s*(\d+)\.\s*(질의|검토|결론|결정|조사|사실관계)",
)

# 문단 번호 참조 정규식
# 패턴 1: "문단 23", "문단 B2", "문단 IE5", "문단 B2~B89", "문단 BC63B" 등
# 패턴 2: 단독 접두사 번호 "BC408", "B59A" — 문단 없이 단독으로 나올 때
_PARA_REF_RE = re.compile(
    r"(?:문단\s*(?:IE|BC|B)?\d+[A-Za-z]*(?:[~～](?:IE|BC|B)?\d+[A-Za-z]*)?)"
    r"|(?<![A-Za-z0-9])(?:IE|BC|B)\d+[A-Za-z]*(?:[~～](?:IE|BC|B)?\d+[A-Za-z]*)?(?![A-Za-z0-9])"
)

# "문단 47 및 52", "문단 B2, B3 및 B4" 같은 접속사 연결 패턴
_PARA_CONJ_RE = re.compile(
    r"문단\s*((?:IE|BC|B)?\d+[A-Za-z]*)"       # 첫 번호: "47" or "B2"
    r"((?:\s*(?:[,，]|및|과|와|또는|그리고)\s*"   # 접속사: ",", "및", "과", "와" 등
    r"(?:문단\s*)?(?:(?:IE|BC|B)?\d+[A-Za-z]*))+)"  # 후속 번호: "52", "B3" 등
)


# ── 공개 함수 ────────────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """~ 문자 이스케이프: Streamlit markdown이 ~text~를 strikethrough로 파싱하기 때문.
    문단 범위 표기 'B2~B89' 등에서 발생합니다.
    """
    return text.replace("~", "\\~")


def _extract_para_ids_from_docs(docs: list[dict]) -> set[str]:
    """현재 evidence_docs에서 참조 가능한 문단 ID 집합을 반환합니다.

    paragraph_id → title → hierarchy 순서로 폴백하여 ID를 수집합니다.
    퀵뷰 칩과 링크 강조 색상 결정에 사용됩니다.
    """
    ids: set[str] = set()
    for doc in docs:
        pid = doc.get("paragraph_id") or doc.get("title") or doc.get("hierarchy", "")
        if pid:
            ids.add(str(pid).strip())
    return ids


def _extract_para_refs(text: str) -> list[str]:
    """텍스트에서 문단 참조 패턴을 모두 추출합니다.

    '문단 B23', '문단 55~59', 'BC408' 등의 패턴을 찾아 리스트로 반환합니다.
    '문단 47 및 52', '문단 B2, B3 및 B4' 같은 접속사 패턴도 처리합니다.
    doc_renderers.py에서 문단 참조 칩 렌더링에 사용됩니다.
    """
    refs = _PARA_REF_RE.findall(text)

    # 접속사로 연결된 문단 참조 추출: "문단 47 및 52", "문단 B2, B3 및 B4"
    # _PARA_REF_RE는 "문단 47"만 잡고 "및 52"의 52는 놓침
    # → 접속사 뒤의 번호를 앞 문단의 접두사(IE/BC/B 등)를 상속하여 추출
    for m in _PARA_CONJ_RE.finditer(text):
        first_num = m.group(1)                      # "47" or "B2"
        conj_part = m.group(2)                      # " 및 52" or ", B3 및 B4"
        # 첫 번호에서 접두사(IE/BC/B) 추출
        prefix_m = re.match(r"^(IE|BC|B)?", first_num)
        prefix = prefix_m.group(1) or "" if prefix_m else ""
        # 접속사 부분에서 개별 번호 추출
        for num in re.findall(r"(?:IE|BC|B)?\d+[A-Za-z]*", conj_part):
            has_prefix = bool(re.match(r"^(?:IE|BC|B)", num))
            full_ref = f"문단 {num}" if has_prefix else f"문단 {prefix}{num}"
            if full_ref not in refs:
                refs.append(full_ref)

    return refs


def _para_ref_to_num(ref: str) -> str:
    """'문단 B23' → 'B23' 형태의 순수 번호 문자열로 변환합니다."""
    raw = ref.replace(" ", "").replace("\u00a0", "")
    return re.sub(r"^문단", "", raw)


def clean_text(text: str) -> str:
    """크롤링 아티팩트·줄바꿈 파편화를 정제하는 정규식 파이프라인.

    처리 순서:
      0.  %N 아티팩트 제거 (QNA 데이터의 %1, %2 등 형식 마커)
      0.5 **[문단 XXX]** 볼드 prefix → <strong> HTML로 변환 (span 삽입으로 인한 마크다운 파괴 방지)
      1.  문단 번호 앞뒤 줄바꿈 → 공백 치환 (괄호 번호 suffix 포함)
      2.  문단 참조 패턴을 파란색 볼드 HTML로 강조
      3.  단독 BC/IE/B 번호도 파란색 볼드 HTML로 강조
      4.  괄호 내부 문단 참조 주변 줄바꿈 제거
      5.  리스트 항목 (1)(2) 앞 줄바꿈 유지 + 뒤 줄바꿈 제거
      6.  문장 마침표 뒤 줄바꿈으로 숨통 트기
      7.  3개 이상 연속 줄바꿈 → 2개 압축
    """
    # 0) %N 아티팩트 제거 — QNA 데이터의 "%1 회사는..." → "회사는..."
    text = re.sub(r"^%\s*\d+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"%%\s*\d+\s*", "", text)  # %%4 같은 패턴

    # 0.1) 각주 슈퍼스크립트 정리 — 크롤링 시 <sup>(주1)</sup> → "^(주1)" 변환 잔재
    # "1백만원^\n(주1)\n에" → "1백만원(주1)에" (인라인 복원)
    text = re.sub(r"\^\s*\n*\s*(\(주\d+\))\s*\n*\s*", r"\1", text)

    # 0.2) 크롤링 구두점 아티팩트 정리 — HTML→text 변환 시 중복 구두점 발생
    # "있습니다,,," → "있습니다," / "막습니다,." → "막습니다."
    text = re.sub(r",{2,}", ",", text)          # 연속 쉼표 → 1개
    text = re.sub(r"\.{2,}", ".", text)          # 연속 마침표 → 1개
    text = re.sub(r",\.", ".", text)             # ,. → .
    text = re.sub(r"\.,", ".", text)             # ., → .

    # 0.5) **[문단 XXX]** → <strong>[문단 XXX]</strong> 변환
    # 이유: step 2/3에서 내부에 <span>이 삽입되면 **[...]** 마크다운 볼드가 깨짐
    # 예: **[문단 B59A]** → step2가 "문단 B59" 만 span으로 감싸 **[<span>...</span>A]** 형태가 됨
    text = re.sub(
        r"\*\*(\[[^\]]+\])\*\*",
        r'<strong>\1</strong>',
        text,
    )

    # 1) 문단 번호 앞뒤 줄바꿈 → 공백 치환 (가장 중요한 클리닝)
    # (?:\([0-9가-힣]+\))? 추가: "문단 35(1)" 처럼 괄호 번호가 붙은 케이스도 처리
    text = re.sub(
        r"\s*\n+\s*(문단\s*[A-Za-z0-9~～]+(?:\([0-9가-힣]+\))?(?:에서)?)\s*\n+\s*",
        r" \1 ",
        text,
    )
    # 2) 문단 참조 패턴 → 파란색 볼드 HTML 강조
    # [A-Za-z]* 추가: "문단 B59A", "문단 BC414V" 처럼 숫자 뒤 알파벳 suffix도 완전히 매칭
    # (?<!>) 추가: <strong> 태그 내부에 이미 삽입된 참조는 재처리 방지
    text = re.sub(
        r"(?<!>)(문단\s*(?:IE|BC|B)?\d+[A-Za-z]*(?:[~～\-](?:IE|BC|B)?\d+[A-Za-z]*)?)",
        r'<span style="color:#1f77b4;font-weight:600;">\1</span>',
        text,
    )
    # 2.5) 접속사 뒤 bare 숫자도 강조 — "문단 47</span> 및 52" → "및 <span>52</span>"
    # 체이닝 처리: "문단 47, 52 및 53" → 각 숫자에 순차적으로 span 적용
    # 괄호 suffix 허용: "문단 35</span>(3), 37" → (3) 건너뛰고 37도 처리
    _CONJ = r'(?:[,，]|및|과|와|또는|그리고)'
    _NUM_RANGE = r'(?:IE|BC|B)?\d+[A-Za-z]*(?:[~～\-](?:IE|BC|B)?\d+[A-Za-z]*)?'
    for _ in range(15):  # 실데이터에 13개 나열 존재
        text, n = re.subn(
            rf'(</span>(?:\([0-9가-힣]+\))?\s*{_CONJ}\s*)({_NUM_RANGE})',
            r'\1<span style="color:#1f77b4;font-weight:600;">\2</span>',
            text,
        )
        if n == 0:
            break
    # 3) 단독 BC/B/IE 번호 → 파란색 볼드 HTML 강조 (이미 span으로 감싼 부분 제외)
    # [A-Za-z]* 추가: "B59A", "BC414V" 같은 suffix 포함 번호 완전 매칭
    text = re.sub(
        r"(?<![\w>])((?:IE|BC|B)\d+[A-Za-z]*(?:[~～](?:IE|BC|B)?\d+[A-Za-z]*)?)(?![\w가-힣])",
        r'<span style="color:#1f77b4;font-weight:600;">\1</span>',
        text,
    )
    # 4) 괄호 안 문단 참조 주변 줄바꿈 제거
    text = re.sub(
        r"(\([^)]{0,30})\n{1,3}((?:문단\s*(?:IE|BC|B)?\d+[^)]{0,30}))\n{1,3}(\))",
        r"\1 \2\3",
        text,
    )
    # 5) 리스트 항목 (1)(2) 앞 줄바꿈 정렬 + 뒤 줄바꿈 제거
    text = re.sub(r"\n*\s*(\([0-9가-하]+\))\s*\n+", r"\n\n\1 ", text)
    # 6) 문장 마침표 뒤 줄바꿈 — 소수점("1.5") 영향 방지: 마침표 뒤 한글일 때만 적용
    text = re.sub(r"다\. (?=[가-힣])", "다.\n\n", text)
    # 7) 3개 이상 연속 줄바꿈 압축
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 8a) 각주 정의 — 마침표 뒤 "(주N)설명..." 전체를 줄바꿈 + 회색 작은 글씨로 분리
    # "없다. (주1)이 사례에서 화폐금액은..." → 본문과 시각적으로 분리된 각주 블록
    text = re.sub(
        r'(?<=\.)\s*(\(주\d+\)[^\n]+)',
        r'<br><span style="color:#94a3b8;font-size:0.85em;"> \1</span>',
        text,
    )
    # 8b) 인라인 각주 마커 — 8a에서 처리 안 된 나머지 "(주N)"만 작은 글씨로 표시
    # sup 대신 span 사용 — sup은 줄 높이를 깨뜨려 비정상적 간격 유발
    text = re.sub(
        r'(?<!">)\(주(\d+)\)',
        r'<span style="color:#94a3b8;font-size:0.75em;">(주\1)</span>',
        text,
    )
    return text


def _clean_whitespace(text: str) -> str:
    """연속된 3개 이상의 줄바꿈을 2개로 압축합니다 (하위 호환 래퍼)."""
    return re.sub(r"\n{3,}", "\n\n", text)


def _normalize_doc_content(text: str, source: str) -> str:
    """문서 콘텐츠를 소스 유형과 무관하게 일관된 마크다운으로 정규화합니다."""
    # 1) 임베딩용 접두어 제거
    text = _CONTEXT_PREFIX_RE.sub("", text).strip()

    # 2) 마크다운 헤딩 축소 (#→####, ##→#####)
    text = _HEADING_RE.sub(lambda m: "#" * (len(m.group(1)) + 3) + " ", text)

    # 3) 소스별 포맷팅
    if source in ("질의회신", "QNA"):
        text = _format_qna(text)
    elif source == "감리사례":
        text = _format_findings(text)
    else:
        # 본문/적용지침 — soup.get_text(separator="\n")로 생긴 교차참조 분리 복원
        # "문단 B58\n의 기준을" → "문단 B58의 기준을" (문장 중간 참조 이음)
        text = re.sub(
            r"(문단\s*[A-Za-z0-9~～]+)\n([의에이가을를은는로으로와과도만부터까지])",
            r"\1\2",
            text,
        )
        # "\n문단 35(1)\n참조" → " 문단 35(1) 참조" (독립 행 참조 인라인화)
        text = re.sub(
            r"\n(문단\s*[A-Za-z0-9~～]+\([0-9가-힣]+\))\n",
            r" \1 ",
            text,
        )
        # 단일 줄바꿈을 이중 줄바꿈으로 변환하여 단락 분리
        text = _ensure_paragraph_breaks(text)

    return text


def _ensure_paragraph_breaks(text: str) -> str:
    """단일 줄바꿈(\n)을 이중 줄바꿈(\n\n)으로 변환합니다.

    마크다운에서 단일 줄바꿈은 공백으로 처리되어 단락이 분리되지 않습니다.
    이미 이중 줄바꿈인 곳은 건드리지 않습니다.
    """
    return re.sub(r"(?<!\n)\n(?!\n)", "\n\n", text)


def _format_qna(text: str) -> str:
    """질의회신 콘텐츠를 읽기 쉬운 구조로 변환합니다.

    처리 순서:
      1. wall-of-text에서 섹션 마커 앞에 줄바꿈 주입
      2. 섹션 키워드를 볼드 + 구분선으로 변환
      3. 번호 목차("1. 질의 내용" 등)를 볼드로 강조
      4. 단일 줄바꿈을 이중으로 변환하여 단락 분리
    """
    # 1) wall-of-text 분리 — 문장 끝 바로 뒤에 섹션 마커가 오면 줄바꿈 삽입
    text = _QNA_SECTION_INJECT_RE.sub("\n", text)

    # 2) 섹션 키워드를 구분선+볼드로 변환
    section_keywords = [
        "관련 회계기준", "회신", "질의", "본문",
        "판단근거", "참고 자료", "참고자료", "검토과정",
    ]
    lines = text.split("\n")
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped in section_keywords:
            result.append(f"\n---\n**{stripped}**\n")
        else:
            # 3) 번호 목차를 볼드로 ("1. 질의 내용" → "**1. 질의 내용**")
            m = re.match(
                r"^(\d+)\.\s*(질의\s*내용|검토\s*내용.*|결론.*|결정.*|조사\s*결과.*|사실관계.*)",
                stripped,
            )
            if m:
                result.append(f"\n---\n**{stripped}**\n")
            else:
                result.append(line)
    text = "\n".join(result)

    # 4) 단락 분리
    text = _ensure_paragraph_breaks(text)
    return text


def _format_findings(text: str) -> str:
    """감리사례 콘텐츠를 정리합니다.

    감리사례는 이미 마크다운 헤딩이 있어 구조화되어 있지만,
    헤딩 축소 후 단락 분리만 보장하면 됩니다.
    """
    text = re.sub(r"^(레퍼런스\s.+)$", r"**\1**", text, flags=re.MULTILINE)
    text = _ensure_paragraph_breaks(text)
    return text

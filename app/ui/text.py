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
    r"(?<=[.?!)\]됨함음다])\s*"  # 문장 끝 뒤에
    r"(?=(?:회\s*신|관련\s*회계\s*기준|질\s*의|본문|판단\s*근거|참고\s*자료|검토\s*과정)"
    r"(?:\s|[□ㅇ▶#\[:]))",  # 섹션 마커가 올 때
)

# 번호 목차 패턴 — "1. 질의 내용", "2. 검토 결과와 결론" 등
_QNA_NUMBERED_SECTION_RE = re.compile(
    r"(?:^|\n)\s*(\d+)\.\s*(질의|검토|결론|결정|조사|사실관계)",
)

# 문단 번호 참조 정규식
# 패턴 1: "문단 23", "문단 B2", "문단 IE5", "문단 B2~B89", "문단 BC63B" 등
# 패턴 2: 단독 접두사 번호 "BC408", "B59A" — 문단 없이 단독으로 나올 때
# 범위 구분자: ~ ～ ∼ (물결표 3종) + - – — (하이픈, en-dash, em-dash)
_RANGE_SEP = r"[~～∼\-–—]"
_PARA_REF_RE = re.compile(
    rf"(?:문단\s*(?:IE|BC|B)?\d+[A-Za-z]*(?:{_RANGE_SEP}(?:IE|BC|B)?\d+[A-Za-z]*)?)"
    rf"|(?<![A-Za-z0-9])(?:IE|BC|B)\d+[A-Za-z]*(?:{_RANGE_SEP}(?:IE|BC|B)?\d+[A-Za-z]*)?(?![A-Za-z0-9])"
)

# "문단 47 및 52", "문단 B2, B3 및 B4" 같은 접속사 연결 패턴
# 첫 번호에 범위(50-51)가 붙을 수 있으므로 _RANGE_SEP 포함
_PARA_CONJ_RE = re.compile(
    rf"문단\s*((?:IE|BC|B)?\d+[A-Za-z]*(?:{_RANGE_SEP}(?:IE|BC|B)?\d+[A-Za-z]*)?)"  # 첫 번호(범위 포함)
    r"((?:\s*(?:[,，]|및|과|와|또는|그리고)\s*"  # 접속사: ",", "및", "과", "와" 등
    rf"(?:문단\s*)?(?:(?:IE|BC|B)?\d+[A-Za-z]*(?:{_RANGE_SEP}(?:IE|BC|B)?\d+[A-Za-z]*)?))+)"  # 후속 번호
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
        first_num = m.group(1)  # "47" or "B2"
        conj_part = m.group(2)  # " 및 52" or ", B3 및 B4"
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
    text = re.sub(r",{2,}", ",", text)  # 연속 쉼표 → 1개
    text = re.sub(r"\.{2,}", ".", text)  # 연속 마침표 → 1개
    text = re.sub(r",\.", ".", text)  # ,. → .
    text = re.sub(r"\.,", ".", text)  # ., → .

    # 0.5) **text** → <strong>text</strong> 변환 (모든 마크다운 볼드)
    # 이유: step 2/3에서 내부에 <span>이 삽입되면 마크다운 파서가 ** 를 볼드로 인식 못함
    # 예: **"대가의 회수 가능성"** → step2 후 **"<span>문단 9</span>"** 형태가 되어 ** 노출
    text = re.sub(
        r"\*\*(.+?)\*\*",
        r"<strong>\1</strong>",
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
    _RS = r"[~～∼\-–—]"  # 범위 구분자 (물결표 3종 + 하이픈/en-dash/em-dash)
    text = re.sub(
        rf"(?<!>)(문단\s*(?:IE|BC|B)?\d+[A-Za-z]*(?:{_RS}(?:IE|BC|B)?\d+[A-Za-z]*)?)",
        r'<span style="color:#1f77b4;font-weight:600;">\1</span>',
        text,
    )
    # 2.5) 접속사 뒤 bare 숫자도 강조 — "문단 47</span> 및 52" → "및 <span>52</span>"
    # 체이닝 처리: "문단 47, 52 및 53" → 각 숫자에 순차적으로 span 적용
    # 괄호 suffix 허용: "문단 35</span>(3), 37" → (3) 건너뛰고 37도 처리
    _CONJ = r"(?:[,，]|및|과|와|또는|그리고)"
    _NUM_RANGE = rf"(?:IE|BC|B)?\d+[A-Za-z]*(?:{_RS}(?:IE|BC|B)?\d+[A-Za-z]*)?"
    for _ in range(15):  # 실데이터에 13개 나열 존재
        text, n = re.subn(
            rf"(</span>(?:\([0-9가-힣]+\))?\s*{_CONJ}\s*)({_NUM_RANGE})",
            r'\1<span style="color:#1f77b4;font-weight:600;">\2</span>',
            text,
        )
        if n == 0:
            break
    # 3) 단독 BC/B/IE 번호 → 파란색 볼드 HTML 강조 (이미 span으로 감싼 부분 제외)
    # [A-Za-z]* 추가: "B59A", "BC414V" 같은 suffix 포함 번호 완전 매칭
    # (?![A-Za-z0-9_]): ASCII 영숫자 연속만 방지. Python 3의 \w는 한글도 포함하므로
    # "B9~B13에서는" 같은 정상 패턴이 범위 전체 매칭되려면 한글 조사를 허용해야 함
    text = re.sub(
        rf"(?<![A-Za-z0-9_>])((?:IE|BC|B)\d+[A-Za-z]*(?:{_RS}(?:IE|BC|B)?\d+[A-Za-z]*)?)(?![A-Za-z0-9_])",
        r'<span style="color:#1f77b4;font-weight:600;">\1</span>',
        text,
    )
    # 3.5) 문서 ID 강조 — QNA-xxx, FSS-CASE-xxx, KICPA-CASE-xxx, EDU-xxx 패턴
    # AI 답변에서 사례·질의회신·교육자료 인용 시 사용자가 왼쪽 패널과 매칭할 수 있도록 강조
    # 대괄호로 감싼 패턴: [QNA-xxx] → [<span>QNA-xxx</span>]
    text = re.sub(
        r"\[((?:FSS-CASE|KICPA-CASE|QNA|EDU)-[\w-]+)\]",
        r'[<span style="color:#1f77b4;font-weight:600;">\1</span>]',
        text,
    )
    # bare ID 패턴: 대괄호 없이 나오는 QNA-xxx, EDU-KASB-xxx 등도 강조
    # (?<![\w>-]) : 이미 span 처리된 것(>) 또는 다른 단어 일부인 것 제외
    text = re.sub(
        r"(?<![\w>])((?:FSS-CASE|KICPA-CASE|QNA|EDU)-[\w-]+)",
        r'<span style="color:#1f77b4;font-weight:600;">\1</span>',
        text,
    )
    # 3.6) 적용사례 참조 강조 — "사례11", "사례 1A", "사례 28B" 등
    # IE 적용사례 번호를 문단 참조와 동일한 파란색 볼드로 표시
    text = re.sub(
        r"(?<![가-힣A-Za-z>])(사례\s*\d+[A-Za-z]?)(?![가-힣A-Za-z0-9])",
        r'<span style="color:#1f77b4;font-weight:600;">\1</span>',
        text,
    )
    # 4a) 여는 괄호 직후 줄바꿈 제거 — "(\n문단 35~37에 따라)" → "(문단 35~37에 따라)"
    # 크롤링 시 soup.get_text(separator="\n")가 괄호와 문단 참조 사이를 분리한 잔재
    text = re.sub(r"\(\s*\n+\s*(문단)", r"(\1", text)
    # 4b) 괄호 안 문단 참조 양쪽 줄바꿈 제거 — "(참고\n문단 35\n)" → "(참고 문단 35)"
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
        r"(?<=\.)\s*(\(주\d+\)[^\n]+)",
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
    # 9) 물결표 → HTML 엔티티 — Streamlit markdown이 ~text~를 취소선(strikethrough)으로
    #    파싱하여 "20~30"이 줄 그어지거나 "2030"으로 표시되는 문제 방지.
    #    clean_text 출력은 항상 unsafe_allow_html=True로 렌더링되므로 엔티티가 안전함.
    text = text.replace("~", "&#126;").replace("∼", "&#126;").replace("～", "&#126;")
    return text


def _clean_whitespace(text: str) -> str:
    """연속된 3개 이상의 줄바꿈을 2개로 압축합니다 (하위 호환 래퍼)."""
    return re.sub(r"\n{3,}", "\n\n", text)


def _normalize_doc_content(text: str, source: str) -> str:
    """문서 콘텐츠를 소스 유형과 무관하게 일관된 마크다운으로 정규화합니다."""
    # 1) 임베딩용 접두어 제거
    text = _CONTEXT_PREFIX_RE.sub("", text).strip()

    # 1.5) 전처리 문단 접두사 제거 — "**[문단 37]** " (03-chunk에서 추가, UI에선 라벨과 중복)
    text = re.sub(r"^\*\*\[문단\s*[^\]]+\]\*\*\s*", "", text)

    # 2) 마크다운 헤딩 축소 (#→####, ##→#####)
    text = _HEADING_RE.sub(lambda m: "#" * (len(m.group(1)) + 3) + " ", text)

    # 3) 소스별 포맷팅
    if source in ("질의회신", "QNA"):
        text = _format_qna(text)
    elif source == "감리사례":
        text = _format_findings(text)
    else:
        # 본문/적용지침 — soup.get_text(separator="\n")로 생긴 교차참조 분리 복원

        # 문장 중간 "text\n문단 XX" 복원 — 크롤링 시 <span> 태그가 줄바꿈으로 변환된 잔재
        # 마침표/물음표 뒤 줄바꿈은 새 단락이므로 유지 (21건), 그 외는 join (455건)
        text = re.sub(
            r"(?<![.!?。])\n(문단\s*(?:IE|BC|B)?\d+)",
            r" \1",
            text,
        )

        # "문단 B58\n의 기준을" → "문단 B58의 기준을" (문장 중간 참조 이음)
        text = re.sub(
            r"(문단\s*[A-Za-z0-9~～]+(?:\([0-9가-힣]+\))?)\n([의에이가을를은는로으로와과도만부터까지])",
            r"\1\2",
            text,
        )
        # bare B/BC/IE 참조 + 줄바꿈 + 조사 이음 — "B9~B13\n에서는" → "B9~B13에서는"
        # "문단" 접두사 없이 단독으로 나오는 참조도 동일하게 처리
        text = re.sub(
            r"((?:IE|BC|B)\d+[A-Za-z]*(?:[~～∼\-–—](?:IE|BC|B)?\d+[A-Za-z]*)?)\n([의에이가을를은는로으로와과도만부터까지])",
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

    마크다운 테이블 행(|로 시작하는 줄)은 단일 \n이어야 렌더링되므로 보호합니다.
    """
    # 테이블 행 사이의 \n을 보호 마커로 치환 → 전체 \n→\n\n 변환 → 마커 복원
    # 테이블 행: | 로 시작하는 줄 (구분선 |---|---| 포함)
    text = re.sub(
        r"(\|[^\n]*)\n(?=\s*\|)",
        lambda m: m.group(1) + "\x00",
        text,
    )
    text = re.sub(r"(?<!\n)\n(?!\n)", "\n\n", text)
    return text.replace("\x00", "\n")


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
        "관련 회계기준",
        "회신",
        "질의",
        "본문",
        "판단근거",
        "참고 자료",
        "참고자료",
        "검토과정",
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


# ── 마크다운 테이블 → HTML 변환 ──────────────────────────────────────────────

# Why: _render_document_expander에서 \n→<br> 변환 시 마크다운 테이블 구조가 파괴됨.
#      테이블 블록을 미리 HTML <table>로 변환하면 <br> 변환의 영향을 받지 않음.

_MD_TABLE_BLOCK_RE = re.compile(
    r"((?:^|\n)(?:\|[^\n]+\|[ \t]*\n?){2,})",
    re.MULTILINE,
)


def _clean_table_grid(
    header: list[str] | None,
    rows: list[list[str]],
) -> tuple[list[str] | None, list[list[str]]]:
    """파이프 테이블에서 빈 열·빈 행을 정리합니다.

    Why: 11-fix-external-tables.py가 HTML colspan/rowspan을 무시하고 변환하므로
         항상 비어있는 열과 모든 셀이 빈 행이 대량 생성됨.
         QNA 분개 테이블(3열, 빈 열 없음)은 영향 없음.
    """
    if not rows:
        return header, rows

    # 1) 빈 행 제거 — 모든 셀이 공백인 행
    rows = [r for r in rows if any(c.strip() for c in r)]

    # 2) 빈 열 제거 — 헤더+모든 데이터에서 공백인 열
    max_cols = max((len(r) for r in rows), default=0)
    if header:
        max_cols = max(max_cols, len(header))

    keep: list[int] = []
    for ci in range(max_cols):
        has = False
        if header and ci < len(header) and header[ci].strip():
            has = True
        if not has:
            for r in rows:
                if ci < len(r) and r[ci].strip():
                    has = True
                    break
        if has:
            keep.append(ci)

    if len(keep) < max_cols:
        header = [header[i] for i in keep if i < len(header)] if header else None
        rows = [[r[i] for i in keep if i < len(r)] for r in rows]

    return header, rows


def _md_table_to_html(block: str) -> str:
    """단일 마크다운 테이블 블록을 HTML <table>로 변환합니다.

    IE 외부 테이블(11-fix-external-tables.py 산출물)의 경우:
      - 빈 열·빈 행을 정리하고
      - 설명 행(내용 셀 1~2개)은 테이블 밖 텍스트로 분리
      - 분개 행(내용 셀 3개 이상)만 테이블로 렌더링
    QNA 분개 테이블(3열, 빈 열 없음)은 그대로 통과.
    """
    lines = [ln.strip() for ln in block.strip().split("\n") if ln.strip()]
    if len(lines) < 2:
        return block

    def _parse_cells(row: str) -> list[str]:
        row = row.strip().strip("|")
        return [c.strip() for c in row.split("|")]

    # 구분선(|---|---|) 여부로 헤더 판별
    has_header = bool(re.match(r"^[\s|:\-]+$", lines[1]))

    style = (
        "border-collapse:collapse; width:100%; margin:0.5rem 0; "
        "font-size:0.88em; line-height:1.6;"
    )
    cell_style = "border:1px solid #d1d5db; padding:4px 8px;"
    header_style = f"{cell_style} background:#f0f4ff; font-weight:600; text-align:center;"

    # 파싱
    header_cells: list[str] | None = None
    if has_header:
        header_cells = _parse_cells(lines[0])
        data_lines = lines[2:]
    else:
        data_lines = lines

    parsed_rows: list[list[str]] = []
    for row_line in data_lines:
        if re.match(r"^[\s|:\-]+$", row_line):
            continue
        parsed_rows.append(_parse_cells(row_line))

    # 빈 열·빈 행 정리
    header_cells, parsed_rows = _clean_table_grid(header_cells, parsed_rows)

    if not parsed_rows:
        return block

    num_cols = max((len(r) for r in parsed_rows), default=0)
    if header_cells:
        num_cols = max(num_cols, len(header_cells))

    # 빈 헤더(모든 셀 공백)이면 헤더 자체를 생략
    if header_cells and not any(h.strip() for h in header_cells):
        header_cells = None

    # Why: 4열 이상이고 설명 행(내용 셀 ≤2)이 있으면, 설명을 <div>로 분리하여
    #       expander 전체 너비를 사용. 분개 행은 CSS grid로 렌더링.
    #       <table> 인라인 스타일은 Streamlit CSS가 덮어쓰고,
    #       마크다운 파이프 테이블은 \n→<br> 변환으로 깨지므로 <div> 사용.
    has_sparse = any(
        sum(1 for c in r if c.strip()) <= 2 for r in parsed_rows
    )
    if has_sparse and num_cols >= 4 and not header_cells:
        parts: list[str] = []
        je_style = (
            "display:grid; grid-template-columns:1fr 1fr 1fr 1fr; "
            "gap:0; margin:0.2rem 0 0.8rem; font-size:0.88em; line-height:1.6;"
        )
        je_cell = (
            "padding:4px 10px; border:1px solid #e2e8f0; "
            "white-space:nowrap;"
        )

        for cells in parsed_rows:
            while len(cells) < num_cols:
                cells.append("")
            filled = [c for c in cells if c.strip()]
            if len(filled) <= 2:
                # 설명 행 → <div> 텍스트 (expander 전체 너비 사용)
                desc = " ".join(c.replace("\r", " ") for c in filled)
                desc = re.sub(r"\s{2,}", " ", desc).strip()
                parts.append(
                    f'<div style="font-weight:600; margin:0.6rem 0 0.1rem; '
                    f'font-size:0.9em;">{desc}</div>'
                )
            else:
                # 분개 행 → CSS grid (4셀: 계정, 금액, 계정, 금액)
                grid_cells = "".join(
                    f'<div style="{je_cell}">{c}</div>' for c in filled
                )
                parts.append(f'<div style="{je_style}">{grid_cells}</div>')

        return "".join(parts)

    # 일반 테이블 (QNA 분개 등): 기존 로직
    rows_html: list[str] = []

    if header_cells:
        hcells = "".join(f'<th style="{header_style}">{h}</th>' for h in header_cells)
        rows_html.append(f"<thead><tr>{hcells}</tr></thead>")

    body_rows: list[str] = []
    for cells in parsed_rows:
        while len(cells) < num_cols:
            cells.append("")
        tds = "".join(f'<td style="{cell_style}">{c}</td>' for c in cells)
        body_rows.append(f"<tr>{tds}</tr>")

    if body_rows:
        rows_html.append(f"<tbody>{''.join(body_rows)}</tbody>")

    return f'<table style="{style}">{"".join(rows_html)}</table>'


def md_tables_to_html(text: str) -> str:
    """텍스트 내 모든 마크다운 파이프 테이블을 HTML <table>로 변환합니다."""
    return _MD_TABLE_BLOCK_RE.sub(lambda m: _md_table_to_html(m.group(1)), text)

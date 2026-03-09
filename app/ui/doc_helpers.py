# app/ui/doc_helpers.py
# 문서 처리용 순수 Python 헬퍼 — Streamlit 의존 없음.
#
# components.py에서 분리. UI 렌더링 없이 데이터 변환·판별·정렬만 수행.

import re
from collections import defaultdict

from app.ui.text import _CONTEXT_PREFIX_RE, _QNA_SECTION_INJECT_RE, _ensure_paragraph_breaks


def _get_doc_para_num(doc: dict) -> str:
    """다양한 경로에서 문단 번호(paraNum)를 신뢰성 있게 추출합니다.

    시도 순서:
      1. doc['metadata']['paraNum'] — LangChain 실제 저장 위치
      2. doc['paraNum']             — 직접 저장된 경우
      3. chunk_id 마지막 세그먼트   — DB 직접 조회 문서 폴백
      4. 본문 첫 토큰 regex         — 최후 수단
    """
    meta = doc.get("metadata") or {}
    para = meta.get("paraNum", "") or ""
    if para.strip():
        return para.strip()
    para = doc.get("paraNum", "") or ""
    if para.strip():
        return para.strip()
    # chunk_id 폴백 — "1115-IE137" → "IE137"
    chunk_id = doc.get("chunk_id", "") or ""
    if chunk_id and "-" in chunk_id:
        candidate = chunk_id.rsplit("-", 1)[-1]
        if re.match(r"^[A-Za-z]{0,2}\d+[A-Za-z]?$", candidate):
            return candidate
    # 본문 첫 토큰에서 추출 — [문맥: ...] 접두어 제거 필수
    text = (
        doc.get("text") or doc.get("page_content") or doc.get("content", "")
    ).strip()
    text = _CONTEXT_PREFIX_RE.sub("", text).strip()
    m = re.match(r"^([A-Z]{0,2}\d+[A-Za-z]?)(?=\s|$)", text)
    return m.group(1) if m else ""


def _build_self_ids(para_id: str) -> set[str]:
    """paraNum 문자열로부터 자기참조 제외용 ID 집합을 생성합니다."""
    ids: set[str] = set()
    if not para_id:
        return ids
    bare = para_id.split("__")[-1].strip() if "__" in para_id else para_id.strip()
    ids.add(bare)
    ids.add(f"문단 {bare}")
    ids.add(f"문단{bare}")
    numeric = re.sub(r"^[A-Za-z]+", "", bare)
    if numeric:
        ids.add(numeric)
    return ids


def _ie_para_sort_key(doc: dict) -> tuple[str, int, str]:
    """IE 사례 문서의 문단 번호를 suffix 포함 튜플로 반환합니다 (오름차순 정렬 키)."""
    para_str = _get_doc_para_num(doc)
    m = re.match(r"([A-Za-z]*)(\d+)([A-Za-z]*)", para_str)
    if m:
        return (m.group(1), int(m.group(2)), m.group(3))
    return ("ZZ", 999999, "")


def _is_ie_doc(doc: dict) -> bool:
    """IE 적용사례 문서 여부 판별."""
    source = doc.get("source") or doc.get("category", "")
    if source == "적용사례IE":
        return True
    chunk_id = doc.get("chunk_id", "") or ""
    return bool(re.match(r"1115-IE", chunk_id))


def _normalize_case_group_title(cgt: str) -> str:
    """case_group_title 정규화 — "[사례 11: 제목]" → "사례 11: 제목"."""
    m = re.match(r"^\[(.+)\]$", cgt.strip())
    if m:
        return m.group(1)
    return cgt


def _apply_cluster_first_bonus(docs: list[dict]) -> list[dict]:
    """동일 prefix 클러스터 내 최저 번호 문단에 score 10% 보너스.

    K-IFRS 구조 특성: 도입·원칙 조항이 세부 처리 조항보다 앞 번호에 위치.
    클러스터 내 문단이 2개 이상일 때만 적용.
    """
    prefix_groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for doc in docs:
        cid = doc.get("chunk_id", "")
        m = re.match(r"^([\w]+-[A-Z]{0,2})(\d+)$", cid)
        if m:
            prefix_groups[m.group(1)].append((int(m.group(2)), cid))

    first_cids: set[str] = set()
    for items in prefix_groups.values():
        if len(items) >= 2:
            first_cids.add(min(items, key=lambda x: x[0])[1])

    return [
        {**doc, "score": doc.get("score", 0.0) * 1.1}
        if doc.get("chunk_id") in first_cids
        else doc
        for doc in docs
    ]


def _convert_journal_entries(text: str) -> str:
    """평문 분개를 마크다운 테이블로 변환합니다.

    입력 패턴 (QNA 신속처리질의):
      (차) 현금
      10,000
      (대) 수익
      9,700
    """
    def _parse_je_block(block: str) -> str:
        lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
        if len(lines) < 4:
            return block

        rows: list[tuple[str, str, str]] = []
        current_side = ""
        i = 0

        while i < len(lines):
            line = lines[i]
            m_side = re.match(r"^\((차|대)\)\s*(.*)", line)
            if m_side:
                current_side = f"({m_side.group(1)})"
                account = m_side.group(2).strip()
                if i + 1 < len(lines) and re.match(r"^[\d,]+\.?\d*$", lines[i + 1].strip()):
                    rows.append((current_side, account, lines[i + 1].strip()))
                    i += 2
                else:
                    rows.append((current_side, account, ""))
                    i += 1
                continue

            if re.match(r"^[\d,]+\.?\d*$", line):
                if rows and not rows[-1][2]:
                    rows[-1] = (rows[-1][0], rows[-1][1], line)
                i += 1
                continue

            if i + 1 < len(lines) and re.match(r"^[\d,]+\.?\d*$", lines[i + 1].strip()):
                rows.append(("", line, lines[i + 1].strip()))
                i += 2
                continue

            break

        if len(rows) < 2:
            return block

        last_side = ""
        filled_rows: list[tuple[str, str, str]] = []
        for side, account, amount in rows:
            if side:
                last_side = side
            filled_rows.append((side or last_side, account, amount))

        table = "\n\n| 구분 | 계정 | 금액 |\n|:----:|------|-----:|\n"
        for side, account, amount in filled_rows:
            table += f"| {side} | {account} | {amount} |\n"
        return table + "\n"

    lines = text.split("\n")
    result_parts: list[str] = []
    je_buffer: list[str] = []
    in_je = False

    for line in lines:
        stripped = line.strip()
        if re.match(r"^\(차\)", stripped):
            in_je = True
            je_buffer = [stripped]
            continue

        if in_je:
            if not stripped:
                continue
            if (re.match(r"^\(대\)", stripped)
                or re.match(r"^[\d,]+\.?\d*$", stripped)
                or (je_buffer and not re.match(r"^[\[(#*\-]", stripped)
                    and not stripped.startswith("##")
                    and not stripped.startswith("---")
                    and not stripped.startswith("**[")
                    and len(stripped) < 30)):
                je_buffer.append(stripped)
                continue
            else:
                table = _parse_je_block("\n".join(je_buffer))
                result_parts.append(table)
                je_buffer = []
                in_je = False
                result_parts.append(line)
                continue

        result_parts.append(line)

    if je_buffer:
        table = _parse_je_block("\n".join(je_buffer))
        result_parts.append(table)

    return "\n".join(result_parts)


def _format_pdr_content(content: str) -> str:
    """QNA/감리사례 Parent 전문의 가독성을 개선합니다."""
    # wall-of-text 분리
    text = _QNA_SECTION_INJECT_RE.sub("\n\n", content)

    # 섹션 헤더 변환: "## 질의 내용" → "\n---\n**질의 내용**"
    _SECTION_HEADERS = (
        "질의 내용", "질의요지", "질의에서 제시된 견해", "질의자의 의문사항",
        "배경 및 질의", "질의",
        "회신", "회답",
        "관련 회계기준", "관련회계기준", "관련기준",
        "참고자료", "참고 자료",
        "검토과정에서 논의된 내용", "검토과정",
        "판단근거", "배경", "본문",
        "레퍼런스",
        "결론", "감리 결과", "지적 내용", "위반사항",
    )
    for header in _SECTION_HEADERS:
        text = re.sub(
            r"^#{1,4}\s*" + re.escape(header) + r"\s*$",
            f"\n---\n**{header}**",
            text, flags=re.MULTILINE,
        )
        text = re.sub(
            r"^" + re.escape(header) + r"\s*$",
            f"\n---\n**{header}**",
            text, flags=re.MULTILINE,
        )

    # ~ 취소선 방지
    text = re.sub(r"(\d)~(\d)", r"\1～\2", text)
    text = re.sub(r"([A-Z])~([A-Z])", r"\1～\2", text)

    # 번호 항목 앞 줄바꿈
    text = re.sub(r"(?<=[.다])\s*(\d{1,2}[가-힣])", r"\n\n\1", text)

    # "부N" 부록 문단 마커 포맷팅
    text = re.sub(
        r"(?:^|\n)\s*(?:%\s*)?부(\d{1,2})\s*([가-힣A-Z])",
        r"\n\n**[부\1]** \2", text,
    )

    # 분개 → 마크다운 테이블
    text = _convert_journal_entries(text)

    # 레퍼런스 내 기준서 항목 리스트화
    text = re.sub(r"([0-9][A-Za-z]?)\s*(기업회계기준서)", r"\1\n\n- \2", text)
    text = re.sub(r"(관련\s*회계\s*기준)\s+(기업회계기준서)", r"\1\n\n- \2", text)

    # 단락 분리
    text = _ensure_paragraph_breaks(text)
    return text

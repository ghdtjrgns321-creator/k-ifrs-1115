# app/test/test_qna_reparse.py
# QNA 재파싱 테스트 — API에서 HTML을 가져와 개선된 파서로 변환 후 비교
#
# 테스트 대상: 5가지 유형의 QNA 문서
#   1. 정상 (## 섹션 있음)
#   2. wall-of-text (SSI 신속처리질의)
#   3. 문장 중간 줄바꿈 심함
#   4. 문단번호+한글 붙음
#   5. 긴 참고자료/관련회계기준 포함
#
# 사용법: PYTHONPATH=. uv run --env-file .env python app/test/test_qna_reparse.py

import json
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

# ── 기존 파서 (05-qna-crawl.py 그대로) ─────────────────────────────────


def clean_qna_html_to_md_OLD(html_text: str) -> str:
    if not html_text:
        return ""
    html_text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00a0]", " ", html_text)
    html_text = html_text.replace("&nbsp;", " ")
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup.find_all("sup"):
        inner = tag.get_text().strip()
        if inner.isdigit():
            tag.decompose()
        else:
            tag.string = f"^{inner}"
    for tag in soup.find_all("sub"):
        tag.string = f"_{tag.get_text()}"
    for tag in soup.find_all("br"):
        tag.replace_with("\n")
    for tbl in soup.find_all("table"):
        md_table = []
        rows = tbl.find_all("tr")
        for i, tr in enumerate(rows):
            cols = tr.find_all(["td", "th"])
            row_data = [
                col.get_text(separator=" ", strip=True).replace("\n", " ")
                for col in cols
            ]
            if not row_data:
                continue
            md_table.append("| " + " | ".join(row_data) + " |")
            if i == 0:
                md_table.append("|" + "|".join(["---"] * len(row_data)) + "|")
        new_tag = soup.new_tag("p")
        new_tag.string = "\n\n" + "\n".join(md_table) + "\n\n"
        tbl.replace_with(new_tag)
    for tag in soup.find_all("li"):
        tag.insert_before("\n- ")
        tag.unwrap()
    for tag in soup.find_all(["ul", "ol"]):
        tag.unwrap()
    for tag in soup.find_all(["p", "div"]):
        tag.insert_before("\n\n")
        tag.unwrap()
    for tag in soup.find_all(["a", "span", "strong", "em", "b", "i", "u"]):
        tag.unwrap()
    text = soup.get_text(separator="")
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_qna_sections_OLD(text: str) -> str:
    patterns = [
        (r"(?m)^[ \t]*(?:\d+\.\s*)?(?:배경\s*및\s*)?질의\s*(?:내용|사항)?\s*$", "## 질의 내용"),
        (
            r"(?m)^[ \t]*(?:\d+\.\s*)?(?:조사\s*결과[와과]?\s*)?(?:결론|결정|판단|회신|검토)\s*$",
            "## 회신",
        ),
        (r"(?m)^[ \t]*관련\s*회계\s*기준\s*$", "## 관련 회계기준"),
        (r"(?m)^[ \t]*참고\s*자료\s*$", "## 참고자료"),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text


# ── 개선된 파서 ──────────────────────────────────────────────────────────


def clean_qna_html_to_md_NEW(html_text: str) -> str:
    """HTML → 마크다운 구조적 변환 (v2 개선)

    개선 사항:
      1. <br>: 블록 요소 사이 <br>은 줄바꿈, 문장 중간 <br>은 공백
      2. <p>/<div> 블록 경계를 더 명확하게 처리
      3. 연속 공백 정리
    """
    if not html_text:
        return ""

    # 유니코드 노이즈 + &nbsp; 제거
    html_text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00a0]", " ", html_text)
    html_text = html_text.replace("&nbsp;", " ")

    soup = BeautifulSoup(html_text, "html.parser")

    # sup/sub 처리 (기존과 동일)
    for tag in soup.find_all("sup"):
        inner = tag.get_text().strip()
        if inner.isdigit():
            tag.decompose()
        else:
            tag.string = f"^{inner}"
    for tag in soup.find_all("sub"):
        tag.string = f"_{tag.get_text()}"

    # <table> → 마크다운 테이블 (기존과 동일)
    for tbl in soup.find_all("table"):
        md_table = []
        rows = tbl.find_all("tr")
        for i, tr in enumerate(rows):
            cols = tr.find_all(["td", "th"])
            row_data = [
                col.get_text(separator=" ", strip=True).replace("\n", " ")
                for col in cols
            ]
            if not row_data:
                continue
            md_table.append("| " + " | ".join(row_data) + " |")
            if i == 0:
                md_table.append("|" + "|".join(["---"] * len(row_data)) + "|")
        new_tag = soup.new_tag("p")
        new_tag.string = "\n\n" + "\n".join(md_table) + "\n\n"
        tbl.replace_with(new_tag)

    # <ul>/<ol> > <li> → 불릿
    for tag in soup.find_all("li"):
        tag.insert_before("\n- ")
        tag.unwrap()
    for tag in soup.find_all(["ul", "ol"]):
        tag.unwrap()

    # [개선] <br> 처리: 단독 <br>은 공백, 연속 <br><br>은 줄바꿈
    # 이유: 원본 HTML에서 <br>이 문장 중간에 줄 맞추기용으로 쓰임
    #       예: "재화나 용역의<br>지급조건을" → 공백으로 연결
    #       반면 <br><br>은 단락 구분 의도 → 줄바꿈 유지
    # 전략: 먼저 연속 <br> 탐지 → \n\n 마커로 변환, 나머지 단독 <br> → 공백
    for tag in soup.find_all("br"):
        # 다음 sibling이 <br>인지 확인 (연속 <br>)
        nxt = tag.next_sibling
        if nxt and getattr(nxt, "name", None) == "br":
            tag.replace_with("\n\n")
        else:
            # 이전 sibling이 이미 \n\n으로 변환된 경우 (연속 br의 2번째)
            prev = tag.previous_sibling
            if prev and isinstance(prev, str) and prev.endswith("\n\n"):
                tag.replace_with("")
            else:
                # 단독 <br> → 공백 (문장 중간 줄바꿈 방지)
                tag.replace_with(" ")

    # <p>, <div> → 단락 구분
    for tag in soup.find_all(["p", "div"]):
        tag.insert_before("\n\n")
        tag.unwrap()

    # 인라인 태그 제거
    for tag in soup.find_all(["a", "span", "strong", "em", "b", "i", "u"]):
        tag.unwrap()

    text = soup.get_text(separator="")
    text = re.sub(r"\r\n", "\n", text)

    # 연속 공백 정리 (줄바꿈 제외)
    text = re.sub(r"[^\S\n]+", " ", text)

    # 3개 이상 연속 줄바꿈 → 2개
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def normalize_qna_sections_NEW(text: str) -> str:
    """섹션 헤더를 ## 마크다운으로 통일 (v2 개선)

    개선 사항:
      1. 줄끝($) 제약 제거 → wall-of-text에서도 인라인 매칭
      2. "회신□", "관련회계기준" 등 공백 없는 패턴 추가
      3. 인라인 섹션 마커 앞에 줄바꿈 삽입 → ## 헤더로 변환 가능하게
    """
    # ── Phase 1: 인라인 섹션 마커를 줄바꿈으로 분리 ──
    # wall-of-text: "...적용하는지?회신□ 매출 계약..."
    # → "...적용하는지?\n\n회신\n□ 매출 계약..."
    # 문장 끝(?.!다함음됨) 바로 뒤에 섹션 키워드가 오면 줄바꿈 삽입
    _SECTION_KEYWORDS = (
        r"회\s*신|관련\s*회계\s*기준|관련회계기준|"
        r"질의\s*내용|질의\s*사항|질의요지|"
        r"참고\s*자료|참고자료|검토\s*과정|본문|판단\s*근거"
    )
    text = re.sub(
        rf"(?<=[.?!)\]됨함음다])\s*(?=(?:{_SECTION_KEYWORDS})(?:\s|[□ㅇo▶#\[:]))",
        "\n\n",
        text,
    )
    # "관련회계기준K-IFRS" 같이 마커 뒤에 바로 내용이 오는 경우도 분리
    text = re.sub(
        rf"(?<=[.?!)\]됨함음다])\s*(?=(?:{_SECTION_KEYWORDS})(?=[A-Z가-힣]))",
        "\n\n",
        text,
    )

    # ── Phase 2: 줄 시작 섹션 키워드를 ## 마크다운으로 변환 ──
    patterns = [
        # 질의 섹션
        (r"(?m)^[ \t]*(?:\d+\.\s*)?(?:배경\s*및\s*)?질의\s*(?:내용|사항|요지)?\s*$", "## 질의 내용"),
        # 회신 섹션 (회답 포함)
        (
            r"(?m)^[ \t]*(?:\d+\.\s*)?(?:조사\s*결과[와과]?\s*)?(?:결론|결정|판단|회신|회답|검토)\s*$",
            "## 회신",
        ),
        # 관련 회계기준 (공백 유무 모두)
        (r"(?m)^[ \t]*관련\s*회계\s*기준\s*$", "## 관련 회계기준"),
        (r"(?m)^[ \t]*관련회계기준\s*$", "## 관련 회계기준"),
        # 참고자료 (공백 유무 모두)
        (r"(?m)^[ \t]*참고\s*자료\s*$", "## 참고자료"),
        (r"(?m)^[ \t]*참고자료\s*$", "## 참고자료"),
        # 본문
        (r"(?m)^[ \t]*본문\s*$", "## 본문"),
        # 검토과정에서 논의된 내용
        (r"(?m)^[ \t]*검토\s*과정(?:에서\s*논의된\s*내용)?\s*$", "## 검토과정에서 논의된 내용"),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)

    return text


def post_clean(text: str) -> str:
    """최종 정리: 문단번호 분리, 불릿 마커 정리 등"""
    # 문단번호+한글 붙음 분리: "9다음 기준을" → "\n\n**문단 9** 다음 기준을"
    # 단, 연도(2020) 등 4자리 숫자는 제외
    text = re.sub(
        r"(?:^|\n)(\d{1,3})\s{2,}([가-힣])",
        r"\n\n**문단 \1** \2",
        text,
    )

    # ⑴⑵⑶ 등 원문자 괄호 번호 앞에 줄바꿈
    text = re.sub(r"(?<=[.다음함됨])\s*([⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽])", r"\n\n\1", text)

    # □, ㅇ, o 불릿 마커 앞에 줄바꿈 (이미 줄바꿈 있으면 스킵)
    text = re.sub(r"(?<!\n)\s*([□ㅇ▶])\s+", r"\n\n\1 ", text)

    # 3개 이상 연속 줄바꿈 → 2개
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 줄 시작/끝 불필요 공백 정리
    text = re.sub(r"^[ \t]+", "", text, flags=re.MULTILINE)

    return text.strip()


# ── 테스트 대상 문서 선정 ────────────────────────────────────────────────

# 다양한 유형을 커버하는 테스트 ID
TEST_DOC_IDS = {
    # 유형 1: wall-of-text (SSI 신속처리질의)
    "SSI-36917": "wall-of-text 기본 (구두계약)",
    "SSI-36993": "wall-of-text + 문단번호 붙음",
    "SSI-36949": "wall-of-text 긴 문서 (2168자)",
    "SSI-35567": "wall-of-text + 참고자료 긴 것",
    # 유형 2: 정상 (## 섹션 있음) — 줄바꿈 문제 확인
    "SSI-38672": "정상 + #### 노출 문제",
    "SSI-38698": "정상 + 짧은 문서",
    # 유형 3: 해석위원회/금감원 (복잡한 구조)
    "2020-I-KQA006": "해석위원회 + 긴 참고자료",
    "201803A": "해석위원회 + 검토과정",
    # 유형 4: 회계기준원 정규질의
    "202504C": "정규질의 + 최신",
}


def fetch_qna_html(doc_number: str) -> dict | None:
    """kifrs.com API에서 단일 QNA의 raw HTML을 가져옵니다."""
    # v2 API에서 검색
    for qna_type in [15, 11, 13, 25]:  # SSI, 정규, 해석위원회, 금감원
        url = f"https://www.kifrs.com/api/qnas/v2?types={qna_type}&page=1&rows=200"
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if res.status_code != 200:
                continue
            data = res.json()
            qna_list = data.get("facilityQnas") or data.get("qnas") or []
            for qna in qna_list:
                if qna.get("docNumber") == doc_number:
                    return qna
        except Exception:
            continue
        time.sleep(0.3)
    return None


def run_comparison(doc_number: str, desc: str, raw_html: str, title: str):
    """기존 파서 vs 개선 파서 비교 출력"""
    print(f"\n{'='*80}")
    print(f"[{doc_number}] {desc}")
    print(f"제목: {title}")
    print(f"HTML 길이: {len(raw_html)}자")
    print(f"{'='*80}")

    # 기존 파서
    old_md = clean_qna_html_to_md_OLD(raw_html)
    old_md = normalize_qna_sections_OLD(old_md)
    old_md = re.sub(r"^관련\s*회계\s*기준[^\n]*\n본문\n?", "", old_md).strip()

    # 개선 파서
    new_md = clean_qna_html_to_md_NEW(raw_html)
    new_md = normalize_qna_sections_NEW(new_md)
    new_md = re.sub(r"^관련\s*회계\s*기준[^\n]*\n본문\n?", "", new_md).strip()
    new_md = post_clean(new_md)

    # 품질 지표
    def quality_metrics(text):
        has_h2 = "## " in text
        mid_breaks = len(re.findall(r"[가-힣]\n[가-힣]", text))
        stuck_nums = len(re.findall(r"\d{1,3}\s{2,}[가-힣]", text))
        sections = len(re.findall(r"^## ", text, re.MULTILINE))
        return {
            "## 섹션 수": sections,
            "문장중간줄바꿈": mid_breaks,
            "문단번호붙음": stuck_nums,
        }

    old_m = quality_metrics(old_md)
    new_m = quality_metrics(new_md)

    print(f"\n--- 품질 지표 비교 ---")
    for k in old_m:
        old_v = old_m[k]
        new_v = new_m[k]
        arrow = "→"
        if k == "## 섹션 수":
            status = "✅" if new_v >= old_v else "❌"
        else:
            status = "✅" if new_v <= old_v else "❌"
        print(f"  {k}: {old_v} {arrow} {new_v} {status}")

    print(f"\n--- [기존] 처음 500자 ---")
    print(old_md[:500])

    print(f"\n--- [개선] 처음 500자 ---")
    print(new_md[:500])

    # 개선 파서 전문도 출력 (짧은 문서만)
    if len(new_md) < 1500:
        print(f"\n--- [개선] 전문 ---")
        print(new_md)

    return old_m, new_m


def main():
    print("=" * 80)
    print("QNA 재파싱 테스트 — API에서 HTML 가져와 기존 vs 개선 파서 비교")
    print("=" * 80)

    all_old = []
    all_new = []

    for doc_number, desc in TEST_DOC_IDS.items():
        print(f"\n📡 [{doc_number}] API에서 가져오는 중...")
        qna = fetch_qna_html(doc_number)
        if not qna:
            print(f"  ⚠️ 문서를 찾을 수 없습니다: {doc_number}")
            continue

        raw_html = qna.get("fullContent", "")
        title = qna.get("title", "제목 없음")

        if not raw_html:
            print(f"  ⚠️ fullContent가 비어있습니다")
            continue

        old_m, new_m = run_comparison(doc_number, desc, raw_html, title)
        all_old.append(old_m)
        all_new.append(new_m)

    # 종합 요약
    if all_old:
        print(f"\n{'='*80}")
        print("📊 종합 요약")
        print(f"{'='*80}")
        for k in all_old[0]:
            old_total = sum(m[k] for m in all_old)
            new_total = sum(m[k] for m in all_new)
            print(f"  {k}: {old_total} → {new_total}")


if __name__ == "__main__":
    main()

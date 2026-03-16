# app/preprocessing/05-qna-crawl.py
# kifrs.com API에서 K-IFRS 1115호 관련 질의회신을 크롤링하여 JSON으로 저장.
#
# v2 개선사항 (2026-03-08):
#   1. <br> 처리: 단독 <br>은 공백, 연속 <br><br>만 줄바꿈 (문장 중간 끊김 방지)
#   2. wall-of-text 섹션 분리: 인라인 "회신□", "관련회계기준" 등을 줄바꿈으로 분리
#   3. 문단번호 분리: "1회사는" → "1. 회사는", "9   다음" → "**문단 9** 다음"
#   4. 섹션 헤더 패턴 확장: 회답, 질의요지, 본문, 검토과정 등 추가
#
# 사용법: PYTHONPATH=. uv run --env-file .env python app/preprocessing/05-qna-crawl.py

import json
import os
import re
import time

import requests
from bs4 import BeautifulSoup


# ── HTML → 마크다운 변환 ─────────────────────────────────────────────────


def clean_qna_html_to_md(html_text: str) -> str:
    """QNA fullContent HTML을 마크다운으로 구조적 변환.

    <br> 처리 전략:
      - 연속 <br><br> → 단락 구분 줄바꿈 (\n\n)
      - 단독 <br> → 공백 (문장 중간 줄바꿈 방지)
    SSI 신속처리질의는 HTML 태그 없이 plain text로 오므로 그대로 통과됩니다.
    """
    if not html_text:
        return ""

    # 유니코드 노이즈 제거
    html_text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00a0]", " ", html_text)
    html_text = html_text.replace("&nbsp;", " ")

    soup = BeautifulSoup(html_text, "html.parser")

    # sup: 순수 숫자는 각주 → 제거, 수식용(x^2)은 보존
    for tag in soup.find_all("sup"):
        inner = tag.get_text().strip()
        if inner.isdigit():
            tag.decompose()
        else:
            tag.string = f"^{inner}"
    for tag in soup.find_all("sub"):
        tag.string = f"_{tag.get_text()}"

    # <table> → 마크다운 테이블
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

    # <br> 처리: 연속 <br><br>은 줄바꿈, 단독 <br>은 공백
    for tag in soup.find_all("br"):
        nxt = tag.next_sibling
        if nxt and getattr(nxt, "name", None) == "br":
            tag.replace_with("\n\n")
        else:
            prev = tag.previous_sibling
            if prev and isinstance(prev, str) and prev.endswith("\n\n"):
                tag.replace_with("")
            else:
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
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── 섹션 헤더 정규화 ─────────────────────────────────────────────────────

# wall-of-text 분리용 섹션 키워드
_SECTION_KEYWORDS = (
    r"회\s*신|관련\s*회계\s*기준|관련회계기준|"
    r"질의\s*내용|질의\s*사항|질의요지|"
    r"참고\s*자료|참고자료|검토\s*과정|본문|판단\s*근거"
)


def normalize_qna_sections(text: str) -> str:
    """다양한 포맷의 QNA 섹션 헤더를 ## 마크다운으로 통일.

    Phase 1: wall-of-text에서 인라인 섹션 마커를 줄바꿈으로 분리
    Phase 2: 줄 시작 섹션 키워드를 ## 마크다운으로 변환
    """
    # ── Phase 1: 인라인 섹션 마커 분리 ──
    # "...적용하는지?회신□" → "...적용하는지?\n\n회신\n\n□"
    text = re.sub(
        rf"(?<=[.?!)\]됨함음다])\s*(?=(?:{_SECTION_KEYWORDS})(?:\s|[□ㅇo▶#\[:]|$))",
        "\n\n",
        text,
    )
    text = re.sub(
        rf"(?<=[.?!)\]됨함음다])\s*(?=(?:{_SECTION_KEYWORDS})(?=[A-Z가-힣]))",
        "\n\n",
        text,
    )

    # "회신□" → "회신\n\n□" (섹션 키워드와 불릿 마커 분리)
    text = re.sub(r"(회\s*신)\s*([□ㅇo▶])", r"\1\n\n\2", text)
    # "관련회계기준K-IFRS" → "관련회계기준\n\nK-IFRS"
    text = re.sub(
        r"(관련\s*회계\s*기준)\s*(K-IFRS|기업회계기준)",
        r"\1\n\n\2",
        text,
    )

    # ── Phase 2: 줄 시작 키워드 → ## 마크다운 ──
    patterns = [
        (r"(?m)^[ \t]*(?:\d+\.\s*)?(?:배경\s*및\s*)?질의\s*(?:내용|사항|요지)?\s*$", "## 질의 내용"),
        (
            r"(?m)^[ \t]*(?:\d+\.\s*)?(?:조사\s*결과[와과]?\s*)?(?:결론|결정|판단|회신|회답|검토)\s*$",
            "## 회신",
        ),
        (r"(?m)^[ \t]*관련\s*회계\s*기준\s*$", "## 관련 회계기준"),
        (r"(?m)^[ \t]*관련회계기준\s*$", "## 관련 회계기준"),
        (r"(?m)^[ \t]*참고\s*자료\s*$", "## 참고자료"),
        (r"(?m)^[ \t]*참고자료\s*$", "## 참고자료"),
        (r"(?m)^[ \t]*본문\s*$", "## 본문"),
        (r"(?m)^[ \t]*검토\s*과정(?:에서\s*논의된\s*내용)?\s*$", "## 검토과정에서 논의된 내용"),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)

    return text


# ── 최종 텍스트 정리 ─────────────────────────────────────────────────────


def post_clean(text: str) -> str:
    """문단번호 분리, 불릿 정리, 줄바꿈 압축."""
    # "9     다음 기준을" → "**문단 9** 다음 기준을"
    text = re.sub(
        r"(?:^|\n)(\d{1,3})\s{2,}([가-힣])",
        r"\n\n**문단 \1** \2",
        text,
    )
    # "1회사는" → "1. 회사는" (줄 시작 숫자+한글 붙은 것 분리)
    text = re.sub(r"^(\d{1,2})([가-힣])", r"\1. \2", text, flags=re.MULTILINE)
    # ⑴⑵⑶ 원문자 번호 앞 줄바꿈
    text = re.sub(r"(?<=[.다음함됨])\s*([⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽])", r"\n\n\1", text)
    # □ ㅇ ▶ 불릿 마커 앞 줄바꿈
    text = re.sub(r"(?<!\n)\s*([□ㅇ▶])\s+", r"\n\n\1 ", text)
    # 줄바꿈 압축 + 줄 앞 공백 제거
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"^[ \t]+", "", text, flags=re.MULTILINE)
    return text.strip()


# ── 크롤링 메인 ──────────────────────────────────────────────────────────


def fetch_targeted_qnas():
    OUTPUT_FILE = "data/web/kifrs-1115-qna-chunks.json"
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    qna_chunks = []
    total_found = 0

    TARGET_CONFIGS = [
        {"type": 13, "name": "IFRS 해석위원회", "weight": 1.15},
        {"type": 25, "name": "금융감독원", "weight": 1.15},
        {"type": 11, "name": "회계기준원 정규질의", "weight": 1.10},
        {"type": 15, "name": "신속처리질의", "weight": 1.05},
    ]

    print("가중치가 적용된 K-IFRS 타겟 크롤링을 시작합니다\n")

    for config in TARGET_CONFIGS:
        category_type = config["type"]
        category_name = config["name"]
        weight = config["weight"]

        print(f"=============================================")
        print(f"[{category_name}] 게시판 스캔 중... (가중치: {weight})")

        page = 1

        while True:
            url = f"https://www.kifrs.com/api/qnas/v2?types={category_type}&page={page}&rows=50"

            try:
                res = requests.get(
                    url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10
                )
                if res.status_code != 200:
                    break

                data = res.json()
                qna_list = data.get("facilityQnas") or data.get("qnas") or []

                if not qna_list:
                    print(f"{category_name} 데이터 조회가 완료되었습니다.")
                    break

                for qna in qna_list:
                    doc_id = qna.get("docNumber", "Unknown")
                    title = qna.get("title", "제목 없음")
                    full_content = qna.get("fullContent", "")
                    rel_stds = str(qna.get("relStds", ""))
                    date_str = str(qna.get("date", "202X"))[:4]
                    qna_id = f"QNA-{doc_id}"

                    if "1115" in rel_stds:
                        total_found += 1

                        # 3단계 파이프라인: HTML변환 → 섹션정규화 → 텍스트정리
                        clean_content = clean_qna_html_to_md(full_content)
                        clean_content = normalize_qna_sections(clean_content)
                        clean_content = post_clean(clean_content)

                        # 서두 노이즈 제거: "관련 회계기준...\n본문\n"
                        # → 일부 SSI 문서에서 "## 관련 회계기준\n...\n## 본문"으로 변환됨
                        clean_content = re.sub(
                            r"^(?:## )?관련\s*회계\s*기준[^\n]*\n(?:## )?본문\n?",
                            "",
                            clean_content,
                        ).strip()

                        # 제목 prefix
                        clean_content = (
                            f"**[{qna_id}]** {title} ({date_str})\n\n{clean_content}"
                        )

                        hierarchy_path = f"질의회신 > {category_name} > K-IFRS 제1115호 > {title} ({date_str})"

                        chunk = {
                            "id": qna_id,
                            "content": clean_content,
                            "metadata": {
                                "stdNum": "1115",
                                "paraNum": doc_id,
                                "title": title,
                                "category": f"질의회신({category_name})",
                                "weight_score": weight,
                                "hierarchy": hierarchy_path,
                                "sectionLevel": 1,
                            },
                        }
                        qna_chunks.append(chunk)
                        print(f"  [HIT!] {doc_id} ({title})")

                page += 1
                time.sleep(0.3)

            except Exception as e:
                print(f"[ERROR] 통신 에러 발생: {e}")
                break

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(qna_chunks, f, ensure_ascii=False, indent=2)

    print(f"\n=============================================")
    print(f"크롤링 및 가중치 매핑 완료")
    print(f"총 {total_found}개 K-IFRS 1115 질의회신 데이터 준비 완료.")
    print(f"결과물 저장: {OUTPUT_FILE}")
    print(f"=============================================")


if __name__ == "__main__":
    fetch_targeted_qnas()

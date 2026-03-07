import requests
import json
import os
import re
import time
from bs4 import BeautifulSoup


def clean_qna_html_to_md(html_text: str) -> str:
    """
    QNA fullContent HTML을 마크다운으로 구조적 변환.
    기존 단순 태그 제거(re.sub)를 BeautifulSoup 기반으로 교체.
    → <br> 줄바꿈, <li> 목록, <table> 마크다운 테이블 보존
    """
    if not html_text:
        return ""

    # 유니코드 노이즈 제거 (기존 06-qna-embed.py에 있던 것을 여기서 처리)
    # → 임베딩 시점이 아닌 크롤링 시점에 정제해야 일관성 유지
    html_text = re.sub(r'[\u200b\u200c\u200d\ufeff\u00a0]', ' ', html_text)
    html_text = html_text.replace('&nbsp;', ' ')

    soup = BeautifulSoup(html_text, "html.parser")

    # <sup>/<sub>를 unwrap 전에 텍스트로 변환 (위/아래 첨자 보존)
    for tag in soup.find_all("sup"):
        tag.string = f"^{tag.get_text()}"
    for tag in soup.find_all("sub"):
        tag.string = f"_{tag.get_text()}"

    # <br> → \n (기존에는 완전히 삭제되던 줄바꿈을 보존)
    for tag in soup.find_all("br"):
        tag.replace_with("\n")

    # <table> → 마크다운 테이블
    for tbl in soup.find_all("table"):
        md_table = []
        rows = tbl.find_all("tr")
        for i, tr in enumerate(rows):
            cols = tr.find_all(["td", "th"])
            row_data = [col.get_text(separator=" ", strip=True).replace("\n", " ") for col in cols]
            if not row_data:
                continue
            md_table.append("| " + " | ".join(row_data) + " |")
            if i == 0:
                md_table.append("|" + "|".join(["---"] * len(row_data)) + "|")
        new_tag = soup.new_tag("p")
        new_tag.string = "\n\n" + "\n".join(md_table) + "\n\n"
        tbl.replace_with(new_tag)

    # <ul>/<ol> > <li> → "- " 불릿 (목록 구조 보존)
    for tag in soup.find_all("li"):
        tag.insert_before("\n- ")
        tag.unwrap()
    for tag in soup.find_all(["ul", "ol"]):
        tag.unwrap()

    # <p>, <div> → 단락 구분 \n\n
    for tag in soup.find_all(["p", "div"]):
        tag.insert_before("\n\n")
        tag.unwrap()

    # 나머지 인라인 태그 제거 (의미 태그는 이미 텍스트로 변환됨)
    for tag in soup.find_all(["a", "span", "strong", "em", "b", "i", "u"]):
        tag.unwrap()

    text = soup.get_text(separator="")
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def normalize_qna_sections(text: str) -> str:
    """
    다양한 포맷의 QNA 섹션 헤더를 ## 마크다운으로 통일.
    → 06-qna-embed.py의 Q/A 분할 regex가 단순한 ## 기반으로 동작하게 됨
    """
    patterns = [
        # 질의 섹션: "1. 질의 내용", "질의사항", "배경 및 질의" 등
        (r'(?m)^[ \t]*(?:\d+\.\s*)?(?:배경\s*및\s*)?질의\s*(?:내용|사항)?\s*$', '## 질의 내용'),
        # 회신 섹션: "2. 결론", "조사 결과와 결론", "회신" 등
        (r'(?m)^[ \t]*(?:\d+\.\s*)?(?:조사\s*결과[와과]?\s*)?(?:결론|결정|판단|회신|검토)\s*$', '## 회신'),
        # 관련 회계기준 섹션
        (r'(?m)^[ \t]*관련\s*회계\s*기준\s*$', '## 관련 회계기준'),
        # 참고자료 섹션
        (r'(?m)^[ \t]*참고\s*자료\s*$', '## 참고자료'),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text


def fetch_targeted_qnas():
    OUTPUT_FILE = "data/web/kifrs-1115-qna-chunks.json"
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    qna_chunks = []
    total_found = 0

    # API 타겟과 실무적 가중치 매핑
    TARGET_CONFIGS = [
        {"type": 13, "name": "IFRS 해석위원회",   "weight": 1.18},  # 1순위 상단 (1.18)
        {"type": 25, "name": "금융감독원",          "weight": 1.18},  # 1순위 상단 (1.18)
        {"type": 11, "name": "회계기준원 정규질의", "weight": 1.15},  # 1순위 표준 (1.15)
        {"type": 15, "name": "신속처리질의",        "weight": 1.05},  # 3순위 강등 (1.05)
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
                res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                if res.status_code != 200:
                    break

                data = res.json()
                # v2 API는 리스트가 'facilityQnas'에 주로 담김
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

                    # 정밀 타겟팅: '1115' 문자열 포함 여부 확인
                    if "1115" in rel_stds:
                        total_found += 1

                        # HTML → 마크다운 구조적 변환 (기존 단순 태그 제거 대체)
                        clean_content = clean_qna_html_to_md(full_content)

                        # 섹션 헤더를 ## 마크다운으로 통일 (06-embed 분할 로직 단순화)
                        clean_content = normalize_qna_sections(clean_content)

                        # 서두 노이즈 제거: "관련 회계기준 K-IFRS ...\n본문\n" 2줄
                        # → hierarchy에 이미 포함되므로 content에서는 불필요한 반복
                        clean_content = re.sub(
                            r'^관련\s*회계\s*기준[^\n]*\n본문\n?', '', clean_content
                        ).strip()

                        # 제목 prefix: 검색 결과에서 출처가 즉시 식별되도록
                        clean_content = f"**[{qna_id}]** {title} ({date_str})\n\n{clean_content}"

                        # 출처가 명확히 보이는 계층 구조
                        hierarchy_path = f"질의회신 > {category_name} > K-IFRS 제1115호 > {title} ({date_str})"

                        chunk = {
                            "id": qna_id,
                            "content": clean_content,
                            "metadata": {
                                "stdNum": "1115",
                                "paraNum": doc_id,
                                "title": title,          # 제목 필드 추가 (검색 결과 표시용)
                                "category": f"질의회신({category_name})",
                                "weight_score": weight,
                                "hierarchy": hierarchy_path,
                                "sectionLevel": 1,
                            }
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

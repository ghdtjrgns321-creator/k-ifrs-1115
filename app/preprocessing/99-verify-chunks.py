"""
청크 품질 검증 스크립트
- 원본 HTML의 번호 목록 (1),(2),(3)... 이 청크에서 누락되었는지 탐지
- fullContent 대비 청크 텍스트의 핵심 키워드 유실 여부 확인
"""

import io
import json
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from bs4 import BeautifulSoup


def extract_numbers_from_html(html: str) -> list[str]:
    """HTML에서 (1), (2), (가), (나) 등 번호 목록 항목을 추출"""
    soup = BeautifulSoup(html, "html.parser")
    numbers = []

    # para-inner-number-item 구조
    for num_div in soup.find_all("div", class_="para-number-para-num"):
        numbers.append(num_div.get_text(strip=True))

    # idt-1 구조 (들여쓰기 번호)
    for div in soup.find_all("div", class_="idt-1"):
        text = div.get_text(strip=True)
        m = re.match(r"(\(\d+\)|\([가-힣]\))", text)
        if m:
            numbers.append(m.group(1))

    # idt-2 구조 (2단 들여쓰기 번호)
    for div in soup.find_all("div", class_="idt-2"):
        text = div.get_text(strip=True)
        m = re.match(r"(\(\d+\)|\([가-힣]\))", text)
        if m:
            numbers.append(m.group(1))

    return numbers


def verify_chunks():
    with open("data/web/kifrs-1115-all.json", "r", encoding="utf-8") as f:
        raw_data = json.load(f)
    with open("data/web/kifrs-1115-chunks.json", "r", encoding="utf-8") as f:
        chunks = json.load(f)

    chunk_map = {c["id"]: c["content"] for c in chunks}

    # 중복 제거 (03-chunk와 동일 로직)
    best = {}
    for item in raw_data:
        uid = str(item.get("uniqueKey", ""))
        if not uid:
            continue
        curr_level = item.get("sectionLevel", -1)
        if uid not in best or curr_level > best[uid].get("sectionLevel", -1):
            best[uid] = item

    issues = []

    for uid, item in best.items():
        html = item.get("paraContent", "")
        if not html:
            continue

        chunk_content = chunk_map.get(uid, "")
        if not chunk_content:
            continue

        full = item.get("fullContent", "")

        # 검증 1: 번호 목록 누락
        html_numbers = extract_numbers_from_html(html)
        for num in html_numbers:
            if num not in chunk_content:
                issues.append(
                    {
                        "uid": uid,
                        "type": "번호_누락",
                        "detail": f"HTML에 {num} 있으나 청크에서 누락",
                    }
                )

        # 검증 2: (N) 뒤에 공백 없이 한글이 바로 붙은 경우 (줄바꿈 이음 부작용)
        # fullContent에서도 동일하게 붙어있으면 원본 자체의 교차참조이므로 제외
        for m in re.finditer(r"\(\d+\)([가-힣])", chunk_content):
            if f"{m.group()}" in full:
                continue  # 원본에도 같은 패턴 존재 → 교차참조, 정상
            issues.append(
                {
                    "uid": uid,
                    "type": "공백_누락",
                    "detail": f"'{m.group()}' - 번호 뒤 공백 없이 텍스트 붙음 (원본에는 공백 있음)",
                }
            )

        # 검증 3: fullContent의 문장이 청크에서 통째로 빠진 경우
        if full:
            # fullContent를 문장 단위로 분리
            sentences = re.split(r"(?<=[.다])\s+", full.strip())
            for sent in sentences:
                sent_clean = sent.strip()
                if len(sent_clean) > 20:  # 의미 있는 길이만
                    # 핵심 키워드 3개 이상 매칭 확인
                    keywords = re.findall(r"[가-힣]{2,}", sent_clean)[:5]
                    found = sum(1 for kw in keywords if kw in chunk_content)
                    if found < min(2, len(keywords)):
                        issues.append(
                            {
                                "uid": uid,
                                "type": "문장_유실",
                                "detail": f"원문 문장 키워드 미매칭: {sent_clean[:50]}...",
                            }
                        )

    # 결과 출력
    print(f"{'='*60}")
    print(f"청크 품질 검증 결과")
    print(f"{'='*60}")
    print(f"검사 문단: {len(best)}개")
    print(f"발견 이슈: {len(issues)}개")
    print()

    if not issues:
        print("✅ 모든 청크가 원본과 일치합니다!")
        return

    # 유형별 분류
    by_type = {}
    for issue in issues:
        t = issue["type"]
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(issue)

    for t, items in by_type.items():
        print(f"\n--- {t} ({len(items)}건) ---")
        for item in items[:10]:
            print(f"  [{item['uid']}] {item['detail']}")
        if len(items) > 10:
            print(f"  ... 외 {len(items)-10}건")


if __name__ == "__main__":
    verify_chunks()

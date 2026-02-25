"""
본문.md → 본문.json 재생성 스크립트

[왜 이 스크립트가 필요한가]
Upstage API로 자동 파싱된 기존 본문.json에는 오류가 있음:
  - 일반 paragraph가 list로 잘못 분류 (PDF 줄바꿈 기호 오인식)
  - 문단 번호와 내용이 별도 요소로 분리
  - 페이지 경계에서 문단이 두 개로 쪼개짐
  - "- \n" 같은 빈 노이즈 요소 존재

본문.md는 위 오류가 수동 편집으로 정리된 정답 소스이므로,
이를 파싱하여 올바른 JSON을 재생성한다.
"""
import json
import os
import re
import sys

# Windows에서 한글/이모지 출력을 위해 stdout을 UTF-8로 강제 설정
sys.stdout.reconfigure(encoding="utf-8")

# ── 경로 설정 ──
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MD_PATH = os.path.join(BASE, "data", "sections", "본문.md")
OLD_JSON_PATH = os.path.join(BASE, "data", "sections", "본문.json")
OUT_JSON_PATH = os.path.join(BASE, "data", "sections", "본문.json")


# ────────────────────────────────────────────────
# Step 1: 기존 JSON에서 heading1 → page 매핑 추출
# [왜] heading 텍스트가 동일한 경우 기존 페이지 번호를 재활용하기 위함
# ────────────────────────────────────────────────
with open(OLD_JSON_PATH, "r", encoding="utf-8") as f:
    old_data = json.load(f)

# content 그대로 키로 사용 (앞뒤 공백만 제거)
heading_page_map: dict[str, int] = {}
for elem in old_data:
    if elem["metadata"]["category"] == "heading1":
        key = elem["content"].strip()
        page = elem["metadata"]["page"]
        # 오탐된 heading은 걸러냄: 숫자 단독, 또는 문장 조각처럼 보이는 것
        # 기준: # 뒤 실제 제목이 2글자 이상이고 마침표로 끝나지 않음
        title_part = re.sub(r"^#+\s*", "", key)
        if len(title_part) >= 2 and not title_part[-1] in ".。":
            heading_page_map[key] = page

# ────────────────────────────────────────────────
# Step 2: fallback 페이지 매핑 (기존 JSON에 없는 heading 보완)
# [왜] 기존 JSON의 오분류로 인해 일부 heading이 누락되어 있음
#       PDF 확인 기반으로 주요 섹션 시작 페이지를 하드코딩
# ────────────────────────────────────────────────
FALLBACK_PAGE: dict[str, int] = {
    "# 적용범위": 9,
    "# 인식": 12,
    "# 계약을 식별함": 12,
    "# 기간에 걸쳐 이행하는 수행의무": 20,
    "# 변동대가": 26,
    "# 수익의 구분": 43,
    "# 수행의무를 이행하는 시기를 판단함": 46,
    "# 거래가격과 수행의무에 배분하는 금액을 산정함": 46,
}

def get_page_for_heading(heading_content: str, current_page: int) -> int:
    """heading1 content에 대응하는 페이지를 반환한다."""
    key = heading_content.strip()
    if key in heading_page_map:
        return heading_page_map[key]
    if key in FALLBACK_PAGE:
        return FALLBACK_PAGE[key]
    # 매핑 없으면 현재까지 추적된 페이지 유지
    return current_page


# ────────────────────────────────────────────────
# Step 3: MD 파일 읽기 및 블록 분리
# [왜] 빈 줄(1개 이상)을 블록 구분자로 사용 — 표준 Markdown 관례
# ────────────────────────────────────────────────
with open(MD_PATH, "r", encoding="utf-8") as f:
    md_text = f.read()

# 2개 이상 연속 빈 줄로 블록 분리
raw_blocks = re.split(r"\n{2,}", md_text.strip())


def classify_block(lines: list[str]) -> str | None:
    """
    블록의 category를 판별한다.

    판별 순서 (우선순위 순):
      1. heading1: 첫 번째 비어있지 않은 줄이 # 로 시작
      2. table: | 가 포함된 줄이 존재
      3. list: - 로 시작하는 내용 있는 줄이 존재
      4. paragraph: 위에 해당하지 않는 나머지
    """
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return None  # 빈 블록은 무시

    # heading1 판별
    if non_empty[0].startswith("#"):
        return "heading1"

    # table 판별
    if any(line.strip().startswith("|") for line in non_empty):
        return "table"

    # list 판별: "- " 뒤에 실제 내용이 있는 줄이 1개 이상
    has_real_list_item = any(
        line.strip().startswith("- ") and line.strip()[2:].strip()
        for line in non_empty
    )
    if has_real_list_item:
        return "list"

    return "paragraph"


def clean_list_block(lines: list[str]) -> list[str]:
    """
    list 블록에서 빈 항목 (예: "- ", "- \n") 을 제거한다.
    [왜] 기존 JSON에 "- \n" 같은 노이즈 요소가 있었음
    """
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            item_content = stripped[2:].strip()
            if not item_content:
                continue  # 빈 list 항목 제거
        cleaned.append(line)
    return cleaned


# ────────────────────────────────────────────────
# Step 4: 블록 → JSON 요소 변환
# ────────────────────────────────────────────────
elements: list[dict] = []
current_page: int = 1  # 현재까지 추적된 페이지

for raw_block in raw_blocks:
    lines = raw_block.split("\n")

    category = classify_block(lines)
    if category is None:
        continue  # 빈 블록 스킵

    # list 블록의 빈 항목 제거
    if category == "list":
        lines = clean_list_block(lines)
        # 정리 후 실제 list 항목이 없으면 스킵
        has_item = any(
            l.strip().startswith("- ") and l.strip()[2:].strip()
            for l in lines
        )
        if not has_item:
            continue

    content = "\n".join(lines).strip()
    if not content:
        continue

    # heading1이면 페이지 번호 업데이트
    if category == "heading1":
        current_page = get_page_for_heading(content, current_page)

    elements.append({
        "content": content,
        "metadata": {
            "category": category,
            "page": current_page,
        }
    })


# ────────────────────────────────────────────────
# Step 5: 결과 저장
# ────────────────────────────────────────────────
with open(OUT_JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(elements, f, ensure_ascii=False, indent=2)


# ────────────────────────────────────────────────
# Step 6: 검증 출력
# ────────────────────────────────────────────────
from collections import Counter

cats = Counter(e["metadata"]["category"] for e in elements)
print(f"✅ 본문.json 재생성 완료")
print(f"   총 요소 수: {len(elements)}개  (기존 JSON: {len(old_data)}개)")
print()
print("── category 분포 ──")
for cat, count in sorted(cats.items()):
    print(f"   {cat:12s}: {count:3d}개")

print()
print("── heading1 목록 (페이지 번호 확인) ──")
for e in elements:
    if e["metadata"]["category"] == "heading1":
        title = e["content"][:50].replace("\n", " ")
        print(f"   p{e['metadata']['page']:3d} | {title}")

print()
print("── 샘플 검증 ──")
# 문단 3, 4가 paragraph인지 확인
para_samples = [e for e in elements if e["metadata"]["category"] == "paragraph"
                and e["content"].startswith("3 ")]
if para_samples:
    print(f"   문단 3: category=paragraph ✅  ({para_samples[0]['content'][:40]}...)")
else:
    print("   문단 3: ⚠️  paragraph 샘플 없음")

# 빈 list 항목이 없는지 확인
empty_list = [e for e in elements
              if e["metadata"]["category"] == "list"
              and not any(l.strip()[2:].strip() for l in e["content"].split("\n")
                          if l.strip().startswith("- "))]
print(f"   빈 list 요소: {len(empty_list)}개  {'✅' if not empty_list else '⚠️'}")

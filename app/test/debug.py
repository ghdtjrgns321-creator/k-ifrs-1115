# 디버그: 섹션 경계 후보 찾기
import json

with open("data/processed/parsed-elements.json", "r", encoding="utf-8") as f:
    parsed = json.load(f)

# 섹션 키워드가 포함된 요소 모두 출력
keywords = ["부록", "적용사례", "실무적용지침", "결론도출근거", "용어의 정의",
            "시행일", "경과 규정", "적용지침", "목 적", "적용범위"]

print("=== 섹션 경계 후보 ===\n")
for i, elem in enumerate(parsed):
    content = elem["content"].strip()
    cat = elem["metadata"].get("category", "")
    if any(kw in content for kw in keywords) and len(content) < 100:
        print(f"[{i:4d}] ({cat:10s}) {content[:80]}")
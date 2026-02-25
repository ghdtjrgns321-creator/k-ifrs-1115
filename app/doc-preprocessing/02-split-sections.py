# Step 1 결과(parsed-elements.json)를 6개 섹션으로 분리
import json
import os

INPUT_JSON = "data/processed/parsed-elements.json"
OUTPUT_DIR = "data/sections"
os.makedirs(OUTPUT_DIR, exist_ok=True)

with open(INPUT_JSON, "r", encoding="utf-8") as f:
    parsed = json.load(f)

SECTION_BOUNDARIES = [
    # ── 부록 A: "부록 A." (마침표 필수) — "계약의 정의(부록 A)" 오탐 방지 ──
    ("부록A_용어",
     lambda cat, txt: cat == "heading1" and "부록 A." in txt),

    # ── 부록 B ──
    ("부록B_적용지침",
     lambda cat, txt: cat == "heading1" and txt.strip().startswith("# 부록 B")),

    # ── 부록 C: "시행일" 제외 조건 삭제 (실제 텍스트에 포함됨) ──
    ("부록C_경과규정",
     lambda cat, txt: cat == "heading1" and txt.strip().startswith("# 부록 C")),

    # ── 적용사례: ※ 로 시작하는 안내 문구 제외 ──
    ("적용사례",
     lambda cat, txt: cat == "paragraph"
         and "적용사례" in txt
         and "실무적용지침" in txt
         and not txt.startswith("[")
         and not txt.startswith("※")),

    ("적용사례",
     lambda cat, txt: cat == "heading1" and "적용사례·실무적용지침 목차" in txt),

    # ── 결론도출근거: 정확 일치 또는 목차 제목 ──
    ("결론도출근거",
     lambda cat, txt: cat == "paragraph" and txt.strip() == "결론도출근거"),

    ("결론도출근거",
     lambda cat, txt: cat == "heading1" and "결론도출근거 목차" in txt),

    ("결론도출근거",
     lambda cat, txt: cat == "heading1"
         and "K-IFRS 제1115호" in txt
         and "결론도출근거" in txt),
]

# ── 섹션 분리 ──
current_section = "본문"
section_elements = {}
transitions = []

for i, elem in enumerate(parsed):
    content = elem["content"].strip()
    cat = elem["metadata"].get("category", "")

    if cat in ("footer", "header"):
        continue

    for sec_name, match_fn in SECTION_BOUNDARIES:
        if match_fn(cat, content):
            if current_section != sec_name:
                transitions.append((i, current_section, sec_name, content[:60]))
                current_section = sec_name
            break

    section_elements.setdefault(current_section, []).append(elem)

# ── 저장 ──
for section_name, elements in section_elements.items():
    json_path = os.path.join(OUTPUT_DIR, f"{section_name}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(elements, f, ensure_ascii=False, indent=2)

    md_path = os.path.join(OUTPUT_DIR, f"{section_name}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        for elem in elements:
            f.write(elem["content"] + "\n\n")

# ── 검증 ──
print("✅ 섹션 분리 완료\n")
print("── 섹션 전환 기록 ──")
for idx, from_sec, to_sec, text in transitions:
    print(f"  [{idx:4d}] {from_sec} → {to_sec}")
    print(f"         \"{text}\"")
print()

expected = ["본문", "부록A_용어", "부록B_적용지침", "부록C_경과규정", "적용사례", "결론도출근거"]
for section_name in expected:
    elements = section_elements.get(section_name, [])
    tables = sum(1 for e in elements if e["metadata"].get("category") == "table")
    print(f"   {section_name}: {len(elements)}개 요소 (표 {tables}개)")

core = len(section_elements.get("본문", [])) + len(section_elements.get("부록B_적용지침", []))
total = sum(len(v) for v in section_elements.values())
print(f"\n   → 본문 + 부록B = {core}개 ({core/total*100:.0f}%) ← MVP 핵심")
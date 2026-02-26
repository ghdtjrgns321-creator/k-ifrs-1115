import requests
import json
import time
import os

INDEX_URL = "https://www.kifrs.com/api/standard-indexes/1115"
PARA_URL = "https://kifrs.com/api/paragraphs/1115"

OUTPUT_DIR = "data/raw"
os.makedirs(OUTPUT_DIR, exist_ok=True)

headers = {"User-Agent": "Mozilla/5.0"}

print("1단계: 섹션 목록 조회...")
res = requests.get(INDEX_URL, headers=headers)
sections = res.json().get("standardIndexes", [])
print(f"  ✅ {len(sections)}개 섹션 발견\n")

print("2단계: 본문(Paragraphs) 데이터 크롤링링 중...")
all_clauses = []

for i, section in enumerate(sections):
    doc_id = section["documentId"]
    title = section.get("title", "")
    
    try:
        # 본문 API
        res = requests.get(f"{PARA_URL}/{doc_id}", headers=headers)
        clauses = res.json().get("clauses", [])
        
        # 메타데이터 꼬리표 달아주기
        for c in clauses:
            c["sectionTitle"] = title
            c["sectionLevel"] = section.get("level", 0)
            
        all_clauses.extend(clauses)
        print(f"  [{i+1:3d}/{len(sections)}] {title[:20]:<20s} → {len(clauses)}개 문단 추출")
        
    except Exception as e:
        print(f"  ❌ 에러 발생: {title} - {e}")
        
    time.sleep(0.2) # 차단 방지 딜레이

output_path = f"{OUTPUT_DIR}/kifrs_1115_all.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(all_clauses, f, ensure_ascii=False, indent=2)

print(f"\n🎉 크롤링 완벽 성공! 총 {len(all_clauses)}개의 진짜 본문 데이터가 저장되었습니다.")
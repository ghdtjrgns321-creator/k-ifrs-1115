import json

with open("data/raw/sections_index.json", "r", encoding="utf-8") as f:
    data = json.load(f)
    print("✅ 데이터 총 개수:", len(data))
    print("✅ 첫 번째 항목의 Key 목록:", list(data[0].keys()))
import requests
import json
import os
import re
import time

def clean_qna_text(text):
    if not text: return ""
    text = text.replace('&nbsp;', ' ')
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'<[^>]+>', '', text) 
    return text.strip()

def fetch_targeted_qnas():
    OUTPUT_FILE = "data/web/kifrs-1115-qna-chunks.json"
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    qna_chunks = []
    total_found = 0
    
    # API 타겟과 실무적 가중치 매핑
    TARGET_CONFIGS = [
        {"type": 13, "name": "IFRS 해석위원회", "weight": 1.18},  # 1순위 상단 (1.18)
        {"type": 25, "name": "금융감독원", "weight": 1.18},       # 1순위 상단 (1.18)
        {"type": 11, "name": "회계기준원 정규질의", "weight": 1.15}, # 1순위 표준 (1.15)
        {"type": 15, "name": "신속처리질의", "weight": 1.05}        # 3순위 강등 (1.05)
    ]
    
    print("가중치가 적용된 K-IFRS 타겟 크롤링을 시작합니다\n")
    
    for config in TARGET_CONFIGS:
        category_type = config["type"]
        category_name = config["name"]
        weight = config["weight"]
        
        print(f"=============================================")
        print(f"🔍 [{category_name}] 게시판 스캔 중... (가중치: {weight})")
        
        page = 1
        
        while True:

            url = f"https://www.kifrs.com/api/qnas/v2?types={category_type}&page={page}&rows=50"
            
            try:
                res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                if res.status_code != 200:
                    break
                    
                data = res.json()
                # v2 API는 리스트가 'facilityQnas'에 주로 담김.
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
                    
                    # 정밀 타겟팅: '1115' 문자열 포함 여부 확인
                    if "1115" in rel_stds:
                        total_found += 1
                        clean_content = clean_qna_text(full_content)
                        
                        # 출처가 명확히 보이는 계층 구조
                        hierarchy_path = f"질의회신 > {category_name} > K-IFRS 제1115호 > {title} ({date_str})"
                        
                        chunk = {
                            "id": f"QNA-{doc_id}",
                            "content": clean_content,
                            "metadata": {
                                "stdNum": "1115",
                                "paraNum": doc_id,
                                "category": f"질의회신({category_name})",
                                "weight_score": weight,  # 카테고리별 차등 가중치 적용
                                "hierarchy": hierarchy_path,
                                "sectionLevel": 1
                            }
                        }
                        qna_chunks.append(chunk)
                        print(f"  🎯 [HIT!] {doc_id} ({title})")
                
                page += 1
                time.sleep(0.3) 
                
            except Exception as e:
                print(f"❌ 통신 에러 발생: {e}")
                break

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(qna_chunks, f, ensure_ascii=False, indent=2)

    print(f"\n=============================================")
    print(f"크롤링 및 가중치 매핑 완벽 종료")
    print(f"총 {total_found}개의 공신력 빵빵한 RAG 데이터가 준비되었습니다.")
    print(f"결과물 저장: {OUTPUT_FILE}")
    print(f"=============================================")

if __name__ == "__main__":
    fetch_targeted_qnas()
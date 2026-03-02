import json
import os
import re
import requests
from bs4 import BeautifulSoup

def clean_breadcrumb_text(html_text):
    """HTML 태그와 불필요한 주석 기호를 깔끔하게 제거."""
    if not html_text:
        return html_text
        
    soup = BeautifulSoup(html_text, "html.parser")
    clean_text = soup.get_text(separator=" ")
    clean_text = re.sub(r'\(주\d+\)', '', clean_text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text

def clean_html_to_md(item):
    para_num = str(item.get("paraNum", ""))
    prefix = f"{para_num} " if para_num else ""
    
    html_content = item.get("paraContent", "")
    full_content = item.get("fullContent", "")
    
    # 외부 파일(표) 분리 케이스 탐지
    if 'data-file-name' in html_content:
        clean_text = full_content.replace('\xa0', ' ')
        lines = [line.strip() for line in clean_text.split('\n')]
        clean_full = '\n'.join([line for line in lines if line]) 
        return f"{prefix}{clean_full}"

    if not html_content:
        return f"{prefix}{full_content.strip()}" if full_content else ""

    soup = BeautifulSoup(html_content, 'html.parser')

    # 마크다운 테이블 렌더링
    for tbl in soup.find_all('table'):
        md_table = []
        rows = tbl.find_all('tr')
        for i, tr in enumerate(rows):
            cols = tr.find_all(['td', 'th'])
            row_data = [col.get_text(separator=" ", strip=True).replace('\n', ' ') for col in cols]
            if not row_data: continue
            md_table.append("| " + " | ".join(row_data) + " |")
            if i == 0:
                md_table.append("|" + "|".join(["---"] * len(row_data)) + "|")
        
        new_tag = soup.new_tag('p')
        new_tag.string = "\n\n" + "\n".join(md_table) + "\n\n"
        tbl.replace_with(new_tag)

    # 들여쓰기 리스트 처리
    for div in soup.find_all('div'):
        classes = div.get('class', [])
        if isinstance(classes, str): classes = [classes]

        if 'idt-1' in classes:
            text = div.get_text(separator=" ", strip=True)
            text = re.sub(r'^(\(\d+\))\s*', r'\1 ', text)
            div.string = f"\n  - {text}\n"
        elif 'idt-2' in classes:
            text = div.get_text(separator=" ", strip=True)
            text = re.sub(r'^(\([가-힣]\))\s*', r'\1 ', text)
            div.string = f"\n    - {text}\n"

    # HTML 껍데기 벗기기
    text = soup.get_text(separator="\n", strip=True)
    final_md = re.sub(r'\n{3,}', '\n\n', text)

    # 조항 번호 결합
    if prefix and not final_md.startswith(str(para_num)):
        final_md = f"{prefix}{final_md}"

    return final_md

# 계층 정보 기반 카테고리 & 가중치 할당 함수
def get_category_and_weight(uid, hierarchy):
    # 1순위: 확실한 식별자(UID) 및 대분류를 가장 먼저 잡아냄.
    if "BC" in uid or "결론도출근거" in hierarchy:
        return "결론도출근거", 1.10
    if "IE" in uid or "적용사례" in hierarchy:
        return "적용사례IE", 1.10
        
    # 2순위: 부록 세부 항목들을 판별.
    if "부록 B" in hierarchy or "적용지침" in hierarchy:
        return "적용지침B", 1.20
    if "부록 A" in hierarchy or "용어의 정의" in hierarchy:
        return "용어정의", 1.05
    if "부록 C" in hierarchy or "시행일" in hierarchy or "경과 규정" in hierarchy:
        return "시행일", 1.05
        
    # 3순위: 위 조건에 모두 해당하지 않으면 일반 본문으로 분류함.
    return "본문", 1.15


def process_kifrs_chunks():
    INPUT_FILE = "data/web/kifrs-1115-all.json"
    OUTPUT_FILE = "data/web/kifrs-1115-chunks.json"
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    print("JSON 데이터 파싱 및 RAG 청킹 (가중치 태깅)을 시작합니다...")
    
    res = requests.get("https://www.kifrs.com/api/standard-indexes/1115", headers={"User-Agent": "Mozilla/5.0"})
    sections = res.json().get("standardIndexes", [])
    section_map = {sec["documentId"]: sec for sec in sections}

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    best_paragraphs = {}
    for item in raw_data:
        uid = str(item.get("uniqueKey", ""))
        if not uid: continue
        
        curr_level = item.get("sectionLevel", -1)
        if uid not in best_paragraphs or curr_level > best_paragraphs[uid].get("sectionLevel", -1):
            best_paragraphs[uid] = item

    print(f"  -> 중복 데이터 압축 완료: {len(raw_data)}개 원본 -> {len(best_paragraphs)}개 고유 문단")

    chunks = []
    for uid, item in best_paragraphs.items():
        clean_text = clean_html_to_md(item)
        if not clean_text.strip(): continue

        doc_id = item.get("documentId")
        hierarchy_path = item.get("sectionTitle", "")

        # Breadcrumb(계층 경로) 조립
        if doc_id and doc_id in section_map:
            sec_info = section_map[doc_id]
            family_ids = sec_info.get("parentDocumentIds", []) + [doc_id]
            family_nodes = [section_map[fid] for fid in family_ids if fid in section_map]
            family_nodes.sort(key=lambda x: x.get("level", 0))
            
            titles = [node.get("title", "") for node in family_nodes]
            titles = [t for t in titles if t and "제1115호" not in t]
            if titles:
                hierarchy_path = " > ".join(titles)
                hierarchy_path = clean_breadcrumb_text(hierarchy_path)
                
        # 카테고리 및 가중치 계산
        category, weight = get_category_and_weight(uid, hierarchy_path)

        chunk = {
            "id": uid,
            "content": clean_text,
            "metadata": {
                "stdNum": "1115",
                "paraNum": str(item.get("paraNum", "")),
                "category": category,
                "weight_score": weight,  # 🎯 검색 시 Re-ranking에 사용할 핵심 무기
                "hierarchy": hierarchy_path, 
                "sectionLevel": item.get("sectionLevel", 0)
            }
        }
        chunks.append(chunk)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    print(f"✅ 총 {len(chunks)}개의 가중치 기반 RAG 청크 생성 완료!")
    print(f"📁 결과물 저장: {OUTPUT_FILE}")
    
    # 적용지침 샘플 하나 출력해서 가중치가 잘 들어갔는지 확인
    sample_chunk = next((c for c in chunks if c["metadata"]["category"] == "적용지침B"), None)
    if sample_chunk:
        print("\n [데이터 변환 샘플 확인 (적용지침B)]")
        print(json.dumps(sample_chunk, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    process_kifrs_chunks()
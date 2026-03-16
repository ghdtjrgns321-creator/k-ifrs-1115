import io
import sys
# Windows cp949 환경에서 이모지 출력 시 UnicodeEncodeError 방지
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

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
    clean_text = re.sub(r"\(주\d+\)", "", clean_text)
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    return clean_text


def clean_html_to_md(item):
    para_num = str(item.get("paraNum", ""))
    # 볼드 형식으로 조항 번호를 명시 (검색 시 가시성 향상)
    prefix = f"**[문단 {para_num}]** " if para_num else ""

    html_content = item.get("paraContent", "")
    full_content = item.get("fullContent", "")

    # 외부 파일(표) 분리 케이스 탐지
    if "data-file-name" in html_content:
        clean_text = full_content.replace("\xa0", " ")
        lines = [line.strip() for line in clean_text.split("\n")]
        clean_full = "\n".join([line for line in lines if line])
        return f"{prefix}{clean_full}"

    if not html_content:
        return f"{prefix}{full_content.strip()}" if full_content else ""

    soup = BeautifulSoup(html_content, "html.parser")

    # [수정 2] <sup>/<sub>를 unwrap 전에 텍스트로 변환 (위/아래 첨자 보존)
    # unwrap 이후에 처리하면 태그 정보가 사라져 ^N, _N 형식으로 복원 불가
    for tag in soup.find_all("sup"):
        tag.string = f"^{tag.get_text()}"
    for tag in soup.find_all("sub"):
        tag.string = f"_{tag.get_text()}"

    # 마크다운 테이블 렌더링
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

    # 번호 목록 처리 (para-inner-number 구조)
    # kifrs.com HTML: (1),(2) = para-inner-number-item, (가),(나) = hanguel-item
    # 부모 div 단위로 모든 자식 항목을 텍스트 조립 후 교체
    _NUM_ITEM_CLASSES = {"para-inner-number-item", "para-inner-number-hanguel-item"}
    for number_div in soup.find_all("div", class_="para-inner-number"):
        lines = []
        for child in number_div.find_all("div", recursive=False):
            child_classes = set(child.get("class", []))
            if not child_classes & _NUM_ITEM_CLASSES:
                continue
            num_div = child.find("div", class_="para-number-para-num")
            con_div = child.find("div", class_="para-num-item-para-con")
            if num_div and con_div:
                num_text = num_div.get_text(strip=True)
                con_text = con_div.get_text(separator=" ", strip=True)
                lines.append(f"{num_text} {con_text}")
        if lines:
            new_tag = soup.new_tag("p")
            new_tag.string = "\n\n" + "\n\n".join(lines) + "\n\n"
            number_div.replace_with(new_tag)

    # 들여쓰기 리스트 처리
    for div in soup.find_all("div"):
        classes = div.get("class", [])
        if isinstance(classes, str):
            classes = [classes]

        if "idt-1" in classes:
            text = div.get_text(separator=" ", strip=True)
            text = re.sub(r"^(\(\d+\))\s*", r"\1 ", text)
            div.string = f"\n  - {text}\n"
        elif "idt-2" in classes:
            text = div.get_text(separator=" ", strip=True)
            text = re.sub(r"^(\([가-힣]\))\s*", r"\1 ", text)
            div.string = f"\n    - {text}\n"

    # 인라인 태그 껍데기 제거 (sup/sub는 이미 텍스트로 변환했으므로 포함)
    INLINE_TAGS = ["a", "span", "strong", "em", "b", "i", "u", "mark", "sup", "sub"]
    for tag in soup.find_all(INLINE_TAGS):
        tag.unwrap()

    # HTML 껍데기 벗기기
    text = soup.get_text(separator="\n", strip=True)

    # ── 교차참조 링크 unwrap 후 separator="\n"으로 분리된 패턴 복원 ──────────────

    # "문단 B58\n의 기준을" → "문단 B58의 기준을" (문장 중간 참조 이음)
    text = re.sub(
        r"(문단\s*[A-Za-z0-9~～]+)\n([의에이가을를은는로으로와과도만])",
        r"\1\2",
        text,
    )
    # "\n문단 35(1)\n참조" → " 문단 35(1) 참조" (괄호번호 붙은 독립 행 참조 인라인화)
    text = re.sub(
        r"\n(문단\s*[A-Za-z0-9~～]+\([0-9가-힣]+\))\n",
        r" \1 ",
        text,
    )
    # "문단 39~45\n를" → "문단 39~45를" (범위 참조 이음)
    text = re.sub(
        r"(문단\s*[A-Za-z0-9~～]+(?:[~～][A-Za-z0-9]+)?)\n([을를])",
        r"\1\2",
        text,
    )
    # "IFRS 15\n를", "C7\n을", "(6)\n의" 처럼 알파벳/숫자/닫는괄호 뒤 줄바꿈 + 조사 이음
    text = re.sub(
        r"([A-Za-z0-9)])\n([의을를이가])\s",
        r"\1\2 ",
        text,
    )
    # "제1109호\n의", "제1116호\n를" — 기준서 번호 뒤 조사 이음
    text = re.sub(
        r"(제\d+호)\n([의을를이가])\s",
        r"\1\2 ",
        text,
    )
    # "위하여\n문단 X를", "하여\n문단 X를" — 문장 연결형 뒤 para ref 이음
    text = re.sub(
        r"([여서고며])\n(문단\s*[A-Za-z0-9~～]+(?:[~～][A-Za-z0-9]+)?[를을])",
        r"\1 \2",
        text,
    )
    # 복합 문단 참조 공통 패턴: 이나/와/과 연결자, 한-접두어, 점(.) 소수 포함
    # ~(U+007E), ～(U+FF5E), ∼(U+223C) 세 가지 물결 문자 모두 포함
    # 예) "91이나 95", "50~55와 59", "87과 88", "BC116A∼BC116U", "한129.1"
    _FLEX_REF = r"문단\s+[A-Za-z가-힣0-9~～∼.]+(?:[~～∼][A-Za-z가-힣0-9~～∼.]+)?(?:\s*(?:이나|와|과)\s*(?:문단\s*)?[A-Za-z가-힣0-9~～∼.]+)*"

    # "(\n문단 XX\n참조)" — 괄호 안 독립 행 참조를 인라인화
    # get_text(separator="\n")로 <a>태그 unwrap 시 parenthesis 안 참조가 독립 줄로 분리되는 케이스
    # 예: "라이선스 부여 (\n문단 B52~B63B\n참조)" → "라이선스 부여 ( 문단 B52~B63B 참조)"
    text = re.sub(
        rf"\n({_FLEX_REF})\n(참조[).]?\.?)",
        r" \1 \2",
        text,
    )
    # "문단 XX이나 YY\n에 따라/에서" — 복합 참조 + 조사 이음
    # 기존 rule 1은 [A-Za-z0-9~～]+ 로만 매칭하여 이나/와/한 포함 참조 미처리
    text = re.sub(
        rf"\n({_FLEX_REF})\n([의에이가을를은는로으로와과도만])",
        r" \1\2",
        text,
    )
    # "\n문단 XX\n)" — 닫는 괄호만 있는 케이스 (이행하는 수행의무(문단 B2~B13) 등)
    text = re.sub(
        rf"\n({_FLEX_REF})\n(\))",
        r" \1\2",
        text,
    )
    # "문단 XX\n(설명)과/와/에서/의" — 열거 문맥 참조 뒤 설명 괄호 이음
    # 예: "문단 81~83\n(할인액의 배분)과" → "문단 81~83 (할인액의 배분)과"
    text = re.sub(
        r"\n(문단\s+[^\n]{1,18})\n(\([^)]{1,50}\)(?:과|와|에서|에서도|의|을|를)?)",
        r" \1 \2",
        text,
    )
    # "문단 XX이나 YY\n까지/부터" — 까지/부터 조사 이음 (기존 패턴 미포함)
    # 예: "문단 한129.1부터 한129.4\n까지의 공시를" → "문단 한129.1부터 한129.4까지의 공시를"
    text = re.sub(
        r"\n(문단\s+[^\n]{1,18})\n(까지|부터)",
        r" \1\2",
        text,
    )
    # "문단 XX\n및/또는/다만" — 접속사 이음 (예: "문단 47\n및 용어의 정의")
    text = re.sub(
        r"\n(문단\s+[^\n]{1,18})\n(및|또는|다만)",
        r" \1 \2",
        text,
    )
    # "문단 XX이나/와 YY\n[에이가을를등]" — _FLEX_REF 미처리 복잡 참조 (한-접두어, 괄호 범위 등) + 조사
    # 예: "문단 한129.1 (2)~(6)\n에 따른" — _FLEX_REF가 괄호 범위를 인식 못하는 케이스 보완
    text = re.sub(
        r"\n(문단\s+[^\n]{1,18})\n([의에이가을를은는로으로와과도만])",
        r" \1\2",
        text,
    )
    # "...이\n문단 XX과/와\n문단 YY..." — 연결 조사(과/와)로 끝나는 독립 참조 행 → 앞뒤와 이음
    # 예: "거래가격을 배분하는 것이\n문단 73의 배분 목적과\n문단 78의..."
    text = re.sub(
        r"\n(문단\s+[^\n]{1,17}(?:과|와))\n",
        r" \1 ",
        text,
    )

    final_md = re.sub(r"\n{3,}", "\n\n", text)

    # 번호 항목 (1)/(가) 등이 줄 시작에 올 때 앞에 빈 줄 보장 (마크다운 단락 분리)
    # "(N) 한글" 또는 "(가) 한글" 패턴만 매칭 → 교차참조 "(1)과" 등은 공백 없으므로 미매칭
    final_md = re.sub(
        r"(?<!\n)\n(\((?:\d+|[가-힣])\) [가-힣])", r"\n\n\1", final_md
    )

    # fullContent에 있지만 HTML 파싱 결과에 없는 텍스트 보충
    # kifrs.com API에서 하위 항목을 paraContent에 넣지 않는 케이스 대응
    if full_content:
        fc_norm = re.sub(r"\s+", "", full_content)
        md_norm = re.sub(r"\s+", "", final_md)
        # fullContent 키워드 중 청크에 없는 것이 20% 이상이면 fullContent로 대체
        fc_words = set(re.findall(r"[가-힣]{3,}", fc_norm))
        md_words = set(re.findall(r"[가-힣]{3,}", md_norm))
        if fc_words and len(fc_words - md_words) / len(fc_words) > 0.3:
            clean_fc = full_content.replace("\xa0", " ")
            clean_fc = "\n".join(
                line.strip() for line in clean_fc.split("\n") if line.strip()
            )
            final_md = clean_fc

    # [수정 1] 텍스트 앞에 이미 있는 문단 번호 흔적 제거 후 볼드 prefix 결합
    # 기존 startswith 방식은 텍스트가 숫자로 시작하면 prefix를 아예 안 붙이는 버그가 있었음
    final_md = re.sub(r"^\s*" + re.escape(para_num) + r"\s*", "", final_md) if para_num else final_md
    if prefix:
        final_md = f"{prefix}{final_md}"

    return final_md


def _get_case_group_title(doc_id: str, section_map: dict) -> str:
    """
    IE 적용사례에서 'Small-to-Big' 연결 고리를 만드는 헬퍼.
    doc_id가 속한 섹션이 '사례 N: 제목' 패턴이면 그 제목을 반환.
    물리적 병합 없이 메타데이터로만 연결해 검색 후 프론트에서 그룹핑 가능하게 함.
    """
    if not doc_id or doc_id not in section_map:
        return ""
    sec_title = section_map[doc_id].get("title", "")
    if re.match(r"^사례\s*\d+", sec_title):
        return sec_title
    # 직계 부모 중 '사례 N' 패턴 탐색 (가장 가까운 부모부터)
    parent_ids = section_map[doc_id].get("parentDocumentIds", [])
    for pid in reversed(parent_ids):
        parent_title = section_map.get(pid, {}).get("title", "")
        if re.match(r"^사례\s*\d+", parent_title):
            return parent_title
    return ""


# 계층 정보 기반 카테고리 & 가중치 할당 함수
def get_category_and_weight(uid, hierarchy):
    # 1순위: 확실한 식별자(UID) 및 대분류를 가장 먼저 잡아냄.
    if "BC" in uid or "결론도출근거" in hierarchy:
        return "결론도출근거", 0.8
    if "IE" in uid or "적용사례" in hierarchy:
        return "적용사례IE", 1.1

    # 2순위: 부록 세부 항목들을 판별.
    if "부록 B" in hierarchy or "적용지침" in hierarchy:
        return "적용지침B", 1.3
    if "부록 A" in hierarchy or "용어의 정의" in hierarchy:
        return "용어정의", 0.8
    if "부록 C" in hierarchy or "시행일" in hierarchy or "경과 규정" in hierarchy:
        return "시행일", 0.8

    # 3순위: 위 조건에 모두 해당하지 않으면 일반 본문으로 분류함.
    return "본문", 1.3


def process_kifrs_chunks():
    INPUT_FILE = "data/web/kifrs-1115-all.json"
    OUTPUT_FILE = "data/web/kifrs-1115-chunks.json"
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    print("JSON 데이터 파싱 및 RAG 청킹 (가중치 태깅)을 시작합니다...")

    res = requests.get(
        "https://www.kifrs.com/api/standard-indexes/1115",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    sections = res.json().get("standardIndexes", [])
    section_map = {sec["documentId"]: sec for sec in sections}

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    best_paragraphs = {}
    for item in raw_data:
        uid = str(item.get("uniqueKey", ""))
        if not uid:
            continue

        curr_level = item.get("sectionLevel", -1)
        if uid not in best_paragraphs or curr_level > best_paragraphs[uid].get(
            "sectionLevel", -1
        ):
            best_paragraphs[uid] = item

    print(
        f"  -> 중복 데이터 압축 완료: {len(raw_data)}개 원본 -> {len(best_paragraphs)}개 고유 문단"
    )

    chunks = []
    for uid, item in best_paragraphs.items():
        clean_text = clean_html_to_md(item)
        if not clean_text.strip():
            continue

        doc_id = item.get("documentId")
        hierarchy_path = item.get("sectionTitle", "")

        # Breadcrumb(계층 경로) 조립
        if doc_id and doc_id in section_map:
            sec_info = section_map[doc_id]
            family_ids = sec_info.get("parentDocumentIds", []) + [doc_id]
            family_nodes = [
                section_map[fid] for fid in family_ids if fid in section_map
            ]
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
                "weight_score": weight,  # 검색 시 Re-ranking에 사용
                "hierarchy": hierarchy_path,
                "sectionLevel": item.get("sectionLevel", 0),
                # IE 사례 그룹 연결 고리: 프론트에서 같은 사례의 문단들을 묶을 때 사용
                # 물리적 병합 없이 메타데이터로만 연결 (Small-to-Big 전략)
                "case_group_title": _get_case_group_title(doc_id, section_map),
            },
        }
        chunks.append(chunk)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    print(f"✅ 총 {len(chunks)}개의 가중치 기반 RAG 청크 생성 완료!")
    print(f"📁 결과물 저장: {OUTPUT_FILE}")

    # 적용지침 샘플 하나 출력해서 가중치가 잘 들어갔는지 확인
    sample_chunk = next(
        (c for c in chunks if c["metadata"]["category"] == "적용지침B"), None
    )
    if sample_chunk:
        print("\n [데이터 변환 샘플 확인 (적용지침B)]")
        print(json.dumps(sample_chunk, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    process_kifrs_chunks()

# app/preprocessing/11-fix-external-tables.py
# 외부 테이블(data-file-name) 문단의 깨진 분개 데이터를 복구합니다.
#
# 문제: 03-chunk에서 data-file-name이 감지되면 fullContent를 그대로 사용 →
#       kifrs.com 외부 .htm 파일의 <table>이 "Evernote Export" 평문으로 소실됨.
# 해결: 외부 .htm을 크롤링 → paraContent HTML에 <table>을 주입 →
#       clean_html_to_md()로 처음부터 다시 변환 → MongoDB text 필드 교체.
#
# 사용법: PYTHONPATH=. uv run --env-file .env python app/preprocessing/11-fix-external-tables.py
#   --dry-run 옵션: 실제 DB 업데이트 없이 변환 결과만 확인

import io
import json
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import requests
from bs4 import BeautifulSoup

from app.config import settings

# 03-chunk-with-weight.py의 clean_html_to_md를 재사용
from app.preprocessing import chunk_helper  # noqa: E402 — 아래에서 동적 임포트

BASE_URL = "https://www.kifrs.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}
CRAWL_DELAY = 0.3


def fetch_table_html(file_path: str) -> str:
    """외부 .htm 파일에서 <table> HTML을 크롤링하여 반환."""
    url = f"{BASE_URL}{file_path}"
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table")
    return str(table) if table else ""


def inject_tables_into_html(para_content: str, table_htmls: list[str]) -> str:
    """paraContent HTML에서 data-file-name 참조를 실제 <table> HTML로 교체."""
    # data-file-name을 포함한 태그를 찾아 table HTML로 교체
    result = para_content
    for table_html in table_htmls:
        if not table_html:
            continue
        # data-file-name 속성이 포함된 태그 패턴 제거 후 table 삽입
        # 패턴: <... data-file-name="..." ...>...</...> 또는 self-closing
        result = re.sub(
            r'<[^>]*data-file-name="[^"]*"[^>]*>(?:</[^>]*>)?',
            table_html,
            result,
            count=1,
        )
    return result


def clean_html_to_md(item: dict) -> str:
    """03-chunk-with-weight.py의 clean_html_to_md 로직 복제 (테이블 주입 후)."""
    para_num = str(item.get("paraNum", ""))
    prefix = f"**[문단 {para_num}]** " if para_num else ""

    html_content = item.get("paraContent", "")
    if not html_content:
        full_content = item.get("fullContent", "")
        return f"{prefix}{full_content.strip()}" if full_content else ""

    soup = BeautifulSoup(html_content, "html.parser")

    # sup 각주 제거
    for tag in soup.find_all("sup"):
        inner = tag.get_text().strip()
        if inner.isdigit():
            tag.decompose()
        else:
            tag.string = f"^{inner}"
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

    # 들여쓰기 리스트
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

    # 인라인 태그 제거
    for tag in soup.find_all(["a", "span", "strong", "em", "b", "i", "u", "mark", "sup", "sub"]):
        tag.unwrap()

    text = soup.get_text(separator="\n", strip=True)

    # 교차참조 줄바꿈 복원 (03-chunk과 동일)
    text = re.sub(r"(문단\s*[A-Za-z0-9~～]+)\n([의에이가을를은는로으로와과도만])", r"\1\2", text)
    text = re.sub(r"\n(문단\s*[A-Za-z0-9~～]+\([0-9가-힣]+\))\n", r" \1 ", text)
    text = re.sub(r"(문단\s*[A-Za-z0-9~～]+(?:[~～][A-Za-z0-9]+)?)\n([을를])", r"\1\2", text)
    text = re.sub(r"([A-Za-z0-9)])\n([의을를이가])\s", r"\1\2 ", text)
    text = re.sub(r"(제\d+호)\n([의을를이가])\s", r"\1\2 ", text)

    final_md = re.sub(r"\n{3,}", "\n\n", text)
    final_md = re.sub(r"^\s*" + re.escape(para_num) + r"\s*", "", final_md) if para_num else final_md
    if prefix:
        final_md = f"{prefix}{final_md}"
    return final_md


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    # 1) 원본 크롤링 데이터에서 data-file-name이 있는 문단 수집
    with open("data/web/kifrs-1115-all.json", "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # paraNum → (raw_item, [file_paths]) 매핑 (중복 제거, 최고 sectionLevel 유지)
    para_items: dict[str, tuple[dict, list[str]]] = {}
    for item in raw_data:
        pn = str(item.get("paraNum", ""))
        pc = item.get("paraContent", "")
        if not pn or "data-file-name" not in pc:
            continue
        files = re.findall(r'data-file-name="([^"]+)"', pc)
        if not files:
            continue
        curr_level = item.get("sectionLevel", -1)
        if pn not in para_items or curr_level > para_items[pn][0].get("sectionLevel", -1):
            para_items[pn] = (item, files)

    print(f"외부 테이블이 있는 고유 문단: {len(para_items)}개")

    # 2) 외부 테이블 크롤링 (HTML 원본)
    para_table_htmls: dict[str, list[str]] = {}
    total_files = sum(len(fs) for _, fs in para_items.values())
    fetched = 0
    for pn, (_, files) in para_items.items():
        htmls: list[str] = []
        for fp in files:
            fetched += 1
            try:
                html = fetch_table_html(fp)
                htmls.append(html)
                status = f"✅ {len(html)}자" if html else "⚠️ 테이블 없음"
                print(f"  [{fetched}/{total_files}] {pn} ← {fp} → {status}")
            except Exception as e:
                htmls.append("")
                print(f"  [{fetched}/{total_files}] {pn} ← {fp} → ❌ {e}")
            time.sleep(CRAWL_DELAY)
        para_table_htmls[pn] = htmls

    # 3) HTML에 테이블 주입 → clean_html_to_md 재실행 → MongoDB 업데이트
    from pymongo import MongoClient

    client = MongoClient(settings.mongo_uri)
    db = client[settings.mongo_db_name]
    col = db[settings.mongo_collection_name]

    updated = 0
    skipped = 0
    for pn, (raw_item, _) in para_items.items():
        table_htmls = para_table_htmls.get(pn, [])
        if not any(table_htmls):
            skipped += 1
            continue

        # paraContent에 외부 테이블 HTML 주입
        original_pc = raw_item.get("paraContent", "")
        injected_pc = inject_tables_into_html(original_pc, table_htmls)

        # 테이블이 주입된 item으로 clean_html_to_md 재실행
        patched_item = {**raw_item, "paraContent": injected_pc}
        new_text = clean_html_to_md(patched_item)

        chunk_id = f"1115-{pn}"
        doc = col.find_one({"chunk_id": chunk_id})
        if not doc:
            print(f"  ⚠️ DB에 {chunk_id} 없음 — 스킵")
            skipped += 1
            continue

        old_text = doc.get("text", "")

        if dry_run:
            print(f"\n{'='*60}")
            print(f"[DRY RUN] {chunk_id}")
            print(f"{'='*60}")
            # 테이블 부분만 발췌
            for line in new_text.split("\n"):
                if "|" in line and "---" not in line:
                    print(f"  {line}")
            # 전체 길이 비교
            print(f"  기존 text: {len(old_text)}자 → 새 text: {len(new_text)}자")
        else:
            col.update_one(
                {"_id": doc["_id"]},
                {"$set": {"text": new_text}},
            )
            updated += 1
            print(f"  ✅ {chunk_id} 업데이트 완료")

    print(f"\n{'='*40}")
    print(f"완료: 업데이트 {updated}건, 스킵 {skipped}건")
    if dry_run:
        print("(DRY RUN — 실제 DB 변경 없음)")


if __name__ == "__main__":
    main()

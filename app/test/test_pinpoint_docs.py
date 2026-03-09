# app/test/test_pinpoint_docs.py
# 핀포인트 패널 문서 로딩 전수 검증 — topics.json의 모든 문단 참조가 DB에 존재하는지 확인
#
# 실행: PYTHONPATH=. uv run --env-file .env python app/test/test_pinpoint_docs.py

import json
import re
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
root = str(Path(__file__).parent.parent.parent)
if root not in sys.path:
    sys.path.insert(0, root)

from pymongo import MongoClient
from app.config import settings


def expand_para_range(raw_num: str) -> list[str]:
    """_expand_para_range 로직 복제 (Streamlit 의존성 없이)."""
    stripped = raw_num.strip()
    m = re.match(r"^([A-Za-z]*?)(\d+)[~～\-]([A-Za-z]*?)(\d+)$", stripped)
    if m:
        prefix = m.group(1) or m.group(3)
        s, e = int(m.group(2)), int(m.group(4))
        if s <= e and (e - s) <= 20:
            return [f"{prefix}{n}" for n in range(s, e + 1)]
    m2 = re.match(
        r"^([A-Za-z]*?\d+)([A-Za-z])[~～\-]([A-Za-z]*?\d+)([A-Za-z])$", stripped
    )
    if m2 and m2.group(1) == m2.group(3):
        base = m2.group(1)
        return [
            f"{base}{chr(c)}"
            for c in range(ord(m2.group(2)), ord(m2.group(4)) + 1)
        ]
    m3 = re.match(r"^([A-Za-z]*?\d+)[~～\-]([A-Za-z]*?\d+)([A-Za-z])$", stripped)
    if m3 and m3.group(1) == m3.group(2):
        base = m3.group(1)
        result = [base]
        for c in range(ord("A"), ord(m3.group(3)) + 1):
            result.append(f"{base}{chr(c)}")
        return result if len(result) <= 20 else [base]
    return [raw_num]


def main():
    # MongoDB 연결
    client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    coll = client[settings.mongo_db_name][settings.mongo_collection_name]

    # topics.json 로드
    json_path = Path(root) / "data" / "topic-curation" / "topics.json"
    with open(json_path, encoding="utf-8") as f:
        topics = json.load(f)

    total_refs = 0
    found_refs = 0
    missing: list[tuple[str, str, str]] = []
    empty_sections: list[tuple[str, str]] = []

    for topic_key, topic_data in topics.items():
        sections = topic_data.get("main_and_bc", {}).get("sections", [])
        for sec in sections:
            title = sec.get("title", "")
            raw_paras = sec.get("paras", [])
            raw_bc = sec.get("bc_paras", [])

            all_expanded: list[str] = []
            for p in raw_paras:
                all_expanded.extend(expand_para_range(p))
            for p in raw_bc:
                all_expanded.extend(expand_para_range(p))

            if not all_expanded:
                empty_sections.append((topic_key, title))
                continue

            # DB 일괄 조회
            chunk_ids = [f"1115-{p}" for p in all_expanded]
            found_ids = set()
            for doc in coll.find(
                {"chunk_id": {"$in": chunk_ids}}, {"chunk_id": 1}
            ):
                found_ids.add(doc["chunk_id"])

            for p in all_expanded:
                total_refs += 1
                cid = f"1115-{p}"
                if cid in found_ids:
                    found_refs += 1
                else:
                    missing.append((topic_key, title, p))

    # 결과 출력
    print("=" * 60)
    print("핀포인트 패널 문서 로딩 전수 검증")
    print("=" * 60)
    print(f"\n총 토픽: {len(topics)}개")
    print(f"총 문단 참조: {total_refs}개")
    print(f"DB 존재: {found_refs}개")
    print(f"DB 누락: {len(missing)}개")
    print(f"문단 참조 없는 섹션: {len(empty_sections)}개")

    if missing:
        print(f"\n[FAIL] 누락된 문단 참조:")
        for topic, sec_title, para in missing:
            print(f"  - [{topic}] {sec_title} -> 문단 {para}")
    else:
        print("\n[OK] 모든 문단 참조가 DB에 존재합니다.")

    if empty_sections:
        print(f"\n[WARN] 문단 참조가 없는 섹션 ({len(empty_sections)}개):")
        for topic, sec_title in empty_sections:
            print(f"  - [{topic}] {sec_title}")

    # filter_relevant_sections 테스트
    print("\n" + "=" * 60)
    print("filter_relevant_sections 테스트")
    print("=" * 60)

    from app.domain.tree_matcher import filter_relevant_sections

    test_cases = [
        ("본인 vs 대리인", ["통제", "본인", "대리인"]),
        ("계약의 식별", ["계약", "식별", "요건"]),
        ("변동대가", ["변동", "대가", "추정"]),
        ("수행의무 식별", ["수행의무", "구별"]),
        ("기간에 걸쳐 vs 한 시점 인식", ["기간", "시점", "인식"]),
    ]

    for topic_key, keywords in test_cases:
        filtered = filter_relevant_sections(topic_key, keywords)
        print(f"\n토픽: {topic_key} | 키워드: {keywords}")
        print(f"  필터링된 섹션: {len(filtered)}개")
        for sec in filtered:
            paras = sec.get("paras", [])
            bc_paras = sec.get("bc_paras", [])
            has_docs = bool(paras or bc_paras)
            print(
                f"    - {sec['title']} | "
                f"paras={len(paras)} bc_paras={len(bc_paras)} "
                f"{'[OK]' if has_docs else '[WARN: no docs]'}"
            )

    # 성공/실패 리턴
    if missing:
        print(f"\n[RESULT] FAIL - {len(missing)}개 누락")
        sys.exit(1)
    else:
        print("\n[RESULT] PASS - 전수 검증 통과")
        sys.exit(0)


if __name__ == "__main__":
    main()

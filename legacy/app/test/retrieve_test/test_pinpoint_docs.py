# app/test/test_pinpoint_docs.py
# 핀포인트 문서 전수 검증 -3가지 검증 계층:
#   1) topics.json paras/bc_paras → DB chunk_id 존재 검증
#   2) _parse_doc_ids_from_text() 파싱 결과 상세 출력
#   3) IE 사례 hierarchy regex 매칭 검증
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
from app.retriever import _parse_doc_ids_from_text, _fetch_ie_case_chunks


def expand_para_range(raw_num: str) -> list[str]:
    """_expand_para_range 로직 복제 (Streamlit 의존성 없이)."""
    stripped = raw_num.strip()
    # 소수점 범위: "한129.1~5" → 한129.1, 한129.2, ..., 한129.5
    m_dot = re.match(r"^(.+?)(\d+)\.(\d+)\s*[~～\-]\s*(\d+)$", stripped)
    if m_dot:
        prefix, base, start, end = m_dot.group(1), m_dot.group(2), int(m_dot.group(3)), int(m_dot.group(4))
        if start <= end and (end - start) <= 20:
            return [f"{prefix}{base}.{n}" for n in range(start, end + 1)]
    m = re.match(r"^([A-Za-z\uac00-\ud7a3]*?)(\d+)[~～\-]([A-Za-z\uac00-\ud7a3]*?)(\d+)$", stripped)
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


# ── 검증 1: topics.json paras/bc_paras → DB 존재 검증 ────────────────────────

def verify_section_chunks(coll, topics: dict) -> tuple[int, int, list, list]:
    """topics.json의 모든 문단 참조가 DB에 존재하는지 확인."""
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

    return total_refs, found_refs, missing, empty_sections


# ── 검증 2: _parse_doc_ids_from_text() 파싱 결과 상세 출력 ────────────────────

def verify_parsed_ids(db) -> dict:
    """decision_trees의 precedents/red_flags 텍스트에서 파싱된 ID를 상세 출력하고 DB 존재 확인."""
    from app.domain.decision_trees import MASTER_DECISION_TREES

    coll = db[settings.mongo_collection_name]
    stats = {"total_parsed": 0, "found_in_db": 0, "missing_from_db": []}

    for topic_key, topic_data in MASTER_DECISION_TREES.items():
        # decision_tree에서 파싱 대상 텍스트 수집
        text_parts: list[str] = []
        for cases in topic_data.get("4_precedents", {}).values():
            text_parts.extend(cases)
        rf = topic_data.get("5_red_flags", {})
        for items in rf.get("check_items_by_branch", {}).values():
            text_parts.extend(items)
        # 체크리스트에도 문단 참조 포함
        for item in topic_data.get("2_checklist", []):
            text_parts.append(item)

        if not text_parts:
            continue

        combined = "\n".join(text_parts)
        parsed = _parse_doc_ids_from_text(combined)

        # 파싱 결과가 있으면 출력
        has_any = any(v for v in parsed.values())
        if not has_any:
            continue

        print(f"\n  [{topic_key}] 파싱 결과:")
        for id_type, id_list in parsed.items():
            if id_list:
                print(f"    {id_type}: {id_list}")

        # paragraph chunk_id DB 존재 확인
        if parsed["paragraphs"]:
            chunk_ids = [f"1115-{p}" for p in parsed["paragraphs"]]
            found_ids = {
                doc["chunk_id"]
                for doc in coll.find({"chunk_id": {"$in": chunk_ids}}, {"chunk_id": 1})
            }
            for p in parsed["paragraphs"]:
                stats["total_parsed"] += 1
                cid = f"1115-{p}"
                if cid in found_ids:
                    stats["found_in_db"] += 1
                else:
                    stats["missing_from_db"].append((topic_key, cid))

        # QNA parent_id DB 존재 확인
        if parsed["qna"]:
            from app.retriever import QNA_PARENT_COLL
            qna_coll = db[QNA_PARENT_COLL]
            for qid in parsed["qna"]:
                stats["total_parsed"] += 1
                if qna_coll.find_one({"_id": qid}, {"_id": 1}):
                    stats["found_in_db"] += 1
                else:
                    stats["missing_from_db"].append((topic_key, qid))

        # 감리사례 parent_id DB 존재 확인
        if parsed["findings"]:
            from app.retriever import FINDINGS_PARENT_COLL
            findings_coll = db[FINDINGS_PARENT_COLL]
            for fid in parsed["findings"]:
                stats["total_parsed"] += 1
                if findings_coll.find_one({"_id": fid}, {"_id": 1}):
                    stats["found_in_db"] += 1
                else:
                    stats["missing_from_db"].append((topic_key, fid))

    return stats


# ── 검증 3: IE 사례 hierarchy regex 매칭 검증 ────────────────────────────────

def verify_ie_regex(db) -> dict:
    """IE 사례 청크의 hierarchy 값을 확인하고, 현재 regex가 매칭되는지 검증."""
    coll = db[settings.mongo_collection_name]
    ie_chunks = list(coll.find(
        {"chunk_id": {"$regex": "^1115-IE"}},
        {"chunk_id": 1, "hierarchy": 1},
    ))

    # 실제 hierarchy 값 샘플 출력
    print(f"\n  IE 청크 총 수: {len(ie_chunks)}개")
    hierarchies = set()
    for doc in ie_chunks:
        h = doc.get("hierarchy", "")
        hierarchies.add(h)

    print(f"  고유 hierarchy 패턴 수: {len(hierarchies)}개")
    for h in sorted(hierarchies)[:20]:
        print(f"    - {repr(h)}")

    # 사례 1~30번까지 regex 매칭 테스트
    match_results = {}
    for n in range(1, 31):
        pattern = re.compile(rf'사례\s*{n}[\s:：]')
        matched_chunks = [
            doc["chunk_id"] for doc in ie_chunks
            if pattern.search(doc.get("hierarchy", ""))
        ]
        if matched_chunks:
            match_results[n] = matched_chunks

    print(f"\n  regex 매칭된 사례 번호: {sorted(match_results.keys())}")
    for n, chunks in sorted(match_results.items()):
        print(f"    사례 {n}: {len(chunks)}개 청크")

    return {"total_ie": len(ie_chunks), "matched_cases": match_results}


# ── 검증 4: chunk_id 패턴 샘플링 ─────────────────────────────────────────────

def sample_chunk_id_patterns(db):
    """DB의 chunk_id 패턴을 샘플링하여 "1115-{para}" 패턴과 비교."""
    coll = db[settings.mongo_collection_name]

    # 1115- 로 시작하는 chunk_id 패턴 분포
    all_chunks = list(coll.find(
        {"chunk_id": {"$regex": "^1115-"}},
        {"chunk_id": 1},
    ))

    # prefix별 카운트
    prefix_counts: dict[str, int] = {}
    for doc in all_chunks:
        cid = doc["chunk_id"]
        # "1115-" 뒤의 첫 알파벳 부분을 prefix로 추출
        after = cid[5:]  # "1115-" 이후
        m = re.match(r'^([A-Za-z]*)', after)
        prefix = m.group(1) if m else ""
        prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1

    print(f"\n  총 '1115-' 청크: {len(all_chunks)}개")
    print(f"  prefix별 분포:")
    for prefix, count in sorted(prefix_counts.items(), key=lambda x: -x[1]):
        sample = next(
            doc["chunk_id"] for doc in all_chunks
            if doc["chunk_id"][5:].startswith(prefix)
        )
        print(f"    '{prefix}': {count}개 (예: {sample})")


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    db = client[settings.mongo_db_name]
    coll = db[settings.mongo_collection_name]

    json_path = Path(root) / "data" / "topic-curation" / "topics.json"
    with open(json_path, encoding="utf-8") as f:
        topics = json.load(f)

    # ── 검증 1: sections paras/bc_paras ───────────────────────────────────────
    print("=" * 60)
    print("[검증 1] topics.json 섹션 문단 참조 → DB 존재 확인")
    print("=" * 60)

    total_refs, found_refs, missing, empty_sections = verify_section_chunks(coll, topics)
    print(f"\n총 토픽: {len(topics)}개")
    print(f"총 문단 참조: {total_refs}개")
    print(f"DB 존재: {found_refs}개, DB 누락: {len(missing)}개")

    if missing:
        print(f"\n[FAIL] 누락된 문단 참조:")
        for topic, sec_title, para in missing:
            print(f"  - [{topic}] {sec_title} -> 1115-{para}")
    else:
        print("[OK] 모든 섹션 문단 참조가 DB에 존재합니다.")

    # ── 검증 2: precedents/red_flags 파싱 ─────────────────────────────────────
    print("\n" + "=" * 60)
    print("[검증 2] precedents/red_flags 텍스트 파싱 + DB 존재 확인")
    print("=" * 60)

    parse_stats = verify_parsed_ids(db)
    print(f"\n  파싱된 참조 총 수: {parse_stats['total_parsed']}개")
    print(f"  DB 존재: {parse_stats['found_in_db']}개")
    if parse_stats["missing_from_db"]:
        print(f"  [FAIL] DB 누락 {len(parse_stats['missing_from_db'])}개:")
        for topic, ref_id in parse_stats["missing_from_db"]:
            print(f"    - [{topic}] {ref_id}")
    else:
        print("  [OK] 파싱된 모든 참조가 DB에 존재합니다.")

    # ── 검증 3: IE 사례 regex ─────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("[검증 3] IE 사례 hierarchy regex 매칭 검증")
    print("=" * 60)

    verify_ie_regex(db)

    # ── 검증 4: chunk_id 패턴 샘플링 ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("[검증 4] chunk_id 패턴 분포 (1115- prefix)")
    print("=" * 60)

    sample_chunk_id_patterns(db)

    # ── 최종 결과 ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    has_failures = bool(missing) or bool(parse_stats["missing_from_db"])
    if has_failures:
        print(f"[RESULT] FAIL -위 누락 항목 확인 필요")
        sys.exit(1)
    else:
        print("[RESULT] PASS -전수 검증 통과")
        sys.exit(0)


if __name__ == "__main__":
    main()

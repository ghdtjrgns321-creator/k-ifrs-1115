"""온톨로지 STEP 1: 기준서 공식 소제목 → 개념 노드 트리 추출

사용법:
  PYTHONPATH=. uv run python app/preprocessing/14-ontology-concepts.py

Why: 토픽/섹션 분류를 AI 생성물 대신 기준서 목차(title.level/ref)에서
     기계적으로 생성 → 온톨로지 뼈대의 신빙성 문제를 제거.
     문단→개념 연결은 ref 파싱이 아니라 documentId(권위 출처)를 사용하고,
     ref 범위는 교차 검증용으로만 쓴다. (설계: docs/ontology/00-overview.md)
"""

import json
import re
from pathlib import Path

SOURCE_PATH = Path("data/web/kifrs-1115-all.json")
OUTPUT_PATH = Path("data/ontology/concepts.json")

# 개념 추출 범위 — 본문 + 부록B (부록C 문단도 본문 흐름에 포함되어 함께 수집됨)
SCOPE_SECTIONS = {"본문", "부록 B 적용지침"}

# 목차상 존재하나 개념이 아닌 메타 항목 (제외 사유를 01-concepts.md에 기록)
EXCLUDE_TITLES = {
    "ㅇ",
    "기업회계기준서 제1115호의 제·개정 등에 대한 회계기준위원회의 의결",
}


def clean_title(raw: str) -> str:
    """HTML 태그(<sup>주석 등)를 제거하고 공백을 정리합니다."""
    text = re.sub(r"<[^>]+>", "", raw)
    return re.sub(r"\s+", " ", text).strip()


def para_sort_key(para_num: str) -> tuple:
    """paraNum을 (네임스페이스, 숫자) 정렬 키로 변환. 한4.1→(0,4.1), B63A→(1,63.01)

    한 접두사는 B/C와 복합 가능(한C1.1 = C 체계의 1.1) — 네임스페이스는 B/C가 결정.
    """
    m = re.match(r"^(한)?(B|C)?([\d.]+)([A-Z]?)$", para_num)
    if not m:
        return (9, 0.0)
    ns = {"B": 1, "C": 2}.get(m.group(2), 0)  # 한N은 본문 번호체계에 속함
    num = float(m.group(3)) + (0.01 * (ord(m.group(4)) - 64) if m.group(4) else 0)
    return (ns, num)


def parse_ref_range(ref: str) -> tuple | None:
    """ref 문자열 → (네임스페이스, 시작, 끝). 파싱 불가 시 None (검증에서 제외).

    한 접두사는 B/C와 복합 가능(예: 'C1~한C1.1') — para_sort_key와 동일 문법.
    """
    m = re.match(
        r"^(한)?(B|C)?([\d.]+)[A-Z]?(?:[~∼]\s*(한)?(B|C)?([\d.]+)[A-Z]?)?$", ref
    )
    if not m:
        return None
    start = float(m.group(3))
    end = float(m.group(6)) if m.group(6) else start
    ns = {"B": 1, "C": 2}.get(m.group(2), 0)
    return (ns, start, end)


def build_tree(titles: list[dict]) -> dict[str, dict]:
    """문서 순서 + level 스택으로 부모-자식 계층을 복원합니다."""
    concepts: dict[str, dict] = {}
    stack: list[tuple[float, str]] = []  # (level, documentId)
    for t in titles:
        level = float(t["level"])
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_id = stack[-1][1] if stack else None
        doc_id = t["documentId"]
        concepts[doc_id] = {
            "title": clean_title(t["title"]),
            "level": level,
            "ref": t.get("ref") or "",
            "parent": parent_id,
            "children": [],
            "paras": [],
        }
        if parent_id:
            concepts[parent_id]["children"].append(doc_id)
        stack.append((level, doc_id))
    # path(경로 문자열)와 section(소속 구획) 부여
    for doc_id, c in concepts.items():
        names, cur = [], doc_id
        while cur:
            names.append(concepts[cur]["title"])
            cur = concepts[cur]["parent"]
        c["path"] = " > ".join(reversed(names[:-1]))  # 최상위(기준서 제목)는 생략
        top2 = names[-2] if len(names) >= 2 else names[-1]  # 최상위 바로 아래
        if top2.startswith("부록 B"):
            c["section"] = "부록B"
        elif top2.startswith("부록 A"):
            c["section"] = "부록A"
        elif top2.startswith("부록 C"):
            c["section"] = "부록C"
        else:
            c["section"] = "본문"
    return concepts


def subtree_paras(concepts: dict, doc_id: str) -> list[str]:
    """개념 자신 + 모든 하위 개념의 문단을 수집합니다."""
    result = list(concepts[doc_id]["paras"])
    for child in concepts[doc_id]["children"]:
        result.extend(subtree_paras(concepts, child))
    return result


def validate_ref(concepts: dict) -> list[str]:
    """ref 범위 ↔ documentId 기반 문단 배정의 교차 검증. 불일치 목록 반환."""
    mismatches = []
    for doc_id, c in concepts.items():
        parsed = parse_ref_range(c["ref"])
        if not parsed:
            continue
        ns, start, end = parsed
        outside = [
            p
            for p in subtree_paras(concepts, doc_id)
            if not (
                para_sort_key(p)[0] == ns and start <= para_sort_key(p)[1] <= end + 0.99
            )
        ]
        if outside:
            mismatches.append(f"[{c['title']}] ref={c['ref']} 밖 문단: {outside}")
    return mismatches


def para_namespace(para_num: str) -> str:
    """paraNum → 번호체계 분류. 모집단 검증에서 수집 대상 여부 판정에 사용."""
    for pattern, ns in [
        (r"^BC", "BC"),
        (r"^IE", "IE"),
        (r"^한?B\d", "B"),
        (r"^한?C\d", "C"),
        (r"^한?\d", "본문"),
    ]:
        if re.match(pattern, para_num):
            return ns
    return "기타"


def verify_population(raw: list, scoped_keys: set) -> None:
    """모집단 등록 + 음의 공간 증명 (검사-후-모집단 방지).

    권위 출처 = 원본 파일의 전체 문단(type=paragraph, uniqueKey 고유).
    ① 음의 공간: 본문/B/C 번호체계 문단 중 수집 범위(SCOPE_SECTIONS) 밖 = 0건이어야 함
    ② 번호 연속성: 본문 1~129, 부록B 1~89, 부록C 1~10에 빠진 번호 = 0건이어야 함
    """
    universe: dict[str, str] = {}  # uniqueKey → paraNum
    for item in raw:
        if item.get("type") == "paragraph":
            universe.setdefault(item["uniqueKey"], item.get("paraNum", ""))
    target = {k for k, p in universe.items() if para_namespace(p) in {"본문", "B", "C"}}
    leaked = sorted(target - scoped_keys)
    mark = "✅" if not leaked else "❌"
    print(
        f"{mark} 모집단: 전체 고유 문단 {len(universe)}개 중 본문/B/C {len(target)}개, 수집 밖 누수 {len(leaked)}건 {leaked or ''}"
    )

    nums = {ns: set() for ns in ("본문", "B", "C")}
    for key in scoped_keys & target:
        p = universe[key]
        m = re.match(r"(\d+)", re.sub(r"^한?[BC]?", "", p))
        if m:
            nums[para_namespace(p)].add(int(m.group(1)))
    for ns, last in [("본문", 129), ("B", 89), ("C", 10)]:
        missing = sorted(set(range(1, last + 1)) - nums[ns])
        mark = "✅" if not missing else "❌"
        print(f"{mark} 연속성: {ns} 1~{last} 누락 {len(missing)}건 {missing or ''}")


def main():
    raw = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))

    # 1) 범위 내 문단 수집 — uniqueKey로 중복 제거 (부록B 문단이 2개 섹션에 중복 수록됨)
    paras: dict[str, dict] = {}
    for item in raw:
        if (
            item.get("type") == "paragraph"
            and item.get("sectionTitle") in SCOPE_SECTIONS
        ):
            paras.setdefault(item["uniqueKey"], item)
    print(f"문단: 원본 레코드 중복 제거 → 고유 {len(paras)}개")
    verify_population(raw, set(paras.keys()))

    # 2) 개념 후보 title 수집 — 범위 내 title + 범위 밖이지만 문단을 소유한 title(부록C 등)
    #    documentId로 중복 제거, 원본 리스트 순서(문서 순서) 유지
    owner_ids = {p["documentId"] for p in paras.values()}
    titles, seen = [], set()
    for item in raw:
        if item.get("type") != "title" or item["documentId"] in seen:
            continue
        if (
            item.get("sectionTitle") in SCOPE_SECTIONS
            or item["documentId"] in owner_ids
        ):
            if clean_title(item["title"]) in EXCLUDE_TITLES:
                seen.add(item["documentId"])  # 제외 항목도 중복 방지
                continue
            titles.append(item)
            seen.add(item["documentId"])
    print(f"개념 후보 title: {len(titles)}개 (제외 {len(EXCLUDE_TITLES)}건)")

    # 3) 계층 트리 구축 + 문단 배정 (documentId 연결)
    concepts = build_tree(titles)
    unassigned = []
    for key, p in paras.items():
        para_num = p.get("paraNum", "")
        if p["documentId"] in concepts:
            concepts[p["documentId"]]["paras"].append(para_num)
        else:
            unassigned.append(para_num)
    for c in concepts.values():
        c["paras"].sort(key=para_sort_key)
    assigned = len(paras) - len(unassigned)
    print(
        f"문단 배정: {assigned}/{len(paras)} (미배정 {len(unassigned)}: {unassigned})"
    )

    # 4) ref 교차 검증 — documentId 배정과 목차 ref 범위의 일치 여부
    # 분모 명시: ref가 파싱 가능한 개념만 검증 대상 (ref 없음/복합 표기는 제외)
    checkable = sum(1 for c in concepts.values() if parse_ref_range(c["ref"]))
    mismatches = validate_ref(concepts)
    print(
        f"ref 교차 검증: 대상 {checkable}/{len(concepts)}개 개념, 불일치 {len(mismatches)}건"
    )
    for m in mismatches:
        print(f"  ⚠️  {m}")

    # 5) 저장
    para_to_concept = {p: doc_id for doc_id, c in concepts.items() for p in c["paras"]}
    sections = {}
    for c in concepts.values():
        sections[c["section"]] = sections.get(c["section"], 0) + 1
    result = {
        "_meta": {
            "source": str(SOURCE_PATH),
            "generated_by": "app/preprocessing/14-ontology-concepts.py",
            "concept_count": len(concepts),
            "para_count": len(paras),
            "sections": sections,
        },
        "concepts": concepts,
        "para_to_concept": para_to_concept,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"저장: {OUTPUT_PATH} (개념 {len(concepts)}개, 구획별 {sections})")

    # 6) ripple 검증 — 서로 다른 구획의 개념 2개에서 문단 확장이 ref와 일치하는지
    for want_title, want_paras in [
        ("변동대가 추정치를 제약함", ["56", "57", "58"]),
        ("산출법", ["B15", "B16", "B17"]),
    ]:
        found = [c for c in concepts.values() if c["title"] == want_title]
        ok = found and found[0]["paras"] == want_paras
        print(
            f"{'✅' if ok else '❌'} ripple: {want_title} → {found[0]['paras'] if found else '없음'}"
        )


if __name__ == "__main__":
    main()

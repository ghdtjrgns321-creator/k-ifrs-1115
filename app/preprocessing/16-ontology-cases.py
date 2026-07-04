"""온톨로지 STEP 3: 문단→사례 스포크 — QNA·감리사례·IE를 기준서 문단에 연결

사용법:
  PYTHONPATH=. uv run python app/preprocessing/16-ontology-cases.py

Why: 사례→문단 연결 출처는 2계통뿐 — ①metadata.related_paragraphs(명시 필드)
     ②사례 원문의 "문단 N" 참조(15-ontology-edges.py와 동일 문법).
     소스별 회계 항등식(언급 N = 내부해소 + 타기준서 + 미해소)으로 전수 검증.
     BC 문단 652개는 이번 범위 밖 (docs/ontology/03-cases.md 참조).
"""

import json
import re
from pathlib import Path

CONCEPTS_PATH = Path("data/ontology/concepts.json")
SOURCE_PATH = Path("data/web/kifrs-1115-all.json")
QNA_PATH = Path("data/web/kifrs-1115-qna-chunks.json")
FINDINGS_PATH = Path("data/findings/findings-final.json")
IE_MAP_PATH = Path("data/ontology/ie-group-concept-map.json")  # 사용자 승인 21행
OUTPUT_PATH = Path("data/ontology/case_links.json")

_TOKEN = r"한?[BC]?[\d.]+[A-Z]?"
_RANGE = rf"{_TOKEN}(?:\s*[~∼]\s*{_TOKEN})?"
MENTION_RE = re.compile(rf"문단\s*({_RANGE})")
# 나열 연속에서 금액·단위 오인 방지: "문단 5, 500백만원"의 500은 문단이 아님
CONT_RE = re.compile(
    rf"^[⑴-⒇①-⑳\s]*(?:과|와|,|및|또는)\s*({_RANGE})(?![호년월일백천만억원개])"
)


def parse_num(token: str) -> tuple | None:
    m = re.match(r"^(한)?(B|C)?([\d.]+)([A-Z]?)$", token.strip())
    if not m:
        return None
    try:
        # "5.1.1" 같은 다중 점 번호(해석서 자체 목차)는 기준서 문단이 아님 → 미해소
        num = float(m.group(3)) + (0.01 * (ord(m.group(4)) - 64) if m.group(4) else 0)
    except ValueError:
        return None
    ns = {"B": 1, "C": 2}.get(m.group(2), 0)
    return (ns, num)


def resolve_range(range_str: str, para_keys: dict) -> list[str]:
    parts = re.split(r"[~∼]", range_str)
    lo = parse_num(parts[0])
    hi = parse_num(parts[-1]) if len(parts) > 1 else lo
    if not lo or not hi:
        return []
    return sorted(
        (
            p
            for p, (ns, n) in para_keys.items()
            if ns == lo[0] and lo[1] <= n <= hi[1] + 0.005
        ),
        key=lambda p: para_keys[p][1],
    )


# 기준 명칭 패턴: 문단 소유자를 결정하는 명시적 명명
# "동/이 기준서"는 직전 명명을 승계하는 중립 표현이라 패턴에서 제외
# 1115 자신의 표기: "제1115호" 또는 "IFRS 15" (국제기준 원문 표기)
_NAME_RE = re.compile(
    r"제(\d{4})호|IFRS\s*(\d+)|IAS\s*\d+|회계감사기준\s*\d+|감사기준서\s*\d+|개념체계"
)


def is_external(text: str, pos: int) -> bool:
    """언급 위치 앞에서 '가장 최근에 명명된 기준서'가 1115가 아니면 외부.

    Why: 인접(40자) 규칙만으로는 "제1038호 '무형자산' … 문단 15"류가
    1115 문단 15로 오연결됨 (QNA 실측 131/700 언급이 최근접 명칭 ≠ 1115).
    틀린 근거 연결은 누락보다 해로우므로 소유자 판정을 문서 흐름 기준으로 강화.
    명명이 한 번도 없으면 내부(1115 해설 문서이므로)로 본다.
    """
    last = None
    for m in _NAME_RE.finditer(text, 0, pos):
        last = m
    if last is None:
        return False
    return not (last.group(1) == "1115" or last.group(2) == "15")


def extract_refs(text: str, para_keys: dict, stats: dict) -> list[str]:
    """원문에서 '문단 N' 참조를 추출·해소. stats에 항등식 카운트 누적."""
    found: set[str] = set()
    for m in MENTION_RE.finditer(text):
        tokens = [m.group(1)]
        tail = text[m.end() :]
        while cm := CONT_RE.match(tail):
            tokens.append(cm.group(1))
            tail = tail[cm.end() :]
        for tk in tokens:
            stats["mentions"] += 1
            if is_external(text, m.start()):
                stats["external"] += 1
                continue
            targets = resolve_range(tk, para_keys)
            if targets:
                stats["resolved"] += 1
                found.update(targets)
            else:
                stats["unresolved"] += 1
                stats["unresolved_raw"].append(tk)
    return sorted(found, key=lambda p: para_keys[p][1])


def main():
    raw = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    para_text: dict[str, str] = {}
    for item in raw:
        if item.get("type") == "paragraph" and item.get("sectionTitle") in (
            "본문",
            "부록 B 적용지침",
        ):
            pn = item.get("paraNum", "")
            if pn and pn not in para_text:
                para_text[pn] = item.get("fullContent", "")
    para_keys = {p: k for p in para_text if (k := parse_num(p))}

    new_stats = lambda: {
        "mentions": 0,
        "resolved": 0,
        "external": 0,
        "unresolved": 0,
        "unresolved_raw": [],
    }
    result = {"qna": [], "findings": [], "ie": []}
    meta_stats = {}

    # ── QNA·감리: 감사본 related_paragraphs가 단일 원천 ─────────────
    # Why: 두 소스는 원문 대조(감리 23/23) + 멀티에이전트 전문 교차검증(QNA 95/101,
    # docs/materials/{fss,qna}/README.md)을 거친 감사 필드를 보유 → 자체 정규식
    # 추출을 union하면 미검증 노이즈가 얹힘(실측: QNA 4개 문서에서 타기준서 오귀속).
    # 정규식 추출은 감사 필드가 없는 IE 전용으로만 사용.
    def meta_normalize(p: str) -> str:
        """감사본 표기 정규화: '35(c)'→'35', 'B37⒜'→'B37' (세부항목 표기 절단)."""
        return re.sub(r"[^0-9A-Z한.].*$", "", str(p).strip())

    def collect_meta(
        items, id_field: str, title_fn, db_prefix: str
    ) -> tuple[list, dict]:
        rows, st = [], {"tokens": 0, "adopted": 0, "excluded": []}
        for item in items:
            md = item.get("metadata", {})
            paras = set()
            for p in md.get("related_paragraphs", []):
                st["tokens"] += 1
                np_ = meta_normalize(p)
                if np_ in para_keys:
                    st["adopted"] += 1
                    paras.add(np_)
                else:
                    st["excluded"].append(f"{md.get(id_field)}:{p}")
            cid = md.get(id_field, item.get("id", ""))
            rows.append(
                {
                    "id": cid,
                    # STEP 5 조회 규약: MongoDB parent_id (QNA는 "QNA-" 접두, 감리는 그대로)
                    # — DB 전수 대조(101/101·22/22, ID·문단·제목 불일치 0)로 확정
                    "db_parent_id": db_prefix + cid,
                    "title": title_fn(md),
                    "paras": sorted(paras, key=lambda p: para_keys[p][1]),
                    "source": "related_paragraphs(감사본)",
                }
            )
        return rows, st

    qna = json.loads(QNA_PATH.read_text(encoding="utf-8"))
    result["qna"], meta_stats["qna"] = collect_meta(
        qna, "paraNum", lambda md: md.get("title", ""), db_prefix="QNA-"
    )
    findings = json.loads(FINDINGS_PATH.read_text(encoding="utf-8"))
    result["findings"], meta_stats["findings"] = collect_meta(
        findings,
        "paraNum",
        lambda md: md.get("hierarchy", "").split(">")[-1].strip(),
        db_prefix="",
    )

    # ── IE 사례 65건: '사례 N' title 하위 IE 문단들의 원문 참조 ─────
    # Why: 사례 밑에 소제목(경우 A/B 등)이 있으면 문단의 documentId가
    # 소제목을 가리켜 사례 title 직접 매칭이 누락됨 (실측 16건 0연결) →
    # 문서 순서 기반으로 "가장 최근에 지나친 사례 N 제목"에 귀속.
    # 그룹(IE 목차 level-2, ref가 IE로 시작)도 같은 방식으로 추적 —
    # 사용자 승인 매핑(ie-group-concept-map.json)으로 사례→개념 간선의 원천.
    group_map = {
        g["group"]: g
        for g in json.loads(IE_MAP_PATH.read_text(encoding="utf-8"))["map"]
    }
    case_titles = {}
    case_group: dict[str, str] = {}
    ie_paras: dict[str, list] = {}
    seen_ie = set()
    current_case = None
    current_group = None
    for item in raw:
        if item.get("type") == "title":
            t = re.sub(r"<[^>]+>", "", str(item.get("title", ""))).strip()
            if item.get("level") == 2 and str(item.get("ref", "")).startswith("IE"):
                current_group = t
            elif re.match(r"사례\s*\d", t):
                current_case = item["documentId"]
                case_titles.setdefault(current_case, t)
                if current_case not in case_group and current_group:
                    case_group[current_case] = current_group
            continue
        pn = str(item.get("paraNum", ""))
        if (
            item.get("type") == "paragraph"
            and pn.startswith("IE")
            and item["uniqueKey"] not in seen_ie
            and current_case
        ):
            seen_ie.add(item["uniqueKey"])
            ie_paras.setdefault(current_case, []).append(item.get("fullContent", ""))
    st = new_stats()
    for doc_id, title in case_titles.items():
        refs: set[str] = set()
        for text in ie_paras.get(doc_id, []):
            refs.update(extract_refs(text, para_keys, st))
        g = group_map.get(case_group.get(doc_id, ""), {})
        result["ie"].append(
            {
                "id": doc_id,
                "title": title,
                "paras": sorted(refs, key=lambda p: para_keys[p][1]),
                "group": case_group.get(doc_id, ""),
                "concept": g.get("concept", ""),
                "concept_title": g.get("concept_title", ""),
            }
        )
    meta_stats["ie"] = st
    no_concept = [c["title"] for c in result["ie"] if not c["concept"]]
    print(
        f"IE 사례→개념: {len(result['ie']) - len(no_concept)}/{len(result['ie'])} 보유, 미보유 {len(no_concept)}건 {no_concept or ''}"
    )

    # ── 항등식·커버리지 출력 ────────────────────────────────────────
    # QNA·감리: 감사본 토큰 회계 (토큰 = 채택 + 형식제외, 제외분 전건 목록)
    for src in ("qna", "findings"):
        st = meta_stats[src]
        ok = st["tokens"] == st["adopted"] + len(st["excluded"])
        print(
            f"{src} 감사본 토큰: {st['tokens']} = 채택 {st['adopted']} + 제외 {len(st['excluded'])} {'✅' if ok else '❌'}"
        )
        if st["excluded"]:
            print(f"  제외(비1115 표기 또는 세부항목 중복): {st['excluded']}")
    # IE: 원문 참조 항등식 (감사 필드 없음 → 정규식 추출 유지)
    st = meta_stats["ie"]
    ok = st["mentions"] == st["resolved"] + st["external"] + st["unresolved"]
    print(
        f"ie 항등식: 언급 {st['mentions']} = 해소 {st['resolved']} + 외부 {st['external']} + 미해소 {st['unresolved']} {'✅' if ok else '❌'}"
    )
    if st["unresolved_raw"]:
        print(f"  ⚠️  미해소 토큰: {sorted(set(st['unresolved_raw']))}")
    # 분모는 하드코딩하지 않고 입력 데이터 행수에서 (모집단 = 권위 파일 전체)
    for src in ("qna", "findings", "ie"):
        total = len(result[src])
        linked = sum(1 for c in result[src] if c["paras"])
        zero = [c["id"] or c["title"] for c in result[src] if not c["paras"]]
        print(
            f"{src} 커버리지: {linked}/{total} 연결, 0건 사례 {len(zero)}개 {zero if zero else ''}"
        )

    edge_total = sum(len(c["paras"]) for src in result.values() for c in src)
    out = {
        "_meta": {
            "generated_by": "app/preprocessing/16-ontology-cases.py",
            "stats": {
                k: {kk: vv for kk, vv in v.items() if kk != "unresolved_raw"}
                for k, v in meta_stats.items()
            },
            "edge_total": edge_total,
        },
        **result,
    }
    OUTPUT_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"저장: {OUTPUT_PATH} (사례→문단 연결 {edge_total}개)")

    # ── ripple ─────────────────────────────────────────────────────
    fss = next(c for c in result["findings"] if c["id"] == "FSS-CASE-2022-2311-02")
    ok1 = {"9", "31"} <= set(fss["paras"])
    print(
        f"{'✅' if ok1 else '❌'} ripple 감리: FSS-2022-2311-02 → 9,31 포함 (실제 {fss['paras'][:6]}...)"
    )
    c45 = next((c for c in result["ie"] if c["title"].startswith("사례 45")), None)
    ok2 = c45 and any(p.startswith("B3") for p in c45["paras"])
    print(
        f"{'✅' if ok2 else '❌'} ripple IE: 사례 45 → B34~B38 계열 포함 (실제 {c45['paras'] if c45 else '없음'})"
    )
    # 사례→개념: 고아였던 38·39는 목차상 [표시], 22(반품권)는 [변동대가 추정치를 제약함]
    for want_title, want_concept in [
        ("사례 38", "표시"),
        ("사례 39", "표시"),
        ("사례 22", "변동대가 추정치를 제약함"),
    ]:
        c = next((x for x in result["ie"] if x["title"].startswith(want_title)), None)
        ok = c and c["concept_title"] == want_concept
        print(
            f"{'✅' if ok else '❌'} ripple 사례→개념: {want_title} → [{c['concept_title'] if c else '없음'}] (기대 [{want_concept}])"
        )


if __name__ == "__main__":
    main()

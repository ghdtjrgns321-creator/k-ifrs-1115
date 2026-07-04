"""온톨로지 BC 스포크: 결론도출근거 → 본문·개념·사례 연결

사용법:
  PYTHONPATH=. uv run python app/preprocessing/18-ontology-bc.py

Why: BC는 "규정을 왜 이렇게 만들었나"의 근거층. 간선 등록부(06-graph-audit.md §2)에
     사전 등록된 3종만 생성 —
     E-BC1 BC문단→본문문단(원문 인용, 항등식), E-BC2 BC그룹→개념(목차 괄호 표기),
     E-BC3 사례→BC(감사본 예약 활성화). 데이터는 문단 단위(DB 조회 정합),
     그래프 표시는 그룹 단위로 축약(05-bc.md에 명시).
"""

import json
import re
from pathlib import Path

SOURCE_PATH = Path("data/web/kifrs-1115-all.json")
CONCEPTS_PATH = Path("data/ontology/concepts.json")
QNA_PATH = Path("data/web/kifrs-1115-qna-chunks.json")
FINDINGS_PATH = Path("data/findings/findings-final.json")
OUTPUT_PATH = Path("data/ontology/bc_links.json")

_TOKEN = r"한?[BC]?[\d.]+[A-Z]?"
_RANGE = rf"{_TOKEN}(?:\s*[~∼]\s*{_TOKEN})?"
MENTION_RE = re.compile(rf"문단\s*({_RANGE})")
CONT_RE = re.compile(
    rf"^[⑴-⒇①-⑳\s]*(?:과|와|,|및|또는)\s*({_RANGE})(?![호년월일백천만억원개])"
)
_NAME_RE = re.compile(
    r"제(\d{4})호|IFRS\s*(\d+)|IAS\s*\d+|회계감사기준\s*\d+|감사기준서\s*\d+|개념체계"
)
# 규범 주제가 아닌 메타 그룹 — 개념 매핑 대상 아님 (05-bc.md에 사유 기록)
META_GROUPS = {
    "도입",
    "개요",
    "배경",
    "IFRS 15의 영향 분석",
    "결과적인 개정",
    "IFRS 최초채택기업의 경과 규정",
    "2011년 공개초안과 달라진 주요 내용 요약",
}


def parse_num(token: str):
    m = re.match(r"^(한)?(B|C)?([\d.]+)([A-Z]?)$", token.strip())
    if not m:
        return None
    try:
        num = float(m.group(3)) + (0.01 * (ord(m.group(4)) - 64) if m.group(4) else 0)
    except ValueError:
        return None
    return ({"B": 1, "C": 2}.get(m.group(2), 0), num)


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


def is_external(text: str, pos: int) -> bool:
    """가장 최근에 명명된 기준서가 1115(=IFRS 15)가 아니면 외부 (16과 동일 규칙).
    BC는 IAS 18·IFRS 3 등 타기준 논의가 잦아 이 규칙이 특히 중요."""
    last = None
    for m in _NAME_RE.finditer(text, 0, pos):
        last = m
    if last is None:
        return False
    return not (last.group(1) == "1115" or last.group(2) == "15")


def main():
    raw = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    cj = json.loads(CONCEPTS_PATH.read_text(encoding="utf-8"))
    concepts = cj["concepts"]

    # 본문·부록 문단 키 (E-BC1 해소 대상)
    para_keys = {}
    for item in raw:
        if item.get("type") == "paragraph" and item.get("sectionTitle") in (
            "본문",
            "부록 B 적용지침",
        ):
            pn = item.get("paraNum", "")
            if pn and pn not in para_keys and (k := parse_num(pn)):
                para_keys[pn] = k

    # ── 모집단: BC 문단 수집 + 그룹 귀속 (문서 순서, IE와 동일 원리) ──
    bc_groups: list[dict] = []
    bc_paras: dict[str, dict] = {}  # paraNum → {group, text}
    extras: dict[str, int] = {}  # BC 네임스페이스 밖(DO·한DO·웩 등) 제외 집계
    seen = set()
    in_bc = False
    current_group = None
    annotated: list[dict] = []  # 모든 레벨의 괄호표기 소제목 (깊은 것 우선 배정용)
    for item in raw:
        if item.get("type") == "title":
            t = re.sub(r"<[^>]+>", "", str(item.get("title", ""))).strip()
            if "결론도출근거" in t:
                in_bc = True
            if in_bc and item.get("level") == 2:
                current_group = t
                if not any(g["group"] == t for g in bc_groups):
                    bc_groups.append({"group": t, "ref": str(item.get("ref", ""))})
            # 괄호표기 보유 소제목 수집 (level 무관): "계약변경(문단 18~21) (ref BC76~BC83)"
            if in_bc:
                ma = re.search(r"\(문단\s*([^)]+)\)", t)
                mr = re.match(
                    r"^BC(\d+)[A-Z]?(?:[~∼]\s*BC(\d+)[A-Z]?)?", str(item.get("ref", ""))
                )
                if ma and mr:
                    annotated.append(
                        {
                            "title": t,
                            "level": item.get("level"),
                            "lo": int(mr.group(1)),
                            "hi": int(mr.group(2) or mr.group(1)),
                            "anno": ma.group(1).strip(),
                        }
                    )
            continue
        if not in_bc:
            continue
        pn = str(item.get("paraNum", ""))
        if item.get("type") != "paragraph" or item["uniqueKey"] in seen:
            continue
        seen.add(item["uniqueKey"])
        if re.match(r"^BC\d", pn):
            bc_paras.setdefault(
                pn,
                {
                    "group": current_group or "(서두)",
                    "text": item.get("fullContent", ""),
                },
            )
        elif pn:
            extras[pn] = extras.get(pn, 0) + 1
    unassigned = [p for p, v in bc_paras.items() if v["group"] == "(서두)"]
    print(
        f"모집단: BC 문단 {len(bc_paras)}개 (기대 652) / 그룹 {len(bc_groups)}개 / 그룹 미귀속 {len(unassigned)}건 {unassigned[:5]}"
    )
    print(
        f"BC 네임스페이스 밖 제외: {len(extras)}건 (DO·한DO·웩 등 소수의견/서두 메타) {sorted(extras)[:8]}"
    )

    # ── E-BC2: 그룹→개념 — ①괄호 표기(문단 X~Y) 범위 → 최소 포함 개념 ②메타 제외 ──
    def covering_concept(rng: str):
        targets = set(resolve_range(rng, para_keys))
        if not targets:
            return None
        best, best_size = None, 10**9
        for cid in concepts:
            sub = set()
            stack = [cid]
            while stack:
                cur = stack.pop()
                sub.update(concepts[cur]["paras"])
                stack.extend(concepts[cur]["children"])
            if targets <= sub and len(sub) < best_size:
                best, best_size = cid, len(sub)
        return best

    # 사용자 검수 확정 (2026-07-04): 그룹명이 내용보다 좁은 2건은 미연결(정밀 연결은
    # 깊은 괄호표기·E-BC1이 담당), 어미 차이 1건은 승인
    REVIEWED = {
        "적용범위": None,  # 내용 대부분이 계약 정의·식별 심의 → 그룹 매핑 없음
        "수행의무의 식별": "수행의무를 식별함",  # 승인
        "손실부담 수행의무": None,  # 최종 기준서에서 제외된 주제 — 대응 개념 없음
    }
    t2id = {v["title"]: k for k, v in concepts.items()}

    # BC 문단별 개념 배정: 괄호표기 소제목 중 '가장 깊은 레벨'이 우선
    # Why: level-2 "계약의 식별(문단 9~16)" 안에 level-3 "계약변경(문단 18~21)"이
    #      있음 — 감사에서 그룹 단위 매핑이 내용과 어긋난 원인. 깊은 표기가 정답.
    annotated.sort(key=lambda a: a["level"])  # 얕은 것 먼저 → 깊은 것이 덮어씀
    anno_cache = {a["title"]: covering_concept(a["anno"]) for a in annotated}
    bc_to_concept: dict[str, dict] = {}
    for a in annotated:
        cid = anno_cache[a["title"]]
        if not cid:
            continue
        for pn in bc_paras:
            m = re.match(r"^BC(\d+)", pn)
            if m and a["lo"] <= int(m.group(1)) <= a["hi"]:
                bc_to_concept[pn] = {
                    "concept": cid,
                    "via": a["title"],
                    "level": a["level"],
                }
    # 괄호표기 없는 구간: 그룹 폴백 (승인된 제목매칭만, 미연결·메타는 제외)
    for g in bc_groups:
        base = re.sub(r"\(문단[^)]*\)", "", g["group"]).strip()
        if base in REVIEWED:
            cid = t2id.get(REVIEWED[base]) if REVIEWED[base] else None
            g["concept"], g["method"] = (
                cid,
                ("제목매칭(사용자 승인)" if cid else "미연결(사용자 확정)"),
            )
        elif base in META_GROUPS or "소수의견" in base:
            g["concept"], g["method"] = None, "메타(제외)"
        else:
            m = re.search(r"\(문단\s*([^)]+)\)", g["group"])
            g["concept"] = covering_concept(m.group(1).strip()) if m else None
            g["method"] = "괄호표기(기계)" if g["concept"] else "검토 필요"
        g["concept_title"] = (
            concepts[g["concept"]]["title"] if g.get("concept") else None
        )
        if g["concept"]:
            for pn, v in bc_paras.items():
                if v["group"] == g["group"] and pn not in bc_to_concept:
                    bc_to_concept[pn] = {
                        "concept": g["concept"],
                        "via": g["group"],
                        "level": 2,
                    }
    n_cov = len(bc_to_concept)
    depth = sum(1 for v in bc_to_concept.values() if v["level"] >= 3)
    print(
        f"E-BC2 문단→개념 배정: {n_cov}/{len(bc_paras)} (깊은 괄호표기 우선 {depth}건 + 그룹 폴백 {n_cov - depth}건)"
    )
    print(f"  미배정 {len(bc_paras) - n_cov}건 = 메타·미연결 그룹 소속 (사유 기록)")
    # 그룹→개념 대표 간선 (그래프용): 그룹 내 배정 개념의 고유 집합
    for g in bc_groups:
        members = [pn for pn, v in bc_paras.items() if v["group"] == g["group"]]
        g["concepts_within"] = sorted(
            {bc_to_concept[pn]["concept"] for pn in members if pn in bc_to_concept}
        )
        mark = {
            "괄호표기(기계)": "=",
            "메타(제외)": "·",
            "제목매칭(사용자 승인)": "✔",
            "미연결(사용자 확정)": "×",
            "검토 필요": "?",
        }[g["method"]]
        names = [concepts[c]["title"][:12] for c in g["concepts_within"][:4]]
        print(
            f"  {mark} {g['group'][:40]} → 그룹 내 개념 {len(g['concepts_within'])}종 {names}"
        )

    # ── E-BC1: BC 문단 → 본문 문단 (원문 인용, 항등식) ──────────────
    e_bc1 = {}
    st = {
        "mentions": 0,
        "resolved": 0,
        "external": 0,
        "unresolved": 0,
        "unresolved_raw": [],
    }
    for pn, v in bc_paras.items():
        found = set()
        text = v["text"]
        for m in MENTION_RE.finditer(text):
            tokens = [m.group(1)]
            tail = text[m.end() :]
            while cm := CONT_RE.match(tail):
                tokens.append(cm.group(1))
                tail = tail[cm.end() :]
            for tk in tokens:
                st["mentions"] += 1
                if is_external(text, m.start()):
                    st["external"] += 1
                    continue
                targets = resolve_range(tk, para_keys)
                if targets:
                    st["resolved"] += 1
                    found.update(targets)
                else:
                    st["unresolved"] += 1
                    st["unresolved_raw"].append(tk)
        if found:
            e_bc1[pn] = sorted(found, key=lambda p: para_keys[p][1])
    ok = st["mentions"] == st["resolved"] + st["external"] + st["unresolved"]
    print(
        f"E-BC1 항등식: 언급 {st['mentions']} = 해소 {st['resolved']} + 외부 {st['external']} + 미해소 {st['unresolved']} {'✅' if ok else '❌'}"
    )
    if st["unresolved_raw"]:
        print(
            f"  미해소 토큰(각주 병합 등, 간선 미생성): {sorted(set(st['unresolved_raw']))[:15]}"
        )
    # 역인덱스: 본문 문단 → BC 목록 (STEP 5 조회용)
    para_to_bc = {}
    for bc, paras in e_bc1.items():
        for p in paras:
            para_to_bc.setdefault(p, []).append(bc)
    print(
        f"E-BC1: 인용 보유 BC {len(e_bc1)}/{len(bc_paras)} → 본문 역인덱스 {len(para_to_bc)}개 문단"
    )

    # ── E-BC3: 사례 → BC (감사본 예약 활성화) ───────────────────────
    e_bc3, missing = [], []
    for path, prefix in [(QNA_PATH, "QNA-"), (FINDINGS_PATH, "")]:
        for item in json.loads(path.read_text(encoding="utf-8")):
            md = item.get("metadata", {})
            for p in md.get("related_paragraphs", []):
                np_ = re.sub(r"[^0-9A-Z한.].*$", "", str(p).strip())
                if re.match(r"^BC\d", np_):
                    row = {"case": prefix + md.get("paraNum", ""), "bc": np_}
                    (e_bc3 if np_ in bc_paras else missing).append(row)
    print(
        f"E-BC3 예약 활성화: {len(e_bc3)}건 + 대상 BC 부재 {len(missing)}건 {missing or ''} (합 = 감사본 BC 토큰 전수)"
    )

    out = {
        "_meta": {
            "generated_by": "app/preprocessing/18-ontology-bc.py",
            "bc_paras": len(bc_paras),
            "groups": len(bc_groups),
            "e_bc1": st | {"unresolved_raw": sorted(set(st["unresolved_raw"]))},
            "e_bc3": {"activated": len(e_bc3), "missing": len(missing)},
        },
        "groups": bc_groups,
        "bc_to_concept": bc_to_concept,
        "bc_group_of": {pn: v["group"] for pn, v in bc_paras.items()},
        "e_bc1_bc_to_para": e_bc1,
        "para_to_bc": {p: sorted(v) for p, v in para_to_bc.items()},
        "e_bc3_case_to_bc": e_bc3,
    }
    OUTPUT_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"저장: {OUTPUT_PATH}")

    # ── ripple ──────────────────────────────────────────────────────
    g1 = next((g for g in bc_groups if g["group"].startswith("계약의 식별")), None)
    ok1 = g1 and g1.get("concept_title") == "계약을 식별함"
    print(
        f"{'✅' if ok1 else '❌'} ripple E-BC2: '계약의 식별(문단 9~16)' → [{g1.get('concept_title') if g1 else '없음'}]"
    )
    ok2 = any(r["case"] == "QNA-202003D" and r["bc"] == "BC307" for r in e_bc3)
    print(f"{'✅' if ok2 else '❌'} ripple E-BC3: QNA-202003D → BC307 활성화")


if __name__ == "__main__":
    main()

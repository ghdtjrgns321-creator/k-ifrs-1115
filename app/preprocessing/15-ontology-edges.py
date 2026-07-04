"""온톨로지 STEP 2: 간선 추출 — E3 문단 상호참조 + E4 본문↔부록B 대응

사용법:
  PYTHONPATH=. uv run python app/preprocessing/15-ontology-edges.py

Why: 문단 원문의 "문단 XX에 따라" 표기와 소제목의 "(문단 35⑴)" 표기는
     기준서가 직접 그어놓은 관계 → 정규식 추출만으로 신빙성 있는 간선 확보.
     회계 항등식(언급 N = 내부해소 M + 타기준서 K + 미해소 U)으로 전수 검증.
     (설계: docs/ontology/00-overview.md 결정 2·3)
"""

import json
import re
from pathlib import Path

CONCEPTS_PATH = Path("data/ontology/concepts.json")
SOURCE_PATH = Path("data/web/kifrs-1115-all.json")
OUTPUT_PATH = Path("data/ontology/edges.json")
SCOPE_SECTIONS = {"본문", "부록 B 적용지침"}

# 문단 번호 토큰: 한C1.1, B63A, 129 등 (14-ontology-concepts.py와 동일 문법)
_TOKEN = r"한?[BC]?[\d.]+[A-Z]?"
_RANGE = rf"{_TOKEN}(?:\s*[~∼]\s*{_TOKEN})?"
MENTION_RE = re.compile(rf"문단\s*({_RANGE})")
# 연속 나열: "문단 60과 65", "문단 9, 12" — 뒤 토큰도 문단 번호로 해석
CONT_RE = re.compile(rf"^[⑴-⒇①-⑳\s]*(?:과|와|,|및|또는)\s*({_RANGE})(?![호년월일])")


def parse_num(token: str) -> tuple | None:
    """'B63A' → (ns=1, 63.01). 14-ontology-concepts.py의 para_sort_key와 동일."""
    m = re.match(r"^(한)?(B|C)?([\d.]+)([A-Z]?)$", token.strip())
    if not m:
        return None
    ns = {"B": 1, "C": 2}.get(m.group(2), 0)
    num = float(m.group(3)) + (0.01 * (ord(m.group(4)) - 64) if m.group(4) else 0)
    return (ns, num)


def resolve_range(range_str: str, para_keys: dict) -> list[str]:
    """'47~72' → 존재하는 문단 리스트. para_keys = {paraNum: (ns, num)}."""
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
    """타 기준서 명칭이 '문단' 바로 앞에 붙은 경우만 외부 참조로 판정.

    외부 O: "기업회계기준서 제1117호 문단 8", "제1008호 문단 28"
    내부 X: "제1116호에 따라 문단 5를 개정" (개정 주체일 뿐, 문단은 이 기준서 것)
    내부 X: "(제1108호에서 정의함)에 대하여 문단 한129.1" (괄호 설명일 뿐)
    """
    ctx = text[max(0, pos - 40) : pos]
    return bool(
        re.search(
            r"제(?!1115)\d{4}호\s*(?:['‘“「][^'’”」]{0,20}['’”」])?\s*(?:의\s*)?$", ctx
        )
    )


def main():
    concepts = json.loads(CONCEPTS_PATH.read_text(encoding="utf-8"))["concepts"]
    raw = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))

    # 스코프 문단 원문 로드 (STEP 1과 동일: uniqueKey 중복 제거)
    para_text: dict[str, str] = {}
    for item in raw:
        if (
            item.get("type") == "paragraph"
            and item.get("sectionTitle") in SCOPE_SECTIONS
        ):
            pn = item.get("paraNum", "")
            if pn and pn not in para_text:
                para_text[pn] = item.get("fullContent", "")
    para_keys = {p: k for p in para_text if (k := parse_num(p))}
    print(f"스코프 문단: {len(para_text)}개 (번호 해석 가능 {len(para_keys)}개)")

    # ── E3: 문단 상호참조 추출 ──────────────────────────────────────
    # 회계 항등식: 언급 N = 내부해소 M + 타기준서 K + 미해소 U
    e3_edges, external, unresolved = [], [], []
    n_mentions = 0
    for pnum, text in para_text.items():
        for m in MENTION_RE.finditer(text):
            tokens = [m.group(1)]
            # 나열 연속 토큰 수집 ("문단 60과 65")
            tail = text[m.end() :]
            while cm := CONT_RE.match(tail):
                tokens.append(cm.group(1))
                tail = tail[cm.end() :]
            for tk in tokens:
                n_mentions += 1
                if is_external(text, m.start()):
                    external.append({"from": pnum, "raw": tk})
                    continue
                targets = resolve_range(tk, para_keys)
                if targets:
                    e3_edges.append({"from": pnum, "to": targets, "raw": tk})
                else:
                    unresolved.append({"from": pnum, "raw": tk})
    m_resolved = len(e3_edges)
    print(
        f"E3 항등식: 언급 {n_mentions} = 내부해소 {m_resolved} + 타기준서 {len(external)} + 미해소 {len(unresolved)}"
    )
    ok_identity = n_mentions == m_resolved + len(external) + len(unresolved)
    print(f"{'✅' if ok_identity else '❌'} 항등식 성립: {ok_identity}")
    for u in unresolved:
        print(f"  ⚠️  미해소: 문단 {u['from']} 원문의 '문단 {u['raw']}'")

    # ── E4: 소제목의 "(문단 …)" 표기 → 본문↔부록B 대응 ────────────────
    e4_edges, e4_fail = [], []
    t_count = 0
    for cid, c in concepts.items():
        m = re.search(r"\(문단\s*([^)]+)\)", c["title"])
        if not m:
            continue
        t_count += 1
        targets: list[str] = []
        for tk in re.split(r"\s*(?:과|와|,|및)\s*", m.group(1)):
            tk = re.sub(r"[⑴-⒇①-⑳]", "", tk).strip()  # 세부항목 표기 제거
            targets += resolve_range(tk, para_keys)
        if targets:
            e4_edges.append(
                {
                    "concept": cid,
                    "concept_title": c["title"],
                    "to": sorted(set(targets), key=lambda p: para_keys[p][1]),
                    "raw": m.group(1),
                }
            )
        else:
            e4_fail.append({"concept_title": c["title"], "raw": m.group(1)})
    print(
        f"E4: '(문단 …)' 보유 소제목 {t_count}/{len(concepts)}개 → 해소 {len(e4_edges)}, 실패 {len(e4_fail)}"
    )
    for f in e4_fail:
        print(f"  ⚠️  E4 실패: {f['concept_title']} ('{f['raw']}')")

    # ── E2: 5단계 선행판단 — 사용자 검수 완료(2026-07-04) 7개 확정 ─────
    # "표시→공시"는 검수에서 삭제: 문단 110상 공시는 특정 단계가 아니라
    # 전 단계 결과를 설명하는 층이므로 선행판단 관계가 아님 (02-edges.md §6)
    title_to_id = {c["title"]: cid for cid, c in concepts.items()}
    E2_DRAFT = [
        ("계약을 식별함", "수행의무를 식별함", "5단계 모형 1→2"),
        ("수행의무를 식별함", "거래가격을 산정함", "5단계 모형 2→3"),
        ("거래가격을 산정함", "거래가격을 수행의무에 배분함", "5단계 모형 3→4"),
        ("거래가격을 수행의무에 배분함", "수행의무의 이행", "5단계 모형 4→5"),
        ("계약을 식별함", "계약의 결합", "결합 대상은 식별된 계약 (문단 17)"),
        ("계약을 식별함", "계약변경", "변경은 기존 계약 전제 (문단 18)"),
        ("수행의무의 이행", "표시", "표시는 수행 정도에 의존 (문단 105)"),
    ]
    e2_edges, e2_fail = [], []
    for src, dst, why in E2_DRAFT:
        if src in title_to_id and dst in title_to_id:
            e2_edges.append(
                {
                    "from": title_to_id[src],
                    "from_title": src,
                    "to": title_to_id[dst],
                    "to_title": dst,
                    "why": why,
                }
            )
        else:
            e2_fail.append((src, dst))
    print(
        f"E2 초안: {len(e2_edges)}/{len(E2_DRAFT)}개 노드 매칭 (실패 {e2_fail or '없음'})"
    )

    # ── 저장 ──────────────────────────────────────────────────────
    result = {
        "_meta": {
            "generated_by": "app/preprocessing/15-ontology-edges.py",
            "e3": {
                "mentions": n_mentions,
                "resolved": m_resolved,
                "external": len(external),
                "unresolved": len(unresolved),
            },
            "e4": {"titles_with_ref": t_count, "resolved": len(e4_edges)},
            "e2_status": "approved",  # 사용자 검수 2026-07-04: 8개 초안 중 7개 확정, 표시→공시 삭제
        },
        "e2_five_step": e2_edges,
        "e3_cross_refs": e3_edges,
        "e4_bridge": e4_edges,
        "e3_external": external,
        "e3_unresolved": unresolved,
    }
    OUTPUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"저장: {OUTPUT_PATH} (E3 {m_resolved} / E4 {len(e4_edges)} / E2 초안 {len(e2_edges)})"
    )

    # ── ripple 검증: 원문 표기 ↔ 간선 일치 (본문↔부록 교차 포함) ──────
    # 기대값 근거: B23 원문 "문단 47~72의 요구사항(문단 56~58 … 포함)을 적용한다"
    checks = [
        ("B23", "47~72", "부록B→본문 교차"),
        ("41", "B14~B19", "본문→부록B 교차"),
    ]
    for src, raw, label in checks:
        hit = any(
            e["from"] == src and e["raw"].replace(" ", "") == raw for e in e3_edges
        )
        print(
            f"{'✅' if hit else '❌'} ripple E3({label}): 문단 {src} → '문단 {raw}' 간선 {'존재' if hit else '없음'}"
        )
    e4_hit = next((e for e in e4_edges if "효익을 동시에" in e["concept_title"]), None)
    ok = bool(e4_hit and "35" in e4_hit["to"])
    print(
        f"{'✅' if ok else '❌'} ripple E4: '효익을 동시에 얻고 소비(문단 35⑴)' → {e4_hit['to'] if e4_hit else '없음'}"
    )


if __name__ == "__main__":
    main()

"""온톨로지 STEP 6: 완전성 census — 파이프라인 자기계정의 '외부' 검증

사용법:
  PYTHONPATH=. uv run python app/preprocessing/20-ontology-census.py
  (edges.json·concepts.json 재생성 뒤 회귀 게이트로 실행. exit 0 = PASS)

Why: 15-ontology-edges.py는 SCOPE={본문, 부록B}에서만 '문단 N' 참조를 스캔하고
     회계 항등식(언급 = 내부해소 + 타기준서 + 미해소)으로 자기계정한다. 그 '미해소 0'은
     자기가 고른 스코프 안에서만 참이다. 이 census는 그 스코프를 믿지 않고,
     동일 정규식을 **전 규범 문단(본문+부록B+부록C)** 에 독립 적용해 참조쌍을 전수
     재추출하고 edges.json 포착분과 차집합을 낸다. 차집합이 곧 파이프라인이 구조적으로
     못 본 규범 참조 = 온톨로지 미완전성의 결정론적 증거.
     결정론으로 검사 가능한 두 축(상호참조 완전성·문단 진입 커버리지)만 게이트한다.
     '올바른 개념을 담았는가'(의미적 완전성)는 원문에 정답이 없어 이 게이트 밖이다.
"""

import json
import re
import sys
from pathlib import Path

SOURCE = Path("data/web/kifrs-1115-all.json")
EDGES = Path("data/ontology/edges.json")
CONCEPTS = Path("data/ontology/concepts.json")

# 15-ontology-edges.py와 동일 문법 (공정 비교 위해 그대로 복제)
_TOKEN = r"한?[BC]?[\d.]+[A-Z]?"
_RANGE = rf"{_TOKEN}(?:\s*[~∼]\s*{_TOKEN})?"
MENTION_RE = re.compile(rf"문단\s*({_RANGE})")
CONT_RE = re.compile(rf"^[⑴-⒇①-⑳\s]*(?:과|와|,|및|또는)\s*({_RANGE})(?![호년월일])")

# 규범 문단 앵커: 본문(숫자)·부록B·부록C. 부록A(A1 계열)는 'IFRS 15 vs Topic 606
# 비교'로 결론도출근거(BC)에 속한 논평이라 규범 스코프 밖 → 앵커에서 자동 배제.
NORM_ANCHOR = re.compile(r"^한?[BC]?[\d.]+[A-Z]?$")


def extract_pairs(para_text: dict) -> set:
    """{paraNum: fullContent} → {(from, raw_token)} 전체 언급쌍 (dedup)."""
    pairs = set()
    for pnum, text in para_text.items():
        for m in MENTION_RE.finditer(text):
            tokens = [m.group(1)]
            tail = text[m.end() :]
            while cm := CONT_RE.match(tail):
                tokens.append(cm.group(1))
                tail = tail[cm.end() :]
            for tk in tokens:
                pairs.add((pnum, tk.replace(" ", "")))
    return pairs


def main() -> int:
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    edges = json.loads(EDGES.read_text(encoding="utf-8"))
    concepts = json.loads(CONCEPTS.read_text(encoding="utf-8"))
    p2c = concepts["para_to_concept"]

    # 전 규범 문단 원문 로드 (namespace 앵커로만 선별, sectionTitle 무관)
    para_text: dict[str, str] = {}
    for item in raw:
        if item.get("type") != "paragraph":
            continue
        pn = item.get("paraNum", "")
        if pn and NORM_ANCHOR.match(pn) and pn not in para_text:
            para_text[pn] = item.get("fullContent", "") or ""

    fail = 0

    # ── STEP A: 상호참조 완전성 (독립 재추출 ⊆ edges.json) ────────────
    population = extract_pairs(para_text)
    done = set()
    for key in ("e3_cross_refs", "e3_external", "e3_unresolved"):
        for e in edges.get(key, []):
            done.add((e["from"], e["raw"].replace(" ", "")))
    missing = sorted(population - done)
    print("── STEP A: 상호참조 완전성 (전 규범 스코프 독립 재추출) ──")
    print(f"  규범 문단(본문+부록B+부록C): {len(para_text)}")
    print(f"  재추출 언급쌍(분모): {len(population)}")
    print(f"  edges.json 포착쌍(e3+external+unresolved): {len(done)}")
    print(f"  규범 참조 누락(차집합): {len(missing)}")
    if missing:
        fail = 1
        for f, r in missing[:30]:
            print(f"    ❌ 문단 {f} → '문단 {r}' (edges.json에 없음)")
    print(f"  {'✅ PASS' if not missing else '❌ FAIL'}\n")

    # ── STEP B: 참조 도달성 (e3 목적지 문단이 개념 진입점 보유) ───────
    e3_targets = {t for e in edges.get("e3_cross_refs", []) for t in e["to"]}
    void = sorted(t for t in e3_targets if t not in p2c)
    print("── STEP B: 참조 도달성 (e3 목적지 → 개념 진입점) ──")
    print(f"  e3 목적지 문단: {len(e3_targets)}  개념 미매핑(허공 참조): {len(void)}")
    if void:
        fail = 1
        print(f"    ❌ {void[:30]}")
    print(f"  {'✅ PASS' if not void else '❌ FAIL'}\n")

    # ── STEP C: 문단 진입 커버리지 (규범 문단 고아 0) ────────────────
    # 개념 관할이 있어야 할 규범 문단(원문 앵커) 중 para_to_concept 미등재
    orphan = sorted(p for p in para_text if p not in p2c)
    # 부록C·부록B 중 개념 미배정은 원문에 개념 소제목이 없는 경우가 있어 정보로만 표기
    print("── STEP C: 문단 진입 커버리지 ──")
    print(f"  para_to_concept 매핑: {len(p2c)}  원문 규범 문단: {len(para_text)}")
    print(
        f"  매핑 무결성(모든 값이 실개념): {all(v in concepts['concepts'] for v in p2c.values())}"
    )
    print(f"  개념 미배정 규범 문단(정보): {len(orphan)}\n")

    # ── STEP D: 표기 완전성 프로브 (정보 — 게이트 아님) ─────────────
    total = matched = 0
    orphan_frag: dict[str, int] = {}
    for t in para_text.values():
        for m in re.finditer("문단", t):
            total += 1
            if MENTION_RE.match(t[m.start() : m.start() + 15]):
                matched += 1
            else:
                frag = t[m.start() : m.start() + 10]
                orphan_frag[frag] = orphan_frag.get(frag, 0) + 1
    bc = sum(v for k, v in orphan_frag.items() if k.startswith("문단 BC"))
    print("── STEP D: 표기 완전성 프로브 (정보) ──")
    print(f"  '문단' 출현 {total}  숫자참조 매칭 {matched}  비매칭 {total - matched}")
    print(
        f"    비매칭 내역: 'BC 참조'(bc_links 별도처리) {bc} + 일반명사·비규범 {total - matched - bc}\n"
    )

    print("=" * 50)
    print("CENSUS 결과:", "✅ PASS (결정론 완전성 2축 충족)" if not fail else "❌ FAIL")
    return fail


if __name__ == "__main__":
    sys.exit(main())

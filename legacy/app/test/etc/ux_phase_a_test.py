"""
app/test/ux-phase-a-test.py
UX Phase A 개선 검증 테스트

레이어 1 (DB 불필요, 즉시 실행):
  - _normalize_query()  : 특수문자 정규화 단위 테스트
  - _parse_chunk_num()  : 섹션 prefix 파싱 단위 테스트
  - INVERTED_MAPPING    : 역매핑 빌드 검증

레이어 2 (MongoDB 연결 필요):
  - run_search() QUERY_MAPPING hit  : 칩 클릭 → exact match 경로
  - run_search() free text miss     : 자유 입력 → LLM 분기 경로
  - _apply_window_boost() 효과      : 인접 청크 클러스터 부스팅 확인

실행 방법:
  PYTHONPATH=. uv run --env-file .env app/test/ux-phase-a-test.py
  PYTHONPATH=. uv run --env-file .env app/test/ux-phase-a-test.py --skip-db  # DB 없이 레이어1만
"""

import sys
import argparse

sys.stdout.reconfigure(encoding="utf-8")

PASS = "[PASS]"
FAIL = "[FAIL]"


# ═══════════════════════════════════════════════════════════════════════════════
# 레이어 1: 단위 테스트 (DB 불필요)
# ═══════════════════════════════════════════════════════════════════════════════

def test_normalize_query():
    """_normalize_query 5단계 정규화 검증."""
    from app.services.search_service import _normalize_query

    cases = [
        # (입력, 기대 출력, 설명)
        ("수익인식(Revenue Recognition)·시기",  "수익인식 시기",    "괄호영문 + 가운뎃점 제거"),
        ("통제-\n이전",                          "통제 이전",        "하이픈 줄바꿈 제거"),
        ("  반품  권  ",                         "반품 권",          "앞뒤 strip + 연속공백 단일화"),
        ("변동  대가   제약",                    "변동 대가 제약",   "연속 공백 단일화"),
        ("라이선스(License)—기간",              "라이선스 기간",    "em-dash + 괄호영문"),
        ("계약변경",                             "계약변경",         "정상 키워드 — 변형 없음"),
    ]

    print("\n[레이어 1-A] _normalize_query 단위 테스트")
    all_pass = True
    for raw, expected, desc in cases:
        result = _normalize_query(raw)
        ok = result == expected
        if not ok:
            all_pass = False
        mark = PASS if ok else FAIL
        print(f"  {mark} {desc}")
        if not ok:
            print(f"         입력:   '{raw}'")
            print(f"         기대:   '{expected}'")
            print(f"         실제:   '{result}'")

    return all_pass


def test_parse_chunk_num():
    """_parse_chunk_num 섹션 prefix 파싱 검증 — 핵심 edge case 포함."""
    from app.retriever import _parse_chunk_num

    cases = [
        # (chunk_id, 기대_prefix, 기대_num, 설명)
        ("1115-31",   "1115-",   31,  "본문 — prefix 빈 알파벳"),
        ("1115-B44",  "1115-B",  44,  "적용지침B — 1글자"),
        ("1115-A2",   "1115-A",  2,   "용어정의A — 1글자"),
        ("1115-C3",   "1115-C",  3,   "시행일C — 1글자"),
        ("1115-IE65", "1115-IE", 65,  "적용사례IE — 2글자"),
        ("1115-BC44", "1115-BC", 44,  "결론도출근거BC — 2글자"),
    ]

    # 교차 오염 방지: 다른 prefix끼리 절대 같은 클러스터가 되면 안 됨
    cross_cases = [
        ("1115-B44",  "1115-BC44",  "B vs BC — prefix 불일치 → 클러스터 분리 필수"),
        ("1115-31",   "1115-B31",   "본문31 vs 적용지침B31 — 번호 같아도 분리"),
        ("1115-IE44", "1115-BC44",  "IE vs BC — 번호 같아도 분리"),
    ]

    print("\n[레이어 1-B] _parse_chunk_num 단위 테스트")
    all_pass = True

    for chunk_id, exp_prefix, exp_num, desc in cases:
        result = _parse_chunk_num(chunk_id)
        ok = result == (exp_prefix, exp_num)
        if not ok:
            all_pass = False
        mark = PASS if ok else FAIL
        print(f"  {mark} {desc}: '{chunk_id}' → {result}")

    print("\n  [교차 오염 방지 — 다른 prefix는 반드시 다른 클러스터]")
    for id_a, id_b, desc in cross_cases:
        pa = _parse_chunk_num(id_a)
        pb = _parse_chunk_num(id_b)
        # 둘 다 파싱 성공하면 prefix가 달라야 함
        if pa and pb:
            ok = pa[0] != pb[0]
        else:
            ok = True  # 한쪽이 None이면 클러스터링 자체 안 됨 → 안전
        if not ok:
            all_pass = False
        mark = PASS if ok else FAIL
        print(f"  {mark} {desc}")
        if not ok:
            print(f"         '{id_a}' prefix={pa[0] if pa else None}")
            print(f"         '{id_b}' prefix={pb[0] if pb else None}")

    return all_pass


def test_inverted_mapping():
    """INVERTED_MAPPING 빌드 결과 기본 검증."""
    from app.services.query_mapping import QUERY_MAPPING, INVERTED_MAPPING

    print("\n[레이어 1-C] INVERTED_MAPPING 빌드 검증")
    all_pass = True

    # 1. 비어 있지 않아야 함
    ok1 = len(INVERTED_MAPPING) > 0
    print(f"  {PASS if ok1 else FAIL} 역매핑 항목 수: {len(INVERTED_MAPPING)}개")
    if not ok1:
        all_pass = False

    # 2. 알려진 공식 용어가 역매핑되는지 확인
    spot_checks = [
        ("반품권",      ["반품", "반품권", "반품조건부판매"]),   # 실무 용어 후보
        ("계약부채",    ["선수금", "선수수익", "계약부채"]),
        ("라이선스",    ["라이선스", "소프트웨어", "IP"]),
    ]
    for official_term, expected_contains in spot_checks:
        mapped = INVERTED_MAPPING.get(official_term, [])
        hits = [k for k in expected_contains if k in mapped]
        ok = len(hits) > 0
        if not ok:
            all_pass = False
        mark = PASS if ok else FAIL
        print(f"  {mark} '{official_term}' 역매핑 확인: {mapped[:5]}...")

    # 3. QUERY_MAPPING의 모든 value가 역매핑에 존재하는지 샘플 검사
    missing = []
    for practitioner, official_list in list(QUERY_MAPPING.items())[:20]:
        for term in official_list:
            if practitioner not in INVERTED_MAPPING.get(term, []):
                missing.append(f"{term} → {practitioner}")
    ok3 = len(missing) == 0
    if not ok3:
        all_pass = False
    mark = PASS if ok3 else FAIL
    print(f"  {mark} 역매핑 일관성 검사 (상위 20개 키): {'누락 없음' if ok3 else f'누락 {len(missing)}건'}")
    for m in missing[:3]:
        print(f"         누락: {m}")

    return all_pass


# ═══════════════════════════════════════════════════════════════════════════════
# 레이어 2: 통합 테스트 (MongoDB 연결 필요)
# ═══════════════════════════════════════════════════════════════════════════════

def test_run_search_hit():
    """QUERY_MAPPING exact match hit — LLM 호출 없이 공식 용어로 확장되어야 함."""
    from app.services.search_service import run_search
    from app.services.query_mapping import QUERY_MAPPING
    from app.services.session_store import SessionStore

    store = SessionStore()
    query = "상품권"   # QUERY_MAPPING에 있는 칩 버튼 키워드

    print(f"\n[레이어 2-A] QUERY_MAPPING hit 테스트 (query='{query}')")
    expected_terms = QUERY_MAPPING[query]
    print(f"  기대 확장 용어: {expected_terms}")

    result = run_search(query, "test-session-hit", store)

    # standalone_query가 공식 용어를 포함하는지 확인
    sq = result.standalone_query
    hit_count = sum(1 for t in expected_terms if t in sq)
    ok1 = hit_count >= len(expected_terms) * 0.5  # 50% 이상 포함
    print(f"  {PASS if ok1 else FAIL} standalone_query 용어 포함률: {hit_count}/{len(expected_terms)}")
    print(f"         standalone_query: '{sq}'")

    # 결과 수 확인
    ok2 = len(result.docs) > 0
    print(f"  {PASS if ok2 else FAIL} 검색 결과 수: {len(result.docs)}개")

    # 상위 3개 chunk_id 출력
    print("  상위 3개 결과:")
    for doc in result.docs[:3]:
        print(f"    [{doc.source}] {doc.chunk_id} | score={doc.score:.4f} | {doc.hierarchy[:40]}")

    return ok1 and ok2


def test_run_search_free_text():
    """자유 텍스트 입력 — LLM 분기 경로 또는 벡터 검색 fallback 동작 확인."""
    from app.services.search_service import run_search
    from app.services.session_store import SessionStore

    store = SessionStore()
    # QUERY_MAPPING에 없는 자유 입력 (LLM이 관련 키를 추출해야 함)
    query = "소프트웨어 도입하면서 초기 셋업비 한 번에 받았는데 기준서 어디 봐야 돼?"

    print(f"\n[레이어 2-B] 자유 텍스트 입력 테스트")
    print(f"  query: '{query}'")

    result = run_search(query, "test-session-free", store)

    # 결과가 있어야 함
    ok1 = len(result.docs) > 0
    print(f"  {PASS if ok1 else FAIL} 검색 결과 수: {len(result.docs)}개")
    print(f"  standalone_query: '{result.standalone_query}'")

    # '설치비' 또는 '환불되지 않는 선수금' 관련 키워드가 standalone_query에 있으면 LLM 성공
    llm_keywords = ["설치비", "환불되지 않는", "선수금", "소프트웨어", "구별되는"]
    hit = any(kw in result.standalone_query for kw in llm_keywords)
    mark = PASS if hit else "[INFO]"
    print(f"  {mark} LLM 키 추출 결과: {'성공 (관련 공식 용어 포함)' if hit else '미추출 (벡터 fallback으로 검색)'}")

    # 상위 5개 결과 출력
    print("  상위 5개 결과:")
    for doc in result.docs[:5]:
        print(f"    [{doc.source}] {doc.chunk_id} | score={doc.score:.4f} | {doc.hierarchy[:50]}")

    return ok1


def test_window_boost():
    """_apply_window_boost 효과 확인 — 인접 청크가 클러스터로 묶여 상위에 노출되는지."""
    from app.retriever import _parse_chunk_num, _apply_window_boost

    print("\n[레이어 2-C] _apply_window_boost in-memory 시뮬레이션")

    # 가상 fused dict: 1115-B44, 1115-B45, 1115-B46 (인접), 1115-31 (비인접 본문)
    fused = {
        "1115-B44": {"doc": {"chunk_id": "1115-B44", "weight_score": 1.2}, "rrf_score": 0.010, "vector_score": 0.9},
        "1115-B45": {"doc": {"chunk_id": "1115-B45", "weight_score": 1.2}, "rrf_score": 0.009, "vector_score": 0.85},
        "1115-B46": {"doc": {"chunk_id": "1115-B46", "weight_score": 1.2}, "rrf_score": 0.008, "vector_score": 0.8},
        "1115-31":  {"doc": {"chunk_id": "1115-31",  "weight_score": 1.15}, "rrf_score": 0.012, "vector_score": 0.95},
        "1115-IE65":{"doc": {"chunk_id": "1115-IE65","weight_score": 1.1}, "rrf_score": 0.007, "vector_score": 0.75},
    }

    before = {k: round(v["rrf_score"], 5) for k, v in fused.items()}
    _apply_window_boost(fused, window=3, boost=0.15)
    after = {k: round(v["rrf_score"], 5) for k, v in fused.items()}

    print("  chunk_id         before_rrf  after_rrf   delta")
    print("  " + "-" * 55)
    all_pass = True
    for cid in fused:
        delta = after[cid] - before[cid]
        print(f"  {cid:<16} {before[cid]:.5f}     {after[cid]:.5f}    +{delta:.5f}")

    # 검증: B44/B45/B46는 점수가 올라야 하고, 1115-31(본문)은 변함없어야 함
    b_boosted = all(after[f"1115-B{n}"] > before[f"1115-B{n}"] for n in [44, 45, 46])
    base_unchanged = after["1115-31"] == before["1115-31"]

    ok1 = b_boosted
    ok2 = base_unchanged
    print(f"\n  {PASS if ok1 else FAIL} B44/B45/B46 인접 클러스터 부스팅: {'모두 상승' if ok1 else '일부 미상승'}")
    print(f"  {PASS if ok2 else FAIL} 1115-31(본문) 비인접 문단 점수 불변: {before['1115-31']} → {after['1115-31']}")

    # 교차 오염 검증: 1115-IE65는 prefix가 달라 B 클러스터와 독립
    ie_unchanged = after["1115-IE65"] == before["1115-IE65"]
    ok3 = ie_unchanged
    print(f"  {PASS if ok3 else FAIL} 1115-IE65(다른 섹션) 교차 부스팅 없음: {before['1115-IE65']} → {after['1115-IE65']}")

    return ok1 and ok2 and ok3


# ═══════════════════════════════════════════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-db", action="store_true", help="레이어 1 단위 테스트만 실행 (DB 불필요)")
    args = parser.parse_args()

    print("=" * 65)
    print("UX Phase A 개선 검증 테스트")
    print("=" * 65)

    results = {}

    # 레이어 1 — 항상 실행
    results["1-A normalize_query"]   = test_normalize_query()
    results["1-B parse_chunk_num"]   = test_parse_chunk_num()
    results["1-C inverted_mapping"]  = test_inverted_mapping()

    # 레이어 2 — DB 연결 필요
    if not args.skip_db:
        print("\n" + "=" * 65)
        print("레이어 2: 통합 테스트 (MongoDB 연결 중...)")
        print("=" * 65)
        try:
            results["2-A search_hit"]      = test_run_search_hit()
            results["2-B search_free_text"] = test_run_search_free_text()
            results["2-C window_boost"]     = test_window_boost()
        except Exception as e:
            print(f"\n[ERROR] DB 연결 실패 또는 예외 발생: {e}")
            print("  --skip-db 옵션으로 단위 테스트만 실행하세요.")
    else:
        print("\n  --skip-db: 레이어 2 건너뜀")
        # window boost는 in-memory라 DB 불필요
        results["2-C window_boost"] = test_window_boost()

    # 최종 요약
    print("\n" + "=" * 65)
    print("테스트 결과 요약")
    print("=" * 65)
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    for name, ok in results.items():
        print(f"  {PASS if ok else FAIL} {name}")
    print(f"\n  합계: {passed}/{total} 통과")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()

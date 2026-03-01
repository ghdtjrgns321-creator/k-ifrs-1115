# app/test/graph-test.py
# LangGraph RAG 전체 파이프라인 통합 테스트
# 실행: uv run app/test/graph-test.py           → 핵심 3개 빠르게
#        uv run app/test/graph-test.py --full   → 전체 10개 (시간 더 걸림)
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

# Windows stdout 버퍼링 해제 — 출력이 실시간으로 보이게
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from app.graph import rag_graph  # noqa: E402

# ── 테스트 케이스 ─────────────────────────────────────────────────────────────
# (질문, 예상_라우팅, 답변에_있어야_할_키워드)
QUICK_CASES = [
    # 1. 범위 밖 → OUT 라우팅 검증
    (
        "오늘 점심 뭐 먹을까요?",
        "OUT",
        None,
    ),
    # 2. Step 2: 수행의무 식별 — 실무 단골 질문
    (
        "SaaS 기업이 소프트웨어 구독권과 초기 구현 서비스를 묶어 판매합니다. "
        "이 두 가지를 하나의 수행의무로 볼 수 있나요, 아니면 분리해야 하나요?",
        "IN",
        ["수행의무"],
    ),
    # 3. Step 5: 기간에 걸친 수익 인식 — 건설/용역업 핵심
    (
        "건설 도급 계약에서 수익을 기간에 걸쳐 인식하기 위한 조건 3가지와 "
        "투입법·산출법의 차이를 알려주세요.",
        "IN",
        ["기간에 걸쳐"],
    ),
]

FULL_CASES = QUICK_CASES + [
    # 4. Step 3: 변동대가 제약
    (
        "매출 리베이트 조건이 있는 계약에서 변동대가를 어떻게 추정하고 "
        "얼마나 수익에 포함할 수 있는지 제약 기준을 설명해 주세요.",
        "IN",
        ["변동대가", "제약"],
    ),
    # 5. Step 4: 독립 판매가격 추정
    (
        "여러 수행의무에 거래가격을 배분할 때 독립 판매가격을 관측할 수 없으면 "
        "어떤 추정 방법을 사용할 수 있나요?",
        "IN",
        ["독립 판매가격"],
    ),
    # 6. 본인 vs 대리인
    (
        "오픈마켓 플랫폼 운영사가 입점 판매자 상품을 중개합니다. "
        "플랫폼사가 환불 의무를 지고 가격 결정권은 판매자에게 있을 때 "
        "본인과 대리인 중 어느 쪽으로 회계처리 해야 하나요?",
        "IN",
        ["본인", "대리인"],
    ),
    # 7. 라이선스: 접근권 vs 사용권
    (
        "제약회사가 특허 라이선스를 제공할 때 "
        "시점 인식(사용권)과 기간 인식(접근권)을 구분하는 판단 기준은 무엇인가요?",
        "IN",
        ["라이선스"],
    ),
    # 8. 계약 변경
    (
        "장기 유지보수 계약 도중 고객이 서비스 범위를 축소하고 "
        "대가도 그에 비례하여 줄이겠다고 요청했습니다. "
        "이 변경을 별개 계약으로 처리해야 하나요, 기존 계약 수정으로 처리해야 하나요?",
        "IN",
        ["계약 변경"],
    ),
    # 9. Step 1: 계약 식별 — PO 기반 계약
    (
        "구매주문서(PO)를 계약으로 볼 수 있는 요건이 무엇인지 알려주세요. "
        "특히 고객이 지급을 이행할 능력과 의도가 있는지 어떻게 판단하나요?",
        "IN",
        ["계약"],
    ),
    # 10. 비현금 대가
    (
        "고객이 현금 대신 자기주식을 대가로 제공하는 계약에서 "
        "거래가격을 어떻게 측정해야 하나요?",
        "IN",
        ["공정가치"],
    ),
]


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def p(*args, **kwargs):
    """flush=True가 기본인 print — 실시간 출력 보장"""
    kwargs.setdefault("flush", True)
    print(*args, **kwargs)


def sep(char="═", n=62):
    p(char * n)


def print_docs(label, docs):
    if not docs:
        p(f"  {label}: (없음)")
        return
    p(f"  {label} ({len(docs)}개):")
    for d in docs[:2]:
        src   = d.get("source", "?")
        cid   = d.get("chunk_id", "?")[:22]
        score = d.get("final_score") or d.get("rerank_score") or d.get("score") or 0
        text  = d.get("content", "").replace("\n", " ")[:55]
        p(f"    [{src}] {cid} | {score:.3f} | {text}...")


# ── 메인 ─────────────────────────────────────────────────────────────────────

def run(cases: list):
    sep()
    p("  K-IFRS 1115 RAG 파이프라인 통합 테스트")
    p(f"  총 {len(cases)}개 질문 실행 중...")
    sep()

    passed = 0

    for idx, (question, expected_routing, keywords) in enumerate(cases):
        sep()
        p(f"[{idx+1:02d}/{len(cases)}] {question}")
        sep()
        p("  ⏳ 그래프 실행 중...", end=" ", flush=True)

        t0 = time.time()
        try:
            result = rag_graph.invoke({
                "messages":       [("human", question)],
                "routing":        "",
                "standalone_query": "",
                "retry_count":    0,
                "retrieved_docs": [],
                "reranked_docs":  [],
                "relevant_docs":  [],
                "answer":         "",
                "cited_sources":  [],
            })
        except Exception as e:
            p(f"\n  ❌ 오류: {type(e).__name__}: {e}")
            continue

        elapsed = time.time() - t0
        p(f"완료 ({elapsed:.1f}초)")

        routing  = result.get("routing", "?")
        sq       = result.get("standalone_query", "")
        answer   = result.get("answer", "")
        sources  = result.get("cited_sources", [])

        p(f"\n🔀 라우팅: {routing} (예상: {expected_routing})")
        if sq:
            p(f"📝 독립형: {sq}")

        p("\n📦 단계별 문서:")
        print_docs("retrieve", result.get("retrieved_docs", []))
        print_docs("rerank  ", result.get("reranked_docs",  []))
        print_docs("grade   ", result.get("relevant_docs",  []))

        p(f"\n💬 답변 앞 350자:")
        p(answer[:350])
        if len(answer) > 350:
            p(f"  ... (총 {len(answer)}자)")

        if sources:
            p(f"\n📌 출처 ({len(sources)}개):")
            for s in sources:
                p(f"  • [{s.get('source')}] {s.get('hierarchy','')}")

        routing_ok = routing == expected_routing
        kw_ok      = all(kw in answer for kw in keywords) if keywords else True
        ok         = routing_ok and kw_ok

        if ok:
            passed += 1
            p(f"\n✅ PASS")
        else:
            reasons = []
            if not routing_ok:
                reasons.append(f"라우팅 불일치(got={routing})")
            if not kw_ok:
                reasons.append(f"키워드 미포함{keywords}")
            p(f"\n❌ FAIL — {' | '.join(reasons)}")

    sep()
    p(f"  결과: {passed}/{len(cases)} 통과")
    p("  🎉 전체 통과!" if passed == len(cases) else "  ⚠️  일부 실패")
    sep()


if __name__ == "__main__":
    mode = FULL_CASES if "--full" in sys.argv else QUICK_CASES
    run(mode)

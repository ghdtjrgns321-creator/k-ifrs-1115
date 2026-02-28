import sys
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from langchain_upstage import UpstageEmbeddings

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

# ── 환경변수 ──────────────────────────────────────────────────────────────────
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("MONGO_DB_NAME", "kifrs_db")
COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME", "k-ifrs-1115-chatbot")

# ── 검색 파라미터 상수 ─────────────────────────────────────────────────────────
VECTOR_TOP_K = 10   # 각 전략별 후보 수
FINAL_TOP_K = 5     # 최종 출력 개수
RRF_K = 60          # RRF 상수 (Reciprocal Rank Fusion 논문 권장값)

# ── 테스트 질의 7개: K-IFRS 1115 Step별 핵심 시나리오 ───────────────────────────
TEST_QUERIES = [
    # Step 2: 수행의무 식별
    "A회사는 고객에게 소프트웨어 라이선스와 1년간 기술지원 서비스를 묶어 판매합니다. 이를 하나의 수행의무로 볼 수 있나요, 아니면 구분하여 두 개의 수행의무로 처리해야 하나요?",
    # Step 3: 거래가격 산정 (변동대가)
    "매출액의 5%를 성과급으로 추가 지급받는 계약에서 변동대가를 어떻게 추정하고 제약해야 하나요?",
    # 본인 vs 대리인
    "A회사는 온라인 플랫폼을 운영하며 B회사의 상품을 중개합니다. 최종 가격 결정권은 A사에 있고 재고 위험은 B사가 부담합니다. 본인인가요, 대리인인가요?",
    # Step 1: 계약 변경
    "건설 계약 중에 고객이 추가 공사를 요청했습니다. 이것이 별개의 계약으로 처리되는 경우와 기존 계약 변경으로 처리되는 경우의 차이는 무엇인가요?",
    # Step 5: 이행 기준 (진행기준)
    "건설 공사 계약에서 기간에 걸쳐 수익을 인식하려면 어떤 조건을 충족해야 하며, 진행률은 어떻게 측정하나요?",
    # 변동대가 + 반품
    "반품 가능성이 높은 제품 판매에서 수익을 얼마나 인식해야 하고, 반품 예상액은 어떻게 처리하나요?",
    # 라이선스
    "지식재산 라이선스를 부여할 때 시점에 인식하는 라이선스와 기간에 걸쳐 인식하는 라이선스를 구분하는 기준은 무엇인가요?",
]


# ── 검색 함수 3개 ──────────────────────────────────────────────────────────────

def search_vector_only(query: str, collection, embeddings) -> list[dict]:
    """
    Vector Search만 수행 (본문 필터 포함)
    parent_id가 없는 문서 = 본문 문서만 검색
    """
    query_vector = embeddings.embed_query(query)

    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 100,
                "limit": VECTOR_TOP_K,
                # parent_id 없는 문서 = QNA Child 제외, 본문만
                "filter": {"parent_id": {"$exists": False}},
            }
        },
        {"$project": {"embedding": 0, "score": {"$meta": "vectorSearchScore"}}},
    ]
    return list(collection.aggregate(pipeline)), query_vector


def search_keyword_only(query: str, collection) -> list[dict]:
    """
    Keyword Search만 수행 (본문 필터 포함)
    compound.mustNot exists parent_id → QNA Child 문서 제외
    """
    pipeline = [
        {
            "$search": {
                "index": "keyword_index",
                "compound": {
                    "must": [{"text": {"query": query, "path": "text"}}],
                    # parent_id 필드가 존재하는 문서(QNA Child)를 검색에서 제외
                    "mustNot": [{"exists": {"path": "parent_id"}}],
                },
            }
        },
        {"$limit": VECTOR_TOP_K},
        {"$project": {"embedding": 0, "score": {"$meta": "searchScore"}}},
    ]
    return list(collection.aggregate(pipeline))


def search_hybrid(
    query: str,
    collection,
    vector_results: list[dict],
    keyword_results: list[dict],
) -> list[dict]:
    """
    RRF(Reciprocal Rank Fusion) 방식으로 두 결과를 융합하고
    도메인 가중치(weight_score)를 추가 보정한 후 Top K 반환

    RRF 공식: score = 1 / (rank + 1 + k)  → 상위 순위일수록 점수가 높음
    최종 공식: final_score = rrf_score * weight_score
    """
    fused = {}  # chunk_id → 점수/순위 정보 누적

    for rank, doc in enumerate(vector_results):
        chunk_id = doc.get("chunk_id", f"v_{rank}")
        rrf = 1.0 / (rank + 1 + RRF_K)
        fused[chunk_id] = {
            "doc": doc,
            "vector_rank": rank + 1,
            "keyword_rank": None,  # 키워드에 없으면 None
            "rrf_score": rrf,
        }

    for rank, doc in enumerate(keyword_results):
        chunk_id = doc.get("chunk_id", f"k_{rank}")
        rrf = 1.0 / (rank + 1 + RRF_K)

        if chunk_id in fused:
            # 두 전략 모두에서 발견된 문서 → 점수 합산 (핵심 RRF 효과)
            fused[chunk_id]["rrf_score"] += rrf
            fused[chunk_id]["keyword_rank"] = rank + 1
        else:
            fused[chunk_id] = {
                "doc": doc,
                "vector_rank": None,
                "keyword_rank": rank + 1,
                "rrf_score": rrf,
            }

    # 도메인 가중치 보정: 카테고리별 중요도를 반영
    final_results = []
    for chunk_id, data in fused.items():
        weight = float(data["doc"].get("weight_score", 1.0))
        data["final_score"] = data["rrf_score"] * weight
        data["weight"] = weight
        final_results.append(data)

    final_results.sort(key=lambda x: x["final_score"], reverse=True)
    return final_results[:FINAL_TOP_K], fused  # fused 분석용으로도 반환


# ── 분석 함수 ──────────────────────────────────────────────────────────────────

def analyze_comparison(
    v_results: list[dict],
    k_results: list[dict],
    h_results: list[dict],
    fused_map: dict,
) -> None:
    """
    3가지 전략 비교 분석 출력
    1. 전략별 Top3 chunk_id 나열
    2. RRF 겹침률 (두 전략이 얼마나 상호보완적인지)
    3. 가중치 보정으로 순위가 바뀐 케이스
    """
    # 전략별 Top3 chunk_id 추출
    v_top3 = [f"{d.get('chunk_id')}({d.get('category', '?')})" for d in v_results[:3]]
    k_top3 = [f"{d.get('chunk_id')}({d.get('category', '?')})" for d in k_results[:3]]
    h_top3 = [
        f"{d['doc'].get('chunk_id')}({d['doc'].get('category', '?')})"
        for d in h_results[:3]
    ]

    print("\n📊 [전략 비교]")
    print(f"  Vector Only Top3:  {', '.join(v_top3)}")
    print(f"  Keyword Only Top3: {', '.join(k_top3)}")
    print(f"  Hybrid Top3:       {', '.join(h_top3)}")

    # RRF 겹침 분석: 두 전략 모두에 등장한 문서 수
    v_ids = {d.get("chunk_id") for d in v_results}
    k_ids = {d.get("chunk_id") for d in k_results}
    overlap = v_ids & k_ids
    overlap_ratio = len(overlap) / VECTOR_TOP_K * 100

    print(f"\n🔗 [RRF 융합 효과]")
    print(
        f"  - Vector ∩ Keyword 겹침: {len(overlap)}/{VECTOR_TOP_K}개 ({overlap_ratio:.0f}%)"
    )
    if 20 <= overlap_ratio <= 50:
        print("  ✅ 두 전략이 적절히 상호보완적으로 작동 중 (겹침 20~50%)")
    elif overlap_ratio < 20:
        print("  ℹ️  겹침이 적어 하이브리드 효과가 큼 (서로 다른 문서 발굴)")
    else:
        print("  ⚠️  겹침이 많아 두 전략 차별화 검토 필요")

    # 가중치 보정 효과: RRF 순위 vs 최종 순위 비교
    print(f"\n⚖️  [가중치 보정 효과]")
    # fused_map에서 rrf_score 기준 순위 재계산
    rrf_sorted = sorted(fused_map.values(), key=lambda x: x["rrf_score"], reverse=True)

    moved_up = []
    for final_rank, item in enumerate(h_results):
        chunk_id = item["doc"].get("chunk_id")
        rrf_rank = next(
            (i for i, x in enumerate(rrf_sorted) if x["doc"].get("chunk_id") == chunk_id),
            final_rank,
        )
        weight = item["weight"]
        if rrf_rank > final_rank and weight > 1.0:
            moved_up.append(
                f"  ↑ {chunk_id} (weight={weight}) : RRF {rrf_rank+1}위 → 최종 {final_rank+1}위"
            )

    if moved_up:
        for line in moved_up:
            print(line)
    else:
        print("  - 이번 쿼리에서 가중치로 인한 순위 변동 없음")


# ── 메인 실행 ──────────────────────────────────────────────────────────────────

def run_tests():
    print("🔍 본문 전용 하이브리드 검색 테스트 (3전략 비교)\n")
    print(f"  DB: {DB_NAME} / 컬렉션: {COLLECTION_NAME}")
    print(f"  각 전략 Top-{VECTOR_TOP_K} → 최종 Top-{FINAL_TOP_K} 출력\n")

    embeddings = UpstageEmbeddings(model="solar-embedding-1-large-query")
    client = MongoClient(MONGO_URI)
    collection = client[DB_NAME][COLLECTION_NAME]

    total = collection.count_documents({})
    body_only = collection.count_documents({"parent_id": {"$exists": False}})
    qna_child = total - body_only
    print(f"  컬렉션 현황: 전체 {total}개 (본문 {body_only}개 / QNA Child {qna_child}개)\n")

    if body_only == 0:
        print("❌ 본문 문서가 없습니다. 임베딩 적재 스크립트를 먼저 실행해 주세요.")
        client.close()
        return

    for idx, query in enumerate(TEST_QUERIES):
        print(f"\n{'═'*62}")
        print(f"[질문 {idx+1}/{len(TEST_QUERIES)}] {query}")
        print(f"{'═'*62}")

        # 3전략 검색 수행
        v_results, query_vector = search_vector_only(query, collection, embeddings)
        k_results = search_keyword_only(query, collection)
        h_results, fused_map = search_hybrid(query, collection, v_results, k_results)

        # 비교 분석 출력
        analyze_comparison(v_results, k_results, h_results, fused_map)

        # Hybrid 최종 Top K 상세 출력
        print(f"\n🏆 [Hybrid 최종 Top {FINAL_TOP_K}]")
        for rank, item in enumerate(h_results):
            doc = item["doc"]
            v_rank = item["vector_rank"] if item["vector_rank"] else "-"
            k_rank = item["keyword_rank"] if item["keyword_rank"] else "-"
            category = doc.get("category", "?")
            weight = item["weight"]

            print(
                f"\n  {rank+1}위 | {doc.get('chunk_id')} | score: {item['final_score']:.5f} "
                f"| {category}(w={weight}) | V:{v_rank} K:{k_rank}"
            )
            print(f"    계층: {doc.get('hierarchy', '-')}")

            # 본문 미리보기 (줄바꿈 제거, 150자)
            preview = doc.get("text", "").replace("\n", " ").strip()
            print(f"    내용: {preview[:150]}...")

            # QNA Child가 섞여 들어왔는지 검증 (parent_id 없어야 정상)
            if doc.get("parent_id"):
                print(f"    ⚠️  경고: QNA Child 문서가 포함됨! parent_id={doc.get('parent_id')}")

    client.close()
    print(f"\n{'═'*62}")
    print("✅ 테스트 완료")


if __name__ == "__main__":
    run_tests()

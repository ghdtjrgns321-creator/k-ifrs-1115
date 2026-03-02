import sys
from collections import Counter
from pymongo import MongoClient
from langchain_upstage import UpstageEmbeddings
from app.config import settings

sys.stdout.reconfigure(encoding="utf-8")

# ── 상수 ──────────────────────────────────────────────────────────────────────
CHILD_COLLECTION  = settings.mongo_collection_name
PARENT_COLLECTION = "kifrs_1115_findings_parents"

# findings는 수가 적으므로 Top3으로 충분
VECTOR_TOP_K = 10
FINAL_TOP_K  = 3
RRF_K        = 60

# findings parent_id 접두어 (FSS-감리원, KICPA-한국공인회계사회)
FINDINGS_PREFIXES = ("FSS-", "KICPA-")

# ── 테스트 질의 ────────────────────────────────────────────────────────────────
TEST_QUERIES = [
    # FSS-CASE-2022-2311-02 (밀어내기 매출, 수행의무 미이행)
    "연말에 협력업체가 발주서를 제출했지만 실제 최종 고객이 없는 상태에서 매출을 인식한 경우",
    # FSS-CASE-2022-2311-03 (유상사급, 통제 이전 여부)
    "유상사급 구조에서 대리점에 원자재를 공급했을 때 매출을 총액으로 인식할 수 있는지",
    # FSS-CASE-2023-2405-01 (판매장려금, 변동대가)
    "의약품 판매장려금을 결산 시점에 과소추정하여 매출채권이 과대계상된 경우",
    # FSS-CASE-2023-2405-05 (검수 조건부 수출, 통제 이전 시점)
    "수출 장비 계약에서 설치 후 최종 검수 조건이 있는데 선적 시점에 수익을 인식한 경우",
    # FSS-CASE-2024-2409-02 (종속회사 밀어내기)
    "종속회사에 밀어내기 판매를 통해 연결재무제표에서 매출을 과대계상한 사례",
]


# ── findings 전용 검색 함수 ───────────────────────────────────────────────────

def is_finding(doc: dict) -> bool:
    """parent_id가 감리사례 접두어로 시작하는지 확인"""
    return str(doc.get("parent_id", "")).startswith(FINDINGS_PREFIXES)


def search_findings_vector(query: str, child_coll, embeddings) -> tuple[list, list]:
    """
    findings Child 청크만 벡터 검색
    - Atlas Vector Search는 컬렉션 전체 대상 → Python 후처리로 findings 필터링
    - numCandidates: 본문 1297 + QNA Child + findings ~45개를 포함해 여유있게 설정
    """
    query_vector = embeddings.embed_query(query)

    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 600,
                "limit": 250,
            }
        },
        {"$project": {"embedding": 0, "score": {"$meta": "vectorSearchScore"}}},
    ]

    raw = list(child_coll.aggregate(pipeline))

    # findings Child만 필터 (FSS-, KICPA- 접두어)
    findings_only = [d for d in raw if is_finding(d)]
    return findings_only[:VECTOR_TOP_K], query_vector


def search_findings_keyword(query: str, child_coll) -> list:
    """
    findings Child 청크만 키워드 검색
    - $search는 compound.filter로 exists(parent_id)를 사용하고,
      Python 후처리로 findings 접두어 검증 (Atlas Search regex filter는 인덱스 의존적)
    """
    pipeline = [
        {
            "$search": {
                "index": "keyword_index",
                "compound": {
                    "must": [{"text": {"query": query, "path": "text"}}],
                    "filter": [{"exists": {"path": "parent_id"}}],
                },
            }
        },
        {"$limit": VECTOR_TOP_K * 3},   # findings 비율이 낮으므로 여유있게
        {"$project": {"embedding": 0, "score": {"$meta": "searchScore"}}},
    ]
    raw = list(child_coll.aggregate(pipeline))
    return [d for d in raw if is_finding(d)][:VECTOR_TOP_K]


def fuse_and_rank(v_results: list, k_results: list) -> tuple[list, dict]:
    """
    RRF(Reciprocal Rank Fusion)로 벡터 + 키워드 결과 융합
    findings는 weight_score=1.0 고정이므로 RRF 점수 그대로 사용
    """
    fused = {}

    for rank, doc in enumerate(v_results):
        chunk_id = doc.get("chunk_id", f"v_{rank}")
        rrf = 1.0 / (rank + 1 + RRF_K)
        fused[chunk_id] = {
            "doc": doc, "vector_rank": rank + 1,
            "keyword_rank": None, "rrf_score": rrf,
        }

    for rank, doc in enumerate(k_results):
        chunk_id = doc.get("chunk_id", f"k_{rank}")
        rrf = 1.0 / (rank + 1 + RRF_K)
        if chunk_id in fused:
            fused[chunk_id]["rrf_score"] += rrf
            fused[chunk_id]["keyword_rank"] = rank + 1
        else:
            fused[chunk_id] = {
                "doc": doc, "vector_rank": None,
                "keyword_rank": rank + 1, "rrf_score": rrf,
            }

    results = []
    for chunk_id, data in fused.items():
        weight = float(data["doc"].get("weight_score", 1.0))
        data["final_score"] = data["rrf_score"] * weight
        data["weight"] = weight
        results.append(data)

    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results, fused


def dedup_by_parent(ranked: list) -> list:
    """
    같은 감리사례에서 Q/A/S가 모두 검색될 경우 최고점 1개만 남김
    → 최종 Top K에서 동일 사례 중복 방지
    """
    seen = set()
    deduped = []
    for item in ranked:
        pid = item["doc"].get("parent_id")
        if pid not in seen:
            seen.add(pid)
            deduped.append(item)
        if len(deduped) >= FINAL_TOP_K:
            break
    return deduped


def lookup_parents(deduped: list, parent_coll) -> dict:
    """
    PDR 패턴: 검색된 Child의 parent_id로 감리사례 원본 전체 텍스트 조회
    kifrs_1115_findings_parents 컬렉션에서 _id 기준 조회
    """
    parent_ids = [item["doc"].get("parent_id") for item in deduped]
    return {
        str(d["_id"]): d
        for d in parent_coll.find({"_id": {"$in": parent_ids}})
    }


# ── 분석 출력 함수 ────────────────────────────────────────────────────────────

def analyze_and_print(
    query_idx: int,
    query: str,
    v_results: list,
    k_results: list,
    ranked_all: list,
    deduped: list,
    parent_docs: dict,
    fused_map: dict,
):
    print(f"\n{'═'*65}")
    print(f"[질문 {query_idx+1}/{len(TEST_QUERIES)}] {query}")
    print(f"{'═'*65}")

    # ── 전략 비교 ─────────────────────────────────────────────────────────────
    def fmt(docs):
        return [f"{d.get('chunk_id')}[{d.get('chunk_type','?')[0].upper()}]" for d in docs[:3]]

    v_top3 = fmt(v_results)
    k_top3 = fmt(k_results)
    h_top3 = [
        f"{i['doc'].get('chunk_id')}[{i['doc'].get('chunk_type','?')[0].upper()}]"
        for i in ranked_all[:3]
    ]

    print("\n[전략 비교]")
    print(f"  Vector Only Top3:  {', '.join(v_top3) if v_top3 else '결과 없음'}")
    print(f"  Keyword Only Top3: {', '.join(k_top3) if k_top3 else '결과 없음'}")
    print(f"  Hybrid Top3:       {', '.join(h_top3) if h_top3 else '결과 없음'}")

    # ── chunk_type 분포 (Q/A/S 중 어떤 파트가 검색되는지) ──────────────────────
    top10 = list(ranked_all[:10])
    type_counts = Counter(item["doc"].get("chunk_type", "?") for item in top10)
    print(f"\n🔍 [chunk_type 분포 - 상위 10개]")
    for ctype, label in [("question", "Q(배경+질의)"), ("answer", "A(감리지적)"), ("supplementary", "S(참고기준)")]:
        bar = "█" * type_counts.get(ctype, 0)
        print(f"  {label}: {type_counts.get(ctype, 0)}개 {bar}")

    # ── RRF 겹침 분석 ─────────────────────────────────────────────────────────
    v_ids = {d.get("chunk_id") for d in v_results}
    k_ids = {d.get("chunk_id") for d in k_results}
    overlap = v_ids & k_ids
    overlap_ratio = len(overlap) / max(len(v_ids), 1) * 100
    print(f"\n[RRF 융합]  Vector ∩ Keyword 겹침: {len(overlap)}/{len(v_ids)}개 ({overlap_ratio:.0f}%)")

    # ── PDR Lookup: 원본 전체 출력 (요약 + 전문 보기 시뮬레이션) ──────────────
    print(f"\n[감리사례 검색 결과 — Top {FINAL_TOP_K}]")

    for rank, item in enumerate(deduped):
        doc    = item["doc"]
        pid    = doc.get("parent_id")
        v_r    = item["vector_rank"] if item["vector_rank"] else "-"
        k_r    = item["keyword_rank"] if item["keyword_rank"] else "-"

        print(f"\n  {'─'*58}")
        print(f"  {rank+1}위 │ {pid}")
        print(f"       score: {item['final_score']:.5f} │ chunk: {doc.get('chunk_type')} │ V:{v_r} K:{k_r}")
        print(f"       계층: {doc.get('hierarchy', '-')}")

        # related_paragraphs: 기준서 연관 문단 표시
        related = doc.get("related_paragraphs", [])
        if related:
            paras = ", ".join(f"§{p}" for p in related)
            print(f"       관련 기준서 문단: {paras}")

        # Parent 원본 조회 (전문 보기)
        parent = parent_docs.get(pid)
        if parent:
            full_text = parent.get("content", "")
            preview = full_text.replace("\n", " ").strip()[:350]
            print(f"\n       ┌── [요약 미리보기] ──────────────────────────────────")
            print(f"       │  {preview}...")
            print(f"       └── 전문 총 {len(full_text)}자")
        else:
            print(f"       ⚠️  Parent({pid}) 조회 실패 — {PARENT_COLLECTION}에 없음")

    # ── Parent 중복 감지 ───────────────────────────────────────────────────────
    all_pids = [item["doc"].get("parent_id") for item in ranked_all[:10]]
    dup_pids = [pid for pid, cnt in Counter(all_pids).items() if cnt > 1]
    if dup_pids:
        print(f"\n[Parent 중복 감지 — dedup 처리됨]")
        for pid in dup_pids:
            chunks = [
                f"{i['doc'].get('chunk_type')}({i['doc'].get('chunk_id')})"
                for i in ranked_all[:10] if i["doc"].get("parent_id") == pid
            ]
            print(f"  {pid}: {', '.join(chunks)}")


# ── 메인 실행 ─────────────────────────────────────────────────────────────────

def run_findings_tests():
    client = MongoClient(settings.mongo_uri)
    db = client[settings.mongo_db_name]
    child_coll  = db[CHILD_COLLECTION]
    parent_coll = db[PARENT_COLLECTION]

    # 상태 점검
    total_children = child_coll.count_documents(
        {"parent_id": {"$regex": f"^({'|'.join(FINDINGS_PREFIXES)})"}}
    )
    total_parents = parent_coll.count_documents({})

    print("감리지적사례 검색 테스트 (PDR 패턴 검증)\n")
    print(f"  DB: {settings.mongo_db_name}")
    print(f"  Child 컬렉션({CHILD_COLLECTION}): findings 청크 {total_children}개")
    print(f"  Parent 컬렉션({PARENT_COLLECTION}): 원본 {total_parents}개")

    if total_children == 0:
        print("\n❌ Findings Child 청크가 없습니다.")
        print("   → 먼저 07-findings-embed.py를 실행해 주세요.")
        print("   → uv run app/preprocessing/07-findings-embed.py")
        client.close()
        return

    # category별 분포 확인
    cats = [
        d.get("category")
        for d in child_coll.find(
            {"parent_id": {"$regex": f"^({'|'.join(FINDINGS_PREFIXES)})"}},
            {"category": 1}
        )
    ]
    print("\n  findings category 분포:")
    for cat, cnt in Counter(cats).most_common():
        print(f"    {cat}: {cnt}개")

    print()
    embeddings = UpstageEmbeddings(model=settings.embed_query_model)

    for idx, query in enumerate(TEST_QUERIES):
        v_results, _ = search_findings_vector(query, child_coll, embeddings)
        k_results    = search_findings_keyword(query, child_coll)
        ranked_all, fused_map = fuse_and_rank(v_results, k_results)

        deduped     = dedup_by_parent(ranked_all)
        parent_docs = lookup_parents(deduped, parent_coll)

        analyze_and_print(idx, query, v_results, k_results, ranked_all, deduped, parent_docs, fused_map)

    client.close()
    print(f"\n{'═'*65}")
    print("✅ 감리사례 검색 테스트 완료")


if __name__ == "__main__":
    run_findings_tests()

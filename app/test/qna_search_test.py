import sys
from collections import Counter
from pymongo import MongoClient
from langchain_upstage import UpstageEmbeddings
from app.config import settings

sys.stdout.reconfigure(encoding="utf-8")

# ── 상수 ──────────────────────────────────────────────────────────────────────
CHILD_COLLECTION  = settings.mongo_collection_name
PARENT_COLLECTION = "kifrs_1115_qna_parents"  # PDR 원본 저장소

VECTOR_TOP_K = 10  # 각 전략별 후보 수
FINAL_TOP_K = 3    # QNA는 원본 전체를 반환하므로 3개로 충분
RRF_K = 60         # RRF 상수

# ── 테스트 질의 5개 ────────────────────────────────────────────────────────────
# 실제 kifrs_1115_qna_parents에 존재하는 질의 유형과 매핑
TEST_QUERIES = [
    # IFRS 해석위원회 QNA-221109A에 직접 매핑 (본인/대리인)
    "소프트웨어 라이선스 재판매자가 IFRS 15를 적용할 때 본인인지 대리인인지 어떻게 판단하나요?",
    # IFRS 해석위원회 QNA-202504C에 매핑 (수업료 수익)
    "교육기관이 학생으로부터 받은 수업료를 수익으로 인식하는 기간은 어떻게 결정하나요?",
    # IFRS 해석위원회 QNA-201906D/QNA-202003D에 매핑 (계약 이행 원가)
    "고객과의 계약을 이행하기 위해 발생한 교육훈련 원가를 자산으로 인식할 수 있나요?",
    # 신속처리질의 영역 (반품/변동대가)
    "반품권이 있는 판매에서 수익 인식 금액과 환불부채는 어떻게 산정하고 처리하나요?",
    # 신속처리질의 영역 (수행의무 배분)
    "묶음 판매 계약에서 거래가격을 개별 수행의무에 배분하는 방법은 무엇인가요?",
]


# ── QNA 전용 검색 함수 3개 ─────────────────────────────────────────────────────

def search_qna_vector(query: str, child_coll, embeddings) -> tuple[list, list]:
    """
    QNA Child 청크만 대상으로 벡터 검색 수행
    - Atlas Vector Search의 filter 옵션은 인덱스에 필드 등록이 필요하므로 사용 안 함
    - 대신 전체 컬렉션에서 충분히 가져온 뒤, Python에서 parent_id 유무로 후처리 필터링
    - numCandidates=500: 본문 1297 + QNA 277 = 1574개 중 QNA 비율(17.6%)을 감안해 넉넉히
    """
    query_vector = embeddings.embed_query(query)

    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 500,
                "limit": 200,  # QNA Child가 충분히 포함될 수 있도록 크게 설정
            }
        },
        {"$project": {"embedding": 0, "score": {"$meta": "vectorSearchScore"}}},
    ]

    raw = list(child_coll.aggregate(pipeline))

    # Python 후처리: parent_id가 있는 문서(QNA Child)만 유지
    qna_only = [d for d in raw if d.get("parent_id")]
    return qna_only[:VECTOR_TOP_K], query_vector


def search_qna_keyword(query: str, child_coll) -> list:
    """
    QNA Child 청크만 대상으로 키워드 검색 수행
    - compound.filter exists parent_id → QNA Child만 선별
    """
    pipeline = [
        {
            "$search": {
                "index": "keyword_index",
                "compound": {
                    "must": [{"text": {"query": query, "path": "text"}}],
                    # filter는 점수에 영향 없이 필터링 (must와 다름)
                    "filter": [{"exists": {"path": "parent_id"}}],
                },
            }
        },
        {"$limit": VECTOR_TOP_K},
        {"$project": {"embedding": 0, "score": {"$meta": "searchScore"}}},
    ]
    return list(child_coll.aggregate(pipeline))


def fuse_and_rank(v_results: list, k_results: list) -> tuple[list, dict]:
    """
    RRF로 두 결과를 융합하고 도메인 가중치 적용
    동일 parent_id에서 Q/A/S가 모두 검색될 수 있으므로 chunk_id 기준으로 점수 계산
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

    # 도메인 가중치 적용
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
    같은 parent_id에서 Q/A/S가 모두 검색될 경우, 최고점 chunk 1개만 남김
    → 최종 출력에서 같은 QNA가 중복으로 등장하는 것을 방지
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
    PDR 패턴의 핵심: 검색된 Child의 parent_id로 원본 전체 텍스트 가져오기
    kifrs_1115_qna_parents 컬렉션에서 _id 기준 조회
    """
    parent_ids = [item["doc"].get("parent_id") for item in deduped]
    parent_docs = {
        str(d["_id"]): d
        for d in parent_coll.find({"_id": {"$in": parent_ids}})
    }
    return parent_docs


# ── 분석 출력 함수 ──────────────────────────────────────────────────────────────

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
    print(f"\n{'═'*62}")
    print(f"[질문 {query_idx+1}/{len(TEST_QUERIES)}] {query}")
    print(f"{'═'*62}")

    # ── 전략 비교 ──────────────────────────────────────────────────
    def fmt(docs, key="chunk_id", cat_key="category"):
        return [f"{d.get(key)}({d.get(cat_key, '?')[:6]})" for d in docs[:3]]

    v_top3 = fmt(v_results)
    k_top3 = fmt(k_results)
    h_top3 = [f"{i['doc'].get('chunk_id')}({i['doc'].get('category','?')[:6]})" for i in ranked_all[:3]]

    print("\n[전략 비교]")
    print(f"  Vector Only Top3:  {', '.join(v_top3) if v_top3 else '결과 없음'}")
    print(f"  Keyword Only Top3: {', '.join(k_top3) if k_top3 else '결과 없음'}")
    print(f"  Hybrid Top3:       {', '.join(h_top3) if h_top3 else '결과 없음'}")

    # ── chunk_type 분포 분석 ───────────────────────────────────────
    # 상위 10개 결과에서 Q/A/S 분포 확인
    top10 = list(ranked_all[:10])
    type_counts = Counter(item["doc"].get("chunk_type", "?") for item in top10)
    print(f"\n🔍 [chunk_type 분포 - 상위 10개]")
    for ctype, cnt in [("question", "Q(질의)"), ("answer", "A(회신)"), ("supplementary", "S(부록)")]:
        bar = "█" * type_counts.get(ctype, 0)
        print(f"  {cnt}: {type_counts.get(ctype, 0)}개 {bar}")

    # ── RRF 겹침 분석 ─────────────────────────────────────────────
    v_ids = {d.get("chunk_id") for d in v_results}
    k_ids = {d.get("chunk_id") for d in k_results}
    overlap = v_ids & k_ids
    overlap_ratio = len(overlap) / max(len(v_ids), 1) * 100
    print(f"\n[RRF 융합]  Vector ∩ Keyword 겹침: {len(overlap)}/{len(v_ids)}개 ({overlap_ratio:.0f}%)")

    # ── 가중치 보정 확인 ───────────────────────────────────────────
    rrf_sorted = sorted(fused_map.values(), key=lambda x: x["rrf_score"], reverse=True)
    moved = []
    for final_rank, item in enumerate(deduped):
        cid = item["doc"].get("chunk_id")
        rrf_rank = next((i for i, x in enumerate(rrf_sorted) if x["doc"].get("chunk_id") == cid), final_rank)
        if rrf_rank > final_rank and item["weight"] > 1.0:
            moved.append(f"  ↑ {cid}(w={item['weight']}) RRF {rrf_rank+1}위 → 최종 {final_rank+1}위")
    if moved:
        print(f"[가중치 보정]")
        for m in moved:
            print(m)

    # ── PDR Lookup: 원본 전체 텍스트 출력 ─────────────────────────
    print(f"\n[PDR Lookup — Hybrid Top {FINAL_TOP_K} 원본]")
    for rank, item in enumerate(deduped):
        doc = item["doc"]
        pid = doc.get("parent_id")
        chunk_type = doc.get("chunk_type", "?")
        v_r = item["vector_rank"] if item["vector_rank"] else "-"
        k_r = item["keyword_rank"] if item["keyword_rank"] else "-"
        category = doc.get("category", "?")
        weight = item["weight"]

        print(f"\n  {rank+1}위 | {doc.get('chunk_id')} | score: {item['final_score']:.5f}")
        print(f"       chunk_type: {chunk_type} | {category}(w={weight}) | V:{v_r} K:{k_r}")
        print(f"       계층: {doc.get('hierarchy', '-')}")

        # Parent 원본 조회
        parent = parent_docs.get(pid)
        if parent:
            meta = parent.get("metadata", {})
            full_text = parent.get("content", "")
            print(f"       ┌── Parent 원본 ({meta.get('category','?')}, paraNum={meta.get('paraNum','?')}) ──")
            # 원본 300자 미리보기 (줄바꿈 → 스페이스)
            preview = full_text.replace("\n", " ").strip()[:300]
            print(f"       │  {preview}...")
            print(f"       └── 원본 총 {len(full_text)}자")
        else:
            print(f"       ⚠️  Parent({pid}) 조회 실패 — kifrs_1115_qna_parents에 없음")

    # ── 중복 Parent 발생 여부 확인 ─────────────────────────────────
    all_pids = [item["doc"].get("parent_id") for item in ranked_all[:10]]
    dup_pids = [pid for pid, cnt in Counter(all_pids).items() if cnt > 1]
    if dup_pids:
        print(f"\n🔄 [Parent 중복 감지 — dedup 처리됨]")
        for pid in dup_pids:
            chunks_from_pid = [
                f"{i['doc'].get('chunk_type')}({i['doc'].get('chunk_id')})"
                for i in ranked_all[:10] if i["doc"].get("parent_id") == pid
            ]
            print(f"  {pid}: {', '.join(chunks_from_pid)}")


# ── 메인 실행 ──────────────────────────────────────────────────────────────────

def run_qna_tests():
    client = MongoClient(settings.mongo_uri)
    db = client[settings.mongo_db_name]
    child_coll = db[CHILD_COLLECTION]
    parent_coll = db[PARENT_COLLECTION]

    # 상태 점검
    total_children = child_coll.count_documents({"parent_id": {"$exists": True}})
    total_parents = parent_coll.count_documents({})

    print("QNA 검색 테스트 (PDR 패턴 검증)\n")
    print(f"  DB: {settings.mongo_db_name}")
    print(f"  Child 컬렉션({CHILD_COLLECTION}): QNA 청크 {total_children}개")
    print(f"  Parent 컬렉션({PARENT_COLLECTION}): 원본 {total_parents}개")

    # ── 임베딩 미완료 시 조기 종료 ────────────────────────────────────────
    if total_children == 0:
        print()
        print("❌ QNA Child 청크가 없습니다.")
        print("   → 먼저 06-qna-embed.py를 실행하여 임베딩을 적재해 주세요.")
        print("   → uv run app/preprocessing/06-qna-embed.py")
        client.close()
        return

    if total_parents == 0:
        print("❌ QNA Parent 원본이 없습니다.")
        print("   → 먼저 06-qna-embed.py를 실행해 주세요.")
        client.close()
        return

    # category별 Child 분포 출력
    from collections import Counter
    cats = [d.get("category") for d in child_coll.find({"parent_id": {"$exists": True}}, {"category": 1})]
    print()
    print("  QNA category 분포:")
    for cat, cnt in Counter(cats).most_common():
        print(f"    {cat}: {cnt}개")

    print()
    embeddings = UpstageEmbeddings(model=settings.embed_query_model)

    for idx, query in enumerate(TEST_QUERIES):
        # 3전략 검색
        v_results, _ = search_qna_vector(query, child_coll, embeddings)
        k_results = search_qna_keyword(query, child_coll)
        ranked_all, fused_map = fuse_and_rank(v_results, k_results)

        # 같은 Parent의 중복 제거 후 Top K
        deduped = dedup_by_parent(ranked_all)

        # PDR: Parent 원본 조회
        parent_docs = lookup_parents(deduped, parent_coll)

        # 분석 출력
        analyze_and_print(idx, query, v_results, k_results, ranked_all, deduped, parent_docs, fused_map)

    client.close()
    print(f"\n{'═'*62}")
    print("✅ QNA 테스트 완료")


if __name__ == "__main__":
    run_qna_tests()

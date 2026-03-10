import re
from pymongo import MongoClient
from rank_bm25 import BM25Okapi
from app.config import settings
from app.embeddings import embed_query_sync

# ── 상수 ────────────────────────────────────────────────────────────────────────
QNA_PARENT_COLL      = "k-ifrs-1115-qna-parents"
FINDINGS_PARENT_COLL = "k-ifrs-1115-findings-parents"

VECTOR_TOP_K        = 100  # 후보 풀 확장
RRF_K               = 60   # RRF 논문 권장값
QNA_SUPPLEMENT      = 15   # QNA 보조 최대 추가 수
FINDINGS_SUPPLEMENT = 15   # 감리사례 보조 최대 추가 수


# ── Lazy 초기화 ──────────────────────────────────────────────────────────────────
_db = None
_bm25: BM25Okapi | None = None
_bm25_corpus: list[dict] | None = None


def _get_db():
    global _db
    if _db is None:
        client = MongoClient(settings.mongo_uri)
        _db = client[settings.mongo_db_name]
    return _db


def _generate_hypothetical_doc(query: str) -> str:
    """HyDE: 질문에 대한 가상 K-IFRS 조항 텍스트를 생성합니다.

    grade 통과 문서가 부족할 때 폴백으로만 호출됩니다.
    실패 시 원본 쿼리로 폴백하여 파이프라인이 중단되지 않습니다.
    """
    from app.agents import hyde_agent
    from app.prompts import HYDE_PROMPT
    try:
        result = hyde_agent.run_sync(HYDE_PROMPT.format(query=query))
        return result.output.strip() if result.output else query
    except Exception:
        return query


# ── 개별 검색 함수 ───────────────────────────────────────────────────────────────

def _search_vector(query_vector: list, limit: int) -> list[dict]:
    """Atlas Vector Search: 전체 컬렉션에서 의미 유사도 검색."""
    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": limit * 5,
                "limit": limit,
            }
        },
        {"$project": {"embedding": 0, "score": {"$meta": "vectorSearchScore"}}},
    ]
    return list(_get_db()[settings.mongo_collection_name].aggregate(pipeline))


def _tokenize_ko(text: str) -> list[str]:
    """한국어 텍스트를 BM25용 토큰 리스트로 변환합니다."""
    tokens: list[str] = []
    for word in re.findall(r'[가-힣]+', text):
        if len(word) == 1:
            tokens.append(word)
        else:
            tokens.extend(word[i:i+2] for i in range(len(word) - 1))
    tokens.extend(t.lower() for t in re.findall(r'[a-zA-Z0-9]+', text))
    return tokens


def _build_bm25_index() -> None:
    """MongoDB 전체 문서로 BM25 인덱스를 빌드합니다. 최초 1회만 실행됩니다."""
    global _bm25, _bm25_corpus
    db = _get_db()
    docs = list(db[settings.mongo_collection_name].find({}, {"embedding": 0}))
    _bm25_corpus = docs
    corpus = [_tokenize_ko(doc.get("text", "")) for doc in docs]
    _bm25 = BM25Okapi(corpus)


def _search_keyword(query: str, limit: int) -> list[dict]:
    """로컬 BM25 키워드 검색."""
    global _bm25, _bm25_corpus
    if _bm25 is None:
        _build_bm25_index()

    query_tokens = _tokenize_ko(query)
    if not query_tokens:
        return []

    scores = _bm25.get_scores(query_tokens)
    ranked_indices = sorted(
        (i for i in range(len(scores)) if scores[i] > 0),
        key=lambda i: scores[i],
        reverse=True,
    )[:limit]

    results = []
    for idx in ranked_indices:
        doc = dict(_bm25_corpus[idx])
        doc["score"] = float(scores[idx])
        results.append(doc)
    return results


# ── RRF 융합 ─────────────────────────────────────────────────────────────────────

def _parse_chunk_num(chunk_id: str) -> tuple[str, int] | None:
    """청크 ID에서 섹션 prefix와 번호를 분리합니다."""
    m = re.match(r'^([\w]+-[A-Z]{0,2})(\d+)$', chunk_id)
    return (m.group(1), int(m.group(2))) if m else None


def _apply_window_boost(fused: dict, window: int = 3, boost: float = 0.15) -> None:
    """같은 섹션(prefix)의 ±window 이내 청크가 동반되면 rrf_score를 부스팅합니다."""
    prefix_map: dict[str, list[tuple[int, str]]] = {}
    for cid in fused:
        parsed = _parse_chunk_num(cid)
        if parsed:
            prefix, num = parsed
            prefix_map.setdefault(prefix, []).append((num, cid))

    for prefix, items in prefix_map.items():
        if len(items) < 2:
            continue
        for num_i, cid_i in items:
            cluster_count = sum(
                1 for num_j, _ in items
                if num_j != num_i and abs(num_j - num_i) <= window
            )
            if cluster_count >= 1:
                fused[cid_i]["rrf_score"] += boost * cluster_count


def _fuse_rrf(v_results: list[dict], k_results: list[dict], final_k: int) -> list[dict]:
    """RRF로 벡터 + 키워드 결과를 융합하고 도메인 가중치를 적용합니다."""
    v_score_map = {doc.get("chunk_id", f"v_{i}"): doc.get("score", 0.0)
                   for i, doc in enumerate(v_results)}

    fused: dict[str, dict] = {}

    for rank, doc in enumerate(v_results):
        chunk_id = doc.get("chunk_id", f"v_{rank}")
        fused[chunk_id] = {
            "doc": doc,
            "rrf_score": 1.0 / (rank + 1 + RRF_K),
            "vector_score": doc.get("score", 0.0),
        }

    for rank, doc in enumerate(k_results):
        chunk_id = doc.get("chunk_id", f"k_{rank}")
        rrf = 1.0 / (rank + 1 + RRF_K)
        if chunk_id in fused:
            fused[chunk_id]["rrf_score"] += rrf
        else:
            fused[chunk_id] = {
                "doc": doc,
                "rrf_score": rrf,
                "vector_score": v_score_map.get(chunk_id, 0.0),
            }

    _apply_window_boost(fused)

    ranked = []
    for data in fused.values():
        weight = float(data["doc"].get("weight_score", 1.0))
        ranked.append({**data, "final_score": data["rrf_score"] * weight})

    ranked.sort(key=lambda x: x["final_score"], reverse=True)

    for item in ranked[:final_k]:
        item["doc"]["vector_score"] = item["vector_score"]

    return [item["doc"] for item in ranked[:final_k]]


# ── PDR Lookup ───────────────────────────────────────────────────────────────────

def _classify_source(parent_id: str | None, category: str = "") -> str:
    """parent_id 접두어와 category로 문서 출처를 결정합니다."""
    if parent_id:
        if str(parent_id).startswith("QNA-"):
            return "QNA"
        if str(parent_id).startswith(("FSS-", "KICPA-")):
            return "감리사례"
    return category if category else "본문"


def _get_parent_content(parent_id: str, source: str) -> str:
    """PDR 패턴: Child 청크의 parent_id로 부모 원문 전체를 조회합니다."""
    db = _get_db()
    if source == "QNA":
        doc = db[QNA_PARENT_COLL].find_one({"_id": parent_id})
    elif source == "감리사례":
        doc = db[FINDINGS_PARENT_COLL].find_one({"_id": parent_id})
    else:
        return ""
    return doc.get("content", "") if doc else ""


def _docs_from_fused(fused_docs: list[dict]) -> list[dict]:
    """RRF 융합 결과를 RAG 통합 스키마로 변환합니다 (PDR 포함)."""
    results = []
    for doc in fused_docs:
        parent_id = doc.get("parent_id")
        source = _classify_source(parent_id, doc.get("category", ""))
        results.append({
            "source":             source,
            "chunk_id":           doc.get("chunk_id", ""),
            "parent_id":          parent_id,
            "category":           doc.get("category", ""),
            "chunk_type":         doc.get("chunk_type", ""),
            "content":            doc.get("text", ""),
            "full_content":       _get_parent_content(parent_id, source) if source != "본문" else "",
            "title":              doc.get("title", ""),
            "case_group_title":   doc.get("case_group_title", ""),
            "score":              doc.get("score", 0.0),
            "vector_score":       doc.get("vector_score", 0.0),
            "related_paragraphs": doc.get("related_paragraphs", []),
            "hierarchy":          doc.get("hierarchy", ""),
        })
    return results


# ── 메인 검색 함수 ───────────────────────────────────────────────────────────────

def search_all(query: str, limit: int = 5) -> list[dict]:
    """기본 하이브리드 검색 (Vector + BM25 + RRF) + QNA/감리사례 보조 추출."""
    query_vector = embed_query_sync(query)
    v_results    = _search_vector(query_vector, VECTOR_TOP_K)
    k_results    = _search_keyword(query, VECTOR_TOP_K // 2)
    fused_docs   = _fuse_rrf(v_results, k_results, final_k=limit)
    base_docs    = _docs_from_fused(fused_docs)

    existing_ids = {d["chunk_id"] for d in base_docs}

    qna_raw = [
        d for d in v_results
        if str(d.get("parent_id", "")).startswith("QNA-")
        and d.get("chunk_id") not in existing_ids
    ][:QNA_SUPPLEMENT]

    findings_raw = [
        d for d in v_results
        if str(d.get("parent_id", "")).startswith(("FSS-", "KICPA-"))
        and d.get("chunk_id") not in existing_ids
    ][:FINDINGS_SUPPLEMENT]

    supplement = _docs_from_fused(qna_raw + findings_raw)
    return base_docs + supplement


def search_all_hyde(query: str, limit: int = 5) -> list[dict]:
    """HyDE 폴백 검색: 가상 K-IFRS 조항 텍스트로 벡터 검색."""
    hypothetical_doc = _generate_hypothetical_doc(query)
    hyde_vector = embed_query_sync(hypothetical_doc)

    v_results = _search_vector(hyde_vector, VECTOR_TOP_K)
    k_results = _search_keyword(query, VECTOR_TOP_K)
    fused_docs = _fuse_rrf(v_results, k_results, final_k=limit)
    return _docs_from_fused(fused_docs)


if __name__ == "__main__":
    query = "밀어내기 매출 수익인식 어떻게 해?"
    results = search_all(query, limit=5)
    for r in results:
        print(f"[{r['source']}] 점수: {r['score']:.4f} | 계층: {r['hierarchy']}")

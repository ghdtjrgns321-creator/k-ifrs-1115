import re
from pymongo import MongoClient
from rank_bm25 import BM25Okapi
from langchain_upstage import UpstageEmbeddings
from app.config import settings

# ── 상수 ────────────────────────────────────────────────────────────────────────
# embed 스크립트의 PARENT_COLLECTION과 반드시 일치해야 함
QNA_PARENT_COLL      = "k-ifrs-1115-qna-parents"
FINDINGS_PARENT_COLL = "k-ifrs-1115-findings-parents"

VECTOR_TOP_K = 20  # 각 전략별 후보 수 (RRF 융합 전 풀)
RRF_K        = 60  # RRF 논문 권장값


# ── Lazy 초기화 ──────────────────────────────────────────────────────────────────
# import 시 DB 연결을 하지 않고, 첫 번째 실제 검색 호출 시 한 번만 연결합니다.
# 테스트 환경에서 .env 없이 모듈을 import해도 에러가 나지 않습니다.
_db = None
_embeddings = None

# BM25 인덱스는 최초 검색 시 MongoDB 전체 문서로 빌드 후 메모리에 캐싱합니다.
# 프로세스 재시작 시에만 재빌드됩니다.
_bm25: BM25Okapi | None = None
_bm25_corpus: list[dict] | None = None


def _get_db():
    global _db
    if _db is None:
        client = MongoClient(settings.mongo_uri)
        _db = client[settings.mongo_db_name]
    return _db


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        # 검색 시에만 query 모델 사용 (passage 모델과 혼용 금지!)
        # api_key를 명시적으로 전달 — UpstageEmbeddings는 os.environ을 직접 참조하므로
        # pydantic-settings만으로는 키가 전달되지 않을 수 있음
        _embeddings = UpstageEmbeddings(
            model=settings.embed_query_model,
            api_key=settings.upstage_api_key,
        )
    return _embeddings


# ── 개별 검색 함수 ───────────────────────────────────────────────────────────────

def _search_vector(query_vector: list, limit: int) -> list[dict]:
    """
    Atlas Vector Search: 전체 컬렉션에서 의미 유사도 검색.
    소스 분류(본문/QNA/감리사례)는 Python 후처리에서 수행합니다.
    """
    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": limit * 5,  # 넉넉하게 탐색
                "limit": limit,
            }
        },
        {"$project": {"embedding": 0, "score": {"$meta": "vectorSearchScore"}}},
    ]
    return list(_get_db()[settings.mongo_collection_name].aggregate(pipeline))


def _tokenize_ko(text: str) -> list[str]:
    """
    한국어 텍스트를 BM25용 토큰 리스트로 변환합니다.

    한국어는 조사가 붙어 "본인과", "대리인을"처럼 표현되어 단순 공백 분리로는
    "본인", "대리인" 키워드 매칭이 실패합니다.
    → 한글 연속 구간에 2-gram(바이그램)을 적용해 "본인과" → ["본인", "인과"]로
      분해함으로써 조사 포함 여부에 무관하게 핵심 어절을 잡아냅니다.
    영문·숫자·조항번호(B34, IE15 등)는 그대로 소문자 처리합니다.
    """
    tokens: list[str] = []

    # 한글 연속 구간 → 바이그램
    for word in re.findall(r'[가-힣]+', text):
        if len(word) == 1:
            tokens.append(word)
        else:
            tokens.extend(word[i:i+2] for i in range(len(word) - 1))

    # 영문·숫자·혼합 토큰 (예: B34, IE15, BM25) → 소문자
    tokens.extend(t.lower() for t in re.findall(r'[a-zA-Z0-9]+', text))

    return tokens


def _build_bm25_index() -> None:
    """
    MongoDB 전체 문서를 로드하여 로컬 BM25 인덱스를 빌드합니다.
    최초 검색 시 1회만 실행되며, 이후 _bm25/_bm25_corpus에 캐싱됩니다.
    Atlas Search 키워드 인덱스 설정 없이도 동작하며,
    한국어 바이그램 토크나이저로 조사 처리 문제를 해결합니다.
    """
    global _bm25, _bm25_corpus
    db = _get_db()
    # embedding 필드 제외 — 벡터(float 배열)가 빠지면 메모리가 크게 절약됩니다.
    docs = list(db[settings.mongo_collection_name].find({}, {"embedding": 0}))
    _bm25_corpus = docs
    corpus = [_tokenize_ko(doc.get("text", "")) for doc in docs]
    _bm25 = BM25Okapi(corpus)


def _search_keyword(query: str, limit: int) -> list[dict]:
    """
    로컬 BM25 키워드 검색 — MongoDB Atlas Search 인덱스 불필요.

    Atlas Search의 Standard Analyzer는 한국어 조사를 분리하지 못해
    "본인과" → "본인" 매칭 실패 같은 문제가 발생합니다.
    rank_bm25 + 한국어 바이그램 토크나이저로 이를 해결합니다.

    score > 0 인 문서만 반환하여 무관한 문서가 RRF 풀을 오염시키는 것을 방지합니다.
    """
    global _bm25, _bm25_corpus
    if _bm25 is None:
        _build_bm25_index()

    query_tokens = _tokenize_ko(query)
    if not query_tokens:
        return []

    scores = _bm25.get_scores(query_tokens)

    # BM25 점수가 0 초과인 문서만 추려 상위 limit개 반환
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

def _fuse_rrf(v_results: list[dict], k_results: list[dict], final_k: int) -> list[dict]:
    """
    RRF(Reciprocal Rank Fusion)로 벡터 + 키워드 결과를 융합하고
    도메인 가중치(weight_score)를 곱해 최종 순위를 결정합니다.

    RRF 공식: score = 1 / (rank + 1 + k)  → 상위일수록 점수 높음
    최종 공식: final_score = rrf_score * weight_score
    두 전략 모두에서 발견된 청크는 점수가 합산되어 순위가 크게 올라갑니다.
    """
    fused: dict[str, dict] = {}

    for rank, doc in enumerate(v_results):
        chunk_id = doc.get("chunk_id", f"v_{rank}")
        fused[chunk_id] = {
            "doc": doc,
            "rrf_score": 1.0 / (rank + 1 + RRF_K),
        }

    for rank, doc in enumerate(k_results):
        chunk_id = doc.get("chunk_id", f"k_{rank}")
        rrf = 1.0 / (rank + 1 + RRF_K)
        if chunk_id in fused:
            # 두 전략 모두 발견 → 점수 합산 (핵심 RRF 효과)
            fused[chunk_id]["rrf_score"] += rrf
        else:
            fused[chunk_id] = {"doc": doc, "rrf_score": rrf}

    # 도메인 가중치 보정 후 정렬
    ranked = []
    for data in fused.values():
        weight = float(data["doc"].get("weight_score", 1.0))
        ranked.append({**data, "final_score": data["rrf_score"] * weight})

    ranked.sort(key=lambda x: x["final_score"], reverse=True)
    return [item["doc"] for item in ranked[:final_k]]


# ── PDR Lookup ───────────────────────────────────────────────────────────────────

def _classify_source(parent_id: str | None) -> str:
    """parent_id 접두어로 문서 출처를 결정합니다."""
    if not parent_id:
        return "본문"
    if str(parent_id).startswith("QNA-"):
        return "QNA"
    if str(parent_id).startswith(("FSS-", "KICPA-")):
        return "감리사례"
    return "본문"


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


# ── 메인 검색 함수 ───────────────────────────────────────────────────────────────

def search_all(query: str, limit: int = 5) -> list[dict]:
    """
    본문 + QNA + 감리사례를 한 번에 하이브리드 검색하고 통합 스키마로 반환합니다.

    흐름:
      1. Vector Search  → 의미 유사도 기반 후보 VECTOR_TOP_K개
      2. Keyword Search → BM25 키워드 정확도 기반 후보 VECTOR_TOP_K개
      3. RRF 융합       → 두 결과를 합산하고 도메인 가중치 보정 후 limit개 추출
      4. PDR Lookup     → QNA/감리사례는 parent 원문을 추가 조회
    """
    query_vector = _get_embeddings().embed_query(query)

    v_results = _search_vector(query_vector, VECTOR_TOP_K)
    k_results = _search_keyword(query, VECTOR_TOP_K)
    fused_docs = _fuse_rrf(v_results, k_results, final_k=limit)

    results = []
    for doc in fused_docs:
        parent_id = doc.get("parent_id")
        source    = _classify_source(parent_id)

        # LangChain MongoDBAtlasVectorSearch는 page_content를 "text" 필드로 저장함
        results.append({
            "source":             source,
            "chunk_id":           doc.get("chunk_id", ""),
            "parent_id":          parent_id,
            "category":           doc.get("category", ""),    # reranker 룰 1 (카테고리 선호도)용
            "chunk_type":         doc.get("chunk_type", ""),  # reranker 룰 2 (Q/A/S 선호도)용
            "content":            doc.get("text", ""),
            "full_content":       _get_parent_content(parent_id, source) if source != "본문" else "",
            "score":              doc.get("score", 0.0),
            "related_paragraphs": doc.get("related_paragraphs", []),
            "hierarchy":          doc.get("hierarchy", ""),
        })

    return results


# ── 간단한 테스트 ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    query = "밀어내기 매출 수익인식 어떻게 해?"
    results = search_all(query, limit=5)
    for r in results:
        print(f"[{r['source']}] 점수: {r['score']:.4f} | 계층: {r['hierarchy']}")

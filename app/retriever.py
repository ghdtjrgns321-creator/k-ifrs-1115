import re
from pymongo import MongoClient
from rank_bm25 import BM25Okapi
from langchain_upstage import UpstageEmbeddings
from langchain_core.messages import HumanMessage
from app.config import settings

# ── 상수 ────────────────────────────────────────────────────────────────────────
QNA_PARENT_COLL      = "k-ifrs-1115-qna-parents"
FINDINGS_PARENT_COLL = "k-ifrs-1115-findings-parents"

VECTOR_TOP_K        = 100  # 후보 풀 확장: QNA/감리사례가 RRF 상위에 못 오를 때 보조 풀 확보
RRF_K               = 60   # RRF 논문 권장값
QNA_SUPPLEMENT      = 15   # QNA 보조 최대 추가 수 (Reranker가 관련 없으면 자동 제외)
FINDINGS_SUPPLEMENT = 15   # 감리사례 보조 최대 추가 수

# HyDE 폴백 전용 프롬프트
# grade 통과 문서가 부족할 때만 사용 — 항상 실행하면 기존 검색을 방해함
_HYDE_PROMPT = """\
당신은 K-IFRS 제1115호 전문가입니다.
아래 질문에 답변하는 데 필요한 기준서 조항의 내용을 작성하세요.

규칙:
- 실제 문단 번호(예: 문단 31, 문단 B58)와 회계 전문 용어를 반드시 포함하세요.
- 기준서 본문 스타일로 3~5문장 이내로 간결하게 작성하세요.

질문: {query}

조항 내용:"""


# ── Lazy 초기화 ──────────────────────────────────────────────────────────────────
_db = None
_embeddings = None
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
        _embeddings = UpstageEmbeddings(
            model=settings.embed_query_model,
            api_key=settings.upstage_api_key,
        )
    return _embeddings


def _generate_hypothetical_doc(query: str) -> str:
    """
    HyDE: 질문에 대한 가상 K-IFRS 조항 텍스트를 생성합니다.

    grade 통과 문서가 부족할 때 폴백으로만 호출됩니다.
    실패 시 원본 쿼리로 폴백하여 파이프라인이 중단되지 않습니다.
    """
    # 순환 import 방지를 위해 함수 내부에서 import
    # get_hyde_llm: 15초 짧은 타임아웃 → 실패 시 원본 쿼리로 즉시 폴백
    from app.llm import get_hyde_llm
    try:
        llm = get_hyde_llm()
        response = llm.invoke([HumanMessage(content=_HYDE_PROMPT.format(query=query))])
        result = response.content.strip()
        return result if result else query
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
    """
    한국어 텍스트를 BM25용 토큰 리스트로 변환합니다.
    한글 연속 구간에 2-gram을 적용해 조사 포함 여부와 무관하게 핵심 어절을 잡습니다.
    """
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
    """청크 ID에서 섹션 prefix와 번호를 분리합니다.

    [A-Z]{0,2}로 0~2자리 대문자를 허용하여 모든 섹션을 올바르게 파싱합니다:
      '1115-31'   → ('1115-', 31)    # 본문
      '1115-B44'  → ('1115-B', 44)   # 적용지침B
      '1115-A2'   → ('1115-A', 2)    # 용어정의
      '1115-IE65' → ('1115-IE', 65)  # 적용사례
      '1115-BC44' → ('1115-BC', 44)  # 결론도출근거

    prefix가 다르면 절대 같은 클러스터로 묶이지 않으므로
    본문(1115-)과 적용지침(1115-B), 적용사례(1115-IE), 결론도출근거(1115-BC)가
    같은 번호를 가져도 독립적으로 처리됩니다.
    """
    m = re.match(r'^([\w]+-[A-Z]{0,2})(\d+)$', chunk_id)
    return (m.group(1), int(m.group(2))) if m else None


def _apply_window_boost(fused: dict, window: int = 3, boost: float = 0.15) -> None:
    """같은 섹션(prefix)의 ±window 이내 청크가 1개 이상 동반되면 rrf_score를 부스팅합니다.

    왜 하는가:
      BM25/벡터 점수는 청크 단독 품질만 반영하지만, 인접 문단이 함께 검색되면
      해당 섹션이 질문과 구조적으로 관련됨을 의미합니다.
      클러스터 부스팅으로 논리적으로 연속된 조항 그룹을 Core Docs 상단에 노출합니다.

    대상: VECTOR_TOP_K=100 풀 내 이미 올라온 청크만 — 추가 DB 쿼리 없음.
    """
    # prefix → [(번호, chunk_id)] 매핑 수집
    prefix_map: dict[str, list[tuple[int, str]]] = {}
    for cid in fused:
        parsed = _parse_chunk_num(cid)
        if parsed:
            prefix, num = parsed
            prefix_map.setdefault(prefix, []).append((num, cid))

    # 각 청크의 ±window 이내 동반 청크 수를 계산하여 부스팅
    for prefix, items in prefix_map.items():
        if len(items) < 2:
            continue
        for num_i, cid_i in items:
            cluster_count = sum(
                1 for num_j, _ in items
                if num_j != num_i and abs(num_j - num_i) <= window
            )
            if cluster_count >= 1:
                # 동반 청크 수에 비례하여 점수 상승 (최대 3개 동반 시 +0.45)
                fused[cid_i]["rrf_score"] += boost * cluster_count


def _fuse_rrf(v_results: list[dict], k_results: list[dict], final_k: int) -> list[dict]:
    """RRF로 벡터 + 키워드 결과를 융합하고 도메인 가중치를 적용합니다.

    섹션 내 벡터 정렬을 위해 각 doc에 vector_score를 첨부합니다.
    BM25 전용 문서(벡터 결과에 없는)는 vector_score=0.0으로 처리합니다.
    """
    # 벡터 점수 조회 테이블 — 섹션 내 정렬 기준으로 활용
    v_score_map = {doc.get("chunk_id", f"v_{i}"): doc.get("score", 0.0)
                   for i, doc in enumerate(v_results)}

    fused: dict[str, dict] = {}

    for rank, doc in enumerate(v_results):
        chunk_id = doc.get("chunk_id", f"v_{rank}")
        fused[chunk_id] = {
            "doc": doc,
            "rrf_score": 1.0 / (rank + 1 + RRF_K),
            "vector_score": doc.get("score", 0.0),  # Atlas vectorSearchScore 보존
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
                "vector_score": v_score_map.get(chunk_id, 0.0),  # BM25 전용 = 0.0
            }

    # 인접 문단 클러스터 부스팅 — final_score 계산 전에 적용해야 효과가 반영됩니다.
    _apply_window_boost(fused)

    ranked = []
    for data in fused.values():
        weight = float(data["doc"].get("weight_score", 1.0))
        ranked.append({**data, "final_score": data["rrf_score"] * weight})

    ranked.sort(key=lambda x: x["final_score"], reverse=True)

    # 섹션 내 벡터 정렬에 쓸 vector_score를 각 doc에 첨부
    for item in ranked[:final_k]:
        item["doc"]["vector_score"] = item["vector_score"]

    return [item["doc"] for item in ranked[:final_k]]


# ── PDR Lookup ───────────────────────────────────────────────────────────────────

def _classify_source(parent_id: str | None, category: str = "") -> str:
    """parent_id 접두어와 category로 문서 출처를 결정합니다.

    QNA/감리사례는 parent_id 패턴으로 식별.
    기준서 문서는 category를 그대로 사용하여 올바른 아코디언 그룹에 배치합니다.
    (category 없이 "본문"으로 뭉뚱그리면 결론도출근거·적용사례IE 등이 잘못된 그룹에 배치됨)
    """
    if parent_id:
        if str(parent_id).startswith("QNA-"):
            return "QNA"
        if str(parent_id).startswith(("FSS-", "KICPA-")):
            return "감리사례"
    # 기준서 문서: category로 세밀 분류 (본문/적용지침B/결론도출근거/적용사례IE/용어정의/시행일)
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
        source    = _classify_source(parent_id, doc.get("category", ""))
        results.append({
            "source":             source,
            "chunk_id":           doc.get("chunk_id", ""),
            "parent_id":          parent_id,
            "category":           doc.get("category", ""),
            "chunk_type":         doc.get("chunk_type", ""),
            "content":            doc.get("text", ""),
            "full_content":       _get_parent_content(parent_id, source) if source != "본문" else "",
            "title":              doc.get("title", ""),       # 08-generate-titles.py 마이그레이션으로 추가된 필드
            "case_group_title":   doc.get("case_group_title", ""),  # IE 사례 그룹핑용
            "score":              doc.get("score", 0.0),
            "vector_score":       doc.get("vector_score", 0.0),  # 섹션 내 정렬 기준
            "related_paragraphs": doc.get("related_paragraphs", []),
            "hierarchy":          doc.get("hierarchy", ""),
        })
    return results


# ── 메인 검색 함수 ───────────────────────────────────────────────────────────────

def search_all(query: str, limit: int = 5) -> list[dict]:
    """
    기본 하이브리드 검색 (Vector + BM25 + RRF) + QNA/감리사례 보조 추출.

    기준서 본문이 많아 QNA/감리사례가 RRF top N에서 밀려나는 문제를 해결합니다.
    벡터 풀(100개)에서 Python 필터로 각각 최대 15개를 추가하고,
    Cohere Reranker가 최종 정렬 시 관련 없는 문서는 자동으로 제외합니다.
    """
    query_vector = _get_embeddings().embed_query(query)
    v_results    = _search_vector(query_vector, VECTOR_TOP_K)         # 100개
    k_results    = _search_keyword(query, VECTOR_TOP_K // 2)          # BM25는 50개 유지
    fused_docs   = _fuse_rrf(v_results, k_results, final_k=limit)
    base_docs    = _docs_from_fused(fused_docs)

    # RRF 결과에 없는 QNA/감리사례를 벡터 풀에서 보조 추출
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
    """
    HyDE 폴백 검색: grade 통과 문서가 부족할 때만 호출됩니다.

    원본 쿼리 대신 LLM이 생성한 가상 K-IFRS 조항 텍스트로 벡터 검색합니다.
    BM25는 원본 쿼리를 그대로 사용해 키워드 매칭 품질을 유지합니다.

    왜 폴백에만 쓰는가?
      항상 적용하면 잘 작동하는 케이스에서 오히려 노이즈를 추가합니다.
      첫 검색이 실패(grade < 3)했을 때만 다른 관점의 검색을 시도하는 것이 안전합니다.
    """
    hypothetical_doc = _generate_hypothetical_doc(query)
    hyde_vector = _get_embeddings().embed_query(hypothetical_doc)

    # 벡터: HyDE 가상 답변 벡터 / BM25: 원본 쿼리 (키워드 매칭 유지)
    v_results = _search_vector(hyde_vector, VECTOR_TOP_K)
    k_results = _search_keyword(query, VECTOR_TOP_K)
    fused_docs = _fuse_rrf(v_results, k_results, final_k=limit)
    return _docs_from_fused(fused_docs)


# ── 간단한 테스트 ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    query = "밀어내기 매출 수익인식 어떻게 해?"
    results = search_all(query, limit=5)
    for r in results:
        print(f"[{r['source']}] 점수: {r['score']:.4f} | 계층: {r['hierarchy']}")

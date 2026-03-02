# app/nodes/format.py
import re
import math
from app.state import RAGState
from app.retriever import _get_db, _get_embeddings, FINDINGS_PARENT_COLL
from app.config import settings

# LLM 답변에서 문단 번호를 추출하는 정규식 (예: 문단 31, 문단 B34)
_PARAGRAPH_RE = re.compile(r"문단\s*([A-Z]*\d+)")

# 모든 주제에 범용으로 등장하는 기본 원칙 문단 — 단독으로 매칭하면 노이즈가 많음
GENERIC_PARAGRAPHS = {"9", "12", "22", "27", "31", "32", "33", "38"}

# 이 점수 미만인 사례는 폐기 (사용자 질문과 관련 없는 사례 필터링)
FINDINGS_SIMILARITY_THRESHOLD = 0.80


def _cosine_similarity(a: list, b: list) -> float:
    """두 벡터의 코사인 유사도를 계산합니다. numpy 없이 순수 Python으로 구현."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _find_best_findings_case(paragraphs: set, user_query: str) -> dict | None:
    """
    문단 번호로 후보 감리사례를 전부 가져온 뒤,
    사용자 질문과의 벡터 유사도가 임계값 이상인 사례 중 가장 유사한 것을 반환.

    흐름:
      1. Child 컬렉션에서 related_paragraphs 매칭 후보 전부 조회
         (chunk_type="question" 만 사용 — 사용자 질문과 의미 유사도가 가장 높음)
      2. 사용자 질문을 임베딩 (Upstage query 모델)
      3. 각 후보 벡터와 코사인 유사도 계산
      4. FINDINGS_SIMILARITY_THRESHOLD(0.80) 미만이면 폐기
      5. 가장 높은 점수 사례의 Parent 원문을 조회해 반환
    """
    db = _get_db()
    child_coll = db[settings.mongo_collection_name]
    parent_coll = db[FINDINGS_PARENT_COLL]

    # 감리사례 child 문서만 조회 (parent_id 접두어로 구분)
    # chunk_type="question"만 사용 — 배경 및 질의 부분이 사용자 질문과 의미상 가장 유사
    candidates = list(child_coll.find(
        {
            "related_paragraphs": {"$in": list(paragraphs)},
            "parent_id": {"$regex": "^(FSS-|KICPA-)"},
            "chunk_type": "question",
        },
        {"embedding": 1, "parent_id": 1},  # 유사도 계산에 필요한 필드만 가져옴
    ))

    if not candidates:
        return None

    # 사용자 질문 임베딩 (retriever.py의 싱글턴 재사용)
    query_vector = _get_embeddings().embed_query(user_query)

    # 코사인 유사도 계산 → 가장 높은 점수 사례 선택
    best_parent_id = None
    best_score = 0.0

    for doc in candidates:
        doc_vector = doc.get("embedding", [])
        if not doc_vector:
            continue
        score = _cosine_similarity(query_vector, doc_vector)
        if score > best_score:
            best_score = score
            best_parent_id = doc.get("parent_id")

    # 임계값 미만이면 노이즈로 판단하여 폐기
    if best_score < FINDINGS_SIMILARITY_THRESHOLD or best_parent_id is None:
        return None

    # Parent 원문 조회
    parent = parent_coll.find_one({"_id": best_parent_id})
    if not parent:
        return None

    hierarchy = parent.get("metadata", {}).get("hierarchy", "")
    case_title = hierarchy.split(">")[-1].strip() if hierarchy else "관련 감리지적사례"

    return {
        "title": case_title,
        "hierarchy": hierarchy,
        "content": parent.get("content", ""),
        "score": round(best_score, 4),
    }


def format_response(state: RAGState):
    """LLM 답변에 감리사례 넛지를 추가합니다."""

    answer = state.get("answer", "")
    cited_sources = state.get("cited_sources", [])
    # 원래 사용자 질문 — 감리사례 벡터 유사도 계산에 사용
    user_query = state.get("standalone_query", "")

    # 1. 문단 번호 수집 (cited_sources + 답변 텍스트 두 곳에서)
    paragraphs = set()
    for src in cited_sources:
        for p in src.get("related_paragraphs", []):
            paragraphs.add(str(p))
    for match in _PARAGRAPH_RE.finditer(answer):
        paragraphs.add(match.group(1))

    # 2. 구체적 쟁점 문단 우선 — 범용 문단만 남은 경우 2순위로 사용
    specific_paras = {p for p in paragraphs if p not in GENERIC_PARAGRAPHS}
    generic_paras  = {p for p in paragraphs if p in GENERIC_PARAGRAPHS}
    search_paras   = specific_paras or generic_paras  # 1순위 없으면 2순위

    # 3. 벡터 유사도 기반 감리사례 매칭
    nudge_text = ""
    findings_case = None

    if search_paras and user_query:
        findings_case = _find_best_findings_case(search_paras, user_query)
        if findings_case:
            case_title = findings_case["title"]
            nudge_text = (
                f"\n\n💡 **덧붙임:** 금융감독원 지적사례[{case_title}]가 존재합니다. "
                f"클릭하여 확인해보세요."
            )

    return {"answer": answer + nudge_text, "findings_case": findings_case}

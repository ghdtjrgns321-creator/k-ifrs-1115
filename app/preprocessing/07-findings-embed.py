import io
import sys

# Windows cp949 환경에서 이모지 출력 시 UnicodeEncodeError 방지
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import json
import time
import re
import os
from pymongo import MongoClient
from app.config import settings
from app.embeddings import embed_texts_sync

sys.stdout.reconfigure(encoding="utf-8")

# ── 상수 ────────────────────────────────────────────────────────────────────────
INPUT_FILE = "data/findings/findings-final.json"
CHILD_COLLECTION = settings.mongo_collection_name
PARENT_COLLECTION = "k-ifrs-1115-findings-parents"
FINDINGS_WEIGHT = 1.2


def title_for(metadata: dict) -> str:
    """임베딩 신호로 앞세울 제목.

    Why: 제목(감독기관이 단 실무 요약)은 일상어 질문과의 매칭을 끌어올리는 1급 신호.
    QNA는 metadata.title, 감리사례는 title 필드가 없어 hierarchy 말단(사례 제목)을 쓴다.
    """
    t = metadata.get("title")
    if t and t.strip():
        return t.strip()
    hierarchy = metadata.get("hierarchy", "")
    return hierarchy.split(">")[-1].strip() if ">" in hierarchy else ""


def split_finding_to_children(
    finding_id: str, full_text: str, metadata: dict
) -> list[dict]:
    """감리지적사례 content를 Q/A/S 3단 분할.

    Why: 원문 5부 구조(회사의 회계처리/위반/지적근거/감사절차/시사점)와
    구 Q·A·S 양식(배경 및 질의/회신/참고자료)을 모두 지원한다.
    chunk_type(question/answer/supplementary)은 reranker 가중치(A>S>Q)와 직결되므로 보존.
    매핑 — Q(사실관계, 답 아님)=회사처리+위반, A(핵심 판단)=지적근거, S(보충)=감사절차+시사점.
    """
    # 서두 변환: "레퍼런스 [ID] 제목..." → "**[ID]** 제목..."
    full_text = re.sub(
        r"^레퍼런스\s*\[([^\]]+)\]\s*([^\n]+)\n(관련\s*회계\s*기준[^\n]*)(?:\n출처:[^\n]*)?\n본문\n?",
        r"**[\1]** \2\n\3\n\n",
        full_text,
    )

    hierarchy = metadata.get("hierarchy", "")

    # ── ## 섹션 파싱 ────────────────────────────────────────────────
    raw_parts = re.split(r"\n##\s*", full_text)
    preamble = raw_parts[0].strip()  # **[ID]** 제목 + 관련 회계기준
    sections: dict[str, str] = {}
    for part in raw_parts[1:]:
        nl = part.find("\n")
        title = (part[:nl] if nl > 0 else part).strip()
        body = (part[nl + 1 :] if nl > 0 else "").strip()
        if body:
            sections[title] = body

    def pick(*titles: str) -> str:
        return "\n\n".join(sections[t] for t in titles if t in sections).strip()

    # ── 양식 감지 → Q/A/S 매핑 ──────────────────────────────────────
    if "회사의 회계처리" in sections:  # 원문 5부 양식
        q_body = pick(
            "회사의 회계처리", "회계기준 위반 지적 내용", "회계기준 위반 내용"
        )
        a_body = pick("지적 근거 및 판단 내용", "지적근거 및 판단 내용")
        s_body = pick("감사절차 미흡사항", "시사점")
    else:  # 구 Q·A·S 양식
        q_body = pick("배경 및 질의")
        a_body = pick("회신")
        s_body = pick("참고자료")

    q_text = f"{preamble}\n\n{q_body}".strip()

    children = [
        {
            "text": f"[문맥: {hierarchy} > 배경 및 질의]\n{q_text}",
            "metadata": {
                **metadata,
                "parent_id": finding_id,
                "chunk_type": "question",
                "chunk_id": f"{finding_id}_Q",
            },
        }
    ]
    if a_body:
        children.append(
            {
                "text": f"[문맥: {hierarchy} > 감리지적내용]\n{a_body}",
                "metadata": {
                    **metadata,
                    "parent_id": finding_id,
                    "chunk_type": "answer",
                    "chunk_id": f"{finding_id}_A",
                },
            }
        )
    if s_body:
        children.append(
            {
                "text": f"[문맥: {hierarchy} > 참고기준]\n{s_body}",
                "metadata": {
                    **metadata,
                    "parent_id": finding_id,
                    "chunk_type": "supplementary",
                    "chunk_id": f"{finding_id}_S",
                },
            }
        )

    return children


def load_findings_to_atlas():
    if not os.path.exists(INPUT_FILE):
        print(f"파일을 찾을 수 없습니다: {INPUT_FILE}")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_findings = json.load(f)

    client = MongoClient(settings.mongo_uri)
    db = client[settings.mongo_db_name]

    parent_docs = []
    child_docs = []

    for finding in raw_findings:
        finding_id = finding["id"]
        full_text = finding["content"]
        metadata = finding["metadata"]

        metadata_with_weight = {**metadata, "weight_score": FINDINGS_WEIGHT}

        parent_docs.append(
            {
                "_id": finding_id,
                "content": full_text,
                "metadata": metadata_with_weight,
            }
        )

        children = split_finding_to_children(
            finding_id, full_text, metadata_with_weight
        )
        child_docs.extend(children)

    # STEP 1. Parent 컬렉션
    parent_coll = db[PARENT_COLLECTION]

    print("1. 기존 Parent 컬렉션을 초기화합니다...")
    p_del = parent_coll.delete_many({})
    print(f" -> {p_del.deleted_count}개 삭제 완료.")

    print(f"2. 감리사례 원본 {len(parent_docs)}개를 저장합니다...")
    parent_coll.insert_many(parent_docs)
    print(" -> Parent 적재 완료!")

    # STEP 2. Child 컬렉션
    child_coll = db[CHILD_COLLECTION]

    print("\n3. 기존 Findings Child 데이터 삭제합니다 (본문 + QNA 보호)...")
    c_del = child_coll.delete_many({"parent_id": {"$regex": "^(FSS-|KICPA-)"}})
    print(f" -> {c_del.deleted_count}개 삭제 완료.")

    # STEP 3. 벡터 임베딩 & 적재
    print(f"\n4. 총 {len(child_docs)}개 Child 청크(Q/A/S) 벡터 임베딩을 시작합니다...")

    success_count = 0
    skipped_docs = []

    for doc in child_docs:
        parent_id = doc["metadata"].get("parent_id")
        chunk_type = doc["metadata"].get("chunk_type")
        text_length = len(doc["text"])

        try:
            # 제목을 임베딩 입력 맨 앞에 승격(저장 text는 원문 유지) — 실무 요약이 검색 신호 1급
            title = title_for(doc["metadata"])
            embed_input = f"[{title}] {doc['text']}" if title else doc["text"]
            vector = embed_texts_sync([embed_input], settings.embed_passage_model)[0]
            mongo_doc = {
                "text": doc["text"],
                "embedding": vector,
                **doc["metadata"],
            }
            child_coll.insert_one(mongo_doc)
            success_count += 1
            if success_count % 10 == 0:
                print(f"  -> {success_count} / {len(child_docs)} 개 적재 완료")
            time.sleep(0.05)

        except Exception as e:
            print(f"\n[SKIP] {parent_id}의 {chunk_type} 파트 적재 실패! ({e})")
            skipped_docs.append(
                {
                    "parent_id": parent_id,
                    "chunk_type": chunk_type,
                    "length": text_length,
                }
            )
            continue

    # STEP 4. 보고서
    print(f"\n{'=' * 65}")
    print("감리지적사례 PDR 적재 최종 보고서")
    print(f"{'=' * 65}")
    print(f"성공: {success_count}개 청크 (Vector DB 안착)")
    print(f"스킵: {len(skipped_docs)}개 청크 (API 용량 초과)")

    if skipped_docs:
        print("\n[스킵된 문서 목록]")
        for skip in skipped_docs:
            print(
                f"  - ID: {skip['parent_id']} | 타입: {skip['chunk_type']} | 길이: {skip['length']:,.0f}자"
            )

    print(f"{'=' * 65}")
    client.close()


if __name__ == "__main__":
    load_findings_to_atlas()

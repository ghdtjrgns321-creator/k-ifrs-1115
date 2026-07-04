import json
import re
import sys
import time
from pymongo import MongoClient, UpdateOne
from pymongo.errors import BulkWriteError
from app.config import settings
from app.embeddings import embed_texts_sync

IE_GROUP_MAP_FILE = "data/ontology/ie-group-concept-map.json"


def _parse_ie(para_num: str):
    """'IE65A' -> (65, 'A'), 'IE3' -> (3, ''). IE 형식이 아니면 None(서두·주석)."""
    m = re.match(r"^IE(\d+)([A-Z]*)$", str(para_num).strip())
    return (int(m.group(1)), m.group(2)) if m else None


def load_ie_group_ranges():
    """확정 맵의 ref 범위(IE2~IE17 등)를 그룹명 조회용 (start, end, group) 리스트로 파싱.

    Why: 그룹명을 하드코딩하지 않고 사용자 승인된 맵(ie-group-concept-map.json)에서
    구동한다. paraNum의 IE 번호가 어느 범위에 드는지로 그룹을 결정 → 데이터가 소스.
    """
    with open(IE_GROUP_MAP_FILE, "r", encoding="utf-8") as f:
        entries = json.load(f)["map"]
    ranges = []
    for e in entries:
        start_str, end_str = e["ref"].split("~")
        ranges.append((_parse_ie(start_str), _parse_ie(end_str), e["group"]))
    return ranges


def ie_group_for(para_num: str, ranges) -> str:
    """paraNum이 속한 IE 그룹명. 서두·주석(IE 번호 없음)이면 ''."""
    key = _parse_ie(para_num)
    if key is None:
        return ""
    for start, end, group in ranges:
        if start <= key <= end:
            return group
    return ""


def build_ie_prefix(metadata: dict, ranges) -> str:
    """IE 적용사례 청크의 임베딩 입력 앞에 붙일 그룹명·사례제목 신호.

    Why: 검색어(일상어)와 사례를 잇는 1급 신호는 사례가 속한 주제 그룹과 사례 제목.
    - 그룹+사례: '[변동대가 추정치의 제약 > 사례 23: ...] '
    - 그룹만(사례 서두, 예 IE2): '[계약의 식별] '
    - 둘 다 없음(적용사례 전체 서두, IE1·웩42): '' (prefix 없음)
    저장 text는 원문 유지, 임베딩 입력에만 반영(과제 2와 동일 원칙).
    """
    if metadata.get("category") != "적용사례IE":
        return ""
    group = ie_group_for(metadata.get("paraNum", ""), ranges)
    if not group:
        return ""
    case = (metadata.get("case_group_title") or "").strip()
    return f"[{group} > {case}] " if case else f"[{group}] "


def _embed_batch_with_retry(inputs: list[str], max_retries: int = 6):
    """배치 임베딩 + 지수 백오프 재시도.

    Why: 단건 호출 1298회는 Upstage 누적 처리량(RPM/TPM) 한도를 넘어 대량 실패한다.
    배치(100건/호출)로 호출 수를 100배 줄이고, 레이트리밋(429 등) 시 백오프 후 재시도한다.
    """
    delay = 2.0
    for attempt in range(max_retries):
        try:
            return embed_texts_sync(inputs, settings.embed_passage_model)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            print(
                f"  [재시도 {attempt + 1}/{max_retries}] 임베딩 실패({type(e).__name__}), {delay:.0f}s 대기"
            )
            time.sleep(delay)
            delay = min(delay * 2, 60)


def _fallback_insert(collection, doc) -> bool:
    """배치 실패분을 단건 임베딩+삽입으로 재시도. 성공 시 True.

    Why: 폴백도 레이트리밋 대상이므로 호출부에서 호출 간 sleep을 준다(여기선 삽입만).
    """
    try:
        vector = _embed_batch_with_retry([doc["embed_input"]])[0]
        collection.insert_one(
            {"text": doc["text"], "embedding": vector, **doc["metadata"]}
        )
        return True
    except Exception as e:
        print(
            f"  [폴백 실패] {doc['metadata'].get('chunk_id', 'unknown')}: {type(e).__name__}"
        )
        return False


def load_main_text_to_atlas_safe():
    INPUT_FILE = "data/web/kifrs-1115-chunks.json"

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_chunks = json.load(f)

    # Upstage 임베딩 최대 4000 토큰 ≈ 한국어 약 3000자
    MAX_EMBED_CHARS = 3000

    documents = []
    for chunk in raw_chunks:
        metadata = chunk["metadata"].copy()
        metadata["chunk_id"] = chunk["id"]
        hierarchy_context = metadata.get("hierarchy", "")
        content = chunk["content"]
        contextual_text = f"[문맥: {hierarchy_context}]\n{content}"
        if len(contextual_text) > MAX_EMBED_CHARS:
            contextual_text = contextual_text[:MAX_EMBED_CHARS]
            metadata["truncated"] = True
        documents.append({"text": contextual_text, "metadata": metadata})

    ie_group_ranges = load_ie_group_ranges()

    client = MongoClient(settings.mongo_uri)
    collection = client[settings.mongo_db_name][settings.mongo_collection_name]

    # 기존 title 필드 백업 (08-generate-titles.py로 생성된 LLM 제목 보존)
    existing_titles = {
        doc["chunk_id"]: doc["title"]
        for doc in collection.find(
            {
                "stdNum": "1115",
                "parent_id": {"$exists": False},
                "title": {"$exists": True, "$ne": ""},
            },
            {"chunk_id": 1, "title": 1, "_id": 0},
        )
        if "chunk_id" in doc and "title" in doc
    }
    print(f"기존 LLM 제목 백업: {len(existing_titles)}개")

    print("기존 데이터 삭제 중 (기준서 본문 1115호만 타기팅)...")
    collection.delete_many(
        {
            "stdNum": "1115",
            "parent_id": {"$exists": False},
        }
    )
    print("기준서 본문(1115호) 기존 데이터 삭제 완료.")

    # 임베딩 입력 사전 구성: IE 사례는 그룹명·사례제목 prefix 승격(저장 text는 원문 유지)
    for doc in documents:
        prefix = build_ie_prefix(doc["metadata"], ie_group_ranges)
        embed_input = f"{prefix}{doc['text']}" if prefix else doc["text"]
        if len(embed_input) > MAX_EMBED_CHARS:
            embed_input = embed_input[:MAX_EMBED_CHARS]
        doc["embed_input"] = embed_input

    batch_size = settings.embed_batch_size
    print(f"배치 단위({batch_size}) 적재 시작...")

    success_count = 0
    error_chunks = []

    for start in range(0, len(documents), batch_size):
        batch = documents[start : start + batch_size]
        inputs = [d["embed_input"] for d in batch]

        # 1) 임베딩 실패(삽입 전) → 배치 전체 개별 폴백. 중복 위험 없음
        try:
            vectors = _embed_batch_with_retry(inputs)
        except Exception as e:
            print(
                f"\n[임베딩 실패] {start}~{start + len(batch)} ({type(e).__name__}) → 개별 폴백"
            )
            for doc in batch:
                if _fallback_insert(collection, doc):
                    success_count += 1
                else:
                    error_chunks.append(doc["metadata"].get("chunk_id", "unknown"))
                time.sleep(0.1)  # 폴백도 레이트리밋 대상
            continue

        # 2) 삽입: ordered=False는 부분 성공을 살리되 BulkWriteError를 던짐.
        #    이미 삽입된 문서는 건드리지 않고 실패 인덱스만 재시도(중복 삽입 방지)
        mongo_docs = [
            {"text": d["text"], "embedding": v, **d["metadata"]}
            for d, v in zip(batch, vectors)
        ]
        try:
            collection.insert_many(mongo_docs, ordered=False)
            success_count += len(mongo_docs)
        except BulkWriteError as bwe:
            failed_idx = {err["index"] for err in bwe.details.get("writeErrors", [])}
            success_count += len(mongo_docs) - len(failed_idx)
            print(f"\n[부분 삽입 실패] 배치 {start}: {len(failed_idx)}건 재시도")
            for idx in failed_idx:
                if _fallback_insert(collection, batch[idx]):
                    success_count += 1
                else:
                    error_chunks.append(
                        batch[idx]["metadata"].get("chunk_id", "unknown")
                    )
                time.sleep(0.1)
        print(f"  -> {success_count} / {len(documents)} 개 적재 완료")
        time.sleep(0.2)

    print(f"\n적재 완료! 총 {success_count}개의 데이터가 클라우드에 올라갔습니다.")
    if error_chunks:
        print(f"[실패 청크 목록] ({len(error_chunks)}개): {error_chunks}")

    # 백업해둔 LLM 제목 복원
    if existing_titles:
        print(f"\nLLM 제목 복원 중... ({len(existing_titles)}개)")
        ops = [
            UpdateOne({"chunk_id": k}, {"$set": {"title": v}})
            for k, v in existing_titles.items()
        ]
        result = collection.bulk_write(ops, ordered=False)
        print(f"LLM 제목 복원 완료: {result.modified_count}개")

    client.close()
    # 삭제 후 재적재 도중 일부라도 실패하면 검색 품질에 직접 영향 → 운영자가 즉시 인지하도록 논-제로 종료
    return len(error_chunks)


if __name__ == "__main__":
    failed = load_main_text_to_atlas_safe()
    if failed:
        sys.exit(1)

# app/preprocessing/12-summary-embed.py
# topics.json의 qna_descs + finding_descs 서머리를 임베딩하여 JSON 저장.
# 출력: data/topic-curation/summary-embeddings.json
#
# 용도: retriever/format에서 쿼리와 코사인 유사도로 QNA/감리사례 매칭

import json
from pathlib import Path
from app.embeddings import embed_texts_sync
from app.config import settings

TOPICS_PATH = Path("data/topic-curation/topics.json")
OUTPUT_PATH = Path("data/topic-curation/summary-embeddings.json")


def main():
    raw = json.loads(TOPICS_PATH.read_text(encoding="utf-8"))

    # 서머리 수집: {id: {type, topic, desc}}
    entries: dict[str, dict] = {}
    for topic_name, topic_data in raw.items():
        for qid, desc in topic_data.get("qna", {}).get("qna_descs", {}).items():
            entries[qid] = {"type": "qna", "topic": topic_name, "desc": desc}
        for fid, desc in topic_data.get("findings", {}).get("finding_descs", {}).items():
            entries[fid] = {"type": "finding", "topic": topic_name, "desc": desc}

    if not entries:
        print("서머리가 없습니다.")
        return

    ids = list(entries.keys())
    texts = [entries[k]["desc"] for k in ids]
    print(f"임베딩 대상: {len(texts)}건 (QNA + 감리사례)")

    # 배치 임베딩 (passage 모드)
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), settings.embed_batch_size):
        batch = texts[i : i + settings.embed_batch_size]
        all_embeddings.extend(embed_texts_sync(batch))
        print(f"  배치 {i // settings.embed_batch_size + 1} 완료 ({len(batch)}건)")

    # 결과 조립
    result = {}
    for idx, doc_id in enumerate(ids):
        result[doc_id] = {**entries[doc_id], "embedding": all_embeddings[idx]}

    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(f"저장 완료: {OUTPUT_PATH} ({len(result)}건)")


if __name__ == "__main__":
    main()

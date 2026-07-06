"""토픽 레벨 임베딩 생성: judgment_goal + summary → topic-embeddings.json

사용법:
  PYTHONPATH=. uv run --env-file .env python app/preprocessing/13-topic-embed.py

Why: tree_matcher가 keyword 매칭에만 의존하면 일상 언어 질문에서 토픽 매칭 실패.
     judgment_goal + summary를 임베딩해두면 쿼리와 의미적 유사도로 토픽 매칭 가능.
"""
import json
from pathlib import Path

from app.domain.decision_trees import MASTER_DECISION_TREES
from app.embeddings import embed_texts_sync

TOPICS_JSON = Path("data/topic-curation/topics.json")
OUTPUT_PATH = Path("data/topic-curation/topic-embeddings.json")


def main():
    # topics.json에서 토픽별 summary 로드
    topic_summaries: dict[str, str] = {}
    valid_topic_keys: set[str] = set()
    if TOPICS_JSON.exists():
        raw = json.loads(TOPICS_JSON.read_text(encoding="utf-8"))
        valid_topic_keys = set(raw.keys())
        for name, data in raw.items():
            topic_summaries[name] = data.get("main_and_bc", {}).get("summary", "")

    # 각 토픽의 임베딩용 텍스트 구성:
    # judgment_goal + trigger_keywords + checklist + summary
    # Why: judgment_goal만으로는 일상 언어 질문과 의미적 거리가 너무 멀어
    #       trigger_keywords와 checklist로 의미 공간을 확장해야 함
    texts: list[str] = []
    names: list[str] = []
    skipped: list[str] = []
    for topic_name, data in MASTER_DECISION_TREES.items():
        # topics.json에 없는 토픽은 제외 — orphaned 임베딩 방지
        if valid_topic_keys and topic_name not in valid_topic_keys:
            skipped.append(topic_name)
            continue
        goal = data["1_routing"]["judgment_goal"]
        triggers = ", ".join(data["1_routing"]["trigger_keywords"])
        checklist = " ".join(data["2_checklist"])[:300]
        summary = topic_summaries.get(topic_name, "")[:200]
        embed_text = (
            f"[{topic_name}] {goal}. "
            f"관련 키워드: {triggers}. "
            f"{checklist} "
            f"{summary}"
        )
        texts.append(embed_text)
        names.append(topic_name)
    if skipped:
        print(f"⚠️  topics.json에 없는 토픽 {len(skipped)}건 제외: {skipped}")

    print(f"토픽 {len(texts)}개 임베딩 중...")
    embeddings = embed_texts_sync(texts)
    print(f"임베딩 완료: {len(embeddings)}개, 차원={len(embeddings[0])}")

    # JSON 저장
    result = {}
    for name, text, emb in zip(names, texts, embeddings):
        result[name] = {
            "text": text,
            "embedding": emb,
        }

    OUTPUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"저장: {OUTPUT_PATH} ({len(result)}건)")


if __name__ == "__main__":
    main()

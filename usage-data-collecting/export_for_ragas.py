"""RAGAS 평가 입력 포맷으로 usage_logs를 추출합니다.

출력: usage-data-collecting/ragas_dataset.json
사용법:
  PYTHONPATH=. uv run --env-file .env python usage-data-collecting/export_for_ragas.py

RAGAS 입력 형식:
  { "question": str, "answer": str, "contexts": [str, ...] }
  ※ ground_truth는 수동 라벨링 필요 (골든셋에서 가져오거나 직접 작성)
"""

import json
from pathlib import Path

from pymongo import MongoClient

from app.config import settings

COLL_NAME = "usage_logs"
OUTPUT_PATH = Path(__file__).parent / "ragas_dataset.json"


def main():
    client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    db = client[settings.mongo_db_name]
    coll = db[COLL_NAME]

    docs = list(coll.find({}).sort("timestamp", -1))
    if not docs:
        print("수집된 로그가 없습니다.")
        return

    dataset = []
    for d in docs:
        # cited_paragraphs를 contexts로 사용 (실제 RAGAS는 문서 텍스트가 필요하지만,
        # 여기서는 문단 번호 기반 참조를 제공하여 후속 스크립트에서 원문 조회 가능)
        entry = {
            "question": d.get("question", ""),
            "answer": d.get("answer", ""),
            "contexts": d.get("cited_paragraphs", []),
            "metadata": {
                "session_id": d.get("session_id", ""),
                "matched_topics": d.get("matched_topics", []),
                "is_situation": d.get("is_situation", False),
                "feedback": d.get("feedback"),
                "response_time_ms": d.get("response_time_ms", 0),
            },
        }
        dataset.append(entry)

    OUTPUT_PATH.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"RAGAS 데이터셋 추출 완료: {len(dataset)}건 → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

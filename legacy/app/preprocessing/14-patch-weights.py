# app/preprocessing/14-patch-weights.py
# MongoDB에서 weight_score만 직접 업데이트하는 패치 스크립트.
# 임베딩·텍스트는 건드리지 않고 가중치만 변경 → API 비용 0, 오류 위험 최소.
#
# 사용법: PYTHONPATH=. uv run --env-file .env python app/preprocessing/14-patch-weights.py

import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from pymongo import MongoClient
from app.config import settings

# ── 기준서 본문 카테고리별 가중치 ──────────────────────────────────────────
STANDARD_WEIGHTS = {
    "본문": 1.3,
    "적용지침B": 1.3,
    "적용사례IE": 1.1,
    "결론도출근거": 0.8,
    "용어정의": 0.8,
    "시행일": 0.8,
}

# ── QNA 출처별 가중치 (category 패턴: "질의회신(출처명)") ─────────────────
QNA_WEIGHTS = {
    "IFRS 해석위원회": 1.15,
    "금융감독원": 1.15,
    "회계기준원 정규질의": 1.10,
    "신속처리질의": 1.05,
}

# ── 감리사례 가중치 (category에 "감리" 포함) ──────────────────────────────
FINDINGS_WEIGHT = 1.2


def patch_weights():
    client = MongoClient(settings.mongo_uri)
    db = client[settings.mongo_db_name]
    coll = db[settings.mongo_collection_name]

    total_modified = 0

    # 1. 기준서 본문 카테고리
    print("── 기준서 본문 카테고리 패치 ──")
    for category, weight in STANDARD_WEIGHTS.items():
        result = coll.update_many(
            {"category": category},
            {"$set": {"weight_score": weight}},
        )
        print(f"  {category}: {result.modified_count}건 → {weight}")
        total_modified += result.modified_count

    # 2. QNA 출처별
    print("\n── QNA 출처별 패치 ──")
    for source, weight in QNA_WEIGHTS.items():
        # category 필드가 "질의회신(IFRS 해석위원회)" 형태
        result = coll.update_many(
            {"category": {"$regex": f"질의회신\\({source}\\)"}},
            {"$set": {"weight_score": weight}},
        )
        print(f"  질의회신({source}): {result.modified_count}건 → {weight}")
        total_modified += result.modified_count

    # 3. 감리사례 (category에 "감리" 포함)
    print("\n── 감리사례 패치 ──")
    result = coll.update_many(
        {"category": {"$regex": "감리"}},
        {"$set": {"weight_score": FINDINGS_WEIGHT}},
    )
    print(f"  감리사례: {result.modified_count}건 → {FINDINGS_WEIGHT}")
    total_modified += result.modified_count

    # 4. 요약
    print(f"\n총 {total_modified}건 weight_score 패치 완료")

    client.close()


if __name__ == "__main__":
    patch_weights()

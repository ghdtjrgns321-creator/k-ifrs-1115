"""실사용 데이터 기본 분석 스크립트.

사용법:
  PYTHONPATH=. uv run --env-file .env python usage-data-collecting/analyze_usage.py
"""

from collections import Counter
from datetime import datetime, timezone

from pymongo import MongoClient

from app.config import settings

COLL_NAME = "usage_logs"


def main():
    client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    db = client[settings.mongo_db_name]
    coll = db[COLL_NAME]

    total = coll.count_documents({})
    if total == 0:
        print("수집된 로그가 없습니다.")
        return

    scored = coll.count_documents({"auto_scores": {"$exists": True}})
    unscored = total - scored

    print(f"=== 실사용 데이터 분석 ({total}건) ===")
    print(f"  채점 완료: {scored}건 | 미채점: {unscored}건")
    if unscored > 0:
        print(f"  → score_usage_logs.py 실행으로 미채점 건 채점 가능")
    print()

    # ── 1. 피드백 분포 ────────────────────────────────────────────
    up = coll.count_documents({"feedback": "up"})
    down = coll.count_documents({"feedback": "down"})
    no_fb = total - up - down
    print(f"[피드백]  좋아요: {up}  |  개선필요: {down}  |  미응답: {no_fb}")
    if up + down > 0:
        print(f"  만족률: {up / (up + down) * 100:.0f}%")
    print()

    # ── 2. 토픽 분포 (top 10) ────────────────────────────────────
    topic_counter: Counter = Counter()
    for doc in coll.find({}, {"matched_topics": 1}):
        for t in doc.get("matched_topics", []):
            topic_counter[t] += 1
    print("[토픽 분포 Top 10]")
    for topic, cnt in topic_counter.most_common(10):
        print(f"  {topic}: {cnt}건")
    print()

    # ── 3. 평균 응답 시간 ─────────────────────────────────────────
    pipeline = [
        {"$group": {
            "_id": None,
            "avg_ms": {"$avg": "$response_time_ms"},
            "max_ms": {"$max": "$response_time_ms"},
        }},
    ]
    agg = list(coll.aggregate(pipeline))
    if agg:
        avg_s = agg[0]["avg_ms"] / 1000
        max_s = agg[0]["max_ms"] / 1000
        print(f"[응답 시간]  평균: {avg_s:.1f}s  |  최대: {max_s:.1f}s\n")

    # ── 4. 일별 사용량 (최근 7일) ─────────────────────────────────
    print("[일별 사용량]")
    day_pipeline = [
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id": -1}},
        {"$limit": 7},
    ]
    for row in coll.aggregate(day_pipeline):
        print(f"  {row['_id']}: {row['count']}건")
    print()

    # ── 5. 개선 필요 케이스 (최근 5건) ────────────────────────────
    down_docs = list(
        coll.find({"feedback": "down"})
        .sort("timestamp", -1)
        .limit(5)
    )
    if down_docs:
        print("[개선 필요 피드백 최근 5건]")
        for d in down_docs:
            q = d.get("question", "")[:80]
            topics = ", ".join(d.get("matched_topics", []))
            reason = d.get("feedback_reason", "")
            print(f"  Q: {q}")
            print(f"    토픽: {topics}  |  응답: {d.get('response_time_ms', 0)}ms")
            if reason:
                print(f"    사유: {reason}")
            print()


if __name__ == "__main__":
    main()

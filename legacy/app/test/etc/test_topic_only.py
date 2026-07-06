"""토픽 매칭만 단독 검증 — LLM 호출 없이 match_topics() 직접 테스트

이전 골든 테스트 결과(golden_results.json)에서 search_keywords를 재사용하고,
golden_cases.py에서 user_message + 기대 토픽을 가져와서 매칭 정확도를 비교합니다.
"""

import json
from pathlib import Path

from app.domain.tree_matcher import match_topics
from app.test.quality_test.golden_cases import GOLDEN_CASES_BY_ID

RESULTS_FILE = (
    Path(__file__).parent.parent
    / "quality_test"
    / "results"
    / "golden_results.json"
)


def main():
    results = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))

    # 싱글턴 turn=0 결과만 (멀티턴 1턴째 포함)
    single_results = [r for r in results if r.get("turn", 0) == 0]

    improved = []
    regressed = []
    unchanged = []

    for r in single_results:
        test_id = r["test_id"]
        meta = GOLDEN_CASES_BY_ID.get(test_id)
        if not meta or not meta.topic or meta.question_type != "situation":
            continue

        search_kws = r.get("search_keywords") or []
        old_topics = r.get("matched_topic_keys") or []

        # user_message: 싱글턴이면 meta.message, 멀티턴이면 첫 턴 message
        user_msg = meta.message if meta.message else ""
        if not user_msg and meta.turns:
            user_msg = meta.turns[0].message

        # standalone_query 재현 불가 → 빈 문자열로 전달
        # Why: embedding은 user_message에서 max를 취하므로 충분
        # keyword 매칭은 search_keywords로 수행
        new_matched = match_topics(
            standalone_query=user_msg,  # user_msg를 standalone으로도 전달
            search_keywords=search_kws,
            topic_hints=None,  # topic_hints 없이 순수 매칭력 테스트
            user_message=user_msg,
        )
        new_topics = [t["topic_name"] for t in new_matched]

        old_hit = any(meta.topic in t for t in old_topics)
        new_hit = any(meta.topic in t for t in new_topics)

        old_top1 = old_topics[0] if old_topics else "-"
        new_top1 = new_topics[0] if new_topics else "-"

        entry = {
            "id": test_id,
            "title": meta.title,
            "expected": meta.topic,
            "old_hit": old_hit,
            "new_hit": new_hit,
            "old_top1": old_top1,
            "new_top1": new_top1,
            "new_topics": new_topics,
        }

        if not old_hit and new_hit:
            improved.append(entry)
        elif old_hit and not new_hit:
            regressed.append(entry)
        else:
            unchanged.append(entry)

    # 리포트
    total = len(improved) + len(regressed) + len(unchanged)
    old_hits = sum(1 for e in improved + regressed + unchanged if e["old_hit"])
    new_hits = sum(1 for e in improved + regressed + unchanged if e["new_hit"])

    print(f"=== 토픽 매칭 비교 (situation {total}건) ===")
    print(f"  변경 전: {old_hits}/{total} ({old_hits*100//total}%)")
    print(f"  변경 후: {new_hits}/{total} ({new_hits*100//total}%)")
    print()

    if improved:
        print(f"개선 ({len(improved)}건):")
        for e in improved:
            print(f"  {e['id']} {e['title']}")
            print(f"    기대: {e['expected']}")
            print(f"    전: {e['old_top1']} → 후: {e['new_top1']}")
            print(f"    new_topics: {e['new_topics']}")
        print()

    if regressed:
        print(f"회귀 ({len(regressed)}건):")
        for e in regressed:
            print(f"  {e['id']} {e['title']}")
            print(f"    기대: {e['expected']}")
            print(f"    전: {e['old_top1']} → 후: {e['new_top1']}")
            print(f"    new_topics: {e['new_topics']}")
        print()

    if not regressed:
        print("회귀: 없음!")


if __name__ == "__main__":
    main()

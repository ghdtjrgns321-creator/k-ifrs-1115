"""STEP 0 산출물 빌더 — failure_buckets.json + split.json.

capture_step0.json(미재현 14건 진입/회수 계측)을 읽어 실패 버킷을 결정적 규칙으로
분류하고, 92건을 dev/test로 층화 분할한다. 분할은 파이프라인 실행 없이 ID만 사용.

버킷 규칙(증거 기반, 결정적):
  OUT : routing != "IN"                     (라우팅 거부)
  A   : gold ∩ retrieved_paras = ∅          (진입 누락 — 정답 문단이 컨텍스트 미도달)
  D   : gold ∩ retrieved ≠ ∅, gold ∩ cited = ∅  (회수됐으나 결론이 다른 프레임 인용)
  기타: gold ∩ retrieved ≠ ∅, gold ∩ cited ≠ ∅  (정답 일부 인용했으나 소프트/결론축 실패)

실행:
  python app/test/qna_holdout/build_buckets_split.py
"""

from __future__ import annotations

import json
from pathlib import Path

_HERE = Path(__file__).parent
TESTSET = Path(__file__).resolve().parents[3] / "data" / "testdata" / "qna_testset.json"
CAPTURE = _HERE / "capture_step0.json"

# report.md 전체표 92 ID (모집단 권위 출처) — 미재현 14는 FAILED_14와 동일해야 함
FAILED_14 = [
    "QNA-2017-I-KQA014",
    "QNA-2020-I-KQA006-Q2",
    "QNA-202003D",
    "QNA-2021-I-KQA008",
    "QNA-2022-I-KQA007",
    "QNA-SSI-202503008",
    "QNA-SSI-202511018",
    "QNA-SSI-35565",
    "QNA-SSI-35567",
    "QNA-SSI-38648",
    "QNA-SSI-38673",
    "QNA-SSI-38675",
    "QNA-SSI-38676",
    "QNA-SSI-38680",
]


def _norm(p: str) -> str:
    return str(p).replace("문단", "").strip()


def classify(row: dict) -> tuple[str, dict]:
    gold = {_norm(g) for g in row.get("gold_cited", [])}
    retr = set(row.get("retrieved_paras", []))
    cited = {_norm(c) for c in row.get("resp_cited", [])}
    routing = row.get("routing", "")
    ev = {
        "routing": routing,
        "gold": sorted(gold),
        "gold_in_retrieved": sorted(gold & retr),
        "gold_in_cited": sorted(gold & cited),
        "retrieved_count": row.get("retrieved_count", 0),
    }
    if routing != "IN":
        return "OUT", ev
    if not gold:  # gold 문단 없는 케이스(하드채점 제외 8건 중 일부) — 회수 판정 불가
        return "기타", ev
    if not (gold & retr):
        return "A", ev
    if not (gold & cited):
        return "D", ev
    return "기타", ev


def build_buckets() -> list[dict]:
    rows = {r["id"]: r for r in json.loads(CAPTURE.read_text(encoding="utf-8"))}
    out = []
    for cid in FAILED_14:
        r = rows.get(cid)
        if r is None:
            raise SystemExit(f"capture에 {cid} 없음 — 캡처 재실행 필요")
        if r.get("error"):
            raise SystemExit(f"{cid} 캡처 에러: {r['error']} — 재실행 필요")
        bucket, ev = classify(r)
        out.append({"id": cid, "bucket": bucket, "evidence": ev})
    return out


def build_split(buckets: list[dict]) -> dict:
    """층화 분할: 미재현14의 각 버킷이 dev≥1, test에 미재현≥4.

    나머지 78건은 출처(SSI/IKQA/ETC) 유지하며 dev/test 약 60/32로 결정적 배분.
    난수 미사용(Date/random 금지 정책 + 재현성) — 정렬 후 인덱스 기반.
    """
    all_ids = [c["id"] for c in json.loads(TESTSET.read_text(encoding="utf-8"))]
    assert len(all_ids) == 92, f"testset {len(all_ids)}건"

    fail_ids = [b["id"] for b in buckets]
    by_bucket: dict[str, list[str]] = {}
    for b in buckets:
        by_bucket.setdefault(b["bucket"], []).append(b["id"])

    # 미재현14 배분: 각 버킷 첫 1건 dev, 나머지 test 우선 → test 미재현 ≥4 보장
    dev_fail, test_fail = [], []
    for _bucket, ids in sorted(by_bucket.items()):
        dev_fail.append(ids[0])
        test_fail.extend(ids[1:])
    # test 미재현 최소 4건 확보(부족하면 dev_fail에서 이동)
    while len(test_fail) < 4 and len(dev_fail) > len(by_bucket):
        test_fail.append(dev_fail.pop())

    # 나머지 78건: 출처별 정렬 후 인덱스 기반 60/32 근사 배분
    def src(cid: str) -> str:
        if "SSI" in cid:
            return "SSI"
        if "I-KQA" in cid or "I-KAQ" in cid:
            return "IKQA"
        return "ETC"

    rest = [i for i in all_ids if i not in fail_ids]
    target_dev_total = 60
    dev, test = set(dev_fail), set(test_fail)
    # 출처별로 dev 비율 유지하며 채움
    from collections import defaultdict

    by_src: dict[str, list[str]] = defaultdict(list)
    for i in sorted(rest):
        by_src[src(i)].append(i)
    need_dev = target_dev_total - len(dev)
    total_rest = len(rest)
    for _s, ids in sorted(by_src.items()):
        k = round(len(ids) * need_dev / total_rest)
        for j, i in enumerate(ids):
            (dev if j < k else test).add(i)

    return {
        "dev": sorted(dev),
        "test": sorted(test),
        "_meta": {
            "dev_n": len(dev),
            "test_n": len(test),
            "dev_fail": sorted(dev_fail),
            "test_fail": sorted(test_fail),
        },
    }


def main() -> None:
    buckets = build_buckets()
    (_HERE / "failure_buckets.json").write_text(
        json.dumps(buckets, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    split = build_split(buckets)
    (_HERE / "split.json").write_text(
        json.dumps(split, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ── 검증 출력 ──
    from collections import Counter

    dist = Counter(b["bucket"] for b in buckets)
    dev, test = set(split["dev"]), set(split["test"])
    print("=== failure_buckets (14건) ===")
    for b in buckets:
        print(
            f"  {b['id']:24} {b['bucket']:4} gold_retr={b['evidence']['gold_in_retrieved']}"
        )
    print("버킷분포:", dict(dist))
    print("\n=== split 검증 ===")
    print(f"dev {len(dev)} + test {len(test)} = {len(dev) + len(test)} (=92 ?)")
    print(f"교집합: {len(dev & test)} (=0 ?)")
    test_fail = [b["id"] for b in buckets if b["id"] in test]
    print(f"test 미재현: {len(test_fail)} (>=4 ?) {test_fail}")
    dev_buckets = {b["bucket"] for b in buckets if b["id"] in dev}
    print(f"dev 커버 버킷: {sorted(dev_buckets)} (전 버킷 {sorted(dist)} ?)")

    ok = (
        len(dev) + len(test) == 92
        and not (dev & test)
        and len(test_fail) >= 4
        and dev_buckets == set(dist)
    )
    print("\nRESULT:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
    main()

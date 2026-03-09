"""
파싱 결과 랜덤 검수 스크립트
임베딩 전에 반드시 실행해서 청크 품질 확인.

사용: uv run inspect-chunks.py [검수할_카테고리]
예시: uv run inspect-chunks.py 적용사례IE
"""
import json
import random
import sys

INPUT_FILE = "data/web/kifrs-1115-chunks.json"
SAMPLE_COUNT = 5
CONTENT_PREVIEW_LEN = 500


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    # 카테고리 필터 (선택적 인수)
    category_filter = sys.argv[1] if len(sys.argv) > 1 else None
    if category_filter:
        target = [c for c in chunks if c["metadata"].get("category") == category_filter]
        print(f"카테고리 필터: '{category_filter}' ({len(target)}개 중 최대 {SAMPLE_COUNT}개 샘플)")
    else:
        target = chunks
        print(f"전체 {len(chunks)}개 청크 중 {SAMPLE_COUNT}개 랜덤 샘플")

    sample = random.sample(target, min(SAMPLE_COUNT, len(target)))

    for i, chunk in enumerate(sample, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/{min(SAMPLE_COUNT, len(target))}] ID: {chunk['id']}")
        print(f"{'='*60}")
        print("[METADATA]")
        for k, v in chunk["metadata"].items():
            print(f"  {k}: {v}")
        print(f"\n[CONTENT 앞 {CONTENT_PREVIEW_LEN}자]")
        print(chunk["content"][:CONTENT_PREVIEW_LEN])
        print()

    # 검증 포인트 요약 출력
    print("\n" + "="*60)
    print("[검증 체크리스트]")

    # 1. 이중 번호 탐지: "**[문단 N]** N " 패턴
    double_num = [
        c for c in chunks
        if c["content"].startswith("**[문단 ") and
        _has_double_number(c["content"])
    ]
    status = "✅" if not double_num else f"❌ {len(double_num)}개 발견"
    print(f"  문단 번호 중복 없음: {status}")

    # 2. IE 청크에 case_group_title 존재 여부
    ie_chunks = [c for c in chunks if c["metadata"].get("category") == "적용사례IE"]
    ie_with_title = [c for c in ie_chunks if c["metadata"].get("case_group_title")]
    status = f"✅ {len(ie_with_title)}/{len(ie_chunks)}개" if ie_chunks else "N/A"
    print(f"  IE case_group_title 존재: {status}")

    # 3. sup/sub 보존 여부
    sup_count = sum(1 for c in chunks if "^" in c["content"])
    sub_count = sum(1 for c in chunks if "_" in c["content"] and "metadata" not in c["content"])
    print(f"  sup(^) 포함 청크: {sup_count}개 | sub(_) 포함 청크: {sub_count}개")

    print("="*60)


def _has_double_number(content: str) -> bool:
    """**[문단 N]** 바로 뒤에 동일 숫자가 반복되는지 탐지."""
    import re
    m = re.match(r"\*\*\[문단 (\d+)\]\*\* (\d+)", content)
    if m and m.group(1) == m.group(2):
        return True
    return False


if __name__ == "__main__":
    main()

"""
QNA / 감리사례 청크 파싱 결과 검수 스크립트.

사용법:
  uv run app/test/inspect-qna.py             → QNA 랜덤 샘플 출력
  uv run app/test/inspect-qna.py findings    → 감리사례 샘플 출력
  uv run app/test/inspect-qna.py all         → QNA + 감리사례 검증 보고서
"""

import sys
import json
import re
import random

INPUT_QNA      = "data/web/kifrs-1115-qna-chunks.json"
INPUT_FINDINGS = "data/findings/findings-final.json"

SAMPLE_SIZE = 3  # 출력할 샘플 수


# ── 검증 함수들 ────────────────────────────────────────────────────────────────

def check_qna_chunk(chunk: dict) -> dict[str, bool]:
    """
    단일 QNA 청크에 대한 체크리스트를 반환.
    각 항목이 True면 정상, False면 문제 있음.
    """
    content = chunk.get("content", "")
    metadata = chunk.get("metadata", {})
    return {
        "제목 prefix(**[QNA-...]**)": bool(re.search(r'^\*\*\[QNA-', content)),
        "서두 노이즈 없음(관련 회계기준...본문)": not bool(re.search(r'^관련\s*회계\s*기준[^\n]*\n본문', content)),
        "## 섹션 헤더 존재": bool(re.search(r'^## ', content, re.MULTILINE)),
        "title 메타데이터 필드": bool(metadata.get("title")),
        "weight_score 존재": "weight_score" in metadata,
    }


def simulate_finding_transform(content: str) -> str:
    """
    07-findings-embed.py의 split_finding_to_children 서두 변환을 시뮬레이션.
    실제 DB 적재 시 적용되는 변환과 동일하므로 embed 전 미리 검증 가능.
    """
    return re.sub(
        r'^레퍼런스\s*\[([^\]]+)\]\s*([^\n]+)\n(관련\s*회계\s*기준[^\n]*)(?:\n출처:[^\n]*)?\n본문\n?',
        r'**[\1]** \2\n\3\n\n',
        content
    )


def check_finding_chunk(chunk: dict) -> dict[str, bool]:
    """
    단일 감리사례 청크에 대한 체크리스트 반환.
    07-findings-embed.py의 변환을 시뮬레이션하여 실제 embed 시 결과를 미리 검증.
    """
    raw_content = chunk.get("content", "")
    # 실제 embed 시 적용되는 변환을 미리 적용하여 검사
    transformed = simulate_finding_transform(raw_content)
    return {
        "서두 변환 성공(**[ID]** prefix)": bool(re.search(r'^\*\*\[(?:FSS|KICPA)-', transformed)),
        "서두 노이즈 제거(레퍼런스...본문)": not bool(re.search(r'^레퍼런스\s*\[', transformed)),
        "## 섹션 헤더 존재": bool(re.search(r'^## ', transformed, re.MULTILINE)),
    }


def print_sample(chunk: dict, check_fn, label: str):
    """청크 내용과 체크리스트를 출력. findings는 변환 시뮬레이션 결과도 함께 출력."""
    cid = chunk.get("id", "?")
    content = chunk.get("content", "")

    # findings는 embed 시 변환이 적용되므로 시뮬레이션 버전으로 미리보기
    display_content = (
        simulate_finding_transform(content) if label == "감리사례" else content
    )

    print(f"\n{'='*65}")
    print(f"[{label}] ID: {cid}")
    print(f"{'='*65}")

    # content 앞 500자만 출력 (서두 확인용)
    preview = display_content[:500]
    prefix = "(변환 후) " if label == "감리사례" else ""
    print(f"--- {prefix}content 미리보기 (앞 500자) ---\n{preview}")
    if len(display_content) > 500:
        print(f"... (총 {len(display_content)}자)")

    # 체크리스트
    checks = check_fn(chunk)
    print(f"\n--- 검증 체크리스트 ---")
    all_pass = True
    for item, passed in checks.items():
        mark = "OK" if passed else "FAIL"
        print(f"  [{mark}] {item}")
        if not passed:
            all_pass = False
    print(f"\n  => {'모든 항목 통과' if all_pass else '일부 항목 실패'}")


def run_qna_report(chunks: list[dict]):
    """전체 QNA 청크에 대한 집계 보고서."""
    total = len(chunks)
    counts = {
        "prefix_ok": 0,
        "no_preamble": 0,
        "has_section": 0,
        "has_title": 0,
    }
    for c in chunks:
        content = c.get("content", "")
        meta = c.get("metadata", {})
        if re.search(r'^\*\*\[QNA-', content):
            counts["prefix_ok"] += 1
        if not re.search(r'^관련\s*회계\s*기준[^\n]*\n본문', content):
            counts["no_preamble"] += 1
        if re.search(r'^## ', content, re.MULTILINE):
            counts["has_section"] += 1
        if meta.get("title"):
            counts["has_title"] += 1

    print(f"\n{'='*65}")
    print(f"QNA 전체 검증 보고서 (총 {total}개)")
    print(f"{'='*65}")
    print(f"  제목 prefix 존재:       {counts['prefix_ok']:3d} / {total}")
    print(f"  서두 노이즈 없음:       {counts['no_preamble']:3d} / {total}")
    print(f"  ## 섹션 헤더 존재:      {counts['has_section']:3d} / {total}")
    print(f"  title 메타데이터 존재:  {counts['has_title']:3d} / {total}")


def run_findings_report(chunks: list[dict]):
    """전체 감리사례에 대한 집계 보고서. 변환 시뮬레이션 적용 후 기준으로 집계."""
    total = len(chunks)
    prefix_ok = 0
    no_preamble = 0
    has_section = 0

    for c in chunks:
        transformed = simulate_finding_transform(c.get("content", ""))
        if re.search(r'^\*\*\[(?:FSS|KICPA)-', transformed):
            prefix_ok += 1
        if not re.search(r'^레퍼런스\s*\[', transformed):
            no_preamble += 1
        if re.search(r'^## ', transformed, re.MULTILINE):
            has_section += 1

    print(f"\n{'='*65}")
    print(f"감리사례 전체 검증 보고서 (총 {total}개, 변환 시뮬레이션 적용)")
    print(f"{'='*65}")
    print(f"  볼드 prefix 존재:  {prefix_ok:3d} / {total}")
    print(f"  서두 노이즈 없음:  {no_preamble:3d} / {total}")
    print(f"  ## 섹션 헤더 존재: {has_section:3d} / {total}")


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "qna"

    if mode in ("qna", "all"):
        try:
            with open(INPUT_QNA, "r", encoding="utf-8") as f:
                qna_chunks = json.load(f)
            print(f"\nQNA 파일 로드 완료: {len(qna_chunks)}개 청크")

            # 랜덤 샘플 출력
            samples = random.sample(qna_chunks, min(SAMPLE_SIZE, len(qna_chunks)))
            for chunk in samples:
                print_sample(chunk, check_qna_chunk, "QNA")

            if mode == "all":
                run_qna_report(qna_chunks)

        except FileNotFoundError:
            print(f"[ERROR] 파일 없음: {INPUT_QNA}")
            print("  -> 먼저 uv run app/preprocessing/05-qna-crawl.py 실행 필요")

    if mode in ("findings", "all"):
        try:
            with open(INPUT_FINDINGS, "r", encoding="utf-8") as f:
                findings = json.load(f)
            print(f"\n감리사례 파일 로드 완료: {len(findings)}개")

            # 랜덤 샘플 출력
            samples = random.sample(findings, min(SAMPLE_SIZE, len(findings)))
            for chunk in samples:
                print_sample(chunk, check_finding_chunk, "감리사례")

            if mode == "all":
                run_findings_report(findings)

        except FileNotFoundError:
            print(f"[ERROR] 파일 없음: {INPUT_FINDINGS}")


if __name__ == "__main__":
    main()

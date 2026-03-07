import io
import sys
# Windows cp949 환경에서 이모지 출력 시 UnicodeEncodeError 방지
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import json
import time
import re
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (app.config 임포트를 위해)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from pymongo import MongoClient, UpdateOne
from openai import OpenAI
from app.config import settings

# ── 설정 상수 ────────────────────────────────────────────────────────────────

# ⚠️ 안전 장치: True이면 3개만 처리하고 DB에 저장하지 않음
# 전체 실행 전 반드시 여기서 결과물을 눈으로 확인할 것
TEST_MODE = False

# LLM 생성 제목 대상 카테고리 (QNA, 질의회신, 감리사례는 별도 처리)
TARGET_CATEGORIES = {"본문", "적용지침B", "결론도출근거", "적용사례IE"}

# 원본 청크 JSON 파일 경로
CHUNKS_FILE = PROJECT_ROOT / "data" / "web" / "kifrs-1115-chunks.json"

# 이 스크립트 전용 모델 — gpt-5-mini는 reasoning 모델이라 제목 생성에 부적합
TITLE_MODEL = "gpt-4o-mini"

# MongoDB UpdateOne 배치 크기 (메모리 효율)
MONGO_BATCH_SIZE = 100

# OpenAI API 호출 간격(초) — Rate Limit 방지
API_CALL_INTERVAL = 0.1


# ── 제목 생성 프롬프트 ───────────────────────────────────────────────────────

SYSTEM_PROMPT = """너는 K-IFRS 회계 전문가야.
주어진 계층구조(hierarchy), 문단번호(paragraph_number), 텍스트(text)를 읽고, 아래 규칙에 따라 제목을 생성해라.

규칙:
1. 출력 형식: `[{소주제}] 문단 {번호} - {핵심 요약}`
   - 예시: "[환불부채] 문단 55 - 반품 예상 대가에 대한 환불부채 인식"
   - 예시: "[구별되는 재화나 용역] 문단 26 - 계약에 포함될 수 있는 재화나 용역의 예시"
2. {소주제}: hierarchy의 맨 마지막 항목을 그대로 사용
3. {번호}: paragraph_number 필드의 값을 그대로 사용 (예: 15, B25, BC367, IE110, BC414V)
   - paragraph_number가 명시된 경우 text에서 번호를 추출하지 말고 반드시 이 값을 사용할 것
4. {핵심 요약}: 이 문단이 말하고자 하는 핵심 회계처리 기준이나 주제를 10~25자로 간결하게 요약
5. 전체 제목 길이는 50자 이내
6. 제목만 출력하고 다른 설명이나 부가 문장은 절대 붙이지 마라"""

USER_PROMPT_TEMPLATE = """hierarchy: {hierarchy}
paragraph_number: {para_num}
text: {text_preview}"""


def extract_para_num(content: str) -> str:
    """
    content 맨 앞에서 문단 번호를 추출한다.
    패턴: "15 ...", "B25 ...", "BC367 ...", "IE110 ...", "한4.1 ..."
    GPT에게 그냥 원본 텍스트를 주는 것이 더 정확하므로 이 함수는 디버깅용.
    """
    match = re.match(r"^([A-Z가-힣]*\d+[\d.]*)", content.strip())
    return match.group(1) if match else ""


def generate_title(client: OpenAI, hierarchy: str, content: str) -> str:
    """
    LLM을 호출하여 계층구조 + 내용 앞부분으로 짧은 제목을 생성한다.
    content는 앞 200자만 전달해 토큰 절약.
    """
    # content가 비어있으면 LLM에 빈 프롬프트가 전달되므로 조기 종료
    if not content.strip():
        raise ValueError("content가 비어있습니다")

    # **[문단 BC414V]** 형태의 볼드 prefix에서 문단번호 직접 추출
    # → LLM에 명시적으로 전달하여 "문단 B55처럼 본문 안의 다른 참조번호를 선택하는 오류" 방지
    prefix_m = re.match(r'^\*\*\[문단\s*([^\]]+)\]\*\*', content.strip())
    extracted_para = prefix_m.group(1).strip() if prefix_m else extract_para_num(content)

    # 앞 200자만 사용 — 문단 번호와 핵심 문장이 앞부분에 집중돼 있음
    text_preview = content[:200].replace("\n", " ")

    response = client.chat.completions.create(
        model=TITLE_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(
                    hierarchy=hierarchy,
                    para_num=extracted_para,
                    text_preview=text_preview,
                ),
            },
        ],
        max_tokens=80,    # "[소주제] 문단 번호 - 핵심요약" 포맷은 최대 50자이므로 여유 확보
        temperature=0,    # 일관성 최우선
    )

    # ── 응답 추출 & 디버깅 ─────────────────────────────────────────────────
    # 일부 최신 모델은 content가 None을 반환할 수 있음 → 명시적으로 확인
    raw_content = response.choices[0].message.content

    if raw_content is None:
        # None인 경우: finish_reason, refusal 등 원본 응답 전체를 출력하여 원인 파악
        print(f"  ⚠️  [DEBUG] content=None 수신. 원본 choices[0]: {response.choices[0]}")
        raise ValueError(f"모델이 None을 반환했습니다 (finish_reason={response.choices[0].finish_reason})")

    title = raw_content.strip()

    if not title:
        # 빈 문자열인 경우: 원본 응답 전체를 출력하여 원인 파악
        print(f"  ⚠️  [DEBUG] 빈 문자열 수신. 원본 choices[0]: {response.choices[0]}")
        raise ValueError("모델이 빈 문자열을 반환했습니다")

    return title


def load_target_chunks() -> list[dict]:
    """
    JSON 파일에서 대상 카테고리 청크만 로드한다.
    반환값: [{"chunk_id": ..., "hierarchy": ..., "content": ...}, ...]
    """
    with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
        all_chunks = json.load(f)

    target_chunks = [
        {
            "chunk_id": chunk["id"],
            "hierarchy": chunk["metadata"].get("hierarchy", ""),
            "content": chunk["content"],
            "category": chunk["metadata"].get("category", ""),
        }
        for chunk in all_chunks
        if chunk["metadata"].get("category") in TARGET_CATEGORIES
    ]

    print(f"✅ 대상 청크 수: {len(target_chunks)}개 (전체 {len(all_chunks)}개 중)")
    return target_chunks


def find_chunks_needing_title(collection, chunk_ids: list[str]) -> set[str]:
    """
    이어하기(resume) 모드: 이미 title이 있는 청크는 스킵한다.
    중단 후 재실행 시 불필요한 LLM 호출 비용을 절약하기 위함.
    전수 재처리가 필요하면 MongoDB에서 title 필드를 일괄 삭제 후 실행할 것.
    """
    already_titled = set()
    for doc in collection.find(
        {"chunk_id": {"$in": chunk_ids}, "title": {"$exists": True, "$ne": ""}},
        {"chunk_id": 1, "_id": 0},
    ):
        already_titled.add(doc["chunk_id"])

    needs = set(chunk_ids) - already_titled
    print(f"📊 대상: {len(chunk_ids)}개 중 title 있음: {len(already_titled)}개, 생성 필요: {len(needs)}개")
    return needs


def run_migration():
    """
    메인 마이그레이션 실행 함수.
    단계: JSON 로드 → 미처리 문서 필터 → LLM 제목 생성 → MongoDB 배치 업데이트

    TEST_MODE=True 이면 3개만 처리하고 DB에 저장하지 않는다.
    """
    # ── 모드 안내 ────────────────────────────────────────────────────────────
    if TEST_MODE:
        print("🧪 TEST_MODE=True — 3개만 처리, DB 저장 없음")
        print("   전체 실행하려면 스크립트 상단 TEST_MODE = False 로 변경하세요\n")
    else:
        print("🚀 PRODUCTION MODE — 전체 처리, DB 저장 활성화\n")

    # ── 클라이언트 초기화 ────────────────────────────────────────────────────
    mongo_client = MongoClient(settings.mongo_uri)
    collection = mongo_client[settings.mongo_db_name][settings.mongo_collection_name]
    openai_client = OpenAI(api_key=settings.openai_api_key)

    print(f"🔌 MongoDB 연결: {settings.mongo_db_name}.{settings.mongo_collection_name}")
    print(f"🤖 LLM 모델: {TITLE_MODEL}\n")

    # ── 처리 대상 청크 로드 ──────────────────────────────────────────────────
    target_chunks = load_target_chunks()
    chunk_ids = [c["chunk_id"] for c in target_chunks]
    chunk_map = {c["chunk_id"]: c for c in target_chunks}  # 빠른 조회를 위한 인덱스

    # ── 미처리 문서 필터 (title 없거나 빈 문자열이면 재처리) ─────────────────
    needs_title_ids = find_chunks_needing_title(collection, chunk_ids)

    if not needs_title_ids:
        print("🎉 모든 문서에 이미 제목이 있습니다. 종료합니다.")
        mongo_client.close()
        return

    # TEST_MODE: 딱 3개만 처리
    if TEST_MODE:
        needs_title_ids = set(list(needs_title_ids)[:3])
        print(f"🧪 테스트 대상 chunk_id: {needs_title_ids}\n")

    # ── 순차 처리: LLM 호출 → UpdateOne 배치 누적 ───────────────────────────
    pending_updates: list[UpdateOne] = []  # 배치로 모아서 한 번에 MongoDB에 씀
    success_count = 0
    error_count = 0
    total = len(needs_title_ids)

    # 카테고리별 진행 현황 추적 (디버깅용)
    category_stats: dict[str, int] = {}

    for i, chunk_id in enumerate(needs_title_ids, start=1):
        chunk = chunk_map[chunk_id]
        category = chunk["category"]

        try:
            # LLM으로 제목 생성
            title = generate_title(
                client=openai_client,
                hierarchy=chunk["hierarchy"],
                content=chunk["content"],
            )

            success_count += 1
            category_stats[category] = category_stats.get(category, 0) + 1

            # TEST_MODE: 매번 출력 (3개뿐이므로 전부 보여줌)
            # PROD MODE: 50개마다 또는 마지막에 출력
            if TEST_MODE or success_count % 50 == 0 or i == total:
                print(f"  [{i}/{total}] '{chunk_id}' → {title}")

            if TEST_MODE:
                # 테스트 모드: DB에 저장하지 않고 확인만
                continue

            # UpdateOne 연산을 배치에 추가
            pending_updates.append(
                UpdateOne(
                    {"chunk_id": chunk_id},
                    {"$set": {"title": title}},
                )
            )

            # MONGO_BATCH_SIZE마다 MongoDB에 한 번에 씀 (네트워크 왕복 최소화)
            if len(pending_updates) >= MONGO_BATCH_SIZE:
                result = collection.bulk_write(pending_updates, ordered=False)
                print(f"  💾 배치 저장: {result.modified_count}개 업데이트")
                pending_updates.clear()

            # Rate Limit 방지
            time.sleep(API_CALL_INTERVAL)

        except Exception as e:
            error_count += 1
            print(f"  ❌ [{chunk_id}] 오류 발생: {type(e).__name__}: {e}")
            continue

    # ── 남은 배치 처리 (PROD MODE만) ────────────────────────────────────────
    if not TEST_MODE and pending_updates:
        result = collection.bulk_write(pending_updates, ordered=False)
        print(f"  💾 최종 배치 저장: {result.modified_count}개 업데이트")

    # ── 결과 요약 ────────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    if TEST_MODE:
        print(f"🧪 테스트 완료 — 성공: {success_count}개, 실패: {error_count}개 (DB 저장 없음)")
        print("   결과가 올바르면 TEST_MODE = False 로 변경 후 전체 실행하세요")
    else:
        print(f"✅ 완료 — 성공: {success_count}개, 실패: {error_count}개")
        print("카테고리별 처리 현황:")
        for cat, cnt in sorted(category_stats.items()):
            print(f"  {cat}: {cnt}개")
    print("=" * 50)

    mongo_client.close()


if __name__ == "__main__":
    run_migration()

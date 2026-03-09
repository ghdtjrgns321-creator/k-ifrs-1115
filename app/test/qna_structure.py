import os
from dotenv import load_dotenv
from pymongo import MongoClient

# 환경 변수 로드
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("MONGO_DB_NAME", "kifrs_db")
CHILD_COLLECTION = os.getenv("MONGO_COLLECTION_NAME", "k-ifrs-1115-chatbot")

def verify_qas_structure():
    print("QnA 데이터 3단 분리 (Q/A/S) 정합성 검사를 시작합니다...\n")

    client = MongoClient(MONGO_URI)
    coll = client[DB_NAME][CHILD_COLLECTION]

    # parent_id를 기준으로 묶어서, 어떤 chunk_type들을 가지고 있는지 배열로 수집
    pipeline = [
        {"$match": {"parent_id": {"$exists": True}}},
        {"$group": {
            "_id": "$parent_id",
            "types": {"$push": "$chunk_type"}, # 해당 Parent가 가진 청크 종류를 리스트로 만듦
            "total_chunks": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]

    results = list(coll.aggregate(pipeline))

    total_qna = len(results)
    qa_count = 0
    qas_count = 0
    error_list = []
    s_examples = []

    for r in results:
        parent_id = r["_id"]
        types = r["types"]

        has_q = "question" in types
        has_a = "answer" in types
        has_s = "supplementary" in types

        # [이상 케이스 검출] 
        # 질문(Q)이나 답변(A)이 없거나, 똑같은 타입이 2개 이상 들어갔거나, 3조각을 초과한 경우
        if not has_q or not has_a or len(types) > 3 or types.count("question") > 1 or types.count("answer") > 1:
            error_list.append({"id": parent_id, "types": types})
            continue

        # [정상 케이스 분류]
        if has_s:
            qas_count += 1
            if len(s_examples) < 3: # 예시 출력을 위해 3개만 저장
                s_examples.append(parent_id)
        else:
            qa_count += 1

    # ==========================================
    # 결과 출력
    # ==========================================
    print(f"[QnA 분리 구조 통계]")
    print(f"  - 전체 검사 대상 QnA (Parent): {total_qna}개")
    print(f"  - 🟢 기본 2단 분리 (Question + Answer): {qa_count}개")
    print(f"  - 🔵 확장 3단 분리 (Question + Answer + Supplementary): {qas_count}개")

    if error_list:
        print(f"\n❌ [경고] 비정상 분리 구조 발견: {len(error_list)}개")
        for err in error_list:
            print(f"    └ ID: {err['id']} | 보유 청크: {err['types']}")
    else:
        print("\n✅ [성공] 모든 QnA가 누락이나 훼손 없이 완벽한 구조로 분리되었습니다!")

    if s_examples:
        print("\n💡 [참고] '부록(Supplementary)'이 성공적으로 분리된 QnA 예시 (검증용):")
        for s_id in s_examples:
            print(f"    - ID: {s_id}")

    print(f"\n{'='*65}")

    client.close()

if __name__ == "__main__":
    verify_qas_structure()
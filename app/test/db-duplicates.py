import os
from dotenv import load_dotenv
from pymongo import MongoClient

# 환경 변수 로드
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("MONGO_DB_NAME", "kifrs_db")
CHILD_COLLECTION = os.getenv("MONGO_COLLECTION_NAME", "k-ifrs-1115-chatbot")
PARENT_COLLECTION = "kifrs_1115_qna_parents"

def check_data_integrity():
    print("MongoDB Atlas 데이터 정합성(중복) 검증을 시작합니다...\n")

    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    child_coll = db[CHILD_COLLECTION]
    parent_coll = db[PARENT_COLLECTION]

    # ==========================================
    # 1. K-IFRS 1115호 본문 중복 검증
    # ==========================================
    # parent_id가 없는 도큐먼트들을 본문으로 간주하고, chunk_id 기준으로 그룹핑
    main_text_pipeline = [
        {"$match": {"parent_id": {"$exists": False}}}, # QnA가 아닌 본문만 필터링
        {"$group": {"_id": "$chunk_id", "count": {"$sum": 1}}}, # chunk_id별 개수 세기
        {"$match": {"count": {"$gt": 1}}} # 1개 초과(중복)인 것만 추출
    ]
    main_duplicates = list(child_coll.aggregate(main_text_pipeline))
    main_total = child_coll.count_documents({"parent_id": {"$exists": False}})

    print(f"📘 [K-IFRS 1115 본문 데이터]")
    print(f"  - 총 적재 건수: {main_total:,}건")
    if not main_duplicates:
        print("  - ✅ 중복 데이터 없음! (모든 본문이 고유함)")
    else:
        print(f"  - ❌ 중복 발견: {len(main_duplicates)}개의 ID가 중복 적재되었습니다.")
        for d in main_duplicates[:5]:
            print(f"    └ ID: {d['_id']} (적재 횟수: {d['count']}번)")

    # ==========================================
    # 2. 질의회신 (QnA Child - 벡터 DB) 중복 검증
    # ==========================================
    # parent_id와 chunk_type(question, answer, supplementary) 조합으로 그룹핑
    qna_child_pipeline = [
        {"$match": {"parent_id": {"$exists": True}}},
        {"$group": {
            "_id": {"parent_id": "$parent_id", "chunk_type": "$chunk_type"}, 
            "count": {"$sum": 1}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]
    child_duplicates = list(child_coll.aggregate(qna_child_pipeline))
    child_total = child_coll.count_documents({"parent_id": {"$exists": True}})

    print(f"\n📗 [QnA Child (Vector DB) 데이터]")
    print(f"  - 총 적재 건수: {child_total:,}건")
    if not child_duplicates:
        print("  - ✅ 중복 데이터 없음! (모든 Q/A/S 파트가 고유함)")
    else:
        print(f"  - ❌ 중복 발견: {len(child_duplicates)}개의 파트가 중복 적재되었습니다.")
        for d in child_duplicates[:5]:
            print(f"    └ Parent ID: {d['_id']['parent_id']} | 타입: {d['_id']['chunk_type']} (적재 횟수: {d['count']}번)")

    # ==========================================
    # 3. 질의회신 (QnA Parent - 원본 DB) 중복 검증
    # ==========================================
    # MongoDB의 기본 _id로 그룹핑 (이론상 _id는 중복 불가하지만 안전을 위해 체크)
    qna_parent_pipeline = [
        {"$group": {"_id": "$_id", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}}
    ]
    parent_duplicates = list(parent_coll.aggregate(qna_parent_pipeline))
    parent_total = parent_coll.count_documents({})

    print(f"\n[QnA Parent (원본 텍스트) 데이터]")
    print(f"  - 총 적재 건수: {parent_total:,}건")
    if not parent_duplicates:
        print("  - ✅ 중복 데이터 없음! (모든 원본이 고유함)")
    else:
        print(f"  - ❌ 중복 발견: {len(parent_duplicates)}개의 원본이 중복 적재되었습니다.")

    print(f"\n{'='*60}")
    print("데이터 정합성 검증 완료!")
    print(f"{'='*60}")

    client.close()

if __name__ == "__main__":
    check_data_integrity()
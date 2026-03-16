"""Unicode 변형 문자가 문단 참조 주변에서 사용되는지 컨텍스트 확인."""
import os
import re
import sys

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")

client = MongoClient(os.environ["MONGO_URI"])
db = client[os.environ.get("MONGO_DB_NAME", "kifrs_db")]

# 조사 대상: 문단 참조 주변의 대시/물결표 변형
RANGE_CHARS = {
    "\u2013": "EN_DASH",     # –
    "\u2014": "EM_DASH",     # —
    "\u2212": "MINUS_SIGN",  # −
    "\u223C": "TILDE_OP",    # ∼
}

for coll_name in [
    "k-ifrs-1115-chatbot",
    "k-ifrs-1115-qna-parents",
    "k-ifrs-1115-findings-parents",
]:
    coll = db[coll_name]
    for doc in coll.find({}, {"content": 1, "_id": 1}):
        content = doc.get("content", "")
        doc_id = doc.get("_id", "")
        for ch, name in RANGE_CHARS.items():
            # 문단 참조 주변 10자 이내에 해당 문자가 있는지
            pattern = rf"문단.{{0,10}}{re.escape(ch)}|{re.escape(ch)}.{{0,10}}문단"
            for m in re.finditer(pattern, content):
                ctx_start = max(0, m.start() - 5)
                ctx_end = min(len(content), m.end() + 15)
                ctx = content[ctx_start:ctx_end]
                print(f"[{name}] {doc_id}: ...{ctx}...")

            # 숫자-대시-숫자 패턴 (문단 범위 표기)
            pattern2 = rf"\d{re.escape(ch)}\d"
            for m in re.finditer(pattern2, content):
                ctx_start = max(0, m.start() - 15)
                ctx_end = min(len(content), m.end() + 15)
                ctx = content[ctx_start:ctx_end]
                print(f"[{name} in range] {doc_id}: ...{ctx}...")

"""DB 전체 문서에서 Unicode 변형 문자 분포를 조사합니다."""
import os
import sys
from collections import Counter

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")

client = MongoClient(os.environ["MONGO_URI"])
db = client[os.environ.get("MONGO_DB_NAME", "kifrs_db")]

SUSPECTS = {
    # 따옴표
    0x2018: "LEFT_SINGLE_QUOTE",
    0x2019: "RIGHT_SINGLE_QUOTE",
    0x201C: "LEFT_DOUBLE_QUOTE",
    0x201D: "RIGHT_DOUBLE_QUOTE",
    0x0027: "APOSTROPHE",
    0x0022: "QUOTATION_MARK",
    0x300C: "LEFT_CORNER_BRACKET",
    0x300D: "RIGHT_CORNER_BRACKET",
    # 대시
    0x2013: "EN_DASH",
    0x2014: "EM_DASH",
    0x2212: "MINUS_SIGN",
    0x002D: "HYPHEN_MINUS",
    0xFF0D: "FULLWIDTH_HYPHEN",
    # 물결표
    0x007E: "TILDE",
    0x223C: "TILDE_OPERATOR",
    0xFF5E: "FULLWIDTH_TILDE",
    0x301C: "WAVE_DASH",
    # 공백
    0x00A0: "NO_BREAK_SPACE",
    0x3000: "IDEOGRAPHIC_SPACE",
    0x2003: "EM_SPACE",
    0x2002: "EN_SPACE",
    0x200B: "ZERO_WIDTH_SPACE",
    # 쉼표/마침표
    0xFF0C: "FULLWIDTH_COMMA",
    0xFF0E: "FULLWIDTH_PERIOD",
    0x3001: "IDEOGRAPHIC_COMMA",
    0x3002: "IDEOGRAPHIC_PERIOD",
    # 괄호
    0xFF08: "FULLWIDTH_LEFT_PAREN",
    0xFF09: "FULLWIDTH_RIGHT_PAREN",
}

results: Counter = Counter()

for coll_name in [
    "k-ifrs-1115-chatbot",
    "k-ifrs-1115-qna-parents",
    "k-ifrs-1115-findings-parents",
]:
    coll = db[coll_name]
    for doc in coll.find({}, {"content": 1}):
        content = doc.get("content", "")
        for ch in content:
            code = ord(ch)
            if code in SUSPECTS:
                results[(coll_name, code)] += 1

print("=== Unicode variant character distribution ===")
for (coll_name, code), count in sorted(results.items(), key=lambda x: (x[0][0], -x[1])):
    short_coll = coll_name.replace("k-ifrs-1115-", "")
    name = SUSPECTS[code]
    print(f"{short_coll:20s} U+{code:04X} {name:30s} {count:>6d}")

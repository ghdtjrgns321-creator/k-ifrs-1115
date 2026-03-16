"""Playwright로 AI 답변 좌측 패널에 pinpoint 문서가 표시되는지 확인.

python app/test/test_pinpoint_ui.py
"""
import subprocess, time, json

BASE = "http://localhost:8502"

# 1. Streamlit에서 직접 질문 전송 대신, API로 답변을 받아서 session에 세팅
# Streamlit UI를 직접 조작하기 어려우므로, API 결과를 확인
import httpx

resp = httpx.post(
    "http://localhost:8004/chat",
    json={"message": "A가 B에게 재화를 100원에 공급하고 세금계산서를 끊음. B는 C에게 120원에 판매. A의 매출액은?"},
    headers={"Accept": "text/event-stream"},
    timeout=90,
)

for line in resp.text.strip().split("\n"):
    if line.startswith("data: ") and '"done"' in line:
        data = json.loads(line[6:])
        docs = data.get("retrieved_docs") or []

        # chunk_type 분포
        types = {}
        for d in docs:
            t = d.get("chunk_type", "MISSING")
            types[t] = types.get(t, 0) + 1
        print(f"chunk_type distribution: {types}")

        # pinpoint 문서 상세
        pp = [d for d in docs if d.get("chunk_type") == "pinpoint"]
        print(f"\npinpoint docs ({len(pp)}건):")

        sources = {}
        for d in pp:
            s = d["source"]
            sources.setdefault(s, []).append(d["chunk_id"])

        for src, ids in sources.items():
            print(f"  {src}: {len(ids)}건")
            for cid in ids[:5]:
                print(f"    - {cid}")
            if len(ids) > 5:
                print(f"    ... +{len(ids)-5}건")

        break

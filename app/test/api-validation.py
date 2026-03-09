from app.config import settings

# Upstage Embedding 테스트
from app.embeddings import embed_query_sync

print("⏳ Upstage 임베딩 서버에 요청을 보냈습니다...")
vector = embed_query_sync("총액인식 순액인식 판단기준")
print(f"✅ Embedding 차원: {len(vector)}")

# PydanticAI Agent 테스트
from app.agents import analyze_agent

print("⏳ PydanticAI Agent(analyze) 테스트 중...")
result = analyze_agent.run_sync("K-IFRS 1115호에서 수행의무 식별 기준을 설명해주세요.")
print(f"✅ Analyze 결과: routing={result.data.routing}, query={result.data.standalone_query[:60]}...")

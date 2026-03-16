# UX3/4 전면 리팩토링 — 규칙 기반 전문가 시스템 전환

## Context

**현재 문제**:
1. clarify_agent가 문서를 검색해도 결론 방향을 **임의로 뒤집는 환각** 발생
2. `GenerateOutput(answer, follow_up_questions, is_conclusion)` — 답변 구조가 **너무 느슨함** (어떤 분기 선택했는지, 근거 문단이 뭔지 강제 안 됨)
3. 3개 dict (decision_trees, qna_match_trees, red_flags) 역할 중복 → 프롬프트 비대화
4. retriever 100% 의존 → 검색 실패 시 답변 품질 급락
5. `graph.py` (LangGraph) 잔존 — production은 `pipeline.py` 사용하지만 dead code 남아있음

**5가지 목표**:
1. retriever 의존도 확 낮추기
2. LangGraph 문법 없이 하기
3. PydanticAI 적극 활용해서 LLM 답변 방식 강제
4. LLM 추론 환각 방지
5. 항상 문서에 근거한 대답

**전환 방향**: LLM 역할을 "추론자" → "전달자"로 변경. 사전 큐레이션된 가이드(체크리스트+결론+사례)를 LLM이 그대로 전달.

---

## Phase 총괄

| Phase | 목표 | 핵심 변경 | 의존성 |
|-------|------|-----------|--------|
| **1** | Domain 통합 | 3개 dict → 1개 MASTER_DECISION_TREES, tree_matcher 재작성 | 없음 |
| **2** | PydanticAI 강화 | Output Schema에 `selected_branch` + `cited_paragraphs` 추가, `result_validator` 도입 | Phase 1 |
| **3** | Prompt 전면 개편 | reasoning_guard 범용화, CLARIFY_SYSTEM에 결론가이드 참조 지시 추가 | Phase 1 |
| **4** | Retriever 역할 축소 | precedents를 context 직접 주입, retriever는 원문 인용 보조로만 | Phase 1 |
| **5** | Dead Code 정리 | graph.py 삭제, LangGraph 의존성 제거, 미사용 노드 정리 | 없음 (독립) |
| **6** | 통합 테스트 + 문서 | 서버 실행, 실제 질문 검증, CLAUDE.md/MEMORY.md 업데이트 | Phase 1~5 |

---

## Phase 1: Domain 통합 (MASTER_DECISION_TREES)

### 배경
사용자가 `decision_trees_2.py` 작성 완료 (25개 토픽, 1085줄). 기존 3개 파일의 데이터를 통합한 새 스키마.

### 수정 파일

#### 1-1. `app/domain/decision_trees.py` ← 교체
- `decision_trees_2.py` → `decision_trees.py`로 rename
- 변수명: `MASTER_DECISION_TREES`

#### 1-2. `app/domain/tree_matcher.py` ← 전면 재작성
- 3개 dict import → `MASTER_DECISION_TREES` 1개
- 3개 format 함수 → `_format_checklist()` 1개 (체크리스트+결론가이드+감리경고+계산공식)
- `best_by_type` 제거 → 단순 score top-2
- `tree_type` 필드 제거
- 반환값에 `precedents`, `calculation_formula` 필드 추가
- `_calc_score()` 변경 없음

```python
# match_topics() 반환값 스키마
{
    "topic_name": str,
    "checklist_text": str,      # system prompt 주입용 (체크리스트+결론가이드+경고)
    "checklist": list[str],     # 항목 카운트용
    "judgment_goal": str,       # 검색 보강용
    "precedents": dict,         # context 주입용 (4_precedents)
    "calculation_formula": dict | None,  # context 주입용 (6_calculation_formula)
    "score": float,
}
```

#### 1-3. `app/nodes/retrieve.py` ← `_extract_checklist_keywords()` 단순화
- dict 분기 제거 (모든 checklist item이 str)
- 주석 "tree_type별" 삭제

#### 1-4. 파일 삭제
- `app/domain/qna_match_trees.py`
- `app/domain/red_flags.py`

---

## Phase 2: PydanticAI Output Schema 강화

### 배경
현재 `GenerateOutput`은 `answer`(자유 텍스트)만 있어서 LLM이 아무 답이나 할 수 있음.
분기 선택과 인용을 **구조적으로 강제**하면 환각이 구조적으로 불가능해짐.

### 수정 파일

#### 2-1. `app/agents.py` ← Output Schema 분리 + result_validator

**현재**:
```python
class GenerateOutput(BaseModel):
    answer: str
    follow_up_questions: list[str]
    is_conclusion: bool
```

**변경**: clarify_agent와 generate_agent의 출력을 분리

```python
class ClarifyOutput(BaseModel):
    """clarify_agent 전용 — 분기 선택을 구조적으로 강제."""
    selected_branches: list[str] = Field(
        description="[결론 가이드]에서 선택한 분기 라벨 (예: '[분기 1]', '[분기 2]'). "
                    "정보 부족 시 가능성 있는 분기를 모두 나열."
    )
    answer: str = Field(
        description="마크다운 답변. 반드시 selected_branches의 분기 번호를 Case로 제시."
    )
    cited_paragraphs: list[str] = Field(
        description="답변에서 인용한 K-IFRS 1115호 문단 번호 (예: ['문단 9', '문단 B35'])"
    )
    follow_up_questions: list[str] = Field(
        description="추가 확인이 필요한 핵심 질문 3개 이내"
    )
    is_conclusion: bool = Field(
        default=False,
        description="충분한 정보로 최종 결론을 내렸으면 True"
    )


class GenerateOutput(BaseModel):
    """generate_agent 전용 — 개념 답변 + 인용 강제."""
    answer: str
    cited_paragraphs: list[str] = Field(
        description="답변에서 인용한 K-IFRS 1115호 문단 번호"
    )
    follow_up_questions: list[str]
    is_conclusion: bool = Field(default=True)
```

**result_validator 추가** (clarify_agent, 강제 + retry, retries=2):
```python
@clarify_agent.result_validator
async def _validate_clarify(ctx, result: ClarifyOutput) -> ClarifyOutput:
    """선택한 분기가 conclusion_guide에 실제로 존재하는지 검증."""
    if not result.cited_paragraphs:
        raise ModelRetry("cited_paragraphs가 비어있습니다. 답변의 근거 문단을 반드시 포함하세요.")
    if not result.selected_branches:
        raise ModelRetry("selected_branches가 비어있습니다. [결론 가이드]에서 해당하는 분기를 선택하세요.")
    return result
```

#### 2-2. `app/nodes/generate.py` ← 출력 타입 분기

```python
# _run_clarify() → ClarifyOutput 사용
result = await clarify_agent.run(user_msg, deps=deps)
output: ClarifyOutput = result.output

# ClarifyOutput → 기존 SSE 호환 변환
return {
    "answer": output.answer,
    "cited_sources": _paragraphs_to_sources(output.cited_paragraphs),
    "follow_up_questions": output.follow_up_questions,
    "is_conclusion": output.is_conclusion,
    "selected_branches": output.selected_branches,  # 신규 (UI에서 활용 가능)
}
```

#### 2-3. `app/api/schemas.py` ← SSEEvent에 selected_branches 추가 (optional)

---

## Phase 3: Prompt 전면 개편

### 수정 파일

#### 3-1. `app/prompts.py` ← reasoning_guard + CLARIFY_SYSTEM

**reasoning_guard 변경** (lines 124-130):
```
<reasoning_guard>
조건부 결론(Case 분기)을 작성할 때:
- [체크리스트 가이드레일]의 [결론 가이드]에 명시된 분기를 반드시 준수하세요.
- selected_branches에 [결론 가이드]의 [분기 N] 라벨을 정확히 기입하세요.
- [결론 가이드]에 없는 분기를 지어내지 마세요.
- cited_paragraphs에 근거 문단을 반드시 기입하세요.
- [결론 가이드]가 없으면 [참고 문서]의 기준서 원문 논리를 따르세요.
</reasoning_guard>
```

**CLARIFY_SYSTEM에 추가**:
```
[중요] selected_branches 필드에는 [결론 가이드]의 [분기 N] 라벨을 정확히 복사하세요.
정보가 부족하면 가능성 있는 모든 분기를 나열하고, 각 Case에서 해당 분기의 조건과 결론을 설명하세요.
```

---

## Phase 4: Retriever 역할 축소

### 배경
MASTER_DECISION_TREES의 `4_precedents`에 IE 사례, QNA 질의회신, 감리사례가 이미 큐레이션되어 있음.
이를 context에 직접 주입하면 retriever가 해당 사례를 못 찾아도 LLM은 답변 가능.

### 수정 파일

#### 4-1. `app/nodes/generate.py` ← `_run_clarify()` 수정

precedents + calculation_formula를 context_str에 추가:
```python
# matched_topics에서 큐레이션된 데이터 추출
for topic in matched_topics:
    # 4_precedents → 선례/질의회신
    precedents = topic.get("precedents", {})
    if precedents:
        lines = [f"\n[선례/질의회신: {topic['topic_name']}]"]
        for branch, refs in precedents.items():
            lines.append(f"  {branch}:")
            lines.extend(f"    {ref}" for ref in refs)
        extra_parts.append("\n".join(lines))

    # 6_calculation_formula → 계산 공식
    formula = topic.get("calculation_formula")
    if formula:
        lines = [f"\n[계산 공식: {topic['topic_name']}]"]
        for branch, text in formula.items():
            lines.append(f"  {branch}: {text}")
        extra_parts.append("\n".join(lines))

if extra_parts:
    context_str += "\n\n---\n\n" + "\n\n".join(extra_parts)
```

#### 4-2. `app/nodes/generate.py` ← `_run_force_conclusion()` 수정
force_conclusion에서도 동일하게 precedents 주입.

### retriever 자체는 유지
기준서 원문 인용이 필요할 때 해당 문단을 가져오는 보조 도구로 역할 축소.
retrieve → rerank 경로 자체를 제거하지는 않음 (원문 인용 품질 유지).

---

## Phase 5: Dead Code 정리

### 삭제 대상

| 파일 | 이유 |
|------|------|
| `app/graph.py` | LangGraph StateGraph — production은 pipeline.py 사용 |
| `app/llm.py` | LangChain ChatOpenAI 팩토리 — agents.py로 대체됨 |
| `app/test/graph-test.py` | graph.py 의존 테스트 |
| `app/test/stress-test.py` | graph.py 의존 테스트 |
| `app/test/stress-test2.py` | graph.py 의존 테스트 |

### 의존성 정리 (`pyproject.toml`)

확인 후 제거:
- `langgraph` — graph.py 전용
- `langchain-openai` — llm.py 전용 (agents.py가 PydanticAI 직접 사용)
- `langchain-upstage` — embeddings.py가 직접 REST API 사용하는지 확인 필요

### 미사용 노드 삭제

| 노드 | 상태 | 조치 |
|------|------|------|
| `app/nodes/grade.py` | Cohere threshold로 대체 | **삭제** |
| `app/nodes/hyde_retrieve.py` | pipeline.py에서 미호출 | **삭제** |
| `app/nodes/rewrite.py` | pipeline.py에서 미호출 | **삭제** |

---

## Phase 6: 통합 테스트 + 문서 업데이트

### 테스트 시나리오

```bash
uv run uvicorn app.main:app --port 8002
```

1. **본인/대리인 질문**: "A가 B에게 상품을 위탁판매하는데 수익은?"
   - 확인: `selected_branches`에 `[분기 1]` 또는 `[분기 2]` 포함
   - 확인: `cited_paragraphs`에 `문단 B35` 등 포함
   - 확인: `[선례/질의회신]`에 IE 사례 45~48 포함

2. **진행률 계산**: "건설공사 진행률 어떻게 계산해?"
   - 확인: `[계산 공식]` context에 포함
   - 확인: 투입법/산출법 분기 포함

3. **환각 검증**: 이전에 환각이 발생했던 질문 재테스트
   - 확인: Case 분기가 conclusion_guide 방향과 일치하는지
   - 확인: result_validator가 빈 인용을 reject하는지

4. **멀티턴**: 꼬리질문 2~3턴 후 force_conclusion
   - 확인: checked_items 누적, selected_branches 변화

### 문서 업데이트
- `CLAUDE.md` — 기술 스택, 디렉토리 구조, 파이프라인 다이어그램
- `MEMORY.md` — 기술 결정 사항, 핵심 파일 경로

---

## 변경 안 하는 파일 (확인 완료)

| 파일 | 이유 |
|------|------|
| `app/pipeline.py` | 이미 순수 Python. 노드 호출 순서 변경 없음 |
| `app/services/session_store.py` | 세션/캐시 로직 변경 없음 |
| `app/services/search_service.py` | /search 파이프라인 독립 |
| `app/retriever.py` | 하이브리드 검색 로직 유지 |
| `app/reranker.py` | Cohere Reranker 유지 |
| `app/embeddings.py` | Upstage 임베딩 유지 |
| `app/domain/summary_matcher.py` | UI pinpoint 패널용 독립 모듈 |
| `app/domain/topic_content_map.py` | UI topic browse용 독립 모듈 |
| `app/nodes/format.py` | 감리사례 넛지 독립 모듈 |
| `app/state.py` | `matched_topics: list[dict]` 타입 동일 |

---

## 전체 데이터 플로우 (리팩토링 후)

```
사용자 질문
  ↓
analyze_agent → AnalyzeResult (routing, is_situation, search_keywords, ...)
  ↓
match_topics(standalone_query, search_keywords) [tree_matcher.py]
  → matched_topics: [{..., precedents, calculation_formula, ...}]
  ↓
state["matched_topics"]
  ├→ retrieve.py: 문단 번호 + judgment_goal로 검색 보강 (보조 역할)
  │
  ├→ agents.py: _inject_clarify_system()
  │   → checklist_text (체크리스트+결론가이드+감리경고) → system prompt
  │
  └→ generate.py: _run_clarify()
      ├→ precedents + calculation_formula → context_str 추가
      └→ clarify_agent.run() → ClarifyOutput
           ├→ selected_branches: ["[분기 1]"]  ← 구조적 분기 강제
           ├→ cited_paragraphs: ["문단 B35"]   ← 인용 강제
           ├→ answer: "Case 1: ..."            ← 결론가이드 준수
           └→ result_validator가 빈 인용/분기 reject
```

---

## 실행 순서 (Phase별 분리 — 각 Phase 완료 후 테스트)

```
Phase 1 (Domain 통합) → 서버 실행 + 기본 동작 확인
  ├─ decision_trees_2.py → decision_trees.py rename
  ├─ tree_matcher.py 전면 재작성
  ├─ retrieve.py 단순화
  └─ qna_match_trees.py, red_flags.py 삭제
  ✅ 검증: 서버 기동, 체크리스트 매칭 + 결론가이드 system prompt 주입 확인

Phase 2 (PydanticAI 강화) → selected_branches + 인용 강제 확인
  ├─ ClarifyOutput 스키마 정의 (selected_branches, cited_paragraphs)
  ├─ result_validator 추가 (강제 + retry, retries=2)
  ├─ generate.py 출력 타입 분기
  └─ schemas.py SSEEvent 확장
  ✅ 검증: clarify 응답에 selected_branches + cited_paragraphs 포함 확인

Phase 3 (Prompt 개편) → 환각 방지 효과 확인
  ├─ reasoning_guard 범용화
  └─ CLARIFY_SYSTEM 분기 선택 지시 추가
  ✅ 검증: 이전 환각 질문 재테스트, Case가 conclusion_guide와 일치하는지

Phase 4 (Retriever 역할 축소) → precedents context 주입 확인
  ├─ generate.py에 precedents/formula context 주입
  └─ force_conclusion에도 동일 적용
  ✅ 검증: [선례/질의회신] 섹션이 context에 포함되는지

Phase 5 (Dead Code 정리) → import error 없음 확인
  ├─ graph.py, llm.py 삭제
  ├─ 미사용 테스트 삭제 (graph-test, stress-test, stress-test2)
  ├─ 미사용 노드 삭제 (grade.py, hyde_retrieve.py, rewrite.py)
  └─ pyproject.toml 의존성 정리
  ✅ 검증: ruff check + 서버 기동 + 전체 파이프라인 정상 동작

Phase 6 (통합 테스트 + 문서) → 최종 확인
  ├─ 서버 실행 + 실제 질문 5개 이상 테스트
  └─ CLAUDE.md, MEMORY.md 업데이트
```

---

## 잠재적 리스크

1. **checklist_text 토큰 증가**: conclusion_guide + red_flags + formula + precedents 포함으로 system prompt + context 길어짐 → reasoning 모델 입력 토큰 비례 응답 시간 증가 → 모니터링 필요
2. **ClarifyOutput 전환 시 SSE 호환**: 기존 `GenerateOutput` → `ClarifyOutput` 분리 시 Streamlit 클라이언트 코드도 수정 필요할 수 있음 → selected_branches는 optional로 추가하여 하위 호환 유지
3. **result_validator retry**: cited_paragraphs 누락 시 LLM 재호출 → 응답 시간 +α → retries=2 제한
4. **trigger_keywords 커버리지**: 기존 ~40개 토픽(3개 dict) → 25개 통합 → 일부 키워드 누락 가능 → 테스트로 검증

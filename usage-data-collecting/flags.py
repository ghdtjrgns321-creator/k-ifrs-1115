"""L1 검색·인용 자동 점검 — LLM 없이 로그에 남은 사실만 대조한다. 오판 0.

설계: docs/quality-loop/02-scoring.md §3
진입 구조 기준: docs/entry-traverse/plan.md §5 (진입 통로 2개)

  ① 용어사전 경유 — 같은 사전을 두 방법으로 읽는다
       글자매칭  질문(재작성문)에 용어가 글자 그대로 있으면 잡는다 → matched_terms
       LLM 선택  용어 목록 349개에서 고르게 한다 → term_hints → via_llm
                 목록 밖 답은 버리고 unknown_terms로 남긴다
  ② 임베딩      사용자 원문 벡터 → via_embed (사전에 없는 표현 대비)

두 갈래로 기록한다.
  flags        — 확실한 실패. 오판이 없어 그대로 제안 대기열로 간다
  observations — 실패는 아니지만 사전·지시문 보강 후보

"답변이 좋은가"는 여기서 판정하지 않는다.
"""

from __future__ import annotations

from app.test.qna_holdout.grade import norm_para

# 진입 흔적이 존재하는 유일한 경로. 나머지(fast_path·pre_retrieved·rejected)는
# analyze·retrieve를 건너뛰므로 진입 판정 대상이 아니다.
SCORABLE_FLOW = "full"

# 확실한 실패 → 추정 원인 층 (docs/quality-loop/00-overview.md §2)
# 순서 = 판정 우선순위. 앞선 항목이 더 근본적인 원인이다.
LAYER_OF: dict[str, int] = {
    "ENTRY_EMPTY": 1,
    "NO_DOCS": 4,
    "CITATION_OUT": 3,
}

# 보강 후보 → 추정 원인 층. flags와 섞지 않는다.
# Why(이상이 아닌 이유): 답변은 정상적으로 나왔다. 사전 통로가 놀았거나 원문 어휘가
# 사전에 없었을 뿐이다. L1이 "오판 0"이려면 실패 아닌 것을 실패로 세면 안 된다.
OBSERVATION_OF: dict[str, int] = {
    "TERM_UNKNOWN": 1,
    "DICT_MISS": 1,
    "TERM_MISS_RAW": 1,
    "HINT_EMPTY": 2,
}

# 사람에게 보여줄 설명 — 승인 화면은 코드명을 노출하지 않는다.
HUMAN_TEXT: dict[str, str] = {
    "ENTRY_EMPTY": "질문에서 어떤 개념도 찾지 못해 검색이 비었습니다.",
    "NO_DOCS": "개념은 찾았는데 기준서 원문이 하나도 붙지 않았습니다.",
    "CITATION_OUT": "답변이 실제로 읽지 않은 문단을 인용했습니다.",
    "TERM_UNKNOWN": "AI가 필요하다고 답한 용어가 용어사전에 없어 버려졌습니다.",
    "DICT_MISS": "용어사전이 이 질문에서 아무 개념도 찾지 못해, 임베딩만으로 검색했습니다.",
    "TERM_MISS_RAW": "사용자가 쓴 말은 용어사전에 없고, AI가 문장을 정식 용어로 고쳐 쓴 덕분에 걸렸습니다.",
    "HINT_EMPTY": "AI가 용어 목록에서 아무것도 고르지 못했습니다.",
}


def _scorable(log: dict) -> bool:
    """진입 판정을 할 수 있는 로그인가. 구버전 로그의 outcome 없음은 성공으로 본다."""
    return log.get("outcome", "ok") == "ok" and log.get("flow") == SCORABLE_FLOW


def l1_flags(log: dict) -> list[str]:
    """로그 1건 → 확실한 실패 목록. 순서는 LAYER_OF 정의 순."""
    if not _scorable(log):
        return []
    entry = log.get("entry") or {}
    retrieval = log.get("retrieval") or {}

    found: list[str] = []
    if not (entry.get("concept_ids") or []):
        found.append("ENTRY_EMPTY")
    if not retrieval.get("doc_count"):
        found.append("NO_DOCS")
    if _citation_out(log):
        found.append("CITATION_OUT")
    return sorted(found, key=lambda f: list(LAYER_OF).index(f))


def l1_observations(log: dict) -> list[str]:
    """로그 1건 → 보강 후보 목록. 실패가 아니므로 flags와 분리해 기록한다."""
    if not _scorable(log):
        return []
    entry = log.get("entry") or {}
    matched = entry.get("matched_terms") or []
    via_llm = entry.get("via_llm") or []
    hints = entry.get("term_hints") or []
    raw = entry.get("matched_terms_raw")

    found: list[str] = []
    # LLM이 목록 밖 용어를 답했다 → 그 문자열이 곧 사전 등재 후보다
    if entry.get("unknown_terms"):
        found.append("TERM_UNKNOWN")
    # 사전 두 통로(글자매칭·LLM 선택)가 둘 다 개념을 못 냈다
    if not via_llm and not matched:
        found.append("DICT_MISS")
    # 원문은 못 걸렸는데 재작성문이 걸렸다 (01 문서 §6)
    if raw is not None and not raw and matched:
        found.append("TERM_MISS_RAW")
    # LLM이 349개 목록에서 하나도 못 골랐다 → 지시문·목록 쪽 문제
    if not hints:
        found.append("HINT_EMPTY")
    return sorted(found, key=lambda f: list(OBSERVATION_OF).index(f))


def _citation_out(log: dict) -> bool:
    """답변이 LLM에게 주어지지 않은 문단을 인용했는가.

    기준 집합은 context_paras(실제로 받은 문단)다. 그래프 후보(paras)가 아니다 —
    두 집합은 어긋난다. 계산 질문은 IE 적용사례를 컨텍스트에서 빼고(generate.py),
    반대로 후보 목록에 없는 문단이 컨텍스트에 들어오기도 한다.
    """
    cited = {norm_para(p) for p in (log.get("cited_paragraphs") or [])}
    if not cited:
        return False
    context = {
        norm_para(p) for p in ((log.get("retrieval") or {}).get("context_paras") or [])
    }
    return bool(cited - context)


def is_unreliable(log: dict) -> bool:
    """답변이 저장 상한에서 잘려 인용 판정이 불완전한가."""
    return bool(log.get("answer_len", 0) > len(log.get("answer") or ""))


# 재질문으로 셀 후속 flow. fast_path(되묻기 답신)는 시스템이 유도한 정상 흐름이라
# 불만 신호가 아니고, rejected(범위 밖)는 앞 답변과 무관한 질문일 가능성이 높다.
FOLLOWUP_FLOWS = ("full", "pre_retrieved")


def is_followup(log: dict, next_log: dict | None) -> bool:
    """이 답변 뒤에 같은 세션에서 새 질문이 왔는가 — 답이 부족했다는 사람 신호.

    Why: 실사용 로그에는 정답이 없다. 정답을 대신할 수 있는 건 사용자 행동뿐이고,
    재질문은 👎와 달리 사용자가 버튼을 누르지 않아도 남는다. 판정은 코드로 끝난다.

    임계(몇 분 안에 물었나)를 두지 않는다 — 세션 자체가 경계다.
    """
    if not _scorable(log) or not next_log:
        return False
    return next_log.get("flow") in FOLLOWUP_FLOWS


def suspect_layer(
    flags: list[str], observations: list[str] | None = None
) -> int | None:
    """항목 목록 → 추정 원인 층. 확정이 아니라 추정이다. 실패가 관찰보다 우선."""
    for f in flags:
        if f in LAYER_OF:
            return LAYER_OF[f]
    for o in observations or []:
        if o in OBSERVATION_OF:
            return OBSERVATION_OF[o]
    return None

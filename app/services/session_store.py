# app/services/session_store.py
# 인메모리 세션 관리 — 멀티턴 대화 히스토리 + 검색 캐시 + 체크리스트 상태
#
# Step 5 멀티턴 개선: checklist_state + cached_relevant_docs 추가
#   - checklist_state: Decision Tree 체크리스트 진행 상태
#   - cached_relevant_docs: 첫 턴 검색 결과 재활용 (후속 턴 retrieve 스킵)
from dataclasses import dataclass, field
from uuid import uuid4

from cachetools import TTLCache

SESSION_TTL_SECONDS = 30 * 60
MAX_SESSIONS = 100


@dataclass
class _SessionData:
    # [("human", "질문"), ("ai", "답변"), ...]
    messages: list[tuple[str, str]] = field(default_factory=list)
    # /search 결과 캐시: search_id → docs 리스트
    search_cache: dict[str, list[dict]] = field(default_factory=dict)
    # 체크리스트 진행 상태 (is_situation=True 멀티턴용)
    # {matched_topics: [...], checked_items: ["가격결정권", ...], turn_count: 1}
    checklist_state: dict | None = None
    # 첫 턴 검색 결과 재활용 (후속 턴에서 retrieve 스킵)
    cached_relevant_docs: list[dict] | None = None


class SessionStore:
    """세션 ID를 키로 대화 히스토리 + 검색 캐시 + 체크리스트를 관리합니다."""

    def __init__(self):
        self._sessions: TTLCache = TTLCache(
            maxsize=MAX_SESSIONS,
            ttl=SESSION_TTL_SECONDS,
        )

    # ── 대화 히스토리 ──────────────────────────────────────────────────────────

    def get_messages(self, session_id: str) -> list[tuple[str, str]]:
        session = self._sessions.get(session_id)
        if session:
            self._touch(session_id)
            return session.messages
        return []

    def append_turn(self, session_id: str, user_msg: str, ai_msg: str) -> None:
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionData()
        session = self._sessions[session_id]
        session.messages.append(("human", user_msg))
        session.messages.append(("ai", ai_msg))
        self._touch(session_id)

    # ── 검색 캐시 ────────────────────────────────────────────────────────────

    def store_search(self, session_id: str, search_id: str, docs: list[dict]) -> None:
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionData()
        session = self._sessions[session_id]
        session.search_cache = {search_id: docs}
        self._touch(session_id)

    def get_search(self, session_id: str, search_id: str) -> list[dict] | None:
        session = self._sessions.get(session_id)
        if session:
            self._touch(session_id)
            return session.search_cache.get(search_id)
        return None

    # ── 체크리스트 상태 (멀티턴 꼬리질문) ──────────────────────────────────────

    def get_checklist_state(self, session_id: str) -> dict | None:
        session = self._sessions.get(session_id)
        if session:
            return session.checklist_state
        return None

    def set_checklist_state(self, session_id: str, state: dict | None) -> None:
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionData()
        self._sessions[session_id].checklist_state = state
        self._touch(session_id)

    # ── 검색 결과 캐시 (멀티턴 retrieve 스킵) ─────────────────────────────────

    def get_cached_docs(self, session_id: str) -> list[dict] | None:
        session = self._sessions.get(session_id)
        if session:
            return session.cached_relevant_docs
        return None

    def set_cached_docs(self, session_id: str, docs: list[dict] | None) -> None:
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionData()
        self._sessions[session_id].cached_relevant_docs = docs
        self._touch(session_id)

    # ── 유틸리티 ─────────────────────────────────────────────────────────────

    def new_session_id(self) -> str:
        return str(uuid4())

    def count(self) -> int:
        return len(self._sessions)

    def _touch(self, session_id: str) -> None:
        """접근 시 TTL을 초기화해 sliding expiry를 구현합니다."""
        if session_id in self._sessions:
            data = self._sessions.pop(session_id)
            self._sessions[session_id] = data


store = SessionStore()

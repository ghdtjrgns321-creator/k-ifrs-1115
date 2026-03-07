# app/services/session_store.py
# 인메모리 세션 관리 — 멀티턴 대화 히스토리 + 검색 결과 캐시를 세션 ID별로 보관합니다.
#
# 설계 결정: Redis 없이 cachetools TTLCache를 사용하는 이유
#   - 포트폴리오/데모 환경에서 동시 사용자 수가 적으므로 충분합니다.
#   - TTLCache가 maxsize(LRU 퇴출)와 TTL 만료를 자동으로 처리합니다.
#   - sliding TTL(접근 시마다 TTL 갱신)은 _touch()로 재삽입하여 구현합니다.
from dataclasses import dataclass, field
from uuid import uuid4

from cachetools import TTLCache

# 세션 미접근 시 만료 시간 (30분, 초 단위)
SESSION_TTL_SECONDS = 30 * 60
# 최대 세션 수 — 초과 시 TTLCache의 LRU 정책으로 가장 오래된 세션이 자동 퇴출됩니다.
MAX_SESSIONS = 100


@dataclass
class _SessionData:
    # LangGraph RAGState의 messages 필드에 직접 넣을 튜플 리스트
    # 형식: [("human", "질문"), ("ai", "답변"), ...]
    messages: list[tuple[str, str]] = field(default_factory=list)
    # /search 결과 캐시: search_id → relevant_docs 리스트
    # /chat 요청 시 search_id가 있으면 이 캐시에서 docs를 꺼내 retrieve/rerank를 스킵합니다.
    search_cache: dict[str, list[dict]] = field(default_factory=dict)
    # last_access 불필요 — TTLCache가 TTL을 직접 관리합니다.


class SessionStore:
    """세션 ID를 키로 대화 히스토리 + 검색 캐시를 관리합니다."""

    def __init__(self):
        # maxsize: LRU 퇴출 기준, ttl: 마지막 삽입 시점 기준 자동 만료 (초)
        self._sessions: TTLCache = TTLCache(
            maxsize=MAX_SESSIONS,
            ttl=SESSION_TTL_SECONDS,
        )

    # ── 대화 히스토리 ──────────────────────────────────────────────────────────────

    def get_messages(self, session_id: str) -> list[tuple[str, str]]:
        """세션의 대화 히스토리를 반환합니다. 없으면 빈 리스트."""
        session = self._sessions.get(session_id)
        if session:
            self._touch(session_id)
            return session.messages
        return []

    def append_turn(self, session_id: str, user_msg: str, ai_msg: str) -> None:
        """한 턴(사용자 + AI 답변)을 세션 히스토리에 추가합니다."""
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionData()
        session = self._sessions[session_id]
        session.messages.append(("human", user_msg))
        session.messages.append(("ai", ai_msg))
        # 메시지 추가 후 TTL을 갱신하여 활성 세션이 만료되지 않도록 합니다.
        self._touch(session_id)

    # ── 검색 캐시 ──────────────────────────────────────────────────────────────────

    def store_search(self, session_id: str, search_id: str, docs: list[dict]) -> None:
        """/search 결과를 search_id 키로 세션에 캐시합니다.

        /chat 요청 시 search_id를 전달하면 이 캐시에서 docs를 꺼내
        retrieve/rerank 단계를 건너뜁니다 (pre_retrieved_docs 패턴).

        이전 검색 결과를 지우고 최신 1개만 유지합니다.
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionData()
        session = self._sessions[session_id]
        # 이전 캐시를 교체하여 메모리 누적을 방지합니다.
        session.search_cache = {search_id: docs}
        self._touch(session_id)

    def get_search(self, session_id: str, search_id: str) -> list[dict] | None:
        """캐시된 검색 결과를 반환합니다. 없으면 None."""
        session = self._sessions.get(session_id)
        if session:
            self._touch(session_id)
            return session.search_cache.get(search_id)
        return None

    # ── 유틸리티 ───────────────────────────────────────────────────────────────────

    def new_session_id(self) -> str:
        """신규 세션 ID를 발급합니다."""
        return str(uuid4())

    def count(self) -> int:
        return len(self._sessions)

    def _touch(self, session_id: str) -> None:
        """접근 시 TTL을 초기화해 sliding expiry를 구현합니다.

        TTLCache는 삽입(insert) 시점을 기준으로 TTL을 계산합니다.
        따라서 기존 값을 pop 후 재삽입하면 TTL 타이머가 초기화됩니다.
        """
        if session_id in self._sessions:
            data = self._sessions.pop(session_id)
            self._sessions[session_id] = data


# 앱 전체에서 공유하는 싱글턴 인스턴스
store = SessionStore()

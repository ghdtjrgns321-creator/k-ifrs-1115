# app/services/session_store.py
# 인메모리 세션 관리 — 멀티턴 대화 히스토리를 세션 ID별로 보관합니다.
#
# 설계 결정: Redis 없이 Python dict를 사용하는 이유
#   - 포트폴리오/데모 환경에서 동시 사용자 수가 적으므로 충분합니다.
#   - Redis를 추가하면 배포 복잡도가 높아지고, 핵심 가치(RAG 품질)와 무관합니다.
#   - TTL 만료로 메모리 누수를 방지합니다.
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import uuid4

# 세션 미접근 시 만료 시간 (30분)
SESSION_TTL = timedelta(minutes=30)
# 최대 세션 수 — 초과 시 가장 오래된 세션부터 제거합니다.
MAX_SESSIONS = 100


@dataclass
class _SessionData:
    # LangGraph RAGState의 messages 필드에 직접 넣을 튜플 리스트
    # 형식: [("human", "질문"), ("ai", "답변"), ...]
    messages: list[tuple[str, str]] = field(default_factory=list)
    last_access: datetime = field(default_factory=datetime.now)


class SessionStore:
    """세션 ID를 키로 대화 히스토리를 관리합니다."""

    def __init__(self):
        self._sessions: dict[str, _SessionData] = {}

    def get_messages(self, session_id: str) -> list[tuple[str, str]]:
        """세션의 대화 히스토리를 반환합니다. 없으면 빈 리스트."""
        self._cleanup_expired()
        session = self._sessions.get(session_id)
        if session:
            session.last_access = datetime.now()
            return session.messages
        return []

    def append_turn(self, session_id: str, user_msg: str, ai_msg: str) -> None:
        """한 턴(사용자 + AI 답변)을 세션 히스토리에 추가합니다."""
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionData()
        session = self._sessions[session_id]
        session.messages.append(("human", user_msg))
        session.messages.append(("ai", ai_msg))
        session.last_access = datetime.now()
        self._enforce_max_sessions()

    def new_session_id(self) -> str:
        """신규 세션 ID를 발급합니다."""
        return str(uuid4())

    def count(self) -> int:
        return len(self._sessions)

    def _cleanup_expired(self) -> None:
        """TTL 초과 세션을 제거합니다."""
        cutoff = datetime.now() - SESSION_TTL
        expired = [sid for sid, s in self._sessions.items() if s.last_access < cutoff]
        for sid in expired:
            del self._sessions[sid]

    def _enforce_max_sessions(self) -> None:
        """최대 세션 수 초과 시 가장 오래된 세션을 제거합니다."""
        if len(self._sessions) > MAX_SESSIONS:
            oldest = min(self._sessions, key=lambda sid: self._sessions[sid].last_access)
            del self._sessions[oldest]


# 앱 전체에서 공유하는 싱글턴 인스턴스
store = SessionStore()

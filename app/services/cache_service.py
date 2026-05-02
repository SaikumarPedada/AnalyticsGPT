"""
In-memory session cache. All active (unsaved) sessions live here.
Swap for Redis by replacing the dict with redis-py calls if you need
multi-process / multi-instance deployments.
"""
import uuid
from datetime import datetime, timedelta
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()


class SessionCache:
    def __init__(self):
        self.active_sessions: dict = {}

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _is_expired(self, session: dict) -> bool:
        idle_timeout = timedelta(minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES)
        return datetime.utcnow() - session["last_active"] > idle_timeout

    def _touch(self, session_id: str) -> None:
        """Update last-active timestamp to reset the idle TTL."""
        self.active_sessions[session_id]["last_active"] = datetime.utcnow()

    def _evict_expired(self) -> None:
        """Remove sessions that have exceeded the idle timeout."""
        expired = [
            sid for sid, data in self.active_sessions.items()
            if self._is_expired(data)
        ]
        for sid in expired:
            logger.info(f"Evicting expired session: {sid}")
            self.active_sessions.pop(sid, None)

    # ── Lifecycle ──────────────────────────────────────────────────────────────
    def create_session(self, user_id: int) -> str:
        self._evict_expired()
        session_id = str(uuid.uuid4())
        now = datetime.utcnow()
        self.active_sessions[session_id] = {
            "user_id": user_id,
            "conversation": [],
            "tokens": 0,
            "tools": [],
            "start_time": now,
            "last_active": now,
        }
        logger.debug(f"Session created: {session_id} for user {user_id}")
        return session_id

    def validate(self, session_id: str) -> None:
        if session_id not in self.active_sessions:
            raise ValueError(f"Invalid or expired session: {session_id}")
        session = self.active_sessions[session_id]
        if self._is_expired(session):
            self.active_sessions.pop(session_id)
            raise ValueError(f"Session timed out: {session_id}")

    def session_exists(self, session_id: str) -> bool:
        if session_id not in self.active_sessions:
            return False
        if self._is_expired(self.active_sessions[session_id]):
            self.active_sessions.pop(session_id)
            return False
        return True

    def end_session(self, session_id: str) -> dict:
        self.validate(session_id)
        data = self.active_sessions.pop(session_id)
        logger.debug(f"Session ended: {session_id}")
        return data

    # ── Messages ───────────────────────────────────────────────────────────────
    def add_message(self, session_id: str, role: str, content: str, tokens: int = 0) -> None:
        self.validate(session_id)
        self._touch(session_id)
        self.active_sessions[session_id]["conversation"].append({
            "role": role,
            "content": content,
            "tokens": tokens,
            "timestamp": datetime.utcnow().isoformat(),
        })
        self.active_sessions[session_id]["tokens"] += tokens

    def get_conversation(self, session_id: str) -> list:
        self.validate(session_id)
        return [
            {"role": m["role"], "content": m["content"]}
            for m in self.active_sessions[session_id]["conversation"]
        ]

    # ── Tokens / Tools ─────────────────────────────────────────────────────────
    def add_tokens(self, session_id: str, tokens: int) -> None:
        self.validate(session_id)
        self.active_sessions[session_id]["tokens"] += tokens

    def add_tool(self, session_id: str, tool_name: str) -> None:
        self.validate(session_id)
        self.active_sessions[session_id]["tools"].append(tool_name)

    # ── Read ───────────────────────────────────────────────────────────────────
    def get_session(self, session_id: str) -> dict:
        self.validate(session_id)
        return self.active_sessions[session_id]

    def get_user_id(self, session_id: str) -> int:
        self.validate(session_id)
        return self.active_sessions[session_id]["user_id"]

    def get_token_count(self, session_id: str) -> int:
        self.validate(session_id)
        return self.active_sessions[session_id]["tokens"]

    def active_count(self) -> int:
        self._evict_expired()
        return len(self.active_sessions)


cache = SessionCache()
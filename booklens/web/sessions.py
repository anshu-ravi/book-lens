"""In-memory registry of live chat sessions, capped so pinned context text can't grow unbounded."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from booklens.chat import ChatSession

MAX_SESSIONS = 8


@dataclass
class SessionRecord:
    """A live chat session and the two connections it owns for its whole life."""

    session_id: str
    book_id: str
    session: ChatSession
    iconn: sqlite3.Connection
    session_pconn: sqlite3.Connection
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SessionRegistry:
    """Live chat sessions, capped at `max_sessions`; the oldest is dropped to make room."""

    def __init__(self, max_sessions: int = MAX_SESSIONS):
        self._max_sessions = max_sessions
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = threading.Lock()

    def create(
        self,
        book_id: str,
        session: ChatSession,
        iconn: sqlite3.Connection,
        session_pconn: sqlite3.Connection,
    ) -> str:
        """Register a new session and return its id, evicting the oldest if over capacity."""
        sid = uuid.uuid4().hex
        record = SessionRecord(
            session_id=sid, book_id=book_id, session=session, iconn=iconn, session_pconn=session_pconn
        )
        with self._lock:
            self._sessions[sid] = record
            while len(self._sessions) > self._max_sessions:
                oldest = min(self._sessions.values(), key=lambda r: r.created_at)
                self._drop_locked(oldest.session_id)
        return sid

    def get(self, sid: str) -> SessionRecord | None:
        """Look up a session by id, or None if it doesn't exist."""
        with self._lock:
            return self._sessions.get(sid)

    def drop(self, sid: str) -> None:
        """Close a session's connections and remove it; a no-op if unknown."""
        with self._lock:
            self._drop_locked(sid)

    def _drop_locked(self, sid: str) -> None:
        """Caller must hold `_lock`."""
        record = self._sessions.pop(sid, None)
        if record is None:
            return
        record.iconn.close()
        record.session_pconn.close()


registry = SessionRegistry()

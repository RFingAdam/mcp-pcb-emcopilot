"""In-memory design session manager.

Replaces PostgreSQL — holds parsed PCBDesignData in a dict keyed by session ID.
Sessions persist for the lifetime of the MCP server process.
"""

from __future__ import annotations

import logging
import time
import uuid

from .models.pcb_data import PCBDesignData

logger = logging.getLogger(__name__)

MAX_SESSIONS = 50
SESSION_TTL_S = 3600


class DesignSessionManager:
    """Manages parsed PCB design sessions in memory."""

    def __init__(self) -> None:
        self._sessions: dict[str, PCBDesignData] = {}
        self._timestamps: dict[str, float] = {}

    def create_session(self, design_data: PCBDesignData) -> str:
        """Store a parsed design and return a new session ID."""
        self._evict_stale()
        if len(self._sessions) >= MAX_SESSIONS:
            oldest = min(self._timestamps, key=self._timestamps.get)  # type: ignore[arg-type]
            self.close_session(oldest)
            logger.warning("Evicted oldest session %s (max %d reached)", oldest, MAX_SESSIONS)
        while True:
            session_id = uuid.uuid4().hex[:12]
            if session_id not in self._sessions:
                break
        self._sessions[session_id] = design_data
        self._timestamps[session_id] = time.time()
        return session_id

    def get_session(self, session_id: str) -> PCBDesignData | None:
        """Retrieve the design data for a session, or None if not found."""
        return self._sessions.get(session_id)

    def close_session(self, session_id: str) -> bool:
        """Remove a session. Returns True if the session existed."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            del self._timestamps[session_id]
            return True
        return False

    def replace_session(self, session_id: str, design_data: PCBDesignData) -> bool:
        """Replace the design data for an existing session in-place.

        Used by ``pcb_parse_layout`` when it is asked to write parsed data
        into an existing session (e.g. one created by
        ``pcb_start_professional_review``). The caller is responsible for
        copying any prior ``review_context`` / ``review_results`` from the
        old session onto ``design_data`` before calling.

        Returns ``True`` if the session existed and was replaced, ``False``
        otherwise.
        """
        if session_id not in self._sessions:
            return False
        self._sessions[session_id] = design_data
        self._timestamps[session_id] = time.time()
        return True

    def list_sessions(self) -> list[dict[str, str | int | float]]:
        """Return summary metadata for all active sessions."""
        result: list[dict[str, str | int | float]] = []
        for sid, data in self._sessions.items():
            result.append({
                "session_id": sid,
                "source_file": data.source_file,
                "format": data.source_format,
                "components": data.component_count,
                "nets": data.net_count,
                "created": self._timestamps.get(sid, 0),
            })
        return result

    def _evict_stale(self) -> None:
        now = time.time()
        stale = [sid for sid, ts in self._timestamps.items() if now - ts > SESSION_TTL_S]
        for sid in stale:
            self.close_session(sid)
            logger.info("Evicted stale session %s", sid)

    @property
    def session_count(self) -> int:
        """Return the number of active sessions."""
        return len(self._sessions)

"""In-memory design session manager.

Replaces PostgreSQL — holds parsed PCBDesignData in a dict keyed by session ID.
Sessions persist for the lifetime of the MCP server process.
"""

from __future__ import annotations

import time
import uuid

from .models.pcb_data import PCBDesignData


class DesignSessionManager:
    """Manages parsed PCB design sessions in memory."""

    def __init__(self) -> None:
        self._sessions: dict[str, PCBDesignData] = {}
        self._timestamps: dict[str, float] = {}

    def create_session(self, design_data: PCBDesignData) -> str:
        """Store a parsed design and return a new session ID."""
        session_id = str(uuid.uuid4())[:8]
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

    @property
    def session_count(self) -> int:
        """Return the number of active sessions."""
        return len(self._sessions)

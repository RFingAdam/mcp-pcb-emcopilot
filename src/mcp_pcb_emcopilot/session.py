"""In-memory design session manager.

Replaces PostgreSQL — holds parsed PCBDesignData in a dict keyed by session ID.
Sessions persist for the lifetime of the MCP server process.

In addition to design data, each session can hold two ancillary queues used by
the Phase 3 cross-MCP intent pattern (see
``integrations/external_actions.py``):

- ``pending_actions[session_id]`` — :class:`ExternalAction` list emitted by
  the orchestrator (openEMS escalations, NEC2 antenna runs, live limit
  lookups, drawio diagrams). Drained by Claude via
  ``pcb_suggest_next_actions``.
- ``external_results[session_id]`` — :class:`ExternalResult` map keyed by
  ``action_id``, populated as Claude feeds sibling-MCP results back through
  ``pcb_attach_external_result``.
"""

from __future__ import annotations

import logging
import time
import uuid

from .integrations.external_actions import ExternalAction, ExternalResult
from .models.pcb_data import PCBDesignData

logger = logging.getLogger(__name__)

MAX_SESSIONS = 50
SESSION_TTL_S = 3600


class DesignSessionManager:
    """Manages parsed PCB design sessions in memory."""

    def __init__(self) -> None:
        self._sessions: dict[str, PCBDesignData] = {}
        self._timestamps: dict[str, float] = {}
        self._pending_actions: dict[str, list[ExternalAction]] = {}
        self._external_results: dict[str, dict[str, ExternalResult]] = {}

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
            self._pending_actions.pop(session_id, None)
            self._external_results.pop(session_id, None)
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

    # =================================================================
    # External-action queue (Phase 3 cross-MCP intent pattern)
    # =================================================================

    def enqueue_actions(self, session_id: str, actions: list[ExternalAction]) -> int:
        """Append *actions* to the session's pending-actions queue.

        Returns the number of actions actually appended after deduping
        against actions already present in the queue (same action_id is
        treated as a no-op; same params signature is treated as a no-op).
        """
        if session_id not in self._sessions:
            raise KeyError(f"unknown session_id: {session_id}")
        bucket = self._pending_actions.setdefault(session_id, [])
        seen_ids = {a.action_id for a in bucket}
        from .integrations.external_actions import _params_signature
        seen_sigs = {(a.mcp_server, a.tool_name, _params_signature(a.params)) for a in bucket}
        added = 0
        for a in actions:
            if a.action_id in seen_ids:
                continue
            sig = (a.mcp_server, a.tool_name, _params_signature(a.params))
            if sig in seen_sigs:
                continue
            bucket.append(a)
            seen_ids.add(a.action_id)
            seen_sigs.add(sig)
            added += 1
        return added

    def get_pending_actions(self, session_id: str) -> list[ExternalAction]:
        """Return a *copy* of the pending-actions queue for inspection."""
        return list(self._pending_actions.get(session_id, []))

    def find_action(self, session_id: str, action_id: str) -> ExternalAction | None:
        """Return the action with *action_id* in *session_id*'s queue, or None."""
        for a in self._pending_actions.get(session_id, []):
            if a.action_id == action_id:
                return a
        return None

    def record_result(self, session_id: str, result: ExternalResult) -> bool:
        """Store an external-MCP result, mark the matching action completed.

        Returns ``True`` if the action was found and marked, ``False`` if
        the action_id is unknown (out-of-band result — still stored for
        diagnostic purposes).
        """
        if session_id not in self._sessions:
            raise KeyError(f"unknown session_id: {session_id}")
        bucket = self._external_results.setdefault(session_id, {})
        bucket[result.action_id] = result
        action = self.find_action(session_id, result.action_id)
        if action is None:
            return False
        action.status = "completed" if result.succeeded else "failed"
        return True

    def get_external_results(self, session_id: str) -> dict[str, ExternalResult]:
        """Return a *copy* of the external-results map for *session_id*."""
        return dict(self._external_results.get(session_id, {}))

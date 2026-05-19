"""Cross-MCP action queue — the data types the orchestrator emits and the
helpers that manage them.

The pcb-emcopilot Python process cannot invoke sibling MCP servers directly
(only Claude can). The pattern used instead is an **intent queue**:

1. The orchestrator inspects each :class:`ReviewFinding` and, when escalation
   thresholds are met (severity >= HIGH or confidence < 0.7), enqueues an
   :class:`ExternalAction` describing the sibling-MCP call Claude should make
   (e.g. ``mcp__openems__openems_create_microstrip`` with the trace geometry).
2. Claude reads the queue via ``pcb_suggest_next_actions``, executes the
   sibling tool, and feeds the result back through ``pcb_attach_external_result``.
3. The orchestrator's re-correlation step updates the linked finding's
   ``verified`` / ``confidence`` / ``source`` based on the simulated result.

This module is pure data — no I/O, no globals beyond the small priority
constants below — so it composes cleanly with the existing
``OpenEMSBridge`` and the future regulations/nec2/drawio bridges.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

# Priority values. Lower number = run sooner. Anything <= PRIORITY_CRITICAL
# blocks ``pcb_generate_design_review_report`` unless ``force=True``.
PRIORITY_CRITICAL = 1
PRIORITY_HIGH = 2
PRIORITY_NORMAL = 3
PRIORITY_LOW = 4
PRIORITY_NICE_TO_HAVE = 5


# Statuses recorded on each action as it moves through the queue.
STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

_VALID_STATUSES: frozenset[str] = frozenset(
    {STATUS_PENDING, STATUS_COMPLETED, STATUS_FAILED, STATUS_SKIPPED}
)


@dataclass
class ExternalAction:
    """A single suggested sibling-MCP call.

    The orchestrator emits these; Claude reads + executes them; the bridge
    layer maps results back onto the originating findings.
    """

    mcp_server: str          # e.g. "openems", "nec2-antenna", "emc-regulations", "drawio-engineering"
    tool_name: str           # e.g. "openems_create_microstrip"
    params: dict[str, Any]
    rationale: str
    linked_finding_ids: list[str] = field(default_factory=list)
    priority: int = PRIORITY_NORMAL
    status: str = STATUS_PENDING
    action_id: str = ""

    def __post_init__(self) -> None:
        if not self.action_id:
            self.action_id = uuid.uuid4().hex[:8]
        if self.status not in _VALID_STATUSES:
            raise ValueError(f"invalid action status {self.status!r}")

    def fully_qualified_tool_name(self) -> str:
        """Return the canonical ``mcp__<server>__<tool>`` form Claude calls."""
        return f"mcp__{self.mcp_server}__{self.tool_name}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "mcp_server": self.mcp_server,
            "tool_name": self.tool_name,
            "fully_qualified_tool_name": self.fully_qualified_tool_name(),
            "params": dict(self.params),
            "rationale": self.rationale,
            "linked_finding_ids": list(self.linked_finding_ids),
            "priority": self.priority,
            "status": self.status,
        }


@dataclass
class ExternalResult:
    """The result Claude feeds back after running a suggested action."""

    action_id: str
    result: dict[str, Any]
    error: str | None = None
    received_at: float = 0.0

    @property
    def succeeded(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "result": dict(self.result),
            "error": self.error,
            "received_at": self.received_at,
            "succeeded": self.succeeded,
        }


def dedupe_actions(actions: list[ExternalAction]) -> list[ExternalAction]:
    """Remove duplicate actions targeting the same tool+params signature.

    Two actions are considered duplicates if they have the same
    ``(mcp_server, tool_name, params_tuple)``. The first occurrence wins;
    linked finding ids from later duplicates are merged into the survivor
    so cross-domain correlations aren't lost.
    """
    seen: dict[tuple, ExternalAction] = {}
    out: list[ExternalAction] = []
    for a in actions:
        # Make params hashable by tuple-ifying its sorted items recursively.
        sig = (a.mcp_server, a.tool_name, _params_signature(a.params))
        if sig in seen:
            survivor = seen[sig]
            for fid in a.linked_finding_ids:
                if fid not in survivor.linked_finding_ids:
                    survivor.linked_finding_ids.append(fid)
            # Keep the highest-priority (lowest number) of the duplicates.
            if a.priority < survivor.priority:
                survivor.priority = a.priority
            continue
        seen[sig] = a
        out.append(a)
    return out


def _params_signature(params: dict[str, Any]) -> tuple:
    """Make a dict hashable for dedupe by recursively tuple-ifying it."""
    items: list[tuple[str, Any]] = []
    for k in sorted(params.keys()):
        v = params[k]
        if isinstance(v, dict):
            items.append((k, _params_signature(v)))
        elif isinstance(v, list):
            items.append((k, tuple(v)))
        else:
            items.append((k, v))
    return tuple(items)


def sort_by_priority(actions: list[ExternalAction]) -> list[ExternalAction]:
    """Return a new list sorted by priority ascending (1 = run first)."""
    return sorted(actions, key=lambda a: (a.priority, a.action_id))


def filter_pending(actions: list[ExternalAction]) -> list[ExternalAction]:
    """Return only actions still awaiting completion."""
    return [a for a in actions if a.status == STATUS_PENDING]


def has_pending_critical(actions: list[ExternalAction]) -> bool:
    """True if any pending action has priority <= PRIORITY_CRITICAL."""
    return any(
        a.status == STATUS_PENDING and a.priority <= PRIORITY_CRITICAL
        for a in actions
    )

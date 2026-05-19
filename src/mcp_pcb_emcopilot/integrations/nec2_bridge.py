"""Bridge to the ``mcp__nec2-antenna__*`` sibling MCP.

Triggered when an intentional radiator (or unintentional antenna with strong
resonance evidence) is detected at frequency ≥ NEC2_MIN_FREQ_MHZ. The bridge
emits an ExternalAction pair Claude executes:

1. ``mcp__nec2-antenna__nec2_create_<type>`` — build the wire model from
   the geometry the bridge inferred (trace length, frequency, ground-plane
   extent).
2. ``mcp__nec2-antenna__nec2_simulate`` — run the model and return VSWR,
   gain, pattern data.

Result ingestion lives in ``server.pcb_attach_external_result``; this
module is the request-side only.
"""

from __future__ import annotations

from typing import Any

from .external_actions import (
    PRIORITY_HIGH,
    ExternalAction,
)

NEC2_MIN_FREQ_MHZ = 30.0


# Antenna-type hints we map to ``nec2_create_<type>`` tools. Order matters:
# the first match wins. The "fallback" entry lets us still emit a useful
# intent when the geometry doesn't fit a known template.
_ANTENNA_TYPE_RULES: list[tuple[str, str]] = [
    ("dipole",      "nec2_create_dipole"),
    ("monopole",    "nec2_create_vertical"),
    ("vertical",    "nec2_create_vertical"),
    ("inverted_v",  "nec2_create_inverted_v"),
    ("inverted-v",  "nec2_create_inverted_v"),
    ("yagi",        "nec2_create_yagi"),
    ("loop",        "nec2_create_loop"),
    ("ifa",         "nec2_create_dipole"),   # closest NEC2 primitive
    ("pifa",        "nec2_create_dipole"),
    ("chip_antenna", "nec2_create_dipole"),  # placeholder — usually pre-validated
]


def infer_antenna_type(title: str, description: str, structure_hint: str | None = None) -> str:
    """Best-effort antenna-type inference from finding text.

    Returns the matched substring (e.g. ``"dipole"``) for use with
    :func:`build_antenna_intent`. Defaults to ``"dipole"`` when nothing
    matches — that's NEC2's most general primitive.
    """
    haystack = " ".join([title, description, structure_hint or ""]).lower()
    for needle, _tool in _ANTENNA_TYPE_RULES:
        if needle in haystack:
            return needle
    return "dipole"


def _tool_for_antenna_type(antenna_type: str) -> str:
    for needle, tool in _ANTENNA_TYPE_RULES:
        if needle == antenna_type.lower():
            return tool
    return "nec2_create_dipole"


def build_antenna_intent(
    finding_id: str,
    title: str,
    description: str,
    trace_length_mm: float,
    frequency_mhz: float,
    antenna_type: str | None = None,
    ground_plane_extent_mm: float | None = None,
    structure_hint: str | None = None,
    priority: int = PRIORITY_HIGH,
) -> ExternalAction | None:
    """Build a NEC2 ``nec2_create_<type>`` intent for a single finding.

    Returns ``None`` when frequency is below the minimum (no point modelling
    sub-30 MHz traces with full-wave NEC2; near-field analytical heuristics
    are more useful at those bands).
    """
    if frequency_mhz < NEC2_MIN_FREQ_MHZ:
        return None
    if trace_length_mm <= 0:
        return None

    chosen_type = antenna_type or infer_antenna_type(title, description, structure_hint)
    tool = _tool_for_antenna_type(chosen_type)
    params: dict[str, Any] = {
        "frequency_mhz": frequency_mhz,
        "length_mm": trace_length_mm,
        "antenna_type_hint": chosen_type,
    }
    if ground_plane_extent_mm is not None:
        params["ground_plane_extent_mm"] = ground_plane_extent_mm
    rationale = (
        f"Validate {chosen_type} antenna behaviour for finding {finding_id} "
        f"({title}) at {frequency_mhz:.1f} MHz via NEC2. Returns simulated "
        f"VSWR, gain, pattern."
    )
    return ExternalAction(
        mcp_server="nec2-antenna",
        tool_name=tool,
        params=params,
        rationale=rationale,
        linked_finding_ids=[finding_id],
        priority=priority,
    )


def build_simulate_followup(
    create_action: ExternalAction,
    priority: int = PRIORITY_HIGH,
) -> ExternalAction:
    """Build the paired ``nec2_simulate`` action for a ``nec2_create_*`` action.

    Convenience for callers that want both halves of the create→simulate
    pair in the queue. Claude is expected to execute ``simulate`` only after
    the matching ``create`` has completed.
    """
    return ExternalAction(
        mcp_server="nec2-antenna",
        tool_name="nec2_simulate",
        params={"created_by_action_id": create_action.action_id},
        rationale=(
            f"Run NEC2 method-of-moments simulation for the antenna model "
            f"created by {create_action.action_id}."
        ),
        linked_finding_ids=list(create_action.linked_finding_ids),
        priority=priority,
    )


def is_antenna_finding(domain: str, signal_name: str | None = None,
                       title: str = "", description: str = "") -> bool:
    """Coarse predicate: should this finding even be considered for NEC2?"""
    if domain in {"antenna", "rf_si"}:
        return True
    keywords = ("antenna", "radiator", "patch", "dipole", "monopole",
                "yagi", "ifa", "loop")
    haystack = " ".join([signal_name or "", title, description]).lower()
    return any(k in haystack for k in keywords)

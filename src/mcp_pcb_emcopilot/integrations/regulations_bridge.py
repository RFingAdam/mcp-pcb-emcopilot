"""Bridge to the ``mcp__emc-regulations__*`` sibling MCP.

Two flavours of work happen here:

1. *Intent emission* — given a (standard, class, freq) tuple the orchestrator
   wants verified against live regulatory data, build an :class:`ExternalAction`
   that Claude will execute. The orchestrator queues these on the session via
   :meth:`DesignSessionManager.enqueue_actions`.
2. *Result ingestion* — given the raw payload Claude attached with
   ``pcb_attach_external_result``, parse it into a :class:`LimitPoint` and
   record it in :mod:`analyzers.emc.limits_provider`'s runtime cache so the
   next ``get_limit`` call returns the live value.

The mapping from internal standard ids to ``emc-regulations`` MCP tools lives
here too — single source of truth.
"""

from __future__ import annotations

from typing import Any

from ..analyzers.emc.limits_provider import LimitPoint, cache_live_result
from .external_actions import (
    PRIORITY_NORMAL,
    ExternalAction,
)

# =============================================================================
# Standard → emc-regulations tool mapping
# =============================================================================

_STD_TO_TOOL: dict[str, str] = {
    "CISPR_25": "cispr25_limit",
    "CISPR25": "cispr25_limit",
    "FCC_PART_15_B": "fcc_part15_limit",
    "FCC_PART_15_A": "fcc_part15_limit",
    "FCC_15B": "fcc_part15_limit",
    "FCC_15A": "fcc_part15_limit",
    "CISPR_32": "cispr_limit",
    "EN_55032": "cispr_limit",
    "ISO_11452_2": "iso11452_levels",
    "ISO_11452_4": "iso11452_levels",
    "ISO_11452_5": "iso11452_levels",
    "ISO_7637_2": "iso7637_pulses",
    "ISO_16750_2": "iso16750_conditions",
    "IEC_60601_1_2": "medical_immunity_levels",
    "IEC_60601_1_2_ED_4_1": "medical_immunity_levels",
    "IEC_60601_1_2_ED_4_0": "medical_immunity_levels",
    "IEC_61000_4_2": "iec61000_test_levels",
    "IEC_61000_4_3": "iec61000_test_levels",
    "IEC_61000_4_4": "iec61000_test_levels",
    "IEC_61000_4_5": "iec61000_test_levels",
    "IEC_61000_4_6": "iec61000_test_levels",
    "IEC_61000_4_8": "iec61000_test_levels",
    "IEC_61000_4_11": "iec61000_test_levels",
    "FCC_47_CFR_15C": "fcc_part15_limit",
    "FCC_47_CFR_15B": "fcc_part15_limit",
}

# Units returned by each tool. Used when parsing results back into LimitPoint.
_TOOL_UNITS: dict[str, str] = {
    "cispr25_limit": "dBuV/m",
    "fcc_part15_limit": "dBuV/m",
    "cispr_limit": "dBuV/m",
    "iso11452_levels": "V/m",
    "iso7637_pulses": "V",
    "iso16750_conditions": "V",
    "medical_immunity_levels": "V/m",
    "iec61000_test_levels": "V/m",
}


def tool_name_for_standard(standard: str) -> str:
    """Return the emc-regulations tool that resolves *standard*."""
    return _STD_TO_TOOL.get(standard.upper(), "source_search")


# =============================================================================
# Intent emission
# =============================================================================

def build_limit_lookup_intent(
    standard: str,
    class_or_level: str,
    frequency_mhz: float,
    detector: str = "QP",
    linked_finding_ids: list[str] | None = None,
    priority: int = PRIORITY_NORMAL,
) -> ExternalAction:
    """Build an ExternalAction that asks Claude to call mcp__emc-regulations__*.

    The resulting action is *not* enqueued — the caller (orchestrator) decides
    when to attach it to a session.
    """
    std_upper = standard.upper()
    tool = tool_name_for_standard(std_upper)
    params: dict[str, Any] = {
        "standard": std_upper,
        "class_or_level": str(class_or_level),
        "frequency_mhz": float(frequency_mhz),
        "detector": detector.upper(),
    }
    rationale = (
        f"Verify {std_upper} class {class_or_level} limit at "
        f"{frequency_mhz:.3f} MHz against the live emc-regulations dataset "
        f"(detector={detector.upper()})."
    )
    return ExternalAction(
        mcp_server="emc-regulations",
        tool_name=tool,
        params=params,
        rationale=rationale,
        linked_finding_ids=list(linked_finding_ids or []),
        priority=priority,
    )


def build_intents_for_standards(
    standards: list[str],
    classes_by_standard: dict[str, str] | None = None,
    sample_frequencies_mhz: tuple[float, ...] = (0.5, 30.0, 150.0, 1000.0),
    linked_finding_ids: list[str] | None = None,
    priority: int = PRIORITY_NORMAL,
) -> list[ExternalAction]:
    """Build one lookup intent per (standard, sample frequency) pair.

    Used by the orchestrator's ``_emit_next_actions`` to warm the runtime
    cache before report generation. ``classes_by_standard`` lets the caller
    pin a specific class (e.g. ``{"CISPR_25": "3"}``); falls back to the
    standard's typical class (``B`` for FCC/CISPR-32, ``3`` for CISPR-25,
    ``3`` for ISO-11452, ``4.1`` for IEC-60601).
    """
    out: list[ExternalAction] = []
    classes_by_standard = classes_by_standard or {}
    for std in standards:
        std_u = std.upper()
        klass = classes_by_standard.get(std_u) or _default_class_for(std_u)
        for f in sample_frequencies_mhz:
            out.append(build_limit_lookup_intent(
                standard=std_u,
                class_or_level=klass,
                frequency_mhz=f,
                detector="QP",
                linked_finding_ids=linked_finding_ids,
                priority=priority,
            ))
    return out


def _default_class_for(standard_upper: str) -> str:
    if standard_upper.startswith("CISPR_25"):
        return "3"
    if standard_upper.startswith("ISO_11452"):
        return "3"
    if standard_upper.startswith("IEC_60601_1_2"):
        return "4.1"
    if standard_upper.startswith("IEC_61000_4"):
        return "3"
    return "B"


# =============================================================================
# Result ingestion
# =============================================================================

def apply_limit_result(
    action: ExternalAction,
    raw_result: dict[str, Any],
) -> LimitPoint | None:
    """Parse a sibling-MCP response into a LimitPoint + cache it.

    ``raw_result`` shape is what the user's emc-regulations MCP returns —
    we tolerate a few common conventions:

    - ``{"limit_dbuv_per_m": 32.0, "band_min_mhz": 0.15, "band_max_mhz": 0.3}``
    - ``{"value": 32.0, "unit": "dBuV/m"}``
    - ``{"limit": 32.0}``

    Returns the LimitPoint that was cached, or ``None`` if the payload is
    unrecognisable.
    """
    if not isinstance(raw_result, dict):
        return None

    value = (
        raw_result.get("limit_value")
        or raw_result.get("limit_dbuv_per_m")
        or raw_result.get("limit_dbuv")
        or raw_result.get("limit_vm")
        or raw_result.get("value")
        or raw_result.get("limit")
    )
    if value is None:
        return None
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return None

    standard = str(action.params.get("standard", "UNKNOWN")).upper()
    klass = str(action.params.get("class_or_level", ""))
    freq = float(action.params.get("frequency_mhz", 0.0))
    detector = str(action.params.get("detector", "QP")).upper()
    unit = raw_result.get("unit") or _TOOL_UNITS.get(action.tool_name, "dBuV/m")
    band_min = float(raw_result.get("band_min_mhz", freq))
    band_max = float(raw_result.get("band_max_mhz", freq))
    notes = str(raw_result.get("source") or raw_result.get("notes") or "live emc-regulations lookup")

    point = LimitPoint(
        standard=standard,
        class_or_level=klass,
        frequency_mhz=freq,
        detector=detector,
        limit_value=value_f,
        limit_unit=str(unit),
        band_min_mhz=band_min,
        band_max_mhz=band_max,
        source="live_regs",
        notes=notes,
    )
    cache_live_result(point)
    return point

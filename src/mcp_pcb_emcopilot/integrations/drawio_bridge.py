"""Bridge to the ``mcp__drawio-engineering__*`` sibling MCP.

Emitted at *report time* (Pass 7 of the playbook). Builds up to four diagram
intents that the report builder later embeds, replacing the
``docs/diagram_*.svg`` placeholders that ship with the framework
documentation:

1. ``create_pcb_stackup`` — always, given the parsed stackup.
2. ``create_rf_block_diagram`` — only if RF nets/interfaces detected.
3. ``create_emc_test_setup`` — one per market in ``target_markets``.
4. ``markup_schematic`` — only when a schematic file was parsed this session.

This is a pure intent-emission module; result ingestion stores the returned
SVG path on the session via ``pcb_attach_external_result`` and the report
builder reads it out.
"""

from __future__ import annotations

from typing import Any

from .external_actions import (
    PRIORITY_NICE_TO_HAVE,
    PRIORITY_NORMAL,
    ExternalAction,
)

# =============================================================================
# Diagram-intent builders
# =============================================================================


def build_stackup_intent(
    layers: list[dict[str, Any]],
    board_thickness_mm: float | None = None,
    priority: int = PRIORITY_NORMAL,
) -> ExternalAction:
    """Always-on stackup diagram."""
    params: dict[str, Any] = {
        "layers": layers,
        "include_dielectric": True,
        "include_copper_weight": True,
    }
    if board_thickness_mm is not None:
        params["board_thickness_mm"] = board_thickness_mm
    return ExternalAction(
        mcp_server="drawio-engineering",
        tool_name="create_pcb_stackup",
        params=params,
        rationale=(
            "Render the layer stackup as a drawio cross-section diagram for "
            "embedding in the design-review report."
        ),
        priority=priority,
    )


def build_rf_chain_intent(
    rf_blocks: list[dict[str, Any]] | None = None,
    frequencies_mhz: list[float] | None = None,
    priority: int = PRIORITY_NICE_TO_HAVE,
) -> ExternalAction:
    """RF block diagram. ``rf_blocks`` is a free-form list the bridge passes
    through; if absent, the diagram tool falls back to a template chain."""
    params: dict[str, Any] = {
        "blocks": rf_blocks or [],
        "frequencies_mhz": frequencies_mhz or [],
    }
    return ExternalAction(
        mcp_server="drawio-engineering",
        tool_name="create_rf_block_diagram",
        params=params,
        rationale=(
            "Render the RF signal chain (LNA / mixer / filter / antenna) as a "
            "drawio block diagram for the RF section of the report."
        ),
        priority=priority,
    )


_MARKET_TO_STANDARD: dict[str, str] = {
    "automotive": "CISPR_25",
    "medical": "IEC_60601_1_2",
    "wireless": "FCC_PART_15_C",
    "commercial": "CISPR_32",
    "industrial": "EN_61326",
}


def build_emc_test_setup_intent(
    market: str,
    standard: str | None = None,
    priority: int = PRIORITY_NICE_TO_HAVE,
) -> ExternalAction:
    """One EMC test setup diagram per market.

    Uses the canonical standard for that market when ``standard`` is not
    provided (e.g. ``"automotive" → "CISPR_25"``).
    """
    chosen_standard = standard or _MARKET_TO_STANDARD.get(market.lower(), "CISPR_32")
    return ExternalAction(
        mcp_server="drawio-engineering",
        tool_name="create_emc_test_setup",
        params={
            "market": market,
            "standard": chosen_standard,
        },
        rationale=(
            f"Render the {chosen_standard} compliance test setup diagram for "
            f"the {market} EMC section of the report."
        ),
        priority=priority,
    )


def build_schematic_markup_intent(
    schematic_path: str,
    annotations: list[dict[str, Any]] | None = None,
    priority: int = PRIORITY_NICE_TO_HAVE,
) -> ExternalAction:
    """Markup the schematic with finding callouts."""
    return ExternalAction(
        mcp_server="drawio-engineering",
        tool_name="markup_schematic",
        params={
            "schematic_path": schematic_path,
            "annotations": annotations or [],
        },
        rationale=(
            "Overlay the design-review findings onto the schematic as a "
            "drawio markup layer for the report's schematic-overview section."
        ),
        priority=priority,
    )


# =============================================================================
# Convenience: build the whole set at once for the orchestrator
# =============================================================================


def build_diagram_intents(
    stackup_layers: list[dict[str, Any]],
    board_thickness_mm: float | None = None,
    detected_interfaces: list[str] | None = None,
    target_markets: list[str] | None = None,
    schematic_path: str | None = None,
    rf_frequencies_mhz: list[float] | None = None,
) -> list[ExternalAction]:
    """Emit every applicable diagram intent for the current session.

    Returned actions are ordered: stackup first, RF chain (if applicable),
    one EMC test setup per market, schematic markup last.
    """
    out: list[ExternalAction] = []
    if stackup_layers:
        out.append(build_stackup_intent(stackup_layers, board_thickness_mm))

    has_rf = any(
        (iface or "").lower() in {"rf", "ble", "wifi", "halow", "gnss", "lte", "nr"}
        or "rf" in (iface or "").lower()
        for iface in (detected_interfaces or [])
    )
    if has_rf or rf_frequencies_mhz:
        out.append(build_rf_chain_intent(frequencies_mhz=rf_frequencies_mhz))

    for market in target_markets or []:
        out.append(build_emc_test_setup_intent(market))

    if schematic_path:
        out.append(build_schematic_markup_intent(schematic_path))

    return out

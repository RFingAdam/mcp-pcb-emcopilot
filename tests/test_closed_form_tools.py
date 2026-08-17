"""Closed-form calculators must stay usable without a parsed design.

A large part of this server's value is tools that are pure math over explicit
arguments: impedance, cavity resonance, lambda/20 stitching spacing, antenna
length checks. They take no ``session_id`` and read no geometry, so they remain
trustworthy even when ingest has failed completely — which is exactly when an
engineer reaches for them.

That makes them the natural boundary for the insufficient-data work: as
analyzers gain preconditions, these tools must NOT acquire one. This test pins
that boundary so a well-intentioned "guard everything" change cannot quietly
make the hand-calculators depend on a parse.

Note ``pcb_analyze_ground_stitch`` is a naming trap: it dispatches to
``current_density.calculate_ground_stitch_spacing``, a closed form — it is not
the ground-island/plane-connectivity analyzer.

Deliberately absent from this list: ``pcb_analyze_grounding`` and
``pcb_analyze_decoupling``. They are currently session-independent, but not
because they are calculators — they fabricate a ground plane and decap
positions respectively. They are expected to gain an *optional* session_id, so
pinning them here would lock in the fabrication.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from test_all_tools_smoke import _default_for_schema

from mcp_pcb_emcopilot import server as srv

CLOSED_FORM_TOOLS = [
    "pcb_calc_via_stitching",
    "pcb_calc_plane_resonance",
    "pcb_analyze_cavity_resonance",
    "pcb_analyze_return_current",
    "pcb_analyze_return_current_density",
    "pcb_analyze_ground_stitch",
    "pcb_optimize_ground_stitching",
    "pcb_visualize_return_path",
    "pcb_analyze_slot_antenna",
    "pcb_analyze_trace_antenna",
    "pcb_analyze_common_mode",
    "pcb_analyze_cable_coupling",
    "pcb_analyze_clock_emi",
    "pcb_predict_compliance",
    "pcb_calc_pdn_impedance",
    "pcb_analyze_pdn",
]


def _registry():
    return {t.name: t for t in asyncio.run(srv.list_tools())}


def _required_args(tool) -> dict:
    """Build only the required args — deliberately no session_id."""
    schema = tool.input_schema or {}
    props = schema.get("properties", {})
    return {
        name: _default_for_schema(name, props.get(name, {}))
        for name in (schema.get("required") or [])
    }


@pytest.mark.parametrize("name", CLOSED_FORM_TOOLS)
def test_tool_is_registered(name):
    assert name in _registry()


@pytest.mark.parametrize("name", CLOSED_FORM_TOOLS)
def test_does_not_require_a_session(name):
    schema = _registry()[name].input_schema or {}
    assert "session_id" not in (schema.get("required") or []), (
        f"{name} now requires a session; closed-form calculators must remain "
        "usable when ingest has failed"
    )


@pytest.mark.parametrize("name", CLOSED_FORM_TOOLS)
def test_returns_a_result_with_no_session_at_all(name):
    tool = _registry()[name]
    result = srv._dispatch(name, _required_args(tool))
    assert result is not None
    blob = json.dumps(result, default=str)
    assert "INSUFFICIENT_DATA" not in blob, (
        f"{name} reported insufficient data despite being a closed-form "
        f"calculator over explicit arguments"
    )


def test_the_two_fabricating_tools_are_excluded_on_purpose():
    """Guard the guard: these must not drift into the protected list.

    pcb_analyze_grounding invents a ground plane at a hardcoded coverage
    percentage; pcb_analyze_decoupling invents decap positions. Both are
    session-independent today, but that is the defect, not the contract.
    """
    assert "pcb_analyze_grounding" not in CLOSED_FORM_TOOLS
    assert "pcb_analyze_decoupling" not in CLOSED_FORM_TOOLS


def test_known_physics_still_comes_out_right():
    """One real numeric anchor, so the parametrized checks above are not the
    only thing between a refactor and silently wrong arithmetic.

    Rectangular plane-pair cavity modes for a 40 x 25 mm FR-4 pair, from the
    closed form ``f = c / (2 * d * sqrt(er))`` with ``sqrt(4.3) = 2.07364``:

        40 mm edge:  3e8 / (2 * 0.040 * 2.07364) = 1808 MHz
        25 mm edge:  3e8 / (2 * 0.025 * 2.07364) = 2893 MHz

    Both are well above any board-level clock harmonic of interest, which is
    the practical point of the calculation: it tells you whether a suspect
    emission frequency *could* be a cavity resonance before you go looking for
    one.
    """
    res = srv._dispatch("pcb_calc_plane_resonance", {
        "plane_width_mm": 40.0,
        "plane_length_mm": 25.0,
        "dielectric_constant": 4.3,
        "dielectric_height_mm": 0.2,
    })
    by_mode = {r["mode"]: r["frequency_mhz"] for r in res["resonances"]}
    assert by_mode["TM01"] == pytest.approx(1808, abs=2), by_mode
    assert by_mode["TM10"] == pytest.approx(2893, abs=3), by_mode
    # Lowest mode must be the one set by the longer edge.
    assert min(by_mode.values()) == by_mode["TM01"]

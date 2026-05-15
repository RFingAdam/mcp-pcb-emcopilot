"""Tests for integrations/nec2_bridge — antenna intent emission."""

from __future__ import annotations

from mcp_pcb_emcopilot.integrations.nec2_bridge import (
    NEC2_MIN_FREQ_MHZ,
    build_antenna_intent,
    build_simulate_followup,
    infer_antenna_type,
    is_antenna_finding,
)

# --- Type inference ---------------------------------------------------------

def test_infer_dipole():
    assert infer_antenna_type("Dipole resonance at 2.4 GHz", "trace edge", None) == "dipole"


def test_infer_monopole_via_vertical_keyword():
    assert infer_antenna_type("Vertical monopole exposure", "stub", None) == "monopole"


def test_infer_yagi():
    assert infer_antenna_type("Yagi-Uda parasitic array", "", None) == "yagi"


def test_infer_default_to_dipole():
    assert infer_antenna_type("unknown structure", "no clue", None) == "dipole"


# --- is_antenna_finding ----------------------------------------------------

def test_antenna_finding_by_domain():
    assert is_antenna_finding("antenna") is True
    assert is_antenna_finding("rf_si") is True


def test_antenna_finding_by_keyword():
    assert is_antenna_finding("emc", title="Trace acts as monopole radiator") is True


def test_non_antenna_finding():
    assert is_antenna_finding("thermal", title="Junction temp", description="hot") is False


# --- build_antenna_intent --------------------------------------------------

def test_build_antenna_intent_emits_dipole_action():
    action = build_antenna_intent(
        finding_id="ANT-001",
        title="Half-wave resonance on test trace",
        description="trace_len = 31 mm at 2400 MHz",
        trace_length_mm=31.0,
        frequency_mhz=2400.0,
    )
    assert action is not None
    assert action.mcp_server == "nec2-antenna"
    assert action.tool_name == "nec2_create_dipole"
    assert action.params["frequency_mhz"] == 2400.0
    assert action.params["length_mm"] == 31.0
    assert "ANT-001" in action.linked_finding_ids


def test_build_antenna_intent_returns_none_below_min_freq():
    a = build_antenna_intent(
        finding_id="X",
        title="t",
        description="d",
        trace_length_mm=10.0,
        frequency_mhz=NEC2_MIN_FREQ_MHZ - 1,
    )
    assert a is None


def test_build_antenna_intent_returns_none_for_zero_length():
    a = build_antenna_intent(
        finding_id="X",
        title="t",
        description="d",
        trace_length_mm=0.0,
        frequency_mhz=2400.0,
    )
    assert a is None


def test_build_antenna_intent_yagi_routes_to_yagi_tool():
    a = build_antenna_intent(
        finding_id="X",
        title="yagi parasitic element",
        description="",
        trace_length_mm=20.0,
        frequency_mhz=400.0,
    )
    assert a is not None and a.tool_name == "nec2_create_yagi"


def test_build_simulate_followup_links_to_create():
    create = build_antenna_intent(
        finding_id="X",
        title="dipole",
        description="",
        trace_length_mm=20.0,
        frequency_mhz=400.0,
    )
    followup = build_simulate_followup(create)
    assert followup.tool_name == "nec2_simulate"
    assert followup.params["created_by_action_id"] == create.action_id
    assert followup.linked_finding_ids == create.linked_finding_ids

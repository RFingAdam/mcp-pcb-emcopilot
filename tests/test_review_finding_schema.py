"""Tests for the Phase 3 ReviewFinding schema upgrade — confidence,
verified, source, finding_id, linked_actions."""

from __future__ import annotations

from mcp_pcb_emcopilot.orchestrator import ReviewFinding, reset_finding_id_counters


def setup_function():
    """Reset finding-id counters between tests so ids are predictable."""
    reset_finding_id_counters()


# --- Defaults ----------------------------------------------------------------

def test_finding_defaults_for_new_fields():
    f = ReviewFinding(domain="emc", severity="high", title="t", description="d")
    assert f.confidence == 0.8
    assert f.verified is False
    assert f.source == "analytical"
    assert f.linked_actions == []


def test_finding_id_auto_generated():
    f = ReviewFinding(domain="emc", severity="high", title="t", description="d")
    # EMC is in _DOMAIN_PREFIXES — yields "EMC"
    assert f.finding_id == "EMC-001"


def test_finding_id_counter_continues():
    a = ReviewFinding(domain="emc", severity="high", title="t1", description="d")
    b = ReviewFinding(domain="emc", severity="warning", title="t2", description="d")
    c = ReviewFinding(domain="signal_integrity", severity="high", title="t3", description="d")
    assert a.finding_id == "EMC-001"
    assert b.finding_id == "EMC-002"
    # signal_integrity maps to "SI" via _DOMAIN_PREFIXES or "SIG" via fallback
    assert c.finding_id.endswith("-001")


def test_finding_id_letters_only_fallback():
    f = ReviewFinding(domain="em_risk", severity="info", title="t", description="d")
    # "em_risk" not in _DOMAIN_PREFIXES → letters-only first 3 uppercased = "EMR"
    assert f.finding_id == "EMR-001"


def test_finding_id_gen_fallback_for_letterless_domain():
    f = ReviewFinding(domain="___", severity="info", title="t", description="d")
    assert f.finding_id == "GEN-001"


def test_finding_id_respects_caller_supplied_value():
    f = ReviewFinding(
        domain="emc", severity="high", title="t", description="d",
        finding_id="CUSTOM-042",
    )
    assert f.finding_id == "CUSTOM-042"


# --- to_dict serialisation ---------------------------------------------------

def test_to_dict_includes_new_fields():
    f = ReviewFinding(
        domain="emc", severity="high", title="SMPS harmonic exceeds limit",
        description="6 MHz harmonic 4 dB over CISPR-25 Class 3 AM band",
        confidence=0.65,
    )
    d = f.to_dict()
    assert d["finding_id"] == "EMC-001"
    assert d["confidence"] == 0.65
    assert d["verified"] is False
    assert d["source"] == "analytical"
    assert "linked_actions" not in d  # only included when non-empty


def test_to_dict_includes_linked_actions_when_present():
    f = ReviewFinding(
        domain="signal_integrity", severity="high", title="t", description="d",
        linked_actions=["a1b2c3d4", "deadbeef"],
    )
    d = f.to_dict()
    assert d["linked_actions"] == ["a1b2c3d4", "deadbeef"]


def test_to_dict_confidence_rounded_to_3_decimals():
    f = ReviewFinding(
        domain="emc", severity="high", title="t", description="d",
        confidence=0.123456789,
    )
    assert f.to_dict()["confidence"] == 0.123

"""Tests for standards/preflight — validate_review_complete gate."""

from __future__ import annotations

from mcp_pcb_emcopilot.standards.preflight import (
    ValidationGate,
    coverage_summary,
    validate_review_complete,
)


class _Design:
    """Stub PCBDesignData — only review_context / review_results used."""
    def __init__(self, review_context: dict | None = None,
                 review_results: dict | None = None) -> None:
        self.review_context = review_context or {}
        self.review_results = review_results or {}


# --- Required-question coverage --------------------------------------------

def test_gate_refuses_without_market_or_standards():
    gate = validate_review_complete(_Design())
    assert gate.ready is False
    assert gate.missing_standard_selection is True


def test_gate_passes_when_core_questions_answered_and_standards_set():
    design = _Design({
        "playbook": {"declared_market": "commercial"},
        "interactive_answers": {
            "operating_environment": "consumer",
            "fab_stackup_spec": "no_use_extracted",
            "cispr32_class": "B",
            "target_regions": ["US", "EU"],
        },
        "target_standards": ["CISPR_32", "FCC_PART_15_B"],
    })
    gate = validate_review_complete(design)
    assert gate.ready is True
    assert gate.missing_required_questions == []
    assert gate.missing_standard_selection is False


def test_gate_lists_missing_market_specific_questions():
    design = _Design({
        "playbook": {"declared_market": "automotive"},
        "interactive_answers": {
            "operating_environment": "automotive",
            "fab_stackup_spec": "no_use_extracted",
        },
        "target_standards": ["CISPR_25"],
    })
    gate = validate_review_complete(design)
    assert gate.ready is False
    # Automotive required questions
    assert "vehicle_class" in gate.missing_required_questions
    assert "cispr25_class" in gate.missing_required_questions
    assert "bus_voltage" in gate.missing_required_questions


def test_gate_marks_stub_standards_as_incomplete():
    design = _Design({
        "playbook": {"declared_market": "automotive"},
        "interactive_answers": {
            "operating_environment": "automotive",
            "fab_stackup_spec": "no_use_extracted",
            "vehicle_class": "passenger",
            "cispr25_class": 3,
            "bus_voltage": "12V",
        },
        "target_standards": ["CISPR_25", "ISO_7637_2"],
    })
    gate = validate_review_complete(design)
    assert gate.ready is True  # required questions answered
    assert "ISO_7637_2" in gate.incomplete_standards  # stub-coverage standard surfaces


def test_gate_notes_active_markets():
    design = _Design({
        "playbook": {"declared_market": "wireless"},
        "interactive_answers": {
            "operating_environment": "consumer",
            "fab_stackup_spec": "no_use_extracted",
            "intentional_radiator": True,
            "fcc_part": "15C",
        },
        "target_standards": ["FCC_47_CFR_15C"],
    })
    gate = validate_review_complete(design)
    assert any("wireless" in n.lower() for n in gate.notes)


def test_validation_gate_to_dict_roundtrip():
    gate = ValidationGate(
        ready=False,
        missing_required_questions=["vehicle_class"],
        missing_standard_selection=True,
        incomplete_standards=["ISO_7637_2"],
        notes=["test note"],
    )
    d = gate.to_dict()
    assert d["ready"] is False
    assert d["missing_required_questions"] == ["vehicle_class"]
    assert d["incomplete_standards"] == ["ISO_7637_2"]


# --- coverage_summary helper ----------------------------------------------

def test_coverage_summary_pulls_from_review_context():
    design = _Design({
        "target_standards": ["CISPR_25", "FCC_PART_15_B"],
    })
    summary = coverage_summary(design, ran_analyzers=["automotive_emc"])
    assert summary["total_standards"] == 2
    # CISPR_25 partially covered (only automotive_emc ran);
    # FCC_PART_15_B no required analyzers ran either.
    assert any(c["standard"] == "CISPR_25" for c in summary["per_standard"])
    assert summary["ready_for_report"] is True  # neither is stub

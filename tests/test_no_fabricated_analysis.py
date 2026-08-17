"""An unanalysable design must yield no numbers at all.

The failure mode being closed: on an empty or unparsed design several analyzers
walked an empty collection, produced zero findings, and reported that as a
result. Zero is indistinguishable from "good" in every one of these metrics, so
the output read as a clean board:

    LOW EMI RISK: Overall score 0/100. Design appears likely to meet FCC_B limits.
    predicted_pass: True, margin_db: 100
    emc_score: 75.0, return_path_score: 47.5, ground_coverage_percent: 80.0

None of those were measurements. The grounding figures came from an invented
plane at a hardcoded 80% coverage on an assumed 100x100 mm board; the 100 dB
margin was returned *because* there was nothing to analyse.
"""
from __future__ import annotations

import json

import pytest

from mcp_pcb_emcopilot.analyzers.emc.emi_risk_scorer import EMIRiskScorer
from mcp_pcb_emcopilot.analyzers.emc.grounding import GroundingAnalyzer, GroundPlane
from mcp_pcb_emcopilot.analyzers.emc.return_path_analyzer import ReturnPathAnalyzer
from mcp_pcb_emcopilot.errors import InsufficientDataError
from mcp_pcb_emcopilot.models.pcb_data import PCBDesignData
from mcp_pcb_emcopilot.orchestrator import (
    _run_grounding_analysis,
    run_design_review,
)

# Numbers that must never appear for a design that could not be analysed.
# Matched against the serialised review, so a regression is caught wherever the
# value resurfaces rather than only at the call site that produced it.
FABRICATION_MARKERS = [
    "emc_score",
    "return_path_score",
    "ground_coverage_percent",
    "predicted_pass",
    "via_stitching_density",
]


def _empty() -> PCBDesignData:
    return PCBDesignData(source_file="empty.kicad_pcb")


# ---------------------------------------------------------------------------
# Analyzer-level preconditions
# ---------------------------------------------------------------------------

def test_return_path_analyzer_refuses_an_empty_design():
    with pytest.raises(InsufficientDataError) as exc:
        ReturnPathAnalyzer().analyze(_empty())
    assert exc.value.context["missing"] == ["nets"]


def test_emi_scorer_refuses_an_empty_design():
    with pytest.raises(InsufficientDataError) as exc:
        EMIRiskScorer().score(_empty())
    assert exc.value.context["missing"] == ["nets"]


def test_grounding_runner_refuses_when_no_ground_plane_is_visible():
    """Previously invented a plane named GND at 80% on a 100x100 mm board."""
    dr = _run_grounding_analysis(_empty())
    assert dr.status == "insufficient_data"
    assert "ground_zones" in dr.missing_inputs
    assert not dr.findings
    blob = json.dumps(dr.to_dict(), default=str)
    for marker in FABRICATION_MARKERS:
        assert marker not in blob, f"{marker} present for an unanalysable design"


def test_grounding_runner_requires_real_board_dimensions():
    """`board_width_mm or 100` used to substitute a phantom board."""
    d = _empty()
    d.zones = [type("Z", (), {"net_name": "GND", "layer": "In1.Cu", "area_mm2": 0.0})()]
    dr = _run_grounding_analysis(d)
    assert dr.status == "insufficient_data"
    assert "board_width_mm" in dr.missing_inputs


# ---------------------------------------------------------------------------
# Coverage must be "not measured", not an assumed constant.
# ---------------------------------------------------------------------------

def test_unknown_coverage_is_reported_as_not_determined():
    """A hardcoded 80.0 sat exactly on the <80 threshold, so the coverage check
    could never fire, while still subtracting fixed penalties from both scores.
    """
    res = GroundingAnalyzer().analyze_grounding(
        planes=[GroundPlane(layer_number=1, name="In1.Cu", coverage_percent=None,
                            width_mm=50.0, height_mm=30.0)],
        board_width_mm=50.0,
        board_height_mm=30.0,
        max_frequency_mhz=600.0,
        via_density=4.0,
    )
    assert res.ground_coverage_percent is None
    assert any("coverage" in nd for nd in res.not_determined)
    assert not any("Ground coverage" in i for i in res.issues)


def test_measured_coverage_is_still_scored_and_can_still_warn():
    """Regression guard: real coverage data must not be ignored."""
    res = GroundingAnalyzer().analyze_grounding(
        planes=[GroundPlane(layer_number=1, name="In1.Cu", coverage_percent=55.0,
                            width_mm=50.0, height_mm=30.0)],
        board_width_mm=50.0,
        board_height_mm=30.0,
        max_frequency_mhz=600.0,
        via_density=4.0,
    )
    assert res.ground_coverage_percent == 55.0
    assert any("Ground coverage" in i for i in res.issues)
    assert not res.not_determined


def test_unknown_coverage_does_not_penalise_the_scores():
    """The score must not be a function of an assumption we never made."""
    kw = dict(board_width_mm=50.0, board_height_mm=30.0,
              max_frequency_mhz=600.0, via_density=99.0)
    unknown = GroundingAnalyzer().analyze_grounding(
        planes=[GroundPlane(1, "In1.Cu", None, 50.0, 30.0)], **kw)
    perfect = GroundingAnalyzer().analyze_grounding(
        planes=[GroundPlane(1, "In1.Cu", 100.0, 50.0, 30.0)], **kw)
    assert unknown.return_path_score == perfect.return_path_score
    assert unknown.emc_score == perfect.emc_score


# ---------------------------------------------------------------------------
# Compliance prediction
# ---------------------------------------------------------------------------

def test_no_spectral_content_is_not_a_predicted_pass():
    scorer = EMIRiskScorer()
    compliance = scorer._assess_compliance([], "FCC_B")["FCC_B"]
    assert compliance["assessable"] is False
    assert compliance["predicted_pass"] is None
    assert compliance["margin_db"] is None
    assert "not a pass" in compliance["notes"].lower()


def test_executive_summary_does_not_claim_low_risk_with_nothing_scored():
    from mcp_pcb_emcopilot.analyzers.emc.emi_risk_scorer import EMIRiskResult

    scorer = EMIRiskScorer()
    summary = scorer._build_executive_summary(EMIRiskResult(), "FCC_B")
    assert "NOT ASSESSED" in summary
    assert "likely to meet" not in summary
    assert "LOW EMI RISK" not in summary


# ---------------------------------------------------------------------------
# End-to-end: the whole review on an unanalysable design.
# ---------------------------------------------------------------------------

def test_empty_design_review_is_inconclusive_with_no_invented_numbers():
    review = run_design_review(_empty(), "sess-empty")
    payload = review.to_dict()
    summary = payload["executive_summary"]

    assert summary["overall_status"] == "INCONCLUSIVE"
    assert summary["coverage_complete"] is False
    assert summary["verdict_reason"]

    blob = json.dumps(payload, default=str)
    for marker in FABRICATION_MARKERS:
        assert marker not in blob, (
            f"{marker} appears in a review of a design that could not be "
            f"analysed — verdict_reason={summary['verdict_reason']!r}"
        )


def test_empty_design_review_says_which_inputs_were_missing():
    review = run_design_review(_empty(), "sess-empty-2")
    payload = review.to_dict()
    insufficient = [
        d for d in payload["domain_results"]
        if d["status"] == "insufficient_data"
    ]
    assert insufficient, [d["status"] for d in payload["domain_results"]]
    assert any(d.get("missing_inputs") for d in insufficient)


def test_real_design_review_still_produces_an_assessment():
    """Regression guard: the preconditions must not disable normal reviews."""
    from pathlib import Path

    from mcp_pcb_emcopilot.parsers import parse_pcb_file

    design = parse_pcb_file(
        str(Path(__file__).parent / "fixtures" / "mixed_signal_4layer.kicad_pcb")
    )
    review = run_design_review(design, "sess-real")
    summary = review.to_dict()["executive_summary"]
    assert summary["overall_status"] in ("PASS", "WARNING", "FAIL", "INCONCLUSIVE")
    assert summary["domains_assessed"] > 0

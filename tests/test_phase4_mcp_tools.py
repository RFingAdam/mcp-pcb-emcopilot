"""End-to-end test for the Phase 4 MCP tools — pcb_set_market,
pcb_get_standards_coverage, pcb_validate_review_complete — plus the
preflight gate wired into pcb_generate_design_review_report.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_pcb_emcopilot import server as srv
from mcp_pcb_emcopilot.orchestrator import reset_finding_id_counters

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_signal_4layer.kicad_pcb"


@pytest.fixture
def fresh_session():
    reset_finding_id_counters()
    if not FIXTURE.exists():
        pytest.skip("fixture not available")
    start = srv._dispatch(
        "pcb_start_professional_review",
        {
            "input_files": [str(FIXTURE)],
            "declared_market": "unknown",  # leave open so set_market drives it
        },
    )
    sid = start["session_id"]
    srv._dispatch("pcb_parse_layout", {"file_path": str(FIXTURE), "session_id": sid})
    return sid


# --- pcb_set_market --------------------------------------------------------

def test_set_market_appends_and_updates_shortlist(fresh_session):
    out = srv._dispatch(
        "pcb_set_market",
        {"session_id": fresh_session, "market_id": "automotive"},
    )
    assert out["markets"] == ["automotive"]
    assert "CISPR_25" in out["standards_shortlist"]
    assert "automotive_emc" in out["analyzer_shortlist"]
    assert out["interview_pack_count"] > 10  # core + automotive merged


def test_set_market_multi_market_unions_standards(fresh_session):
    srv._dispatch("pcb_set_market",
                  {"session_id": fresh_session, "market_id": "medical"})
    out = srv._dispatch(
        "pcb_set_market",
        {"session_id": fresh_session, "market_id": "wireless"},
    )
    assert set(out["markets"]) == {"medical", "wireless"}
    standards = set(out["standards_shortlist"])
    assert "IEC_60601_1_2_ED_4_1" in standards
    assert "FCC_47_CFR_15C" in standards


def test_set_market_replace_clears_previous(fresh_session):
    srv._dispatch("pcb_set_market",
                  {"session_id": fresh_session, "market_id": "commercial"})
    out = srv._dispatch(
        "pcb_set_market",
        {
            "session_id": fresh_session,
            "market_id": "automotive",
            "replace": True,
        },
    )
    assert out["markets"] == ["automotive"]
    # Commercial-only standards should NOT be in the shortlist anymore
    assert "CISPR_32" not in out["standards_shortlist"]


def test_set_market_prefills_sub_options(fresh_session):
    srv._dispatch(
        "pcb_set_market",
        {
            "session_id": fresh_session,
            "market_id": "automotive",
            "sub_options": {
                "vehicle_class": "passenger",
                "bus_voltage": "12V",
            },
        },
    )
    data = srv.sessions.get_session(fresh_session)
    answers = data.review_context["interactive_answers"]
    assert answers["vehicle_class"] == "passenger"
    assert answers["bus_voltage"] == "12V"


def test_set_market_rejects_unknown_market(fresh_session):
    from mcp_pcb_emcopilot.errors import ValidationError
    with pytest.raises(ValidationError):
        srv._dispatch(
            "pcb_set_market",
            {"session_id": fresh_session, "market_id": "aerospace_quantum"},
        )


# --- pcb_get_standards_coverage -------------------------------------------

def test_coverage_for_automotive(fresh_session):
    srv._dispatch("pcb_set_market",
                  {"session_id": fresh_session, "market_id": "automotive"})
    out = srv._dispatch("pcb_get_standards_coverage",
                       {"session_id": fresh_session})
    assert out["total_standards"] >= 5  # CISPR_25, ISO_11452_*, ISO_7637_*, ISO_16750_2
    # ISO_7637_* should be flagged stub
    stub_stds = {c["standard"] for c in out["per_standard"]
                 if c["coverage_level"] == "stub"}
    assert "ISO_7637_2" in stub_stds


def test_coverage_distinguishes_ran_analyzers(fresh_session):
    """If review_results pretends automotive_emc ran, coverage should reflect it."""
    srv._dispatch("pcb_set_market",
                  {"session_id": fresh_session, "market_id": "automotive"})
    data = srv.sessions.get_session(fresh_session)
    data.review_results = {
        "domain_results": [
            {"domain": "automotive_emc", "status": "pass", "findings": []},
            {"domain": "return_paths", "status": "pass", "findings": []},
        ]
    }
    out = srv._dispatch("pcb_get_standards_coverage",
                       {"session_id": fresh_session})
    cispr = next(c for c in out["per_standard"] if c["standard"] == "CISPR_25")
    assert "automotive_emc" in cispr["ran_analyzers"]
    assert "return_paths" in cispr["ran_analyzers"]
    assert "smps_emi" in cispr["missing_analyzers"]


# --- pcb_validate_review_complete -----------------------------------------

def test_validate_initially_not_ready(fresh_session):
    out = srv._dispatch("pcb_validate_review_complete",
                       {"session_id": fresh_session})
    assert out["ready"] is False


def test_validate_passes_after_market_and_answers(fresh_session):
    srv._dispatch("pcb_set_market", {
        "session_id": fresh_session,
        "market_id": "commercial",
        "sub_options": {
            "operating_environment": "consumer",
            "fab_stackup_spec": "no_use_extracted",
            "cispr32_class": "B",
            "target_regions": ["US", "EU"],
        },
    })
    out = srv._dispatch("pcb_validate_review_complete",
                       {"session_id": fresh_session})
    assert out["ready"] is True


# --- Preflight gate wired into the report generator -----------------------

def test_report_gate_defers_when_preflight_fails(fresh_session):
    out = srv._dispatch(
        "pcb_generate_design_review_report",
        {"session_id": fresh_session, "format": "html"},
    )
    assert out["status"] == "deferred"
    # The new gate fires before the cross-MCP gate when intake is incomplete
    assert "preflight" in out
    assert out["preflight"]["ready"] is False


def test_report_force_true_emits_preliminary_when_preflight_fails(fresh_session):
    out = srv._dispatch(
        "pcb_generate_design_review_report",
        {"session_id": fresh_session, "format": "html", "force": True},
    )
    # Either the builder produced a report (with preliminary=True) or it
    # itself returned a structured response — in either case the gate did
    # not stop us.
    assert out.get("status") != "deferred"
    if "preliminary" in out:
        assert out["preliminary"] is True
        assert "preflight" in out

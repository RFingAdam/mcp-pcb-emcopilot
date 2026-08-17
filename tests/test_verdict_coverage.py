"""Coverage-aware verdict: a review that didn't run must not read as PASS.

Regression guard for the scariest failure mode of a compliance-adjacent tool —
zero findings from errored or never-run domains being reported as a clean
"PASS". The distinction that matters: ``error`` is an applicable analyzer that
threw (a real coverage gap) while ``skipped`` is a benign not-applicable domain
(no DDR interface, no power nets). See ``orchestrator._build_executive_summary``.
"""
from __future__ import annotations

import types

from mcp_pcb_emcopilot.orchestrator import DomainResult, _build_executive_summary


def _cls():
    return types.SimpleNamespace(design_type="mixed_signal", complexity_label="moderate")


def _finding(severity):
    # _build_executive_summary only reads finding.severity via the *_count props.
    return types.SimpleNamespace(severity=severity)


def test_assessed_clean_board_is_pass():
    drs = [
        DomainResult(domain="emc_grounding", status="pass"),
        DomainResult(domain="thermal", status="pass"),
    ]
    s = _build_executive_summary(drs, _cls(), [])
    assert s["overall_status"] == "PASS"
    assert s["coverage_complete"] is True


def test_errored_domain_downgrades_pass_to_inconclusive():
    drs = [
        DomainResult(domain="emc_grounding", status="pass"),
        DomainResult(domain="power_integrity", status="error"),
    ]
    s = _build_executive_summary(drs, _cls(), [])
    assert s["overall_status"] == "INCONCLUSIVE"  # NOT "PASS"
    assert s["domains_errored"] == 1
    assert s["coverage_complete"] is False


def test_nothing_actually_ran_is_inconclusive():
    drs = [
        DomainResult(domain="high_speed_ddr", status="skipped"),
        DomainResult(domain="high_speed_usb", status="skipped"),
    ]
    s = _build_executive_summary(drs, _cls(), [])
    assert s["overall_status"] == "INCONCLUSIVE"


def test_not_applicable_skips_do_not_block_pass():
    # A real assessment plus benign not-applicable skips is still a clean PASS.
    drs = [
        DomainResult(domain="emc_grounding", status="pass"),
        DomainResult(domain="high_speed_ddr", status="skipped"),
    ]
    s = _build_executive_summary(drs, _cls(), [])
    assert s["overall_status"] == "PASS"


def test_critical_finding_still_fails_regardless_of_coverage():
    real = DomainResult(domain="emc", status="fail", findings=[_finding("critical")])
    errored = DomainResult(domain="thermal", status="error")
    s = _build_executive_summary([real, errored], _cls(), [])
    assert s["overall_status"] == "FAIL"


# ---------------------------------------------------------------------------
# The gap the original gate left open: WARNING was tested *before*
# INCONCLUSIVE, so a single warning was enough to suppress the coverage gate
# and report "we looked and found issues" when the truth was "we could not
# look". One fabricated warning is all it took.
# ---------------------------------------------------------------------------

def test_warning_with_incomplete_coverage_is_inconclusive():
    """A warning must not mask a coverage gap.

    WARNING and INCONCLUSIVE answer different questions: WARNING means "we
    assessed it and found issues", INCONCLUSIVE means "we could not assess
    it". Reporting WARNING on incomplete coverage overstates confidence,
    because it implies the absence of *further* findings.
    """
    assessed = DomainResult(domain="emc", status="warning", findings=[_finding("warning")])
    errored = DomainResult(domain="power_integrity", status="error")
    s = _build_executive_summary([assessed, errored], _cls(), [])
    assert s["overall_status"] == "INCONCLUSIVE"
    assert s["coverage_complete"] is False


def test_warning_with_partial_parse_is_inconclusive():
    """Same rule for the ingest completeness gate, not just errored domains."""
    assessed = DomainResult(domain="emc", status="warning", findings=[_finding("warning")])
    s = _build_executive_summary([assessed], _cls(), [], parse_partial=True)
    assert s["overall_status"] == "INCONCLUSIVE"


def test_warning_survives_when_coverage_is_complete():
    """Real warnings are NOT weakened — full coverage still reports WARNING."""
    assessed = DomainResult(domain="emc", status="warning", findings=[_finding("warning")])
    other = DomainResult(domain="thermal", status="pass")
    s = _build_executive_summary([assessed, other], _cls(), [])
    assert s["overall_status"] == "WARNING"
    assert s["coverage_complete"] is True


def test_warnings_are_still_counted_when_inconclusive():
    """Only the headline changes; the findings themselves are still reported."""
    assessed = DomainResult(domain="emc", status="warning", findings=[_finding("warning")])
    errored = DomainResult(domain="thermal", status="error")
    s = _build_executive_summary([assessed, errored], _cls(), [])
    assert s["overall_status"] == "INCONCLUSIVE"
    assert s["total_warnings"] == 1
    assert s["domain_statuses"]["emc"]["warnings"] == 1


def test_insufficient_data_domain_blocks_pass():
    """"We had no data to answer this" is a coverage gap, not a pass.

    Distinct from ``error`` (the analyzer threw) and from ``skipped`` (the
    domain does not apply to this design).
    """
    assessed = DomainResult(domain="emc", status="pass")
    no_data = DomainResult(domain="emc_return_path", status="insufficient_data")
    s = _build_executive_summary([assessed, no_data], _cls(), [])
    assert s["overall_status"] == "INCONCLUSIVE"
    assert s["domains_insufficient"] == 1
    assert s["coverage_complete"] is False


def test_verdict_reason_names_the_gate_that_fired():
    """The verdict must be explainable, not just a bare word."""
    s_pass = _build_executive_summary(
        [DomainResult(domain="emc", status="pass")], _cls(), []
    )
    assert s_pass["verdict_reason"]

    s_inc = _build_executive_summary(
        [DomainResult(domain="emc", status="error")], _cls(), []
    )
    assert s_inc["overall_status"] == "INCONCLUSIVE"
    assert "error" in s_inc["verdict_reason"].lower()

    s_fail = _build_executive_summary(
        [DomainResult(domain="emc", status="fail", findings=[_finding("critical")])],
        _cls(), [],
    )
    assert "critical" in s_fail["verdict_reason"].lower()

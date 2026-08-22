"""Coverage-aware verdict: a review that didn't run must not read as PASS.

Regression guard for the scariest failure mode of a compliance-adjacent tool:
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

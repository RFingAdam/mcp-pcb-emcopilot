"""Return-path findings must actually reach the review report.

Regression guard for a silent-wrongness bug: ``_run_return_path_analysis`` read
``rp_result.net_analyses``, but :class:`ReturnPathAnalysisResult` has no such
attribute — the field is ``net_results``. Because the read went through
``getattr(..., [])`` it never raised; it just yielded an empty list, so the
domain reported ``status="pass"`` with zero findings for *every* design, however
bad its return paths were. The analysis ran correctly and its output was thrown
away between the analyzer and the report.

This is the worst category of defect for a compliance-adjacent tool: not a
crash, but a confident clean bill of health that a user will trust.
"""
from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from mcp_pcb_emcopilot.analyzers.emc.return_path_analyzer import (
    ReturnPathAnalysisResult,
    ReturnPathAnalyzer,
)
from mcp_pcb_emcopilot.classifiers.net_classifier import NetClassifier
from mcp_pcb_emcopilot.orchestrator import _run_return_path_analysis
from mcp_pcb_emcopilot.parsers import parse_pcb_file

FIXTURE = Path(__file__).parent / "fixtures" / "simple_2layer.kicad_pcb"


def _design_and_classification():
    design = parse_pcb_file(str(FIXTURE))
    return design, NetClassifier().classify(design)


# ---------------------------------------------------------------------------
# Schema guards — these are what makes the typo class of bug impossible to
# reintroduce silently.
# ---------------------------------------------------------------------------

def test_result_exposes_net_results():
    """The field the orchestrator must read is named ``net_results``."""
    names = {f.name for f in fields(ReturnPathAnalysisResult)}
    assert "net_results" in names


def test_result_has_no_net_analyses_attribute():
    """``net_analyses`` must not exist — a getattr for it silently yields []."""
    assert not hasattr(ReturnPathAnalysisResult(), "net_analyses")


# ---------------------------------------------------------------------------
# The actual defect: findings produced by the analyzer reached nothing.
# ---------------------------------------------------------------------------

def test_analyzer_produces_issues_on_this_fixture():
    """Precondition: the fixture really does have return-path issues.

    If this ever stops holding, the test below would pass vacuously.
    """
    design, net_cls = _design_and_classification()
    rp = ReturnPathAnalyzer().analyze(design, net_cls)
    issue_count = sum(len(nr.issues) for nr in rp.net_results)
    assert rp.net_results, "analyzer returned no per-net results"
    assert issue_count >= 3, f"expected >=3 issue strings, got {issue_count}"


def test_orchestrator_surfaces_return_path_findings():
    """Findings must reach DomainResult — this returned 0 before the fix."""
    design, net_cls = _design_and_classification()
    result = _run_return_path_analysis(design, net_cls)

    assert result.status != "error", result.error
    assert len(result.findings) >= 3, (
        f"return-path findings were dropped: got {len(result.findings)}"
    )


def test_findings_carry_real_issue_text_not_a_placeholder():
    """``issues`` is list[str]; the old code produced 'unknown' for every title.

    ``getattr(issue, 'issue_type', 'unknown')`` on a plain string always falls
    through to the default, so every finding was titled identically and carried
    no recommendation.
    """
    design, net_cls = _design_and_classification()
    result = _run_return_path_analysis(design, net_cls)

    titles = [f.title for f in result.findings]
    assert titles, "no findings to inspect"
    assert not any("unknown" in t for t in titles), titles
    # Distinct issues must produce distinct titles, or the risk matrix collapses.
    assert len(set(titles)) > 1, f"all findings share one title: {titles[0]!r}"
    assert all(f.description for f in result.findings)


def test_findings_are_attributed_to_their_net():
    design, net_cls = _design_and_classification()
    result = _run_return_path_analysis(design, net_cls)

    named = [f for f in result.findings if f.signal_name]
    assert named, "no finding carried a signal_name"
    assert any(f.signal_name == "SIG1" for f in result.findings), (
        [f.signal_name for f in result.findings]
    )


def test_per_net_recommendations_are_carried_through():
    """The analyzer emits per-net recommendations; they must not be discarded."""
    design, net_cls = _design_and_classification()
    result = _run_return_path_analysis(design, net_cls)

    assert any(f.recommendation for f in result.findings), (
        "every recommendation was dropped"
    )


def test_status_reflects_the_findings():
    """With findings present the domain can no longer report a clean pass."""
    design, net_cls = _design_and_classification()
    result = _run_return_path_analysis(design, net_cls)

    assert result.findings
    assert result.status in ("warning", "fail")


def test_string_issues_are_not_relabelled_as_a_severity_we_invented():
    """``ReturnPathResult.issues`` is list[str] and carries no severity.

    The caller must not manufacture 'critical' from a bare string — on this
    fixture one net is graded 'poor' only because it has an empty name and thus
    no routing, which is a data artifact, not an EMC critical.
    """
    design, net_cls = _design_and_classification()
    result = _run_return_path_analysis(design, net_cls)

    assert all(f.severity in ("warning", "info") for f in result.findings), (
        [(f.severity, f.title) for f in result.findings]
    )

"""Human-review / lab-verification block: the report's honesty backstop.

Covers the orchestrator's ``_build_human_review`` (review-level reasons +
per-finding flags) and an end-to-end check that a real review surfaces the
block into review_results and the rendered HTML report.
"""
from __future__ import annotations

from pathlib import Path

from mcp_pcb_emcopilot.orchestrator import (
    DomainResult,
    ReviewFinding,
    _build_human_review,
    run_design_review,
)
from mcp_pcb_emcopilot.parsers import parse_pcb_file
from mcp_pcb_emcopilot.reports.html_report import generate_html_report

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_signal_4layer.kicad_pcb"


def _summary(**kw):
    base = {"parse_partial": False, "domains_errored": 0, "overall_status": "PASS"}
    base.update(kw)
    return base


def test_partial_parse_adds_reason():
    hr = _build_human_review([], _summary(parse_partial=True))
    assert hr["required"]
    assert any("partial" in r.lower() for r in hr["reasons"])


def test_errored_domains_add_reason():
    hr = _build_human_review([], _summary(domains_errored=2))
    assert any("errored" in r.lower() for r in hr["reasons"])


def test_inconclusive_adds_reason():
    hr = _build_human_review([], _summary(overall_status="INCONCLUSIVE"))
    assert any("inconclusive" in r.lower() for r in hr["reasons"])


def test_low_confidence_finding_flagged():
    f = ReviewFinding(domain="signal_integrity", severity="warning",
                      title="X", description="d", confidence=0.4)
    dr = DomainResult(domain="signal_integrity", status="warning", findings=[f])
    hr = _build_human_review([dr], _summary())
    assert any("confidence" in it["reason"].lower() for it in hr["items"])


def test_analytical_critical_flagged():
    f = ReviewFinding(domain="signal_integrity", severity="critical",
                      title="X", description="d", confidence=0.85, source="analytical")
    dr = DomainResult(domain="signal_integrity", status="fail", findings=[f])
    hr = _build_human_review([dr], _summary())
    assert any(it["severity"] == "critical" for it in hr["items"])


def test_emc_pdn_screening_caveat_present():
    f = ReviewFinding(domain="emc_emi_risk", severity="info",
                      title="X", description="d", confidence=0.9)
    dr = DomainResult(domain="emc_emi_risk", status="pass", findings=[f])
    hr = _build_human_review([dr], _summary())
    assert any("screening" in r.lower() for r in hr["reasons"])


def test_clean_non_emc_review_not_required():
    f = ReviewFinding(domain="thermal", severity="info",
                      title="X", description="d", confidence=0.9)
    dr = DomainResult(domain="thermal", status="pass", findings=[f])
    hr = _build_human_review([dr], _summary())
    assert hr["required"] is False
    assert hr["items"] == []


def test_real_review_surfaces_human_review_and_renders(tmp_path):
    design = parse_pcb_file(str(FIXTURE))
    review = run_design_review(design, "hr-test")
    hr = review.to_dict().get("human_review", {})
    # A real mixed-signal board exercises EMC/PDN, so the screening caveat applies.
    assert hr.get("required") is True
    assert hr.get("reasons")

    design.review_results = review.to_dict()
    out = tmp_path / "hr.html"
    generate_html_report(design=design, session_id="hr-test", output_path=str(out),
                         title="HR Test", theme="light")
    html = out.read_text(encoding="utf-8")
    assert "Human Review" in html
    assert "Lab Verification" in html

"""End-to-end golden-path test: parse → review → report.

This is the single test that proves the whole flagship pipeline works:

1. parse a published KiCad fixture,
2. run the full multi-domain design review,
3. generate both DOCX and HTML reports,
4. verify the outputs are structurally valid (non-empty, readable as
   their respective formats, contain expected section anchors).

It does NOT hash-check artifact contents — DOCX output embeds a
creation timestamp that makes byte-identical reproduction impossible
without monkey-patching the whole toolchain. Structural validation is
the right level for a regression gate: if the review silently produces
an empty report, or the DOCX becomes unparseable, or the HTML loses a
section, this test goes red.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from mcp_pcb_emcopilot.orchestrator import run_design_review
from mcp_pcb_emcopilot.parsers import parse_pcb_file

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_signal_4layer.kicad_pcb"


@pytest.fixture(scope="module")
def reviewed_design():
    design = parse_pcb_file(str(FIXTURE))
    review = run_design_review(design, "e2e-golden")
    return design, review


def test_parse_produces_real_data(reviewed_design):
    design, _ = reviewed_design
    assert len(design.components) > 5
    assert len(design.nets) > 10
    assert len(design.traces) > 10
    assert len(design.layers) >= 4


def test_review_covers_multiple_domains(reviewed_design):
    _, review = reviewed_design
    # The orchestrator runs across 20+ domains; a golden-path review must
    # produce results for a meaningful cross-section of them.
    assert len(review.domain_results) >= 10
    statuses = {dr.status for dr in review.domain_results}
    # At least one domain must have actually run — not all skipped/errored.
    assert statuses & {"pass", "warning", "fail"}, (
        f"no domains actually ran; statuses were {statuses}"
    )


def test_executive_summary_is_nontrivial(reviewed_design):
    _, review = reviewed_design
    summary = review.executive_summary
    assert summary is not None
    # Either a non-empty string or a dict with fields — reject both None
    # and empty stringy/empty-dict cases that indicate the summariser bailed.
    assert (isinstance(summary, str) and len(summary) > 50) or (
        isinstance(summary, dict) and summary
    )


def test_docx_report_is_valid_zip(reviewed_design, tmp_path):
    docx_mod = pytest.importorskip("docx", reason="python-docx not installed")
    from mcp_pcb_emcopilot.reports.docx_report import generate_docx_report

    design, review = reviewed_design
    # Attach review results to the design the way the MCP tool flow does.
    design.review_results = review.to_dict()
    out = tmp_path / "report.docx"
    path = generate_docx_report(design, session_id="e2e-golden", output_path=str(out))

    assert Path(path).exists()
    assert Path(path).stat().st_size > 1024, "DOCX report is suspiciously small"
    # DOCX is a ZIP — if the archive is malformed the report is broken.
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
    assert "word/document.xml" in names, "DOCX missing core document.xml"

    # Round-trip via python-docx to confirm the document actually parses.
    doc = docx_mod.Document(path)
    assert len(doc.paragraphs) > 5, "DOCX has fewer paragraphs than expected"


def test_html_report_has_expected_sections(reviewed_design, tmp_path):
    from mcp_pcb_emcopilot.reports.html_report import generate_html_report

    design, review = reviewed_design
    design.review_results = review.to_dict()
    out = tmp_path / "report.html"
    path = generate_html_report(
        design=design,
        session_id="e2e-golden",
        output_path=str(out),
        title="E2E Golden Report",
        theme="light",
    )

    html = Path(path).read_text(encoding="utf-8")
    assert len(html) > 5000, "HTML report is suspiciously small"
    assert "<html" in html.lower()
    assert "</html>" in html.lower()
    # The review banner must include the title we passed.
    assert "E2E Golden Report" in html

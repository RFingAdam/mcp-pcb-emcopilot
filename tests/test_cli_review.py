"""CLI ``review`` subcommand: one-command 'board in -> report out'.

These lock the headless product contract: a non-expert can point the tool at
a board file and get a report, with clear exit codes and an honest summary.
The heavy engine work is already covered by test_end_to_end_review.py; here we
only exercise the CLI glue (arg handling, format inference, error paths).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mcp_pcb_emcopilot.cli import run_review

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_signal_4layer.kicad_pcb"


def test_html_review_produces_report(tmp_path):
    out = tmp_path / "report.html"
    rc = run_review([str(FIXTURE), "--format", "html", "-o", str(out), "--quiet"])
    assert rc == 0
    assert out.exists() and out.stat().st_size > 5000
    assert "<html" in out.read_text(encoding="utf-8").lower()


def test_docx_review_when_available(tmp_path):
    pytest.importorskip("docx", reason="python-docx not installed")
    out = tmp_path / "report.docx"
    rc = run_review(
        [str(FIXTURE), "--format", "docx", "-o", str(out), "--market", "automotive", "--quiet"]
    )
    assert rc == 0
    assert out.exists() and out.stat().st_size > 1024


def test_format_inferred_from_output_extension(tmp_path):
    out = tmp_path / "inferred.html"
    rc = run_review([str(FIXTURE), "-o", str(out), "--quiet"])
    assert rc == 0
    assert out.exists()
    assert "<html" in out.read_text(encoding="utf-8").lower()


def test_missing_board_returns_nonzero(tmp_path):
    rc = run_review([str(tmp_path / "does_not_exist.kicad_pcb"), "--quiet"])
    assert rc == 2


def test_unknown_market_returns_nonzero(tmp_path):
    rc = run_review(
        [str(FIXTURE), "--market", "nonsense-market", "-o", str(tmp_path / "r.html"), "--quiet"]
    )
    assert rc == 2

"""Optional dependencies must degrade predictably, not crash.

CI installs ``.[all,dev]`` on Linux, so every optional-dependency fallback path
in the package is dead code there — no CI leg has ever executed one. That blind
spot hid a real defect: ``cairosvg`` installs from a wheel on Windows but raises
``OSError`` from cairocffi's ``dlopen`` when the native Cairo library is absent.
The guard in ``exporter.svg_to_png`` caught only ``ImportError``, so the
``OSError`` escaped and report generation aborted instead of degrading.

These tests simulate absence explicitly so both failure modes are covered
regardless of what is installed on the machine running them.
"""
from __future__ import annotations

import sys
import textwrap

import pytest

from mcp_pcb_emcopilot.errors import MissingDependencyError, PCBError
from mcp_pcb_emcopilot.visualization import exporter

SIMPLE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10">'
    '<rect x="1" y="1" width="18" height="8" fill="#000"/></svg>'
)


def _install_fake_cairosvg(tmp_path, monkeypatch, body: str) -> None:
    """Shadow the real cairosvg with a module whose import raises."""
    pkg = tmp_path / "cairosvg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(textwrap.dedent(body), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "cairosvg", raising=False)


# ---------------------------------------------------------------------------
# The regression: an installed-but-unusable dependency raises OSError.
# ---------------------------------------------------------------------------

def test_oserror_is_treated_as_a_missing_dependency():
    """OSError must be in the caught set, not just ImportError.

    This is the whole defect: cairocffi raises OSError, so guarding only
    ImportError let it propagate out of every caller that meant to degrade.
    """
    assert OSError in exporter._CAIRO_IMPORT_ERRORS
    assert ImportError in exporter._CAIRO_IMPORT_ERRORS


def test_svg_to_png_converts_oserror_into_missing_dependency(tmp_path, monkeypatch):
    _install_fake_cairosvg(
        tmp_path, monkeypatch,
        'raise OSError("no library called \\"cairo-2\\" was found")',
    )
    assert exporter.png_export_available() is False
    with pytest.raises(MissingDependencyError) as exc:
        exporter.svg_to_png(SIMPLE_SVG, str(tmp_path / "out.png"))
    assert exc.value.code == "MISSING_DEPENDENCY"
    assert "cairosvg" in exc.value.message


def test_svg_to_png_converts_importerror_into_missing_dependency(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setitem(sys.modules, "cairosvg", None)
    assert exporter.png_export_available() is False
    with pytest.raises(MissingDependencyError):
        exporter.svg_to_png(SIMPLE_SVG, str(tmp_path / "out.png"))


def test_missing_dependency_error_is_a_pcberror():
    """So the MCP layer serialises it as a structured refusal, not a crash."""
    assert issubclass(MissingDependencyError, PCBError)
    err = MissingDependencyError("MISSING_DEPENDENCY", "nope", {"dependency": "x"})
    payload = err.to_dict()
    assert payload["error_type"] == "MissingDependencyError"
    assert payload["context"]["dependency"] == "x"


# ---------------------------------------------------------------------------
# SVG output must stay available with no optional dependency at all.
# ---------------------------------------------------------------------------

def test_svg_output_needs_no_optional_dependency(tmp_path, monkeypatch):
    _install_fake_cairosvg(tmp_path, monkeypatch, 'raise OSError("no cairo")')
    out = exporter.svg_to_file(SIMPLE_SVG, str(tmp_path / "out.svg"))
    assert "<svg" in open(out, encoding="utf-8").read()


def test_batch_export_svg_needs_no_optional_dependency(tmp_path, monkeypatch):
    _install_fake_cairosvg(tmp_path, monkeypatch, 'raise OSError("no cairo")')
    results = exporter.batch_export(
        {"board": SIMPLE_SVG}, str(tmp_path / "d"), fmt="svg"
    )
    assert results["board"].endswith(".svg")


def test_png_export_does_not_silently_write_svg_bytes(tmp_path, monkeypatch):
    """A .png containing SVG is worse than an explicit failure.

    The module docstring used to claim it "falls back to writing raw SVG",
    which was never implemented. Assert the honest behaviour instead.
    """
    _install_fake_cairosvg(tmp_path, monkeypatch, 'raise OSError("no cairo")')
    target = tmp_path / "out.png"
    with pytest.raises(MissingDependencyError):
        exporter.svg_to_png(SIMPLE_SVG, str(target))
    assert not target.exists() or target.stat().st_size == 0


# ---------------------------------------------------------------------------
# Report generation must survive without PNG support.
# ---------------------------------------------------------------------------

def test_generate_all_renders_returns_empty_instead_of_raising(tmp_path, monkeypatch):
    """Previously the first two svg_to_png calls were unguarded and aborted."""
    from mcp_pcb_emcopilot.reports import docx_report

    monkeypatch.setattr(
        "mcp_pcb_emcopilot.visualization.exporter.png_export_available",
        lambda: False,
    )
    design = _design()
    results = docx_report.generate_all_renders(
        design, "sess", str(tmp_path / "imgs"), 400
    )
    assert results == {}


def test_docx_report_still_generates_without_png_support(tmp_path, monkeypatch):
    pytest.importorskip("docx", reason="python-docx not installed")
    from mcp_pcb_emcopilot.reports.docx_report import generate_docx_report

    monkeypatch.setattr(
        "mcp_pcb_emcopilot.visualization.exporter.png_export_available",
        lambda: False,
    )
    out = tmp_path / "r.docx"
    result = generate_docx_report(
        design=_design(),
        session_id="s1",
        output_path=str(out),
        title="Text Only Report",
    )
    assert out.exists()
    assert out.stat().st_size > 1000
    from docx import Document
    text = "\n".join(p.text for p in Document(result).paragraphs)
    assert "Text Only Report" in text


def _design():
    from mcp_pcb_emcopilot.models.pcb_data import PCBDesignData

    d = PCBDesignData(source_file="/tmp/b.kicad_pcb")
    d.board_width_mm = 50.0
    d.board_height_mm = 30.0
    return d

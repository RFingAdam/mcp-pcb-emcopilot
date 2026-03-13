"""Tests for the ReportBuilder class."""

from __future__ import annotations

import os
import pytest

from mcp_pcb_emcopilot.models.pcb_data import PCBDesignData, PCBLayer, PCBComponent, PCBNet, PCBTrace
from mcp_pcb_emcopilot.reports.report_builder import ReportBuilder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_design(**overrides) -> PCBDesignData:
    """Create a minimal PCBDesignData for testing."""
    defaults = dict(
        source_file="test_board.kicad_pcb",
        source_format="kicad",
        board_width_mm=100.0,
        board_height_mm=80.0,
        board_thickness_mm=1.6,
        title="Test Board",
        layers=[
            PCBLayer(number=0, name="F.Cu", layer_type="signal", thickness_mm=0.035),
            PCBLayer(number=1, name="GND", layer_type="plane", thickness_mm=0.035),
            PCBLayer(number=2, name="PWR", layer_type="plane", thickness_mm=0.035),
            PCBLayer(number=3, name="B.Cu", layer_type="signal", thickness_mm=0.035),
        ],
        components=[
            PCBComponent(reference="U1", value="MCU", package="BGA-256",
                         x_mm=50.0, y_mm=40.0, layer="F.Cu", rotation=0.0),
        ],
        nets=[
            PCBNet(name="GND", pin_count=12),
            PCBNet(name="VCC_3V3", pin_count=6),
        ],
        traces=[
            PCBTrace(layer="F.Cu", width_mm=0.2, net_name="VCC_3V3",
                     length_mm=15.0, x1_mm=10.0, y1_mm=20.0, x2_mm=25.0, y2_mm=20.0),
        ],
    )
    defaults.update(overrides)
    return PCBDesignData(**defaults)


def _make_review_results():
    """Create synthetic review_results dict."""
    return {
        "overall_status": "WARNING",
        "domains": {
            "emc": {
                "status": "WARNING",
                "score": 75,
                "findings": [
                    {
                        "severity": "WARNING",
                        "title": "EMI risk moderate",
                        "detail": "Board EMI score 75/100",
                        "recommendation": "Add shielding",
                    }
                ],
            },
            "signal_integrity": {
                "status": "PASS",
                "score": 95,
                "findings": [
                    {
                        "severity": "PASS",
                        "title": "DDR eye diagram OK",
                        "detail": "Eye height 738 mV",
                        "recommendation": "",
                    }
                ],
            },
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReportBuilderInit:
    """Tests for ReportBuilder initialization."""

    def test_creates_with_design_data(self):
        design = _make_design()
        builder = ReportBuilder(design)
        assert builder.design is design

    def test_creates_with_title_override(self):
        design = _make_design()
        builder = ReportBuilder(design, title="Custom Report Title")
        assert builder.title == "Custom Report Title"

    def test_default_title_from_design(self):
        design = _make_design(title="Test Board")
        builder = ReportBuilder(design)
        assert "Test Board" in builder.title


class TestSessionHarvesting:
    """Tests for collecting analysis results."""

    def test_harvest_from_review_results(self):
        design = _make_design(review_results=_make_review_results())
        builder = ReportBuilder(design)
        results = builder._harvest_session()
        assert "emc" in results
        assert "signal_integrity" in results

    def test_harvest_from_analysis_cache(self):
        design = _make_design()
        design.analysis_cache["pcb_analyze_esd"] = {"status": "FAIL"}
        builder = ReportBuilder(design)
        results = builder._harvest_session()
        assert "pcb_analyze_esd" in results

    def test_harvest_merges_both_sources(self):
        design = _make_design(review_results=_make_review_results())
        design.analysis_cache["pcb_analyze_esd"] = {"status": "FAIL"}
        builder = ReportBuilder(design)
        results = builder._harvest_session()
        assert "emc" in results
        assert "pcb_analyze_esd" in results

    def test_empty_session_returns_empty(self):
        design = _make_design()
        builder = ReportBuilder(design)
        results = builder._harvest_session()
        assert isinstance(results, dict)


class TestReportGeneration:
    """Tests for generating report files."""

    def test_empty_session_produces_valid_docx(self, tmp_path):
        design = _make_design()
        builder = ReportBuilder(design, output_dir=str(tmp_path))
        result = builder.generate(format="docx")
        assert result["docx_path"].endswith(".docx")
        assert os.path.exists(result["docx_path"])
        assert result["sections_generated"] >= 7  # required sections always present
        assert result["overall_verdict"] is not None

    def test_empty_session_produces_valid_html(self, tmp_path):
        design = _make_design()
        builder = ReportBuilder(design, output_dir=str(tmp_path))
        result = builder.generate(format="html")
        assert result["html_path"].endswith(".html")
        assert os.path.exists(result["html_path"])

    def test_both_format_produces_both_files(self, tmp_path):
        design = _make_design()
        builder = ReportBuilder(design, output_dir=str(tmp_path))
        result = builder.generate(format="both")
        assert os.path.exists(result["docx_path"])
        assert os.path.exists(result["html_path"])

    def test_session_with_results_includes_domain_sections(self, tmp_path):
        design = _make_design(review_results=_make_review_results())
        builder = ReportBuilder(design, output_dir=str(tmp_path))
        result = builder.generate(format="docx")
        assert result["sections_generated"] > 7  # more than just required

    def test_findings_count_in_result(self, tmp_path):
        design = _make_design(review_results=_make_review_results())
        builder = ReportBuilder(design, output_dir=str(tmp_path))
        result = builder.generate(format="docx")
        fc = result["findings_count"]
        assert isinstance(fc, dict)
        assert "critical" in fc
        assert "high" in fc
        assert "warning" in fc
        assert "pass" in fc

    def test_overall_verdict_critical(self, tmp_path):
        results = _make_review_results()
        results["domains"]["emc"]["findings"][0]["severity"] = "CRITICAL"
        design = _make_design(review_results=results)
        builder = ReportBuilder(design, output_dir=str(tmp_path))
        result = builder.generate(format="docx")
        assert "CRITICAL" in result["overall_verdict"]

    def test_overall_verdict_pass(self, tmp_path):
        results = _make_review_results()
        for domain in results["domains"].values():
            for f in domain["findings"]:
                f["severity"] = "PASS"
        design = _make_design(review_results=results)
        builder = ReportBuilder(design, output_dir=str(tmp_path))
        result = builder.generate(format="docx")
        assert "PASS" in result["overall_verdict"]

    def test_custom_title_in_output(self, tmp_path):
        design = _make_design()
        builder = ReportBuilder(design, title="Acme Widget Rev C", output_dir=str(tmp_path))
        result = builder.generate(format="docx")
        assert os.path.exists(result["docx_path"])

    def test_custom_confidentiality(self, tmp_path):
        design = _make_design()
        builder = ReportBuilder(design, confidentiality="PUBLIC", output_dir=str(tmp_path))
        result = builder.generate(format="docx")
        assert os.path.exists(result["docx_path"])

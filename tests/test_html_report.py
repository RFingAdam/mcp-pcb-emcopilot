"""Tests for the interactive HTML report generator."""

import os
import re
import tempfile

import pytest

from mcp_pcb_emcopilot.models.pcb_data import (
    PCBComponent,
    PCBDesignData,
    PCBLayer,
    PCBNet,
    PCBTrace,
    PCBVia,
    PCBZone,
)
from mcp_pcb_emcopilot.reports.html_report import (
    DomainResult,
    Finding,
    HTMLReportData,
    HTMLReportGenerator,
    _build_badge,
    _build_finding_card,
    _build_info_table,
    _build_section,
    _embed_image,
    _escape_html,
    _severity_class,
    generate_html_report,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_design(**overrides) -> PCBDesignData:
    """Create a minimal PCBDesignData suitable for HTML report tests."""
    d = PCBDesignData(source_file="/tmp/test_board.kicad_pcb", source_format="kicad")
    d.board_width_mm = 100.0
    d.board_height_mm = 80.0
    d.layer_count = 4
    d.layers = [
        PCBLayer(name="F.Cu", number=0, layer_type="signal", thickness_mm=0.035, copper_weight_oz=1.0),
        PCBLayer(name="GND", number=1, layer_type="plane", thickness_mm=0.035),
        PCBLayer(name="PWR", number=2, layer_type="plane", thickness_mm=0.035),
        PCBLayer(name="B.Cu", number=3, layer_type="signal", thickness_mm=0.035, copper_weight_oz=1.0),
    ]
    d.components = [
        PCBComponent(reference="U1", value="MCU", footprint="QFP-48", x_mm=50, y_mm=40, layer="F.Cu"),
        PCBComponent(reference="R1", value="10k", footprint="0402", x_mm=30, y_mm=20, layer="F.Cu"),
    ]
    d.nets = [
        PCBNet(name="GND", index=0, pin_count=12),
        PCBNet(name="VCC_3V3", index=1, pin_count=6),
        PCBNet(name="SPI_CLK", index=2, pin_count=2),
    ]
    d.traces = [
        PCBTrace(layer="F.Cu", width_mm=0.2, x1_mm=30, y1_mm=20, x2_mm=50, y2_mm=40, net_name="SPI_CLK", net_index=2),
    ]
    d.vias = [
        PCBVia(x_mm=25, y_mm=30, drill_mm=0.3, pad_diameter_mm=0.6, net_name="GND", net_index=0),
        PCBVia(x_mm=60, y_mm=50, drill_mm=0.4, pad_diameter_mm=0.8, net_name="VCC_3V3", net_index=1),
    ]
    d.zones = [
        PCBZone(layer="GND", net_name="GND"),
    ]
    d.review_results = overrides.get("review_results", {})
    return d


def _make_review_results(
    *,
    critical: int = 1,
    warning: int = 2,
    info: int = 1,
    pass_count: int = 1,
    domains: list[str] | None = None,
) -> dict:
    """Build synthetic review_results dict."""
    if domains is None:
        domains = ["EMC", "Signal Integrity"]

    all_findings = []
    for i in range(critical):
        all_findings.append(
            {"severity": "CRITICAL", "title": f"Critical #{i+1}", "detail": "Fix this", "recommendation": "Add filter"}
        )
    for i in range(warning):
        all_findings.append(
            {"severity": "WARNING", "title": f"Warning #{i+1}", "detail": "Check this", "recommendation": "Review"}
        )
    for i in range(info):
        all_findings.append(
            {"severity": "INFO", "title": f"Info #{i+1}", "detail": "Noted", "recommendation": ""}
        )
    for i in range(pass_count):
        all_findings.append(
            {"severity": "PASS", "title": f"Pass #{i+1}", "detail": "Good", "recommendation": ""}
        )

    # Distribute findings across domains
    domain_results = []
    for idx, dom in enumerate(domains):
        start = idx * len(all_findings) // len(domains)
        end = (idx + 1) * len(all_findings) // len(domains)
        domain_results.append({
            "domain": dom,
            "status": "WARNING",
            "findings": all_findings[start:end],
        })

    return {
        "executive_summary": {
            "overall_status": "WARNING",
            "total_findings": len(all_findings),
            "total_critical": critical,
            "total_warnings": warning,
        },
        "domain_results": domain_results,
        "emi_hotspots": [],
    }


# ---------------------------------------------------------------------------
# Test: generate_html_report (function-based API)
# ---------------------------------------------------------------------------

class TestGenerateHtmlReport:
    """Tests for the generate_html_report() function."""

    def test_generates_valid_html_file(self):
        """Report file should be created and contain valid HTML structure."""
        design = _make_design(review_results=_make_review_results())
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            result = generate_html_report(design, session_id="sess-001", output_path=out_path)
            assert os.path.exists(result)
            with open(result) as fh:
                html = fh.read()
            assert "<!DOCTYPE html>" in html
        finally:
            os.unlink(out_path)

    def test_contains_html_head_body(self):
        """Report must include <html>, <head>, and <body> tags."""
        design = _make_design(review_results=_make_review_results())
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            generate_html_report(design, session_id="sess-002", output_path=out_path)
            with open(out_path) as fh:
                html = fh.read()
            assert "<html" in html
            assert "<head>" in html
            assert "<body>" in html
            assert "</html>" in html
        finally:
            os.unlink(out_path)

    def test_contains_style_and_script(self):
        """Report must embed <style> and <script> blocks."""
        design = _make_design(review_results=_make_review_results())
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            generate_html_report(design, session_id="sess-003", output_path=out_path)
            with open(out_path) as fh:
                html = fh.read()
            assert "<style>" in html
            assert "</style>" in html
            assert "<script>" in html
            assert "</script>" in html
        finally:
            os.unlink(out_path)

    def test_self_contained_no_external_urls(self):
        """Report should not reference any external http/https URLs."""
        design = _make_design(review_results=_make_review_results())
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            generate_html_report(design, session_id="sess-004", output_path=out_path)
            with open(out_path) as fh:
                html = fh.read()
            # No external resource references (stylesheets, scripts, images)
            assert 'href="http://' not in html
            assert 'href="https://' not in html
            assert 'src="http://' not in html
            assert 'src="https://' not in html
        finally:
            os.unlink(out_path)

    def test_domain_sections_rendered(self):
        """Each analysis domain should appear as a section heading."""
        results = _make_review_results(domains=["EMC", "Thermal", "PDN"])
        design = _make_design(review_results=results)
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            generate_html_report(design, session_id="sess-005", output_path=out_path)
            with open(out_path) as fh:
                html = fh.read()
            assert "EMC Analysis" in html
            assert "Thermal Analysis" in html
            assert "PDN Analysis" in html
        finally:
            os.unlink(out_path)

    def test_severity_filter_buttons(self):
        """Filter bar should have buttons for each severity level."""
        design = _make_design(review_results=_make_review_results())
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            generate_html_report(design, session_id="sess-006", output_path=out_path)
            with open(out_path) as fh:
                html = fh.read()
            assert 'data-severity="CRITICAL"' in html
            assert 'data-severity="HIGH"' in html
            assert 'data-severity="WARNING"' in html
            assert 'data-severity="PASS"' in html
            assert 'data-severity="INFO"' in html
            assert 'data-severity="ALL"' in html
        finally:
            os.unlink(out_path)

    def test_findings_have_severity_badges(self):
        """Each finding card should contain a severity badge."""
        results = _make_review_results(critical=1, warning=1, info=0, pass_count=0)
        design = _make_design(review_results=results)
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            generate_html_report(design, session_id="sess-007", output_path=out_path)
            with open(out_path) as fh:
                html = fh.read()
            assert 'class="badge badge-CRITICAL"' in html
            assert 'class="badge badge-WARNING"' in html
        finally:
            os.unlink(out_path)

    def test_score_dashboard_present(self):
        """Executive summary should include score dashboard cards."""
        design = _make_design(review_results=_make_review_results())
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            generate_html_report(design, session_id="sess-008", output_path=out_path)
            with open(out_path) as fh:
                html = fh.read()
            assert "summary-grid" in html
            assert "summary-card" in html
            assert "Overall Status" in html
            assert "Total Findings" in html
        finally:
            os.unlink(out_path)

    def test_empty_findings(self):
        """Report should render gracefully with zero findings."""
        design = _make_design(review_results={
            "executive_summary": {"overall_status": "PASS"},
            "domain_results": [],
        })
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            result = generate_html_report(design, session_id="sess-009", output_path=out_path)
            assert os.path.exists(result)
            with open(result) as fh:
                html = fh.read()
            assert "<!DOCTYPE html>" in html
            # Should still contain the dashboard
            assert "Total Findings" in html
        finally:
            os.unlink(out_path)

    def test_all_severity_levels_present(self):
        """Report with all severity levels should render all of them."""
        results = _make_review_results(critical=1, warning=1, info=1, pass_count=1)
        results["domain_results"][0]["findings"].append(
            {"severity": "HIGH", "title": "High issue", "detail": "Found it", "recommendation": "Fix"}
        )
        design = _make_design(review_results=results)
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            generate_html_report(design, session_id="sess-010", output_path=out_path)
            with open(out_path) as fh:
                html = fh.read()
            assert "finding-CRITICAL" in html
            assert "finding-HIGH" in html
            assert "finding-WARNING" in html
            assert "finding-PASS" in html
            assert "finding-INFO" in html
        finally:
            os.unlink(out_path)

    def test_save_to_file_returns_abs_path(self):
        """generate_html_report should return the absolute path."""
        design = _make_design(review_results=_make_review_results())
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            result = generate_html_report(design, session_id="sess-011", output_path=out_path)
            assert os.path.isabs(result)
            assert result == os.path.abspath(out_path)
        finally:
            os.unlink(result)

    def test_auto_creates_temp_file(self):
        """When output_path is None, a temp file should be created."""
        design = _make_design(review_results=_make_review_results())
        result = generate_html_report(design, session_id="sess-012")
        try:
            assert os.path.exists(result)
            assert result.endswith(".html")
        finally:
            os.unlink(result)

    def test_dark_theme(self):
        """Dark theme CSS variables should appear when theme='dark'."""
        design = _make_design(review_results=_make_review_results())
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            generate_html_report(design, session_id="sess-013", output_path=out_path, theme="dark")
            with open(out_path) as fh:
                html = fh.read()
            # Dark theme uses #0f172a as background
            assert "#0f172a" in html
        finally:
            os.unlink(out_path)

    def test_light_theme_default(self):
        """Default theme should be light (white background)."""
        design = _make_design(review_results=_make_review_results())
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            generate_html_report(design, session_id="sess-014", output_path=out_path)
            with open(out_path) as fh:
                html = fh.read()
            # Light theme uses #ffffff as primary bg
            assert "--bg-primary: #ffffff" in html
        finally:
            os.unlink(out_path)

    def test_collapsible_section_js(self):
        """JS for collapsible sections should be embedded."""
        design = _make_design(review_results=_make_review_results())
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            generate_html_report(design, session_id="sess-015", output_path=out_path)
            with open(out_path) as fh:
                html = fh.read()
            assert "section-header" in html
            assert "toggle" in html
            assert "DOMContentLoaded" in html
        finally:
            os.unlink(out_path)

    def test_print_css_media_query(self):
        """Print-friendly @media print CSS should be present."""
        design = _make_design(review_results=_make_review_results())
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            generate_html_report(design, session_id="sess-016", output_path=out_path)
            with open(out_path) as fh:
                html = fh.read()
            assert "@media print" in html
        finally:
            os.unlink(out_path)

    def test_board_overview_section(self):
        """Board Overview section should list board dimensions and counts."""
        design = _make_design(review_results=_make_review_results())
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            generate_html_report(design, session_id="sess-017", output_path=out_path)
            with open(out_path) as fh:
                html = fh.read()
            assert "Board Overview" in html
            assert "Board Size" in html
            assert "Layer Count" in html
            assert "Components" in html
        finally:
            os.unlink(out_path)

    def test_custom_title(self):
        """Custom title should appear in <title> and header."""
        design = _make_design(review_results=_make_review_results())
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            generate_html_report(
                design, session_id="sess-018", output_path=out_path,
                title="My Custom Board Review",
            )
            with open(out_path) as fh:
                html = fh.read()
            assert "<title>My Custom Board Review</title>" in html
            assert "My Custom Board Review" in html
        finally:
            os.unlink(out_path)

    def test_session_id_in_report(self):
        """Session ID should appear in the report metadata."""
        design = _make_design(review_results=_make_review_results())
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            generate_html_report(design, session_id="sess-unique-42", output_path=out_path)
            with open(out_path) as fh:
                html = fh.read()
            assert "sess-unique-42" in html
        finally:
            os.unlink(out_path)

    def test_no_review_results(self):
        """Report should render even with empty review_results."""
        design = _make_design()
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            result = generate_html_report(design, session_id="sess-019", output_path=out_path)
            assert os.path.exists(result)
            with open(result) as fh:
                html = fh.read()
            assert "<!DOCTYPE html>" in html
        finally:
            os.unlink(out_path)

    def test_drill_table_section(self):
        """When vias exist, a Drill Table section should be included."""
        design = _make_design(review_results=_make_review_results())
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            generate_html_report(design, session_id="sess-020", output_path=out_path)
            with open(out_path) as fh:
                html = fh.read()
            assert "Drill Table" in html
            assert "0.300 mm" in html
            assert "0.400 mm" in html
        finally:
            os.unlink(out_path)


# ---------------------------------------------------------------------------
# Test: helper functions
# ---------------------------------------------------------------------------

class TestEscapeHtml:
    """Tests for _escape_html()."""

    def test_escapes_ampersand(self):
        assert "&amp;" in _escape_html("A & B")

    def test_escapes_angle_brackets(self):
        assert "&lt;" in _escape_html("<script>")
        assert "&gt;" in _escape_html("x>y")

    def test_escapes_quotes(self):
        assert "&quot;" in _escape_html('say "hello"')
        assert "&#x27;" in _escape_html("it's")

    def test_plain_text_unchanged(self):
        assert _escape_html("Hello World 123") == "Hello World 123"


class TestSeverityClass:
    """Tests for _severity_class()."""

    def test_canonical_values(self):
        assert _severity_class("critical") == "CRITICAL"
        assert _severity_class("HIGH") == "HIGH"
        assert _severity_class("warning") == "WARNING"
        assert _severity_class("pass") == "PASS"
        assert _severity_class("info") == "INFO"

    def test_aliases(self):
        assert _severity_class("ERROR") == "CRITICAL"
        assert _severity_class("FAIL") == "CRITICAL"
        assert _severity_class("MEDIUM") == "WARNING"
        assert _severity_class("MODERATE") == "WARNING"
        assert _severity_class("LOW") == "PASS"
        assert _severity_class("OK") == "PASS"

    def test_unknown_defaults_to_info(self):
        assert _severity_class("banana") == "INFO"


class TestBuildBadge:
    """Tests for _build_badge()."""

    def test_returns_span(self):
        badge = _build_badge("critical")
        assert "<span" in badge
        assert 'class="badge badge-CRITICAL"' in badge
        assert "CRITICAL" in badge

    def test_warning_badge(self):
        badge = _build_badge("warning")
        assert "badge-WARNING" in badge


class TestBuildFindingCard:
    """Tests for _build_finding_card()."""

    def test_card_has_data_severity(self):
        card = _build_finding_card({"severity": "WARNING", "title": "Test"})
        assert 'data-severity="WARNING"' in card
        assert "finding-WARNING" in card

    def test_card_shows_title(self):
        card = _build_finding_card({"severity": "INFO", "title": "My Title"})
        assert "My Title" in card

    def test_card_shows_recommendation(self):
        card = _build_finding_card({
            "severity": "CRITICAL",
            "title": "Issue",
            "recommendation": "Fix it now",
        })
        assert "Recommendation:" in card
        assert "Fix it now" in card

    def test_card_escapes_html_in_title(self):
        card = _build_finding_card({"severity": "INFO", "title": "<script>alert(1)</script>"})
        assert "<script>" not in card
        assert "&lt;script&gt;" in card


class TestBuildSection:
    """Tests for _build_section()."""

    def test_section_structure(self):
        section = _build_section("My Section", "<p>Content</p>")
        assert 'class="section"' in section
        assert "My Section" in section
        assert "<p>Content</p>" in section

    def test_collapsed_section(self):
        section = _build_section("Collapsed", "<p>Hidden</p>", collapsed=True)
        assert "collapsed" in section


class TestBuildInfoTable:
    """Tests for _build_info_table()."""

    def test_creates_table(self):
        table = _build_info_table([("Name", "Value"), ("Size", "100 mm")])
        assert '<table class="info-table">' in table
        assert "Name" in table
        assert "Value" in table
        assert "100 mm" in table


class TestEmbedImage:
    """Tests for _embed_image()."""

    def test_nonexistent_path_returns_empty(self):
        result = _embed_image("/does/not/exist.png")
        assert result == ""

    def test_empty_path_returns_empty(self):
        result = _embed_image("")
        assert result == ""

    def test_embeds_svg_as_base64(self):
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w") as f:
            f.write(svg_content)
            f.flush()
            path = f.name
        try:
            result = _embed_image(path, caption="Test SVG")
            assert "data:image/svg+xml;base64," in result
            assert "render-container" in result
            assert "Test SVG" in result
        finally:
            os.unlink(path)

    def test_embeds_png_as_base64(self):
        # Minimal valid PNG: 1x1 white pixel
        import base64
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        )
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png_bytes)
            path = f.name
        try:
            result = _embed_image(path, caption="Tiny PNG")
            assert "data:image/png;base64," in result
            assert "Tiny PNG" in result
        finally:
            os.unlink(path)

    def test_embed_image_with_images_in_report(self):
        """Embedded SVG images should appear inline in generated report."""
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg"><circle r="5"/></svg>'
        with tempfile.TemporaryDirectory() as imgdir:
            svg_path = os.path.join(imgdir, "board_full.svg")
            with open(svg_path, "w") as f:
                f.write(svg_content)

            design = _make_design(review_results=_make_review_results())
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
                out_path = f.name
            try:
                generate_html_report(
                    design,
                    session_id="sess-img",
                    output_path=out_path,
                    image_dir=imgdir,
                )
                with open(out_path) as fh:
                    html = fh.read()
                # The image should be embedded inline as base64
                assert "data:image/svg+xml;base64," in html
            finally:
                os.unlink(out_path)


# ---------------------------------------------------------------------------
# Test: dataclasses
# ---------------------------------------------------------------------------

class TestDataclasses:
    """Tests for Finding, DomainResult, HTMLReportData dataclasses."""

    def test_finding_defaults(self):
        f = Finding(severity="warning", title="Test", description="Desc")
        assert f.recommendation == ""
        assert f.location == ""
        assert f.domain == ""

    def test_domain_result(self):
        findings = [Finding(severity="info", title="OK", description="All good")]
        dr = DomainResult(name="EMC", score=85.0, findings=findings)
        assert dr.name == "EMC"
        assert dr.score == 85.0
        assert len(dr.findings) == 1

    def test_html_report_data(self):
        data = HTMLReportData(
            title="Board Review",
            design_file="board.kicad_pcb",
            review_date="2025-05-01",
        )
        assert data.title == "Board Review"
        assert data.domains == []
        assert data.summary == {}
        assert data.images == {}


# ---------------------------------------------------------------------------
# Test: HTMLReportGenerator class
# ---------------------------------------------------------------------------

class TestHTMLReportGenerator:
    """Tests for the HTMLReportGenerator class-based API."""

    def test_class_exists(self):
        gen = HTMLReportGenerator()
        assert hasattr(gen, "generate")
        assert hasattr(gen, "save")

    def test_generate_returns_valid_html(self):
        """HTMLReportGenerator.generate returns a complete HTML string."""
        gen = HTMLReportGenerator()
        data = HTMLReportData(
            title="Test",
            design_file="test.kicad_pcb",
            review_date="2025-05-01",
        )
        html = gen.generate(data)
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "Test" in html
        assert "test.kicad_pcb" in html

    def test_generate_with_domains(self):
        """HTMLReportGenerator should render domain sections with findings."""
        gen = HTMLReportGenerator()
        data = HTMLReportData(
            title="Domain Test",
            design_file="board.kicad_pcb",
            review_date="2025-06-01",
            domains=[
                DomainResult(
                    name="EMC",
                    score=72.0,
                    findings=[
                        Finding(severity="warning", title="Clock routing issue", description="Clock crosses split plane"),
                        Finding(severity="pass", title="Decoupling OK", description="Adequate decoupling"),
                    ],
                ),
                DomainResult(
                    name="Signal Integrity",
                    score=90.0,
                    findings=[
                        Finding(severity="info", title="Trace length note", description="Within tolerance"),
                    ],
                ),
            ],
        )
        html = gen.generate(data)
        assert "EMC" in html
        assert "Signal Integrity" in html
        assert "Clock routing issue" in html
        assert "Decoupling OK" in html

    def test_generate_with_inline_svg_image(self):
        """HTMLReportGenerator should embed inline SVG content."""
        gen = HTMLReportGenerator()
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
        data = HTMLReportData(
            title="Image Test",
            design_file="board.kicad_pcb",
            review_date="2025-06-01",
            images={"board_render": svg},
        )
        html = gen.generate(data)
        assert "Board Images" in html
        assert "<svg" in html
        assert "board_render" in html

    def test_save_writes_file(self):
        """HTMLReportGenerator.save should write HTML to disk and return abs path."""
        gen = HTMLReportGenerator()
        data = HTMLReportData(
            title="Save Test",
            design_file="board.kicad_pcb",
            review_date="2025-06-01",
        )
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            out_path = f.name
        try:
            result = gen.save(data, out_path)
            assert os.path.isabs(result)
            assert os.path.exists(result)
            with open(result) as fh:
                html = fh.read()
            assert "Save Test" in html
        finally:
            os.unlink(out_path)

    def test_generate_self_contained(self):
        """Class-based report should also be self-contained (no external URLs)."""
        gen = HTMLReportGenerator()
        data = HTMLReportData(
            title="Self-contained Test",
            design_file="board.kicad_pcb",
            review_date="2025-06-01",
            domains=[
                DomainResult(name="Thermal", score=65.0, findings=[
                    Finding(severity="critical", title="Hot spot", description="U1 overheating"),
                ]),
            ],
        )
        html = gen.generate(data)
        assert 'href="http://' not in html
        assert 'href="https://' not in html
        assert 'src="http://' not in html
        assert 'src="https://' not in html

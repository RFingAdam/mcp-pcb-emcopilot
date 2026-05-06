"""Tests for PDF schematic parser, server tool dispatch, and cross-reference validation.

Tests the following without requiring a real PDF file or PyMuPDF:
- Component reference regex extraction
- Net label regex extraction
- Fallback (no pymupdf) path
- Server dispatch for the 3 new tools
- SchematicLayoutValidator cross-reference
"""

import os
import sys
import tempfile

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from mcp_pcb_emcopilot.analyzers.validation.schematic_layout_validator import (
    SchematicLayoutValidator,
)
from mcp_pcb_emcopilot.models.pcb_data import (
    PCBComponent,
    PCBDesignData,
    PCBNet,
)
from mcp_pcb_emcopilot.parsers.pdf_schematic_parser import (
    _NET_BLACKLIST,
    _NET_LABEL_PATTERN,
    _REFDES_PATTERN,
    PDFSchematicParser,
    PDFSchematicResult,
)

# =========================================================================
# 1. Regex unit tests
# =========================================================================

class TestRefDesRegex:
    """Test that the reference designator regex matches expected patterns."""

    def test_basic_resistor(self):
        m = _REFDES_PATTERN.search("R1")
        assert m is not None
        assert m.group("ref") == "R1"

    def test_multi_digit(self):
        m = _REFDES_PATTERN.search("C100")
        assert m is not None
        assert m.group("ref") == "C100"

    def test_ic(self):
        m = _REFDES_PATTERN.search("U3")
        assert m is not None
        assert m.group("ref") == "U3"

    def test_connector(self):
        m = _REFDES_PATTERN.search("J1")
        assert m is not None
        assert m.group("ref") == "J1"

    def test_inductor(self):
        m = _REFDES_PATTERN.search("L2")
        assert m is not None
        assert m.group("ref") == "L2"

    def test_ferrite_bead(self):
        m = _REFDES_PATTERN.search("FB1")
        assert m is not None
        assert m.group("ref") == "FB1"

    def test_transistor(self):
        m = _REFDES_PATTERN.search("Q1")
        assert m is not None
        assert m.group("ref") == "Q1"

    def test_led(self):
        m = _REFDES_PATTERN.search("LED1")
        assert m is not None
        assert m.group("ref") == "LED1"

    def test_tvs(self):
        m = _REFDES_PATTERN.search("TVS1")
        assert m is not None
        assert m.group("ref") == "TVS1"

    def test_test_point(self):
        m = _REFDES_PATTERN.search("TP5")
        assert m is not None
        assert m.group("ref") == "TP5"

    def test_with_value_equals(self):
        m = _REFDES_PATTERN.search("R1=10k")
        assert m is not None
        assert m.group("ref") == "R1"
        assert m.group("value").strip() == "10k"

    def test_with_value_space(self):
        m = _REFDES_PATTERN.search("C10 100nF")
        assert m is not None
        assert m.group("ref") == "C10"
        assert "100n" in m.group("value").strip()

    def test_with_letter_suffix(self):
        m = _REFDES_PATTERN.search("R1A")
        assert m is not None
        assert m.group("ref") == "R1A"

    def test_multiple_in_text(self):
        text = "Connect R1 10k to U3 pin 5, through C10 100nF. Also check D1 and Q2."
        refs = [m.group("ref") for m in _REFDES_PATTERN.finditer(text)]
        assert "R1" in refs
        assert "U3" in refs
        assert "C10" in refs
        assert "D1" in refs
        assert "Q2" in refs

    def test_no_match_for_plain_text(self):
        assert _REFDES_PATTERN.search("Hello World") is None

    def test_no_match_for_revision(self):
        # "REV" should NOT match as a refdes (no digits)
        m = _REFDES_PATTERN.search("REV A")
        assert m is None


class TestNetLabelRegex:
    """Test net label regex extraction."""

    def test_vcc(self):
        m = _NET_LABEL_PATTERN.search("VCC")
        assert m is not None
        assert m.group("net") == "VCC"

    def test_gnd(self):
        m = _NET_LABEL_PATTERN.search("GND")
        assert m is not None
        assert m.group("net") == "GND"

    def test_power_rail(self):
        m = _NET_LABEL_PATTERN.search("+3V3")
        assert m is not None
        assert m.group("net") == "+3V3"

    def test_signal_name(self):
        m = _NET_LABEL_PATTERN.search("SDA")
        assert m is not None
        assert m.group("net") == "SDA"

    def test_complex_net_name(self):
        m = _NET_LABEL_PATTERN.search("CLK_100M")
        assert m is not None
        assert m.group("net") == "CLK_100M"

    def test_vbus_usb(self):
        m = _NET_LABEL_PATTERN.search("VBUS_USB")
        assert m is not None
        assert m.group("net") == "VBUS_USB"

    def test_blacklist_filtered(self):
        for word in ["TITLE", "DATE", "SHEET", "SCALE", "PROJECT"]:
            assert word in _NET_BLACKLIST

    def test_multiple_nets_in_text(self):
        text = "VCC to GND through SDA and SCL lines. CLK_100M clock."
        nets = [m.group("net") for m in _NET_LABEL_PATTERN.finditer(text)]
        assert "VCC" in nets
        assert "GND" in nets
        assert "SDA" in nets
        assert "SCL" in nets
        assert "CLK_100M" in nets


# =========================================================================
# 2. Parser extraction tests (using internal methods)
# =========================================================================

class TestParserExtraction:
    """Test the parser's extraction methods directly."""

    def setup_method(self):
        self.parser = PDFSchematicParser()

    def test_extract_components_from_text(self):
        text = """
        Sheet 1 of 3
        R1 10k   R2 4.7k   C1 100nF
        U1 STM32F4   U2 LM3940
        J1 USB-C   J2 Header 2x5
        D1 LED  Q1 2N2222
        """
        comps = self.parser._extract_components(text, page=1)
        refs = {c["reference"] for c in comps}
        assert "R1" in refs
        assert "R2" in refs
        assert "C1" in refs
        assert "U1" in refs
        assert "U2" in refs
        assert "J1" in refs
        assert "J2" in refs
        assert "D1" in refs
        assert "Q1" in refs

    def test_extract_components_deduplicates(self):
        text = "R1 10k\nR1 10k\nR1 10k"
        comps = self.parser._extract_components(text, page=1)
        assert len(comps) == 1

    def test_extract_nets_from_text(self):
        text = """
        VCC +3V3 GND
        SDA SCL MOSI MISO
        CLK_100M  RESET_N
        UART_TX UART_RX
        """
        nets = self.parser._extract_nets(text, page=1)
        names = {n["name"] for n in nets}
        assert "VCC" in names
        assert "GND" in names
        assert "SDA" in names
        assert "SCL" in names
        assert "MOSI" in names
        assert "CLK_100M" in names
        assert "UART_TX" in names

    def test_extract_nets_filters_blacklist(self):
        text = "TITLE: My Project   SHEET 1 of 3   DATE 2025-01-01"
        nets = self.parser._extract_nets(text, page=1)
        names = {n["name"] for n in nets}
        assert "TITLE" not in names
        assert "SHEET" not in names
        assert "DATE" not in names

    def test_extract_nets_power_classification(self):
        text = "VCC VDD VBUS GND VSS AGND"
        nets = self.parser._extract_nets(text, page=1)
        net_map = {n["name"]: n for n in nets}
        assert net_map["VCC"]["is_power"] is True
        assert net_map["VDD"]["is_power"] is True
        assert net_map["GND"]["is_ground"] is True
        assert net_map["VSS"]["is_ground"] is True
        assert net_map["AGND"]["is_ground"] is True

    def test_extract_nets_does_not_duplicate_refdes(self):
        """Net extraction should not pick up things that are component refs."""
        text = "R1 C10 U3 SDA SCL"
        nets = self.parser._extract_nets(text, page=1)
        names = {n["name"] for n in nets}
        assert "SDA" in names
        assert "SCL" in names
        # R1, C10, U3 should NOT appear as nets
        assert "R1" not in names
        assert "C10" not in names
        assert "U3" not in names


# =========================================================================
# 3. PDF fallback tests (no pymupdf, using a real minimal PDF)
# =========================================================================

class TestPDFParseFallback:
    """Test fallback parsing when pymupdf is not available."""

    def test_parse_nonexistent_file_raises(self):
        parser = PDFSchematicParser()
        try:
            parser.parse("/nonexistent/file.pdf")
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_parse_non_pdf_raises(self):
        parser = PDFSchematicParser()
        # Create a temp non-PDF file with .pdf extension
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, mode="wb") as f:
            f.write(b"This is not a PDF")
            tmp_path = f.name
        try:
            result = parser.parse(tmp_path)
            # Should parse but detect it's not valid
            # (fallback path will note the issue in warnings or set page_count=0)
            # The fallback path should handle this gracefully
            assert result.page_count == 0 or len(result.warnings) > 0
        except ValueError:
            pass  # Also acceptable
        finally:
            os.unlink(tmp_path)

    def test_parse_minimal_pdf_fallback(self):
        """Create a minimal valid PDF and test fallback parsing."""
        parser = PDFSchematicParser()
        # Force fallback by unsetting fitz
        parser._fitz = None
        original_load = parser._load_fitz
        parser._load_fitz = lambda: False  # Force fallback

        # Create a minimal valid PDF
        pdf_bytes = _make_minimal_pdf()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, mode="wb") as f:
            f.write(pdf_bytes)
            tmp_path = f.name

        try:
            result = parser.parse(tmp_path)
            assert result.pymupdf_available is False
            assert result.page_count >= 0  # May or may not parse page count
            assert any("PyMuPDF" in w for w in result.warnings)
        finally:
            os.unlink(tmp_path)
            parser._load_fitz = original_load


# =========================================================================
# 4. PDFSchematicResult tests
# =========================================================================

class TestPDFSchematicResult:
    """Test the result dataclass."""

    def test_to_summary(self):
        result = PDFSchematicResult(
            file_path="/path/to/schematic.pdf",
            page_count=3,
            components=[
                {"reference": "R1", "value": "10k", "page": 1},
                {"reference": "R2", "value": "4.7k", "page": 1},
                {"reference": "C1", "value": "100nF", "page": 2},
                {"reference": "U1", "value": None, "page": 1},
            ],
            nets=[
                {"name": "VCC", "page": 1},
                {"name": "GND", "page": 1},
            ],
            has_text_layer=True,
            pymupdf_available=True,
        )

        summary = result.to_summary()
        assert summary["page_count"] == 3
        assert summary["component_count"] == 4
        assert summary["net_count"] == 2
        assert summary["has_text_layer"] is True
        assert "R" in summary["unique_ref_prefixes"]
        assert summary["unique_ref_prefixes"]["R"] == 2
        assert summary["unique_ref_prefixes"]["C"] == 1
        assert summary["unique_ref_prefixes"]["U"] == 1


# =========================================================================
# 5. Cross-reference validation tests
# =========================================================================

class TestCrossReferenceValidation:
    """Test SchematicLayoutValidator with PDF-extracted schematic data."""

    def test_perfect_match(self):
        """All schematic components present in layout."""
        data = PCBDesignData(source_file="test.kicad_pcb")
        data.schematic_components = [
            {"reference": "R1", "value": "10k"},
            {"reference": "C1", "value": "100nF"},
            {"reference": "U1", "value": "STM32"},
        ]
        data.components = [
            PCBComponent(reference="R1", value="10k"),
            PCBComponent(reference="C1", value="100nF"),
            PCBComponent(reference="U1", value="STM32"),
        ]

        validator = SchematicLayoutValidator()
        result = validator.validate(data)
        assert result.total_schematic_components == 3
        assert result.total_layout_components == 3
        assert result.matching_components == 3
        assert result.errors == 0
        assert result.warnings == 0
        assert result.calculate_match_percentage() == 100.0

    def test_missing_in_layout(self):
        """Component in schematic but not in layout."""
        data = PCBDesignData(source_file="test.kicad_pcb")
        data.schematic_components = [
            {"reference": "R1", "value": "10k"},
            {"reference": "R2", "value": "4.7k"},
        ]
        data.components = [
            PCBComponent(reference="R1", value="10k"),
        ]

        validator = SchematicLayoutValidator()
        result = validator.validate(data)
        assert result.total_schematic_components == 2
        assert result.total_layout_components == 1
        assert result.matching_components == 1
        assert result.errors == 1  # R2 missing in layout
        mismatches = [m for m in result.component_mismatches if m.mismatch_type == "missing_in_layout"]
        assert len(mismatches) == 1
        assert mismatches[0].reference == "R2"

    def test_missing_in_schematic(self):
        """Component in layout but not in schematic (extra component)."""
        data = PCBDesignData(source_file="test.kicad_pcb")
        data.schematic_components = [
            {"reference": "R1", "value": "10k"},
        ]
        data.components = [
            PCBComponent(reference="R1", value="10k"),
            PCBComponent(reference="C99", value="1uF"),
        ]

        validator = SchematicLayoutValidator()
        result = validator.validate(data)
        assert result.warnings == 1  # C99 extra in layout
        mismatches = [m for m in result.component_mismatches if m.mismatch_type == "missing_in_schematic"]
        assert len(mismatches) == 1
        assert mismatches[0].reference == "C99"

    def test_value_mismatch(self):
        """Same component but different value."""
        data = PCBDesignData(source_file="test.kicad_pcb")
        data.schematic_components = [
            {"reference": "R1", "value": "10k"},
        ]
        data.components = [
            PCBComponent(reference="R1", value="4.7k"),
        ]

        validator = SchematicLayoutValidator()
        result = validator.validate(data)
        assert result.warnings == 1
        mismatches = [m for m in result.component_mismatches if m.mismatch_type == "value_mismatch"]
        assert len(mismatches) == 1
        assert mismatches[0].schematic_value == "10k"
        assert mismatches[0].layout_value == "4.7k"

    def test_net_mismatch(self):
        """Schematic net not in layout."""
        data = PCBDesignData(source_file="test.kicad_pcb")
        data.schematic_components = []
        data.schematic_nets = [
            {"name": "SDA"},
            {"name": "SCL"},
            {"name": "VCC"},  # power nets are skipped
        ]
        data.nets = [
            PCBNet(name="SDA", index=1),
        ]

        validator = SchematicLayoutValidator()
        result = validator.validate(data)
        # SCL is a signal net missing from layout
        net_mismatches = [m for m in result.net_mismatches if m.net_name == "SCL"]
        assert len(net_mismatches) == 1


# =========================================================================
# 6. Server dispatch tests (test through _dispatch)
# =========================================================================

class TestServerDispatch:
    """Test the 3 new tools through the server dispatch mechanism."""

    def _dispatch(self, name, args):
        """Call _dispatch directly."""
        from mcp_pcb_emcopilot.server import _dispatch
        return _dispatch(name, args)

    def _create_layout_session(self):
        """Create a mock layout session and return the session_id."""
        from mcp_pcb_emcopilot.server import sessions
        data = PCBDesignData(
            source_file="test.kicad_pcb",
            source_format="kicad",
            components=[
                PCBComponent(reference="R1", value="10k"),
                PCBComponent(reference="R2", value="4.7k"),
                PCBComponent(reference="C1", value="100nF"),
                PCBComponent(reference="U1", value="STM32F4"),
            ],
            nets=[
                PCBNet(name="VCC", index=1),
                PCBNet(name="GND", index=2),
                PCBNet(name="SDA", index=3),
                PCBNet(name="SCL", index=4),
            ],
        )
        return sessions.create_session(data)

    def test_parse_schematic_pdf_creates_session(self):
        """Test pcb_parse_schematic_pdf with a minimal PDF creates a session."""
        pdf_bytes = _make_minimal_pdf()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, mode="wb") as f:
            f.write(pdf_bytes)
            tmp_path = f.name

        try:
            result = self._dispatch("pcb_parse_schematic_pdf", {"file_path": tmp_path})
            assert result["success"] is True
            assert "session_id" in result
            assert result["page_count"] >= 0

            # Clean up session
            from mcp_pcb_emcopilot.server import sessions
            sessions.close_session(result["session_id"])
        finally:
            os.unlink(tmp_path)

    def test_parse_schematic_pdf_attaches_to_session(self):
        """Test pcb_parse_schematic_pdf attaching to an existing layout session."""
        sid = self._create_layout_session()

        pdf_bytes = _make_minimal_pdf()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, mode="wb") as f:
            f.write(pdf_bytes)
            tmp_path = f.name

        try:
            result = self._dispatch("pcb_parse_schematic_pdf", {
                "file_path": tmp_path,
                "session_id": sid,
            })
            assert result["success"] is True
            assert result["session_id"] == sid

            # Verify schematic data was attached
            from mcp_pcb_emcopilot.server import sessions
            data = sessions.get_session(sid)
            assert data.schematic_pdf_path is not None
            assert data.schematic_pages is not None
        finally:
            os.unlink(tmp_path)
            from mcp_pcb_emcopilot.server import sessions
            sessions.close_session(sid)

    def test_get_schematic_page_no_data_raises(self):
        """pcb_get_schematic_page on session without schematic should raise."""
        sid = self._create_layout_session()
        try:
            self._dispatch("pcb_get_schematic_page", {
                "session_id": sid,
                "page_number": 1,
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "No schematic PDF data" in str(e)
        finally:
            from mcp_pcb_emcopilot.server import sessions
            sessions.close_session(sid)

    def test_get_schematic_page_out_of_range_raises(self):
        """pcb_get_schematic_page with bad page number should raise."""
        from mcp_pcb_emcopilot.server import sessions

        data = PCBDesignData(
            source_file="test.pdf",
            source_format="schematic_pdf",
            schematic_pages=[
                {"page_number": 1, "text": "R1 C1", "components": [], "nets": [], "width_pts": 0, "height_pts": 0},
            ],
        )
        sid = sessions.create_session(data)

        try:
            self._dispatch("pcb_get_schematic_page", {
                "session_id": sid,
                "page_number": 5,
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "out of range" in str(e)
        finally:
            sessions.close_session(sid)

    def test_get_schematic_page_returns_data(self):
        """pcb_get_schematic_page returns correct page data."""
        from mcp_pcb_emcopilot.server import sessions

        data = PCBDesignData(
            source_file="test.pdf",
            source_format="schematic_pdf",
            schematic_pages=[
                {
                    "page_number": 1,
                    "text": "Sheet 1: Power supply\nR1 10k C1 100nF U1 LM3940\nVCC GND",
                    "components": [
                        {"reference": "R1", "value": "10k", "page": 1},
                        {"reference": "C1", "value": "100nF", "page": 1},
                        {"reference": "U1", "value": None, "page": 1},
                    ],
                    "nets": [
                        {"name": "VCC", "page": 1},
                        {"name": "GND", "page": 1},
                    ],
                    "width_pts": 792.0,
                    "height_pts": 612.0,
                },
                {
                    "page_number": 2,
                    "text": "Sheet 2: MCU\nU2 STM32\nSDA SCL",
                    "components": [{"reference": "U2", "value": None, "page": 2}],
                    "nets": [
                        {"name": "SDA", "page": 2},
                        {"name": "SCL", "page": 2},
                    ],
                    "width_pts": 792.0,
                    "height_pts": 612.0,
                },
            ],
        )
        sid = sessions.create_session(data)

        try:
            result = self._dispatch("pcb_get_schematic_page", {
                "session_id": sid,
                "page_number": 1,
            })
            assert result["page_number"] == 1
            assert result["component_count"] == 3
            assert result["net_count"] == 2
            assert "R1" in result["text"]

            result2 = self._dispatch("pcb_get_schematic_page", {
                "session_id": sid,
                "page_number": 2,
            })
            assert result2["page_number"] == 2
            assert result2["component_count"] == 1
        finally:
            sessions.close_session(sid)

    def test_cross_reference_no_schematic_raises(self):
        """pcb_cross_reference_schematic without schematic data should raise."""
        sid = self._create_layout_session()
        try:
            self._dispatch("pcb_cross_reference_schematic", {"session_id": sid})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "No schematic data" in str(e)
        finally:
            from mcp_pcb_emcopilot.server import sessions
            sessions.close_session(sid)

    def test_cross_reference_no_layout_raises(self):
        """pcb_cross_reference_schematic without layout data should raise."""
        from mcp_pcb_emcopilot.server import sessions

        data = PCBDesignData(
            source_file="test.pdf",
            source_format="schematic_pdf",
            schematic_components=[{"reference": "R1", "value": "10k"}],
        )
        sid = sessions.create_session(data)

        try:
            self._dispatch("pcb_cross_reference_schematic", {"session_id": sid})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "No layout data" in str(e)
        finally:
            sessions.close_session(sid)

    def test_cross_reference_full_flow(self):
        """Full cross-reference: layout + schematic in one session."""
        from mcp_pcb_emcopilot.server import sessions

        data = PCBDesignData(
            source_file="test.kicad_pcb",
            source_format="kicad",
            components=[
                PCBComponent(reference="R1", value="10k"),
                PCBComponent(reference="C1", value="100nF"),
                PCBComponent(reference="U1", value="STM32F4"),
            ],
            nets=[
                PCBNet(name="VCC", index=1),
                PCBNet(name="GND", index=2),
                PCBNet(name="SDA", index=3),
            ],
            schematic_components=[
                {"reference": "R1", "value": "10k"},
                {"reference": "R2", "value": "4.7k"},  # missing in layout
                {"reference": "C1", "value": "100nF"},
                {"reference": "U1", "value": "STM32F4"},
            ],
            schematic_nets=[
                {"name": "VCC"},
                {"name": "GND"},
                {"name": "SDA"},
                {"name": "SCL"},  # missing in layout (signal net)
            ],
        )
        sid = sessions.create_session(data)

        try:
            result = self._dispatch("pcb_cross_reference_schematic", {"session_id": sid})
            assert result["total_schematic_components"] == 4
            assert result["total_layout_components"] == 3
            assert result["matching_components"] == 3
            assert result["errors"] >= 1  # R2 missing
            assert result["match_percentage"] == 75.0

            # Check component mismatches
            comp_mismatches = result["component_mismatches"]
            missing_refs = [m["reference"] for m in comp_mismatches if m["mismatch_type"] == "missing_in_layout"]
            assert "R2" in missing_refs

            # Check net mismatches
            net_mismatches = result["net_mismatches"]
            missing_nets = [m["net_name"] for m in net_mismatches if m["mismatch_type"] == "missing_in_layout"]
            assert "SCL" in missing_nets
        finally:
            sessions.close_session(sid)


# =========================================================================
# 7. Format detection test
# =========================================================================

class TestFormatDetection:
    """Test that PDF format is detected correctly."""

    def test_detect_pdf(self):
        from mcp_pcb_emcopilot.parsers import detect_format
        assert detect_format("schematic.pdf") == "schematic_pdf"
        assert detect_format("DESIGN.PDF") == "schematic_pdf"

    def test_detect_other_formats_unchanged(self):
        from mcp_pcb_emcopilot.parsers import detect_format
        assert detect_format("board.kicad_pcb") == "kicad"
        assert detect_format("board.PcbDoc") == "altium"


# =========================================================================
# Helpers
# =========================================================================

def _make_minimal_pdf() -> bytes:
    """Create a minimal valid PDF (1 page) in memory.

    This is a bare-bones PDF that satisfies the %PDF header check
    and has a /Count 1 for page counting.
    """
    # Minimal PDF 1.0 spec compliant document
    return (
        b"%PDF-1.0\n"
        b"1 0 obj\n"
        b"<< /Type /Catalog /Pages 2 0 R >>\n"
        b"endobj\n"
        b"2 0 obj\n"
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>\n"
        b"endobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\n"
        b"endobj\n"
        b"xref\n"
        b"0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"trailer\n"
        b"<< /Size 4 /Root 1 0 R >>\n"
        b"startxref\n"
        b"190\n"
        b"%%EOF\n"
    )


# =========================================================================
# Run all tests
# =========================================================================

def run_tests():
    """Run all test classes and methods."""
    import traceback

    test_classes = [
        TestRefDesRegex,
        TestNetLabelRegex,
        TestParserExtraction,
        TestPDFParseFallback,
        TestPDFSchematicResult,
        TestCrossReferenceValidation,
        TestServerDispatch,
        TestFormatDetection,
    ]

    total = 0
    passed = 0
    failed = 0
    errors = []

    for cls in test_classes:
        instance = cls()
        methods = [m for m in dir(instance) if m.startswith("test_")]
        for method_name in sorted(methods):
            total += 1
            method = getattr(instance, method_name)
            try:
                # Call setup_method if it exists
                if hasattr(instance, "setup_method"):
                    instance.setup_method()
                method()
                passed += 1
                print(f"  PASS  {cls.__name__}.{method_name}")
            except Exception as e:
                failed += 1
                errors.append((cls.__name__, method_name, e))
                print(f"  FAIL  {cls.__name__}.{method_name}: {e}")
                traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if errors:
        print("\nFailed tests:")
        for cls_name, method_name, err in errors:
            print(f"  - {cls_name}.{method_name}: {err}")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)

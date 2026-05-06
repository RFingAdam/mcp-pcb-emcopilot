"""Tests for the Allegro/OrCAD PCB parser."""

from pathlib import Path

import pytest

from mcp_pcb_emcopilot.errors import ParseError
from mcp_pcb_emcopilot.parsers import detect_format, parse_pcb_file
from mcp_pcb_emcopilot.parsers.allegro_parser import (
    AllegroParser,
    _map_layer_name,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_ALLEGRO = str(FIXTURES_DIR / "sample_allegro.txt")


class TestAllegroParserBasic:
    """Test basic parsing of the Allegro sample fixture."""

    @pytest.fixture(autouse=True)
    def parse_board(self):
        parser = AllegroParser()
        self.board = parser.parse_file(SAMPLE_ALLEGRO)

    def test_source_file(self):
        assert self.board.source_file == SAMPLE_ALLEGRO

    def test_version(self):
        assert self.board.version == "17.4-2024"

    def test_title(self):
        assert self.board.title == "Allegro 4-Layer Test Board"

    def test_units(self):
        assert self.board.units == "mm"


class TestAllegroComponents:
    """Test component extraction from Allegro fixture."""

    @pytest.fixture(autouse=True)
    def parse_board(self):
        parser = AllegroParser()
        self.board = parser.parse_file(SAMPLE_ALLEGRO)

    def test_component_count(self):
        assert len(self.board.components) == 10

    def test_component_references(self):
        refs = {c.reference for c in self.board.components}
        expected = {"U1", "U2", "R1", "R2", "R3", "R4", "C1", "C2", "C3", "J1"}
        assert refs == expected

    def test_bga_component(self):
        u1 = next(c for c in self.board.components if c.reference == "U1")
        assert u1.footprint == "BGA-256"
        assert u1.x_mm == 50.0
        assert u1.y_mm == 40.0
        assert u1.rotation == 0.0
        assert u1.side == "TOP"
        assert u1.value == "MCU"
        assert u1.part_number == "STM32F407"

    def test_qfp_component(self):
        u2 = next(c for c in self.board.components if c.reference == "U2")
        assert u2.footprint == "QFP-64"
        assert u2.x_mm == 20.0
        assert u2.y_mm == 30.0
        assert u2.rotation == 90.0
        assert u2.value == "FPGA"

    def test_resistor_component(self):
        r1 = next(c for c in self.board.components if c.reference == "R1")
        assert r1.footprint == "0402"
        assert r1.value == "4.7k"
        assert r1.x_mm == 35.0
        assert r1.y_mm == 15.0

    def test_connector_component(self):
        j1 = next(c for c in self.board.components if c.reference == "J1")
        assert j1.footprint == "USB-C"
        assert j1.x_mm == 5.0
        assert j1.y_mm == 40.0

    def test_all_components_top_side(self):
        for comp in self.board.components:
            assert comp.side == "TOP"


class TestAllegroNets:
    """Test net extraction from Allegro fixture."""

    @pytest.fixture(autouse=True)
    def parse_board(self):
        parser = AllegroParser()
        self.board = parser.parse_file(SAMPLE_ALLEGRO)

    def test_net_count(self):
        assert len(self.board.nets) == 15

    def test_net_names(self):
        names = {n.name for n in self.board.nets}
        expected = {
            "GND", "VCC", "USB_DP", "USB_DN", "CLK",
            "DATA0", "DATA1", "DATA2", "DATA3",
            "ADDR0", "ADDR1", "ADDR2", "ADDR3",
            "RESET", "INT",
        }
        assert names == expected

    def test_gnd_net_pins(self):
        gnd = next(n for n in self.board.nets if n.name == "GND")
        assert len(gnd.pins) >= 6  # Multiple components connect to GND

    def test_usb_dp_net_pins(self):
        usb_dp = next(n for n in self.board.nets if n.name == "USB_DP")
        assert "U1.USB_DP" in usb_dp.pins
        assert "J1.DP" in usb_dp.pins

    def test_net_indices_unique(self):
        indices = [n.index for n in self.board.nets]
        assert len(indices) == len(set(indices))


class TestAllegroTraces:
    """Test trace segment extraction from Allegro fixture."""

    @pytest.fixture(autouse=True)
    def parse_board(self):
        parser = AllegroParser()
        self.board = parser.parse_file(SAMPLE_ALLEGRO)

    def test_trace_count(self):
        assert len(self.board.traces) == 20

    def test_usb_dp_traces(self):
        usb_traces = [t for t in self.board.traces if t.net_name == "USB_DP"]
        assert len(usb_traces) == 2
        for t in usb_traces:
            assert t.width_mm == pytest.approx(0.15)
            assert t.layer == "F.Cu"  # TOP mapped to F.Cu

    def test_data_traces_on_top(self):
        data_traces = [t for t in self.board.traces
                       if t.net_name and t.net_name.startswith("DATA")]
        assert len(data_traces) == 4
        for t in data_traces:
            assert t.layer == "F.Cu"
            assert t.width_mm == pytest.approx(0.12)

    def test_addr_traces_on_bottom(self):
        addr_traces = [t for t in self.board.traces
                       if t.net_name and t.net_name.startswith("ADDR")]
        assert len(addr_traces) == 4
        for t in addr_traces:
            assert t.layer == "B.Cu"
            assert t.width_mm == pytest.approx(0.12)

    def test_trace_coordinates(self):
        usb_dp = [t for t in self.board.traces if t.net_name == "USB_DP"]
        first = usb_dp[0]
        assert first.x1_mm == pytest.approx(5.0)
        assert first.y1_mm == pytest.approx(41.0)
        assert first.x2_mm == pytest.approx(25.0)
        assert first.y2_mm == pytest.approx(41.0)

    def test_trace_length_calculation(self):
        usb_dp = [t for t in self.board.traces if t.net_name == "USB_DP"]
        first = usb_dp[0]
        assert first.length_mm == pytest.approx(20.0, abs=0.01)

    def test_gnd_trace_on_bottom(self):
        gnd_traces = [t for t in self.board.traces if t.net_name == "GND"]
        assert len(gnd_traces) == 1
        assert gnd_traces[0].layer == "B.Cu"
        assert gnd_traces[0].width_mm == pytest.approx(0.3)


class TestAllegroVias:
    """Test via extraction from Allegro fixture."""

    @pytest.fixture(autouse=True)
    def parse_board(self):
        parser = AllegroParser()
        self.board = parser.parse_file(SAMPLE_ALLEGRO)

    def test_via_count(self):
        assert len(self.board.vias) == 8

    def test_via_positions(self):
        positions = {(v.x_mm, v.y_mm) for v in self.board.vias}
        assert (25.0, 41.0) in positions
        assert (25.0, 39.0) in positions
        assert (50.0, 30.0) in positions

    def test_via_drill_sizes(self):
        for via in self.board.vias:
            assert via.drill_mm > 0
            assert via.drill_mm <= 0.5

    def test_via_pad_sizes(self):
        for via in self.board.vias:
            assert via.pad_diameter_mm > 0
            assert via.pad_diameter_mm >= via.drill_mm

    def test_via_layers(self):
        # Most vias go TOP to BOTTOM
        through_vias = [v for v in self.board.vias
                        if v.start_layer == "F.Cu" and v.end_layer == "B.Cu"]
        assert len(through_vias) >= 5

    def test_via_partial_span(self):
        # One via goes TOP to GND (partial span)
        partial = [v for v in self.board.vias
                   if v.end_layer == "GND.Cu"]
        assert len(partial) >= 1

    def test_via_net_assignments(self):
        usb_dp_vias = [v for v in self.board.vias if v.net_name == "USB_DP"]
        assert len(usb_dp_vias) == 1
        assert usb_dp_vias[0].x_mm == pytest.approx(25.0)
        assert usb_dp_vias[0].y_mm == pytest.approx(41.0)


class TestAllegroBoardOutline:
    """Test board outline and dimensions."""

    @pytest.fixture(autouse=True)
    def parse_board(self):
        parser = AllegroParser()
        self.board = parser.parse_file(SAMPLE_ALLEGRO)

    def test_board_outline_vertices(self):
        assert len(self.board.board_outline) == 4

    def test_board_width(self):
        assert self.board.width_mm == pytest.approx(100.0)

    def test_board_height(self):
        assert self.board.height_mm == pytest.approx(80.0)

    def test_outline_coordinates(self):
        xs = [pt[0] for pt in self.board.board_outline]
        ys = [pt[1] for pt in self.board.board_outline]
        assert min(xs) == pytest.approx(0.0)
        assert max(xs) == pytest.approx(100.0)
        assert min(ys) == pytest.approx(0.0)
        assert max(ys) == pytest.approx(80.0)


class TestAllegroDesignRules:
    """Test design rules extraction."""

    @pytest.fixture(autouse=True)
    def parse_board(self):
        parser = AllegroParser()
        self.board = parser.parse_file(SAMPLE_ALLEGRO)

    def test_design_rules_present(self):
        assert self.board.design_rules is not None

    def test_min_trace_width(self):
        assert self.board.design_rules.min_trace_width_mm == pytest.approx(0.1)

    def test_min_clearance(self):
        assert self.board.design_rules.min_clearance_mm == pytest.approx(0.1)

    def test_min_drill(self):
        assert self.board.design_rules.min_via_drill_mm == pytest.approx(0.2)


class TestAllegroStackup:
    """Test stackup extraction."""

    @pytest.fixture(autouse=True)
    def parse_board(self):
        parser = AllegroParser()
        self.board = parser.parse_file(SAMPLE_ALLEGRO)

    def test_stackup_layer_count(self):
        assert len(self.board.stackup) == 7  # 4 copper + 3 dielectric

    def test_copper_layers(self):
        copper = [s for s in self.board.stackup
                  if s.layer_type in ("signal", "plane")]
        assert len(copper) == 4

    def test_dielectric_layers(self):
        dielectric = [s for s in self.board.stackup
                      if s.layer_type == "dielectric"]
        assert len(dielectric) == 3

    def test_layer_count_from_stackup(self):
        assert self.board.layer_count == 4

    def test_layer_names(self):
        layer_names = [s.name for s in self.board.stackup
                       if s.layer_type in ("signal", "plane")]
        assert "TOP" in layer_names
        assert "GND" in layer_names
        assert "PWR" in layer_names
        assert "BOTTOM" in layer_names

    def test_prepreg_properties(self):
        prepreg = next(s for s in self.board.stackup
                       if s.name == "PREPREG1")
        assert prepreg.thickness_mm == pytest.approx(0.2)
        assert prepreg.material == "FR4"
        assert prepreg.dielectric_constant == pytest.approx(4.5)
        assert prepreg.loss_tangent == pytest.approx(0.02)


class TestAllegroErrorHandling:
    """Test parser error handling and edge cases."""

    def test_file_not_found(self):
        parser = AllegroParser()
        with pytest.raises(FileNotFoundError):
            parser.parse_file("/nonexistent/path/design.txt")

    def test_empty_content(self):
        parser = AllegroParser()
        with pytest.raises(ValueError, match="Empty file content"):
            parser.parse_content("")

    def test_whitespace_only_content(self):
        parser = AllegroParser()
        with pytest.raises(ValueError, match="Empty file content"):
            parser.parse_content("   \n\n   ")

    def test_invalid_format(self):
        parser = AllegroParser()
        with pytest.raises(ValueError, match="Not a valid Allegro"):
            parser.parse_content("This is just a random text file.")

    def test_missing_sections(self):
        """File with only $HEADER should parse without error."""
        parser = AllegroParser()
        content = "$HEADER\nUNITS = mm\n$END\n"
        result = parser.parse_content(content)
        assert result.units == "mm"
        assert len(result.components) == 0
        assert len(result.nets) == 0
        assert len(result.traces) == 0

    def test_malformed_component_line(self):
        """Malformed component lines should generate warnings, not crash."""
        parser = AllegroParser()
        content = (
            "$HEADER\nUNITS = mm\n$END\n"
            "$COMPONENTS\n"
            "BAD\n"  # Too few fields
            "U1 BGA-256 10.0 20.0 0 TOP MCU\n"
            "$END\n"
        )
        result = parser.parse_content(content)
        assert len(result.components) == 1
        assert result.components[0].reference == "U1"
        assert len(result.warnings) >= 1

    def test_malformed_trace_line(self):
        """Malformed trace lines should generate warnings, not crash."""
        parser = AllegroParser()
        content = (
            "$HEADER\nUNITS = mm\n$END\n"
            "$ROUTES\n"
            "BAD LINE\n"  # Too few fields
            "TOP 0.2 10.0 20.0 30.0 40.0 NET1\n"
            "$END\n"
        )
        result = parser.parse_content(content)
        assert len(result.traces) == 1
        assert len(result.warnings) >= 1

    def test_malformed_via_line(self):
        """Malformed via lines should generate warnings, not crash."""
        parser = AllegroParser()
        content = (
            "$HEADER\nUNITS = mm\n$END\n"
            "$VIAS\n"
            "BAD\n"
            "10.0 20.0 0.3 0.6 TOP BOTTOM NET1\n"
            "$END\n"
        )
        result = parser.parse_content(content)
        assert len(result.vias) == 1
        assert len(result.warnings) >= 1


class TestAllegroUnits:
    """Test unit conversion."""

    def test_mil_units(self):
        parser = AllegroParser()
        content = (
            "$HEADER\nUNITS = mil\n$END\n"
            "$COMPONENTS\n"
            "U1 BGA 1000.0 2000.0 0 TOP MCU\n"
            "$END\n"
        )
        result = parser.parse_content(content)
        assert result.components[0].x_mm == pytest.approx(25.4, abs=0.01)
        assert result.components[0].y_mm == pytest.approx(50.8, abs=0.01)

    def test_inch_units(self):
        parser = AllegroParser()
        content = (
            "$HEADER\nUNITS = inch\n$END\n"
            "$COMPONENTS\n"
            "U1 BGA 1.0 2.0 0 TOP MCU\n"
            "$END\n"
        )
        result = parser.parse_content(content)
        assert result.components[0].x_mm == pytest.approx(25.4, abs=0.01)
        assert result.components[0].y_mm == pytest.approx(50.8, abs=0.01)

    def test_mm_units_default(self):
        parser = AllegroParser()
        content = (
            "$HEADER\nUNITS = mm\n$END\n"
            "$COMPONENTS\n"
            "U1 BGA 25.0 50.0 0 TOP MCU\n"
            "$END\n"
        )
        result = parser.parse_content(content)
        assert result.components[0].x_mm == pytest.approx(25.0)
        assert result.components[0].y_mm == pytest.approx(50.0)


class TestAllegroLayerMapping:
    """Test Allegro layer name to standard name mapping."""

    def test_top_maps_to_fcu(self):
        assert _map_layer_name("TOP") == "F.Cu"

    def test_bottom_maps_to_bcu(self):
        assert _map_layer_name("BOTTOM") == "B.Cu"

    def test_bot_maps_to_bcu(self):
        assert _map_layer_name("BOT") == "B.Cu"

    def test_inner_layers(self):
        assert _map_layer_name("INNER1") == "In1.Cu"
        assert _map_layer_name("INNER2") == "In2.Cu"

    def test_unknown_layer_passthrough(self):
        assert _map_layer_name("CUSTOM_LAYER") == "CUSTOM_LAYER"

    def test_case_insensitive(self):
        assert _map_layer_name("top") == "F.Cu"
        assert _map_layer_name("bottom") == "B.Cu"


class TestAllegroIntegration:
    """Test Allegro parser via the parse_pcb_file integration path."""

    def test_parse_pcb_file_allegro(self):
        """parse_pcb_file should produce valid PCBDesignData from fixture."""
        result = parse_pcb_file(SAMPLE_ALLEGRO, format_hint="allegro")
        assert result.source_format == "allegro"
        assert result.board_width_mm == pytest.approx(100.0)
        assert result.board_height_mm == pytest.approx(80.0)
        assert len(result.components) == 10
        assert len(result.nets) == 15
        assert len(result.traces) == 20
        assert len(result.vias) == 8
        assert result.layer_count == 4

    def test_parse_pcb_file_design_rules(self):
        result = parse_pcb_file(SAMPLE_ALLEGRO, format_hint="allegro")
        assert result.min_trace_width_mm == pytest.approx(0.1)
        assert result.min_clearance_mm == pytest.approx(0.1)
        assert result.min_via_drill_mm == pytest.approx(0.2)

    def test_parse_pcb_file_trace_length(self):
        result = parse_pcb_file(SAMPLE_ALLEGRO, format_hint="allegro")
        assert result.total_trace_length_mm > 0

    def test_parse_pcb_file_component_layers(self):
        result = parse_pcb_file(SAMPLE_ALLEGRO, format_hint="allegro")
        for comp in result.components:
            assert comp.layer == "F.Cu"  # All components on TOP side

    def test_parse_pcb_file_stackup_layers(self):
        result = parse_pcb_file(SAMPLE_ALLEGRO, format_hint="allegro")
        assert len(result.layers) == 7
        copper_layers = result.get_copper_layers()
        assert len(copper_layers) == 4

    def test_parse_pcb_file_summary(self):
        result = parse_pcb_file(SAMPLE_ALLEGRO, format_hint="allegro")
        summary = result.to_summary()
        assert summary["format"] == "allegro"
        assert summary["components"] == 10
        assert summary["nets"] == 15
        assert summary["traces"] == 20
        assert summary["vias"] == 8


class TestAllegroFormatDetection:
    """Test format detection for Allegro files."""

    def test_detect_brd_extension(self):
        assert detect_format("design.brd") == "allegro"

    def test_detect_brd_uppercase(self):
        assert detect_format("DESIGN.BRD") == "allegro"

    def test_detect_exp_extension(self):
        assert detect_format("design.exp") == "allegro"

    def test_detect_txt_with_allegro_content(self, tmp_path):
        txt_file = tmp_path / "design.txt"
        txt_file.write_text("$HEADER\nUNITS = mm\n$END\n")
        assert detect_format(str(txt_file)) == "allegro"

    def test_detect_txt_without_allegro_content(self, tmp_path):
        txt_file = tmp_path / "readme.txt"
        txt_file.write_text("This is a plain text file.")
        assert detect_format(str(txt_file)) == "unknown"

    def test_detect_txt_with_allegro_marker(self, tmp_path):
        txt_file = tmp_path / "export.txt"
        txt_file.write_text("# Allegro ASCII Export\nSome data\n")
        assert detect_format(str(txt_file)) == "allegro"

    def test_detect_sample_fixture(self):
        assert detect_format(SAMPLE_ALLEGRO) == "allegro"

    def test_parse_pcb_file_not_found(self):
        with pytest.raises(ParseError):
            parse_pcb_file("/nonexistent/allegro.brd", format_hint="allegro")


class TestAllegroTracesSection:
    """Test that $TRACES section name also works (alternative to $ROUTES)."""

    def test_traces_section_name(self):
        parser = AllegroParser()
        content = (
            "$HEADER\nUNITS = mm\n$END\n"
            "$TRACES\n"
            "TOP 0.2 10.0 20.0 30.0 40.0 SIG1\n"
            "$END\n"
        )
        result = parser.parse_content(content)
        assert len(result.traces) == 1
        assert result.traces[0].net_name == "SIG1"
        assert result.traces[0].layer == "F.Cu"


class TestAllegroExtractionFormat:
    """Test basic extraction (.exp) format support."""

    def test_exp_minimal_parse(self):
        parser = AllegroParser()
        content = (
            "$HEADER\nUNITS = mm\nVERSION = 17.2\n$END\n"
            "$COMPONENTS\n"
            "U1 QFP-48 30.0 25.0 0 TOP IC\n"
            "$END\n"
            "$NETS\n"
            "VCC; U1.VCC\n"
            "GND; U1.GND\n"
            "$END\n"
        )
        result = parser.parse_content(content)
        assert len(result.components) == 1
        assert len(result.nets) == 2
        assert result.version == "17.2"

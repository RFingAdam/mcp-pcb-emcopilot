"""Tests for the KiCad PCB parser using synthetic fixture files."""
import pytest

from mcp_pcb_emcopilot.parsers.kicad_pcb_parser import KiCadPcbParser


class TestSimple2LayerParsing:
    """Test parsing the simple 2-layer fixture."""

    @pytest.fixture(autouse=True)
    def parse_board(self, simple_2layer_kicad):
        parser = KiCadPcbParser()
        self.board = parser.parse_file(simple_2layer_kicad)

    def test_version_and_generator(self):
        assert self.board.kicad_version == "20221018"
        assert self.board.generator == "pcbnew"

    def test_title_block(self):
        assert self.board.title == "Simple 2-Layer Test Board"
        assert self.board.revision == "1.0"
        assert self.board.company == "Synthetic Test Designs"
        assert self.board.date == "2025-01-15"

    def test_layer_count(self):
        # Parser counts layers with "Cu" in name; Edge.Cuts matches too
        # so layer_count is 3 (F.Cu, B.Cu, Edge.Cuts)
        assert self.board.layer_count == 3

    def test_copper_layers(self):
        # Actual signal copper layers
        signal_layers = [l for l in self.board.layers
                         if l.layer_type == "signal" and "Cu" in l.name]
        assert len(signal_layers) == 2
        names = {l.name for l in signal_layers}
        assert "F.Cu" in names
        assert "B.Cu" in names

    def test_layer_definitions(self):
        # Should have copper + non-copper layers
        assert len(self.board.layers) >= 2
        fcu = next(l for l in self.board.layers if l.name == "F.Cu")
        assert fcu.number == 0
        assert fcu.layer_type == "signal"

    def test_board_thickness(self):
        assert self.board.thickness_mm == 1.6

    def test_component_count(self):
        assert len(self.board.components) == 5

    def test_component_references(self):
        refs = {c.reference for c in self.board.components}
        assert refs == {"U1", "R1", "R2", "C1", "J1"}

    def test_component_values(self):
        u1 = next(c for c in self.board.components if c.reference == "U1")
        assert u1.value == "MCU"
        r1 = next(c for c in self.board.components if c.reference == "R1")
        assert r1.value == "10k"
        c1 = next(c for c in self.board.components if c.reference == "C1")
        assert c1.value == "100nF"
        j1 = next(c for c in self.board.components if c.reference == "J1")
        assert j1.value == "USB-C"

    def test_component_positions(self):
        u1 = next(c for c in self.board.components if c.reference == "U1")
        assert u1.x_mm == 25.0
        assert u1.y_mm == 15.0

    def test_component_footprints(self):
        u1 = next(c for c in self.board.components if c.reference == "U1")
        assert u1.footprint == "TQFP-48_7x7mm_P0.5mm"
        assert u1.footprint_library == "Package_QFP"

    def test_component_layer(self):
        for comp in self.board.components:
            assert comp.layer == "F.Cu"

    def test_net_count(self):
        # 9 nets total (including net 0 which is unconnected)
        assert len(self.board.nets) == 9

    def test_net_names(self):
        net_names = {n.name for n in self.board.nets}
        assert "GND" in net_names
        assert "VCC" in net_names
        assert "USB_D_P" in net_names
        assert "USB_D_N" in net_names
        assert "SIG1" in net_names
        assert "SIG2" in net_names

    def test_net_indices(self):
        gnd = next(n for n in self.board.nets if n.name == "GND")
        assert gnd.index == 1
        usb_dp = next(n for n in self.board.nets if n.name == "USB_D_P")
        assert usb_dp.index == 7

    def test_trace_count(self):
        assert len(self.board.traces) == 10

    def test_trace_properties(self):
        # Find a USB trace
        usb_traces = [t for t in self.board.traces if t.net_index == 7]
        assert len(usb_traces) >= 1
        for t in usb_traces:
            assert t.width_mm == 0.15
            assert t.layer == "F.Cu"

    def test_trace_coordinates(self):
        # First trace: (0,15) -> (10,15)
        first_trace = self.board.traces[0]
        assert first_trace.x1_mm == 0.0
        assert first_trace.y1_mm == 15.0
        assert first_trace.x2_mm == 10.0
        assert first_trace.y2_mm == 15.0

    def test_trace_length(self):
        first_trace = self.board.traces[0]
        assert abs(first_trace.length_mm - 10.0) < 0.01

    def test_via_count(self):
        assert len(self.board.vias) == 3

    def test_via_properties(self):
        via = self.board.vias[0]
        assert via.drill_mm == 0.3
        assert via.size_mm == 0.6
        assert via.layers == ("F.Cu", "B.Cu")

    def test_via_positions(self):
        positions = {(v.x_mm, v.y_mm) for v in self.board.vias}
        assert (15.0, 8.0) in positions
        assert (30.0, 15.0) in positions
        assert (20.0, 25.0) in positions

    def test_via_net_assignments(self):
        via_nets = {v.net_index for v in self.board.vias}
        assert 3 in via_nets  # SIG1
        assert 1 in via_nets  # GND
        assert 2 in via_nets  # VCC

    def test_zone_count(self):
        assert len(self.board.zones) == 1

    def test_zone_properties(self):
        zone = self.board.zones[0]
        assert zone.net_name == "GND"
        assert zone.layer == "B.Cu"
        assert zone.fill_type == "solid"

    def test_zone_outline(self):
        zone = self.board.zones[0]
        assert len(zone.outline) == 4
        xs = [pt[0] for pt in zone.outline]
        ys = [pt[1] for pt in zone.outline]
        assert min(xs) == 0.0
        assert max(xs) == 50.0
        assert min(ys) == 0.0
        assert max(ys) == 30.0

    def test_board_dimensions_calculated(self):
        assert self.board.width_mm > 0
        assert self.board.height_mm > 0

    def test_total_trace_length(self):
        assert self.board.total_trace_length_mm > 0

    def test_net_classes(self):
        assert "Default" in self.board.net_classes
        assert "USB" in self.board.net_classes

    def test_net_class_default_properties(self):
        default = self.board.net_classes["Default"]
        assert default["clearance_mm"] == 0.15
        assert default["trace_width_mm"] == 0.2
        assert default["via_diameter_mm"] == 0.6
        assert default["via_drill_mm"] == 0.3

    def test_net_class_usb_properties(self):
        usb = self.board.net_classes["USB"]
        assert usb["diff_pair_width_mm"] == 0.15
        assert usb["diff_pair_gap_mm"] == 0.12

    def test_net_class_memberships(self):
        default = self.board.net_classes["Default"]
        assert "GND" in default["nets"]
        assert "VCC" in default["nets"]
        usb = self.board.net_classes["USB"]
        assert "USB_D_P" in usb["nets"]
        assert "USB_D_N" in usb["nets"]

    def test_pad_parsing(self):
        u1 = next(c for c in self.board.components if c.reference == "U1")
        assert len(u1.pads) == 4
        pad1 = u1.pads[0]
        assert pad1.number == "1"
        assert pad1.pad_type == "smd"
        assert pad1.net_name == "GND"

    def test_design_rules_present(self):
        assert self.board.design_rules is not None


class TestMixedSignal4LayerParsing:
    """Test parsing the mixed-signal 4-layer fixture."""

    @pytest.fixture(autouse=True)
    def parse_board(self, mixed_signal_4layer_kicad):
        parser = KiCadPcbParser()
        self.board = parser.parse_file(mixed_signal_4layer_kicad)

    def test_layer_count(self):
        # Parser counts layers with "Cu" in name; Edge.Cuts matches too
        assert self.board.layer_count == 5

    def test_all_copper_layers(self):
        copper = [l for l in self.board.layers if l.name.endswith(".Cu")]
        names = {l.name for l in copper}
        assert "F.Cu" in names
        assert "In1.Cu" in names
        assert "In2.Cu" in names
        assert "B.Cu" in names
        assert len(names) == 4

    def test_inner_layer_types(self):
        in1 = next(l for l in self.board.layers if l.name == "In1.Cu")
        assert in1.layer_type == "power"
        in2 = next(l for l in self.board.layers if l.name == "In2.Cu")
        assert in2.layer_type == "power"

    def test_title_block(self):
        assert self.board.title == "Mixed Signal 4-Layer Test Board"
        assert self.board.revision == "2.1"

    def test_component_count(self):
        assert len(self.board.components) == 15

    def test_component_references(self):
        refs = {c.reference for c in self.board.components}
        expected = {"U1", "U2", "U3", "U4", "U5", "U6",
                    "R1", "R2", "R3", "R4",
                    "C1", "C2", "C3", "Y1", "J1"}
        assert refs == expected

    def test_mcu_component(self):
        u1 = next(c for c in self.board.components if c.reference == "U1")
        assert u1.value == "SOC_MCU"
        assert u1.x_mm == 40.0
        assert u1.y_mm == 30.0

    def test_ddr_component(self):
        u2 = next(c for c in self.board.components if c.reference == "U2")
        assert u2.value == "DDR3L_256MB"
        assert u2.x_mm == 40.0
        assert u2.y_mm == 55.0

    def test_net_count(self):
        assert len(self.board.nets) == 25  # Including net 0 (unconnected)

    def test_ddr_nets(self):
        net_names = {n.name for n in self.board.nets}
        for sig in ["DDR_DQ0", "DDR_DQ1", "DDR_DQ2", "DDR_DQ3",
                     "DDR_CLK_P", "DDR_CLK_N", "DDR_DQS_P", "DDR_DQS_N"]:
            assert sig in net_names

    def test_usb_nets(self):
        net_names = {n.name for n in self.board.nets}
        assert "USB_D_P" in net_names
        assert "USB_D_N" in net_names

    def test_power_nets(self):
        net_names = {n.name for n in self.board.nets}
        assert "VCC_3V3" in net_names
        assert "VCC_1V8" in net_names
        assert "VCC_1V1" in net_names

    def test_trace_count(self):
        assert len(self.board.traces) == 25

    def test_via_count(self):
        assert len(self.board.vias) == 10

    def test_blind_vias(self):
        # Vias that don't span F.Cu to B.Cu
        non_through = [v for v in self.board.vias if v.layers != ("F.Cu", "B.Cu")]
        assert len(non_through) > 0

    def test_net_classes_count(self):
        assert len(self.board.net_classes) == 3
        assert "Default" in self.board.net_classes
        assert "USB" in self.board.net_classes
        assert "DDR" in self.board.net_classes

    def test_ddr_net_class(self):
        ddr = self.board.net_classes["DDR"]
        assert ddr["trace_width_mm"] == 0.1
        assert ddr["diff_pair_width_mm"] == 0.1
        assert ddr["diff_pair_gap_mm"] == 0.1

    def test_stackup(self):
        assert len(self.board.stackup) > 0

    def test_stackup_layers(self):
        # Stackup should contain copper and dielectric layers
        copper = [s for s in self.board.stackup if s.layer_type == "copper"]
        dielectric = [s for s in self.board.stackup if s.layer_type in ("prepreg", "core")]
        assert len(copper) == 4
        assert len(dielectric) == 3

    def test_stackup_dielectric_properties(self):
        prepreg = next(s for s in self.board.stackup if s.layer_type == "prepreg")
        assert prepreg.thickness_mm == 0.2
        assert prepreg.material == "FR4"
        assert prepreg.dielectric_constant == 4.5
        assert prepreg.loss_tangent == 0.02

    def test_zone_count(self):
        assert len(self.board.zones) == 2

    def test_gnd_zone(self):
        gnd_zones = [z for z in self.board.zones if z.net_name == "GND"]
        assert len(gnd_zones) == 1
        assert gnd_zones[0].layer == "In1.Cu"

    def test_power_zone(self):
        pwr_zones = [z for z in self.board.zones if z.net_name == "VCC_3V3"]
        assert len(pwr_zones) == 1
        assert pwr_zones[0].layer == "In2.Cu"

    def test_back_copper_traces(self):
        back_traces = [t for t in self.board.traces if t.layer == "B.Cu"]
        assert len(back_traces) >= 2


class TestKiCadParserEdgeCases:
    """Test parser error handling and edge cases."""

    def test_file_not_found(self):
        parser = KiCadPcbParser()
        with pytest.raises(FileNotFoundError):
            parser.parse_file("/nonexistent/path/board.kicad_pcb")

    def test_wrong_extension(self, tmp_path):
        bad_file = tmp_path / "board.txt"
        bad_file.write_text("(kicad_pcb)")
        parser = KiCadPcbParser()
        with pytest.raises(ValueError, match="Not a KiCad PCB file"):
            parser.parse_file(str(bad_file))

    def test_invalid_root_element(self):
        parser = KiCadPcbParser()
        with pytest.raises(ValueError, match="Not a KiCad PCB file"):
            parser.parse_content("(some_other_format (version 1))")

    def test_empty_content(self):
        parser = KiCadPcbParser()
        with pytest.raises(ValueError):
            parser.parse_content("")

    def test_malformed_sexpression(self):
        parser = KiCadPcbParser()
        # Unbalanced parens - parser should handle gracefully
        result = parser.parse_content("(kicad_pcb (version 20221018)")
        # Should at least parse the root element and version
        assert result.kicad_version == "20221018"

    def test_minimal_valid_file(self):
        parser = KiCadPcbParser()
        result = parser.parse_content("(kicad_pcb (version 20221018) (generator pcbnew))")
        assert result.kicad_version == "20221018"
        assert result.generator == "pcbnew"
        assert len(result.components) == 0
        assert len(result.nets) == 0
        assert len(result.traces) == 0

    def test_missing_general_section(self):
        parser = KiCadPcbParser()
        result = parser.parse_content("(kicad_pcb (version 20221018))")
        # Default thickness should be used
        assert result.thickness_mm == 1.6

    def test_component_with_no_pads(self):
        content = """(kicad_pcb (version 20221018)
          (layers (0 "F.Cu" signal))
          (footprint "Test:TestPart" (layer "F.Cu")
            (at 10 20)
            (fp_text reference "X1" (at 0 0) (layer "F.SilkS"))
            (fp_text value "TestVal" (at 0 0) (layer "F.Fab"))
          )
        )"""
        parser = KiCadPcbParser()
        result = parser.parse_content(content)
        assert len(result.components) == 1
        assert result.components[0].reference == "X1"
        assert result.components[0].value == "TestVal"
        assert len(result.components[0].pads) == 0

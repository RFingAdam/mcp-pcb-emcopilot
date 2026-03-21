"""Tests for the IPC-2581 XML parser using synthetic fixture files."""
import pytest

from mcp_pcb_emcopilot.parsers.ipc2581_parser import IPC2581Parser


class TestIPC2581Parsing:
    """Test parsing the sample IPC-2581 fixture."""

    @pytest.fixture(autouse=True)
    def parse_design(self, sample_ipc2581):
        parser = IPC2581Parser()
        self.data = parser.parse(sample_ipc2581)

    def test_version(self):
        assert self.data.version == "C"

    def test_board_name(self):
        assert self.data.board_name == "TestBoard"

    def test_board_dimensions(self):
        assert abs(self.data.width_mm - 80.0) < 0.1
        assert abs(self.data.height_mm - 60.0) < 0.1

    def test_ecad_name(self):
        assert self.data.properties.get("ecad_name") == "TestECAD"

    def test_units(self):
        assert self.data.properties.get("units") == "MM"

    def test_layer_count(self):
        # Stackup has 4 copper layers: TOP, GND, PWR, BOTTOM
        assert self.data.layer_count == 4

    def test_stackup_layers(self):
        assert len(self.data.stackup) == 7  # 4 copper + 3 dielectric

    def test_stackup_copper_layers(self):
        copper = [s for s in self.data.stackup if s.layer_type in ("SIGNAL", "PLANE")]
        assert len(copper) == 4

    def test_stackup_dielectric_layers(self):
        dielectric = [s for s in self.data.stackup if s.layer_type == "DIELECTRIC"]
        assert len(dielectric) == 3

    def test_stackup_properties(self):
        top_layer = next(s for s in self.data.stackup if s.name == "TOP")
        assert top_layer.layer_type == "SIGNAL"
        assert abs(top_layer.thickness_mm - 0.035) < 0.001
        assert top_layer.material == "Copper"

    def test_stackup_dielectric_properties(self):
        dielectric = next(s for s in self.data.stackup if s.name == "DIELECTRIC1")
        assert dielectric.layer_type == "DIELECTRIC"
        assert abs(dielectric.thickness_mm - 0.2) < 0.001
        assert dielectric.material == "FR4"
        assert abs(dielectric.dielectric_constant - 4.5) < 0.1

    def test_component_count(self):
        assert len(self.data.components) == 8

    def test_component_references(self):
        refs = {c.reference for c in self.data.components}
        expected = {"U1", "U3", "U4", "C1", "C2", "J1", "R1", "R2"}
        assert refs == expected

    def test_component_positions(self):
        u1 = next(c for c in self.data.components if c.reference == "U1")
        assert abs(u1.x_mm - 40.0) < 0.1
        assert abs(u1.y_mm - 30.0) < 0.1

    def test_component_package_ref(self):
        u1 = next(c for c in self.data.components if c.reference == "U1")
        assert u1.package_ref == "BGA-256"

    def test_component_layer(self):
        u1 = next(c for c in self.data.components if c.reference == "U1")
        assert u1.layer == "TOP"
        r2 = next(c for c in self.data.components if c.reference == "R2")
        assert r2.layer == "BOTTOM"

    def test_component_mount_type(self):
        u1 = next(c for c in self.data.components if c.reference == "U1")
        assert u1.mount_type == "SMD"

    def test_net_count(self):
        assert len(self.data.nets) == 5

    def test_net_names(self):
        net_names = {n.name for n in self.data.nets}
        expected = {"GND", "VCC_3V3", "USB_D_P", "USB_D_N", "SPI_CLK"}
        assert net_names == expected

    def test_net_pins(self):
        gnd = next(n for n in self.data.nets if n.name == "GND")
        assert len(gnd.pins) == 3
        # Check pin references
        comp_refs = {p["component"] for p in gnd.pins}
        assert "U1" in comp_refs
        assert "C1" in comp_refs

    def test_trace_count(self):
        assert len(self.data.traces) == 6

    def test_trace_properties(self):
        usb_traces = [t for t in self.data.traces if t.net_name == "USB_D_P"]
        assert len(usb_traces) >= 1
        for t in usb_traces:
            assert abs(t.width_mm - 0.15) < 0.001

    def test_trace_layers(self):
        top_traces = [t for t in self.data.traces if t.layer == "TOP"]
        bottom_traces = [t for t in self.data.traces if t.layer == "BOTTOM"]
        assert len(top_traces) == 5
        assert len(bottom_traces) == 1

    def test_via_count(self):
        assert len(self.data.vias) == 3

    def test_via_drill(self):
        for via in self.data.vias:
            assert abs(via.drill_mm - 0.3) < 0.001

    def test_via_positions(self):
        positions = {(via.x_mm, via.y_mm) for via in self.data.vias}
        assert (15.0, 15.0) in positions
        assert (35.0, 28.0) in positions
        assert (45.0, 28.0) in positions

    def test_via_nets(self):
        via_nets = {v.net_name for v in self.data.vias}
        assert "USB_D_P" in via_nets
        assert "GND" in via_nets

    def test_design_rules(self):
        assert len(self.data.design_rules) == 3

    def test_design_rule_values(self):
        rule_names = {r.name for r in self.data.design_rules}
        assert "min_trace_width" in rule_names
        assert "min_clearance" in rule_names
        assert "min_drill" in rule_names

        width_rule = next(r for r in self.data.design_rules if r.name == "min_trace_width")
        assert abs(width_rule.value - 0.1) < 0.001

    def test_total_trace_length(self):
        assert self.data.total_trace_length_mm > 0

    def test_via_count_stat(self):
        assert self.data.via_count == 3

    def test_packages_parsed(self):
        # Parser stores packages internally; verify indirectly through component data
        u1 = next(c for c in self.data.components if c.reference == "U1")
        assert u1.package_ref == "BGA-256"

    def test_pad_stacks_parsed(self):
        # Vias should use pad stack data for drill sizes
        for via in self.data.vias:
            assert via.drill_mm > 0


class TestIPC2581EdgeCases:
    """Test IPC-2581 parser error handling."""

    def test_file_not_found(self):
        parser = IPC2581Parser()
        with pytest.raises(FileNotFoundError):
            parser.parse("/nonexistent/design.xml")

    def test_invalid_xml(self, tmp_path):
        bad_xml = tmp_path / "bad.xml"
        bad_xml.write_text("This is not XML at all <><><<>")
        parser = IPC2581Parser()
        with pytest.raises(ValueError, match="IPC-2581"):
            parser.parse(str(bad_xml))

    def test_empty_xml(self, tmp_path):
        empty_xml = tmp_path / "empty.xml"
        empty_xml.write_text('<?xml version="1.0"?><IPC-2581 revision="A"/>')
        parser = IPC2581Parser()
        data = parser.parse(str(empty_xml))
        assert data.version == "A"
        assert len(data.components) == 0
        assert len(data.nets) == 0

    def test_xml_missing_content_section(self, tmp_path):
        minimal = tmp_path / "minimal.xml"
        minimal.write_text(
            '<?xml version="1.0"?>'
            '<IPC-2581 revision="B">'
            '<Net name="GND"/>'
            '</IPC-2581>'
        )
        parser = IPC2581Parser()
        data = parser.parse(str(minimal))
        assert data.version == "B"
        assert len(data.nets) == 1
        assert data.nets[0].name == "GND"

    def test_xml_with_unknown_namespace(self, tmp_path):
        ns_xml = tmp_path / "ns.xml"
        ns_xml.write_text(
            '<?xml version="1.0"?>'
            '<IPC-2581 xmlns="http://custom.namespace/2581" revision="C">'
            '<Net name="VCC"/>'
            '</IPC-2581>'
        )
        parser = IPC2581Parser()
        data = parser.parse(str(ns_xml))
        assert data.version == "C"

    def test_component_without_location(self, tmp_path):
        no_loc = tmp_path / "no_location.xml"
        no_loc.write_text(
            '<?xml version="1.0"?>'
            '<IPC-2581 revision="C">'
            '<Component refDes="X1" packageRef="PKG1" layerRef="TOP"/>'
            '</IPC-2581>'
        )
        parser = IPC2581Parser()
        data = parser.parse(str(no_loc))
        assert len(data.components) == 1
        assert data.components[0].reference == "X1"
        assert data.components[0].x_mm == 0.0
        assert data.components[0].y_mm == 0.0

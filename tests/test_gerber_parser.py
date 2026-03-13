"""Tests for the Gerber RS-274X parser using synthetic fixture files."""
import pytest

from mcp_pcb_emcopilot.parsers.gerber_parser import ApertureType, GerberParser


class TestGerberParsing:
    """Test parsing the sample Gerber fixture."""

    @pytest.fixture(autouse=True)
    def parse_gerber(self, sample_gerber):
        parser = GerberParser()
        self.data = parser.parse(sample_gerber)

    def test_format_detected(self):
        assert self.data.format_spec == "RS-274X"

    def test_units(self):
        assert self.data.units == "mm"

    def test_coordinate_format(self):
        assert self.data.integer_digits == 3
        assert self.data.decimal_digits == 4

    def test_absolute_coordinates(self):
        assert self.data.absolute_coords is True

    def test_aperture_count(self):
        # 6 apertures: D10 through D15
        assert len(self.data.apertures) == 6

    def test_circle_aperture(self):
        # D10 is a 0.15mm circle
        ap10 = self.data.apertures[10]
        assert ap10.aperture_type == ApertureType.CIRCLE
        assert abs(ap10.width_mm - 0.15) < 0.001

    def test_circle_aperture_d11(self):
        ap11 = self.data.apertures[11]
        assert ap11.aperture_type == ApertureType.CIRCLE
        assert abs(ap11.width_mm - 0.20) < 0.001

    def test_circle_aperture_d12(self):
        ap12 = self.data.apertures[12]
        assert ap12.aperture_type == ApertureType.CIRCLE
        assert abs(ap12.width_mm - 0.25) < 0.001

    def test_rectangle_aperture(self):
        # D13 is a 0.6x0.2mm rectangle
        ap13 = self.data.apertures[13]
        assert ap13.aperture_type == ApertureType.RECTANGLE
        assert abs(ap13.width_mm - 0.60) < 0.001
        assert abs(ap13.height_mm - 0.20) < 0.001

    def test_large_circle_aperture(self):
        # D14 is a 0.6mm circle (flash pad)
        ap14 = self.data.apertures[14]
        assert ap14.aperture_type == ApertureType.CIRCLE
        assert abs(ap14.width_mm - 0.60) < 0.001

    def test_square_aperture(self):
        # D15 is a 1.0x1.0mm rectangle
        ap15 = self.data.apertures[15]
        assert ap15.aperture_type == ApertureType.RECTANGLE
        assert abs(ap15.width_mm - 1.0) < 0.001
        assert abs(ap15.height_mm - 1.0) < 0.001

    def test_trace_count(self):
        # 6 draw commands: 4 with D10, 1 with D11, 1 with D12 = 6 trace segments
        # But some D02 (move) commands don't generate traces, and
        # D11 has 2 draws, D12 has 1 draw
        assert len(self.data.traces) >= 5

    def test_trace_width(self):
        # At least some traces should have D10 aperture width (0.15mm)
        d10_traces = [t for t in self.data.traces if t.aperture_code == 10]
        assert len(d10_traces) >= 2
        for t in d10_traces:
            assert abs(t.width_mm - 0.15) < 0.001

    def test_pad_count(self):
        # 5 flash commands: 3 with D14, 2 with D15
        assert len(self.data.pads) == 5

    def test_pad_shapes(self):
        d14_pads = [p for p in self.data.pads if p.aperture_code == 14]
        d15_pads = [p for p in self.data.pads if p.aperture_code == 15]
        assert len(d14_pads) == 3
        assert len(d15_pads) == 2

    def test_bounding_box(self):
        # Verify bounding box is computed
        assert self.data.width_mm > 0
        assert self.data.height_mm > 0

    def test_x2_file_function(self):
        assert self.data.attributes.file_function is not None
        assert "Copper" in self.data.attributes.file_function

    def test_x2_file_polarity(self):
        assert self.data.attributes.file_polarity == "Positive"

    def test_x2_generation_software(self):
        assert self.data.attributes.generation_software is not None
        assert "SyntheticTestGen" in self.data.attributes.generation_software

    def test_x2_project_id(self):
        assert self.data.attributes.project_id is not None
        assert "TestBoard" in self.data.attributes.project_id

    def test_layer_type_inferred(self):
        # The file function says Copper,L1,Top
        assert self.data.layer_type == "copper"
        assert self.data.layer_side == "top"

    def test_statistics(self):
        assert self.data.trace_count >= 5
        assert self.data.pad_count == 5
        assert self.data.total_trace_length_mm > 0


class TestGerberEdgeCases:
    """Test Gerber parser error handling."""

    def test_file_not_found(self):
        parser = GerberParser()
        with pytest.raises(FileNotFoundError):
            parser.parse("/nonexistent/file.gbr")

    def test_empty_file(self, tmp_path):
        empty = tmp_path / "empty.gbr"
        empty.write_text("")
        parser = GerberParser()
        data = parser.parse(str(empty))
        # Should parse without crashing, with empty results
        assert len(data.traces) == 0
        assert len(data.pads) == 0

    def test_only_header(self, tmp_path):
        header_only = tmp_path / "header.gbr"
        header_only.write_text(
            "%FSLAX34Y34*%\n%MOMM*%\n%ADD10C,0.100*%\nM02*\n"
        )
        parser = GerberParser()
        data = parser.parse(str(header_only))
        assert data.format_spec == "RS-274X"
        assert data.units == "mm"
        assert 10 in data.apertures
        assert len(data.traces) == 0

    def test_invalid_aperture_definition(self, tmp_path):
        bad_gerber = tmp_path / "bad_aperture.gbr"
        bad_gerber.write_text(
            "%FSLAX34Y34*%\n%MOMM*%\n%ADD10Z,0.100*%\nM02*\n"
        )
        parser = GerberParser()
        data = parser.parse(str(bad_gerber))
        # Parser should handle gracefully, aperture may or may not be in the dict
        # The key thing is it doesn't crash
        assert data.format_spec == "RS-274X"

    def test_inch_units(self, tmp_path):
        inch_gerber = tmp_path / "inch.gbr"
        inch_gerber.write_text(
            "%FSLAX25Y25*%\n%MOIN*%\n%ADD10C,0.010*%\n"
            "D10*\n"
            "X0Y0D02*\n"
            "X100000Y0D01*\n"
            "M02*\n"
        )
        parser = GerberParser()
        data = parser.parse(str(inch_gerber))
        assert data.units == "inch"
        # Aperture diameter should be converted to mm (0.010 inch = 0.254 mm)
        assert 10 in data.apertures
        assert abs(data.apertures[10].width_mm - 0.254) < 0.01

    def test_rs274d_detection(self, tmp_path):
        old_gerber = tmp_path / "old.gbr"
        old_gerber.write_text("D10*\nX0Y0D02*\nX10000Y10000D01*\nM02*\n")
        parser = GerberParser()
        data = parser.parse(str(old_gerber))
        assert data.format_spec == "RS-274D"

"""Tests for IBIS model parser (Issue #23).

Covers:
- Engineering notation parsing
- Component info extraction
- Pin list parsing
- Model I-V curve parsing
- Waveform data extraction
- Triplet (typ/min/max) handling
- Timing analysis from IBIS data
- Error cases and edge conditions
- MCP tool dispatch for IBIS tools
"""
from __future__ import annotations

import json
import math
import os
import sys

import pytest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
SAMPLE_IBS = os.path.join(FIXTURES_DIR, 'sample_io.ibs')


# =============================================================================
# Engineering Notation Tests
# =============================================================================

class TestEngineeringNotation:
    """Tests for parse_eng_notation()."""

    def test_nano(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        assert parse_eng_notation("1.0n") == pytest.approx(1e-9)

    def test_nano_with_unit(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        assert parse_eng_notation("1.0nH") == pytest.approx(1e-9)

    def test_pico(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        assert parse_eng_notation("5.0pF") == pytest.approx(5e-12)

    def test_milli(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        assert parse_eng_notation("50.0mA") == pytest.approx(0.05)

    def test_micro(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        assert parse_eng_notation("2.5uF") == pytest.approx(2.5e-6)

    def test_kilo(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        assert parse_eng_notation("4.7k") == pytest.approx(4700.0)

    def test_mega(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        assert parse_eng_notation("10M") == pytest.approx(10e6)

    def test_giga(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        assert parse_eng_notation("2.4G") == pytest.approx(2.4e9)

    def test_plain_float(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        assert parse_eng_notation("0.1") == pytest.approx(0.1)

    def test_plain_integer(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        assert parse_eng_notation("50") == pytest.approx(50.0)

    def test_negative_value(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        assert parse_eng_notation("-3.3V") == pytest.approx(-3.3)

    def test_negative_with_suffix(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        assert parse_eng_notation("-50.0mA") == pytest.approx(-0.05)

    def test_scientific_notation(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        assert parse_eng_notation("1.5e-9") == pytest.approx(1.5e-9)

    def test_zero(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        assert parse_eng_notation("0") == pytest.approx(0.0)

    def test_zero_with_unit(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        assert parse_eng_notation("0.0A") == pytest.approx(0.0)

    def test_empty_raises(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        with pytest.raises(ValueError):
            parse_eng_notation("")

    def test_invalid_raises(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import parse_eng_notation
        with pytest.raises(ValueError):
            parse_eng_notation("abc")


# =============================================================================
# IBIS File Parsing Tests
# =============================================================================

class TestIBISParser:
    """Tests for IBISParser."""

    def _load_sample(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import IBISParser
        parser = IBISParser()
        return parser.parse_file(SAMPLE_IBS)

    def test_parse_file_exists(self):
        """Parsing the sample file should succeed."""
        model = self._load_sample()
        assert model is not None

    def test_ibis_version(self):
        model = self._load_sample()
        assert model.ibis_version == "5.0"

    def test_component_name(self):
        model = self._load_sample()
        assert model.component_name == "SAMPLE_IC_3V3"

    def test_manufacturer(self):
        model = self._load_sample()
        assert model.manufacturer == "TestSemiconductor Inc."

    def test_package_rlc(self):
        model = self._load_sample()
        assert "R_PKG" in model.package_rlc
        assert "L_PKG" in model.package_rlc
        assert "C_PKG" in model.package_rlc

        r_pkg = model.package_rlc["R_PKG"]
        assert r_pkg["typ"] == pytest.approx(0.10)
        assert r_pkg["min"] == pytest.approx(0.05)
        assert r_pkg["max"] == pytest.approx(0.15)

    def test_package_lpkg_nano(self):
        model = self._load_sample()
        l_pkg = model.package_rlc["L_PKG"]
        assert l_pkg["typ"] == pytest.approx(1e-9)
        assert l_pkg["min"] == pytest.approx(0.5e-9)
        assert l_pkg["max"] == pytest.approx(1.5e-9)

    def test_package_cpkg_pico(self):
        model = self._load_sample()
        c_pkg = model.package_rlc["C_PKG"]
        assert c_pkg["typ"] == pytest.approx(0.5e-12)

    def test_pin_count(self):
        model = self._load_sample()
        assert len(model.pins) == 6

    def test_pin_data(self):
        model = self._load_sample()
        pin3 = model.get_pin_by_number("3")
        assert pin3 is not None
        assert pin3["signal"] == "DATA0"
        assert pin3["model_name"] == "IO_3V3"

    def test_pin_rlc(self):
        model = self._load_sample()
        pin3 = model.get_pin_by_number("3")
        assert pin3 is not None
        assert pin3["R_pin"] == pytest.approx(0.1)
        assert pin3["L_pin"] == pytest.approx(1e-9)
        assert pin3["C_pin"] == pytest.approx(0.5e-12)

    def test_power_pin(self):
        model = self._load_sample()
        pin1 = model.get_pin_by_number("1")
        assert pin1 is not None
        assert pin1["signal"] == "VCC"
        assert pin1["model_name"] == "POWER"

    def test_model_count(self):
        model = self._load_sample()
        assert len(model.models) == 2

    def test_model_names(self):
        model = self._load_sample()
        names = model.model_names()
        assert "IO_3V3" in names
        assert "IO_1V8" in names

    def test_model_type(self):
        model = self._load_sample()
        io_3v3 = model.models["IO_3V3"]
        assert io_3v3["model_type"] == "i/o"

    def test_model_type_output(self):
        model = self._load_sample()
        io_1v8 = model.models["IO_1V8"]
        assert io_1v8["model_type"] == "output"

    def test_vinl(self):
        model = self._load_sample()
        io_3v3 = model.models["IO_3V3"]
        assert io_3v3["vinl"] == pytest.approx(0.8)

    def test_vinh(self):
        model = self._load_sample()
        io_3v3 = model.models["IO_3V3"]
        assert io_3v3["vinh"] == pytest.approx(2.0)

    def test_vmeas(self):
        model = self._load_sample()
        io_3v3 = model.models["IO_3V3"]
        assert io_3v3["vmeas"] == pytest.approx(1.5)

    def test_c_comp(self):
        model = self._load_sample()
        io_3v3 = model.models["IO_3V3"]
        c_comp = io_3v3["c_comp"]
        assert c_comp["typ"] == pytest.approx(3e-12)
        assert c_comp["min"] == pytest.approx(2e-12)
        assert c_comp["max"] == pytest.approx(4e-12)

    def test_pullup_data(self):
        model = self._load_sample()
        io_3v3 = model.models["IO_3V3"]
        pullup = io_3v3["pullup"]
        assert len(pullup) >= 5
        # Check first point
        assert pullup[0]["voltage"] == pytest.approx(-3.3)
        assert pullup[0]["typ"] == pytest.approx(0.1)  # 100mA

    def test_pulldown_data(self):
        model = self._load_sample()
        io_3v3 = model.models["IO_3V3"]
        pulldown = io_3v3["pulldown"]
        assert len(pulldown) >= 5

    def test_pulldown_zero_crossing(self):
        model = self._load_sample()
        io_3v3 = model.models["IO_3V3"]
        pulldown = io_3v3["pulldown"]
        # Find 0V point
        zero_point = [p for p in pulldown if abs(p["voltage"]) < 0.01]
        assert len(zero_point) >= 1
        assert zero_point[0]["typ"] == pytest.approx(0.0)

    def test_rising_waveform(self):
        model = self._load_sample()
        io_3v3 = model.models["IO_3V3"]
        rising = io_3v3["rising_waveform"]
        assert len(rising) >= 1
        wf = rising[0]
        assert wf["r_fixture"] == pytest.approx(50.0)
        assert wf["v_fixture"] == pytest.approx(3.3)
        assert len(wf["data"]) >= 5

    def test_rising_waveform_data_points(self):
        model = self._load_sample()
        io_3v3 = model.models["IO_3V3"]
        wf = io_3v3["rising_waveform"][0]
        # First point should be at time=0, voltage=0
        assert wf["data"][0]["time"] == pytest.approx(0.0)
        assert wf["data"][0]["typ"] == pytest.approx(0.0)
        # Last point should be at full voltage
        assert wf["data"][-1]["typ"] == pytest.approx(3.3)

    def test_falling_waveform(self):
        model = self._load_sample()
        io_3v3 = model.models["IO_3V3"]
        falling = io_3v3["falling_waveform"]
        assert len(falling) >= 1
        wf = falling[0]
        assert len(wf["data"]) >= 5
        # First point should be at full voltage
        assert wf["data"][0]["typ"] == pytest.approx(3.3)
        # Last point should be at 0V
        assert wf["data"][-1]["typ"] == pytest.approx(0.0)

    def test_second_model_1v8(self):
        model = self._load_sample()
        io_1v8 = model.models["IO_1V8"]
        assert io_1v8["vinl"] == pytest.approx(0.5)
        assert io_1v8["vinh"] == pytest.approx(1.17)
        assert io_1v8["vmeas"] == pytest.approx(0.9)

    def test_second_model_waveform(self):
        model = self._load_sample()
        io_1v8 = model.models["IO_1V8"]
        rising = io_1v8["rising_waveform"]
        assert len(rising) >= 1
        assert rising[0]["v_fixture"] == pytest.approx(1.8)

    def test_get_model_case_insensitive(self):
        model = self._load_sample()
        result = model.get_model("io_3v3")
        assert result is not None
        assert result["model_type"] == "i/o"

    def test_get_model_nonexistent(self):
        model = self._load_sample()
        result = model.get_model("NONEXISTENT")
        assert result is None

    def test_to_dict(self):
        model = self._load_sample()
        d = model.to_dict()
        assert d["component_name"] == "SAMPLE_IC_3V3"
        assert d["pin_count"] == 6
        assert d["model_count"] == 2
        assert "IO_3V3" in d["model_names"]

    def test_file_not_found(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import IBISParser
        parser = IBISParser()
        with pytest.raises(FileNotFoundError):
            parser.parse_file("/nonexistent/file.ibs")


# =============================================================================
# Triplet Parsing Tests
# =============================================================================

class TestTripletParsing:
    """Tests for typ/min/max triplet parsing."""

    def test_full_triplet(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import _parse_triplet
        result = _parse_triplet(["1.0n", "0.5n", "1.5n"])
        assert result["typ"] == pytest.approx(1e-9)
        assert result["min"] == pytest.approx(0.5e-9)
        assert result["max"] == pytest.approx(1.5e-9)

    def test_single_value(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import _parse_triplet
        result = _parse_triplet(["50"])
        assert result["typ"] == pytest.approx(50.0)
        assert "min" not in result
        assert "max" not in result

    def test_two_values(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import _parse_triplet
        result = _parse_triplet(["1.0", "0.5"])
        assert result["typ"] == pytest.approx(1.0)
        assert result["min"] == pytest.approx(0.5)


# =============================================================================
# IBIS Timing Analysis Tests
# =============================================================================

class TestIBISTimingAnalysis:
    """Tests for analyze_ibis_timing()."""

    def _get_model_data(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import IBISParser
        parser = IBISParser()
        model = parser.parse_file(SAMPLE_IBS)
        return model.models["IO_3V3"]

    def test_timing_analysis_basic(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import analyze_ibis_timing
        model_data = self._get_model_data()
        result = analyze_ibis_timing(model_data, data_rate_gbps=1.0, trace_length_mm=50.0)
        assert result["rise_time_ps"] > 0
        assert result["fall_time_ps"] > 0
        assert result["unit_interval_ps"] > 0

    def test_timing_analysis_eye_height(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import analyze_ibis_timing
        model_data = self._get_model_data()
        result = analyze_ibis_timing(model_data, data_rate_gbps=1.0, trace_length_mm=50.0)
        assert result["eye_height_mv"] > 0

    def test_timing_analysis_eye_width(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import analyze_ibis_timing
        model_data = self._get_model_data()
        result = analyze_ibis_timing(model_data, data_rate_gbps=1.0, trace_length_mm=50.0)
        assert result["eye_width_ps"] > 0

    def test_timing_analysis_high_speed_degrades(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import analyze_ibis_timing
        model_data = self._get_model_data()
        slow = analyze_ibis_timing(model_data, data_rate_gbps=1.0, trace_length_mm=50.0)
        fast = analyze_ibis_timing(model_data, data_rate_gbps=10.0, trace_length_mm=50.0)
        # Higher data rate should have smaller or equal eye width
        assert fast["eye_width_ps"] <= slow["eye_width_ps"]

    def test_timing_analysis_longer_trace_degrades(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import analyze_ibis_timing
        model_data = self._get_model_data()
        short = analyze_ibis_timing(model_data, data_rate_gbps=5.0, trace_length_mm=20.0)
        long_ = analyze_ibis_timing(model_data, data_rate_gbps=5.0, trace_length_mm=200.0)
        # Longer trace should have lower eye height
        assert long_["eye_height_mv"] <= short["eye_height_mv"]

    def test_timing_analysis_pass_fail(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import analyze_ibis_timing
        model_data = self._get_model_data()
        result = analyze_ibis_timing(model_data, data_rate_gbps=1.0, trace_length_mm=50.0)
        assert result["pass_fail"] in ("PASS", "FAIL")

    def test_timing_analysis_model_type(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import analyze_ibis_timing
        model_data = self._get_model_data()
        result = analyze_ibis_timing(model_data, data_rate_gbps=1.0, trace_length_mm=50.0)
        assert result["model_type"] == "i/o"


# =============================================================================
# String Parsing Edge Cases
# =============================================================================

class TestIBISStringParsing:
    """Tests for parsing IBIS content from strings."""

    def test_minimal_ibis(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import IBISParser
        content = """[IBIS Ver] 3.0
[Component] MINIMAL_IC
[Manufacturer] TestMfg
[End]
"""
        parser = IBISParser()
        model = parser.parse_string(content)
        assert model.ibis_version == "3.0"
        assert model.component_name == "MINIMAL_IC"
        assert model.manufacturer == "TestMfg"

    def test_empty_model(self):
        from mcp_pcb_emcopilot.parsers.ibis_parser import IBISParser
        content = """[IBIS Ver] 4.0
[Component] TEST
[Model] EMPTY_MODEL
Model_type Input
[End]
"""
        parser = IBISParser()
        model = parser.parse_string(content)
        assert "EMPTY_MODEL" in model.models
        assert model.models["EMPTY_MODEL"]["model_type"] == "input"

    def test_comment_handling(self):
        """Lines with | comments should be handled."""
        from mcp_pcb_emcopilot.parsers.ibis_parser import IBISParser
        content = """[IBIS Ver] 5.0
[Component] COMMENTED | this is a comment
[Manufacturer] TestMfg
[End]
"""
        parser = IBISParser()
        model = parser.parse_string(content)
        assert model.component_name == "COMMENTED"

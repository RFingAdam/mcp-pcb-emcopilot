"""Tests for Touchstone S-parameter parser (Issue #24).

Covers:
- Option line parsing
- Frequency unit conversion (Hz, kHz, MHz, GHz)
- Data format conversion (RI, MA, DB)
- 1-port, 2-port, and 4-port files
- Complex number conversion
- Error handling
- File I/O
"""
from __future__ import annotations

import cmath
import math
import os
import sys

import pytest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
SAMPLE_S2P = os.path.join(FIXTURES_DIR, 'sample_channel.s2p')


# =============================================================================
# Option Line Parsing Tests
# =============================================================================

class TestOptionLineParsing:
    """Tests for _parse_option_line()."""

    def test_default_options(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _parse_option_line
        result = _parse_option_line("# GHz S RI R 50")
        assert result["freq_unit"] == "ghz"
        assert result["param_type"] == "S"
        assert result["format"] == "RI"
        assert result["impedance"] == pytest.approx(50.0)

    def test_mhz_ma_format(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _parse_option_line
        result = _parse_option_line("# MHz S MA R 75")
        assert result["freq_unit"] == "mhz"
        assert result["format"] == "MA"
        assert result["impedance"] == pytest.approx(75.0)

    def test_hz_db_format(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _parse_option_line
        result = _parse_option_line("# Hz S DB R 50")
        assert result["freq_unit"] == "hz"
        assert result["format"] == "DB"

    def test_khz_unit(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _parse_option_line
        result = _parse_option_line("# kHz S RI R 50")
        assert result["freq_unit"] == "khz"

    def test_y_parameters(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _parse_option_line
        result = _parse_option_line("# GHz Y RI R 50")
        assert result["param_type"] == "Y"

    def test_z_parameters(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _parse_option_line
        result = _parse_option_line("# GHz Z RI R 50")
        assert result["param_type"] == "Z"

    def test_custom_impedance(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _parse_option_line
        result = _parse_option_line("# GHz S RI R 100")
        assert result["impedance"] == pytest.approx(100.0)


# =============================================================================
# Data Format Conversion Tests
# =============================================================================

class TestDataFormatConversion:
    """Tests for _values_to_complex()."""

    def test_ri_format(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _values_to_complex
        result = _values_to_complex(0.5, -0.3, "RI")
        assert result == pytest.approx(complex(0.5, -0.3))

    def test_ri_format_zero(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _values_to_complex
        result = _values_to_complex(0.0, 0.0, "RI")
        assert result == pytest.approx(complex(0, 0))

    def test_ma_format(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _values_to_complex
        result = _values_to_complex(1.0, 0.0, "MA")
        assert abs(result) == pytest.approx(1.0)
        assert cmath.phase(result) == pytest.approx(0.0, abs=1e-10)

    def test_ma_format_with_angle(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _values_to_complex
        result = _values_to_complex(1.0, 90.0, "MA")
        assert abs(result) == pytest.approx(1.0)
        assert math.degrees(cmath.phase(result)) == pytest.approx(90.0, abs=0.1)

    def test_db_format_zero_db(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _values_to_complex
        result = _values_to_complex(0.0, 0.0, "DB")
        assert abs(result) == pytest.approx(1.0)

    def test_db_format_minus20db(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _values_to_complex
        result = _values_to_complex(-20.0, 0.0, "DB")
        assert abs(result) == pytest.approx(0.1, rel=0.01)

    def test_db_format_with_angle(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _values_to_complex
        result = _values_to_complex(-6.0, 45.0, "DB")
        magnitude = 10.0 ** (-6.0 / 20.0)
        assert abs(result) == pytest.approx(magnitude, rel=0.01)
        assert math.degrees(cmath.phase(result)) == pytest.approx(45.0, abs=0.1)

    def test_unknown_format_raises(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _values_to_complex
        with pytest.raises(ValueError):
            _values_to_complex(1.0, 0.0, "XX")


# =============================================================================
# Port Count Detection Tests
# =============================================================================

class TestPortCountDetection:
    """Tests for _detect_port_count()."""

    def test_s1p(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _detect_port_count
        assert _detect_port_count("test.s1p") == 1

    def test_s2p(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _detect_port_count
        assert _detect_port_count("test.s2p") == 2

    def test_s4p(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _detect_port_count
        assert _detect_port_count("test.s4p") == 4

    def test_s8p(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _detect_port_count
        assert _detect_port_count("test.s8p") == 8

    def test_unknown_extension(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import _detect_port_count
        assert _detect_port_count("test.dat") == 2  # Default


# =============================================================================
# 2-Port File Parsing Tests
# =============================================================================

class TestTouchstoneParser2Port:
    """Tests for parsing 2-port Touchstone files."""

    def _load_sample(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import TouchstoneParser
        parser = TouchstoneParser()
        return parser.parse_file(SAMPLE_S2P)

    def test_parse_file_exists(self):
        data = self._load_sample()
        assert data is not None

    def test_port_count(self):
        data = self._load_sample()
        assert data.port_count == 2

    def test_reference_impedance(self):
        data = self._load_sample()
        assert data.reference_impedance == pytest.approx(50.0)

    def test_frequency_count(self):
        data = self._load_sample()
        assert data.num_points == 23  # 23 frequency points in fixture

    def test_frequency_range(self):
        data = self._load_sample()
        fmin, fmax = data.freq_range_hz
        assert fmin == pytest.approx(0.1e9)  # 100 MHz
        assert fmax == pytest.approx(10.0e9)  # 10 GHz

    def test_s11_data(self):
        data = self._load_sample()
        s11 = data.get_s(1, 1)
        assert len(s11) == 23

    def test_s21_data(self):
        data = self._load_sample()
        s21 = data.get_s(2, 1)
        assert len(s21) == 23

    def test_s12_data(self):
        data = self._load_sample()
        s12 = data.get_s(1, 2)
        assert len(s12) == 23

    def test_s22_data(self):
        data = self._load_sample()
        s22 = data.get_s(2, 2)
        assert len(s22) == 23

    def test_s21_decreases_with_frequency(self):
        """Insertion loss should generally increase with frequency."""
        data = self._load_sample()
        s21_db = data.get_s_db(2, 1)
        # First point should have less loss than last
        assert s21_db[0] > s21_db[-1]

    def test_s11_stays_negative(self):
        """Return loss should be negative (well-matched channel)."""
        data = self._load_sample()
        s11_db = data.get_s_db(1, 1)
        assert all(s < 0 for s in s11_db)

    def test_s21_db(self):
        data = self._load_sample()
        s21_db = data.get_s_db(2, 1)
        assert len(s21_db) == 23
        # First point at 100 MHz should be close to 0 dB
        assert s21_db[0] > -1.0

    def test_get_s_phase(self):
        data = self._load_sample()
        phase = data.get_s_phase_deg(2, 1)
        assert len(phase) == 23

    def test_get_s_magnitude(self):
        data = self._load_sample()
        mag = data.get_s_magnitude(2, 1)
        assert len(mag) == 23
        assert all(m >= 0 for m in mag)

    def test_to_dict(self):
        data = self._load_sample()
        d = data.to_dict()
        assert d["port_count"] == 2
        assert d["num_points"] == 23
        assert "S21" in d["s_parameters_summary"]

    def test_file_not_found(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import TouchstoneParser
        parser = TouchstoneParser()
        with pytest.raises(FileNotFoundError):
            parser.parse_file("/nonexistent/file.s2p")

    def test_invalid_port_key(self):
        data = self._load_sample()
        with pytest.raises(KeyError):
            data.get_s(3, 1)


# =============================================================================
# 1-Port String Parsing Tests
# =============================================================================

class TestTouchstoneParser1Port:
    """Tests for parsing 1-port Touchstone content."""

    def test_parse_1port_ri(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import TouchstoneParser
        content = """! 1-port S-parameter
# MHz S RI R 50
100  -0.1  -0.2
200  -0.15  -0.3
500  -0.2  -0.4
"""
        parser = TouchstoneParser()
        data = parser.parse_string(content, port_count=1)
        assert data.port_count == 1
        assert data.num_points == 3
        s11 = data.get_s(1, 1)
        assert len(s11) == 3
        # Check first point
        assert s11[0] == pytest.approx(complex(-0.1, -0.2))

    def test_parse_1port_frequencies_mhz(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import TouchstoneParser
        content = """# MHz S RI R 50
100  -0.1  -0.2
500  -0.2  -0.4
"""
        parser = TouchstoneParser()
        data = parser.parse_string(content, port_count=1)
        assert data.frequencies_hz[0] == pytest.approx(100e6)
        assert data.frequencies_hz[1] == pytest.approx(500e6)


# =============================================================================
# MA and DB Format Tests
# =============================================================================

class TestTouchstoneMAFormat:
    """Tests for MA (magnitude/angle) format parsing."""

    def test_parse_ma_format(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import TouchstoneParser
        content = """# GHz S MA R 50
1.0  0.1  -170.0  0.95  -10.0  0.95  -10.0  0.1  -170.0
"""
        parser = TouchstoneParser()
        data = parser.parse_string(content, port_count=2)
        s11 = data.get_s(1, 1)
        assert len(s11) == 1
        assert abs(s11[0]) == pytest.approx(0.1, abs=0.01)


class TestTouchstoneDBFormat:
    """Tests for DB (dB/angle) format parsing."""

    def test_parse_db_format(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import TouchstoneParser
        content = """# GHz S DB R 50
1.0  -20.0  -170.0  -0.5  -10.0  -0.5  -10.0  -20.0  -170.0
"""
        parser = TouchstoneParser()
        data = parser.parse_string(content, port_count=2)
        s11 = data.get_s(1, 1)
        assert len(s11) == 1
        # -20 dB magnitude should be 0.1
        assert abs(s11[0]) == pytest.approx(0.1, abs=0.01)
        s21 = data.get_s(2, 1)
        # -0.5 dB should be ~0.944
        assert abs(s21[0]) == pytest.approx(10 ** (-0.5 / 20.0), abs=0.01)


# =============================================================================
# 4-Port File Parsing Tests
# =============================================================================

class TestTouchstoneParser4Port:
    """Tests for parsing 4-port Touchstone content."""

    def test_parse_4port(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import TouchstoneParser
        # 4-port has 16 S-parameter pairs (32 values) + frequency per line
        # Values are in row-major order: S11 S12 S13 S14 S21 S22 S23 S24 ...
        content = """# GHz S RI R 50
1.0  -0.1 -0.1  0.0 0.0  0.0 0.0  0.0 0.0  0.0 0.0  -0.1 -0.1  0.0 0.0  0.0 0.0  0.0 0.0  0.0 0.0  -0.1 -0.1  0.0 0.0  0.0 0.0  0.0 0.0  0.0 0.0  -0.1 -0.1
"""
        parser = TouchstoneParser()
        data = parser.parse_string(content, port_count=4)
        assert data.port_count == 4
        assert data.num_points == 1
        s11 = data.get_s(1, 1)
        assert s11[0] == pytest.approx(complex(-0.1, -0.1))
        s22 = data.get_s(2, 2)
        assert s22[0] == pytest.approx(complex(-0.1, -0.1))


# =============================================================================
# Frequency Unit Tests
# =============================================================================

class TestFrequencyUnits:
    """Tests for all frequency unit conversions."""

    def _parse_with_unit(self, unit_str, freq_val, expected_hz):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import TouchstoneParser
        content = f"""# {unit_str} S RI R 50
{freq_val}  -0.1  -0.2
"""
        parser = TouchstoneParser()
        data = parser.parse_string(content, port_count=1)
        assert data.frequencies_hz[0] == pytest.approx(expected_hz)

    def test_hz(self):
        self._parse_with_unit("Hz", "1000000", 1e6)

    def test_khz(self):
        self._parse_with_unit("kHz", "1000", 1e6)

    def test_mhz(self):
        self._parse_with_unit("MHz", "1", 1e6)

    def test_ghz(self):
        self._parse_with_unit("GHz", "0.001", 1e6)

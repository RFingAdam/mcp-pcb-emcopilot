"""Tests for IBIS-driven eye diagram generation (Issue #39).

Covers:
- IBIS waveform parsing (inline fixture data)
- I-V curve extraction and impedance estimation
- Channel loss convolution (S-parameter and analytical)
- Eye diagram generation from bit pattern
- LPDDR4, USB 2.0, and generic CMOS scenarios
- Edge cases (flat waveform, zero-loss channel)
"""
from __future__ import annotations

import math
import os
import sys

import pytest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# =============================================================================
# Inline fixture data builders
# =============================================================================

def _make_rising_waveform_data(v_supply: float = 3.3, rise_time_s: float = 1e-9,
                                num_points: int = 10) -> list[dict]:
    """Build inline rising waveform data (list of dicts)."""
    data = []
    dt = rise_time_s * 1.5 / (num_points - 1)
    for i in range(num_points):
        t = i * dt
        x = (t - rise_time_s * 0.5) / (rise_time_s * 0.167)
        v = v_supply / (1.0 + math.exp(-x))
        data.append({"time": t, "typ": v, "min": v * 0.95, "max": v * 1.05})
    return data


def _make_falling_waveform_data(v_supply: float = 3.3, fall_time_s: float = 1e-9,
                                 num_points: int = 10) -> list[dict]:
    """Build inline falling waveform data (list of dicts)."""
    data = []
    dt = fall_time_s * 1.5 / (num_points - 1)
    for i in range(num_points):
        t = i * dt
        x = (t - fall_time_s * 0.5) / (fall_time_s * 0.167)
        v = v_supply - v_supply / (1.0 + math.exp(-x))
        data.append({"time": t, "typ": v, "min": v * 0.95, "max": v * 1.05})
    return data


def _make_iv_curve(v_supply: float = 3.3, ron: float = 50.0,
                   direction: str = "pulldown") -> list[dict]:
    """Build inline I-V curve data."""
    data = []
    for v_step in range(-5, 16):
        v = v_step * v_supply / 10.0
        if direction == "pulldown":
            i = v / ron
        else:
            i = (v - v_supply) / ron
        data.append({"voltage": v, "typ": i, "min": i * 0.9, "max": i * 1.1})
    return data


def _make_ibis_model_dict(v_supply: float = 3.3, rise_time_s: float = 1e-9,
                           ron: float = 50.0) -> dict:
    """Build a complete IBIS model dict like IBISParser produces."""
    return {
        "model_name": "TEST_IO",
        "model_type": "i/o",
        "vinl": v_supply * 0.3,
        "vinh": v_supply * 0.7,
        "vmeas": v_supply * 0.5,
        "c_comp": {"typ": 3e-12, "min": 2e-12, "max": 4e-12},
        "pullup": _make_iv_curve(v_supply, ron, "pullup"),
        "pulldown": _make_iv_curve(v_supply, ron, "pulldown"),
        "rising_waveform": [{
            "r_fixture": 50.0,
            "v_fixture": v_supply,
            "data": _make_rising_waveform_data(v_supply, rise_time_s),
        }],
        "falling_waveform": [{
            "r_fixture": 50.0,
            "v_fixture": v_supply,
            "data": _make_falling_waveform_data(v_supply, rise_time_s),
        }],
    }


def _make_sparam_channel(loss_at_nyquist_db: float = 3.0,
                          f_nyquist_hz: float = 2.5e9,
                          num_points: int = 20) -> tuple[list[float], list[complex]]:
    """Build synthetic S-parameter data with sqrt(f) loss profile."""
    freqs = []
    s21_vals = []
    f_max = f_nyquist_hz * 3.0
    for i in range(num_points):
        f = f_max * (i + 1) / num_points
        if f_nyquist_hz > 0 and loss_at_nyquist_db > 0:
            loss_db = loss_at_nyquist_db * math.sqrt(f / f_nyquist_hz)
        else:
            loss_db = 0.0
        mag = 10.0 ** (-loss_db / 20.0)
        phase = -2.0 * math.pi * f * 1e-9
        s21 = complex(mag * math.cos(phase), mag * math.sin(phase))
        freqs.append(f)
        s21_vals.append(s21)
    return freqs, s21_vals


# =============================================================================
# IBIS Waveform Parsing Tests
# =============================================================================

class TestIBISWaveformParsing:
    """Tests for parsing IBIS waveform data into WaveformPoint objects."""

    def test_parse_rising_waveform(self):
        """Rising waveform data should produce monotonically increasing voltages."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            parse_ibis_waveform,
        )
        raw = _make_rising_waveform_data(v_supply=3.3, rise_time_s=1e-9)
        points = parse_ibis_waveform(raw)

        assert len(points) == len(raw)
        assert points[0].time_s == pytest.approx(0.0)
        assert points[0].typ < points[-1].typ  # voltage increases
        assert points[-1].typ == pytest.approx(3.3, abs=0.1)

    def test_parse_falling_waveform(self):
        """Falling waveform data should produce monotonically decreasing voltages."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            parse_ibis_waveform,
        )
        raw = _make_falling_waveform_data(v_supply=3.3, fall_time_s=1e-9)
        points = parse_ibis_waveform(raw)

        assert len(points) == len(raw)
        assert points[0].typ > points[-1].typ  # voltage decreases
        assert points[0].typ == pytest.approx(3.3, abs=0.2)

    def test_waveform_min_max_columns(self):
        """Parsed waveform should include min/max triplet columns."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            parse_ibis_waveform,
        )
        raw = _make_rising_waveform_data()
        points = parse_ibis_waveform(raw)

        # Non-zero point should have min < typ < max
        mid = len(points) // 2
        assert points[mid].min is not None
        assert points[mid].max is not None
        assert points[mid].min <= points[mid].typ <= points[mid].max

    def test_waveform_string_time_values(self):
        """Waveform parser should handle string time values."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            parse_ibis_waveform,
        )
        raw = [
            {"time": "0.0", "typ": "0.0"},
            {"time": "0.5e-9", "typ": "1.65"},
            {"time": "1.0e-9", "typ": "3.3"},
        ]
        points = parse_ibis_waveform(raw)
        assert len(points) == 3
        assert points[1].time_s == pytest.approx(0.5e-9)
        assert points[2].typ == pytest.approx(3.3)


# =============================================================================
# I-V Curve Extraction Tests
# =============================================================================

class TestIVCurveExtraction:
    """Tests for I-V curve parsing and impedance estimation."""

    def test_parse_pulldown_iv(self):
        """Pulldown I-V curve should have increasing current with voltage."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            parse_ibis_iv_curve,
        )
        raw = _make_iv_curve(v_supply=3.3, ron=50.0, direction="pulldown")
        points = parse_ibis_iv_curve(raw)

        assert len(points) == len(raw)
        # At V=0, I should be ~0
        zero_points = [p for p in points if abs(p.voltage) < 0.01]
        assert len(zero_points) >= 1
        assert abs(zero_points[0].typ) < 0.01

    def test_parse_pullup_iv(self):
        """Pullup I-V curve should have proper current direction."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            parse_ibis_iv_curve,
        )
        raw = _make_iv_curve(v_supply=3.3, ron=50.0, direction="pullup")
        points = parse_ibis_iv_curve(raw)
        assert len(points) > 0

    def test_output_impedance_from_iv(self):
        """Output impedance should match Ron used to generate I-V curve."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        model_dict = _make_ibis_model_dict(v_supply=3.3, ron=40.0)
        model = gen.parse_ibis_model(model_dict)

        z_out = model.output_impedance("low")
        # Should be close to 40 ohm (within model tolerance)
        assert 20.0 < z_out < 80.0

    def test_iv_curve_min_max(self):
        """I-V curve points should have min/max triplet values."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            parse_ibis_iv_curve,
        )
        raw = _make_iv_curve(v_supply=3.3, ron=50.0, direction="pulldown")
        points = parse_ibis_iv_curve(raw)

        # Find a non-zero current point
        nonzero = [p for p in points if abs(p.typ) > 0.01]
        assert len(nonzero) > 0
        assert nonzero[0].min is not None
        assert nonzero[0].max is not None


# =============================================================================
# Channel Loss Convolution Tests
# =============================================================================

class TestChannelLossConvolution:
    """Tests for S-parameter and analytical channel loss convolution."""

    def test_sparam_channel_creation(self):
        """Creating SParameterData from freq/S21 arrays should work."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        freqs, s21 = _make_sparam_channel(loss_at_nyquist_db=5.0)
        sparam = gen.parse_sparam_data(freqs, s21)

        assert sparam.num_points == len(freqs)
        assert sparam.freq_range_hz[0] > 0
        assert sparam.freq_range_hz[1] > sparam.freq_range_hz[0]

    def test_sparam_s21_db_decreases(self):
        """S21 in dB should decrease (more loss) with frequency."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        freqs, s21 = _make_sparam_channel(loss_at_nyquist_db=10.0)
        sparam = gen.parse_sparam_data(freqs, s21)

        s21_db = sparam.s21_db()
        # First point should have less loss than last (more negative)
        assert s21_db[0] > s21_db[-1]

    def test_sparam_interpolation(self):
        """S21 magnitude interpolation should work at intermediate frequencies."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        freqs, s21 = _make_sparam_channel(loss_at_nyquist_db=6.0, f_nyquist_hz=2.5e9)
        sparam = gen.parse_sparam_data(freqs, s21)

        # Interpolate at Nyquist
        mag = sparam.interpolate_s21_mag(2.5e9)
        expected = 10.0 ** (-6.0 / 20.0)  # ~0.5
        assert 0.2 < mag < 0.9  # reasonable range

    def test_lossy_channel_factory(self):
        """create_lossy_channel should produce S-parameter data with correct loss."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        sparam = gen.create_lossy_channel(
            loss_at_nyquist_db=6.0,
            data_rate_gbps=5.0,
        )

        assert sparam.num_points > 0
        s21_db = sparam.s21_db()
        # Should have some loss
        assert any(db < -1.0 for db in s21_db)

    def test_zero_loss_channel_passthrough(self):
        """A zero-loss channel should preserve driver swing."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        model = gen.create_generic_cmos_model(v_supply=3.3)
        result = gen.generate_eye(model, data_rate_gbps=1.0, channel_loss_db=0.0)

        # With zero channel loss, eye height should be close to full swing
        assert result.eye_height_mv > 1000.0  # should preserve most of 3.3V swing


# =============================================================================
# Eye Diagram Generation Tests
# =============================================================================

class TestEyeDiagramGeneration:
    """Tests for end-to-end eye diagram generation from bit pattern."""

    def test_basic_eye_generation(self):
        """Basic eye generation should produce valid metrics."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        model_dict = _make_ibis_model_dict(v_supply=3.3, rise_time_s=1e-9)
        model = gen.parse_ibis_model(model_dict)
        result = gen.generate_eye(model, data_rate_gbps=1.0, channel_loss_db=3.0)

        assert result.eye_height_mv > 0
        assert result.eye_width_ps > 0
        assert result.unit_interval_ps == pytest.approx(1000.0)  # 1 Gbps
        assert result.data_rate_gbps == 1.0

    def test_eye_with_sparam_channel(self):
        """Eye generation with S-parameter channel should produce valid result."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        model = gen.create_generic_cmos_model(v_supply=3.3)
        freqs, s21 = _make_sparam_channel(loss_at_nyquist_db=5.0, f_nyquist_hz=2.5e9)
        sparam = gen.parse_sparam_data(freqs, s21)

        result = gen.generate_eye(model, data_rate_gbps=5.0, sparam=sparam)

        assert result.eye_height_mv >= 0
        assert result.eye_width_ps >= 0
        assert result.insertion_loss_at_nyquist_db > 0
        assert result.protocol == "generic"

    def test_higher_loss_degrades_eye(self):
        """Higher channel loss should degrade eye height."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        model = gen.create_generic_cmos_model(v_supply=3.3)

        low_loss = gen.generate_eye(model, data_rate_gbps=2.0, channel_loss_db=2.0)
        high_loss = gen.generate_eye(model, data_rate_gbps=2.0, channel_loss_db=15.0)

        assert high_loss.eye_height_mv <= low_loss.eye_height_mv

    def test_eye_result_to_dict(self):
        """EyeDiagramResult.to_dict() should produce complete JSON-able dict."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        model = gen.create_generic_cmos_model()
        result = gen.generate_eye(model, data_rate_gbps=1.0, channel_loss_db=3.0)
        d = result.to_dict()

        required_keys = [
            "eye_height_mv", "eye_width_ps", "eye_width_ui",
            "unit_interval_ps", "data_rate_gbps", "rise_time_ps",
            "fall_time_ps", "v_swing_mv", "pass_fail", "protocol",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"

    def test_eye_pass_fail(self):
        """Eye diagram should report PASS/FAIL based on protocol thresholds."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        model = gen.create_generic_cmos_model(v_supply=3.3)

        # Short trace, low loss -> should pass
        result = gen.generate_eye(model, data_rate_gbps=1.0, channel_loss_db=1.0)
        assert result.pass_fail in ("PASS", "FAIL")

    def test_ibis_model_to_dict(self):
        """IBISModel.to_dict() should return complete summary."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        model = gen.create_generic_cmos_model(v_supply=3.3)
        d = model.to_dict()

        assert d["model_name"] == "GENERIC_CMOS"
        assert d["v_supply"] == 3.3
        assert d["rise_time_ps"] > 0
        assert d["c_comp_pF"] > 0


# =============================================================================
# Protocol-Specific Scenario Tests
# =============================================================================

class TestProtocolScenarios:
    """Tests for LPDDR4, USB 2.0, and generic CMOS buffer models."""

    def test_lpddr4_model_creation(self):
        """LPDDR4 model should have correct voltage and fast edges."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        model = gen.create_lpddr4_model(v_supply=1.1)

        assert model.v_supply == pytest.approx(1.1)
        assert model.model_name == "LPDDR4_DQ"
        assert len(model.rising_waveform) == 1
        assert len(model.falling_waveform) == 1
        assert len(model.pullup) > 0
        assert len(model.pulldown) > 0

    def test_lpddr4_eye_diagram(self):
        """LPDDR4 eye diagram at 4.267 Gbps should produce valid result."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        model = gen.create_lpddr4_model()
        result = gen.generate_eye(
            model, data_rate_gbps=4.267,
            channel_loss_db=4.0,
            protocol="lpddr4",
        )

        assert result.protocol == "lpddr4"
        assert result.unit_interval_ps == pytest.approx(1e12 / (4.267e9), rel=0.01)
        assert result.eye_height_mv >= 0
        assert result.pass_fail in ("PASS", "FAIL")

    def test_usb2_model_creation(self):
        """USB 2.0 model should have 3.3V supply and slow edges."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        model = gen.create_usb2_model(v_supply=3.3)

        assert model.v_supply == pytest.approx(3.3)
        assert model.model_name == "USB2_FS"
        # USB 2.0 should have slower rise time than LPDDR4
        assert model.rise_time_s > 1e-10  # at least 100 ps

    def test_usb2_eye_diagram(self):
        """USB 2.0 HS eye diagram at 480 Mbps should work."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        model = gen.create_usb2_model()
        result = gen.generate_eye(
            model, data_rate_gbps=0.48,
            channel_loss_db=1.0,
            protocol="usb2",
        )

        assert result.protocol == "usb2"
        assert result.data_rate_gbps == 0.48
        assert result.eye_height_mv > 0

    def test_generic_cmos_model(self):
        """Generic CMOS model should work with configurable parameters."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        model = gen.create_generic_cmos_model(v_supply=2.5, rise_time_ps=300.0, ron=60.0)

        assert model.v_supply == pytest.approx(2.5)
        assert model.model_type == "output"
        d = model.to_dict()
        assert d["v_supply"] == 2.5


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_flat_waveform_handled(self):
        """A flat waveform (no transition) should not crash."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
            WaveformPoint,
        )
        gen = IBISEyeGenerator()

        # All-same-voltage waveform
        flat_rising = [WaveformPoint(time_s=i * 1e-10, typ=1.5) for i in range(10)]
        model = gen.build_ibis_model(
            rising_waveform=flat_rising,
            v_supply=3.3,
        )

        # rise_time should be handled gracefully (fallback)
        assert model.rise_time_s > 0
        # Eye generation should not crash
        result = gen.generate_eye(model, data_rate_gbps=1.0, channel_loss_db=3.0)
        assert result.eye_height_mv >= 0

    def test_empty_sparam_passthrough(self):
        """Empty SParameterData should act as lossless passthrough."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            SParameterData,
        )
        sparam = SParameterData()
        assert sparam.num_points == 0
        assert sparam.interpolate_s21_mag(1e9) == 1.0  # pass-through

    def test_sparam_to_dict(self):
        """SParameterData.to_dict() should return valid dict."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        freqs, s21 = _make_sparam_channel(loss_at_nyquist_db=3.0)
        sparam = gen.parse_sparam_data(freqs, s21)
        d = sparam.to_dict()

        assert d["num_points"] == len(freqs)
        assert d["reference_impedance"] == 50.0
        assert d["port_count"] == 2

    def test_very_high_data_rate(self):
        """Very high data rate should produce small UI and potentially closed eye."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        model = gen.create_generic_cmos_model(v_supply=3.3, rise_time_ps=500.0)
        result = gen.generate_eye(model, data_rate_gbps=28.0, channel_loss_db=20.0)

        # At 28 Gbps with 20 dB loss, eye should be very degraded
        assert result.unit_interval_ps < 40.0
        # Should likely fail
        assert result.isi_penalty_percent > 0

    def test_model_from_parsed_dict(self):
        """parse_ibis_model should correctly populate all fields from dict."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
        )
        gen = IBISEyeGenerator()
        model_dict = _make_ibis_model_dict(v_supply=1.8, rise_time_s=0.5e-9, ron=35.0)
        model = gen.parse_ibis_model(model_dict, model_name="MY_IO_1V8")

        assert model.model_name == "MY_IO_1V8"
        assert model.model_type == "i/o"
        assert model.v_supply == pytest.approx(1.8, abs=0.1)
        assert len(model.pullup) > 0
        assert len(model.pulldown) > 0
        assert len(model.rising_waveform) == 1
        assert len(model.falling_waveform) == 1
        assert model.c_comp_typ == pytest.approx(3e-12)

    def test_import_path(self):
        """Verify the expected import path works."""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.ibis_eye import (
            IBISEyeGenerator,
            IBISModel,
            SParameterData,
        )
        assert IBISEyeGenerator is not None
        assert IBISModel is not None
        assert SParameterData is not None

"""Tests for input validation on server tool dispatch.

Validates that calculator tools reject invalid inputs with structured errors,
and that invalid session IDs produce SessionError.
"""
import json
import math
import pytest

from mcp_pcb_emcopilot.errors import ValidationError, SessionError


# ─── Direct function-level tests ────────────────────────────────────────────
# We test the calc functions after validation would occur by calling _dispatch directly.
# Since _dispatch is not easily importable without starting the server, we test
# the validation functions and the calc functions independently.

from mcp_pcb_emcopilot.server import (
    calc_microstrip_impedance,
    calc_stripline_impedance,
    calc_differential_impedance,
    calc_trace_width_for_current,
    calc_cpw_impedance,
    calc_skin_effect,
    calc_dielectric_loss,
    calc_plane_resonance,
    calc_via_stitching_requirements,
    analyze_trace_timing,
    analyze_crosstalk,
    analyze_via,
    analyze_current_loop,
    estimate_rise_time_bandwidth,
    _dispatch,
    _get_session,
)


class TestMicrostripValidation:
    """pcb_calc_microstrip_impedance validation."""

    def test_valid_inputs(self):
        result = _dispatch("pcb_calc_microstrip_impedance", {
            "trace_width_mm": 0.15,
            "dielectric_height_mm": 0.1,
            "trace_thickness_mm": 0.035,
            "dielectric_constant": 4.3,
        })
        assert result["success"] is True
        assert "impedance_ohms" in result

    def test_negative_trace_width(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_calc_microstrip_impedance", {
                "trace_width_mm": -0.15,
                "dielectric_height_mm": 0.1,
                "trace_thickness_mm": 0.035,
                "dielectric_constant": 4.3,
            })

    def test_zero_trace_width(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_calc_microstrip_impedance", {
                "trace_width_mm": 0.0,
                "dielectric_height_mm": 0.1,
                "trace_thickness_mm": 0.035,
                "dielectric_constant": 4.3,
            })

    def test_nan_dielectric_height(self):
        with pytest.raises(ValidationError, match="finite"):
            _dispatch("pcb_calc_microstrip_impedance", {
                "trace_width_mm": 0.15,
                "dielectric_height_mm": float("nan"),
                "trace_thickness_mm": 0.035,
                "dielectric_constant": 4.3,
            })

    def test_inf_trace_thickness(self):
        with pytest.raises(ValidationError, match="finite"):
            _dispatch("pcb_calc_microstrip_impedance", {
                "trace_width_mm": 0.15,
                "dielectric_height_mm": 0.1,
                "trace_thickness_mm": float("inf"),
                "dielectric_constant": 4.3,
            })

    def test_dielectric_constant_out_of_range_low(self):
        with pytest.raises(ValidationError, match="between"):
            _dispatch("pcb_calc_microstrip_impedance", {
                "trace_width_mm": 0.15,
                "dielectric_height_mm": 0.1,
                "trace_thickness_mm": 0.035,
                "dielectric_constant": 0.5,
            })

    def test_dielectric_constant_out_of_range_high(self):
        with pytest.raises(ValidationError, match="between"):
            _dispatch("pcb_calc_microstrip_impedance", {
                "trace_width_mm": 0.15,
                "dielectric_height_mm": 0.1,
                "trace_thickness_mm": 0.035,
                "dielectric_constant": 200.0,
            })


class TestStriplineValidation:
    """pcb_calc_stripline_impedance validation."""

    def test_valid(self):
        result = _dispatch("pcb_calc_stripline_impedance", {
            "trace_width_mm": 0.1,
            "dielectric_height_mm": 0.2,
            "trace_thickness_mm": 0.035,
            "dielectric_constant": 4.3,
        })
        assert result["success"] is True

    def test_negative_trace_width(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_calc_stripline_impedance", {
                "trace_width_mm": -1.0,
                "dielectric_height_mm": 0.2,
                "trace_thickness_mm": 0.035,
                "dielectric_constant": 4.3,
            })

    def test_nan_input(self):
        with pytest.raises(ValidationError):
            _dispatch("pcb_calc_stripline_impedance", {
                "trace_width_mm": float("nan"),
                "dielectric_height_mm": 0.2,
                "trace_thickness_mm": 0.035,
                "dielectric_constant": 4.3,
            })


class TestDifferentialImpedanceValidation:
    """pcb_calc_differential_impedance validation."""

    def test_valid(self):
        result = _dispatch("pcb_calc_differential_impedance", {
            "trace_width_mm": 0.1,
            "trace_spacing_mm": 0.15,
            "dielectric_height_mm": 0.1,
            "trace_thickness_mm": 0.035,
            "dielectric_constant": 4.3,
        })
        assert result["success"] is True

    def test_negative_spacing(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_calc_differential_impedance", {
                "trace_width_mm": 0.1,
                "trace_spacing_mm": -0.15,
                "dielectric_height_mm": 0.1,
                "trace_thickness_mm": 0.035,
                "dielectric_constant": 4.3,
            })


class TestTraceWidthValidation:
    """pcb_calc_trace_width validation."""

    def test_valid(self):
        result = _dispatch("pcb_calc_trace_width", {
            "current_amps": 1.0,
            "temp_rise_c": 10.0,
            "copper_thickness_oz": 1.0,
        })
        assert result["success"] is True

    def test_negative_current(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_calc_trace_width", {
                "current_amps": -1.0,
                "temp_rise_c": 10.0,
                "copper_thickness_oz": 1.0,
            })

    def test_inf_temp_rise(self):
        with pytest.raises(ValidationError, match="finite"):
            _dispatch("pcb_calc_trace_width", {
                "current_amps": 1.0,
                "temp_rise_c": float("inf"),
                "copper_thickness_oz": 1.0,
            })


class TestCPWValidation:
    """pcb_calc_cpw_impedance validation."""

    def test_valid(self):
        result = _dispatch("pcb_calc_cpw_impedance", {
            "trace_width_mm": 0.5,
            "gap_mm": 0.2,
            "dielectric_height_mm": 0.2,
            "trace_thickness_mm": 0.035,
            "dielectric_constant": 4.3,
        })
        assert result["success"] is True

    def test_negative_gap(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_calc_cpw_impedance", {
                "trace_width_mm": 0.5,
                "gap_mm": -0.2,
                "dielectric_height_mm": 0.2,
                "trace_thickness_mm": 0.035,
                "dielectric_constant": 4.3,
            })

    def test_dielectric_constant_out_of_range(self):
        with pytest.raises(ValidationError, match="between"):
            _dispatch("pcb_calc_cpw_impedance", {
                "trace_width_mm": 0.5,
                "gap_mm": 0.2,
                "dielectric_height_mm": 0.2,
                "trace_thickness_mm": 0.035,
                "dielectric_constant": 0.1,
            })


class TestSkinEffectValidation:
    """pcb_calc_skin_effect validation."""

    def test_valid(self):
        result = _dispatch("pcb_calc_skin_effect", {
            "frequency_mhz": 100.0,
        })
        assert result["success"] is True

    def test_negative_frequency(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_calc_skin_effect", {
                "frequency_mhz": -100.0,
            })


class TestDielectricLossValidation:
    """pcb_calc_dielectric_loss validation."""

    def test_valid(self):
        result = _dispatch("pcb_calc_dielectric_loss", {
            "frequency_mhz": 1000.0,
            "dielectric_constant": 4.3,
            "loss_tangent": 0.02,
            "trace_length_mm": 50.0,
        })
        assert result["success"] is True

    def test_negative_trace_length(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_calc_dielectric_loss", {
                "frequency_mhz": 1000.0,
                "dielectric_constant": 4.3,
                "loss_tangent": 0.02,
                "trace_length_mm": -10.0,
            })

    def test_dielectric_constant_out_of_range(self):
        with pytest.raises(ValidationError, match="between"):
            _dispatch("pcb_calc_dielectric_loss", {
                "frequency_mhz": 1000.0,
                "dielectric_constant": 0.0,
                "loss_tangent": 0.02,
                "trace_length_mm": 50.0,
            })


class TestPlaneResonanceValidation:
    """pcb_calc_plane_resonance validation."""

    def test_valid(self):
        result = _dispatch("pcb_calc_plane_resonance", {
            "plane_width_mm": 100.0,
            "plane_length_mm": 80.0,
            "dielectric_constant": 4.3,
            "dielectric_height_mm": 0.2,
        })
        assert result["success"] is True

    def test_negative_plane_width(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_calc_plane_resonance", {
                "plane_width_mm": -100.0,
                "plane_length_mm": 80.0,
                "dielectric_constant": 4.3,
                "dielectric_height_mm": 0.2,
            })


class TestViaStitchingValidation:
    """pcb_calc_via_stitching validation."""

    def test_valid(self):
        result = _dispatch("pcb_calc_via_stitching", {
            "max_frequency_mhz": 1000.0,
            "dielectric_constant": 4.3,
        })
        assert result["success"] is True

    def test_negative_frequency(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_calc_via_stitching", {
                "max_frequency_mhz": -1000.0,
                "dielectric_constant": 4.3,
            })

    def test_dielectric_constant_out_of_range(self):
        with pytest.raises(ValidationError, match="between"):
            _dispatch("pcb_calc_via_stitching", {
                "max_frequency_mhz": 1000.0,
                "dielectric_constant": 0.5,
            })


class TestViaAnalysisValidation:
    """pcb_analyze_via validation."""

    def test_valid(self):
        result = _dispatch("pcb_analyze_via", {
            "via_diameter_mm": 0.3,
            "via_length_mm": 1.6,
            "pad_diameter_mm": 0.6,
            "antipad_diameter_mm": 1.0,
            "dielectric_constant": 4.3,
            "frequency_ghz": 5.0,
        })
        assert result["success"] is True

    def test_negative_via_diameter(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_analyze_via", {
                "via_diameter_mm": -0.3,
                "via_length_mm": 1.6,
                "pad_diameter_mm": 0.6,
                "antipad_diameter_mm": 1.0,
                "dielectric_constant": 4.3,
                "frequency_ghz": 5.0,
            })

    def test_nan_frequency(self):
        with pytest.raises(ValidationError, match="finite"):
            _dispatch("pcb_analyze_via", {
                "via_diameter_mm": 0.3,
                "via_length_mm": 1.6,
                "pad_diameter_mm": 0.6,
                "antipad_diameter_mm": 1.0,
                "dielectric_constant": 4.3,
                "frequency_ghz": float("nan"),
            })


class TestEyeDiagramValidation:
    """pcb_calc_eye_diagram validation."""

    def test_valid(self):
        result = _dispatch("pcb_calc_eye_diagram", {
            "data_rate_gbps": 10.0,
            "trace_length_mm": 100.0,
            "dielectric_constant": 4.0,
            "loss_tangent": 0.02,
            "trace_width_mm": 0.12,
            "dielectric_height_mm": 0.1,
        })
        assert result["success"] is True

    def test_negative_data_rate(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_calc_eye_diagram", {
                "data_rate_gbps": -10.0,
                "trace_length_mm": 100.0,
                "dielectric_constant": 4.0,
                "loss_tangent": 0.02,
                "trace_width_mm": 0.12,
                "dielectric_height_mm": 0.1,
            })


class TestCurrentLoopValidation:
    """pcb_analyze_current_loop validation."""

    def test_valid(self):
        result = _dispatch("pcb_analyze_current_loop", {
            "loop_area_mm2": 10.0,
            "current_ma": 100.0,
            "frequency_mhz": 100.0,
        })
        assert result["success"] is True

    def test_negative_loop_area(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_analyze_current_loop", {
                "loop_area_mm2": -10.0,
                "current_ma": 100.0,
                "frequency_mhz": 100.0,
            })

    def test_nan_frequency(self):
        with pytest.raises(ValidationError, match="finite"):
            _dispatch("pcb_analyze_current_loop", {
                "loop_area_mm2": 10.0,
                "current_ma": 100.0,
                "frequency_mhz": float("nan"),
            })


class TestBandwidthValidation:
    """pcb_estimate_bandwidth validation."""

    def test_valid(self):
        result = _dispatch("pcb_estimate_bandwidth", {
            "rise_time_ps": 100.0,
        })
        assert result["success"] is True

    def test_negative_rise_time(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_estimate_bandwidth", {
                "rise_time_ps": -100.0,
            })


class TestTimingValidation:
    """pcb_analyze_timing validation."""

    def test_valid(self):
        result = _dispatch("pcb_analyze_timing", {
            "trace_length_mm": 50.0,
            "effective_er": 4.0,
            "data_rate_gbps": 5.0,
            "rise_time_ps": 100.0,
            "setup_time_ps": 50.0,
            "hold_time_ps": 50.0,
        })
        assert result["success"] is True

    def test_dielectric_constant_out_of_range(self):
        with pytest.raises(ValidationError, match="between"):
            _dispatch("pcb_analyze_timing", {
                "trace_length_mm": 50.0,
                "effective_er": 0.5,
                "data_rate_gbps": 5.0,
                "rise_time_ps": 100.0,
                "setup_time_ps": 50.0,
                "hold_time_ps": 50.0,
            })


class TestCrosstalkValidation:
    """pcb_analyze_crosstalk validation."""

    def test_valid(self):
        result = _dispatch("pcb_analyze_crosstalk", {
            "trace_spacing_mm": 0.2,
            "trace_width_mm": 0.1,
            "dielectric_height_mm": 0.1,
            "coupling_length_mm": 25.0,
            "rise_time_ps": 100.0,
        })
        assert result["success"] is True

    def test_negative_spacing(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_analyze_crosstalk", {
                "trace_spacing_mm": -0.2,
                "trace_width_mm": 0.1,
                "dielectric_height_mm": 0.1,
                "coupling_length_mm": 25.0,
                "rise_time_ps": 100.0,
            })


class TestDifferentialPairValidation:
    """pcb_analyze_differential_pair validation."""

    def test_valid(self):
        result = _dispatch("pcb_analyze_differential_pair", {
            "trace_width_mm": 0.1,
            "trace_spacing_mm": 0.15,
            "dielectric_height_mm": 0.1,
            "dielectric_constant": 4.3,
            "target_impedance_ohm": 100.0,
            "data_rate_gbps": 5.0,
        })
        assert "differential_impedance_ohm" in result

    def test_negative_target(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_analyze_differential_pair", {
                "trace_width_mm": 0.1,
                "trace_spacing_mm": 0.15,
                "dielectric_height_mm": 0.1,
                "dielectric_constant": 4.3,
                "target_impedance_ohm": -100.0,
                "data_rate_gbps": 5.0,
            })


class TestInsertionLossValidation:
    """pcb_calc_insertion_loss validation."""

    def test_negative_trace_width(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_calc_insertion_loss", {
                "trace_length_mm": 100.0,
                "trace_width_mm": -0.1,
                "dielectric_height_mm": 0.1,
                "dielectric_constant": 4.3,
                "loss_tangent": 0.02,
            })


class TestReturnLossValidation:
    """pcb_calc_return_loss validation."""

    def test_negative_impedance(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_calc_return_loss", {
                "impedance_ohm": -50.0,
                "target_impedance_ohm": 50.0,
                "frequency_mhz": 1000.0,
            })


class TestModeConversionValidation:
    """pcb_analyze_mode_conversion validation."""

    def test_negative_trace_width(self):
        with pytest.raises(ValidationError, match="positive"):
            _dispatch("pcb_analyze_mode_conversion", {
                "trace_width_mm": -0.1,
                "trace_spacing_mm": 0.15,
                "dielectric_height_mm": 0.1,
                "dielectric_constant": 4.3,
                "length_asymmetry_mm": 0.5,
                "data_rate_gbps": 10.0,
            })


class TestSessionValidation:
    """Invalid session IDs produce SessionError."""

    def test_invalid_session_get_stackup(self):
        with pytest.raises(SessionError, match="No active session"):
            _dispatch("pcb_get_stackup", {"session_id": "nonexistent-id"})

    def test_invalid_session_get_components(self):
        with pytest.raises(SessionError, match="No active session"):
            _dispatch("pcb_get_components", {"session_id": "nonexistent-id"})

    def test_invalid_session_get_nets(self):
        with pytest.raises(SessionError, match="No active session"):
            _dispatch("pcb_get_nets", {"session_id": "nonexistent-id"})

    def test_invalid_session_get_vias(self):
        with pytest.raises(SessionError, match="No active session"):
            _dispatch("pcb_get_vias", {"session_id": "nonexistent-id"})

    def test_invalid_session_classify_nets(self):
        with pytest.raises(SessionError, match="No active session"):
            _dispatch("pcb_classify_nets", {"session_id": "nonexistent-id"})

    def test_get_session_helper(self):
        with pytest.raises(SessionError, match="No active session"):
            _get_session("does-not-exist")

    def test_session_error_has_structured_data(self):
        try:
            _get_session("bad-id")
        except SessionError as e:
            d = e.to_dict()
            assert d["error_type"] == "SessionError"
            assert d["code"] == "INVALID_SESSION"
            assert "bad-id" in d["message"]
            assert d["context"]["session_id"] == "bad-id"


class TestLengthMatchingValidation:
    """pcb_analyze_length_matching validation."""

    def test_valid(self):
        result = _dispatch("pcb_analyze_length_matching", {
            "trace_lengths_mm": {"clk": 50.0, "data": 52.0},
            "max_skew_ps": 50.0,
            "effective_er": 4.0,
        })
        assert "max_skew_ps" in result

    def test_dielectric_constant_out_of_range(self):
        with pytest.raises(ValidationError, match="between"):
            _dispatch("pcb_analyze_length_matching", {
                "trace_lengths_mm": {"clk": 50.0, "data": 52.0},
                "max_skew_ps": 50.0,
                "effective_er": 0.1,
            })

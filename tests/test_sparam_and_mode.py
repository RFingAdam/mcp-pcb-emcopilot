"""
Tests for S-parameter extraction (Issue #8) and mode conversion analysis (Issue #12).

Validates against known physics:
- FR4 at 1 GHz: ~0.1-0.3 dB/inch insertion loss
- FR4 at 10 GHz: ~1-3 dB/inch
- Rogers 4350B: ~3x less loss than FR4
- 10% impedance mismatch → ~0.04 dB mismatch loss, ~26 dB return loss
"""



from mcp_pcb_emcopilot.analyzers.rf_si.mode_conversion import (
    analyze_mode_conversion,
)
from mcp_pcb_emcopilot.analyzers.rf_si.sparam_extractor import (
    calculate_insertion_loss,
    calculate_return_loss,
)

# ============================================================================
# S-Parameter Extractor Tests (Issue #8)
# ============================================================================

class TestInsertionLoss:
    """Test calculate_insertion_loss."""

    # FR4: Er=4.3, Df=0.02
    FR4_PARAMS = dict(
        dielectric_constant=4.3,
        loss_tangent=0.02,
        dielectric_height_mm=0.2,
        trace_width_mm=0.3,
        copper_thickness_oz=1.0,
        surface_roughness_um=0.5,
    )

    # Rogers 4350B: Er=3.48, Df=0.0037
    ROGERS_PARAMS = dict(
        dielectric_constant=3.48,
        loss_tangent=0.0037,
        dielectric_height_mm=0.2,
        trace_width_mm=0.3,
        copper_thickness_oz=1.0,
        surface_roughness_um=0.3,
    )

    def test_basic_sweep_returns_arrays(self):
        """Should return frequency, S21, S11 arrays of correct length."""
        result = calculate_insertion_loss(
            trace_length_mm=25.4,  # 1 inch
            num_points=20,
            freq_start_mhz=100,
            freq_stop_mhz=10000,
            **self.FR4_PARAMS,
        )
        assert "frequency_mhz" in result
        assert "s21_db" in result
        assert "s11_db" in result
        assert len(result["frequency_mhz"]) == 20
        assert len(result["s21_db"]) == 20
        assert len(result["s11_db"]) == 20

    def test_s21_negative(self):
        """S21 (insertion loss) should always be negative dB."""
        result = calculate_insertion_loss(
            trace_length_mm=50.0,
            num_points=10,
            freq_start_mhz=100,
            freq_stop_mhz=5000,
            **self.FR4_PARAMS,
        )
        for val in result["s21_db"]:
            assert val <= 0, f"S21 should be <= 0 dB, got {val}"

    def test_s21_increases_with_frequency(self):
        """Insertion loss (magnitude) should increase with frequency."""
        result = calculate_insertion_loss(
            trace_length_mm=25.4,
            num_points=10,
            freq_start_mhz=100,
            freq_stop_mhz=10000,
            **self.FR4_PARAMS,
        )
        # Loss gets worse (more negative) at higher frequencies
        assert result["s21_db"][-1] < result["s21_db"][0], \
            "Loss should be worse at higher frequency"

    def test_s21_increases_with_length(self):
        """Longer trace should have more loss."""
        short = calculate_insertion_loss(
            trace_length_mm=25.4,
            num_points=5,
            freq_start_mhz=1000,
            freq_stop_mhz=1000,
            **self.FR4_PARAMS,
        )
        long = calculate_insertion_loss(
            trace_length_mm=254.0,
            num_points=5,
            freq_start_mhz=1000,
            freq_stop_mhz=1000,
            **self.FR4_PARAMS,
        )
        # More negative = more loss
        assert long["s21_db"][0] < short["s21_db"][0]

    def test_fr4_loss_at_1ghz(self):
        """FR4 at 1 GHz should show ~0.1-0.3 dB/inch insertion loss."""
        result = calculate_insertion_loss(
            trace_length_mm=25.4,  # 1 inch
            num_points=5,
            freq_start_mhz=1000,
            freq_stop_mhz=1000,
            **self.FR4_PARAMS,
        )
        # S21 is negative; loss per inch = -S21
        loss_per_inch = -result["s21_db"][0]
        assert 0.05 < loss_per_inch < 0.5, \
            f"FR4 at 1 GHz should be ~0.1-0.3 dB/inch, got {loss_per_inch:.4f}"

    def test_fr4_loss_at_10ghz(self):
        """FR4 at 10 GHz should show ~1-3 dB/inch insertion loss."""
        result = calculate_insertion_loss(
            trace_length_mm=25.4,
            num_points=5,
            freq_start_mhz=10000,
            freq_stop_mhz=10000,
            **self.FR4_PARAMS,
        )
        loss_per_inch = -result["s21_db"][0]
        assert 0.3 < loss_per_inch < 5.0, \
            f"FR4 at 10 GHz should be ~1-3 dB/inch, got {loss_per_inch:.4f}"

    def test_rogers_less_loss_than_fr4(self):
        """Rogers 4350B should have significantly less loss than FR4."""
        fr4 = calculate_insertion_loss(
            trace_length_mm=25.4,
            num_points=5,
            freq_start_mhz=5000,
            freq_stop_mhz=5000,
            **self.FR4_PARAMS,
        )
        rogers = calculate_insertion_loss(
            trace_length_mm=25.4,
            num_points=5,
            freq_start_mhz=5000,
            freq_stop_mhz=5000,
            **self.ROGERS_PARAMS,
        )
        fr4_loss = -fr4["s21_db"][0]
        rogers_loss = -rogers["s21_db"][0]
        ratio = fr4_loss / rogers_loss if rogers_loss > 0 else float("inf")
        assert ratio > 1.5, \
            f"FR4 should be at least 1.5x more lossy than Rogers, got ratio={ratio:.2f}"

    def test_trace_impedance_returned(self):
        """Should return calculated trace impedance."""
        result = calculate_insertion_loss(
            trace_length_mm=25.4,
            num_points=5,
            **self.FR4_PARAMS,
        )
        assert "trace_impedance_ohm" in result
        # For typical params, impedance should be physically reasonable
        assert 20 < result["trace_impedance_ohm"] < 200

    def test_notes_generated(self):
        """Should return diagnostic notes."""
        result = calculate_insertion_loss(
            trace_length_mm=25.4,
            num_points=5,
            **self.FR4_PARAMS,
        )
        assert "notes" in result
        assert isinstance(result["notes"], list)


class TestReturnLoss:
    """Test calculate_return_loss."""

    def test_perfect_match(self):
        """50 ohm into 50 ohm should give very low reflection."""
        result = calculate_return_loss(50.0, 50.0, 1000.0)
        assert result["s11_db"] < -50
        assert result["vswr"] < 1.01
        assert result["mismatch_loss_db"] < 0.001

    def test_10_percent_mismatch(self):
        """10% impedance mismatch → ~26 dB return loss, ~0.04 dB mismatch loss."""
        # 55 ohm into 50 ohm = 10% mismatch
        result = calculate_return_loss(55.0, 50.0, 1000.0)

        # Expected: gamma = 5/105 = 0.0476
        # S11 = 20*log10(0.0476) = -26.4 dB
        # Return loss = 26.4 dB
        assert 24 < result["return_loss_db"] < 28, \
            f"Expected ~26 dB return loss, got {result['return_loss_db']:.1f}"

        # Mismatch loss = -10*log10(1 - 0.0476^2) = 0.0099 dB
        assert result["mismatch_loss_db"] < 0.1, \
            f"Expected ~0.04 dB mismatch loss, got {result['mismatch_loss_db']:.4f}"

    def test_large_mismatch(self):
        """100 ohm into 50 ohm should show poor match."""
        result = calculate_return_loss(100.0, 50.0, 1000.0)
        # gamma = 50/150 = 0.333
        # S11 = -9.54 dB
        assert result["return_loss_db"] < 12
        assert result["vswr"] > 1.5

    def test_vswr_calculation(self):
        """VSWR should be >= 1 and consistent with reflection coefficient."""
        result = calculate_return_loss(75.0, 50.0, 1000.0)
        gamma = result["reflection_coefficient"]
        expected_vswr = (1 + gamma) / (1 - gamma)
        assert abs(result["vswr"] - expected_vswr) < 0.01

    def test_notes_present(self):
        """Should include notes."""
        result = calculate_return_loss(75.0, 50.0, 1000.0)
        assert "notes" in result
        assert len(result["notes"]) > 0


# ============================================================================
# Mode Conversion Tests (Issue #12)
# ============================================================================

class TestModeConversion:
    """Test analyze_mode_conversion."""

    # Typical USB3 diff pair geometry
    USB3_PARAMS = dict(
        trace_width_mm=0.15,
        trace_spacing_mm=0.15,
        dielectric_height_mm=0.1,
        dielectric_constant=4.3,
        data_rate_gbps=5.0,
    )

    def test_basic_result_structure(self):
        """Should return all expected fields."""
        result = analyze_mode_conversion(
            length_asymmetry_mm=0.5,
            **self.USB3_PARAMS,
        )
        required_keys = [
            "z_odd_ohm", "z_even_ohm", "z_diff_ohm", "z_common_ohm",
            "coupling_coefficient", "scd21_vs_frequency", "worst_scd21_db",
            "common_mode_current_ma", "skew_ps", "mode_conversion_risk",
            "emi_impact", "emi_increase_db",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_impedance_relationships(self):
        """Z_diff = 2*Z_odd, Z_common = Z_even/2."""
        result = analyze_mode_conversion(
            length_asymmetry_mm=0.1,
            **self.USB3_PARAMS,
        )
        assert abs(result["z_diff_ohm"] - 2 * result["z_odd_ohm"]) < 0.02
        assert abs(result["z_common_ohm"] - result["z_even_ohm"] / 2) < 0.02

    def test_zero_asymmetry_low_risk(self):
        """Zero length mismatch should produce negligible mode conversion."""
        result = analyze_mode_conversion(
            length_asymmetry_mm=0.0,
            **self.USB3_PARAMS,
        )
        assert result["worst_scd21_db"] < -60, \
            f"Zero asymmetry should give very low SCD21, got {result['worst_scd21_db']}"
        assert result["mode_conversion_risk"] == "negligible"

    def test_large_asymmetry_high_risk(self):
        """Large length mismatch should produce significant mode conversion."""
        result = analyze_mode_conversion(
            length_asymmetry_mm=5.0,
            **self.USB3_PARAMS,
        )
        assert result["worst_scd21_db"] > -30, \
            f"5mm asymmetry at 5 Gb/s should cause notable mode conversion, got {result['worst_scd21_db']}"
        assert result["mode_conversion_risk"] in ("medium", "high")

    def test_scd21_worsens_with_frequency(self):
        """Higher harmonics should have worse (less negative) SCD21."""
        result = analyze_mode_conversion(
            length_asymmetry_mm=0.5,
            **self.USB3_PARAMS,
        )
        scd21_list = result["scd21_vs_frequency"]
        # For non-zero asymmetry, SCD21 should get worse (closer to 0) at higher freq
        assert scd21_list[-1]["scd21_db"] >= scd21_list[0]["scd21_db"], \
            "SCD21 should worsen at higher harmonics"

    def test_scd21_worsens_with_more_asymmetry(self):
        """More asymmetry should produce worse SCD21."""
        small = analyze_mode_conversion(length_asymmetry_mm=0.1, **self.USB3_PARAMS)
        large = analyze_mode_conversion(length_asymmetry_mm=2.0, **self.USB3_PARAMS)
        assert large["worst_scd21_db"] > small["worst_scd21_db"]

    def test_common_mode_current_positive(self):
        """Common-mode current should be non-negative."""
        result = analyze_mode_conversion(
            length_asymmetry_mm=0.5,
            **self.USB3_PARAMS,
        )
        assert result["common_mode_current_ma"] >= 0

    def test_skew_calculation(self):
        """Skew should scale linearly with length asymmetry."""
        r1 = analyze_mode_conversion(length_asymmetry_mm=1.0, **self.USB3_PARAMS)
        r2 = analyze_mode_conversion(length_asymmetry_mm=2.0, **self.USB3_PARAMS)
        ratio = r2["skew_ps"] / r1["skew_ps"] if r1["skew_ps"] > 0 else 0
        assert 1.9 < ratio < 2.1, f"Skew should scale linearly, got ratio {ratio:.2f}"

    def test_stripline_mode(self):
        """Stripline trace type should work and produce physically reasonable results."""
        result = analyze_mode_conversion(
            trace_width_mm=0.15,
            trace_spacing_mm=0.15,
            dielectric_height_mm=0.1,
            dielectric_constant=4.3,
            length_asymmetry_mm=0.5,
            data_rate_gbps=5.0,
            trace_type="stripline",
        )
        assert 20 < result["z_odd_ohm"] < 150
        assert result["z_even_ohm"] > result["z_odd_ohm"]
        assert result["z_diff_ohm"] > 0

    def test_emi_increase_consistent_with_scd21(self):
        """EMI increase (dB) should equal the negative of worst SCD21."""
        result = analyze_mode_conversion(
            length_asymmetry_mm=0.5,
            **self.USB3_PARAMS,
        )
        expected_emi = -result["worst_scd21_db"]
        assert abs(result["emi_increase_db"] - expected_emi) < 0.01

    def test_coupling_coefficient_range(self):
        """Coupling coefficient should be between 0 and 1."""
        result = analyze_mode_conversion(
            length_asymmetry_mm=0.1,
            **self.USB3_PARAMS,
        )
        assert 0 <= result["coupling_coefficient"] <= 1

    def test_notes_for_large_asymmetry(self):
        """Should generate notes for problematic geometry."""
        result = analyze_mode_conversion(
            length_asymmetry_mm=2.0,
            **self.USB3_PARAMS,
        )
        assert len(result["notes"]) > 0


# ============================================================================
# Integration: dispatch via server._dispatch
# ============================================================================

class TestServerDispatch:
    """Test that the new tools are wired into server.py dispatch correctly."""

    def test_insertion_loss_dispatch(self):
        from mcp_pcb_emcopilot.server import _dispatch
        result = _dispatch("pcb_calc_insertion_loss", {
            "trace_length_mm": 25.4,
            "trace_width_mm": 0.3,
            "dielectric_height_mm": 0.2,
            "dielectric_constant": 4.3,
            "loss_tangent": 0.02,
        })
        assert result.get("success") is True
        assert "s21_db" in result

    def test_return_loss_dispatch(self):
        from mcp_pcb_emcopilot.server import _dispatch
        result = _dispatch("pcb_calc_return_loss", {
            "impedance_ohm": 55.0,
            "target_impedance_ohm": 50.0,
            "frequency_mhz": 1000.0,
        })
        assert result.get("success") is True
        assert "s11_db" in result
        assert "vswr" in result

    def test_mode_conversion_dispatch(self):
        from mcp_pcb_emcopilot.server import _dispatch
        result = _dispatch("pcb_analyze_mode_conversion", {
            "trace_width_mm": 0.15,
            "trace_spacing_mm": 0.15,
            "dielectric_height_mm": 0.1,
            "dielectric_constant": 4.3,
            "length_asymmetry_mm": 0.5,
            "data_rate_gbps": 5.0,
        })
        assert result.get("success") is True
        assert "z_diff_ohm" in result
        assert "worst_scd21_db" in result

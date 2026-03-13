"""Tests for power plane cavity resonance analyzer.

Covers Issue #26:
- Resonant mode calculation for rectangular plane pairs
- Q factor and peak impedance
- Problematic mode detection near common clocks
- Decoupling capacitor recommendations
- Edge cases and dispatch integration

15+ tests total.
"""
from __future__ import annotations

import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from mcp_pcb_emcopilot.analyzers.power_integrity.cavity_resonance import (
    analyze_cavity_resonance,
    _format_cap,
)

# Speed of light for reference calculations
C0 = 299792458.0


# =============================================================================
# Basic mode calculation
# =============================================================================

def test_first_resonance_100x80_board():
    """First resonant mode of 100x80mm board should match TM10 analytical value."""
    width = 100.0  # mm
    height = 80.0  # mm
    er = 4.3
    h_mm = 0.2  # dielectric height

    result = analyze_cavity_resonance(
        plane_width_mm=width,
        plane_height_mm=height,
        dielectric_height_mm=h_mm,
        dielectric_constant=er,
    )

    assert result["success"] is True
    assert result["total_modes_found"] > 0
    assert result["first_resonance_mhz"] is not None

    # Analytical first resonance: f_10 = c / (2*sqrt(er)) * (1/a)
    # where a = longest dimension = 100mm = 0.1m
    a = width / 1000.0
    expected_f10 = (C0 / (2 * math.sqrt(er))) / a
    expected_mhz = expected_f10 / 1e6

    # Check TM10 mode
    first_mode = result["modes"][0]
    assert first_mode["mode"] == "TM10"
    assert abs(first_mode["frequency_mhz"] - expected_mhz) < 1.0, \
        f"Expected ~{expected_mhz:.1f} MHz, got {first_mode['frequency_mhz']} MHz"


def test_first_resonance_50x50_square():
    """Square board: TM10 and TM01 should have equal frequency."""
    result = analyze_cavity_resonance(
        plane_width_mm=50.0,
        plane_height_mm=50.0,
        dielectric_height_mm=0.1,
        dielectric_constant=4.3,
    )

    assert result["success"] is True
    # For square board, TM10 and TM01 are degenerate
    modes = result["modes"]
    assert len(modes) >= 2
    # First two modes should have same frequency
    assert abs(modes[0]["frequency_mhz"] - modes[1]["frequency_mhz"]) < 0.1


def test_mode_ordering():
    """Modes should be sorted by ascending frequency."""
    result = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=60.0,
        dielectric_height_mm=0.2,
        dielectric_constant=4.3,
    )

    modes = result["modes"]
    for i in range(len(modes) - 1):
        assert modes[i]["frequency_hz"] <= modes[i + 1]["frequency_hz"], \
            f"Mode {modes[i]['mode']} at {modes[i]['frequency_hz']} Hz > " \
            f"mode {modes[i+1]['mode']} at {modes[i+1]['frequency_hz']} Hz"


def test_dc_mode_excluded():
    """TM00 (DC) mode should not appear."""
    result = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=80.0,
        dielectric_height_mm=0.2,
        dielectric_constant=4.3,
    )

    for mode in result["modes"]:
        assert mode["mode"] != "TM00", "DC mode (TM00) should be excluded"


def test_dielectric_constant_effect():
    """Higher Er should lower resonant frequencies."""
    result_low_er = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=80.0,
        dielectric_height_mm=0.2,
        dielectric_constant=3.0,
    )
    result_high_er = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=80.0,
        dielectric_height_mm=0.2,
        dielectric_constant=10.0,
    )

    assert result_low_er["first_resonance_mhz"] > result_high_er["first_resonance_mhz"], \
        "Higher Er should produce lower first resonance frequency"


def test_larger_board_lower_frequency():
    """Larger board should have lower first resonance."""
    result_small = analyze_cavity_resonance(
        plane_width_mm=50.0,
        plane_height_mm=40.0,
        dielectric_height_mm=0.2,
        dielectric_constant=4.3,
    )
    result_large = analyze_cavity_resonance(
        plane_width_mm=200.0,
        plane_height_mm=150.0,
        dielectric_height_mm=0.2,
        dielectric_constant=4.3,
    )

    assert result_small["first_resonance_mhz"] > result_large["first_resonance_mhz"]


# =============================================================================
# Q factor and impedance
# =============================================================================

def test_q_factor_positive():
    """All modes should have positive Q factor."""
    result = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=80.0,
        dielectric_height_mm=0.2,
        dielectric_constant=4.3,
    )

    for mode in result["modes"]:
        assert mode["q_factor"] > 0, f"Mode {mode['mode']} has non-positive Q: {mode['q_factor']}"


def test_peak_impedance_positive():
    """All modes should have positive peak impedance."""
    result = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=80.0,
        dielectric_height_mm=0.2,
        dielectric_constant=4.3,
    )

    for mode in result["modes"]:
        assert mode["peak_impedance_ohm"] >= 0, \
            f"Mode {mode['mode']} has negative impedance: {mode['peak_impedance_ohm']}"


def test_loss_tangent_affects_q():
    """Higher loss tangent should reduce Q factor."""
    result_low_loss = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=80.0,
        dielectric_height_mm=0.2,
        dielectric_constant=4.3,
        loss_tangent=0.002,  # low-loss material
    )
    result_high_loss = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=80.0,
        dielectric_height_mm=0.2,
        dielectric_constant=4.3,
        loss_tangent=0.05,  # high-loss material
    )

    # Compare Q factor of first mode
    q_low = result_low_loss["modes"][0]["q_factor"]
    q_high = result_high_loss["modes"][0]["q_factor"]
    assert q_low > q_high, \
        f"Low loss Q ({q_low}) should be > high loss Q ({q_high})"


def test_bandwidth_inversely_proportional_to_q():
    """Bandwidth should be approximately f/Q."""
    result = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=80.0,
        dielectric_height_mm=0.2,
        dielectric_constant=4.3,
    )

    for mode in result["modes"][:5]:
        if mode["q_factor"] > 0:
            expected_bw = mode["frequency_mhz"] / mode["q_factor"]
            assert abs(mode["bandwidth_mhz"] - expected_bw) < 0.2, \
                f"Mode {mode['mode']}: BW {mode['bandwidth_mhz']} != f/Q {expected_bw:.1f}"


# =============================================================================
# Problematic mode detection
# =============================================================================

def test_problematic_mode_detection():
    """Should detect modes near common clock frequencies."""
    # Use a board size that gives a resonance near 100 MHz
    # f_10 = c / (2*sqrt(er)*a), for f=100MHz, er=4.3:
    # a = c / (2*sqrt(4.3)*100e6) = 0.722m = 722mm
    # Use a board that gives a mode near one of the standard clocks
    result = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=80.0,
        dielectric_height_mm=0.2,
        dielectric_constant=4.3,
        max_frequency_hz=5e9,
    )

    # The result should have the problematic_modes field
    assert "problematic_modes" in result
    assert isinstance(result["problematic_modes"], list)

    # Each problematic mode should have near_clock_mhz and offset_percent
    for pm in result["problematic_modes"]:
        assert "near_clock_mhz" in pm
        assert "offset_percent" in pm
        assert pm["offset_percent"] < 5.0  # within 5%


def test_no_false_problematic_modes():
    """Problematic modes should only include those within 5% of a clock."""
    result = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=80.0,
        dielectric_height_mm=0.2,
        dielectric_constant=4.3,
    )

    for pm in result["problematic_modes"]:
        # Verify that the mode is actually within 5% of the stated clock
        near_clk_hz = pm["near_clock_mhz"] * 1e6
        mode_hz = pm["frequency_hz"]
        offset = abs(mode_hz - near_clk_hz) / near_clk_hz * 100
        assert offset < 5.0, f"Mode {pm['mode']} offset {offset:.1f}% > 5%"


# =============================================================================
# Decoupling recommendations
# =============================================================================

def test_decoupling_recommendations_present():
    """Should provide decoupling capacitor recommendations."""
    result = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=80.0,
        dielectric_height_mm=0.2,
        dielectric_constant=4.3,
    )

    assert len(result["decoupling_recommendations"]) > 0
    rec = result["decoupling_recommendations"][0]
    assert "mode" in rec
    assert "frequency_mhz" in rec
    assert "suggested_cap_nf" in rec
    assert "suggested_cap_value" in rec
    assert rec["suggested_cap_nf"] > 0


def test_decoupling_cap_values_reasonable():
    """Recommended cap values should be reasonable for the frequencies."""
    result = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=80.0,
        dielectric_height_mm=0.2,
        dielectric_constant=4.3,
    )

    for rec in result["decoupling_recommendations"]:
        # Cap value should decrease with frequency (C = 1/(4*pi^2*f^2*ESL))
        f = rec["frequency_mhz"] * 1e6
        esl = 1e-9
        expected_c = 1.0 / (4 * math.pi ** 2 * f ** 2 * esl)
        expected_nf = expected_c * 1e9
        assert abs(rec["suggested_cap_nf"] - expected_nf) < 0.01


# =============================================================================
# Format helper
# =============================================================================

def test_format_cap_uf():
    """Cap formatting: microfarads."""
    assert _format_cap(1e-6) == "1.0uF"
    assert _format_cap(10e-6) == "10.0uF"
    assert _format_cap(4.7e-6) == "4.7uF"


def test_format_cap_nf():
    """Cap formatting: nanofarads."""
    assert _format_cap(100e-9) == "100.0nF"
    assert _format_cap(1e-9) == "1.0nF"
    assert _format_cap(2.2e-9) == "2.2nF"


def test_format_cap_pf():
    """Cap formatting: picofarads."""
    assert _format_cap(100e-12) == "100.0pF"
    assert _format_cap(10e-12) == "10.0pF"


# =============================================================================
# Edge cases
# =============================================================================

def test_max_frequency_limits_modes():
    """Setting lower max_frequency_hz should return fewer modes."""
    result_low = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=80.0,
        dielectric_height_mm=0.2,
        dielectric_constant=4.3,
        max_frequency_hz=1e9,
    )
    result_high = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=80.0,
        dielectric_height_mm=0.2,
        dielectric_constant=4.3,
        max_frequency_hz=5e9,
    )

    assert result_low["total_modes_found"] <= result_high["total_modes_found"]


def test_narrow_board():
    """Very narrow board (1mm x 100mm) should still work."""
    result = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=1.0,
        dielectric_height_mm=0.1,
        dielectric_constant=4.3,
    )

    assert result["success"] is True
    assert result["total_modes_found"] > 0
    # TM01 frequency should be very high since b is tiny
    # TM10 should dominate as first mode


def test_very_small_board():
    """Very small board should have high first resonance."""
    result = analyze_cavity_resonance(
        plane_width_mm=5.0,
        plane_height_mm=5.0,
        dielectric_height_mm=0.1,
        dielectric_constant=4.3,
        max_frequency_hz=50e9,  # Need high limit for small board
    )

    assert result["success"] is True
    # 5mm board: f_10 = c / (2*sqrt(4.3)*0.005) = ~14.4 GHz
    assert result["first_resonance_mhz"] > 10000  # > 10 GHz


def test_return_structure():
    """Verify the complete return structure."""
    result = analyze_cavity_resonance(
        plane_width_mm=100.0,
        plane_height_mm=80.0,
        dielectric_height_mm=0.2,
        dielectric_constant=4.3,
    )

    # Top-level keys
    assert "success" in result
    assert "plane_dimensions_mm" in result
    assert "dielectric" in result
    assert "total_modes_found" in result
    assert "modes" in result
    assert "problematic_modes" in result
    assert "decoupling_recommendations" in result
    assert "first_resonance_mhz" in result

    # Plane dimensions
    assert result["plane_dimensions_mm"]["width"] == 100.0
    assert result["plane_dimensions_mm"]["height"] == 80.0

    # Dielectric info
    assert result["dielectric"]["height_mm"] == 0.2
    assert result["dielectric"]["er"] == 4.3
    assert result["dielectric"]["loss_tangent"] == 0.02

    # Mode structure
    mode = result["modes"][0]
    assert "mode" in mode
    assert "frequency_hz" in mode
    assert "frequency_mhz" in mode
    assert "q_factor" in mode
    assert "peak_impedance_ohm" in mode
    assert "bandwidth_mhz" in mode


# =============================================================================
# Dispatch integration test
# =============================================================================

def test_dispatch_cavity_resonance():
    """Test pcb_analyze_cavity_resonance through server dispatch."""
    from mcp_pcb_emcopilot.server import _dispatch

    result = _dispatch("pcb_analyze_cavity_resonance", {
        "plane_width_mm": 100.0,
        "plane_height_mm": 80.0,
        "dielectric_height_mm": 0.2,
        "dielectric_constant": 4.3,
    })

    assert result["success"] is True
    assert result["total_modes_found"] > 0
    assert result["first_resonance_mhz"] is not None


def test_tool_registration():
    """Verify pcb_analyze_cavity_resonance appears in tool list."""
    import asyncio
    from mcp_pcb_emcopilot.server import list_tools

    tools = asyncio.run(list_tools())
    tool_names = {t.name for t in tools}

    assert "pcb_analyze_cavity_resonance" in tool_names, \
        "pcb_analyze_cavity_resonance not found in tool list"


# =============================================================================
# Main runner
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("Cavity Resonance Analyzer Tests (Issue #26)")
    print("=" * 70)

    tests = [
        ("First resonance 100x80", test_first_resonance_100x80_board),
        ("Square board degenerate modes", test_first_resonance_50x50_square),
        ("Mode ordering", test_mode_ordering),
        ("DC mode excluded", test_dc_mode_excluded),
        ("Er effect", test_dielectric_constant_effect),
        ("Board size effect", test_larger_board_lower_frequency),
        ("Q factor positive", test_q_factor_positive),
        ("Peak impedance positive", test_peak_impedance_positive),
        ("Loss tangent vs Q", test_loss_tangent_affects_q),
        ("Bandwidth ~ f/Q", test_bandwidth_inversely_proportional_to_q),
        ("Problematic mode detection", test_problematic_mode_detection),
        ("No false problematic modes", test_no_false_problematic_modes),
        ("Decoupling recommendations", test_decoupling_recommendations_present),
        ("Cap values reasonable", test_decoupling_cap_values_reasonable),
        ("Format cap uF", test_format_cap_uf),
        ("Format cap nF", test_format_cap_nf),
        ("Format cap pF", test_format_cap_pf),
        ("Max frequency limits modes", test_max_frequency_limits_modes),
        ("Narrow board", test_narrow_board),
        ("Very small board", test_very_small_board),
        ("Return structure", test_return_structure),
        ("Dispatch integration", test_dispatch_cavity_resonance),
        ("Tool registration", test_tool_registration),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        try:
            test_fn()
            passed += 1
            print("  PASS")
        except Exception as e:
            print(f"  FAIL: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 70}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    print(f"{'=' * 70}")

    sys.exit(1 if failed > 0 else 0)

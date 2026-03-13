"""Tests for current density analysis, ground stitching, clock EMI, and SMPS EMI.

Covers Issues #14 and #15:
- Return current density estimation and ground stitch optimization
- Crystal oscillator EMI and SMPS harmonic analysis

Tests all 4 new MCP tools through their dispatch handlers.
"""

import json
import math
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# =============================================================================
# Issue #14: Return current density and ground stitching
# =============================================================================

def test_return_current_density_basic():
    """Test basic return current density analysis."""
    from mcp_pcb_emcopilot.analyzers.emc.current_density import analyze_return_current_density

    result = analyze_return_current_density(
        trace_x_start=10, trace_y_start=25,
        trace_x_end=40, trace_y_end=25,
        plane_width_mm=50, plane_height_mm=50,
        frequency_mhz=100,
    )

    assert "current_distribution" in result
    assert len(result["current_distribution"]) == 10  # 10x10 grid
    assert len(result["current_distribution"][0]) == 10
    assert result["max_density_ratio"] >= 1.0
    assert result["current_spreading_mm"] > 0
    assert result["transition_frequency_mhz"] > 0
    assert result["frequency_regime"] in ("resistive", "transition", "inductive")
    assert result["trace_length_mm"] > 0
    assert len(result["notes"]) > 0

    # Peak density should be at or near 1.0 (normalized)
    # Grid sampling may not land exactly on the peak, so allow small tolerance
    grid = result["current_distribution"]
    max_val = max(max(row) for row in grid)
    assert abs(max_val - 1.0) < 0.02, f"Expected peak~1.0, got {max_val}"

    print(f"  Regime: {result['frequency_regime']}, spreading: {result['current_spreading_mm']}mm")
    print(f"  Density ratio: {result['max_density_ratio']}:1")
    print(f"  Transition freq: {result['transition_frequency_mhz']} MHz")
    print("  PASS: Basic return current density analysis works")


def test_return_current_density_with_gaps():
    """Test current density with plane gaps (crowding detection)."""
    from mcp_pcb_emcopilot.analyzers.emc.current_density import analyze_return_current_density

    gaps = [
        {"x_start_mm": 24, "y_start_mm": 0, "x_end_mm": 26, "y_end_mm": 50, "width_mm": 2},
    ]
    result = analyze_return_current_density(
        trace_x_start=10, trace_y_start=25,
        trace_x_end=40, trace_y_end=25,
        plane_width_mm=50, plane_height_mm=50,
        frequency_mhz=500,
        plane_gaps=gaps,
    )

    assert len(result["crowding_locations"]) > 0
    # The gap is right at trace center -- should show high crowding
    gap_crowding = [c for c in result["crowding_locations"] if "gap_center_x_mm" in c]
    assert len(gap_crowding) > 0
    assert gap_crowding[0]["crowding_factor"] > 1.0

    print(f"  Found {len(result['crowding_locations'])} crowding locations")
    for c in result["crowding_locations"][:3]:
        print(f"    {c}")
    print("  PASS: Gap crowding detection works")


def test_return_current_density_dc():
    """Test DC (0 MHz) regime -- current should spread broadly."""
    from mcp_pcb_emcopilot.analyzers.emc.current_density import analyze_return_current_density

    result = analyze_return_current_density(
        trace_x_start=20, trace_y_start=20,
        trace_x_end=30, trace_y_end=20,
        plane_width_mm=50, plane_height_mm=50,
        frequency_mhz=0,
    )

    assert result["frequency_regime"] == "resistive"
    assert result["current_spreading_mm"] > 5  # broad spreading at DC
    print(f"  DC spreading: {result['current_spreading_mm']}mm (regime: {result['frequency_regime']})")
    print("  PASS: DC regime works correctly")


def test_return_current_density_high_freq():
    """Test high frequency -- current should concentrate under trace."""
    from mcp_pcb_emcopilot.analyzers.emc.current_density import analyze_return_current_density

    result = analyze_return_current_density(
        trace_x_start=20, trace_y_start=25,
        trace_x_end=30, trace_y_end=25,
        plane_width_mm=50, plane_height_mm=50,
        frequency_mhz=1000,
    )

    assert result["frequency_regime"] == "inductive"
    assert result["current_spreading_mm"] < 5  # tight concentration
    print(f"  1 GHz spreading: {result['current_spreading_mm']}mm (regime: {result['frequency_regime']})")
    print("  PASS: High-frequency concentration works correctly")


def test_ground_stitching_basic():
    """Test basic ground stitching optimization."""
    from mcp_pcb_emcopilot.analyzers.emc.current_density import optimize_ground_stitching

    result = optimize_ground_stitching(
        plane_width_mm=50, plane_height_mm=40,
        max_frequency_mhz=1000, dielectric_constant=4.3,
    )

    assert "suggested_via_locations" in result
    assert result["total_new_vias"] > 0
    assert result["spacing_mm"] > 0
    assert result["density_per_cm2"] > 0
    assert result["wavelength_mm"] > 0
    assert len(result["coverage_analysis"]) == 4  # 4 quadrants
    assert len(result["notes"]) > 0

    # Spacing should be <= lambda/20
    lambda_mm = result["wavelength_mm"]
    assert result["spacing_mm"] <= lambda_mm / 20.0 + 0.1  # small tolerance

    print(f"  Suggested vias: {result['total_new_vias']}, spacing: {result['spacing_mm']}mm")
    print(f"  Wavelength: {result['wavelength_mm']}mm, density: {result['density_per_cm2']}/cm2")
    print("  PASS: Basic ground stitching works")


def test_ground_stitching_with_gaps():
    """Test ground stitching with plane gaps -- should add gap stitch vias."""
    from mcp_pcb_emcopilot.analyzers.emc.current_density import optimize_ground_stitching

    gaps = [
        {"x_start_mm": 20, "y_start_mm": 0, "x_end_mm": 20, "y_end_mm": 40, "width_mm": 2},
    ]
    result = optimize_ground_stitching(
        plane_width_mm=50, plane_height_mm=40,
        max_frequency_mhz=500, dielectric_constant=4.3,
        plane_gaps=gaps,
    )

    gap_vias = [v for v in result["suggested_via_locations"] if v.get("purpose") == "gap_stitching"]
    assert len(gap_vias) > 0, "Expected gap stitching vias"

    print(f"  Total vias: {result['total_new_vias']}, gap stitch vias: {len(gap_vias)}")
    print("  PASS: Gap stitching vias generated")


def test_ground_stitching_with_existing_vias():
    """Test that existing vias are respected."""
    from mcp_pcb_emcopilot.analyzers.emc.current_density import optimize_ground_stitching

    existing = [
        {"x_mm": 10, "y_mm": 10},
        {"x_mm": 20, "y_mm": 20},
        {"x_mm": 30, "y_mm": 30},
    ]
    result = optimize_ground_stitching(
        plane_width_mm=50, plane_height_mm=40,
        max_frequency_mhz=500, dielectric_constant=4.3,
        existing_vias=existing,
    )

    assert result["existing_vias_count"] == 3
    # Suggested vias should not overlap existing
    for sv in result["suggested_via_locations"]:
        for ev in existing:
            dist = math.sqrt((sv["x_mm"] - ev["x_mm"]) ** 2 + (sv["y_mm"] - ev["y_mm"]) ** 2)
            assert dist >= 0.9, f"Suggested via too close to existing: {dist:.2f}mm"

    print(f"  Existing: {result['existing_vias_count']}, new: {result['total_new_vias']}")
    print("  PASS: Existing vias respected")


# =============================================================================
# Issue #15: Clock EMI and SMPS EMI
# =============================================================================

def test_clock_emi_basic():
    """Test basic clock EMI analysis."""
    from mcp_pcb_emcopilot.analyzers.emc.clock_emi_analyzer import analyze_clock_emi

    result = analyze_clock_emi(
        frequency_mhz=100,
        voltage_v=3.3,
        rise_time_ps=500,
        current_ma=10,
        loop_area_mm2=10,
    )

    assert "harmonics" in result
    assert len(result["harmonics"]) > 0
    assert result["fundamental_frequency_mhz"] == 100
    assert result["risk_level"] in ("pass", "marginal", "fail")
    assert result["overall_compliant"] in (True, False)
    assert result["envelope_f1_mhz"] > 0
    assert result["envelope_f2_mhz"] > 0
    assert result["spread_spectrum_reduction_db"] == 0.0

    # Check harmonic structure
    h1 = result["harmonics"][0]
    assert h1["harmonic_number"] == 1
    assert h1["frequency_mhz"] == 100
    assert h1["amplitude_v"] > 0
    assert "limit_dbuv_m" in h1
    assert "margin_db" in h1

    print(f"  Harmonics: {result['num_harmonics_analyzed']}, risk: {result['risk_level']}")
    print(f"  Worst margin: {result['worst_margin_db']}dB at {result['worst_frequency_mhz']}MHz")
    print("  PASS: Basic clock EMI works")


def test_clock_emi_spread_spectrum():
    """Test that spread spectrum reduces emissions."""
    from mcp_pcb_emcopilot.analyzers.emc.clock_emi_analyzer import analyze_clock_emi

    result_no_ss = analyze_clock_emi(
        frequency_mhz=100, rise_time_ps=500,
        current_ma=10, loop_area_mm2=10,
        spread_spectrum_percent=0,
    )
    result_ss = analyze_clock_emi(
        frequency_mhz=100, rise_time_ps=500,
        current_ma=10, loop_area_mm2=10,
        spread_spectrum_percent=1.0,
    )

    assert result_ss["spread_spectrum_reduction_db"] > 0
    # With SS, worst margin should be better (higher)
    if result_no_ss["worst_margin_db"] is not None and result_ss["worst_margin_db"] is not None:
        assert result_ss["worst_margin_db"] >= result_no_ss["worst_margin_db"]

    print(f"  No SS margin: {result_no_ss['worst_margin_db']}dB")
    print(f"  With SS margin: {result_ss['worst_margin_db']}dB (reduction: {result_ss['spread_spectrum_reduction_db']}dB)")
    print("  PASS: Spread spectrum reduces emissions")


def test_clock_emi_fast_rise_time():
    """Test that faster rise time produces more high-frequency content."""
    from mcp_pcb_emcopilot.analyzers.emc.clock_emi_analyzer import analyze_clock_emi

    result_slow = analyze_clock_emi(frequency_mhz=100, rise_time_ps=2000)
    result_fast = analyze_clock_emi(frequency_mhz=100, rise_time_ps=100)

    # Fast rise time should have worse (lower) margin
    if result_slow["worst_margin_db"] is not None and result_fast["worst_margin_db"] is not None:
        assert result_fast["worst_margin_db"] <= result_slow["worst_margin_db"]

    # f2 corner should be higher for fast rise time
    assert result_fast["envelope_f2_mhz"] > result_slow["envelope_f2_mhz"]

    print(f"  Slow (2ns) f2: {result_slow['envelope_f2_mhz']}MHz, margin: {result_slow['worst_margin_db']}dB")
    print(f"  Fast (100ps) f2: {result_fast['envelope_f2_mhz']}MHz, margin: {result_fast['worst_margin_db']}dB")
    print("  PASS: Rise time affects harmonic content correctly")


def test_clock_emi_cispr():
    """Test clock EMI with CISPR standard."""
    from mcp_pcb_emcopilot.analyzers.emc.clock_emi_analyzer import analyze_clock_emi

    result = analyze_clock_emi(
        frequency_mhz=25, rise_time_ps=500,
        standard="cispr_b",
    )

    assert result["standard"] == "CISPR_B"
    # CISPR limits are 40 dBuV/m from 30-230 MHz
    for h in result["harmonics"]:
        if 30 <= h["frequency_mhz"] <= 230:
            assert h["limit_dbuv_m"] == 40.0

    print(f"  CISPR analysis: {result['num_harmonics_analyzed']} harmonics, risk: {result['risk_level']}")
    print("  PASS: CISPR standard limits applied correctly")


def test_smps_emi_basic():
    """Test basic SMPS EMI analysis."""
    from mcp_pcb_emcopilot.analyzers.emc.clock_emi_analyzer import analyze_smps_emi

    result = analyze_smps_emi(
        switching_freq_khz=500,
        input_voltage_v=12,
        output_voltage_v=3.3,
        output_current_a=2,
    )

    assert "harmonics" in result
    assert len(result["harmonics"]) > 0
    assert result["switching_frequency_khz"] == 500
    assert result["risk_level"] in ("pass", "marginal", "fail")
    assert 0 < result["duty_cycle"] < 1

    # Buck converter: D = Vout/Vin = 3.3/12 = 0.275
    assert abs(result["duty_cycle"] - 3.3 / 12.0) < 0.01

    assert result["filter_recommendations"]["input_filter"]["corner_frequency_khz"] > 0
    assert result["input_current_avg_a"] > 0
    assert result["output_ripple_a"] > 0

    # Check harmonics have input/output breakdown
    h1 = result["harmonics"][0]
    assert "input_emission_dbuv_m" in h1
    assert "output_emission_dbuv_m" in h1
    assert "dominant_source" in h1

    print(f"  Duty cycle: {result['duty_cycle']}, topology: {result['topology']}")
    print(f"  Harmonics: {result['num_harmonics_analyzed']}, risk: {result['risk_level']}")
    print(f"  Filter corner: {result['filter_recommendations']['input_filter']['corner_frequency_khz']}kHz")
    print("  PASS: Basic SMPS EMI works")


def test_smps_emi_boost():
    """Test SMPS EMI with boost topology."""
    from mcp_pcb_emcopilot.analyzers.emc.clock_emi_analyzer import analyze_smps_emi

    result = analyze_smps_emi(
        switching_freq_khz=300,
        input_voltage_v=5,
        output_voltage_v=12,
        output_current_a=1,
        topology="boost",
    )

    assert result["topology"] == "boost"
    # Boost: D = 1 - Vin/Vout = 1 - 5/12 = 0.583
    expected_d = 1.0 - 5.0 / 12.0
    assert abs(result["duty_cycle"] - expected_d) < 0.01

    print(f"  Boost D={result['duty_cycle']:.3f} (expected {expected_d:.3f})")
    print(f"  Risk: {result['risk_level']}, worst margin: {result['worst_margin_db']}dB")
    print("  PASS: Boost topology works")


def test_smps_emi_loop_area_impact():
    """Test that larger loop area increases emissions."""
    from mcp_pcb_emcopilot.analyzers.emc.clock_emi_analyzer import analyze_smps_emi

    # Use 2000 kHz switching so harmonics reach above 30 MHz (h15 = 30 MHz)
    result_small = analyze_smps_emi(
        switching_freq_khz=2000, input_voltage_v=12,
        output_voltage_v=3.3, output_current_a=2,
        input_loop_area_mm2=5, output_loop_area_mm2=5,
    )
    result_large = analyze_smps_emi(
        switching_freq_khz=2000, input_voltage_v=12,
        output_voltage_v=3.3, output_current_a=2,
        input_loop_area_mm2=100, output_loop_area_mm2=100,
    )

    # Larger loop should have worse margin
    if result_small["worst_margin_db"] is not None and result_large["worst_margin_db"] is not None:
        assert result_large["worst_margin_db"] <= result_small["worst_margin_db"]

    print(f"  Small loop margin: {result_small['worst_margin_db']}dB")
    print(f"  Large loop margin: {result_large['worst_margin_db']}dB")
    print("  PASS: Loop area impacts emissions correctly")


# =============================================================================
# Tool dispatch tests
# =============================================================================

def test_dispatch_return_current_density():
    """Test pcb_analyze_return_current through dispatch."""
    from mcp_pcb_emcopilot.server import _dispatch

    result = _dispatch("pcb_analyze_return_current", {
        "trace_height_mm": 0.1,
        "signal_current_ma": 100,
        "analysis_width_mm": 5.0,
        "num_points": 20,
    })

    assert result["peak_density_ma_per_mm"] > 0
    assert "density_ma_per_mm" in result
    assert len(result["density_ma_per_mm"]) == 20

    print(f"  Dispatch OK: peak={result['peak_density_ma_per_mm']:.1f} mA/mm")
    print("  PASS: pcb_analyze_return_current dispatch works")


def test_dispatch_ground_stitching():
    """Test pcb_analyze_ground_stitch through dispatch."""
    from mcp_pcb_emcopilot.server import _dispatch

    result = _dispatch("pcb_analyze_ground_stitch", {
        "max_frequency_hz": 1e9,
        "dielectric_constant": 4.3,
    })

    assert result["recommended_spacing_mm"] > 0

    print(f"  Dispatch OK: spacing={result['recommended_spacing_mm']:.2f}mm")
    print("  PASS: pcb_analyze_ground_stitch dispatch works")


def test_dispatch_clock_emi():
    """Test pcb_analyze_clock_emi through dispatch."""
    from mcp_pcb_emcopilot.server import _dispatch

    result = _dispatch("pcb_analyze_clock_emi", {
        "clock_frequency_mhz": 100,
        "rise_time_ns": 0.5,
    })

    assert "harmonics" in result
    assert result["pass_fail"] in ("PASS", "FAIL")
    assert result["worst_frequency_mhz"] > 0

    print(f"  Dispatch OK: {len(result['harmonics'])} harmonics, pass_fail={result['pass_fail']}")
    print("  PASS: pcb_analyze_clock_emi dispatch works")


def test_dispatch_smps_emi():
    """Test pcb_analyze_smps_emi through dispatch."""
    from mcp_pcb_emcopilot.server import _dispatch

    result = _dispatch("pcb_analyze_smps_emi", {
        "switching_frequency_khz": 500,
        "input_voltage_v": 12,
        "output_voltage_v": 3.3,
        "output_current_a": 2,
    })

    assert "harmonics" in result
    assert result["pass_fail"] in ("PASS", "FAIL")
    assert "power_stage" in result

    print(f"  Dispatch OK: pass_fail={result['pass_fail']}")
    print("  PASS: pcb_analyze_smps_emi dispatch works")


# =============================================================================
# Tool registration test
# =============================================================================

def test_tool_registration():
    """Verify all 4 new tools appear in the tool list."""
    import asyncio
    from mcp_pcb_emcopilot.server import list_tools

    tools = asyncio.run(list_tools())
    tool_names = {t.name for t in tools}

    expected = {
        "pcb_analyze_return_current",
        "pcb_analyze_ground_stitch",
        "pcb_analyze_clock_emi",
        "pcb_analyze_smps_emi",
    }

    missing = expected - tool_names
    assert not missing, f"Missing tools: {missing}"
    print(f"  All 4 new tools registered (total tools: {len(tools)})")
    print("  PASS: Tool registration verified")


# =============================================================================
# Edge cases
# =============================================================================

def test_edge_cases():
    """Test edge cases: zero frequency, tiny plane, zero current, etc."""
    from mcp_pcb_emcopilot.analyzers.emc.current_density import (
        analyze_return_current_density, optimize_ground_stitching,
    )
    from mcp_pcb_emcopilot.analyzers.emc.clock_emi_analyzer import (
        analyze_clock_emi, analyze_smps_emi,
    )

    # Zero-length trace
    r = analyze_return_current_density(
        trace_x_start=10, trace_y_start=10,
        trace_x_end=10, trace_y_end=10,
        plane_width_mm=50, plane_height_mm=50,
        frequency_mhz=100,
    )
    assert r["trace_length_mm"] <= 0.01
    print("  Zero-length trace: OK")

    # Very small plane
    r = optimize_ground_stitching(
        plane_width_mm=2, plane_height_mm=2,
        max_frequency_mhz=100, dielectric_constant=4.3,
    )
    assert r["total_new_vias"] >= 4  # at least corners
    print("  Small plane stitching: OK")

    # Very high frequency stitching
    r = optimize_ground_stitching(
        plane_width_mm=50, plane_height_mm=50,
        max_frequency_mhz=10000, dielectric_constant=4.3,
    )
    assert r["spacing_mm"] >= 1.0  # respects minimum
    print("  High-freq stitching (min spacing): OK")

    # Very low frequency clock (all harmonics below 30 MHz)
    r = analyze_clock_emi(frequency_mhz=1)
    assert len(r["harmonics"]) > 0
    print("  Low-freq clock: OK")

    # SMPS with equal Vin/Vout (D=1 for boost, clamped)
    r = analyze_smps_emi(
        switching_freq_khz=500, input_voltage_v=5,
        output_voltage_v=5, output_current_a=1,
        topology="boost",
    )
    assert 0 < r["duty_cycle"] < 1
    print("  Equal Vin/Vout boost: OK")

    # Buck-boost topology
    r = analyze_smps_emi(
        switching_freq_khz=300, input_voltage_v=12,
        output_voltage_v=5, output_current_a=2,
        topology="buck_boost",
    )
    assert r["topology"] == "buck_boost"
    expected_d = 5.0 / (12.0 + 5.0)
    assert abs(r["duty_cycle"] - expected_d) < 0.01
    print("  Buck-boost topology: OK")

    print("  PASS: All edge cases handled correctly")


# =============================================================================
# FCC limit verification
# =============================================================================

def test_fcc_limits():
    """Verify FCC Class B limits are applied correctly."""
    from mcp_pcb_emcopilot.analyzers.emc.clock_emi_analyzer import analyze_clock_emi

    # Use a frequency where we can check specific limit bands
    # 25 MHz clock: harmonics at 25, 50, 75, 100, 125, ...
    result = analyze_clock_emi(frequency_mhz=25, standard="fcc_b")

    for h in result["harmonics"]:
        f = h["frequency_mhz"]
        limit = h["limit_dbuv_m"]
        if 30 <= f < 88:
            assert limit == 40.0, f"Expected 40 dBuV/m at {f}MHz, got {limit}"
        elif 88 <= f < 216:
            assert limit == 43.5, f"Expected 43.5 dBuV/m at {f}MHz, got {limit}"
        elif 216 <= f < 960:
            assert limit == 46.0, f"Expected 46 dBuV/m at {f}MHz, got {limit}"
        elif f >= 960:
            assert limit == 54.0, f"Expected 54 dBuV/m at {f}MHz, got {limit}"

    print("  FCC Class B limits: 40/43.5/46/54 dBuV/m applied correctly")
    print("  PASS: FCC limit verification passed")


# =============================================================================
# Main runner
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("Current Density, Ground Stitching, Clock EMI & SMPS EMI Tests")
    print("(Issues #14 and #15)")
    print("=" * 70)

    tests = [
        # Issue #14: Return current density
        ("Current density: basic", test_return_current_density_basic),
        ("Current density: with gaps", test_return_current_density_with_gaps),
        ("Current density: DC regime", test_return_current_density_dc),
        ("Current density: high freq", test_return_current_density_high_freq),
        ("Ground stitching: basic", test_ground_stitching_basic),
        ("Ground stitching: with gaps", test_ground_stitching_with_gaps),
        ("Ground stitching: existing vias", test_ground_stitching_with_existing_vias),

        # Issue #15: Clock and SMPS EMI
        ("Clock EMI: basic", test_clock_emi_basic),
        ("Clock EMI: spread spectrum", test_clock_emi_spread_spectrum),
        ("Clock EMI: rise time", test_clock_emi_fast_rise_time),
        ("Clock EMI: CISPR limits", test_clock_emi_cispr),
        ("SMPS EMI: basic", test_smps_emi_basic),
        ("SMPS EMI: boost", test_smps_emi_boost),
        ("SMPS EMI: loop area", test_smps_emi_loop_area_impact),

        # Dispatch tests
        ("Dispatch: return current density", test_dispatch_return_current_density),
        ("Dispatch: ground stitching", test_dispatch_ground_stitching),
        ("Dispatch: clock EMI", test_dispatch_clock_emi),
        ("Dispatch: SMPS EMI", test_dispatch_smps_emi),

        # Registration and edge cases
        ("Registration: tool list", test_tool_registration),
        ("Edge cases", test_edge_cases),
        ("FCC limits", test_fcc_limits),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 70}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    print(f"{'=' * 70}")

    sys.exit(1 if failed > 0 else 0)

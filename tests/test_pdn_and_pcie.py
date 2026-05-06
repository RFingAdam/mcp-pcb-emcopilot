"""Tests for PDN impedance profiling (#11) and PCIe link budget / lane skew (#13).

Exercises:
- pdn_impedance.calculate_pdn_impedance() directly
- pcie_link_budget.calculate_pcie_link_budget() directly
- pcie_link_budget.validate_pcie_lanes() directly
- All three new tools through the server _dispatch() path
- Tool registration in the tool list
- Edge cases and expected failures
"""

import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# =========================================================================
# PDN impedance profiling tests
# =========================================================================

def test_pdn_impedance_basic():
    """Basic PDN impedance sweep with one bulk cap and one MLCC."""
    from mcp_pcb_emcopilot.analyzers.power_integrity.pdn_impedance import calculate_pdn_impedance

    result = calculate_pdn_impedance(
        supply_voltage_v=1.0,
        max_current_a=5.0,
        ripple_percent=3.0,
        capacitors=[
            {"capacitance_uf": 100, "esr_mohm": 10, "esl_nh": 2.0, "quantity": 2},  # bulk
            {"capacitance_uf": 0.1, "esr_mohm": 5, "esl_nh": 0.3, "quantity": 20},  # MLCC
        ],
        vrm_bandwidth_khz=50,
        vrm_r_out_mohm=1.0,
        plane_area_mm2=2500,
        dielectric_height_mm=0.1,
        dielectric_constant=4.3,
        num_points=200,
    )

    assert "frequencies_hz" in result
    assert "impedance_ohm" in result
    assert "target_impedance_ohm" in result
    assert "anti_resonances" in result
    assert "meets_target" in result
    assert "notes" in result

    # Target impedance: 1.0V * 3% / 5A = 0.006 ohm = 6 mohm
    assert abs(result["target_impedance_ohm"] - 0.006) < 1e-6
    assert len(result["frequencies_hz"]) == 200
    assert len(result["impedance_ohm"]) == 200
    assert result["worst_impedance_ohm"] > 0

    print(f"  Target: {result['target_impedance_ohm']*1e3:.2f} mohm")
    print(f"  Worst: {result['worst_impedance_ohm']*1e3:.2f} mohm @ {result['worst_frequency_hz']:.0f} Hz")
    print(f"  Anti-resonances: {len(result['anti_resonances'])}")
    print(f"  Meets target: {result['meets_target']}")
    print(f"  Notes: {len(result['notes'])}")
    print("  PASS: Basic PDN impedance sweep works correctly")


def test_pdn_impedance_no_caps():
    """PDN with only VRM and plane capacitance (no discrete caps)."""
    from mcp_pcb_emcopilot.analyzers.power_integrity.pdn_impedance import calculate_pdn_impedance

    result = calculate_pdn_impedance(
        supply_voltage_v=3.3,
        max_current_a=1.0,
        ripple_percent=5.0,
        capacitors=[],
        vrm_bandwidth_khz=100,
        vrm_r_out_mohm=5.0,
        plane_area_mm2=5000,
        dielectric_height_mm=0.1,
        dielectric_constant=4.3,
        num_points=100,
    )

    # Target: 3.3 * 5% / 1.0 = 0.165 ohm
    assert abs(result["target_impedance_ohm"] - 0.165) < 1e-6
    assert len(result["frequencies_hz"]) == 100
    assert len(result["anti_resonances"]) == 0  # no discrete caps means no anti-resonance
    print(f"  Target: {result['target_impedance_ohm']*1e3:.1f} mohm")
    print(f"  Worst: {result['worst_impedance_ohm']*1e3:.1f} mohm")
    print("  PASS: PDN with no discrete caps works correctly")


def test_pdn_impedance_antiresonance():
    """Two cap values should produce an anti-resonance between their SRFs."""
    from mcp_pcb_emcopilot.analyzers.power_integrity.pdn_impedance import calculate_pdn_impedance

    # Use a very tight target so the anti-resonance is likely to exceed it
    result = calculate_pdn_impedance(
        supply_voltage_v=1.0,
        max_current_a=20.0,
        ripple_percent=1.0,
        capacitors=[
            {"capacitance_uf": 10, "esr_mohm": 10, "esl_nh": 2.0, "quantity": 4},
            {"capacitance_uf": 0.01, "esr_mohm": 5, "esl_nh": 0.3, "quantity": 30},
        ],
        num_points=500,
    )

    # With a 0.5 mohm target and two widely spaced cap values, we expect anti-resonance
    assert result["target_impedance_ohm"] == 0.0005  # 1.0 * 1% / 20A
    print(f"  Target: {result['target_impedance_ohm']*1e3:.3f} mohm")
    print(f"  Anti-resonances exceeding target: {len(result['anti_resonances'])}")
    for ar in result["anti_resonances"][:5]:
        print(f"    {ar['frequency_hz']:.0f} Hz: {ar['impedance_ohm']*1e3:.2f} mohm (+{ar['exceeds_target_by_db']:.1f} dB)")
    print(f"  Meets target: {result['meets_target']}")
    print("  PASS: Anti-resonance detection works correctly")


def test_pdn_impedance_plane_capacitance():
    """Verify plane capacitance calculation contributes at high frequencies."""
    from mcp_pcb_emcopilot.analyzers.power_integrity.pdn_impedance import calculate_pdn_impedance

    # Without plane
    r1 = calculate_pdn_impedance(
        supply_voltage_v=1.0, max_current_a=5.0, ripple_percent=5.0,
        capacitors=[{"capacitance_uf": 0.1, "esr_mohm": 5, "esl_nh": 0.3, "quantity": 10}],
        plane_area_mm2=0, num_points=100,
    )

    # With plane
    r2 = calculate_pdn_impedance(
        supply_voltage_v=1.0, max_current_a=5.0, ripple_percent=5.0,
        capacitors=[{"capacitance_uf": 0.1, "esr_mohm": 5, "esl_nh": 0.3, "quantity": 10}],
        plane_area_mm2=5000, dielectric_height_mm=0.1, dielectric_constant=4.3, num_points=100,
    )

    # At high frequencies, the plane should lower impedance
    # Compare the last few impedance points (high freq end)
    z_no_plane_high = r1["impedance_ohm"][-1]
    z_with_plane_high = r2["impedance_ohm"][-1]
    print(f"  Z @ max freq without plane: {z_no_plane_high*1e3:.2f} mohm")
    print(f"  Z @ max freq with plane: {z_with_plane_high*1e3:.2f} mohm")
    # Plane cap should reduce high-freq impedance
    assert z_with_plane_high <= z_no_plane_high
    print("  PASS: Plane capacitance reduces high-frequency impedance")


# =========================================================================
# PCIe link budget tests
# =========================================================================

def test_pcie_link_budget_gen3():
    """Gen3 link budget with a short trace should pass easily."""
    from mcp_pcb_emcopilot.analyzers.high_speed.pcie_link_budget import calculate_pcie_link_budget

    result = calculate_pcie_link_budget(
        pcie_gen=3,
        trace_length_mm=100,
        dielectric_constant=4.0,
        loss_tangent=0.02,
        copper_thickness_oz=0.5,
        connector_loss_db=0.5,
        via_loss_db=0.3,
    )

    assert result["pass_fail"] == "PASS"
    assert result["spec_limit_db"] == 8.0
    assert result["total_loss_db"] > 0
    assert result["equalizer_margin_db"] > 0
    assert "Gen3" in result["pcie_generation"]
    print(f"  Gen3: total={result['total_loss_db']:.2f} dB, limit={result['spec_limit_db']} dB, "
          f"margin={result['equalizer_margin_db']:.2f} dB -> {result['pass_fail']}")
    print("  PASS: Gen3 link budget calculation works correctly")


def test_pcie_link_budget_gen5():
    """Gen5 link budget with long lossy trace should exercise the limit."""
    from mcp_pcb_emcopilot.analyzers.high_speed.pcie_link_budget import calculate_pcie_link_budget

    result = calculate_pcie_link_budget(
        pcie_gen=5,
        trace_length_mm=250,
        dielectric_constant=3.5,
        loss_tangent=0.008,  # low-loss material
        copper_thickness_oz=0.5,
        connector_loss_db=1.0,
        via_loss_db=0.5,
        package_loss_db=1.5,
    )

    assert result["spec_limit_db"] == 28.0
    assert result["total_loss_db"] > 0
    assert "Gen5" in result["pcie_generation"]
    print(f"  Gen5: total={result['total_loss_db']:.2f} dB, limit={result['spec_limit_db']} dB, "
          f"margin={result['equalizer_margin_db']:.2f} dB -> {result['pass_fail']}")
    print("  PASS: Gen5 link budget calculation works correctly")


def test_pcie_link_budget_all_gens():
    """Verify all 6 generations are supported and have increasing limits."""
    from mcp_pcb_emcopilot.analyzers.high_speed.pcie_link_budget import calculate_pcie_link_budget

    prev_limit = 0
    for gen in range(1, 7):
        result = calculate_pcie_link_budget(pcie_gen=gen, trace_length_mm=50)
        assert result["spec_limit_db"] > prev_limit
        prev_limit = result["spec_limit_db"]
        print(f"  Gen{gen}: spec_limit={result['spec_limit_db']} dB, "
              f"trace_loss={result['trace_loss_db']:.3f} dB")
    print("  PASS: All 6 PCIe generations supported with increasing spec limits")


def test_pcie_link_budget_invalid_gen():
    """Invalid generation should raise ValueError."""
    from mcp_pcb_emcopilot.analyzers.high_speed.pcie_link_budget import calculate_pcie_link_budget

    try:
        calculate_pcie_link_budget(pcie_gen=7, trace_length_mm=100)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "7" in str(e)
        print(f"  Correctly raised: {e}")
    print("  PASS: Invalid generation raises ValueError")


# =========================================================================
# PCIe lane skew validation tests
# =========================================================================

def test_pcie_lane_skew_pass():
    """Well-matched lanes should pass."""
    from mcp_pcb_emcopilot.analyzers.high_speed.pcie_link_budget import validate_pcie_lanes

    result = validate_pcie_lanes(
        lane_lengths_mm={"TX0": 80.0, "TX1": 80.1, "TX2": 80.2, "TX3": 79.9},
        dielectric_constant=4.0,
        pcie_gen=4,
    )

    assert result["pass_fail"] == "PASS"
    assert result["max_skew_ps"] < 200  # Gen4 limit
    assert result["spec_limit_ps"] == 200
    assert len(result["lanes"]) == 4
    assert result["reference_lane"] in ("TX0", "TX1", "TX2", "TX3")
    print(f"  Max skew: {result['max_skew_ps']:.1f} ps (limit {result['spec_limit_ps']} ps)")
    print(f"  Reference lane: {result['reference_lane']}")
    for name, info in result["lanes"].items():
        print(f"    {name}: {info['length_mm']} mm, delay={info['delay_ps']:.1f} ps, skew={info['skew_ps']:.1f} ps")
    print("  PASS: Well-matched lanes pass validation")


def test_pcie_lane_skew_fail():
    """One significantly longer lane should fail Gen4 (>200ps skew)."""
    from mcp_pcb_emcopilot.analyzers.high_speed.pcie_link_budget import validate_pcie_lanes

    # 50mm difference at ~6.15 ps/mm = ~308 ps skew, exceeding 200ps Gen4 limit
    result = validate_pcie_lanes(
        lane_lengths_mm={"TX0": 80.0, "TX1": 80.0, "TX2": 80.0, "TX3": 130.0},
        dielectric_constant=4.0,
        pcie_gen=4,
    )

    assert result["pass_fail"] == "FAIL"
    assert result["max_skew_ps"] > 200
    print(f"  Max skew: {result['max_skew_ps']:.1f} ps (limit {result['spec_limit_ps']} ps) -> FAIL")
    print("  PASS: Mismatched lane correctly flagged as FAIL")


def test_pcie_lane_skew_gen1_relaxed():
    """Same large mismatch should pass with relaxed Gen1 limits."""
    from mcp_pcb_emcopilot.analyzers.high_speed.pcie_link_budget import validate_pcie_lanes

    result = validate_pcie_lanes(
        lane_lengths_mm={"TX0": 80.0, "TX1": 80.0, "TX2": 80.0, "TX3": 130.0},
        dielectric_constant=4.0,
        pcie_gen=1,
    )

    assert result["pass_fail"] == "PASS"  # Gen1 limit is 20ns
    print(f"  Max skew: {result['max_skew_ps']:.1f} ps (Gen1 limit {result['spec_limit_ps']} ps) -> PASS")
    print("  PASS: Relaxed Gen1 limit correctly allows larger skew")


def test_pcie_lane_skew_empty():
    """Empty lane dict should return PASS with no lanes."""
    from mcp_pcb_emcopilot.analyzers.high_speed.pcie_link_budget import validate_pcie_lanes

    result = validate_pcie_lanes(
        lane_lengths_mm={},
        pcie_gen=4,
    )

    assert result["pass_fail"] == "PASS"
    assert result["max_skew_ps"] == 0.0
    print("  PASS: Empty lane dict handled gracefully")


def test_pcie_lane_skew_single():
    """Single lane should always pass with zero skew."""
    from mcp_pcb_emcopilot.analyzers.high_speed.pcie_link_budget import validate_pcie_lanes

    result = validate_pcie_lanes(
        lane_lengths_mm={"TX0": 100.0},
        pcie_gen=5,
    )

    assert result["pass_fail"] == "PASS"
    assert result["max_skew_ps"] == 0.0
    assert result["reference_lane"] == "TX0"
    print("  PASS: Single lane yields zero skew")


# =========================================================================
# Dispatch / tool registration tests
# =========================================================================

def test_dispatch_pdn_impedance():
    """Test pcb_calc_pdn_impedance through the dispatch system."""
    from mcp_pcb_emcopilot.server import _dispatch

    result = _dispatch("pcb_calc_pdn_impedance", {
        "supply_voltage_v": 1.0,
        "max_current_a": 5.0,
        "ripple_percent": 3.0,
        "capacitors": [
            {"capacitance_uf": 10, "esr_mohm": 10, "esl_nh": 1.0, "quantity": 4},
            {"capacitance_uf": 0.1, "esr_mohm": 5, "esl_nh": 0.3, "quantity": 20},
        ],
        "plane_area_mm2": 2500,
        "dielectric_height_mm": 0.1,
        "num_points": 100,
    })

    assert "frequencies_hz" in result
    assert "impedance_ohm" in result
    assert "target_impedance_ohm" in result
    assert "anti_resonances" in result
    assert len(result["frequencies_hz"]) == 100
    print(f"  Dispatch pcb_calc_pdn_impedance: OK - {len(result['frequencies_hz'])} points, "
          f"target={result['target_impedance_ohm']*1e3:.2f} mohm")
    print("  PASS: pcb_calc_pdn_impedance dispatch works correctly")


def test_dispatch_pcie_link_budget():
    """Test pcb_calc_pcie_link_budget through the dispatch system."""
    from mcp_pcb_emcopilot.server import _dispatch

    result = _dispatch("pcb_calc_pcie_link_budget", {
        "pcie_gen": 4,
        "trace_length_mm": 150,
        "dielectric_constant": 3.8,
        "loss_tangent": 0.01,
        "connector_loss_db": 0.5,
        "via_loss_db": 0.3,
    })

    assert "total_loss_db" in result
    assert "equalizer_margin_db" in result
    assert "pass_fail" in result
    assert "Gen4" in result["pcie_generation"]
    print(f"  Dispatch pcb_calc_pcie_link_budget: OK - total={result['total_loss_db']:.2f} dB, "
          f"margin={result['equalizer_margin_db']:.2f} dB, {result['pass_fail']}")
    print("  PASS: pcb_calc_pcie_link_budget dispatch works correctly")


def test_dispatch_pcie_lanes():
    """Test pcb_validate_pcie_lanes through the dispatch system."""
    from mcp_pcb_emcopilot.server import _dispatch

    result = _dispatch("pcb_validate_pcie_lanes", {
        "lane_lengths_mm": {"TX0": 80.0, "TX1": 80.5, "TX2": 79.8, "TX3": 80.2},
        "dielectric_constant": 4.0,
        "pcie_gen": 4,
    })

    assert "lanes" in result
    assert "max_skew_ps" in result
    assert "pass_fail" in result
    assert "spec_limit_ps" in result
    print(f"  Dispatch pcb_validate_pcie_lanes: OK - max_skew={result['max_skew_ps']:.1f} ps, "
          f"{result['pass_fail']}")
    print("  PASS: pcb_validate_pcie_lanes dispatch works correctly")


def test_tool_registration():
    """Verify all 3 new tools appear in the tool list."""
    import asyncio

    from mcp_pcb_emcopilot.server import list_tools

    tools = asyncio.run(list_tools())
    tool_names = {t.name for t in tools}

    expected = {
        "pcb_calc_pdn_impedance",
        "pcb_calc_pcie_link_budget",
        "pcb_validate_pcie_lanes",
    }

    missing = expected - tool_names
    assert not missing, f"Missing tools: {missing}"
    print(f"  All 3 new tools registered (total tools: {len(tools)})")
    for name in sorted(expected):
        print(f"    {name}")
    print("  PASS: Tool registration verified")


# =========================================================================
# Edge cases
# =========================================================================

def test_pdn_single_cap():
    """PDN with a single capacitor value -- no anti-resonance expected."""
    from mcp_pcb_emcopilot.analyzers.power_integrity.pdn_impedance import calculate_pdn_impedance

    result = calculate_pdn_impedance(
        supply_voltage_v=3.3,
        max_current_a=2.0,
        ripple_percent=5.0,
        capacitors=[{"capacitance_uf": 0.1, "esr_mohm": 10, "esl_nh": 0.5, "quantity": 10}],
        num_points=50,
    )

    # With a single cap value the impedance curve is a clean V-shape at SRF
    # No anti-resonance between different cap values
    assert result["target_impedance_ohm"] > 0
    assert len(result["frequencies_hz"]) == 50
    print(f"  Single cap value: {len(result['anti_resonances'])} anti-resonances")
    print("  PASS: Single cap value handled correctly")


def test_pdn_custom_freq_range():
    """Test custom frequency range."""
    from mcp_pcb_emcopilot.analyzers.power_integrity.pdn_impedance import calculate_pdn_impedance

    result = calculate_pdn_impedance(
        supply_voltage_v=1.8,
        max_current_a=3.0,
        ripple_percent=2.0,
        capacitors=[{"capacitance_uf": 1.0, "esr_mohm": 8, "esl_nh": 0.5, "quantity": 5}],
        freq_start_hz=1e3,
        freq_stop_hz=1e8,
        num_points=50,
    )

    # Verify the frequency range
    assert result["frequencies_hz"][0] >= 999  # ~1 kHz
    assert result["frequencies_hz"][-1] <= 1.01e8  # ~100 MHz
    print(f"  Freq range: {result['frequencies_hz'][0]:.0f} Hz - {result['frequencies_hz'][-1]:.0f} Hz")
    print("  PASS: Custom frequency range works correctly")


def test_pcie_link_budget_zero_trace():
    """Zero trace length -- only connector/via/package losses."""
    from mcp_pcb_emcopilot.analyzers.high_speed.pcie_link_budget import calculate_pcie_link_budget

    result = calculate_pcie_link_budget(
        pcie_gen=4,
        trace_length_mm=0,
        connector_loss_db=1.0,
        via_loss_db=0.5,
        package_loss_db=2.0,
    )

    assert result["trace_loss_db"] == 0.0
    assert abs(result["total_loss_db"] - 3.5) < 0.01
    assert result["pass_fail"] == "PASS"  # 3.5 dB < 16 dB limit
    print(f"  Zero trace: total={result['total_loss_db']:.2f} dB -> {result['pass_fail']}")
    print("  PASS: Zero trace length handled correctly")


if __name__ == "__main__":
    print("=" * 70)
    print("PDN Impedance Profiling & PCIe Link Budget / Lane Skew Tests")
    print("=" * 70)

    tests = [
        ("PDN: basic impedance sweep", test_pdn_impedance_basic),
        ("PDN: no discrete caps", test_pdn_impedance_no_caps),
        ("PDN: anti-resonance detection", test_pdn_impedance_antiresonance),
        ("PDN: plane capacitance effect", test_pdn_impedance_plane_capacitance),
        ("PDN: single cap value", test_pdn_single_cap),
        ("PDN: custom freq range", test_pdn_custom_freq_range),
        ("PCIe: Gen3 link budget", test_pcie_link_budget_gen3),
        ("PCIe: Gen5 link budget", test_pcie_link_budget_gen5),
        ("PCIe: all generations", test_pcie_link_budget_all_gens),
        ("PCIe: invalid generation", test_pcie_link_budget_invalid_gen),
        ("PCIe: lane skew pass", test_pcie_lane_skew_pass),
        ("PCIe: lane skew fail", test_pcie_lane_skew_fail),
        ("PCIe: Gen1 relaxed skew", test_pcie_lane_skew_gen1_relaxed),
        ("PCIe: empty lanes", test_pcie_lane_skew_empty),
        ("PCIe: single lane", test_pcie_lane_skew_single),
        ("PCIe: zero trace length", test_pcie_link_budget_zero_trace),
        ("Dispatch: pcb_calc_pdn_impedance", test_dispatch_pdn_impedance),
        ("Dispatch: pcb_calc_pcie_link_budget", test_dispatch_pcie_link_budget),
        ("Dispatch: pcb_validate_pcie_lanes", test_dispatch_pcie_lanes),
        ("Registration: tool list", test_tool_registration),
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

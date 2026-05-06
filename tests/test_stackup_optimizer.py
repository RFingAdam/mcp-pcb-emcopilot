"""Tests for stackup optimizer with comparative analysis.

Covers Issue #40:
- Alternative stackup generation (4, 6, 8 layer)
- Impedance calculation per variant
- Insertion loss comparison at key frequencies
- Cavity resonance calculation
- Cost/complexity scoring
- Edge cases (single layer, very thick/thin stackups)

14+ tests total.
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from mcp_pcb_emcopilot.analyzers.stackup_optimizer import (
    C0,
    KEY_FREQUENCIES,
    MATERIAL_LIBRARY,
    StackupOptimizer,
)

# =============================================================================
# Stackup generation
# =============================================================================

def test_generate_4_layer_stackup():
    """4-layer stackup should have 2 signal + 2 plane copper layers."""
    opt = StackupOptimizer()
    variant = opt.generate_stackup(layer_count=4, material="FR4_standard")

    assert variant.layer_count == 4
    assert variant.signal_layer_count == 2
    assert variant.plane_layer_count == 2
    assert variant.total_thickness_mm > 0
    # First copper layer should be signal (Top), last should be signal (Bottom)
    copper = [ly for ly in variant.layers if ly.is_copper]
    assert copper[0].layer_type == "signal"
    assert copper[-1].layer_type == "signal"


def test_generate_6_layer_stackup():
    """6-layer stackup should have 3 signal + 3 plane copper layers."""
    opt = StackupOptimizer()
    variant = opt.generate_stackup(layer_count=6, material="FR4_standard")

    assert variant.layer_count == 6
    assert variant.signal_layer_count == 3
    assert variant.plane_layer_count == 3
    assert variant.total_thickness_mm > 0


def test_generate_8_layer_stackup():
    """8-layer stackup should have 4 signal + 4 plane copper layers."""
    opt = StackupOptimizer()
    variant = opt.generate_stackup(layer_count=8, material="FR4_standard")

    assert variant.layer_count == 8
    assert variant.signal_layer_count == 4
    assert variant.plane_layer_count == 4
    assert variant.total_thickness_mm > 0


def test_odd_layer_count_rounded_up():
    """Odd layer counts > 1 should be rounded up to even."""
    opt = StackupOptimizer()
    variant = opt.generate_stackup(layer_count=5, material="FR4_standard")

    # 5 -> 6
    assert variant.layer_count == 6


def test_2_layer_stackup():
    """2-layer stackup should have 2 signal layers and 0 planes."""
    opt = StackupOptimizer()
    variant = opt.generate_stackup(layer_count=2, material="FR4_standard")

    assert variant.layer_count == 2
    assert variant.signal_layer_count == 2
    assert variant.plane_layer_count == 0


# =============================================================================
# Impedance calculation
# =============================================================================

def test_impedance_calculated_for_all_signal_layers():
    """Every signal layer should get an impedance result."""
    opt = StackupOptimizer()
    variant = opt.generate_stackup(layer_count=4)
    opt.calculate_impedances(variant, trace_width_mm=0.127)

    assert len(variant.impedance_results) == variant.signal_layer_count
    for res in variant.impedance_results:
        assert res.impedance_ohm > 0
        assert res.effective_dielectric > 0


def test_microstrip_vs_stripline_classification():
    """Outer layers should be microstrip, inner should be stripline in a 6-layer."""
    opt = StackupOptimizer()
    variant = opt.generate_stackup(layer_count=6)
    opt.calculate_impedances(variant, trace_width_mm=0.127)

    types_by_name = {r.layer_name: r.trace_type for r in variant.impedance_results}
    # Top and Bottom are outer layers -> microstrip
    assert types_by_name["Top"] == "microstrip"
    assert types_by_name["Bottom"] == "microstrip"
    # Inner signal (Sig2) sits between two planes -> stripline
    assert types_by_name["Sig2"] == "stripline"


def test_impedance_varies_with_material():
    """Different dielectric constants should yield different impedance values."""
    opt = StackupOptimizer()

    v_fr4 = opt.generate_stackup(layer_count=4, material="FR4_standard")
    opt.calculate_impedances(v_fr4, trace_width_mm=0.127)

    v_hs = opt.generate_stackup(layer_count=4, material="high_speed")
    opt.calculate_impedances(v_hs, trace_width_mm=0.127)

    z_fr4 = v_fr4.impedance_results[0].impedance_ohm
    z_hs = v_hs.impedance_results[0].impedance_ohm

    # Lower Er (high-speed) should give higher impedance (for same geometry)
    assert z_hs > z_fr4, (
        f"High-speed laminate (Er={MATERIAL_LIBRARY['high_speed']['dielectric_constant']}) "
        f"should give higher Z than FR4 (Er={MATERIAL_LIBRARY['FR4_standard']['dielectric_constant']})"
    )


# =============================================================================
# Insertion loss
# =============================================================================

def test_insertion_loss_calculated_at_key_frequencies():
    """Insertion loss dict should have entries for all four key frequencies."""
    opt = StackupOptimizer()
    variant = opt.generate_stackup(layer_count=4)
    opt.calculate_impedances(variant, trace_width_mm=0.127)
    opt.calculate_insertion_loss(variant, trace_width_mm=0.127, trace_length_mm=50.0)

    for freq_label in KEY_FREQUENCIES:
        assert freq_label in variant.insertion_loss_db, (
            f"Missing insertion loss for {freq_label}"
        )
        layer_losses = variant.insertion_loss_db[freq_label]
        assert len(layer_losses) == variant.signal_layer_count


def test_insertion_loss_increases_with_frequency():
    """Loss should monotonically increase with frequency."""
    opt = StackupOptimizer()
    variant = opt.generate_stackup(layer_count=4)
    opt.calculate_impedances(variant, trace_width_mm=0.127)
    opt.calculate_insertion_loss(variant, trace_width_mm=0.127, trace_length_mm=50.0)

    # Pick the first signal layer
    first_layer = variant.impedance_results[0].layer_name
    sorted_freqs = sorted(KEY_FREQUENCIES.items(), key=lambda x: x[1])

    losses_ordered = [
        variant.insertion_loss_db[label][first_layer]
        for label, _ in sorted_freqs
    ]

    for i in range(len(losses_ordered) - 1):
        assert losses_ordered[i + 1] >= losses_ordered[i], (
            f"Loss should increase with frequency but "
            f"{losses_ordered[i + 1]:.4f} < {losses_ordered[i]:.4f}"
        )


def test_high_speed_material_lower_loss():
    """High-speed laminate should have lower insertion loss than FR4."""
    opt = StackupOptimizer()

    v_fr4 = opt.generate_stackup(layer_count=4, material="FR4_standard")
    opt.calculate_impedances(v_fr4, trace_width_mm=0.127)
    opt.calculate_insertion_loss(v_fr4, trace_width_mm=0.127, trace_length_mm=50.0)

    v_hs = opt.generate_stackup(layer_count=4, material="high_speed")
    opt.calculate_impedances(v_hs, trace_width_mm=0.127)
    opt.calculate_insertion_loss(v_hs, trace_width_mm=0.127, trace_length_mm=50.0)

    # Compare at 5 GHz (USB) on Top layer
    loss_fr4 = v_fr4.insertion_loss_db["USB_5GHz"]["Top"]
    loss_hs = v_hs.insertion_loss_db["USB_5GHz"]["Top"]

    assert loss_hs < loss_fr4, (
        f"High-speed loss {loss_hs:.4f} should be < FR4 loss {loss_fr4:.4f}"
    )


# =============================================================================
# Cavity resonance
# =============================================================================

def test_cavity_resonances_populated():
    """Cavity resonances should be calculated for a 4-layer stackup."""
    opt = StackupOptimizer()
    variant = opt.generate_stackup(layer_count=4)
    opt.calculate_cavity_resonances(
        variant, board_width_mm=100.0, board_height_mm=80.0
    )

    assert len(variant.cavity_resonances_mhz) > 0
    # Should be sorted
    for i in range(len(variant.cavity_resonances_mhz) - 1):
        assert variant.cavity_resonances_mhz[i] <= variant.cavity_resonances_mhz[i + 1]


def test_cavity_first_resonance_analytical():
    """First resonance should match the TM10 analytical formula."""
    opt = StackupOptimizer()
    variant = opt.generate_stackup(layer_count=4, material="FR4_standard")
    opt.calculate_cavity_resonances(
        variant, board_width_mm=100.0, board_height_mm=80.0
    )

    er = MATERIAL_LIBRARY["FR4_standard"]["dielectric_constant"]
    a = 100.0 / 1000.0  # longest dimension in meters
    expected_f10_mhz = (C0 / (2 * math.sqrt(er))) / a / 1e6

    first = variant.cavity_resonances_mhz[0]
    assert abs(first - expected_f10_mhz) < 1.0, (
        f"Expected first resonance ~{expected_f10_mhz:.1f} MHz, got {first:.1f} MHz"
    )


# =============================================================================
# Cost / complexity scoring
# =============================================================================

def test_cost_increases_with_layer_count():
    """Higher layer count should cost more."""
    opt = StackupOptimizer()

    v4 = opt.generate_stackup(layer_count=4)
    opt.calculate_cost_score(v4)
    v8 = opt.generate_stackup(layer_count=8)
    opt.calculate_cost_score(v8)

    assert v8.cost_score > v4.cost_score


def test_cost_increases_with_premium_material():
    """Premium materials should raise cost score."""
    opt = StackupOptimizer()

    v_std = opt.generate_stackup(layer_count=4, material="FR4_standard")
    opt.calculate_cost_score(v_std)
    v_hs = opt.generate_stackup(layer_count=4, material="high_speed")
    opt.calculate_cost_score(v_hs)

    assert v_hs.cost_score > v_std.cost_score


# =============================================================================
# Full optimize round-trip
# =============================================================================

def test_full_optimize_returns_variants():
    """Full optimize should return multiple variants with comparison."""
    opt = StackupOptimizer()
    result = opt.optimize(
        target_layer_count=4,
        target_impedance_ohm=50.0,
        board_width_mm=100.0,
        board_height_mm=80.0,
    )

    assert result.success is True
    assert len(result.variants) == 3  # default 3 materials
    assert result.comparison is not None
    assert result.comparison.best_impedance_variant != ""
    assert result.comparison.best_loss_variant != ""
    assert result.comparison.best_cost_variant != ""
    assert result.summary != ""


# =============================================================================
# Edge cases
# =============================================================================

def test_single_layer_stackup():
    """Single-layer board should not crash and have 1 signal layer."""
    opt = StackupOptimizer()
    variant = opt.generate_stackup(layer_count=1, material="FR4_standard")

    assert variant.layer_count == 1
    assert variant.signal_layer_count == 1
    assert variant.total_thickness_mm > 0


def test_very_thin_dielectric():
    """Board with very thin dielectrics should still calculate correctly."""
    opt = StackupOptimizer()
    variant = opt.generate_stackup(layer_count=8, material="FR4_standard")

    # 8-layer has 0.1mm prepregs
    thin_layers = [
        ly for ly in variant.layers
        if ly.layer_type == "dielectric" and ly.thickness_mm < 0.15
    ]
    assert len(thin_layers) > 0, "8-layer should contain thin dielectric layers"

    opt.calculate_impedances(variant, trace_width_mm=0.127)
    for r in variant.impedance_results:
        assert r.impedance_ohm > 0
        assert math.isfinite(r.impedance_ohm)


def test_to_dict_serialization():
    """All dataclass to_dict methods should return serializable dicts."""
    opt = StackupOptimizer()
    result = opt.optimize(
        target_layer_count=4,
        target_impedance_ohm=50.0,
        board_width_mm=100.0,
        board_height_mm=80.0,
    )

    d = result.to_dict()
    assert isinstance(d, dict)
    assert d["success"] is True
    assert len(d["variants"]) == 3
    assert "comparison" in d

    # Check variant dict
    vd = d["variants"][0]
    assert "impedance_results" in vd
    assert "insertion_loss_db" in vd
    assert "cavity_resonances_mhz" in vd
    assert "cost_score" in vd


def test_large_layer_count():
    """10- and 12-layer boards should generate without errors."""
    opt = StackupOptimizer()
    for lc in (10, 12):
        variant = opt.generate_stackup(layer_count=lc)
        assert variant.layer_count == lc
        assert variant.total_thickness_mm > 0
        opt.calculate_impedances(variant, trace_width_mm=0.127)
        assert len(variant.impedance_results) == variant.signal_layer_count

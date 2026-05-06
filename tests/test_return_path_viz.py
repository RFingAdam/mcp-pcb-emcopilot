"""Tests for ReturnPathVisualizer -- return path discontinuity analysis.

Covers skin depth, via current spreading, loop area calculations,
slot crossing impedance, edge cases, and aggregate summaries.
"""

from __future__ import annotations

import math

import pytest

from mcp_pcb_emcopilot.analyzers.signal_integrity.return_path_viz import (
    MU0,
    SIGMA_CU,
    ReturnPathVisualizer,
)


@pytest.fixture
def viz() -> ReturnPathVisualizer:
    return ReturnPathVisualizer()


# -----------------------------------------------------------------------
# Skin depth tests
# -----------------------------------------------------------------------

class TestSkinDepth:
    """Skin depth calculation at multiple frequencies."""

    def test_skin_depth_1ghz(self, viz: ReturnPathVisualizer) -> None:
        """At 1 GHz copper skin depth should be roughly 2.09 um."""
        result = viz.skin_depth(frequency_hz=1e9)
        expected_mm = 1.0 / math.sqrt(math.pi * 1e9 * MU0 * SIGMA_CU) * 1e3
        assert result.skin_depth_mm == pytest.approx(expected_mm, rel=1e-6)
        assert result.frequency_hz == 1e9

    def test_skin_depth_100mhz(self, viz: ReturnPathVisualizer) -> None:
        """At 100 MHz the skin depth should be about 6.6 um."""
        result = viz.skin_depth(frequency_hz=100e6)
        expected_mm = 1.0 / math.sqrt(math.pi * 100e6 * MU0 * SIGMA_CU) * 1e3
        assert result.skin_depth_mm == pytest.approx(expected_mm, rel=1e-6)

    def test_skin_depth_1mhz(self, viz: ReturnPathVisualizer) -> None:
        """At 1 MHz the skin depth should be about 66 um."""
        result = viz.skin_depth(frequency_hz=1e6)
        expected_mm = 1.0 / math.sqrt(math.pi * 1e6 * MU0 * SIGMA_CU) * 1e3
        assert result.skin_depth_mm == pytest.approx(expected_mm, rel=1e-6)
        # Skin depth at 1 MHz should be larger than at 1 GHz
        result_1g = viz.skin_depth(frequency_hz=1e9)
        assert result.skin_depth_mm > result_1g.skin_depth_mm

    def test_skin_depth_zero_frequency(self, viz: ReturnPathVisualizer) -> None:
        """At DC (0 Hz) the skin depth should be effectively infinite."""
        result = viz.skin_depth(frequency_hz=0.0)
        assert result.skin_depth_mm == 1e6
        assert any("DC" in n or "infinite" in n for n in result.notes)

    def test_skin_depth_very_high_frequency(self, viz: ReturnPathVisualizer) -> None:
        """At 10 GHz skin depth should be very thin and produce a note."""
        result = viz.skin_depth(frequency_hz=10e9)
        assert result.skin_depth_mm < 0.01  # less than 10 um
        assert any("surface roughness" in n for n in result.notes)

    def test_skin_depth_negative_frequency(self, viz: ReturnPathVisualizer) -> None:
        """Negative frequency should be treated as DC."""
        result = viz.skin_depth(frequency_hz=-100.0)
        assert result.skin_depth_mm == 1e6


# -----------------------------------------------------------------------
# Via current spreading tests
# -----------------------------------------------------------------------

class TestViaCurrentSpreading:
    """Via transition current spreading model."""

    def test_basic_spreading(self, viz: ReturnPathVisualizer) -> None:
        """Standard 0.3mm drill, 0.6mm antipad at 1 GHz."""
        result = viz.via_current_spreading(
            via_drill_mm=0.3,
            antipad_mm=0.6,
            frequency_hz=1e9,
        )
        # Spreading radius should exceed antipad radius
        assert result.spreading_radius_mm > 0.3
        assert result.effective_area_mm2 > 0
        assert result.current_density_ratio >= 1.0
        assert result.skin_depth_mm > 0

    def test_dc_spreading(self, viz: ReturnPathVisualizer) -> None:
        """At DC, current should spread much more broadly."""
        result_dc = viz.via_current_spreading(
            via_drill_mm=0.3,
            antipad_mm=0.6,
            frequency_hz=0.0,
        )
        result_hf = viz.via_current_spreading(
            via_drill_mm=0.3,
            antipad_mm=0.6,
            frequency_hz=1e9,
        )
        assert result_dc.spreading_radius_mm > result_hf.spreading_radius_mm

    def test_large_antipad_crowding(self, viz: ReturnPathVisualizer) -> None:
        """Large antipad relative to drill should cause crowding note."""
        result = viz.via_current_spreading(
            via_drill_mm=0.2,
            antipad_mm=2.0,
            frequency_hz=1e9,
        )
        assert result.current_density_ratio > 1.0


# -----------------------------------------------------------------------
# Loop area tests
# -----------------------------------------------------------------------

class TestLoopArea:
    """Loop area calculation at each discontinuity type."""

    def test_plane_split_loop_area(self, viz: ReturnPathVisualizer) -> None:
        """Plane split: area = trace_length * 2 * split_width."""
        result = viz.loop_area_plane_split(
            trace_length_mm=10.0,
            split_width_mm=4.0,
        )
        assert result.loop_area_mm2 == pytest.approx(10.0 * 8.0, rel=1e-6)
        assert result.discontinuity_type == "plane_split"

    def test_via_transition_loop_area(self, viz: ReturnPathVisualizer) -> None:
        """Via transition: area = plane_spacing * return_via_distance."""
        result = viz.loop_area_via_transition(
            plane_spacing_mm=0.2,
            return_via_distance_mm=5.0,
        )
        assert result.loop_area_mm2 == pytest.approx(1.0, rel=1e-6)
        assert result.discontinuity_type == "via_transition"
        # Distance > 2mm should trigger a note
        assert any("ground via" in n for n in result.notes)

    def test_slot_crossing_loop_area(self, viz: ReturnPathVisualizer) -> None:
        """Slot crossing: area = trace_length * slot_width."""
        result = viz.loop_area_slot_crossing(
            trace_length_mm=15.0,
            slot_width_mm=1.0,
        )
        assert result.loop_area_mm2 == pytest.approx(15.0, rel=1e-6)
        assert result.discontinuity_type == "slot_crossing"

    def test_wide_slot_triggers_note(self, viz: ReturnPathVisualizer) -> None:
        """Slot wider than 2x trace height should produce a warning."""
        result = viz.loop_area_slot_crossing(
            trace_length_mm=10.0,
            slot_width_mm=2.0,
            plane_height_mm=0.2,
        )
        assert any("plane split" in n for n in result.notes)


# -----------------------------------------------------------------------
# Slot crossing impedance tests
# -----------------------------------------------------------------------

class TestSlotCrossingImpedance:
    """Slot crossing impedance increase estimation."""

    def test_basic_impedance_increase(self, viz: ReturnPathVisualizer) -> None:
        """A 2mm slot at 1 GHz with 0.1mm trace should give nonzero dZ."""
        result = viz.slot_crossing_impedance(
            slot_width_mm=2.0,
            trace_width_mm=0.1,
            frequency_hz=1e9,
        )
        assert result.impedance_increase_ohm > 0
        assert result.impedance_increase_pct > 0
        assert result.excess_loop_area_mm2 == pytest.approx(0.2, rel=1e-6)

    def test_zero_frequency_no_increase(self, viz: ReturnPathVisualizer) -> None:
        """At DC there should be no inductive impedance increase."""
        result = viz.slot_crossing_impedance(
            slot_width_mm=2.0,
            trace_width_mm=0.1,
            frequency_hz=0.0,
        )
        assert result.impedance_increase_ohm == 0.0
        assert result.impedance_increase_pct == 0.0

    def test_large_slot_warns(self, viz: ReturnPathVisualizer) -> None:
        """Large slot at high freq should trigger reflection warning."""
        result = viz.slot_crossing_impedance(
            slot_width_mm=10.0,
            trace_width_mm=0.1,
            frequency_hz=5e9,
        )
        assert result.impedance_increase_pct > 20.0
        assert any("reflections" in n for n in result.notes)

    def test_narrow_slot_small_increase(self, viz: ReturnPathVisualizer) -> None:
        """Slot narrower than trace width should give minimal impact."""
        result = viz.slot_crossing_impedance(
            slot_width_mm=0.05,
            trace_width_mm=0.15,
            frequency_hz=1e9,
        )
        # When slot < trace width, ratio clamps to 1, log(1)=0 => dZ=0
        assert result.impedance_increase_ohm == pytest.approx(0.0, abs=1e-6)


# -----------------------------------------------------------------------
# Aggregate summary tests
# -----------------------------------------------------------------------

class TestDiscontinuitySummary:
    """Aggregate summary across multiple discontinuities."""

    def test_summary(self, viz: ReturnPathVisualizer) -> None:
        items = [
            viz.loop_area_plane_split(10.0, 4.0),
            viz.loop_area_via_transition(0.2, 5.0),
            viz.loop_area_slot_crossing(15.0, 1.0),
        ]
        summary = viz.summarize_discontinuities(items)
        assert summary.discontinuity_count == 3
        assert summary.total_excess_loop_area_mm2 == pytest.approx(
            80.0 + 1.0 + 15.0, rel=1e-4
        )
        assert summary.worst_type == "plane_split"

    def test_empty_summary(self, viz: ReturnPathVisualizer) -> None:
        summary = viz.summarize_discontinuities([])
        assert summary.discontinuity_count == 0
        assert summary.total_excess_loop_area_mm2 == 0.0


# -----------------------------------------------------------------------
# Current density profile test
# -----------------------------------------------------------------------

class TestCurrentDensityProfile:
    """Current density profile for visualisation."""

    def test_profile_shape(self, viz: ReturnPathVisualizer) -> None:
        profile = viz.current_density_profile(trace_height_mm=0.2, num_points=21)
        assert len(profile["x_mm"]) == 21
        assert len(profile["density_normalised"]) == 21
        # Peak should be at the center
        densities = profile["density_normalised"]
        mid = len(densities) // 2
        assert densities[mid] == max(densities)
        # Containment percentages should be reasonable
        assert 70 < profile["within_3h_pct"] < 90
        assert 85 < profile["within_5h_pct"] < 98

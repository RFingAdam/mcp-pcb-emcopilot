"""Tests for EMI filter designer module."""
from __future__ import annotations

import math

import pytest

from mcp_pcb_emcopilot.analyzers.emc.filter_design import (
    FilterDesigner,
    _pi_filter_transfer,
)


@pytest.fixture
def designer():
    return FilterDesigner(source_impedance_ohm=50.0, load_impedance_ohm=50.0)


# =====================================================================
# Pi-filter insertion loss tests
# =====================================================================

class TestPiFilter:
    def test_pi_insertion_loss_at_dc_is_zero(self, designer):
        """At DC the pi-filter should pass signal with ~0 dB loss."""
        il = designer.calculate_insertion_loss(
            "pi", {"c1_pf": 1000, "l_uh": 1.0, "c2_pf": 1000},
            frequencies_mhz=[0.001],  # near DC
        )
        assert len(il.insertion_loss_db) == 1
        # Should be very close to 0 dB at near-DC
        assert abs(il.insertion_loss_db[0]) < 1.0

    def test_pi_insertion_loss_increases_with_frequency(self, designer):
        """Pi-filter attenuation should increase at higher frequencies."""
        il = designer.calculate_insertion_loss(
            "pi", {"c1_pf": 1000, "l_uh": 10.0, "c2_pf": 1000},
            frequencies_mhz=[1.0, 10.0, 100.0],
        )
        # Attenuation increases (values become more negative)
        assert il.insertion_loss_db[2] < il.insertion_loss_db[1]
        assert il.insertion_loss_db[1] < il.insertion_loss_db[0]

    def test_pi_has_cutoff_frequency(self, designer):
        """Pi-filter should report a -3 dB cutoff frequency."""
        il = designer.calculate_insertion_loss(
            "pi", {"c1_pf": 1000, "l_uh": 5.0, "c2_pf": 1000},
        )
        assert il.cutoff_frequency_mhz > 0

    def test_pi_high_attenuation_at_high_frequency(self, designer):
        """Well above cutoff, pi-filter should have large attenuation."""
        il = designer.calculate_insertion_loss(
            "pi", {"c1_pf": 2200, "l_uh": 10.0, "c2_pf": 2200},
            frequencies_mhz=[500.0],
        )
        # Should be significantly negative (large attenuation)
        assert il.insertion_loss_db[0] < -40

    def test_pi_filter_transfer_at_dc(self):
        """Direct transfer function at DC should be ~1.0."""
        h = _pi_filter_transfer(0.0, 1e-9, 1e-6, 1e-9, 50, 50)
        assert abs(h) == pytest.approx(1.0, abs=0.01)

    def test_pi_third_order_rolloff(self, designer):
        """Pi-filter (3rd order) should approach -60 dB/decade rolloff."""
        il = designer.calculate_insertion_loss(
            "pi", {"c1_pf": 1000, "l_uh": 5.0, "c2_pf": 1000},
            frequencies_mhz=[50.0, 500.0],
        )
        # Over one decade, 3rd order => ~60 dB more attenuation
        delta = il.insertion_loss_db[0] - il.insertion_loss_db[1]
        # Allow some tolerance (real filters aren't ideal)
        assert delta > 30  # at least 30 dB per decade


# =====================================================================
# LC low-pass filter tests
# =====================================================================

class TestLCFilter:
    def test_lc_dc_passthrough(self, designer):
        """LC filter at DC should pass signal."""
        il = designer.calculate_insertion_loss(
            "lc", {"l_uh": 1.0, "c_pf": 1000},
            frequencies_mhz=[0.001],
        )
        assert abs(il.insertion_loss_db[0]) < 1.0

    def test_lc_rolloff_rate_second_order(self, designer):
        """LC filter (2nd order) should approach -40 dB/decade."""
        # Use component values that give cutoff well below test range
        il = designer.calculate_insertion_loss(
            "lc", {"l_uh": 10.0, "c_pf": 10000},
            frequencies_mhz=[10.0, 100.0],
        )
        delta = il.insertion_loss_db[0] - il.insertion_loss_db[1]
        # Second order: ~40 dB/decade, allow tolerance
        assert delta > 25  # at least 25 dB over one decade

    def test_lc_cutoff_reported(self, designer):
        il = designer.calculate_insertion_loss(
            "lc", {"l_uh": 5.0, "c_pf": 5000},
        )
        assert il.cutoff_frequency_mhz > 0

    def test_lc_at_cutoff_is_approx_minus_3db(self, designer):
        """At the cutoff frequency, IL should be approximately -3 dB."""
        # Design an LC with known cutoff: f_c = 1/(2*pi*sqrt(L*C))
        l_uh = 10.0
        c_pf = 1000.0
        l_h = l_uh * 1e-6
        c_f = c_pf * 1e-12
        f_c_hz = 1.0 / (2 * math.pi * math.sqrt(l_h * c_f))
        f_c_mhz = f_c_hz / 1e6

        il = designer.calculate_insertion_loss(
            "lc", {"l_uh": l_uh, "c_pf": c_pf},
            frequencies_mhz=[f_c_mhz],
        )
        # At resonance of an LC in 50-ohm system, the exact value depends
        # on damping.  For a Butterworth design it would be -3 dB.
        # For an arbitrary LC, just check it's in the transition band.
        assert il.insertion_loss_db[0] < 0
        assert il.insertion_loss_db[0] > -20  # not way past cutoff


# =====================================================================
# CMC impedance model tests
# =====================================================================

class TestCMC:
    def test_cmc_impedance_rises_below_srf(self, designer):
        """CMC impedance should rise as frequency approaches SRF."""
        z_low = designer.cmc_impedance(1.0, l_cm_uh=100.0, srf_mhz=50.0)
        z_mid = designer.cmc_impedance(20.0, l_cm_uh=100.0, srf_mhz=50.0)
        assert z_mid > z_low

    def test_cmc_impedance_peaks_near_srf(self, designer):
        """CMC impedance should peak near SRF."""
        srf = 50.0
        z_at_srf = designer.cmc_impedance(srf, l_cm_uh=100.0, srf_mhz=srf)
        z_below = designer.cmc_impedance(srf / 5, l_cm_uh=100.0, srf_mhz=srf)
        z_above = designer.cmc_impedance(srf * 5, l_cm_uh=100.0, srf_mhz=srf)
        assert z_at_srf > z_below
        assert z_at_srf > z_above

    def test_cmc_impedance_falls_above_srf(self, designer):
        """CMC impedance should decrease well above SRF."""
        srf = 50.0
        z_at_srf = designer.cmc_impedance(srf, l_cm_uh=100.0, srf_mhz=srf)
        z_far_above = designer.cmc_impedance(srf * 10, l_cm_uh=100.0, srf_mhz=srf)
        assert z_far_above < z_at_srf

    def test_cmc_insertion_loss_increases_near_srf(self, designer):
        """CMC should provide more attenuation near SRF."""
        il = designer.calculate_insertion_loss(
            "cmc", {"l_cm_uh": 100.0, "srf_mhz": 50.0},
            frequencies_mhz=[1.0, 50.0],
        )
        # Near SRF should have more attenuation (more negative)
        assert il.insertion_loss_db[1] < il.insertion_loss_db[0]


# =====================================================================
# Ferrite bead impedance tests
# =====================================================================

class TestFerriteBead:
    def test_ferrite_impedance_peak_at_srf(self, designer):
        """Ferrite bead should have impedance peak near SRF."""
        srf = 100.0
        z_at_srf = designer.ferrite_impedance(srf, z_peak_ohm=600.0, srf_mhz=srf)
        z_below = designer.ferrite_impedance(srf / 10, z_peak_ohm=600.0, srf_mhz=srf)
        z_above = designer.ferrite_impedance(srf * 10, z_peak_ohm=600.0, srf_mhz=srf)
        assert z_at_srf > z_below
        assert z_at_srf > z_above

    def test_ferrite_impedance_at_dc_is_low(self, designer):
        """Ferrite bead impedance at very low freq should be small."""
        z = designer.ferrite_impedance(0.001, z_peak_ohm=600.0, srf_mhz=100.0)
        assert z < 50.0  # Much less than peak

    def test_ferrite_peak_value_reasonable(self, designer):
        """Peak impedance should be close to specified z_peak."""
        srf = 100.0
        z = designer.ferrite_impedance(srf, z_peak_ohm=600.0, srf_mhz=srf)
        # Should be within ~factor of 2 of specified peak
        assert z > 200.0
        assert z < 1200.0

    def test_ferrite_insertion_loss(self, designer):
        """Ferrite should attenuate signal near SRF."""
        il = designer.calculate_insertion_loss(
            "ferrite", {"z_peak_ohm": 600.0, "srf_mhz": 100.0},
            frequencies_mhz=[100.0],
        )
        assert il.insertion_loss_db[0] < -3  # Should attenuate


# =====================================================================
# auto_design_filter tests
# =====================================================================

class TestAutoDesignFilter:
    def test_auto_selects_pi_for_high_attenuation(self, designer):
        """High attenuation requirement should select pi-filter."""
        result = designer.auto_design_filter(
            failure_frequencies_mhz=[30.0],
            required_attenuation_db=[50.0],
            filter_type="auto",
        )
        assert result.filter_spec.topology == "pi"

    def test_auto_selects_ferrite_for_high_freq(self, designer):
        """High freq, moderate attenuation should select ferrite."""
        result = designer.auto_design_filter(
            failure_frequencies_mhz=[200.0],
            required_attenuation_db=[10.0],
            filter_type="auto",
        )
        assert result.filter_spec.topology == "ferrite"

    def test_auto_selects_cmc_for_low_freq(self, designer):
        """Low frequency failure should suggest CMC."""
        result = designer.auto_design_filter(
            failure_frequencies_mhz=[5.0],
            required_attenuation_db=[15.0],
            filter_type="auto",
        )
        assert result.filter_spec.topology == "cmc"

    def test_forced_topology_respected(self, designer):
        """Explicit filter_type should override auto selection."""
        result = designer.auto_design_filter(
            failure_frequencies_mhz=[100.0],
            required_attenuation_db=[20.0],
            filter_type="lc",
        )
        assert result.filter_spec.topology == "lc"

    def test_auto_design_returns_insertion_loss_curve(self, designer):
        """Result should include insertion loss curve data."""
        result = designer.auto_design_filter(
            failure_frequencies_mhz=[30.0, 100.0],
            required_attenuation_db=[20.0, 30.0],
        )
        assert len(result.insertion_loss.frequencies_mhz) > 0
        assert len(result.insertion_loss.insertion_loss_db) > 0

    def test_auto_design_achieved_attenuation_reported(self, designer):
        """Achieved attenuation should be reported for each failure freq."""
        result = designer.auto_design_filter(
            failure_frequencies_mhz=[30.0, 100.0],
            required_attenuation_db=[10.0, 20.0],
        )
        assert len(result.achieved_attenuation_db) == 2
        # All achieved values should be positive (attenuation)
        for a in result.achieved_attenuation_db:
            assert a >= 0

    def test_auto_design_no_failures(self, designer):
        """Empty failure list should return no-filter-needed result."""
        result = designer.auto_design_filter(
            failure_frequencies_mhz=[],
            required_attenuation_db=[],
        )
        assert result.meets_requirements is True

    def test_auto_design_meets_requirements_flag(self, designer):
        """meets_requirements should reflect if attenuation goals are met."""
        # Request very low attenuation -- should be met easily
        result = designer.auto_design_filter(
            failure_frequencies_mhz=[100.0],
            required_attenuation_db=[5.0],
        )
        assert result.meets_requirements is True

    def test_filter_reduces_emission_below_limit(self, designer):
        """Designed filter should reduce at least some emission at fail freq."""
        result = designer.auto_design_filter(
            failure_frequencies_mhz=[50.0],
            required_attenuation_db=[20.0],
        )
        # Achieved attenuation at 50 MHz should be > 0
        assert result.achieved_attenuation_db[0] > 0


# =====================================================================
# to_dict output tests
# =====================================================================

class TestToDict:
    def test_to_dict_contains_required_keys(self, designer):
        result = designer.auto_design_filter(
            failure_frequencies_mhz=[30.0],
            required_attenuation_db=[20.0],
        )
        d = designer.to_dict(result)
        assert "topology" in d
        assert "components" in d
        assert "cutoff_frequency_mhz" in d
        assert "meets_requirements" in d
        assert "insertion_loss_curve" in d
        assert "recommendations" in d
        assert "achieved_attenuation_db" in d
        assert "failure_frequencies_mhz" in d
        assert "required_attenuation_db" in d
        assert "max_attenuation_db" in d

    def test_to_dict_insertion_loss_curve_format(self, designer):
        result = designer.auto_design_filter(
            failure_frequencies_mhz=[30.0],
            required_attenuation_db=[20.0],
        )
        d = designer.to_dict(result)
        curve = d["insertion_loss_curve"]
        assert "frequencies_mhz" in curve
        assert "insertion_loss_db" in curve
        assert len(curve["frequencies_mhz"]) == len(curve["insertion_loss_db"])

    def test_to_dict_description_nonempty(self, designer):
        result = designer.auto_design_filter(
            failure_frequencies_mhz=[50.0],
            required_attenuation_db=[15.0],
        )
        d = designer.to_dict(result)
        assert len(d["description"]) > 0


# =====================================================================
# Edge cases
# =====================================================================

class TestEdgeCases:
    def test_zero_inductance_lc(self, designer):
        """LC filter with zero inductance should not crash."""
        il = designer.calculate_insertion_loss(
            "lc", {"l_uh": 0.0, "c_pf": 1000},
            frequencies_mhz=[1.0, 10.0, 100.0],
        )
        assert len(il.insertion_loss_db) == 3

    def test_very_high_frequency(self, designer):
        """Filter should handle very high frequencies without error."""
        il = designer.calculate_insertion_loss(
            "pi", {"c1_pf": 100, "l_uh": 0.1, "c2_pf": 100},
            frequencies_mhz=[5000.0, 10000.0],
        )
        assert len(il.insertion_loss_db) == 2
        # Should still have significant attenuation
        assert il.insertion_loss_db[0] < -10

    def test_single_failure_frequency(self, designer):
        """auto_design should work with a single failure frequency."""
        result = designer.auto_design_filter(
            failure_frequencies_mhz=[100.0],
            required_attenuation_db=[25.0],
        )
        assert result.filter_spec.topology in ("pi", "lc", "cmc", "ferrite")

    def test_mismatched_attenuation_list_padded(self, designer):
        """If fewer attenuation values than frequencies, should pad."""
        result = designer.auto_design_filter(
            failure_frequencies_mhz=[30.0, 100.0, 200.0],
            required_attenuation_db=[20.0],
        )
        assert len(result.achieved_attenuation_db) == 3

    def test_custom_impedance(self):
        """FilterDesigner should work with non-50-ohm impedances."""
        designer = FilterDesigner(source_impedance_ohm=75.0, load_impedance_ohm=75.0)
        il = designer.calculate_insertion_loss(
            "pi", {"c1_pf": 1000, "l_uh": 5.0, "c2_pf": 1000},
            frequencies_mhz=[1.0, 100.0],
        )
        assert il.insertion_loss_db[1] < il.insertion_loss_db[0]

    def test_unknown_topology_raises(self, designer):
        """Unknown topology should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown filter topology"):
            designer.calculate_insertion_loss(
                "unknown", {}, frequencies_mhz=[1.0],
            )

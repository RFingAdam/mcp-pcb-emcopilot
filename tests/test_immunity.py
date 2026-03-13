"""Tests for immunity margin analysis with coupling path model."""
from __future__ import annotations

import math

import pytest

from mcp_pcb_emcopilot.analyzers.emc.immunity import (
    IC_THRESHOLDS,
    ImmunityAnalysisResult,
    ImmunityAnalyzer,
    InterfaceImmunityResult,
    antenna_factor,
    bci_pin_voltage,
    effective_height,
    get_ic_threshold,
    transfer_impedance_shielded,
    transfer_impedance_unshielded,
    voltage_from_field,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def analyzer():
    return ImmunityAnalyzer()


@pytest.fixture
def sample_interfaces():
    return [
        {
            "name": "USB",
            "cable_length_mm": 500,
            "shielding": "shielded",
            "ic_type": "usb2_phy",
            "trace_length_mm": 30,
        },
        {
            "name": "CAN bus",
            "cable_length_mm": 2000,
            "shielding": "none",
            "ic_type": "cmos_logic",
            "trace_length_mm": 50,
        },
        {
            "name": "Ethernet",
            "cable_length_mm": 1000,
            "shielding": "shielded",
            "ic_type": "ethernet_phy",
            "trace_length_mm": 20,
        },
    ]


# ---------------------------------------------------------------------------
# 1. Coupling path voltage calculation at various field strengths
# ---------------------------------------------------------------------------

class TestVoltageFromField:
    def test_zero_field(self):
        assert voltage_from_field(0.0, 50.0) == 0.0

    def test_proportional_to_field(self):
        v1 = voltage_from_field(1.0, 50.0)
        v10 = voltage_from_field(10.0, 50.0)
        assert abs(v10 / v1 - 10.0) < 1e-9

    def test_short_trace_uses_length(self):
        # 10 mm trace at 100 MHz → wavelength ~ 3 m, trace is electrically short
        v = voltage_from_field(10.0, 10.0, 100e6)
        expected = 10.0 * 0.010  # h_eff ≈ trace length
        assert abs(v - expected) < 1e-6

    def test_higher_field_higher_voltage(self):
        v_low = voltage_from_field(1.0, 50.0)
        v_high = voltage_from_field(30.0, 50.0)
        assert v_high > v_low

    def test_longer_trace_higher_voltage(self):
        v_short = voltage_from_field(10.0, 10.0, 100e6)
        v_long = voltage_from_field(10.0, 100.0, 100e6)
        assert v_long > v_short


# ---------------------------------------------------------------------------
# 2. Antenna factor for different trace lengths
# ---------------------------------------------------------------------------

class TestAntennaFactor:
    def test_basic_af(self):
        af = antenna_factor(100e6, 1.0)
        wavelength = 299_792_458 / 100e6
        expected = 9.73 / wavelength
        assert abs(af - expected) < 1e-6

    def test_higher_freq_higher_af(self):
        af_low = antenna_factor(100e6, 1.0)
        af_high = antenna_factor(1e9, 1.0)
        assert af_high > af_low

    def test_higher_gain_lower_af(self):
        af_unity = antenna_factor(100e6, 1.0)
        af_gain = antenna_factor(100e6, 4.0)
        assert af_gain < af_unity

    def test_zero_frequency(self):
        assert antenna_factor(0.0) == 0.0

    def test_zero_gain(self):
        assert antenna_factor(100e6, 0.0) == 0.0


# ---------------------------------------------------------------------------
# 3. Transfer impedance for shielded vs unshielded cables
# ---------------------------------------------------------------------------

class TestTransferImpedance:
    def test_unshielded_dc(self):
        # At DC, only R_DC contribution
        zt = transfer_impedance_unshielded(0.05, 10.0, 0.0, 1.0)
        assert abs(zt - 0.05) < 1e-9

    def test_unshielded_increases_with_frequency(self):
        zt_low = transfer_impedance_unshielded(0.05, 10.0, 1e6, 1.0)
        zt_high = transfer_impedance_unshielded(0.05, 10.0, 100e6, 1.0)
        assert zt_high > zt_low

    def test_unshielded_scales_with_length(self):
        zt_short = transfer_impedance_unshielded(0.05, 10.0, 100e6, 0.5)
        zt_long = transfer_impedance_unshielded(0.05, 10.0, 100e6, 2.0)
        assert abs(zt_long / zt_short - 4.0) < 1e-6

    def test_shielded_less_than_unshielded(self):
        zt_unshield = transfer_impedance_unshielded(0.05, 10.0, 100e6, 1.0)
        zt_shield = transfer_impedance_shielded(0.05, 0.1, 100e6, 1.0)
        assert zt_shield < zt_unshield

    def test_shielded_thicker_shield_better(self):
        zt_thin = transfer_impedance_shielded(0.01, 0.05, 100e6, 1.0)
        zt_thick = transfer_impedance_shielded(0.01, 0.5, 100e6, 1.0)
        assert zt_thick < zt_thin

    def test_shielded_dc_no_skin_effect(self):
        zt = transfer_impedance_shielded(0.01, 0.1, 0.0, 1.0)
        # At DC skin depth → ∞, exp(-t/δ) → 1 (but function returns r*l)
        assert abs(zt - 0.01) < 1e-6


# ---------------------------------------------------------------------------
# 4. IC threshold lookups for each type
# ---------------------------------------------------------------------------

class TestICThresholds:
    def test_all_known_types(self):
        for ic_type in IC_THRESHOLDS:
            t = get_ic_threshold(ic_type)
            assert "upset_v" in t
            assert "damage_v" in t
            assert "description" in t

    def test_cmos_logic_values(self):
        t = get_ic_threshold("cmos_logic")
        assert t["upset_v"] == 0.3
        assert t["damage_v"] == 2.0

    def test_lpddr4_values(self):
        t = get_ic_threshold("lpddr4")
        assert t["upset_v"] == 0.2
        assert t["damage_v"] == 0.7

    def test_usb2_phy_values(self):
        t = get_ic_threshold("usb2_phy")
        assert t["upset_v"] == 0.4
        assert t["damage_v"] == 3.6

    def test_ethernet_phy_values(self):
        t = get_ic_threshold("ethernet_phy")
        assert t["upset_v"] == 1.0
        assert t["damage_v"] == 4.0

    def test_gnss_has_desense(self):
        t = get_ic_threshold("gnss_receiver")
        assert "desense_dbm" in t
        assert t["desense_dbm"] == -110.0

    def test_unknown_returns_default(self):
        t = get_ic_threshold("unknown_ic_xyz")
        assert t["upset_v"] == 0.3  # conservative CMOS default
        assert "unknown" in t["description"].lower() or "Unknown" in t["description"]


# ---------------------------------------------------------------------------
# 5. BCI to pin voltage conversion
# ---------------------------------------------------------------------------

class TestBCIPinVoltage:
    def test_basic_calculation(self):
        v = bci_pin_voltage(0.01, 5.0, 1.0)
        assert abs(v - 0.05) < 1e-9

    def test_coupling_factor_scales(self):
        v1 = bci_pin_voltage(0.01, 5.0, 1.0)
        v2 = bci_pin_voltage(0.01, 5.0, 0.5)
        assert abs(v2 / v1 - 0.5) < 1e-9

    def test_zero_current(self):
        v = bci_pin_voltage(0.0, 5.0, 1.0)
        assert v == 0.0


# ---------------------------------------------------------------------------
# 6. Margin calculation (positive = pass, negative = fail)
# ---------------------------------------------------------------------------

class TestMarginCalculation:
    def test_pass_margin(self, analyzer):
        """Small induced voltage vs large threshold → positive margin."""
        interfaces = [{
            "name": "test",
            "cable_length_mm": 100,
            "shielding": "shielded",
            "ic_type": "ethernet_phy",    # 1V upset threshold
            "trace_length_mm": 5,          # short trace → low coupling
        }]
        result = analyzer.analyze_immunity(interfaces, field_strength_vm=1.0)
        e_result = result.interface_results[0]  # electric_field
        assert e_result.upset_margin_db > 0

    def test_fail_margin(self, analyzer):
        """Large field + long trace + sensitive IC → negative margin."""
        interfaces = [{
            "name": "sensitive",
            "cable_length_mm": 2000,
            "shielding": "none",
            "ic_type": "lpddr4",          # 0.2V upset threshold
            "trace_length_mm": 200,        # long trace
        }]
        result = analyzer.analyze_immunity(interfaces, field_strength_vm=30.0)
        e_result = result.interface_results[0]
        assert e_result.upset_margin_db < 0
        assert e_result.status == "fail"

    def test_marginal_has_recommendation(self, analyzer):
        """Marginal or failing results should have recommendations."""
        interfaces = [{
            "name": "test",
            "cable_length_mm": 2000,
            "shielding": "none",
            "ic_type": "lpddr4",
            "trace_length_mm": 200,
        }]
        result = analyzer.analyze_immunity(interfaces, field_strength_vm=30.0)
        failing = [r for r in result.interface_results if r.status in ("fail", "marginal")]
        for r in failing:
            assert len(r.recommendation) > 0


# ---------------------------------------------------------------------------
# 7. Full interface analysis with multiple interfaces
# ---------------------------------------------------------------------------

class TestFullAnalysis:
    def test_multiple_interfaces(self, analyzer, sample_interfaces):
        result = analyzer.analyze_immunity(sample_interfaces, iso_level=3)
        # 3 interfaces × 2 coupling types = 6 results
        assert len(result.interface_results) == 6

    def test_iso_level_sets_field_strength(self, analyzer, sample_interfaces):
        result = analyzer.analyze_immunity(sample_interfaces, iso_level=3)
        assert result.field_strength_vm == 10.0
        assert result.bci_current_ma == 10.0

    def test_overall_status_reflects_worst(self, analyzer):
        """If any interface fails, overall should be fail."""
        interfaces = [
            {"name": "ok", "cable_length_mm": 100, "shielding": "shielded",
             "ic_type": "ethernet_phy", "trace_length_mm": 5},
            {"name": "bad", "cable_length_mm": 2000, "shielding": "none",
             "ic_type": "lpddr4", "trace_length_mm": 200},
        ]
        result = analyzer.analyze_immunity(interfaces, field_strength_vm=30.0)
        assert result.overall_status == "fail"

    def test_score_percentage(self, analyzer, sample_interfaces):
        result = analyzer.analyze_immunity(sample_interfaces, iso_level=3)
        assert 0 <= result.score <= 100

    def test_all_levels(self, analyzer, sample_interfaces):
        """All ISO levels should produce valid results."""
        for level in range(1, 6):
            result = analyzer.analyze_immunity(sample_interfaces, iso_level=level)
            assert result.iso_level == level
            assert result.overall_status in ("pass", "marginal", "fail")

    def test_higher_level_worse_margins(self, analyzer, sample_interfaces):
        """Higher ISO level = stronger field = worse margins."""
        r1 = analyzer.analyze_immunity(sample_interfaces, iso_level=1)
        r5 = analyzer.analyze_immunity(sample_interfaces, iso_level=5)
        # Average upset margin should be lower at level 5
        avg1 = sum(r.upset_margin_db for r in r1.interface_results) / len(r1.interface_results)
        avg5 = sum(r.upset_margin_db for r in r5.interface_results) / len(r5.interface_results)
        assert avg5 < avg1

    def test_shielded_better_than_unshielded(self, analyzer):
        """Shielded cables should produce lower BCI-induced voltage."""
        iface_shielded = [{
            "name": "shielded", "cable_length_mm": 1000, "shielding": "shielded",
            "ic_type": "cmos_logic", "trace_length_mm": 30,
        }]
        iface_unshielded = [{
            "name": "unshielded", "cable_length_mm": 1000, "shielding": "none",
            "ic_type": "cmos_logic", "trace_length_mm": 30,
        }]
        r_s = analyzer.analyze_immunity(iface_shielded, iso_level=3)
        r_u = analyzer.analyze_immunity(iface_unshielded, iso_level=3)
        # BCI result is index 1
        bci_s = r_s.interface_results[1]
        bci_u = r_u.interface_results[1]
        assert bci_s.induced_voltage_v < bci_u.induced_voltage_v

    def test_recommendations_populated(self, analyzer, sample_interfaces):
        result = analyzer.analyze_immunity(sample_interfaces, iso_level=3)
        assert len(result.recommendations) > 0


# ---------------------------------------------------------------------------
# 8. to_dict output format
# ---------------------------------------------------------------------------

class TestToDict:
    def test_to_dict_keys(self, analyzer, sample_interfaces):
        result = analyzer.analyze_immunity(sample_interfaces, iso_level=3)
        d = analyzer.to_dict(result)
        assert "iso_level" in d
        assert "field_strength_vm" in d
        assert "bci_current_ma" in d
        assert "overall_status" in d
        assert "score" in d
        assert "interface_count" in d
        assert "interfaces" in d
        assert "recommendations" in d

    def test_to_dict_interface_keys(self, analyzer, sample_interfaces):
        result = analyzer.analyze_immunity(sample_interfaces, iso_level=3)
        d = analyzer.to_dict(result)
        for iface in d["interfaces"]:
            assert "interface_name" in iface
            assert "ic_type" in iface
            assert "coupling_type" in iface
            assert "induced_voltage_v" in iface
            assert "upset_threshold_v" in iface
            assert "upset_margin_db" in iface
            assert "status" in iface

    def test_to_dict_count_matches(self, analyzer, sample_interfaces):
        result = analyzer.analyze_immunity(sample_interfaces, iso_level=3)
        d = analyzer.to_dict(result)
        assert d["interface_count"] == len(d["interfaces"])

    def test_to_dict_serializable(self, analyzer, sample_interfaces):
        """Output should be JSON-serializable (all native types)."""
        import json
        result = analyzer.analyze_immunity(sample_interfaces, iso_level=3)
        d = analyzer.to_dict(result)
        # Should not raise
        json.dumps(d)


# ---------------------------------------------------------------------------
# 9. Effective height edge cases
# ---------------------------------------------------------------------------

class TestEffectiveHeight:
    def test_short_trace(self):
        """Electrically short trace: h_eff ≈ trace length."""
        h = effective_height(10.0, 100e6)  # 10 mm at 100 MHz
        assert abs(h - 0.010) < 1e-6

    def test_very_long_trace_saturates(self):
        """Very long trace: h_eff saturates at lambda/pi."""
        h = effective_height(10_000.0, 100e6)  # 10 m at 100 MHz
        wavelength = 299_792_458 / 100e6
        h_max = wavelength / math.pi
        assert abs(h - h_max) < 1e-3

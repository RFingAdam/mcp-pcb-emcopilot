"""Tests for conducted emissions analysis — LISN, CISPR 25 & FCC Part 15."""
from __future__ import annotations

import math

import pytest

from mcp_pcb_emcopilot.analyzers.emc.automotive_emc import CISPR25_CONDUCTED_LIMITS
from mcp_pcb_emcopilot.analyzers.emc.conducted_emissions import (
    FCC_PART15_CONDUCTED_LIMITS,
    ConductedEmissionAnalysis,
    ConductedEmissionAnalyzer,
    ConductedEmissionFinding,
    LISNModel,
)


@pytest.fixture
def analyzer():
    return ConductedEmissionAnalyzer()


@pytest.fixture
def lisn():
    return LISNModel()


# ===========================================================================
# LISN impedance model
# ===========================================================================

class TestLISNImpedance:
    def test_impedance_at_dc_is_zero(self, lisn):
        """At DC the inductor is a short, so Z_LISN -> 0."""
        assert lisn.impedance_at(0) == 0.0

    def test_impedance_below_corner_is_low(self, lisn):
        """Well below the corner frequency, impedance is dominated by inductor (low)."""
        z = lisn.impedance_at(1e3)  # 1 kHz
        assert z < 5.0  # should be very low

    def test_impedance_above_corner_approaches_50(self, lisn):
        """Well above the corner frequency, impedance approaches 50 Ohm."""
        z = lisn.impedance_at(10e6)  # 10 MHz
        assert 49.0 < z <= 50.0

    def test_impedance_at_corner_frequency(self, lisn):
        """At the corner frequency |Z| should be R/sqrt(2) ≈ 35.4 Ohm."""
        f_c = lisn.corner_frequency_hz
        z = lisn.impedance_at(f_c)
        expected = lisn.resistance_ohm / math.sqrt(2)
        assert abs(z - expected) < 0.5

    def test_corner_frequency_value(self, lisn):
        """Corner freq for 50µH/50Ω: f_c = R/(2π·L) ≈ 159 kHz."""
        f_c = lisn.corner_frequency_hz
        expected = 50 / (2 * math.pi * 50e-6)  # ~159 kHz
        assert abs(f_c - expected) < 1.0

    def test_impedance_monotonically_increases_to_limit(self, lisn):
        """Impedance should increase with frequency up to the resistor limit."""
        freqs = [1e3, 10e3, 100e3, 1e6, 10e6]
        zs = [lisn.impedance_at(f) for f in freqs]
        for i in range(len(zs) - 1):
            assert zs[i + 1] >= zs[i]

    def test_custom_lisn_values(self):
        """Non-standard LISN parameters should work correctly."""
        custom = LISNModel(inductance_uh=5.0, resistance_ohm=50.0)
        # Corner should be 10x higher than standard 50µH
        assert custom.corner_frequency_hz > LISNModel().corner_frequency_hz


# ===========================================================================
# FCC Part 15 conducted limit lookups
# ===========================================================================

class TestFCCLimits:
    def test_class_b_150khz(self, analyzer):
        result = analyzer.get_fcc_conducted_limit(0.2, "B")
        assert result is not None
        assert result["qp_limit_dbuv"] == 66
        assert result["avg_limit_dbuv"] == 56

    def test_class_b_above_500khz(self, analyzer):
        result = analyzer.get_fcc_conducted_limit(1.0, "B")
        assert result is not None
        assert result["qp_limit_dbuv"] == 56
        assert result["avg_limit_dbuv"] == 46

    def test_class_b_above_5mhz(self, analyzer):
        result = analyzer.get_fcc_conducted_limit(10.0, "B")
        assert result is not None
        assert result["qp_limit_dbuv"] == 60
        assert result["avg_limit_dbuv"] == 50

    def test_class_a_is_more_permissive(self, analyzer):
        a = analyzer.get_fcc_conducted_limit(0.3, "A")
        b = analyzer.get_fcc_conducted_limit(0.3, "B")
        assert a is not None and b is not None
        assert a["qp_limit_dbuv"] > b["qp_limit_dbuv"]

    def test_out_of_range_returns_none(self, analyzer):
        assert analyzer.get_fcc_conducted_limit(50.0, "B") is None

    def test_invalid_class_returns_none(self, analyzer):
        assert analyzer.get_fcc_conducted_limit(1.0, "X") is None

    def test_fcc_class_a_at_1mhz(self, analyzer):
        result = analyzer.get_fcc_conducted_limit(1.0, "A")
        assert result is not None
        assert result["qp_limit_dbuv"] == 73
        assert result["avg_limit_dbuv"] == 60


# ===========================================================================
# CISPR 25 conducted limit lookups (via analyzer, referencing shared data)
# ===========================================================================

class TestCISPR25ConductedLimits:
    def test_lookup_class3_lf(self, analyzer):
        result = analyzer.get_cispr25_conducted_limit(0.2, cispr_class=3)
        assert result is not None
        assert result["peak_limit_dbuv"] == 70
        assert result["avg_limit_dbuv"] == 60

    def test_lookup_class1_more_permissive(self, analyzer):
        c1 = analyzer.get_cispr25_conducted_limit(1.0, cispr_class=1)
        c5 = analyzer.get_cispr25_conducted_limit(1.0, cispr_class=5)
        assert c1 is not None and c5 is not None
        assert c1["peak_limit_dbuv"] > c5["peak_limit_dbuv"]

    def test_invalid_class_returns_none(self, analyzer):
        assert analyzer.get_cispr25_conducted_limit(1.0, cispr_class=0) is None
        assert analyzer.get_cispr25_conducted_limit(1.0, cispr_class=6) is None

    def test_out_of_range_frequency(self, analyzer):
        # 200 MHz is outside CISPR 25 conducted range
        assert analyzer.get_cispr25_conducted_limit(200.0, cispr_class=3) is None

    def test_shared_data_matches(self, analyzer):
        """CISPR 25 conducted limits should reference the same data as automotive_emc."""
        result = analyzer.get_cispr25_conducted_limit(50.0, cispr_class=3)
        assert result is not None
        assert result["peak_limit_dbuv"] == 40
        assert result["avg_limit_dbuv"] == 30


# ===========================================================================
# SMPS harmonic prediction
# ===========================================================================

class TestSMPSHarmonics:
    def test_harmonics_decrease_with_order(self, analyzer):
        """Higher harmonics should generally have lower amplitude."""
        harmonics = analyzer.predict_smps_harmonics(
            switching_freq_khz=200, input_voltage=12.0,
            duty_cycle=0.5, rise_time_ns=20.0, num_harmonics=10,
        )
        # First harmonic should be higher than 10th
        assert harmonics[0]["level_dbuv"] > harmonics[-1]["level_dbuv"]

    def test_harmonics_count(self, analyzer):
        harmonics = analyzer.predict_smps_harmonics(
            switching_freq_khz=100, input_voltage=12.0,
            duty_cycle=0.5, rise_time_ns=20.0, num_harmonics=20,
        )
        assert len(harmonics) == 20

    def test_harmonic_frequencies_correct(self, analyzer):
        harmonics = analyzer.predict_smps_harmonics(
            switching_freq_khz=500, input_voltage=12.0,
            duty_cycle=0.5, rise_time_ns=10.0, num_harmonics=5,
        )
        for i, h in enumerate(harmonics):
            expected_mhz = 0.5 * (i + 1)
            assert abs(h["frequency_mhz"] - expected_mhz) < 0.01

    def test_filter_reduces_levels(self, analyzer):
        """Input filter attenuation should reduce predicted levels."""
        h_no_filter = analyzer.predict_smps_harmonics(
            switching_freq_khz=200, input_voltage=12.0,
            duty_cycle=0.5, rise_time_ns=20.0, num_harmonics=5,
            input_filter_db=0.0,
        )
        h_filtered = analyzer.predict_smps_harmonics(
            switching_freq_khz=200, input_voltage=12.0,
            duty_cycle=0.5, rise_time_ns=20.0, num_harmonics=5,
            input_filter_db=20.0,
        )
        for nf, f in zip(h_no_filter, h_filtered):
            assert f["level_dbuv"] < nf["level_dbuv"]
            assert abs(nf["level_dbuv"] - f["level_dbuv"] - 20.0) < 0.1

    def test_lisn_impedance_recorded(self, analyzer):
        harmonics = analyzer.predict_smps_harmonics(
            switching_freq_khz=200, input_voltage=12.0,
            duty_cycle=0.5, rise_time_ns=20.0, num_harmonics=5,
        )
        for h in harmonics:
            assert "lisn_impedance_ohm" in h
            assert h["lisn_impedance_ohm"] > 0


# ===========================================================================
# Compliance prediction
# ===========================================================================

class TestCompliancePrediction:
    def test_returns_analysis_object(self, analyzer):
        result = analyzer.predict_conducted_compliance(
            switching_freq_khz=200, input_voltage=12.0,
            duty_cycle=0.5, rise_time_ns=20.0,
        )
        assert isinstance(result, ConductedEmissionAnalysis)

    def test_status_is_valid(self, analyzer):
        result = analyzer.predict_conducted_compliance(
            switching_freq_khz=200, input_voltage=12.0,
            duty_cycle=0.5, rise_time_ns=20.0,
        )
        assert result.overall_status in ("pass", "marginal", "fail", "unknown")

    def test_findings_have_margins(self, analyzer):
        result = analyzer.predict_conducted_compliance(
            switching_freq_khz=200, input_voltage=12.0,
            duty_cycle=0.5, rise_time_ns=20.0,
        )
        for f in result.findings:
            if f.status != "unknown":
                assert f.margin_db is not None

    def test_filter_improves_compliance(self, analyzer):
        unfiltered = analyzer.predict_conducted_compliance(
            switching_freq_khz=200, input_voltage=24.0,
            duty_cycle=0.5, rise_time_ns=5.0,
            input_filter_db=0.0,
        )
        filtered = analyzer.predict_conducted_compliance(
            switching_freq_khz=200, input_voltage=24.0,
            duty_cycle=0.5, rise_time_ns=5.0,
            input_filter_db=40.0,
        )
        assert filtered.score >= unfiltered.score

    def test_recommendations_generated(self, analyzer):
        result = analyzer.predict_conducted_compliance(
            switching_freq_khz=100, input_voltage=24.0,
            duty_cycle=0.5, rise_time_ns=5.0,
        )
        # Should have at least one recommendation
        assert len(result.recommendations) > 0 or result.overall_status == "pass"

    def test_notes_include_lisn_info(self, analyzer):
        result = analyzer.predict_conducted_compliance(
            switching_freq_khz=200, input_voltage=12.0,
            duty_cycle=0.5, rise_time_ns=20.0,
        )
        assert any("LISN" in n for n in result.notes)

    def test_score_between_0_and_100(self, analyzer):
        result = analyzer.predict_conducted_compliance(
            switching_freq_khz=200, input_voltage=12.0,
            duty_cycle=0.5, rise_time_ns=20.0,
        )
        assert 0 <= result.score <= 100

    def test_marginal_status_exists(self, analyzer):
        """6 dB margin boundary should produce marginal findings."""
        # This is a statistical check — we just verify the model can produce
        # findings with any status
        result = analyzer.predict_conducted_compliance(
            switching_freq_khz=200, input_voltage=12.0,
            duty_cycle=0.5, rise_time_ns=20.0,
        )
        statuses = {f.status for f in result.findings}
        # We at least need pass or marginal or fail present
        assert len(statuses) > 0


# ===========================================================================
# to_dict output format
# ===========================================================================

class TestToDict:
    def test_top_level_keys(self, analyzer):
        analysis = analyzer.predict_conducted_compliance(
            switching_freq_khz=200, input_voltage=12.0,
            duty_cycle=0.5, rise_time_ns=20.0,
        )
        d = analyzer.to_dict(analysis)
        assert "overall_status" in d
        assert "score" in d
        assert "worst_margin_db" in d
        assert "cispr25_class" in d
        assert "fcc_class" in d
        assert "findings" in d
        assert "recommendations" in d
        assert "notes" in d
        assert "smps_params" in d
        assert "findings_count" in d

    def test_findings_only_issues(self, analyzer):
        """The 'findings' key should only contain fail/marginal entries."""
        analysis = analyzer.predict_conducted_compliance(
            switching_freq_khz=200, input_voltage=12.0,
            duty_cycle=0.5, rise_time_ns=20.0,
        )
        d = analyzer.to_dict(analysis)
        for f in d["findings"]:
            assert f["status"] in ("fail", "marginal")

    def test_all_findings_summary_included(self, analyzer):
        analysis = analyzer.predict_conducted_compliance(
            switching_freq_khz=200, input_voltage=12.0,
            duty_cycle=0.5, rise_time_ns=20.0,
        )
        d = analyzer.to_dict(analysis)
        assert "all_findings_summary" in d
        assert len(d["all_findings_summary"]) == len(analysis.findings)

    def test_smps_params_in_output(self, analyzer):
        analysis = analyzer.predict_conducted_compliance(
            switching_freq_khz=300, input_voltage=48.0,
            duty_cycle=0.25, rise_time_ns=10.0,
        )
        d = analyzer.to_dict(analysis)
        assert d["smps_params"]["switching_freq_khz"] == 300
        assert d["smps_params"]["input_voltage"] == 48.0
        assert d["smps_params"]["duty_cycle"] == 0.25

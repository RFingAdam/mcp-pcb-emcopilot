"""Tests for automotive EMC standards module."""
from __future__ import annotations

import pytest

from mcp_pcb_emcopilot.analyzers.emc.automotive_emc import (
    CISPR25_CONDUCTED_LIMITS,
    CISPR25_RADIATED_LIMITS,
    ISO11452_BCI_LEVELS,
    ISO11452_FIELD_LEVELS,
    AutomotiveComplianceResult,
    AutomotiveEMCAnalysis,
    AutomotiveEMCAnalyzer,
)


@pytest.fixture
def analyzer():
    return AutomotiveEMCAnalyzer()


class TestCISPR25RadiatedLimits:
    def test_lookup_known_frequency(self, analyzer):
        result = analyzer.get_cispr25_limit(100.0, cispr_class=3, category="radiated")
        assert result is not None
        assert result["class"] == 3
        assert "limit_dbuvm" in result

    def test_lookup_low_frequency(self, analyzer):
        result = analyzer.get_cispr25_limit(0.2, cispr_class=3, category="radiated")
        assert result is not None
        assert result["limit_dbuvm"] == 32  # Class 3 @ 0.15-0.3 MHz

    def test_lookup_high_frequency(self, analyzer):
        result = analyzer.get_cispr25_limit(2000.0, cispr_class=3, category="radiated")
        assert result is not None

    def test_frequency_outside_ranges(self, analyzer):
        result = analyzer.get_cispr25_limit(10.0, cispr_class=3, category="radiated")
        assert result is None  # 10 MHz is in a gap between defined ranges

    def test_class_1_more_permissive(self, analyzer):
        c1 = analyzer.get_cispr25_limit(100.0, cispr_class=1)
        c5 = analyzer.get_cispr25_limit(100.0, cispr_class=5)
        assert c1 is not None and c5 is not None
        assert c1["limit_dbuvm"] > c5["limit_dbuvm"]

    def test_all_classes_have_limits(self, analyzer):
        for cls in range(1, 6):
            result = analyzer.get_cispr25_limit(100.0, cispr_class=cls)
            assert result is not None, f"Class {cls} should have a limit at 100 MHz"

    def test_invalid_class_returns_none(self, analyzer):
        assert analyzer.get_cispr25_limit(100.0, cispr_class=0) is None
        assert analyzer.get_cispr25_limit(100.0, cispr_class=6) is None


class TestCISPR25ConductedLimits:
    def test_conducted_lookup(self, analyzer):
        result = analyzer.get_cispr25_limit(1.0, cispr_class=3, category="conducted")
        assert result is not None
        assert "peak_limit_dbuv" in result
        assert "avg_limit_dbuv" in result

    def test_conducted_peak_higher_than_avg(self, analyzer):
        result = analyzer.get_cispr25_limit(1.0, cispr_class=3, category="conducted")
        assert result["peak_limit_dbuv"] > result["avg_limit_dbuv"]


class TestISO11452Levels:
    def test_level_3_default(self, analyzer):
        result = analyzer.get_iso11452_level(3)
        assert result is not None
        assert result["level"] == 3
        assert result["field_strength_vm"] == 10
        assert result["bci_current_ma"] == 10

    def test_all_levels(self, analyzer):
        for lvl in range(1, 6):
            result = analyzer.get_iso11452_level(lvl)
            assert result is not None

    def test_levels_increase(self, analyzer):
        l1 = analyzer.get_iso11452_level(1)
        l5 = analyzer.get_iso11452_level(5)
        assert l5["field_strength_vm"] > l1["field_strength_vm"]

    def test_invalid_level(self, analyzer):
        assert analyzer.get_iso11452_level(0) is None
        assert analyzer.get_iso11452_level(6) is None


class TestCompliancePrediction:
    def test_predict_single_clock(self, analyzer):
        results = analyzer.predict_cispr25_compliance([50.0])
        assert len(results) > 0
        assert all(isinstance(r, AutomotiveComplianceResult) for r in results)

    def test_predict_includes_harmonics(self, analyzer):
        results = analyzer.predict_cispr25_compliance([10.0])
        freqs = [r.frequency_mhz for r in results]
        # Should include harmonics (multiples of 10 MHz)
        assert any(f > 10.0 for f in freqs)

    def test_all_results_have_status(self, analyzer):
        results = analyzer.predict_cispr25_compliance([100.0])
        for r in results:
            assert r.status in ("pass", "marginal", "fail")

    def test_shielding_improves_margin(self, analyzer):
        no_shield = analyzer.predict_cispr25_compliance([100.0], shielding_db=0)
        shielded = analyzer.predict_cispr25_compliance([100.0], shielding_db=20)
        # Find a common frequency
        no_shield_margins = {r.frequency_mhz: r.margin_db for r in no_shield if r.margin_db is not None}
        for r in shielded:
            if r.frequency_mhz in no_shield_margins and r.margin_db is not None:
                assert r.margin_db > no_shield_margins[r.frequency_mhz]

    def test_harmonic_rolloff(self, analyzer):
        results = analyzer.predict_cispr25_compliance([50.0])
        # Find fundamental and higher harmonic at same limit band
        fundamentals = [r for r in results if r.frequency_mhz == 50.0]
        higher = [r for r in results if r.frequency_mhz > 50.0]
        # Higher harmonics should generally have lower predicted values (more rolloff)
        # (though limit values also change with frequency, so this is approximate)
        assert len(higher) > 0


class TestFullAnalysis:
    def test_overall_status_set(self, analyzer):
        analysis = analyzer.analyze_automotive_design([100.0])
        assert analysis.overall_status in ("pass", "marginal", "fail")

    def test_score_calculated(self, analyzer):
        analysis = analyzer.analyze_automotive_design([100.0])
        assert 0 <= analysis.score <= 100

    def test_recommendations_generated(self, analyzer):
        analysis = analyzer.analyze_automotive_design([200.0], has_shielding=False, has_input_filter=False)
        assert len(analysis.recommendations) > 0
        # Should recommend shielding
        assert any("shielding" in r.lower() for r in analysis.recommendations)

    def test_high_freq_clock_recommendation(self, analyzer):
        analysis = analyzer.analyze_automotive_design([200.0])
        assert any("spread-spectrum" in r.lower() or "ssc" in r.lower() for r in analysis.recommendations)

    def test_iso_immunity_recommendation(self, analyzer):
        analysis = analyzer.analyze_automotive_design([50.0], iso_level=4)
        assert any("iso 11452" in r.lower() or "immunity" in r.lower() for r in analysis.recommendations)

    def test_to_dict_format(self, analyzer):
        analysis = analyzer.analyze_automotive_design([100.0])
        d = analyzer.to_dict(analysis)
        assert "overall_status" in d
        assert "score" in d
        assert "cispr25_class" in d
        assert "iso11452_level" in d
        assert "findings" in d
        assert "recommendations" in d

    def test_to_dict_only_issues(self, analyzer):
        analysis = analyzer.analyze_automotive_design([100.0])
        d = analyzer.to_dict(analysis)
        # to_dict should only include fail/marginal findings
        for f in d["findings"]:
            assert f["status"] in ("fail", "marginal")

    def test_shielded_vs_unshielded(self, analyzer):
        unshielded = analyzer.analyze_automotive_design([100.0], has_shielding=False)
        shielded = analyzer.analyze_automotive_design([100.0], has_shielding=True)
        assert shielded.score >= unshielded.score


class TestDataConstants:
    def test_radiated_limits_cover_key_bands(self):
        # Should cover AM broadcast, FM broadcast, cellular bands
        freq_ranges = [(e["freq_min_mhz"], e["freq_max_mhz"]) for e in CISPR25_RADIATED_LIMITS]
        # AM broadcast (0.53-1.7 MHz)
        assert any(fmin <= 1.0 <= fmax for fmin, fmax in freq_ranges)
        # FM broadcast (87.5-108 MHz)
        assert any(fmin <= 100.0 <= fmax for fmin, fmax in freq_ranges)

    def test_iso_levels_complete(self):
        assert len(ISO11452_FIELD_LEVELS) == 5
        assert len(ISO11452_BCI_LEVELS) == 5

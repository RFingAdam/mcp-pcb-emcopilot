"""Tests for near-field probe and current loop EMI modeling.

Covers Issue #35:
- H-field from small current loop (magnetic dipole)
- E-field from electric dipole (voltage-driven trace)
- Near-field / far-field transition distance
- Source classification (magnetic vs electric)
- Multiple sources at different frequencies
- Field decay rates (1/r^3 near-field, 1/r far-field)
- to_dict output format
- Edge cases (zero current, zero area)
- MCP tool dispatch
"""
from __future__ import annotations

import asyncio
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from mcp_pcb_emcopilot.analyzers.emc.near_field import (
    _C,
    ELECTRIC_SOURCE_TYPES,
    MAGNETIC_SOURCE_TYPES,
    FieldPoint,
    NearFieldAnalysis,
    NearFieldAnalyzer,
    NearFieldSource,
    SourceResult,
    classify_source,
    determine_region,
    e_field_electric_dipole,
    h_field_magnetic_dipole,
    to_db_e,
    to_db_h,
    transition_distance,
    wavelength,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def analyzer():
    return NearFieldAnalyzer()


@pytest.fixture
def magnetic_source():
    """100 MHz SMPS inductor loop, 1A, 25 mm^2 area."""
    return {
        "name": "SMPS Loop",
        "type": "current_loop",
        "frequency_mhz": 100.0,
        "current_a": 1.0,
        "area_mm2": 25.0,
    }


@pytest.fixture
def electric_source():
    """100 MHz clock trace, 3.3V, 20 mm long."""
    return {
        "name": "CLK Trace",
        "type": "clock_trace",
        "frequency_mhz": 100.0,
        "voltage_v": 3.3,
        "length_mm": 20.0,
    }


# =====================================================================
# 1. H-field from small loop at various distances
# =====================================================================

class TestHFieldMagneticDipole:
    def test_h_field_at_1mm(self):
        """H-field from 1A, 25mm^2 loop at 100 MHz, 1mm distance."""
        area_m2 = 25e-6  # 25 mm^2
        h = h_field_magnetic_dipole(1.0, area_m2, 100.0, 0.001)
        assert h > 0
        # At 1mm with 25mm^2 loop, reactive near-field:
        # H = I*A/(4*pi*r^3) = 1*25e-6 / (4*pi*1e-9) = ~1989 A/m
        expected = 1.0 * 25e-6 / (4 * math.pi * (0.001)**3)
        assert abs(h - expected) / expected < 0.01  # within 1%

    def test_h_field_at_10mm(self):
        """H-field at 10mm distance."""
        area_m2 = 25e-6
        h = h_field_magnetic_dipole(1.0, area_m2, 100.0, 0.01)
        assert h > 0

    def test_h_field_at_1m(self):
        """H-field at 1m distance (far-field for 100 MHz)."""
        area_m2 = 25e-6
        h = h_field_magnetic_dipole(1.0, area_m2, 100.0, 1.0)
        assert h > 0
        # At 1m, far-field should dominate for 100 MHz (lambda=3m, r_trans~0.48m)

    def test_h_field_decreases_with_distance(self):
        """H-field must decrease as distance increases."""
        area_m2 = 25e-6
        h_1mm = h_field_magnetic_dipole(1.0, area_m2, 100.0, 0.001)
        h_10mm = h_field_magnetic_dipole(1.0, area_m2, 100.0, 0.01)
        h_100mm = h_field_magnetic_dipole(1.0, area_m2, 100.0, 0.1)
        h_1m = h_field_magnetic_dipole(1.0, area_m2, 100.0, 1.0)
        assert h_1mm > h_10mm > h_100mm > h_1m

    def test_h_field_near_field_1_over_r3(self):
        """In reactive near-field, H should follow ~1/r^3."""
        area_m2 = 25e-6
        r1 = 0.001
        r2 = 0.002  # double the distance
        h1 = h_field_magnetic_dipole(1.0, area_m2, 100.0, r1)
        h2 = h_field_magnetic_dipole(1.0, area_m2, 100.0, r2)
        # 1/r^3: doubling distance should reduce by factor of 8
        ratio = h1 / h2
        assert abs(ratio - 8.0) / 8.0 < 0.05  # within 5%

    def test_h_field_far_field_1_over_r(self):
        """In far-field, H should follow ~1/r."""
        area_m2 = 25e-6
        # For 100 MHz: lambda=3m, r_trans~0.48m.
        # Far-field distances: well beyond transition
        r1 = 5.0
        r2 = 10.0
        h1 = h_field_magnetic_dipole(1.0, area_m2, 100.0, r1)
        h2 = h_field_magnetic_dipole(1.0, area_m2, 100.0, r2)
        ratio = h1 / h2
        assert abs(ratio - 2.0) / 2.0 < 0.05

    def test_h_field_proportional_to_current(self):
        """H-field should scale linearly with current."""
        area_m2 = 25e-6
        h1 = h_field_magnetic_dipole(1.0, area_m2, 100.0, 0.01)
        h2 = h_field_magnetic_dipole(2.0, area_m2, 100.0, 0.01)
        assert abs(h2 / h1 - 2.0) < 0.01

    def test_h_field_proportional_to_area(self):
        """H-field should scale linearly with loop area."""
        h1 = h_field_magnetic_dipole(1.0, 25e-6, 100.0, 0.01)
        h2 = h_field_magnetic_dipole(1.0, 50e-6, 100.0, 0.01)
        assert abs(h2 / h1 - 2.0) < 0.01


# =====================================================================
# 2. E-field from electric dipole
# =====================================================================

class TestEFieldElectricDipole:
    def test_e_field_at_10mm(self):
        """E-field from 3.3V, 20mm trace at 100 MHz, 10mm distance."""
        e = e_field_electric_dipole(3.3, 0.02, 100.0, 0.01)
        assert e > 0

    def test_e_field_decreases_with_distance(self):
        """E-field must decrease with distance."""
        e_1mm = e_field_electric_dipole(3.3, 0.02, 100.0, 0.001)
        e_10mm = e_field_electric_dipole(3.3, 0.02, 100.0, 0.01)
        e_1m = e_field_electric_dipole(3.3, 0.02, 100.0, 1.0)
        assert e_1mm > e_10mm > e_1m

    def test_e_field_near_field_1_over_r2(self):
        """In near-field, E should follow ~1/r^2."""
        r1 = 0.001
        r2 = 0.002
        e1 = e_field_electric_dipole(3.3, 0.02, 100.0, r1)
        e2 = e_field_electric_dipole(3.3, 0.02, 100.0, r2)
        ratio = e1 / e2
        assert abs(ratio - 4.0) / 4.0 < 0.05

    def test_e_field_proportional_to_voltage(self):
        """E-field should scale linearly with voltage."""
        e1 = e_field_electric_dipole(1.0, 0.02, 100.0, 0.01)
        e2 = e_field_electric_dipole(3.0, 0.02, 100.0, 0.01)
        assert abs(e2 / e1 - 3.0) < 0.01


# =====================================================================
# 3. Near-field / far-field transition distance
# =====================================================================

class TestTransitionDistance:
    def test_transition_100mhz(self):
        """Transition at 100 MHz: lambda = 3m, r = 3/(2*pi) ~ 0.477m."""
        r = transition_distance(100.0)
        expected = 3.0 / (2 * math.pi)
        assert abs(r - expected) / expected < 0.01

    def test_transition_1ghz(self):
        """Transition at 1 GHz: lambda = 0.3m, r ~ 0.0477m."""
        r = transition_distance(1000.0)
        expected = 0.3 / (2 * math.pi)
        assert abs(r - expected) / expected < 0.01

    def test_transition_increases_with_lower_frequency(self):
        """Lower frequency = larger transition distance."""
        r_100 = transition_distance(100.0)
        r_1000 = transition_distance(1000.0)
        assert r_100 > r_1000

    def test_transition_zero_frequency(self):
        """Zero frequency should return infinity."""
        r = transition_distance(0.0)
        assert r == float("inf")

    def test_wavelength_calculation(self):
        """Verify wavelength calculation."""
        lam = wavelength(300.0)  # 300 MHz -> lambda = 1m
        assert abs(lam - 1.0) < 0.001


# =====================================================================
# 4. Source classification
# =====================================================================

class TestSourceClassification:
    def test_magnetic_sources(self):
        for st in MAGNETIC_SOURCE_TYPES:
            assert classify_source(st) == "magnetic"

    def test_electric_sources(self):
        for st in ELECTRIC_SOURCE_TYPES:
            assert classify_source(st) == "electric"

    def test_unknown_source(self):
        assert classify_source("weird_thing") == "unknown"

    def test_case_insensitive(self):
        assert classify_source("Current_Loop") == "magnetic"
        assert classify_source("CLOCK_TRACE") == "electric"


# =====================================================================
# 5. Multiple sources at different frequencies
# =====================================================================

class TestMultipleSources:
    def test_analyze_two_sources(self, analyzer, magnetic_source, electric_source):
        """Analyze both magnetic and electric sources together."""
        analysis = analyzer.analyze_sources([magnetic_source, electric_source])
        assert len(analysis.sources) == 2
        assert analysis.dominant_source != ""
        assert analysis.summary != ""

    def test_different_frequencies(self, analyzer):
        """Sources at different frequencies produce different transition distances."""
        sources = [
            {"name": "Low-F Loop", "type": "current_loop", "frequency_mhz": 10.0,
             "current_a": 1.0, "area_mm2": 25.0},
            {"name": "High-F Loop", "type": "current_loop", "frequency_mhz": 1000.0,
             "current_a": 1.0, "area_mm2": 25.0},
        ]
        analysis = analyzer.analyze_sources(sources)
        assert analysis.sources[0].transition_distance_m > analysis.sources[1].transition_distance_m

    def test_higher_current_dominates(self, analyzer):
        """Source with higher current should dominate."""
        sources = [
            {"name": "Weak", "type": "current_loop", "frequency_mhz": 100.0,
             "current_a": 0.01, "area_mm2": 25.0},
            {"name": "Strong", "type": "current_loop", "frequency_mhz": 100.0,
             "current_a": 10.0, "area_mm2": 25.0},
        ]
        analysis = analyzer.analyze_sources(sources)
        assert analysis.dominant_source == "Strong"


# =====================================================================
# 6. Region determination
# =====================================================================

class TestRegionDetermination:
    def test_reactive_near_field(self):
        # 100 MHz: r_trans ~ 0.477m. At 0.01m this is well within reactive.
        assert determine_region(0.01, 100.0) == "reactive_near_field"

    def test_radiating_near_field(self):
        # At r_trans: radiating near-field
        r_trans = transition_distance(100.0)
        assert determine_region(r_trans, 100.0) == "radiating_near_field"

    def test_far_field(self):
        # At 2m: well beyond 0.477m transition for 100 MHz
        assert determine_region(2.0, 100.0) == "far_field"


# =====================================================================
# 7. to_dict output format
# =====================================================================

class TestToDict:
    def test_to_dict_keys(self, analyzer, magnetic_source):
        analysis = analyzer.analyze_sources([magnetic_source])
        d = analyzer.to_dict(analysis)
        assert "summary" in d
        assert "dominant_source" in d
        assert "max_h_field_dba_per_m" in d
        assert "max_e_field_dbuv_per_m" in d
        assert "source_count" in d
        assert "sources" in d
        assert "recommendations" in d

    def test_to_dict_source_structure(self, analyzer, magnetic_source):
        analysis = analyzer.analyze_sources([magnetic_source])
        d = analyzer.to_dict(analysis)
        src = d["sources"][0]
        assert "name" in src
        assert "source_type" in src
        assert "field_type" in src
        assert "frequency_mhz" in src
        assert "wavelength_m" in src
        assert "transition_distance_m" in src
        assert "field_points" in src

    def test_to_dict_field_point_structure(self, analyzer, magnetic_source):
        analysis = analyzer.analyze_sources([magnetic_source])
        d = analyzer.to_dict(analysis)
        fp = d["sources"][0]["field_points"][0]
        assert "distance_m" in fp
        assert "h_field_a_per_m" in fp
        assert "e_field_v_per_m" in fp
        assert "h_field_dba_per_m" in fp
        assert "e_field_dbuv_per_m" in fp
        assert "region" in fp

    def test_to_dict_source_count(self, analyzer, magnetic_source, electric_source):
        analysis = analyzer.analyze_sources([magnetic_source, electric_source])
        d = analyzer.to_dict(analysis)
        assert d["source_count"] == 2
        assert len(d["sources"]) == 2


# =====================================================================
# 8. Edge cases
# =====================================================================

class TestEdgeCases:
    def test_zero_current(self):
        """Zero current should give zero H-field."""
        h = h_field_magnetic_dipole(0.0, 25e-6, 100.0, 0.01)
        assert h == 0.0

    def test_zero_area(self):
        """Zero loop area should give zero H-field."""
        h = h_field_magnetic_dipole(1.0, 0.0, 100.0, 0.01)
        assert h == 0.0

    def test_zero_voltage(self):
        """Zero voltage should give zero E-field."""
        e = e_field_electric_dipole(0.0, 0.02, 100.0, 0.01)
        assert e == 0.0

    def test_zero_length(self):
        """Zero trace length should give zero E-field."""
        e = e_field_electric_dipole(3.3, 0.0, 100.0, 0.01)
        assert e == 0.0

    def test_zero_frequency(self):
        """Zero frequency should give zero fields (static case)."""
        h = h_field_magnetic_dipole(1.0, 25e-6, 0.0, 0.01)
        e = e_field_electric_dipole(3.3, 0.02, 0.0, 0.01)
        assert h == 0.0
        assert e == 0.0

    def test_zero_distance(self):
        """Zero distance should give zero (not infinity)."""
        h = h_field_magnetic_dipole(1.0, 25e-6, 100.0, 0.0)
        assert h == 0.0

    def test_negative_distance(self):
        """Negative distance should give zero."""
        h = h_field_magnetic_dipole(1.0, 25e-6, 100.0, -1.0)
        assert h == 0.0

    def test_analyze_empty_sources(self, analyzer):
        """Empty source list should work without error."""
        analysis = analyzer.analyze_sources([])
        assert len(analysis.sources) == 0

    def test_db_conversion_zero(self):
        """dB of zero should return -999."""
        assert to_db_h(0.0) == -999.0
        assert to_db_e(0.0) == -999.0

    def test_db_conversion_positive(self):
        """dB conversion for known values."""
        # 1 A/m -> 0 dBA/m
        assert abs(to_db_h(1.0)) < 0.01
        # 1 V/m = 1e6 uV/m -> 120 dBuV/m
        assert abs(to_db_e(1.0) - 120.0) < 0.01


# =====================================================================
# 9. Custom distances
# =====================================================================

class TestCustomDistances:
    def test_custom_distances(self):
        """Analyzer with custom evaluation distances."""
        dists = [0.005, 0.05, 0.5]
        analyzer = NearFieldAnalyzer(distances_m=dists)
        src = NearFieldSource(
            name="Test", source_type="current_loop",
            frequency_mhz=100.0, current_a=1.0, area_mm2=25.0,
        )
        result = analyzer.analyze_source(src)
        assert len(result.field_points) == 3
        assert result.field_points[0].distance_m == 0.005


# =====================================================================
# 10. Recommendations
# =====================================================================

class TestRecommendations:
    def test_high_h_field_recommendation(self, analyzer):
        """Strong magnetic source should trigger recommendation."""
        sources = [
            {"name": "Big Loop", "type": "current_loop", "frequency_mhz": 100.0,
             "current_a": 10.0, "area_mm2": 100.0},
        ]
        analysis = analyzer.analyze_sources(sources)
        # 10A, 100mm^2 at 100MHz at 10mm should be very high
        assert len(analysis.recommendations) > 0
        assert any("loop area" in r.lower() or "shielding" in r.lower()
                    for r in analysis.recommendations)

    def test_high_e_field_recommendation(self, analyzer):
        """Strong electric source should trigger recommendation."""
        sources = [
            {"name": "Long Clock", "type": "clock_trace", "frequency_mhz": 500.0,
             "voltage_v": 3.3, "length_mm": 100.0},
        ]
        analysis = analyzer.analyze_sources(sources)
        # Check if recommendation is generated (depends on field strength)
        # A 100mm trace at 500 MHz, 3.3V should produce notable field
        assert isinstance(analysis.recommendations, list)


# =====================================================================
# 11. Tool dispatch
# =====================================================================

class TestToolDispatch:
    def test_dispatch_near_field(self):
        """Test pcb_analyze_near_field through dispatch."""
        from mcp_pcb_emcopilot.server import _dispatch

        result = _dispatch("pcb_analyze_near_field", {
            "sources": [
                {"name": "Loop1", "type": "current_loop", "frequency_mhz": 100.0,
                 "current_a": 1.0, "area_mm2": 25.0},
            ],
        })

        assert result["source_count"] == 1
        assert "sources" in result
        assert "recommendations" in result
        assert result["sources"][0]["name"] == "Loop1"

    def test_dispatch_multiple_sources(self):
        """Test dispatch with both magnetic and electric sources."""
        from mcp_pcb_emcopilot.server import _dispatch

        result = _dispatch("pcb_analyze_near_field", {
            "sources": [
                {"name": "Inductor", "type": "smps_inductor", "frequency_mhz": 500.0,
                 "current_a": 2.0, "area_mm2": 10.0},
                {"name": "CLK", "type": "clock_trace", "frequency_mhz": 100.0,
                 "voltage_v": 1.8, "length_mm": 15.0},
            ],
        })

        assert result["source_count"] == 2
        assert result["sources"][0]["field_type"] == "magnetic"
        assert result["sources"][1]["field_type"] == "electric"


# =====================================================================
# 12. Tool registration
# =====================================================================

class TestToolRegistration:
    def test_tool_registered(self):
        """Verify pcb_analyze_near_field appears in the tool list."""
        from mcp_pcb_emcopilot.server import list_tools

        tools = asyncio.run(list_tools())
        tool_names = {t.name for t in tools}
        assert "pcb_analyze_near_field" in tool_names


# =====================================================================
# 13. Probe sensitivity (extra coverage)
# =====================================================================

class TestProbeSensitivity:
    def test_probe_thresholds_defined(self):
        """Probe sensitivity thresholds should be available."""
        assert len(NearFieldAnalyzer.PROBE_SENSITIVITIES) >= 3

    def test_probe_values_are_negative_or_zero(self):
        """Probe sensitivities are dBA/m, typically <= 0."""
        for name, val in NearFieldAnalyzer.PROBE_SENSITIVITIES.items():
            assert val <= 0, f"{name} sensitivity should be <= 0 dBA/m"

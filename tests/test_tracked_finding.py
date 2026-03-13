"""Tests for the TrackedFinding dataclass."""

from __future__ import annotations

import pytest

from mcp_pcb_emcopilot.reports.tracked_finding import TrackedFinding


class TestTrackedFindingCreation:
    """Tests for creating TrackedFinding instances."""

    def test_full_traceability_fields(self):
        """Finding with all traceability fields should serialize correctly."""
        f = TrackedFinding(
            finding_id="ANT-001",
            severity="WARNING",
            domain="antenna",
            title="Trace resonant at 2.4 GHz WiFi band",
            nets=["WiFi_2.4GHz"],
            layers=["L1"],
            components=["U12 (WiFi SoC)", "J8 (antenna connector)"],
            coordinates_mm=[(10.0, 20.0), (41.2, 20.0)],
            trace_length_mm=31.2,
            what_it_means="This trace acts as a quarter-wave antenna at 2.4 GHz.",
            how_calculated="f = c / (4 * L * sqrt(er_eff))",
            physical_mechanism="Quarter-wave monopole radiates and receives at WiFi frequency.",
            measured_value="31.2 mm routed length on L1 microstrip",
            limit_value="lambda/4 at 2.4 GHz = 31.25 mm",
            margin="-0.05 mm (resonant match)",
            recommendation="Route on inner layer L3 with continuous GND reference.",
            reference_standard="FCC Part 15.109",
        )
        d = f.to_dict()
        assert d["finding_id"] == "ANT-001"
        assert d["severity"] == "WARNING"
        assert d["nets"] == ["WiFi_2.4GHz"]
        assert d["layers"] == ["L1"]
        assert d["components"] == ["U12 (WiFi SoC)", "J8 (antenna connector)"]
        assert d["trace_length_mm"] == 31.2
        assert "quarter-wave" in d["what_it_means"]

    def test_optional_fields_default_to_none_or_empty(self):
        """Finding with only required fields should work."""
        f = TrackedFinding(
            finding_id="EMC-001",
            severity="CRITICAL",
            domain="emc",
            title="Clock EMI at 900 MHz",
            what_it_means="Clock harmonic exceeds emission limit.",
            how_calculated="Trapezoidal harmonic envelope.",
            physical_mechanism="Harmonic radiation from clock trace.",
            measured_value="63.2 dB above FCC Class B",
            limit_value="43.5 dBuV/m",
            margin="-63.2 dB",
            recommendation="Enable SSC or add pi-filter.",
            reference_standard="FCC Part 15",
        )
        assert f.nets == []
        assert f.layers == []
        assert f.components == []
        assert f.coordinates_mm == []
        assert f.trace_length_mm is None
        assert f.plot_path is None
        assert f.render_path is None

    def test_to_dict_roundtrip(self):
        """to_dict output should contain all fields."""
        f = TrackedFinding(
            finding_id="SI-001",
            severity="PASS",
            domain="signal_integrity",
            title="LPDDR4 eye meets spec",
            what_it_means="Eye opening is adequate.",
            how_calculated="Statistical eye analysis.",
            physical_mechanism="ISI and jitter reduce eye opening.",
            measured_value="738 mV height, 0.93 UI width",
            limit_value="> 200 mV, > 0.7 UI",
            margin="+538 mV, +0.23 UI",
            recommendation="",
            reference_standard="JEDEC JESD209-4",
            plot_path="/tmp/eye.png",
        )
        d = f.to_dict()
        assert set(d.keys()) == {
            "finding_id", "severity", "domain", "title",
            "nets", "layers", "components", "coordinates_mm",
            "trace_length_mm",
            "what_it_means", "how_calculated", "physical_mechanism",
            "measured_value", "limit_value", "margin",
            "recommendation", "reference_standard",
            "plot_path", "render_path",
        }


class TestTrackedFindingSeverity:
    """Tests for severity validation."""

    @pytest.mark.parametrize("severity", ["CRITICAL", "HIGH", "WARNING", "INFO", "PASS"])
    def test_valid_severities(self, severity):
        """All five severity levels should be accepted."""
        f = TrackedFinding(
            finding_id="TEST-001",
            severity=severity,
            domain="test",
            title="Test",
            what_it_means="x",
            how_calculated="x",
            physical_mechanism="x",
            measured_value="x",
            limit_value="x",
            margin="x",
            recommendation="x",
            reference_standard="x",
        )
        assert f.severity == severity

    def test_invalid_severity_raises(self):
        """Invalid severity string should raise ValueError."""
        with pytest.raises(ValueError, match="severity"):
            TrackedFinding(
                finding_id="TEST-001",
                severity="INVALID",
                domain="test",
                title="Test",
                what_it_means="x",
                how_calculated="x",
                physical_mechanism="x",
                measured_value="x",
                limit_value="x",
                margin="x",
                recommendation="x",
                reference_standard="x",
            )

    def test_severity_case_insensitive(self):
        """Severity should accept lowercase and normalize to uppercase."""
        f = TrackedFinding(
            finding_id="TEST-001",
            severity="critical",
            domain="test",
            title="Test",
            what_it_means="x",
            how_calculated="x",
            physical_mechanism="x",
            measured_value="x",
            limit_value="x",
            margin="x",
            recommendation="x",
            reference_standard="x",
        )
        assert f.severity == "CRITICAL"


class TestTrackedFindingId:
    """Tests for finding_id format."""

    def test_valid_id_format(self):
        """Finding ID should follow DOMAIN-NNN pattern."""
        f = TrackedFinding(
            finding_id="EMC-001",
            severity="HIGH",
            domain="emc",
            title="Test",
            what_it_means="x",
            how_calculated="x",
            physical_mechanism="x",
            measured_value="x",
            limit_value="x",
            margin="x",
            recommendation="x",
            reference_standard="x",
        )
        assert f.finding_id == "EMC-001"

    def test_invalid_id_format_raises(self):
        """Finding ID without dash-number should raise ValueError."""
        with pytest.raises(ValueError, match="finding_id"):
            TrackedFinding(
                finding_id="bad_id",
                severity="HIGH",
                domain="emc",
                title="Test",
                what_it_means="x",
                how_calculated="x",
                physical_mechanism="x",
                measured_value="x",
                limit_value="x",
                margin="x",
                recommendation="x",
                reference_standard="x",
            )

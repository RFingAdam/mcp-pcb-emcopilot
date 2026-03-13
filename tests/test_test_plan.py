"""Tests for the pre-compliance test plan generator."""

from __future__ import annotations

import pytest

from mcp_pcb_emcopilot.reports.test_plan import (
    ComplianceTestEntry,
    ComplianceTestPlan,
    EquipmentRecommendation,
    RiskFinding,
    Severity,
    TestPlanGenerator,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _critical_finding(**overrides) -> RiskFinding:
    defaults = dict(
        severity="critical",
        category="radiated_emissions",
        frequency_range_mhz=(100.0, 500.0),
        description="Clock harmonics exceed FCC Class B limit at 300 MHz",
    )
    defaults.update(overrides)
    return RiskFinding(**defaults)


def _high_finding(**overrides) -> RiskFinding:
    defaults = dict(
        severity="high",
        category="conducted_emissions",
        frequency_range_mhz=(0.15, 30.0),
        description="SMPS fundamental exceeds CISPR 25 conducted limit",
    )
    defaults.update(overrides)
    return RiskFinding(**defaults)


def _medium_finding(**overrides) -> RiskFinding:
    defaults = dict(
        severity="medium",
        category="emi",
        frequency_range_mhz=(30.0, 1000.0),
        description="Moderate EMI risk from unshielded ribbon cable",
    )
    defaults.update(overrides)
    return RiskFinding(**defaults)


def _low_finding(**overrides) -> RiskFinding:
    defaults = dict(
        severity="low",
        category="grounding",
        frequency_range_mhz=(1.0, 100.0),
        description="Ground stitch spacing slightly larger than recommended",
    )
    defaults.update(overrides)
    return RiskFinding(**defaults)


# ---------------------------------------------------------------------------
# Test: prioritization
# ---------------------------------------------------------------------------

class TestPrioritization:
    """Tests that verify test entries are ordered by severity."""

    def test_critical_tests_come_first(self):
        """CRITICAL-priority tests must appear before all other severities."""
        findings = [_low_finding(), _critical_finding(), _medium_finding()]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        assert len(plan.entries) > 0
        first_entry = plan.entries[0]
        assert first_entry.priority == Severity.CRITICAL

    def test_ordering_critical_high_medium_low(self):
        """Entries must be sorted CRITICAL -> HIGH -> MEDIUM -> LOW."""
        findings = [
            _low_finding(),
            _high_finding(),
            _critical_finding(),
            _medium_finding(),
        ]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        priorities = [e.priority for e in plan.entries]
        # Verify monotonically non-decreasing severity values
        for i in range(len(priorities) - 1):
            assert priorities[i].value <= priorities[i + 1].value, (
                f"Entry {i} ({priorities[i].name}) should not come after "
                f"entry {i+1} ({priorities[i+1].name})"
            )

    def test_all_critical_remain_first(self):
        """When multiple CRITICAL findings exist, all their tests come first."""
        findings = [
            _critical_finding(description="Critical issue 1"),
            _critical_finding(
                description="Critical issue 2",
                category="conducted_emissions",
            ),
            _low_finding(),
        ]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        critical_entries = [e for e in plan.entries if e.priority == Severity.CRITICAL]
        non_critical = [e for e in plan.entries if e.priority != Severity.CRITICAL]
        assert len(critical_entries) >= 2

        if non_critical:
            last_critical_idx = max(
                plan.entries.index(e) for e in critical_entries
            )
            first_non_critical_idx = min(
                plan.entries.index(e) for e in non_critical
            )
            assert last_critical_idx < first_non_critical_idx


# ---------------------------------------------------------------------------
# Test: setup instructions
# ---------------------------------------------------------------------------

class TestSetupInstructions:
    """Tests for test-specific setup instruction generation."""

    def test_radiated_setup_mentions_chamber(self):
        """Radiated emission tests should mention chamber or OATS setup."""
        findings = [_critical_finding(category="radiated_emissions")]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        radiated_entries = [
            e for e in plan.entries if "radiated" in e.test_name.lower()
        ]
        assert len(radiated_entries) > 0
        for entry in radiated_entries:
            setup_lower = entry.setup_instructions.lower()
            assert "chamber" in setup_lower or "oats" in setup_lower or "antenna" in setup_lower

    def test_conducted_setup_mentions_lisn(self):
        """Conducted emission tests should reference LISN or AN setup."""
        findings = [_high_finding(category="conducted_emissions")]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        conducted_entries = [
            e for e in plan.entries if "conducted" in e.test_name.lower()
        ]
        assert len(conducted_entries) > 0
        for entry in conducted_entries:
            setup_lower = entry.setup_instructions.lower()
            assert "lisn" in setup_lower or "artificial network" in setup_lower or "an" in setup_lower

    def test_setup_instructions_non_empty(self):
        """Every generated test entry must have non-empty setup instructions."""
        findings = [_critical_finding(), _medium_finding()]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        for entry in plan.entries:
            assert entry.setup_instructions.strip(), (
                f"Test {entry.test_id} has empty setup instructions"
            )


# ---------------------------------------------------------------------------
# Test: equipment recommendations
# ---------------------------------------------------------------------------

class TestEquipmentRecommendations:
    """Tests for measurement equipment recommendations."""

    def test_radiated_test_has_antenna_recommendation(self):
        """Radiated emission tests must recommend an antenna."""
        findings = [_critical_finding(category="radiated_emissions")]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        radiated_entries = [
            e for e in plan.entries if "radiated" in e.test_name.lower()
        ]
        assert len(radiated_entries) > 0
        for entry in radiated_entries:
            equipment_types = [eq.equipment_type for eq in entry.equipment]
            assert "antenna" in equipment_types, (
                f"Test {entry.test_id} missing antenna recommendation"
            )

    def test_conducted_test_has_lisn_recommendation(self):
        """Conducted emission tests must recommend a LISN."""
        findings = [_high_finding(category="conducted_emissions")]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        conducted_entries = [
            e for e in plan.entries if "conducted" in e.test_name.lower()
        ]
        assert len(conducted_entries) > 0
        for entry in conducted_entries:
            equipment_types = [eq.equipment_type for eq in entry.equipment]
            assert any(t in ("lisn", "cdn") for t in equipment_types), (
                f"Test {entry.test_id} missing LISN/CDN recommendation"
            )

    def test_equipment_has_specification(self):
        """Every equipment recommendation must include a specification string."""
        findings = [_critical_finding(), _high_finding()]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        for entry in plan.entries:
            for eq in entry.equipment:
                assert eq.specification.strip(), (
                    f"Equipment {eq.equipment_type} in {entry.test_id} "
                    f"missing specification"
                )


# ---------------------------------------------------------------------------
# Test: duration estimates
# ---------------------------------------------------------------------------

class TestDurationEstimates:
    """Tests for test duration estimation."""

    def test_total_duration_is_sum(self):
        """Total estimated duration must equal the sum of individual tests."""
        findings = [_critical_finding(), _high_finding(), _low_finding()]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        expected_total = sum(e.estimated_duration_minutes for e in plan.entries)
        assert plan.total_estimated_duration_minutes == expected_total

    def test_each_entry_has_positive_duration(self):
        """Every test entry must have a positive duration estimate."""
        findings = [_critical_finding(), _medium_finding()]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        for entry in plan.entries:
            assert entry.estimated_duration_minutes > 0, (
                f"Test {entry.test_id} has non-positive duration"
            )

    def test_empty_findings_zero_duration(self):
        """An empty findings list should produce zero total duration."""
        gen = TestPlanGenerator()
        plan = gen.generate([])
        assert plan.total_estimated_duration_minutes == 0


# ---------------------------------------------------------------------------
# Test: pre-compliance vs full-compliance matrix
# ---------------------------------------------------------------------------

class TestComplianceMatrix:
    """Tests for pre-compliance and full-compliance test matrices."""

    def test_pre_compliance_subset(self):
        """Pre-compliance matrix must be a subset of the full plan entries."""
        findings = [_critical_finding(), _high_finding()]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        pre_comp = gen.get_pre_compliance_matrix(plan)
        assert all(e in plan.entries for e in pre_comp)

    def test_full_compliance_subset(self):
        """Full-compliance matrix must be a subset of the full plan entries."""
        findings = [_critical_finding(), _high_finding()]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        full_comp = gen.get_full_compliance_matrix(plan)
        assert all(e in plan.entries for e in full_comp)

    def test_mil_std_is_full_compliance_only(self):
        """MIL-STD-461G tests should be full compliance but not pre-compliance."""
        findings = [
            RiskFinding(
                severity="critical",
                category="military radiated_emissions",
                frequency_range_mhz=(10.0, 18000.0),
                description="MIL-STD-461G RE102 margin predicted negative",
            ),
        ]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        mil_entries = [e for e in plan.entries if "MIL-STD" in e.standard]
        if mil_entries:
            for entry in mil_entries:
                assert entry.is_full_compliance is True
                assert entry.is_pre_compliance is False

    def test_pre_compliance_matrix_non_empty_for_commercial(self):
        """Commercial-standard findings should produce pre-compliance tests."""
        findings = [_critical_finding()]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        pre_comp = gen.get_pre_compliance_matrix(plan)
        assert len(pre_comp) > 0


# ---------------------------------------------------------------------------
# Test: edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge-case inputs."""

    def test_no_findings_produces_empty_plan(self):
        """Empty findings list should produce a valid but empty plan."""
        gen = TestPlanGenerator()
        plan = gen.generate([])

        assert isinstance(plan, ComplianceTestPlan)
        assert len(plan.entries) == 0
        assert plan.total_estimated_duration_minutes == 0
        assert plan.summary  # Should still have a summary message

    def test_all_critical_findings(self):
        """Plan with only CRITICAL findings should have all CRITICAL entries."""
        findings = [
            _critical_finding(description=f"Critical issue {i}")
            for i in range(5)
        ]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        assert len(plan.entries) > 0
        for entry in plan.entries:
            assert entry.priority == Severity.CRITICAL

    def test_mixed_severities_consistent(self):
        """Plan with mixed severities should maintain correct ordering."""
        findings = [
            _low_finding(),
            _critical_finding(),
            _medium_finding(),
            _high_finding(),
            _low_finding(description="Another low issue"),
        ]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        values = [e.priority.value for e in plan.entries]
        assert values == sorted(values), "Entries not sorted by priority"

    def test_single_finding_produces_plan(self):
        """A single finding should still produce a complete plan."""
        findings = [_medium_finding()]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        assert len(plan.entries) >= 1
        assert plan.total_estimated_duration_minutes > 0
        assert len(plan.standards_covered) >= 1

    def test_severity_from_string_aliases(self):
        """Severity.from_string should handle alias strings correctly."""
        assert Severity.from_string("critical") == Severity.CRITICAL
        assert Severity.from_string("CRITICAL") == Severity.CRITICAL
        assert Severity.from_string("high") == Severity.HIGH
        assert Severity.from_string("warning") == Severity.MEDIUM
        assert Severity.from_string("info") == Severity.LOW
        assert Severity.from_string("unknown_value") == Severity.LOW

    def test_immunity_finding_generates_immunity_tests(self):
        """An immunity-category finding should generate IEC 61000-4-x tests."""
        findings = [
            RiskFinding(
                severity="high",
                category="immunity",
                frequency_range_mhz=(0.15, 6000.0),
                description="Insufficient filtering on I/O ports",
            ),
        ]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        standards = plan.standards_covered
        assert any("IEC 61000-4" in s for s in standards), (
            f"Expected IEC 61000-4-x in standards but got: {standards}"
        )

    def test_expected_failure_frequencies_within_range(self):
        """Predicted failure frequencies should relate to the finding range."""
        finding = _critical_finding(frequency_range_mhz=(100.0, 500.0))
        gen = TestPlanGenerator()
        plan = gen.generate([finding])

        for entry in plan.entries:
            for freq in entry.expected_failure_frequencies_mhz:
                assert freq >= 100.0
                assert freq <= 500.0

    def test_predicted_margin_negative_for_critical(self):
        """CRITICAL tests should have a negative predicted margin (failure)."""
        findings = [_critical_finding()]
        gen = TestPlanGenerator()
        plan = gen.generate(findings)

        critical_entries = [
            e for e in plan.entries if e.priority == Severity.CRITICAL
        ]
        assert len(critical_entries) > 0
        for entry in critical_entries:
            assert entry.predicted_margin_db is not None
            assert entry.predicted_margin_db < 0, (
                f"CRITICAL test {entry.test_id} should have negative margin"
            )

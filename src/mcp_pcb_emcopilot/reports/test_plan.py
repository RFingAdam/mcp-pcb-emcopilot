"""Pre-compliance test plan generator for PCB design reviews.

Takes risk findings from design review analysis and generates a prioritized
test plan with setup instructions, equipment recommendations, duration
estimates, and a pre-compliance vs full-compliance test matrix.

Standards covered: FCC Part 15, CISPR 32, CISPR 25, MIL-STD-461G,
IEC 61000-4-3, IEC 61000-4-6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# =============================================================================
# Severity enumeration
# =============================================================================

class Severity(Enum):
    """Risk severity levels, ordered from most to least severe."""

    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3

    @classmethod
    def from_string(cls, value: str) -> Severity:
        """Parse a severity string (case-insensitive) into a Severity enum.

        Accepts aliases: ``"warning"`` maps to MEDIUM, ``"info"`` maps to LOW.
        """
        mapping: dict[str, Severity] = {
            "critical": cls.CRITICAL,
            "high": cls.HIGH,
            "medium": cls.MEDIUM,
            "warning": cls.MEDIUM,
            "low": cls.LOW,
            "info": cls.LOW,
        }
        return mapping.get(value.strip().lower(), cls.LOW)


# =============================================================================
# Input data structure
# =============================================================================

@dataclass
class RiskFinding:
    """A single risk finding from a design review analysis.

    Parameters
    ----------
    severity : str
        One of ``"critical"``, ``"high"``, ``"medium"``/``"warning"``,
        ``"low"``/``"info"``.
    category : str
        Analysis domain (e.g. ``"radiated_emissions"``,
        ``"conducted_emissions"``, ``"immunity"``, ``"esd"``).
    frequency_range_mhz : tuple[float, float]
        Frequency range of concern as ``(low, high)`` in MHz.
    description : str
        Human-readable description of the finding.
    """

    severity: str
    category: str
    frequency_range_mhz: tuple[float, float]
    description: str


# =============================================================================
# Output data structures
# =============================================================================

@dataclass
class EquipmentRecommendation:
    """Recommended measurement equipment for a test.

    Parameters
    ----------
    equipment_type : str
        Category of equipment (e.g. ``"spectrum_analyzer"``, ``"antenna"``,
        ``"lisn"``).
    model_suggestion : str
        Suggested model or specification.
    specification : str
        Key specification detail (e.g. bandwidth, gain, impedance).
    """

    equipment_type: str
    model_suggestion: str
    specification: str


@dataclass
class ComplianceTestEntry:
    """A single test in the test plan.

    Parameters
    ----------
    test_id : str
        Unique identifier for the test (e.g. ``"RE-001"``).
    standard : str
        Applicable standard (e.g. ``"FCC Part 15 Class B"``).
    test_name : str
        Descriptive test name.
    priority : Severity
        Priority derived from associated risk severity.
    setup_instructions : str
        Detailed test setup description.
    frequency_range_mhz : tuple[float, float]
        Frequency range for this test.
    expected_failure_frequencies_mhz : list[float]
        Predicted frequencies where failures may occur.
    predicted_margin_db : float | None
        Predicted margin to limit (positive = pass, negative = fail).
    equipment : list[EquipmentRecommendation]
        Recommended equipment for this test.
    estimated_duration_minutes : int
        Estimated test duration in minutes.
    risk_description : str
        Description of the risk that triggered this test.
    is_pre_compliance : bool
        Whether this test is suitable for pre-compliance testing.
    is_full_compliance : bool
        Whether this test is required for full compliance testing.
    """

    test_id: str
    standard: str
    test_name: str
    priority: Severity
    setup_instructions: str
    frequency_range_mhz: tuple[float, float]
    expected_failure_frequencies_mhz: list[float] = field(default_factory=list)
    predicted_margin_db: Optional[float] = None
    equipment: list[EquipmentRecommendation] = field(default_factory=list)
    estimated_duration_minutes: int = 60
    risk_description: str = ""
    is_pre_compliance: bool = True
    is_full_compliance: bool = True


@dataclass
class ComplianceTestPlan:
    """A complete pre-compliance test plan.

    Parameters
    ----------
    entries : list[ComplianceTestEntry]
        Ordered list of test entries (CRITICAL first).
    total_estimated_duration_minutes : int
        Sum of all test durations.
    standards_covered : list[str]
        List of standards addressed.
    summary : str
        Executive summary of the test plan.
    """

    entries: list[ComplianceTestEntry] = field(default_factory=list)
    total_estimated_duration_minutes: int = 0
    standards_covered: list[str] = field(default_factory=list)
    summary: str = ""


# =============================================================================
# Standards database
# =============================================================================

# Maps (category keyword, standard) -> setup / equipment / duration metadata
_STANDARD_PROFILES: dict[str, dict] = {
    "FCC Part 15 Class B": {
        "radiated": {
            "test_name": "Radiated Emissions (FCC Part 15 Class B)",
            "frequency_range_mhz": (30.0, 1000.0),
            "setup": (
                "3 m semi-anechoic chamber (SAC) or OATS. "
                "EUT on 80 cm non-conductive table. "
                "Turntable rotation 0-360 deg, antenna height scan 1-4 m. "
                "Horizontal and vertical polarization."
            ),
            "equipment": [
                EquipmentRecommendation(
                    "spectrum_analyzer",
                    "Keysight N9048B PXE or R&S FSW",
                    "RBW 120 kHz (CISPR quasi-peak), frequency range 30 MHz - 1 GHz",
                ),
                EquipmentRecommendation(
                    "antenna",
                    "Biconical 30-300 MHz + Log-periodic 200 MHz - 1 GHz",
                    "Calibrated antenna factor per ANSI C63.5",
                ),
            ],
            "duration_minutes": 120,
            "is_pre_compliance": True,
            "is_full_compliance": True,
        },
        "conducted": {
            "test_name": "Conducted Emissions (FCC Part 15 Class B)",
            "frequency_range_mhz": (0.15, 30.0),
            "setup": (
                "LISN on AC mains input per CISPR 16-1-2. "
                "EUT 40 cm from ground plane, 80 cm from vertical plane. "
                "Measure line and neutral separately."
            ),
            "equipment": [
                EquipmentRecommendation(
                    "spectrum_analyzer",
                    "Keysight N9048B PXE or R&S ESR",
                    "RBW 9 kHz (CISPR Band B), quasi-peak and average detectors",
                ),
                EquipmentRecommendation(
                    "lisn",
                    "Schwarzbeck NSLK 8127 or Rohde & Schwarz ENV216",
                    "50 uH / 50 Ohm LISN per CISPR 16-1-2",
                ),
            ],
            "duration_minutes": 60,
            "is_pre_compliance": True,
            "is_full_compliance": True,
        },
    },
    "CISPR 32 Class B": {
        "radiated": {
            "test_name": "Radiated Emissions (CISPR 32 Class B)",
            "frequency_range_mhz": (30.0, 6000.0),
            "setup": (
                "3 m or 10 m semi-anechoic chamber. "
                "EUT on 80 cm table, turntable rotation, antenna height scan 1-4 m. "
                "Above 1 GHz: fixed antenna height, EUT rotation only."
            ),
            "equipment": [
                EquipmentRecommendation(
                    "spectrum_analyzer",
                    "R&S ESW or Keysight N9048B PXE",
                    "RBW 120 kHz (30-1000 MHz), 1 MHz (1-6 GHz), peak and quasi-peak",
                ),
                EquipmentRecommendation(
                    "antenna",
                    "Biconical + Log-periodic + Horn (1-6 GHz)",
                    "Calibrated set covering 30 MHz - 6 GHz",
                ),
            ],
            "duration_minutes": 180,
            "is_pre_compliance": True,
            "is_full_compliance": True,
        },
        "conducted": {
            "test_name": "Conducted Emissions (CISPR 32 Class B)",
            "frequency_range_mhz": (0.15, 30.0),
            "setup": (
                "LISN per CISPR 16-1-2 on AC mains. "
                "EUT on 80 cm non-conductive table, ground plane reference. "
                "Quasi-peak and average measurements."
            ),
            "equipment": [
                EquipmentRecommendation(
                    "spectrum_analyzer",
                    "R&S ESW or Keysight N9048B",
                    "RBW 9 kHz (CISPR Band B), quasi-peak and average detectors",
                ),
                EquipmentRecommendation(
                    "lisn",
                    "Schwarzbeck NSLK 8127",
                    "50 uH / 50 Ohm V-network per CISPR 16-1-2",
                ),
            ],
            "duration_minutes": 60,
            "is_pre_compliance": True,
            "is_full_compliance": True,
        },
    },
    "CISPR 25": {
        "radiated": {
            "test_name": "Radiated Emissions (CISPR 25 Automotive)",
            "frequency_range_mhz": (150.0, 2500.0),
            "setup": (
                "Shielded room with absorber-lined walls (ALSE). "
                "Wire harness on 50 mm support, 1 m monopole or biconical antenna "
                "at specified distance. Use AN per CISPR 25 Annex A."
            ),
            "equipment": [
                EquipmentRecommendation(
                    "spectrum_analyzer",
                    "R&S ESR or Keysight N9048B",
                    "RBW 120 kHz / 1 MHz, peak and quasi-peak detectors",
                ),
                EquipmentRecommendation(
                    "antenna",
                    "Monopole + Biconical + Log-periodic + Horn",
                    "Calibrated antenna set for 150 kHz - 2.5 GHz per CISPR 25",
                ),
            ],
            "duration_minutes": 150,
            "is_pre_compliance": True,
            "is_full_compliance": True,
        },
        "conducted": {
            "test_name": "Conducted Emissions (CISPR 25 Automotive)",
            "frequency_range_mhz": (0.15, 108.0),
            "setup": (
                "AN (Artificial Network) per CISPR 25 on 12V/24V harness. "
                "EUT on ground plane, harness 50 mm above plane, "
                "AN 200 mm from EUT connector."
            ),
            "equipment": [
                EquipmentRecommendation(
                    "spectrum_analyzer",
                    "R&S ESR or Keysight N9048B",
                    "RBW 9 kHz / 120 kHz, peak and average detectors",
                ),
                EquipmentRecommendation(
                    "lisn",
                    "Schwarzbeck NNHV 8123 or equivalent AN",
                    "5 uH Artificial Network per CISPR 25",
                ),
            ],
            "duration_minutes": 90,
            "is_pre_compliance": True,
            "is_full_compliance": True,
        },
    },
    "MIL-STD-461G": {
        "radiated": {
            "test_name": "RE102 Radiated Emissions (MIL-STD-461G)",
            "frequency_range_mhz": (10.0, 18000.0),
            "setup": (
                "Shielded enclosure per MIL-STD-461G. "
                "EUT on non-conductive table 1 m from antenna. "
                "Rod antenna (10 kHz - 30 MHz), biconical (30-200 MHz), "
                "double-ridged horn (200 MHz - 18 GHz)."
            ),
            "equipment": [
                EquipmentRecommendation(
                    "spectrum_analyzer",
                    "R&S ESW26 or Keysight N9048B",
                    "RBW per MIL-STD-461G Table II, peak detector, 10 kHz - 18 GHz",
                ),
                EquipmentRecommendation(
                    "antenna",
                    "Rod + Biconical + Double-ridged horn",
                    "Calibrated antennas 10 kHz - 18 GHz per MIL-STD-461G",
                ),
            ],
            "duration_minutes": 240,
            "is_pre_compliance": False,
            "is_full_compliance": True,
        },
        "conducted": {
            "test_name": "CE102 Conducted Emissions (MIL-STD-461G)",
            "frequency_range_mhz": (0.01, 10.0),
            "setup": (
                "LISN per MIL-STD-461G on each power input. "
                "EUT on ground plane in shielded room. "
                "10 kHz - 10 MHz, peak detector."
            ),
            "equipment": [
                EquipmentRecommendation(
                    "spectrum_analyzer",
                    "R&S ESW or Keysight N9048B",
                    "RBW per MIL-STD-461G, peak detector, 10 kHz - 10 MHz",
                ),
                EquipmentRecommendation(
                    "lisn",
                    "Solar 9144-1 or equivalent",
                    "10 uH LISN per MIL-STD-461G, CI-type",
                ),
            ],
            "duration_minutes": 90,
            "is_pre_compliance": False,
            "is_full_compliance": True,
        },
    },
    "IEC 61000-4-3": {
        "immunity": {
            "test_name": "Radiated Immunity (IEC 61000-4-3)",
            "frequency_range_mhz": (80.0, 6000.0),
            "setup": (
                "Fully anechoic chamber or SAC. "
                "Field strength calibration with field probes. "
                "1% AM modulation at 1 kHz. "
                "EUT monitored for performance degradation."
            ),
            "equipment": [
                EquipmentRecommendation(
                    "rf_amplifier",
                    "AR 100W1000M or equivalent",
                    "100 W broadband amplifier, 80 MHz - 6 GHz (may need multiple)",
                ),
                EquipmentRecommendation(
                    "antenna",
                    "Biconical + Log-periodic + Horn for TX",
                    "Transmit antennas 80 MHz - 6 GHz, field probe for calibration",
                ),
                EquipmentRecommendation(
                    "signal_generator",
                    "Keysight N5182B or R&S SMW200A",
                    "Signal generator with AM modulation, 80 MHz - 6 GHz",
                ),
            ],
            "duration_minutes": 240,
            "is_pre_compliance": True,
            "is_full_compliance": True,
        },
    },
    "IEC 61000-4-6": {
        "immunity": {
            "test_name": "Conducted Immunity (IEC 61000-4-6)",
            "frequency_range_mhz": (0.15, 80.0),
            "setup": (
                "Coupling/decoupling network (CDN) on signal and power ports. "
                "EM clamp for ports without CDN. "
                "1% AM modulation at 1 kHz. "
                "150 kHz - 80 MHz sweep, monitor EUT performance."
            ),
            "equipment": [
                EquipmentRecommendation(
                    "rf_amplifier",
                    "AR 25A250A or equivalent",
                    "25 W amplifier, 150 kHz - 80 MHz",
                ),
                EquipmentRecommendation(
                    "cdn",
                    "Schwarzbeck CDN-M series or Teseq CDN",
                    "CDN for power lines, signal lines; EM clamp for unterminated",
                ),
                EquipmentRecommendation(
                    "signal_generator",
                    "Keysight N5182B or R&S SMW200A",
                    "Signal generator with AM modulation, 150 kHz - 80 MHz",
                ),
            ],
            "duration_minutes": 180,
            "is_pre_compliance": True,
            "is_full_compliance": True,
        },
    },
}


# Maps risk categories to relevant test types
_CATEGORY_TO_TEST_TYPES: dict[str, list[str]] = {
    "radiated_emissions": ["radiated"],
    "conducted_emissions": ["conducted"],
    "immunity": ["immunity"],
    "esd": ["immunity"],
    "emi": ["radiated", "conducted"],
    "clock_emi": ["radiated"],
    "smps_emi": ["conducted", "radiated"],
    "signal_integrity": ["radiated"],
    "crosstalk": ["radiated"],
    "common_mode": ["radiated", "conducted"],
    "pdn": ["conducted"],
    "power_integrity": ["conducted"],
    "grounding": ["radiated", "conducted"],
    "return_path": ["radiated"],
    "shielding": ["radiated", "immunity"],
    "slot_antenna": ["radiated"],
    "trace_antenna": ["radiated"],
    "cable_coupling": ["radiated", "conducted"],
    "differential_pair": ["radiated"],
}


# Default standards to apply when the category doesn't narrow it down
_DEFAULT_STANDARDS = ["FCC Part 15 Class B", "CISPR 32 Class B"]


def _select_standards_for_finding(finding: RiskFinding) -> list[str]:
    """Determine which standards are relevant based on the finding category
    and frequency range."""
    standards: list[str] = []

    cat = finding.category.lower().replace(" ", "_")
    freq_low, freq_high = finding.frequency_range_mhz

    # Automotive categories -> CISPR 25
    if "automotive" in cat or "vehicle" in cat:
        standards.append("CISPR 25")

    # Military categories -> MIL-STD-461G
    if "military" in cat or "mil" in cat or "defense" in cat:
        standards.append("MIL-STD-461G")

    # Immunity-related categories
    if cat in ("immunity", "esd", "shielding"):
        if freq_high > 80.0:
            standards.append("IEC 61000-4-3")
        if freq_low < 80.0:
            standards.append("IEC 61000-4-6")

    # Emissions categories -> commercial standards
    test_types = _CATEGORY_TO_TEST_TYPES.get(cat, ["radiated", "conducted"])
    if "radiated" in test_types or "conducted" in test_types:
        if not standards:
            standards.extend(_DEFAULT_STANDARDS)

    # Ensure we always have at least one standard
    if not standards:
        standards.extend(_DEFAULT_STANDARDS)

    return list(dict.fromkeys(standards))  # deduplicate preserving order


def _estimate_failure_frequencies(
    finding: RiskFinding,
) -> list[float]:
    """Estimate likely failure frequencies from the finding's frequency range.

    Returns up to 3 representative frequencies: the band edges and midpoint.
    """
    low, high = finding.frequency_range_mhz
    if low <= 0:
        low = 0.15
    if high <= low:
        return [low]
    mid = (low + high) / 2.0
    frequencies = [low, mid, high]
    return sorted(set(round(f, 2) for f in frequencies))


def _estimate_margin(severity: Severity) -> float | None:
    """Predict margin to limit based on severity."""
    margin_map: dict[Severity, float] = {
        Severity.CRITICAL: -12.0,
        Severity.HIGH: -6.0,
        Severity.MEDIUM: 3.0,
        Severity.LOW: 10.0,
    }
    return margin_map.get(severity)


def _duration_for_standard(standard: str, test_type: str) -> int:
    """Look up estimated duration in minutes for a standard/test-type combo."""
    profile = _STANDARD_PROFILES.get(standard, {})
    test_profile = profile.get(test_type, {})
    return int(test_profile.get("duration_minutes", 60))


# =============================================================================
# Generator
# =============================================================================

class TestPlanGenerator:
    """Generates a pre-compliance test plan from design review risk findings.

    Usage::

        findings = [
            RiskFinding(
                severity="critical",
                category="radiated_emissions",
                frequency_range_mhz=(100.0, 500.0),
                description="Clock harmonics exceed FCC Class B at 300 MHz",
            ),
        ]
        generator = TestPlanGenerator()
        plan = generator.generate(findings)
        for entry in plan.entries:
            print(entry.test_id, entry.standard, entry.priority)
    """

    def generate(self, findings: list[RiskFinding]) -> ComplianceTestPlan:
        """Generate a complete test plan from risk findings.

        Parameters
        ----------
        findings : list[RiskFinding]
            Design review risk findings to generate tests for.

        Returns
        -------
        ComplianceTestPlan
            Prioritized test plan with setup instructions, equipment
            recommendations, and duration estimates.
        """
        if not findings:
            return ComplianceTestPlan(
                entries=[],
                total_estimated_duration_minutes=0,
                standards_covered=[],
                summary="No risk findings provided. No tests required.",
            )

        entries: list[ComplianceTestEntry] = []
        test_counter = 0
        standards_seen: set[str] = set()

        for finding in findings:
            severity = Severity.from_string(finding.severity)
            standards = _select_standards_for_finding(finding)
            cat = finding.category.lower().replace(" ", "_")
            test_types = _CATEGORY_TO_TEST_TYPES.get(cat, ["radiated", "conducted"])

            for standard in standards:
                std_profile = _STANDARD_PROFILES.get(standard, {})

                for test_type in test_types:
                    profile = std_profile.get(test_type)
                    if profile is None:
                        continue

                    test_counter += 1
                    test_id = f"T-{test_counter:03d}"

                    # Merge frequency ranges: use tighter of finding vs standard
                    std_freq = profile.get("frequency_range_mhz", finding.frequency_range_mhz)
                    merged_low = max(finding.frequency_range_mhz[0], std_freq[0])
                    merged_high = min(finding.frequency_range_mhz[1], std_freq[1])
                    if merged_low > merged_high:
                        # No overlap -- use the standard's full range
                        merged_low, merged_high = std_freq

                    entry = ComplianceTestEntry(
                        test_id=test_id,
                        standard=standard,
                        test_name=profile.get("test_name", f"{test_type} test"),
                        priority=severity,
                        setup_instructions=profile.get("setup", ""),
                        frequency_range_mhz=(merged_low, merged_high),
                        expected_failure_frequencies_mhz=_estimate_failure_frequencies(finding),
                        predicted_margin_db=_estimate_margin(severity),
                        equipment=list(profile.get("equipment", [])),
                        estimated_duration_minutes=profile.get("duration_minutes", 60),
                        risk_description=finding.description,
                        is_pre_compliance=profile.get("is_pre_compliance", True),
                        is_full_compliance=profile.get("is_full_compliance", True),
                    )
                    entries.append(entry)
                    standards_seen.add(standard)

        # Sort by priority (CRITICAL=0 first)
        entries.sort(key=lambda e: e.priority.value)

        total_duration = sum(e.estimated_duration_minutes for e in entries)
        standards_list = sorted(standards_seen)

        # Build summary
        severity_counts: dict[str, int] = {}
        for entry in entries:
            name = entry.priority.name
            severity_counts[name] = severity_counts.get(name, 0) + 1

        summary_parts = [
            f"Test plan with {len(entries)} tests across "
            f"{len(standards_list)} standards.",
        ]
        for sev_name in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            count = severity_counts.get(sev_name, 0)
            if count > 0:
                summary_parts.append(f"{count} {sev_name} priority.")
        summary_parts.append(
            f"Estimated total duration: {total_duration} minutes "
            f"({total_duration / 60:.1f} hours)."
        )

        return ComplianceTestPlan(
            entries=entries,
            total_estimated_duration_minutes=total_duration,
            standards_covered=standards_list,
            summary=" ".join(summary_parts),
        )

    def get_pre_compliance_matrix(self, plan: ComplianceTestPlan) -> list[ComplianceTestEntry]:
        """Return only tests suitable for pre-compliance testing."""
        return [e for e in plan.entries if e.is_pre_compliance]

    def get_full_compliance_matrix(self, plan: ComplianceTestPlan) -> list[ComplianceTestEntry]:
        """Return only tests required for full compliance testing."""
        return [e for e in plan.entries if e.is_full_compliance]

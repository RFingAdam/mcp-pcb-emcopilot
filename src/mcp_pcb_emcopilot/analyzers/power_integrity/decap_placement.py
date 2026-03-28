"""
Decoupling Capacitor Placement Analyzer.

Analyzes and recommends decoupling capacitor placement:
- Proximity to IC power pins
- Via inductance impact
- Effective frequency range
- Capacitor value selection
- Optimal placement locations
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DecapIssueType(str, Enum):
    """Types of decoupling issues."""
    TOO_FAR_FROM_PIN = "too_far_from_pin"
    HIGH_VIA_INDUCTANCE = "high_via_inductance"
    MISSING_VALUE = "missing_value"
    WRONG_ORIENTATION = "wrong_orientation"
    INSUFFICIENT_COUNT = "insufficient_count"
    FREQUENCY_GAP = "frequency_gap"


@dataclass
class DecapRecommendation:
    """Recommendation for a decoupling capacitor."""
    capacitance_uf: float
    target_frequency_hz: float
    count: int
    package_size: str  # 0402, 0603, 0805, etc.
    max_distance_mm: float
    priority: str  # critical, high, medium, low
    reason: str

    def to_dict(self) -> dict:
        return {
            "capacitance_uf": self.capacitance_uf,
            "target_frequency_hz": self.target_frequency_hz,
            "count": self.count,
            "package_size": self.package_size,
            "max_distance_mm": round(self.max_distance_mm, 2),
            "priority": self.priority,
            "reason": self.reason,
        }


@dataclass
class DecapIssue:
    """A decoupling-related issue."""
    issue_type: DecapIssueType
    severity: str
    description: str
    component_ref: Optional[str] = None
    current_distance_mm: Optional[float] = None
    recommended_distance_mm: Optional[float] = None
    recommendation: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "issue_type": self.issue_type.value,
            "severity": self.severity,
            "description": self.description,
            "component_ref": self.component_ref,
            "current_distance_mm": round(self.current_distance_mm, 2) if self.current_distance_mm else None,
            "recommended_distance_mm": round(self.recommended_distance_mm, 2) if self.recommended_distance_mm else None,
            "recommendation": self.recommendation,
        }


@dataclass
class DecapAnalysis:
    """Analysis of a single decoupling capacitor."""
    component_ref: str
    capacitance_uf: float
    package_size: str
    distance_to_ic_mm: float
    via_count: int
    estimated_esl_nh: float
    self_resonant_freq_hz: float
    effective_freq_range: tuple[float, float]
    is_optimally_placed: bool
    issues: list[DecapIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "component_ref": self.component_ref,
            "capacitance_uf": self.capacitance_uf,
            "package_size": self.package_size,
            "distance_to_ic_mm": round(self.distance_to_ic_mm, 2),
            "via_count": self.via_count,
            "estimated_esl_nh": round(self.estimated_esl_nh, 3),
            "self_resonant_freq_hz": self.self_resonant_freq_hz,
            "effective_freq_range": self.effective_freq_range,
            "is_optimally_placed": self.is_optimally_placed,
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass
class DecapResult:
    """Result of decoupling capacitor analysis."""
    target_ic_ref: str
    power_rail: str

    # Analyzed capacitors
    analyzed_decaps: list[DecapAnalysis] = field(default_factory=list)

    # Coverage analysis
    frequency_coverage: list[tuple[float, float]] = field(default_factory=list)
    frequency_gaps: list[tuple[float, float]] = field(default_factory=list)

    # Recommendations
    recommendations: list[DecapRecommendation] = field(default_factory=list)

    # Issues
    issues: list[DecapIssue] = field(default_factory=list)

    # Score
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "target_ic_ref": self.target_ic_ref,
            "power_rail": self.power_rail,
            "analyzed_decaps": [d.to_dict() for d in self.analyzed_decaps],
            "frequency_coverage": self.frequency_coverage,
            "frequency_gaps": self.frequency_gaps,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "issues": [i.to_dict() for i in self.issues],
            "score": round(self.score, 1),
        }


# Standard capacitor ESL values by package (nH)
PACKAGE_ESL = {
    "0201": 0.2,
    "0402": 0.4,
    "0603": 0.6,
    "0805": 0.8,
    "1206": 1.0,
    "1210": 1.2,
}

# Standard capacitor ESR values by value range (mΩ)
VALUE_ESR = {
    "100pf": 50,
    "1nf": 30,
    "10nf": 20,
    "100nf": 10,
    "1uf": 10,
    "10uf": 5,
    "100uf": 3,
}

# Maximum recommended distance from IC by package (mm)
MAX_DISTANCE = {
    "0201": 1.0,
    "0402": 2.0,
    "0603": 3.0,
    "0805": 5.0,
    "1206": 8.0,
    "1210": 10.0,
}


class DecapAnalyzer:
    """
    Decoupling capacitor placement analyzer.

    Analyzes the effectiveness of decoupling capacitors based on:
    - Distance from IC power pins
    - Via inductance in connection
    - Self-resonant frequency
    - Frequency coverage of the network

    Usage:
        analyzer = DecapAnalyzer()
        result = analyzer.analyze_ic_decoupling(
            ic_ref="U1",
            ic_position=(50.0, 50.0),
            power_rail="VCC",
            target_frequency_hz=100e6,
            decaps=[
                {
                    "ref": "C1",
                    "capacitance_uf": 0.1,
                    "package": "0402",
                    "position": (48.0, 50.0),
                    "via_count": 2,
                },
            ],
        )
    """

    # Via inductance per via (nH)
    VIA_INDUCTANCE_NH = 0.5

    def __init__(
        self,
        default_esr_mohm: float = 10.0,
        via_inductance_nh: float = 0.5,
    ):
        """
        Initialize analyzer.

        Args:
            default_esr_mohm: Default ESR if not specified
            via_inductance_nh: Inductance per via
        """
        self.default_esr = default_esr_mohm * 1e-3
        self.via_inductance = via_inductance_nh

    def calculate_self_resonant_frequency(
        self,
        capacitance_f: float,
        esl_h: float,
    ) -> float:
        """
        Calculate self-resonant frequency of capacitor.

        f_sr = 1 / (2π√(LC))

        Args:
            capacitance_f: Capacitance in Farads
            esl_h: ESL in Henries

        Returns:
            Self-resonant frequency in Hz
        """
        if capacitance_f <= 0 or esl_h <= 0:
            return 0.0
        return 1 / (2 * math.pi * math.sqrt(esl_h * capacitance_f))

    def calculate_effective_frequency_range(
        self,
        srf_hz: float,
        q_factor: float = 10.0,
    ) -> tuple[float, float]:
        """
        Calculate effective frequency range around SRF.

        The capacitor is effective from about SRF/Q to SRF*Q.

        Args:
            srf_hz: Self-resonant frequency
            q_factor: Quality factor

        Returns:
            Tuple of (lower_freq, upper_freq)
        """
        lower = srf_hz / q_factor
        upper = srf_hz * q_factor
        return (lower, upper)

    def estimate_esl(
        self,
        package_size: str,
        via_count: int,
        trace_length_mm: float = 1.0,
    ) -> float:
        """
        Estimate total ESL including package, vias, and traces.

        Args:
            package_size: Package size (0402, 0603, etc.)
            via_count: Number of vias in path
            trace_length_mm: Trace length to IC

        Returns:
            Total ESL in nH
        """
        # Package ESL
        pkg_esl = PACKAGE_ESL.get(package_size, 0.6)

        # Via ESL
        via_esl = via_count * self.via_inductance

        # Trace ESL for microstrip over ground plane (~0.02 nH/mm)
        # Source: IPC-2141A, Wadell "Transmission Line Design Handbook"
        # (isolated wire in free space would be ~1 nH/mm; microstrip is much lower)
        trace_esl = trace_length_mm * 0.02

        return pkg_esl + via_esl + trace_esl

    def analyze_single_decap(
        self,
        component_ref: str,
        capacitance_uf: float,
        package_size: str,
        position: tuple[float, float],
        ic_position: tuple[float, float],
        via_count: int = 2,
        esr_mohm: Optional[float] = None,
    ) -> DecapAnalysis:
        """
        Analyze a single decoupling capacitor.

        Args:
            component_ref: Component reference designator
            capacitance_uf: Capacitance in µF
            package_size: Package size
            position: Decap position (x, y) in mm
            ic_position: IC position (x, y) in mm
            via_count: Number of vias
            esr_mohm: ESR in milliohms

        Returns:
            DecapAnalysis result
        """
        # Calculate distance
        dx = position[0] - ic_position[0]
        dy = position[1] - ic_position[1]
        distance = math.sqrt(dx * dx + dy * dy)

        # Estimate ESL
        esl_nh = self.estimate_esl(package_size, via_count, distance)

        # Calculate SRF
        capacitance_f = capacitance_uf * 1e-6
        esl_h = esl_nh * 1e-9
        srf = self.calculate_self_resonant_frequency(capacitance_f, esl_h)

        # Calculate effective frequency range
        freq_range = self.calculate_effective_frequency_range(srf)

        # Check if optimally placed
        max_dist = MAX_DISTANCE.get(package_size, 5.0)
        is_optimal = distance <= max_dist

        # Identify issues
        issues = []
        if distance > max_dist:
            issues.append(DecapIssue(
                issue_type=DecapIssueType.TOO_FAR_FROM_PIN,
                severity="high" if distance > 2 * max_dist else "medium",
                description=f"{component_ref} is {distance:.1f}mm from IC, recommended <{max_dist}mm",
                component_ref=component_ref,
                current_distance_mm=distance,
                recommended_distance_mm=max_dist,
                recommendation=f"Move {component_ref} closer to IC power pin",
            ))

        if via_count > 4:
            issues.append(DecapIssue(
                issue_type=DecapIssueType.HIGH_VIA_INDUCTANCE,
                severity="medium",
                description=f"{component_ref} uses {via_count} vias, adding excessive inductance",
                component_ref=component_ref,
                recommendation="Reduce via count or use wider vias",
            ))

        return DecapAnalysis(
            component_ref=component_ref,
            capacitance_uf=capacitance_uf,
            package_size=package_size,
            distance_to_ic_mm=distance,
            via_count=via_count,
            estimated_esl_nh=esl_nh,
            self_resonant_freq_hz=srf,
            effective_freq_range=freq_range,
            is_optimally_placed=is_optimal,
            issues=issues,
        )

    def analyze_ic_decoupling(
        self,
        ic_ref: str,
        ic_position: tuple[float, float],
        power_rail: str,
        target_frequency_hz: float,
        decaps: list[dict],
        max_current_a: float = 1.0,
        voltage_v: float = 3.3,
    ) -> DecapResult:
        """
        Analyze decoupling network for an IC.

        Args:
            ic_ref: IC reference designator
            ic_position: IC center position (x, y) in mm
            power_rail: Power rail name (VCC, VDD, etc.)
            target_frequency_hz: Target operating frequency
            decaps: List of decap specs: {ref, capacitance_uf, package, position, via_count}
            max_current_a: Maximum transient current
            voltage_v: Supply voltage

        Returns:
            DecapResult with analysis and recommendations
        """
        analyzed = []
        all_issues = []
        freq_ranges = []

        # Analyze each decap
        for d in decaps:
            analysis = self.analyze_single_decap(
                component_ref=d.get("ref", "C?"),
                capacitance_uf=d.get("capacitance_uf", 0.1),
                package_size=d.get("package", "0402"),
                position=d.get("position", (0, 0)),
                ic_position=ic_position,
                via_count=d.get("via_count", 2),
                esr_mohm=d.get("esr_mohm"),
            )
            analyzed.append(analysis)
            all_issues.extend(analysis.issues)
            freq_ranges.append(analysis.effective_freq_range)

        # Merge overlapping frequency ranges
        coverage = self._merge_frequency_ranges(freq_ranges)

        # Find frequency gaps
        gaps = self._find_frequency_gaps(
            coverage,
            target_frequency_hz / 100,  # From 1% of target
            target_frequency_hz * 10,    # To 10x target
        )

        # Generate recommendations
        recommendations = self._generate_recommendations(
            gaps, target_frequency_hz, ic_ref, power_rail
        )

        # Check for insufficient decoupling
        if len(decaps) == 0:
            all_issues.append(DecapIssue(
                issue_type=DecapIssueType.INSUFFICIENT_COUNT,
                severity="critical",
                description=f"No decoupling capacitors found for {ic_ref} {power_rail}",
                recommendation="Add at least one 0.1µF capacitor close to power pin",
            ))

        # Calculate score
        score = self._calculate_score(analyzed, gaps, all_issues)

        return DecapResult(
            target_ic_ref=ic_ref,
            power_rail=power_rail,
            analyzed_decaps=analyzed,
            frequency_coverage=coverage,
            frequency_gaps=gaps,
            recommendations=recommendations,
            issues=all_issues,
            score=score,
        )

    def _merge_frequency_ranges(
        self,
        ranges: list[tuple[float, float]],
    ) -> list[tuple[float, float]]:
        """Merge overlapping frequency ranges."""
        if not ranges:
            return []

        # Sort by start frequency
        sorted_ranges = sorted(ranges, key=lambda x: x[0])

        merged = [sorted_ranges[0]]
        for current in sorted_ranges[1:]:
            last = merged[-1]
            if current[0] <= last[1]:
                # Overlapping - extend
                merged[-1] = (last[0], max(last[1], current[1]))
            else:
                # Gap - add new range
                merged.append(current)

        return merged

    def _find_frequency_gaps(
        self,
        coverage: list[tuple[float, float]],
        min_freq: float,
        max_freq: float,
    ) -> list[tuple[float, float]]:
        """Find frequency gaps in coverage."""
        if not coverage:
            return [(min_freq, max_freq)]

        gaps = []
        current_freq = min_freq

        for start, end in coverage:
            if start > current_freq:
                gaps.append((current_freq, start))
            current_freq = max(current_freq, end)

        if current_freq < max_freq:
            gaps.append((current_freq, max_freq))

        return gaps

    def _generate_recommendations(
        self,
        gaps: list[tuple[float, float]],
        target_freq: float,
        ic_ref: str,
        power_rail: str,
    ) -> list[DecapRecommendation]:
        """Generate recommendations to fill frequency gaps."""
        recommendations = []

        for gap_start, gap_end in gaps:
            # Calculate center frequency of gap
            center_freq = math.sqrt(gap_start * gap_end)

            # Determine capacitor value for this frequency
            # SRF = 1/(2π√LC), assuming ~0.5nH ESL for 0402
            esl = 0.5e-9  # 0.5 nH
            cap_value = 1 / ((2 * math.pi * center_freq) ** 2 * esl)
            cap_uf = cap_value * 1e6

            # Round to standard value
            cap_uf = self._round_to_standard_value(cap_uf)

            # Determine priority
            if gap_start < target_freq < gap_end:
                priority = "critical"
            elif gap_start < target_freq * 3:
                priority = "high"
            else:
                priority = "medium"

            recommendations.append(DecapRecommendation(
                capacitance_uf=cap_uf,
                target_frequency_hz=center_freq,
                count=1,
                package_size="0402" if cap_uf < 1 else "0603",
                max_distance_mm=2.0 if cap_uf < 1 else 3.0,
                priority=priority,
                reason=f"Cover frequency gap {gap_start/1e6:.1f}-{gap_end/1e6:.1f} MHz for {ic_ref} {power_rail}",
            ))

        return recommendations

    def _round_to_standard_value(self, value_uf: float) -> float:
        """Round to nearest standard capacitor value."""
        standard_values = [
            0.00001, 0.0001, 0.001, 0.01, 0.022, 0.047,
            0.1, 0.22, 0.47, 1.0, 2.2, 4.7, 10.0, 22.0, 47.0, 100.0
        ]

        closest = min(standard_values, key=lambda x: abs(math.log10(x) - math.log10(value_uf)))
        return closest

    def _calculate_score(
        self,
        analyzed: list[DecapAnalysis],
        gaps: list[tuple[float, float]],
        issues: list[DecapIssue],
    ) -> float:
        """Calculate decoupling quality score."""
        score = 100.0

        # Deduct for issues
        for issue in issues:
            if issue.severity == "critical":
                score -= 25
            elif issue.severity == "high":
                score -= 15
            elif issue.severity == "medium":
                score -= 8
            else:
                score -= 3

        # Deduct for frequency gaps
        score -= len(gaps) * 10

        # Deduct for suboptimal placement
        suboptimal = sum(1 for a in analyzed if not a.is_optimally_placed)
        score -= suboptimal * 5

        return max(0.0, score)

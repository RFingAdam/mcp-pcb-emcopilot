"""
Trace Antenna Analyzer.

Detects traces that may act as unintentional antennas
at frequencies where their length approaches λ/4 or λ/2.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TraceAntennaType(Enum):
    """Types of unintentional antenna structures."""
    QUARTER_WAVE_MONOPOLE = "quarter_wave_monopole"
    HALF_WAVE_DIPOLE = "half_wave_dipole"
    STUB_ANTENNA = "stub_antenna"
    LOOP_ANTENNA = "loop_antenna"


@dataclass
class TraceAntennaIssue:
    """A trace acting as an unintentional antenna."""
    trace_id: str
    net_name: str
    trace_length_mm: float
    antenna_type: TraceAntennaType

    # Resonant characteristics
    resonant_frequency_mhz: float
    signal_frequency_mhz: Optional[float]  # Fundamental frequency on the trace
    harmonic_number: int  # Which harmonic hits the resonance

    # Severity factors
    current_strength: str  # "high", "medium", "low"
    near_edge: bool  # Is trace near board edge?
    has_return_path: bool  # Is there a continuous return path?

    severity: str  # "critical", "high", "medium", "low"
    recommendation: str

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "net_name": self.net_name,
            "trace_length_mm": round(self.trace_length_mm, 2),
            "antenna_type": self.antenna_type.value,
            "resonant_frequency_mhz": round(self.resonant_frequency_mhz, 1),
            "signal_frequency_mhz": round(self.signal_frequency_mhz, 1) if self.signal_frequency_mhz else None,
            "harmonic_number": self.harmonic_number,
            "current_strength": self.current_strength,
            "near_edge": self.near_edge,
            "has_return_path": self.has_return_path,
            "severity": self.severity,
            "recommendation": self.recommendation,
        }


@dataclass
class TraceAntennaResult:
    """Result of trace antenna analysis."""
    issues: list[TraceAntennaIssue] = field(default_factory=list)
    total_traces_analyzed: int = 0
    potential_antennas: int = 0
    max_concern_frequency_mhz: float = 0.0
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "issues": [i.to_dict() for i in self.issues],
            "total_traces_analyzed": self.total_traces_analyzed,
            "potential_antennas": self.potential_antennas,
            "max_concern_frequency_mhz": round(self.max_concern_frequency_mhz, 1),
            "score": round(self.score, 1),
        }


class TraceAntennaAnalyzer:
    """
    Trace antenna analyzer.

    Identifies traces that may act as unintentional antennas
    based on their length and the frequencies present on them.

    Key relationships:
    - Quarter-wave monopole: L = c / (4f)
    - Half-wave dipole: L = c / (2f)
    - Effective wavelength: λ_eff = λ_0 / sqrt(εr_eff)

    Usage:
        analyzer = TraceAntennaAnalyzer(dielectric_constant=4.3)
        result = analyzer.analyze(
            traces=[
                {
                    "id": "trace_1",
                    "net": "CLK_100MHZ",
                    "length_mm": 50,
                    "signal_freq_mhz": 100,
                    "near_board_edge": True,
                    "has_return_plane": True,
                },
            ],
            max_frequency_mhz=3000,  # Analyze up to 3GHz
        )
    """

    # Speed of light (m/s)
    C = 299792458

    def __init__(
        self,
        dielectric_constant: float = 4.3,
        edge_distance_threshold_mm: float = 5.0,
    ):
        """
        Initialize analyzer.

        Args:
            dielectric_constant: PCB dielectric constant (εr)
            edge_distance_threshold_mm: Distance to edge to flag as "near edge"
        """
        self.er = dielectric_constant
        self.edge_threshold = edge_distance_threshold_mm

    def calculate_resonant_frequency(
        self,
        length_mm: float,
        antenna_type: TraceAntennaType,
    ) -> float:
        """
        Calculate resonant frequency for a trace as an antenna.

        Args:
            length_mm: Trace length in mm
            antenna_type: Type of antenna structure

        Returns:
            Resonant frequency in MHz
        """
        length_m = length_mm / 1000

        # Effective dielectric for microstrip (approximate)
        er_eff = (self.er + 1) / 2

        # Velocity factor
        vf = 1 / math.sqrt(er_eff)

        # Effective speed of light
        v = self.C * vf

        if antenna_type == TraceAntennaType.QUARTER_WAVE_MONOPOLE:
            # f = v / (4L)
            freq_hz = v / (4 * length_m)
        elif antenna_type == TraceAntennaType.HALF_WAVE_DIPOLE:
            # f = v / (2L)
            freq_hz = v / (2 * length_m)
        else:
            # Default to quarter wave
            freq_hz = v / (4 * length_m)

        return freq_hz / 1e6  # Convert to MHz

    def find_resonance_at_harmonics(
        self,
        trace_length_mm: float,
        signal_freq_mhz: float,
        max_harmonic: int = 20,
    ) -> list[tuple[int, TraceAntennaType, float]]:
        """
        Find harmonics that hit antenna resonances.

        Args:
            trace_length_mm: Trace length
            signal_freq_mhz: Fundamental signal frequency
            max_harmonic: Maximum harmonic to check

        Returns:
            List of (harmonic_number, antenna_type, resonant_freq)
        """
        resonances = []

        # Calculate resonant frequencies
        f_quarter = self.calculate_resonant_frequency(
            trace_length_mm, TraceAntennaType.QUARTER_WAVE_MONOPOLE
        )
        f_half = self.calculate_resonant_frequency(
            trace_length_mm, TraceAntennaType.HALF_WAVE_DIPOLE
        )

        # Check each harmonic
        for n in range(1, max_harmonic + 1):
            harmonic_freq = signal_freq_mhz * n

            # Check quarter-wave (within 20%)
            if 0.8 * f_quarter <= harmonic_freq <= 1.2 * f_quarter:
                resonances.append((n, TraceAntennaType.QUARTER_WAVE_MONOPOLE, f_quarter))

            # Check half-wave
            if 0.8 * f_half <= harmonic_freq <= 1.2 * f_half:
                resonances.append((n, TraceAntennaType.HALF_WAVE_DIPOLE, f_half))

        return resonances

    def analyze_trace(
        self,
        trace: dict,
        max_frequency_mhz: float,
    ) -> list[TraceAntennaIssue]:
        """
        Analyze a single trace for antenna behavior.

        Args:
            trace: Trace specification
            max_frequency_mhz: Maximum frequency of concern

        Returns:
            List of antenna issues
        """
        issues = []

        trace_id = trace.get("id", "unknown")
        net = trace.get("net", "unknown")
        length = trace.get("length_mm", 0)
        signal_freq = trace.get("signal_freq_mhz")
        near_edge = trace.get("near_board_edge", False)
        has_return = trace.get("has_return_plane", True)
        current = trace.get("current_strength", "medium")

        if length <= 0:
            return []

        # Calculate resonant frequencies
        f_quarter = self.calculate_resonant_frequency(
            length, TraceAntennaType.QUARTER_WAVE_MONOPOLE
        )
        f_half = self.calculate_resonant_frequency(
            length, TraceAntennaType.HALF_WAVE_DIPOLE
        )

        # If signal frequency known, check harmonics
        if signal_freq and signal_freq > 0:
            resonances = self.find_resonance_at_harmonics(length, signal_freq)

            for harmonic, antenna_type, res_freq in resonances:
                if res_freq <= max_frequency_mhz:
                    severity = self._calculate_severity(
                        harmonic, current, near_edge, has_return
                    )
                    recommendation = self._generate_recommendation(
                        antenna_type, severity, length, near_edge
                    )

                    issues.append(TraceAntennaIssue(
                        trace_id=trace_id,
                        net_name=net,
                        trace_length_mm=length,
                        antenna_type=antenna_type,
                        resonant_frequency_mhz=res_freq,
                        signal_frequency_mhz=signal_freq,
                        harmonic_number=harmonic,
                        current_strength=current,
                        near_edge=near_edge,
                        has_return_path=has_return,
                        severity=severity,
                        recommendation=recommendation,
                    ))

        else:
            # No signal frequency - check if trace could be antenna at any frequency
            for freq, antenna_type in [(f_quarter, TraceAntennaType.QUARTER_WAVE_MONOPOLE),
                                       (f_half, TraceAntennaType.HALF_WAVE_DIPOLE)]:
                if freq <= max_frequency_mhz:
                    severity = self._calculate_severity(1, current, near_edge, has_return)
                    recommendation = self._generate_recommendation(
                        antenna_type, severity, length, near_edge
                    )

                    issues.append(TraceAntennaIssue(
                        trace_id=trace_id,
                        net_name=net,
                        trace_length_mm=length,
                        antenna_type=antenna_type,
                        resonant_frequency_mhz=freq,
                        signal_frequency_mhz=None,
                        harmonic_number=1,
                        current_strength=current,
                        near_edge=near_edge,
                        has_return_path=has_return,
                        severity=severity,
                        recommendation=recommendation,
                    ))

        return issues

    def _calculate_severity(
        self,
        harmonic: int,
        current: str,
        near_edge: bool,
        has_return: bool,
    ) -> str:
        """Calculate severity of antenna issue."""
        score = 0

        # Lower harmonics are more significant
        if harmonic <= 3:
            score += 3
        elif harmonic <= 7:
            score += 2
        else:
            score += 1

        # Current strength
        if current == "high":
            score += 3
        elif current == "medium":
            score += 2
        else:
            score += 1

        # Edge proximity increases radiation
        if near_edge:
            score += 2

        # Missing return path is critical
        if not has_return:
            score += 3

        if score >= 8:
            return "critical"
        elif score >= 6:
            return "high"
        elif score >= 4:
            return "medium"
        else:
            return "low"

    def _generate_recommendation(
        self,
        antenna_type: TraceAntennaType,
        severity: str,
        length_mm: float,
        near_edge: bool,
    ) -> str:
        """Generate recommendation for antenna issue."""
        recs = []

        if antenna_type == TraceAntennaType.QUARTER_WAVE_MONOPOLE:
            recs.append(f"Trace ({length_mm:.1f}mm) may act as λ/4 monopole")
        else:
            recs.append(f"Trace ({length_mm:.1f}mm) may act as λ/2 dipole")

        if near_edge:
            recs.append("Move trace away from board edge")

        if severity in ["critical", "high"]:
            recs.append("Consider shortening trace or adding termination")
            recs.append("Ensure continuous return path under entire trace")

        return "; ".join(recs)

    def analyze(
        self,
        traces: list[dict],
        max_frequency_mhz: float = 3000.0,
    ) -> TraceAntennaResult:
        """
        Analyze all traces for antenna behavior.

        Args:
            traces: List of trace specifications
            max_frequency_mhz: Maximum frequency of concern

        Returns:
            TraceAntennaResult with analysis
        """
        all_issues = []
        max_freq = 0.0

        for trace in traces:
            issues = self.analyze_trace(trace, max_frequency_mhz)
            all_issues.extend(issues)

            for issue in issues:
                if issue.resonant_frequency_mhz > max_freq:
                    max_freq = issue.resonant_frequency_mhz

        score = self._calculate_score(all_issues)

        return TraceAntennaResult(
            issues=all_issues,
            total_traces_analyzed=len(traces),
            potential_antennas=len(set(i.trace_id for i in all_issues)),
            max_concern_frequency_mhz=max_freq,
            score=score,
        )

    def _calculate_score(self, issues: list[TraceAntennaIssue]) -> float:
        """Calculate antenna analysis score."""
        score = 100.0

        for issue in issues:
            if issue.severity == "critical":
                score -= 20
            elif issue.severity == "high":
                score -= 10
            elif issue.severity == "medium":
                score -= 5
            else:
                score -= 2

        return max(0.0, score)

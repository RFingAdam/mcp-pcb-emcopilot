"""
Power Distribution Network (PDN) Impedance Analyzer.

Analyzes the PDN impedance profile and identifies potential issues:
- Target impedance calculation based on load requirements
- Frequency-domain impedance analysis
- Resonance detection (parallel/series)
- Anti-resonance identification
- Decoupling effectiveness evaluation
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PDNIssueType(str, Enum):
    """Types of PDN issues."""
    HIGH_IMPEDANCE = "high_impedance"
    RESONANCE = "resonance"
    ANTI_RESONANCE = "anti_resonance"
    INSUFFICIENT_DECOUPLING = "insufficient_decoupling"
    EXCESSIVE_LOOP_INDUCTANCE = "excessive_loop_inductance"
    PLANE_RESONANCE = "plane_resonance"


@dataclass
class PDNImpedancePoint:
    """Single frequency point in PDN impedance profile."""
    frequency_hz: float
    impedance_ohm: float
    phase_deg: float
    is_resonance: bool = False
    is_anti_resonance: bool = False

    def to_dict(self) -> dict:
        return {
            "frequency_hz": self.frequency_hz,
            "impedance_ohm": round(self.impedance_ohm, 4),
            "phase_deg": round(self.phase_deg, 2),
            "is_resonance": self.is_resonance,
            "is_anti_resonance": self.is_anti_resonance,
        }


@dataclass
class PDNIssue:
    """A PDN-related issue."""
    issue_type: PDNIssueType
    severity: str  # critical, high, medium, low
    description: str
    frequency_hz: Optional[float] = None
    impedance_ohm: Optional[float] = None
    target_ohm: Optional[float] = None
    recommendation: Optional[str] = None
    location: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "issue_type": self.issue_type.value,
            "severity": self.severity,
            "description": self.description,
            "frequency_hz": self.frequency_hz,
            "impedance_ohm": round(self.impedance_ohm, 4) if self.impedance_ohm else None,
            "target_ohm": round(self.target_ohm, 4) if self.target_ohm else None,
            "recommendation": self.recommendation,
            "location": self.location,
        }


@dataclass
class PDNResult:
    """Result of PDN impedance analysis."""
    # Target impedance
    target_impedance_ohm: float
    target_frequency_hz: float

    # Impedance profile
    impedance_profile: list[PDNImpedancePoint] = field(default_factory=list)

    # Key metrics
    max_impedance_ohm: float = 0.0
    max_impedance_freq_hz: float = 0.0
    min_impedance_ohm: float = float("inf")
    min_impedance_freq_hz: float = 0.0

    # Resonances detected
    resonance_frequencies: list[float] = field(default_factory=list)
    anti_resonance_frequencies: list[float] = field(default_factory=list)

    # Issues found
    issues: list[PDNIssue] = field(default_factory=list)

    # Analysis summary
    meets_target: bool = True
    margin_db: float = 0.0
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "target_impedance_ohm": round(self.target_impedance_ohm, 4),
            "target_frequency_hz": self.target_frequency_hz,
            "impedance_profile": [p.to_dict() for p in self.impedance_profile],
            "max_impedance_ohm": round(self.max_impedance_ohm, 4),
            "max_impedance_freq_hz": self.max_impedance_freq_hz,
            "min_impedance_ohm": round(self.min_impedance_ohm, 4),
            "min_impedance_freq_hz": self.min_impedance_freq_hz,
            "resonance_frequencies": self.resonance_frequencies,
            "anti_resonance_frequencies": self.anti_resonance_frequencies,
            "issues": [i.to_dict() for i in self.issues],
            "meets_target": self.meets_target,
            "margin_db": round(self.margin_db, 2),
            "score": round(self.score, 1),
        }


class PDNAnalyzer:
    """
    Power Distribution Network impedance analyzer.

    Calculates PDN impedance considering:
    - Power plane capacitance
    - Decoupling capacitor network
    - Package and via inductance
    - Bulk capacitors
    - VRM output impedance

    Usage:
        analyzer = PDNAnalyzer()
        result = analyzer.analyze(
            voltage=1.0,
            max_current=5.0,
            ripple_percent=3.0,
            decaps=[
                {"capacitance_uf": 0.1, "esr_mohm": 10, "esl_nh": 0.5, "count": 20},
                {"capacitance_uf": 10, "esr_mohm": 5, "esl_nh": 1.0, "count": 4},
            ],
            plane_area_mm2=2500,
            plane_spacing_mm=0.1,
            dielectric_constant=4.3,
        )
    """

    # Physical constants
    EPS0 = 8.854187817e-12  # F/m

    def __init__(
        self,
        freq_start_hz: float = 1e3,
        freq_stop_hz: float = 1e9,
        num_points: int = 200,
    ):
        """
        Initialize PDN analyzer.

        Args:
            freq_start_hz: Start frequency for analysis
            freq_stop_hz: Stop frequency for analysis
            num_points: Number of frequency points
        """
        self.freq_start = freq_start_hz
        self.freq_stop = freq_stop_hz
        self.num_points = num_points

    def calculate_target_impedance(
        self,
        voltage: float,
        max_current: float,
        ripple_percent: float = 5.0,
        transient_current_fraction: float = 0.5,
    ) -> float:
        """
        Calculate target PDN impedance.

        Formula: Z_target = V * ripple% / I_transient

        Args:
            voltage: Supply voltage (V)
            max_current: Maximum load current (A)
            ripple_percent: Allowable voltage ripple (%)
            transient_current_fraction: Fraction of max current in transient

        Returns:
            Target impedance in Ohms
        """
        i_transient = max_current * transient_current_fraction
        z_target = (voltage * ripple_percent / 100) / i_transient
        return z_target

    def calculate_plane_capacitance(
        self,
        area_mm2: float,
        spacing_mm: float,
        dielectric_constant: float = 4.3,
    ) -> float:
        """
        Calculate parallel plate capacitance of power-ground plane pair.

        Args:
            area_mm2: Plane area in mm²
            spacing_mm: Spacing between planes in mm
            dielectric_constant: Relative permittivity

        Returns:
            Capacitance in Farads
        """
        area_m2 = area_mm2 * 1e-6
        spacing_m = spacing_mm * 1e-3
        capacitance = self.EPS0 * dielectric_constant * area_m2 / spacing_m
        return capacitance

    def calculate_decap_impedance(
        self,
        frequency_hz: float,
        capacitance_f: float,
        esr_ohm: float,
        esl_h: float,
    ) -> complex:
        """
        Calculate impedance of a single decoupling capacitor.

        Z = ESR + j(wL - 1/wC)

        Args:
            frequency_hz: Frequency in Hz
            capacitance_f: Capacitance in Farads
            esr_ohm: Equivalent series resistance in Ohms
            esl_h: Equivalent series inductance in Henries

        Returns:
            Complex impedance
        """
        omega = 2 * math.pi * frequency_hz
        z_c = -1j / (omega * capacitance_f) if capacitance_f > 0 else 0
        z_l = 1j * omega * esl_h
        return esr_ohm + z_c + z_l

    def analyze(
        self,
        voltage: float,
        max_current: float,
        ripple_percent: float = 5.0,
        decaps: Optional[list[dict]] = None,
        plane_area_mm2: Optional[float] = None,
        plane_spacing_mm: float = 0.1,
        dielectric_constant: float = 4.3,
        via_inductance_nh: float = 0.5,
        package_inductance_nh: float = 1.0,
        vrm_output_impedance: Optional[float] = None,
    ) -> PDNResult:
        """
        Perform full PDN impedance analysis.

        Args:
            voltage: Supply voltage (V)
            max_current: Maximum load current (A)
            ripple_percent: Allowable ripple (%)
            decaps: List of decap specs: {capacitance_uf, esr_mohm, esl_nh, count}
            plane_area_mm2: Power plane area
            plane_spacing_mm: Power-ground plane spacing
            dielectric_constant: Dielectric Er
            via_inductance_nh: Via inductance to add to ESL
            package_inductance_nh: Package inductance
            vrm_output_impedance: VRM output impedance at low freq

        Returns:
            PDNResult with impedance profile and analysis
        """
        # Calculate target impedance
        z_target = self.calculate_target_impedance(voltage, max_current, ripple_percent)

        # Calculate plane capacitance if area provided
        plane_capacitance = 0.0
        if plane_area_mm2:
            plane_capacitance = self.calculate_plane_capacitance(
                plane_area_mm2, plane_spacing_mm, dielectric_constant
            )

        # Generate frequency points (log scale)
        frequencies = self._log_space(self.freq_start, self.freq_stop, self.num_points)

        # Build decap list
        decap_list = []
        if decaps:
            for d in decaps:
                cap_f = d.get("capacitance_uf", 0.1) * 1e-6
                esr = d.get("esr_mohm", 10) * 1e-3
                esl = (d.get("esl_nh", 0.5) + via_inductance_nh) * 1e-9
                count = d.get("count", 1)
                decap_list.append({
                    "capacitance_f": cap_f,
                    "esr_ohm": esr,
                    "esl_h": esl,
                    "count": count,
                })

        # Calculate impedance at each frequency
        impedance_profile = []
        max_z = 0.0
        max_z_freq = 0.0
        min_z = float("inf")
        min_z_freq = 0.0
        prev_phase = None

        for freq in frequencies:
            omega = 2 * math.pi * freq

            # Start with VRM impedance (dominates at low frequency)
            if vrm_output_impedance and freq < 1e5:
                z_vrm = vrm_output_impedance
            else:
                z_vrm = float("inf")

            # Plane capacitance impedance
            z_plane = 1 / (1j * omega * plane_capacitance) if plane_capacitance > 0 else float("inf")

            # Parallel combination of all decaps
            y_total = 0j
            for decap in decap_list:
                z_decap = self.calculate_decap_impedance(
                    freq,
                    decap["capacitance_f"],
                    decap["esr_ohm"],
                    decap["esl_h"],
                )
                if abs(z_decap) > 1e-12:
                    y_total += decap["count"] / z_decap

            # Add plane capacitance
            if plane_capacitance > 0:
                y_total += 1 / z_plane

            # Convert to impedance
            if abs(y_total) > 1e-12:
                z_total = 1 / y_total
            else:
                z_total = 1e6 + 0j

            # Account for package inductance at high freq
            z_pkg = 1j * omega * package_inductance_nh * 1e-9
            z_total = z_total + z_pkg

            z_mag = abs(z_total)
            z_phase = math.degrees(math.atan2(z_total.imag, z_total.real))

            # Detect resonance/anti-resonance
            is_resonance = False
            is_anti_resonance = False
            if prev_phase is not None:
                # Anti-resonance (impedance peak): phase crosses negative to positive
                if prev_phase < 0 and z_phase > 0:
                    is_anti_resonance = True
                # Series resonance (impedance minimum): phase crosses positive to negative
                elif prev_phase > 0 and z_phase < 0:
                    is_resonance = True

            point = PDNImpedancePoint(
                frequency_hz=freq,
                impedance_ohm=z_mag,
                phase_deg=z_phase,
                is_resonance=is_resonance,
                is_anti_resonance=is_anti_resonance,
            )
            impedance_profile.append(point)

            if z_mag > max_z:
                max_z = z_mag
                max_z_freq = freq
            if z_mag < min_z:
                min_z = z_mag
                min_z_freq = freq

            prev_phase = z_phase

        # Collect resonance frequencies
        resonance_freqs = [p.frequency_hz for p in impedance_profile if p.is_resonance]
        anti_resonance_freqs = [p.frequency_hz for p in impedance_profile if p.is_anti_resonance]

        # Check if target is met
        meets_target = max_z <= z_target
        margin_db = 20 * math.log10(z_target / max_z) if max_z > 0 else float("inf")

        # Identify issues
        issues = self._identify_issues(
            impedance_profile, z_target, anti_resonance_freqs, plane_area_mm2
        )

        # Calculate score
        score = self._calculate_score(meets_target, margin_db, issues)

        return PDNResult(
            target_impedance_ohm=z_target,
            target_frequency_hz=1e6,  # Typical target frequency
            impedance_profile=impedance_profile,
            max_impedance_ohm=max_z,
            max_impedance_freq_hz=max_z_freq,
            min_impedance_ohm=min_z,
            min_impedance_freq_hz=min_z_freq,
            resonance_frequencies=resonance_freqs,
            anti_resonance_frequencies=anti_resonance_freqs,
            issues=issues,
            meets_target=meets_target,
            margin_db=margin_db,
            score=score,
        )

    def _log_space(self, start: float, stop: float, num: int) -> list[float]:
        """Generate logarithmically spaced frequencies."""
        log_start = math.log10(start)
        log_stop = math.log10(stop)
        step = (log_stop - log_start) / (num - 1)
        return [10 ** (log_start + i * step) for i in range(num)]

    def _identify_issues(
        self,
        profile: list[PDNImpedancePoint],
        z_target: float,
        anti_resonance_freqs: list[float],
        plane_area: Optional[float],
    ) -> list[PDNIssue]:
        """Identify PDN issues from impedance profile."""
        issues = []

        # Check for high impedance exceeding target
        for point in profile:
            if point.impedance_ohm > z_target:
                issues.append(PDNIssue(
                    issue_type=PDNIssueType.HIGH_IMPEDANCE,
                    severity="high" if point.impedance_ohm > 2 * z_target else "medium",
                    description=f"PDN impedance exceeds target at {point.frequency_hz/1e6:.2f} MHz",
                    frequency_hz=point.frequency_hz,
                    impedance_ohm=point.impedance_ohm,
                    target_ohm=z_target,
                    recommendation="Add decoupling capacitors with self-resonant frequency near this frequency",
                ))

        # Check for anti-resonance peaks
        for freq in anti_resonance_freqs:
            point = next((p for p in profile if abs(p.frequency_hz - freq) < freq * 0.1), None)  # type: ignore[assignment]
            if point and point.impedance_ohm > z_target * 0.8:
                issues.append(PDNIssue(
                    issue_type=PDNIssueType.ANTI_RESONANCE,
                    severity="medium",
                    description=f"Anti-resonance peak detected at {freq/1e6:.2f} MHz",
                    frequency_hz=freq,
                    impedance_ohm=point.impedance_ohm if point else None,
                    recommendation="Add decoupling capacitor to bridge the anti-resonance gap",
                ))

        # Check plane area
        if plane_area and plane_area < 500:
            issues.append(PDNIssue(
                issue_type=PDNIssueType.INSUFFICIENT_DECOUPLING,
                severity="medium",
                description="Power plane area is small, limiting high-frequency decoupling",
                location="power_plane",
                recommendation="Maximize power plane area or add more small-value decaps",
            ))

        return issues

    def _calculate_score(
        self,
        meets_target: bool,
        margin_db: float,
        issues: list[PDNIssue],
    ) -> float:
        """Calculate PDN quality score (0-100)."""
        score = 100.0

        # Deduct for not meeting target
        if not meets_target:
            score -= 30 + min(20, abs(margin_db) * 2)

        # Deduct for issues
        for issue in issues:
            if issue.severity == "critical":
                score -= 15
            elif issue.severity == "high":
                score -= 10
            elif issue.severity == "medium":
                score -= 5
            else:
                score -= 2

        return max(0.0, score)

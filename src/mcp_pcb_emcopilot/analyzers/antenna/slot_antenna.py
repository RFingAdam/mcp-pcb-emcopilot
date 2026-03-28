"""
Slot Antenna Analyzer.

Detects slots in ground/power planes that may act as
unintentional slot antennas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SlotType(Enum):
    """Types of slot structures."""
    GROUND_PLANE_SLOT = "ground_plane_slot"
    POWER_PLANE_SPLIT = "power_plane_split"
    VIA_CLEARANCE_CHAIN = "via_clearance_chain"
    CONNECTOR_CUTOUT = "connector_cutout"


class SlotSeverity(Enum):
    """Slot antenna severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class SlotAntennaIssue:
    """A slot acting as an unintentional antenna."""
    slot_id: str
    slot_type: SlotType
    layer: str

    # Slot dimensions
    length_mm: float
    width_mm: float
    aspect_ratio: float

    # Resonant characteristics
    resonant_frequency_mhz: float
    frequency_in_band: bool  # Is resonance in operating frequency range?

    # Coupling information
    crossing_traces: list[str]  # Traces crossing the slot
    high_speed_crossing: bool  # Do high-speed signals cross?

    severity: SlotSeverity
    recommendation: str

    def to_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "slot_type": self.slot_type.value,
            "layer": self.layer,
            "length_mm": round(self.length_mm, 2),
            "width_mm": round(self.width_mm, 2),
            "aspect_ratio": round(self.aspect_ratio, 1),
            "resonant_frequency_mhz": round(self.resonant_frequency_mhz, 1),
            "frequency_in_band": self.frequency_in_band,
            "crossing_traces": self.crossing_traces,
            "high_speed_crossing": self.high_speed_crossing,
            "severity": self.severity.value,
            "recommendation": self.recommendation,
        }


@dataclass
class SlotAntennaResult:
    """Result of slot antenna analysis."""
    issues: list[SlotAntennaIssue] = field(default_factory=list)
    total_slots_analyzed: int = 0
    critical_slots: int = 0
    high_slots: int = 0
    lowest_resonance_mhz: float = float("inf")
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "issues": [i.to_dict() for i in self.issues],
            "total_slots_analyzed": self.total_slots_analyzed,
            "critical_slots": self.critical_slots,
            "high_slots": self.high_slots,
            "lowest_resonance_mhz": round(self.lowest_resonance_mhz, 1)
            if self.lowest_resonance_mhz != float("inf") else None,
            "score": round(self.score, 1),
        }


class SlotAntennaAnalyzer:
    """
    Slot antenna analyzer.

    Identifies slots in reference planes that may radiate
    at their resonant frequencies.

    Slot antenna resonance: f = c / (2L * sqrt(εr_eff))

    A slot in a ground plane is the dual of a dipole antenna.
    It radiates when:
    - Length approaches λ/2 at some frequency
    - Current is forced to flow around it
    - High-speed signals cross it

    Usage:
        analyzer = SlotAntennaAnalyzer()
        result = analyzer.analyze(
            slots=[
                {
                    "id": "slot_1",
                    "type": "ground_plane_slot",
                    "layer": "L2_GND",
                    "length_mm": 30,
                    "width_mm": 1.5,
                    "crossing_nets": ["DDR_DQ0", "DDR_DQ1"],
                    "high_speed_crossing": True,
                },
            ],
            operating_frequencies_mhz=[100, 400, 1066],  # DDR3 frequencies
        )
    """

    C = 299792458  # Speed of light

    def __init__(
        self,
        dielectric_constant: float = 4.3,
        min_slot_length_mm: float = 2.0,
    ):
        """
        Initialize analyzer.

        Args:
            dielectric_constant: PCB εr
            min_slot_length_mm: Minimum slot length to analyze
        """
        self.er = dielectric_constant
        self.min_length = min_slot_length_mm

    def calculate_slot_resonance(self, length_mm: float) -> float:
        """
        Calculate slot antenna resonant frequency.

        For a slot in a ground plane, the resonant frequency is:
        f = c / (2L * sqrt(εr_eff))

        Args:
            length_mm: Slot length in mm

        Returns:
            Resonant frequency in MHz
        """
        length_m = length_mm / 1000
        # Hammerstad εr_eff — use w/h ratio if available, else assume w/h=1
        w_over_h = getattr(self, 'w_over_h', 1.0)
        f_wh = (1 + 12 / max(w_over_h, 0.1)) ** (-0.5)
        er_eff = (self.er + 1) / 2 + (self.er - 1) / 2 * f_wh

        freq_hz = self.C / (2 * length_m * math.sqrt(er_eff))
        return freq_hz / 1e6

    def check_frequency_in_band(
        self,
        resonant_freq: float,
        operating_frequencies: list[float],
        max_harmonic: int = 10,
    ) -> bool:
        """
        Check if slot resonance is in the operating frequency band.

        Args:
            resonant_freq: Slot resonant frequency
            operating_frequencies: List of operating frequencies
            max_harmonic: Maximum harmonic to check

        Returns:
            True if resonance is within 20% of any harmonic
        """
        for f_op in operating_frequencies:
            for n in range(1, max_harmonic + 1):
                harmonic = f_op * n
                if 0.8 * resonant_freq <= harmonic <= 1.2 * resonant_freq:
                    return True
        return False

    def analyze_slot(
        self,
        slot: dict,
        operating_frequencies: list[float],
    ) -> Optional[SlotAntennaIssue]:
        """
        Analyze a single slot for antenna behavior.

        Args:
            slot: Slot specification
            operating_frequencies: Operating frequencies to check

        Returns:
            SlotAntennaIssue if problematic, None otherwise
        """
        slot_id = slot.get("id", "unknown")
        slot_type_str = slot.get("type", "ground_plane_slot")
        layer = slot.get("layer", "unknown")
        length = slot.get("length_mm", 0)
        width = slot.get("width_mm", 0.5)
        crossing_nets = slot.get("crossing_nets", [])
        hs_crossing = slot.get("high_speed_crossing", False)

        if length < self.min_length:
            return None

        # Map type string to enum
        type_map = {
            "ground_plane_slot": SlotType.GROUND_PLANE_SLOT,
            "power_plane_split": SlotType.POWER_PLANE_SPLIT,
            "via_clearance_chain": SlotType.VIA_CLEARANCE_CHAIN,
            "connector_cutout": SlotType.CONNECTOR_CUTOUT,
        }
        slot_type = type_map.get(slot_type_str, SlotType.GROUND_PLANE_SLOT)

        # Calculate resonance
        resonant_freq = self.calculate_slot_resonance(length)
        in_band = self.check_frequency_in_band(resonant_freq, operating_frequencies)

        # Calculate aspect ratio
        aspect = length / width if width > 0 else length

        # Determine severity
        severity = self._calculate_severity(
            slot_type, aspect, in_band, hs_crossing, len(crossing_nets)
        )

        # Generate recommendation
        recommendation = self._generate_recommendation(
            slot_type, severity, length, crossing_nets
        )

        return SlotAntennaIssue(
            slot_id=slot_id,
            slot_type=slot_type,
            layer=layer,
            length_mm=length,
            width_mm=width,
            aspect_ratio=aspect,
            resonant_frequency_mhz=resonant_freq,
            frequency_in_band=in_band,
            crossing_traces=crossing_nets[:5],  # Limit to first 5
            high_speed_crossing=hs_crossing,
            severity=severity,
            recommendation=recommendation,
        )

    def _calculate_severity(
        self,
        slot_type: SlotType,
        aspect_ratio: float,
        in_band: bool,
        hs_crossing: bool,
        crossing_count: int,
    ) -> SlotSeverity:
        """Calculate slot severity."""
        score = 0

        # Slot type
        if slot_type == SlotType.POWER_PLANE_SPLIT:
            score += 3
        elif slot_type == SlotType.GROUND_PLANE_SLOT:
            score += 2
        else:
            score += 1

        # Aspect ratio (narrow slots are worse)
        if aspect_ratio > 20:
            score += 3
        elif aspect_ratio > 10:
            score += 2
        elif aspect_ratio > 5:
            score += 1

        # In-band resonance
        if in_band:
            score += 3

        # High-speed crossing
        if hs_crossing:
            score += 3
        elif crossing_count > 3:
            score += 2
        elif crossing_count > 0:
            score += 1

        if score >= 9:
            return SlotSeverity.CRITICAL
        elif score >= 6:
            return SlotSeverity.HIGH
        elif score >= 4:
            return SlotSeverity.MEDIUM
        else:
            return SlotSeverity.LOW

    def _generate_recommendation(
        self,
        slot_type: SlotType,
        severity: SlotSeverity,
        length: float,
        crossing_nets: list[str],
    ) -> str:
        """Generate recommendation for slot issue."""
        recs = []

        if slot_type == SlotType.POWER_PLANE_SPLIT:
            recs.append("Consider stitching power plane split with capacitors")
        elif slot_type == SlotType.GROUND_PLANE_SLOT:
            recs.append(f"Slot ({length:.1f}mm) may radiate - add stitching vias")

        if severity in [SlotSeverity.CRITICAL, SlotSeverity.HIGH]:
            if crossing_nets:
                recs.append(f"Re-route {crossing_nets[0]} to avoid slot crossing")
            recs.append("Add copper stitching to bridge the slot")

        if len(crossing_nets) > 3:
            recs.append(f"{len(crossing_nets)} signals cross this slot - review routing")

        return "; ".join(recs) if recs else "Monitor slot for EMI issues"

    def analyze(
        self,
        slots: list[dict],
        operating_frequencies_mhz: list[float] = None,  # type: ignore[assignment]
    ) -> SlotAntennaResult:
        """
        Analyze all slots for antenna behavior.

        Args:
            slots: List of slot specifications
            operating_frequencies_mhz: Operating frequencies to check

        Returns:
            SlotAntennaResult with analysis
        """
        if operating_frequencies_mhz is None:
            operating_frequencies_mhz = [100.0]  # Default 100MHz

        issues = []
        lowest_res = float("inf")
        critical = 0
        high = 0

        for slot in slots:
            issue = self.analyze_slot(slot, operating_frequencies_mhz)
            if issue:
                issues.append(issue)
                if issue.resonant_frequency_mhz < lowest_res:
                    lowest_res = issue.resonant_frequency_mhz
                if issue.severity == SlotSeverity.CRITICAL:
                    critical += 1
                elif issue.severity == SlotSeverity.HIGH:
                    high += 1

        score = self._calculate_score(issues)

        return SlotAntennaResult(
            issues=issues,
            total_slots_analyzed=len(slots),
            critical_slots=critical,
            high_slots=high,
            lowest_resonance_mhz=lowest_res,
            score=score,
        )

    def _calculate_score(self, issues: list[SlotAntennaIssue]) -> float:
        """Calculate slot analysis score."""
        score = 100.0

        for issue in issues:
            if issue.severity == SlotSeverity.CRITICAL:
                score -= 20
            elif issue.severity == SlotSeverity.HIGH:
                score -= 10
            elif issue.severity == SlotSeverity.MEDIUM:
                score -= 5
            else:
                score -= 2

        return max(0.0, score)

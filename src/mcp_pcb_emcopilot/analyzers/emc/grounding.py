"""Grounding analyzer for EMC assessment"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class GroundingResult:
    """Results from grounding analysis"""
    # Board identification
    board_id: str
    layer_count: int

    # Ground plane assessment
    ground_coverage_percent: float
    plane_count: int
    split_plane_count: int
    island_count: int

    # Return path quality
    return_path_score: float  # 0-100
    via_stitching_density: float  # vias per cm²
    antipad_risk_areas: int

    # Impedance characteristics
    plane_impedance_mohm: float
    max_via_inductance_nh: float

    # EMC assessment
    emc_score: float  # 0-100
    risk_level: str  # low, medium, high, critical

    # Split plane analysis
    splits: List[Dict[str, Any]] = field(default_factory=list)

    # Issues and recommendations
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    # Details
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GroundPlane:
    """Ground plane definition"""
    layer_number: int
    name: str
    coverage_percent: float
    width_mm: float
    height_mm: float
    copper_thickness_um: float = 35
    splits: List[Dict[str, float]] = field(default_factory=list)  # List of {x, y, length, width}
    voids: List[Dict[str, float]] = field(default_factory=list)  # List of {x, y, radius}
    via_locations: List[Tuple[float, float]] = field(default_factory=list)


@dataclass
class SignalCrossing:
    """Signal crossing a split or void"""
    net_name: str
    layer: int
    crossing_type: str  # split, void, edge
    crossing_location: Tuple[float, float]
    signal_type: str  # clock, data, power, analog


class GroundingAnalyzer:
    """
    Grounding and return path analyzer for EMC.

    Analyzes:
    - Ground plane integrity
    - Split plane issues
    - Via stitching adequacy
    - Return path discontinuities

    Critical for signal integrity and EMC compliance.
    """

    # Copper conductivity (S/m)
    COPPER_CONDUCTIVITY = 5.8e7

    # Recommended via stitching densities (vias per cm²)
    STITCHING_RECOMMENDATIONS = {
        "low_speed": 0.5,      # < 100 MHz
        "medium_speed": 2.0,   # 100 MHz - 1 GHz
        "high_speed": 5.0,     # 1 - 5 GHz
        "very_high_speed": 10.0,  # > 5 GHz
    }

    def __init__(self):
        pass

    def analyze_grounding(
        self,
        planes: List[GroundPlane],
        board_width_mm: float,
        board_height_mm: float,
        board_id: str = "PCB1",
        max_frequency_mhz: float = 1000,
        via_density: Optional[float] = None,
    ) -> GroundingResult:
        """
        Analyze board grounding.

        Args:
            planes: List of ground plane definitions
            board_width_mm: Board width
            board_height_mm: Board height
            board_id: Board identifier
            max_frequency_mhz: Maximum signal frequency

        Returns:
            GroundingResult with complete analysis
        """
        board_area_cm2 = (board_width_mm * board_height_mm) / 100

        # Analyze each plane
        total_coverage: float = 0
        total_splits = 0
        total_islands = 0
        total_vias = 0
        all_splits = []

        for plane in planes:
            total_coverage += plane.coverage_percent
            total_splits += len(plane.splits)
            total_vias += len(plane.via_locations)

            # Analyze splits
            for split in plane.splits:
                split_analysis = self._analyze_split(split, max_frequency_mhz)
                split_analysis["layer"] = plane.layer_number
                all_splits.append(split_analysis)

            # Estimate islands from voids
            total_islands += self._estimate_islands(plane)

        avg_coverage = total_coverage / len(planes) if planes else 0
        # Use provided via density if available (from actual design data),
        # otherwise fall back to counting via_locations on plane objects
        if via_density is None:
            via_density = total_vias / board_area_cm2 if board_area_cm2 > 0 else 0

        # Calculate plane impedance
        if planes:
            plane_impedance = self._calculate_plane_impedance(
                planes[0], board_width_mm, board_height_mm
            )
        else:
            plane_impedance = 1.0  # Default high

        # Via inductance
        max_via_inductance = self._estimate_via_inductance(planes, max_frequency_mhz)

        # Antipad risk areas
        antipad_risk = self._count_antipad_risks(planes, max_frequency_mhz)

        # Return path score
        return_path_score = self._calculate_return_path_score(
            avg_coverage,
            total_splits,
            via_density,
            max_frequency_mhz,
        )

        # EMC score
        emc_score = self._calculate_emc_score(
            avg_coverage,
            total_splits,
            total_islands,
            via_density,
            plane_impedance,
            max_frequency_mhz,
        )

        # Risk level
        if emc_score >= 80:
            risk_level = "low"
        elif emc_score >= 60:
            risk_level = "medium"
        elif emc_score >= 40:
            risk_level = "high"
        else:
            risk_level = "critical"

        # Generate issues and recommendations
        issues = []
        recommendations = []

        if avg_coverage < 80:
            issues.append(f"Ground coverage {avg_coverage:.1f}% below 80% target")
            recommendations.append("Increase ground plane copper pour")

        if total_splits > 0:
            issues.append(f"{total_splits} split plane(s) detected")
            recommendations.append("Review signal routing across splits")
            recommendations.append("Add stitching capacitors near split boundaries")

        if total_islands > 0:
            issues.append(f"{total_islands} isolated copper island(s)")
            recommendations.append("Connect or remove floating copper islands")

        # Via stitching
        required_density = self._get_required_via_density(max_frequency_mhz)
        if via_density < required_density:
            issues.append(f"Via stitching {via_density:.1f}/cm² below {required_density:.1f}/cm² for {max_frequency_mhz}MHz")
            recommendations.append(f"Add ground vias to achieve {required_density:.1f} vias/cm²")

        if plane_impedance > 1:  # > 1 mΩ
            issues.append(f"Plane impedance {plane_impedance:.2f}mΩ may cause ground bounce")
            recommendations.append("Use thicker copper or reduce return path length")

        if antipad_risk > 5:
            issues.append(f"{antipad_risk} high-risk antipad areas for return currents")
            recommendations.append("Add return vias near signal vias in critical areas")

        return GroundingResult(
            board_id=board_id,
            layer_count=len(planes),
            ground_coverage_percent=round(avg_coverage, 1),
            plane_count=len(planes),
            split_plane_count=total_splits,
            island_count=total_islands,
            return_path_score=round(return_path_score, 1),
            via_stitching_density=round(via_density, 2),
            antipad_risk_areas=antipad_risk,
            plane_impedance_mohm=round(plane_impedance, 3),
            max_via_inductance_nh=round(max_via_inductance, 2),
            emc_score=round(emc_score, 1),
            risk_level=risk_level,
            splits=all_splits,
            issues=issues,
            recommendations=recommendations,
            metrics={
                "board_area_cm2": round(board_area_cm2, 1),
                "total_vias": total_vias,
                "max_frequency_mhz": max_frequency_mhz,
                "required_via_density": required_density,
            },
        )

    def _analyze_split(
        self,
        split: Dict[str, float],
        max_frequency_mhz: float,
    ) -> Dict[str, Any]:
        """Analyze a single split."""
        length = split.get("length", 10)
        width = split.get("width", 1)

        # Split resonance frequency
        wavelength_at_res_mm = 2 * length
        resonance_mhz = 300000 / wavelength_at_res_mm

        # Risk assessment
        if resonance_mhz < max_frequency_mhz * 1.5:
            risk = "high"
        elif resonance_mhz < max_frequency_mhz * 3:
            risk = "medium"
        else:
            risk = "low"

        return {
            "length_mm": length,
            "width_mm": width,
            "resonance_mhz": round(resonance_mhz, 0),
            "risk": risk,
            "x": split.get("x", 0),
            "y": split.get("y", 0),
        }

    def _estimate_islands(self, plane: GroundPlane) -> int:
        """Estimate number of isolated islands."""
        # Simplified: count voids that might create islands
        large_voids = [v for v in plane.voids if v.get("radius", 0) > 2]
        return len(large_voids) // 3  # Rough estimate

    def _calculate_plane_impedance(
        self,
        plane: GroundPlane,
        width_mm: float,
        height_mm: float,
    ) -> float:
        """
        Calculate ground plane DC impedance in mΩ.

        R = ρL / (W × t)
        """
        thickness_m = plane.copper_thickness_um * 1e-6
        width_m = width_mm * 1e-3
        length_m = height_mm * 1e-3  # Assume current flows across height

        resistivity = 1 / self.COPPER_CONDUCTIVITY  # Ω⋅m

        # Sheet resistance
        r_sheet = resistivity / thickness_m

        # Total resistance (simplified rectangular model)
        resistance = r_sheet * length_m / width_m

        return resistance * 1000  # Convert to mΩ

    def _estimate_via_inductance(
        self,
        planes: List[GroundPlane],
        max_frequency_mhz: float,
    ) -> float:
        """Estimate maximum via inductance in nH."""
        # Typical via inductance: 0.5-1.5 nH
        # Depends on via length and diameter

        if not planes:
            return 1.0

        # Assume typical via parameters
        via_length_mm = 1.6  # Through-hole
        via_diameter_mm = 0.3

        # Wheeler formula approximation
        # L ≈ 5.08 × h × [ln(4h/d) - 1] nH
        h = via_length_mm
        d = via_diameter_mm
        inductance = 5.08 * h * (math.log(4 * h / d) - 1) / 25.4

        return max(0.3, inductance)

    def _count_antipad_risks(
        self,
        planes: List[GroundPlane],
        max_frequency_mhz: float,
    ) -> int:
        """Count areas where antipads may disrupt return current."""
        # At high frequencies, antipad size matters more
        wavelength_mm = 300000 / max_frequency_mhz

        risk_count = 0
        for plane in planes:
            # Voids larger than λ/20 are potential issues
            threshold = wavelength_mm / 20
            for void in plane.voids:
                if void.get("radius", 0) > threshold:
                    risk_count += 1

        return risk_count

    def _calculate_return_path_score(
        self,
        coverage: float,
        splits: int,
        via_density: float,
        max_freq_mhz: float,
    ) -> float:
        """Calculate return path quality score 0-100."""
        score = 100.0

        # Coverage factor
        if coverage < 95:
            score -= (95 - coverage) * 1.5

        # Split penalty
        score -= splits * 10

        # Via density factor
        required = self._get_required_via_density(max_freq_mhz)
        if via_density < required:
            score -= (required - via_density) / required * 30

        return max(0, min(100, score))

    def _calculate_emc_score(
        self,
        coverage: float,
        splits: int,
        islands: int,
        via_density: float,
        plane_impedance: float,
        max_freq_mhz: float,
    ) -> float:
        """Calculate overall EMC score 0-100."""
        score = 100.0

        # Coverage (40% weight)
        if coverage < 90:
            score -= (90 - coverage) * 0.5

        # Splits and islands (30% weight)
        score -= splits * 8
        score -= islands * 5

        # Via stitching (20% weight)
        required = self._get_required_via_density(max_freq_mhz)
        if via_density < required:
            ratio = via_density / required if required > 0 else 0
            score -= (1 - ratio) * 20

        # Plane impedance (10% weight)
        if plane_impedance > 0.5:
            score -= min(10, (plane_impedance - 0.5) * 5)

        return max(0, min(100, score))

    def _get_required_via_density(self, max_freq_mhz: float) -> float:
        """Get required via stitching density for frequency."""
        if max_freq_mhz < 100:
            return self.STITCHING_RECOMMENDATIONS["low_speed"]
        elif max_freq_mhz < 1000:
            return self.STITCHING_RECOMMENDATIONS["medium_speed"]
        elif max_freq_mhz < 5000:
            return self.STITCHING_RECOMMENDATIONS["high_speed"]
        else:
            return self.STITCHING_RECOMMENDATIONS["very_high_speed"]

    def analyze_signal_crossings(
        self,
        crossings: List[SignalCrossing],
        planes: List[GroundPlane],
    ) -> Dict[str, Any]:
        """
        Analyze signals crossing ground plane discontinuities.

        Args:
            crossings: List of signal crossings
            planes: Ground plane definitions

        Returns:
            Analysis of crossing risks
        """
        high_risk = []
        medium_risk = []
        low_risk = []

        for crossing in crossings:
            risk = self._assess_crossing_risk(crossing)
            crossing_info = {
                "net": crossing.net_name,
                "layer": crossing.layer,
                "type": crossing.crossing_type,
                "signal_type": crossing.signal_type,
                "location": crossing.crossing_location,
            }

            if risk == "high":
                high_risk.append(crossing_info)
            elif risk == "medium":
                medium_risk.append(crossing_info)
            else:
                low_risk.append(crossing_info)

        recommendations = []
        if high_risk:
            recommendations.append("Re-route high-risk signals to avoid splits")
            recommendations.append("Add stitching capacitors for signals that must cross")

        if any(c["signal_type"] == "clock" for c in high_risk):
            recommendations.append("CRITICAL: Clock signals should never cross split planes")

        return {
            "total_crossings": len(crossings),
            "high_risk": high_risk,
            "medium_risk": medium_risk,
            "low_risk": low_risk,
            "high_risk_count": len(high_risk),
            "recommendations": recommendations,
        }

    def _assess_crossing_risk(self, crossing: SignalCrossing) -> str:
        """Assess risk level of a signal crossing."""
        # High risk signals crossing splits
        if crossing.crossing_type == "split":
            if crossing.signal_type in ("clock", "high_speed"):
                return "high"
            elif crossing.signal_type in ("data", "analog"):
                return "medium"
            else:
                return "low"

        # Voids/antipads
        if crossing.crossing_type == "void":
            if crossing.signal_type == "clock":
                return "medium"
            return "low"

        return "low"

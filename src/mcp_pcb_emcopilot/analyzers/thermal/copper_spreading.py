"""
Copper Spreading Analyzer.

Analyzes copper plane heat spreading effectiveness
for thermal management.
"""
import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SpreadingAnalysis:
    """Heat spreading analysis for a component."""
    component_ref: str
    component_power_w: float
    source_area_mm2: float

    # Spreading copper characteristics
    copper_layer: str
    copper_area_mm2: float
    copper_thickness_mm: float

    # Spreading effectiveness
    spreading_ratio: float  # copper_area / source_area
    estimated_spreading_resistance_c_per_w: float
    estimated_temp_reduction_percent: float

    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "component_ref": self.component_ref,
            "component_power_w": round(self.component_power_w, 2),
            "source_area_mm2": round(self.source_area_mm2, 1),
            "copper_layer": self.copper_layer,
            "copper_area_mm2": round(self.copper_area_mm2, 1),
            "copper_thickness_mm": round(self.copper_thickness_mm, 4),
            "spreading_ratio": round(self.spreading_ratio, 1),
            "estimated_spreading_resistance_c_per_w": round(self.estimated_spreading_resistance_c_per_w, 2),
            "estimated_temp_reduction_percent": round(self.estimated_temp_reduction_percent, 1),
            "issues": self.issues,
        }


@dataclass
class CopperSpreadingResult:
    """Result of copper spreading analysis."""
    analyses: list[SpreadingAnalysis] = field(default_factory=list)
    total_spreading_area_mm2: float = 0.0
    average_spreading_effectiveness_percent: float = 0.0
    issues: list[str] = field(default_factory=list)
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "analyses": [a.to_dict() for a in self.analyses],
            "total_spreading_area_mm2": round(self.total_spreading_area_mm2, 1),
            "average_spreading_effectiveness_percent": round(self.average_spreading_effectiveness_percent, 1),
            "issues": self.issues,
            "score": round(self.score, 1),
        }


class CopperSpreadingAnalyzer:
    """
    Copper plane heat spreading analyzer.

    Evaluates how effectively copper planes spread heat
    from high-power components.

    The spreading resistance model is based on simplified
    thermal spreading theory for thin plates.

    Usage:
        analyzer = CopperSpreadingAnalyzer()
        result = analyzer.analyze(
            components=[
                {
                    "ref": "U1",
                    "power_w": 3.0,
                    "footprint_area_mm2": 100,
                    "connected_copper": [
                        {"layer": "L2_GND", "area_mm2": 2500, "thickness_mm": 0.035},
                    ],
                },
            ],
        )
    """

    # Thermal conductivity of copper (W/m·K)
    COPPER_K = 385

    # Thermal conductivity of FR4 (W/m·K)
    FR4_K = 0.3

    def __init__(
        self,
        min_spreading_ratio: float = 10.0,
        good_spreading_ratio: float = 25.0,
    ):
        """
        Initialize analyzer.

        Args:
            min_spreading_ratio: Minimum acceptable spreading ratio
            good_spreading_ratio: Good spreading ratio target
        """
        self.min_ratio = min_spreading_ratio
        self.good_ratio = good_spreading_ratio

    def calculate_spreading_resistance(
        self,
        source_radius_m: float,
        spread_radius_m: float,
        copper_thickness_m: float,
    ) -> float:
        """
        Calculate thermal spreading resistance.

        Uses simplified model for thin plate spreading:
        R_sp = 1 / (π * k * t) * (1/r_source - 1/r_spread)

        Args:
            source_radius_m: Heat source radius in meters
            spread_radius_m: Spreading area radius in meters
            copper_thickness_m: Copper thickness in meters

        Returns:
            Spreading resistance in °C/W
        """
        if spread_radius_m <= source_radius_m:
            return 0.0

        # Simplified spreading resistance formula
        r_sp = (1 / (math.pi * self.COPPER_K * copper_thickness_m)) * \
               (1 / source_radius_m - 1 / spread_radius_m)

        return max(0.0, r_sp)

    def estimate_temp_reduction(
        self,
        spreading_ratio: float,
    ) -> float:
        """
        Estimate temperature reduction from spreading.

        Based on empirical data showing that larger spreading
        areas reduce peak temperature.

        Args:
            spreading_ratio: Ratio of spread area to source area

        Returns:
            Estimated temperature reduction percentage
        """
        if spreading_ratio <= 1:
            return 0.0

        # Logarithmic relationship between spreading and temp reduction
        # A 10x spreading ratio gives ~30% reduction
        # A 100x spreading ratio gives ~50% reduction
        reduction = 15 * math.log10(spreading_ratio)
        return min(60.0, reduction)  # Cap at 60%

    def analyze_component(
        self,
        component_ref: str,
        power_w: float,
        footprint_area_mm2: float,
        connected_copper: list[dict],
    ) -> SpreadingAnalysis:
        """
        Analyze heat spreading for a single component.

        Args:
            component_ref: Component reference
            power_w: Power dissipation
            footprint_area_mm2: Component footprint area
            connected_copper: List of connected copper areas

        Returns:
            SpreadingAnalysis result
        """
        issues = []

        # Calculate total spreading copper
        total_copper_area = sum(c.get("area_mm2", 0) for c in connected_copper)
        avg_thickness = 0.035  # Default 1oz

        if connected_copper:
            avg_thickness = sum(
                c.get("thickness_mm", 0.035) * c.get("area_mm2", 0)
                for c in connected_copper
            ) / total_copper_area if total_copper_area > 0 else 0.035

        # Calculate spreading ratio
        spreading_ratio = total_copper_area / footprint_area_mm2 if footprint_area_mm2 > 0 else 0

        # Calculate spreading resistance
        source_radius = math.sqrt(footprint_area_mm2 / math.pi) / 1000  # Convert to meters
        spread_radius = math.sqrt(total_copper_area / math.pi) / 1000
        thickness_m = avg_thickness / 1000

        r_sp = self.calculate_spreading_resistance(source_radius, spread_radius, thickness_m)

        # Estimate temperature reduction
        temp_reduction = self.estimate_temp_reduction(spreading_ratio)

        # Check for issues
        if spreading_ratio < self.min_ratio and power_w > 0.5:
            issues.append(
                f"Low spreading ratio ({spreading_ratio:.1f}x) for {power_w}W component"
            )

        if total_copper_area < footprint_area_mm2 * 5:
            issues.append("Limited copper connection for heat spreading")

        # Determine primary layer
        primary_layer = "none"
        if connected_copper:
            primary = max(connected_copper, key=lambda x: x.get("area_mm2", 0))
            primary_layer = primary.get("layer", "unknown")

        return SpreadingAnalysis(
            component_ref=component_ref,
            component_power_w=power_w,
            source_area_mm2=footprint_area_mm2,
            copper_layer=primary_layer,
            copper_area_mm2=total_copper_area,
            copper_thickness_mm=avg_thickness,
            spreading_ratio=spreading_ratio,
            estimated_spreading_resistance_c_per_w=r_sp,
            estimated_temp_reduction_percent=temp_reduction,
            issues=issues,
        )

    def analyze(
        self,
        components: list[dict],
    ) -> CopperSpreadingResult:
        """
        Analyze copper spreading for all components.

        Args:
            components: List of component specs with copper connection data

        Returns:
            CopperSpreadingResult with analysis
        """
        analyses = []
        all_issues = []
        total_area = 0.0
        total_effectiveness = 0.0

        for comp in components:
            ref = comp.get("ref", "?")
            power = comp.get("power_w", 0)
            footprint = comp.get("footprint_area_mm2", 0)
            copper = comp.get("connected_copper", [])

            # Only analyze components with significant power
            if power > 0.1:
                analysis = self.analyze_component(ref, power, footprint, copper)
                analyses.append(analysis)
                all_issues.extend(analysis.issues)
                total_area += analysis.copper_area_mm2
                total_effectiveness += analysis.estimated_temp_reduction_percent

        avg_effectiveness = total_effectiveness / len(analyses) if analyses else 0

        # Add global issues
        if avg_effectiveness < 20:
            all_issues.append("Overall copper spreading is limited")

        score = self._calculate_score(analyses, all_issues)

        return CopperSpreadingResult(
            analyses=analyses,
            total_spreading_area_mm2=total_area,
            average_spreading_effectiveness_percent=avg_effectiveness,
            issues=all_issues,
            score=score,
        )

    def _calculate_score(
        self,
        analyses: list[SpreadingAnalysis],
        issues: list[str],
    ) -> float:
        """Calculate copper spreading score."""
        score = 100.0

        # Deduct for issues
        score -= len(issues) * 5

        # Deduct for poor spreading
        for a in analyses:
            if a.spreading_ratio < self.min_ratio and a.component_power_w > 0.5:
                score -= 10
            elif a.spreading_ratio < self.good_ratio and a.component_power_w > 1.0:
                score -= 5

        # Bonus for good spreading
        good_spreading = sum(1 for a in analyses if a.spreading_ratio >= self.good_ratio)
        score = min(100, score + good_spreading * 3)

        return max(0.0, score)

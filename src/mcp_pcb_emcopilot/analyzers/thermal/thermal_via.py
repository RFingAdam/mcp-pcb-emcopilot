"""
Thermal Via Analyzer.

Analyzes thermal via structures for heat dissipation:
- Via count and density
- Via sizing
- Thermal resistance estimation
"""
import math
from dataclasses import dataclass, field
from typing import Optional


class ThermalViaIssueType:
    """Types of thermal via issues."""
    INSUFFICIENT_COUNT = "insufficient_count"
    POOR_PLACEMENT = "poor_placement"
    WRONG_SIZE = "wrong_size"
    NO_PLANE_CONNECTION = "no_plane_connection"
    MISSING_THERMAL_VIAS = "missing_thermal_vias"


@dataclass
class ThermalViaIssue:
    """A thermal via issue."""
    issue_type: str
    severity: str
    description: str
    component_ref: Optional[str] = None
    recommendation: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "issue_type": self.issue_type,
            "severity": self.severity,
            "description": self.description,
            "component_ref": self.component_ref,
            "recommendation": self.recommendation,
        }


@dataclass
class ThermalViaAnalysis:
    """Analysis of thermal vias for a component."""
    component_ref: str
    pad_area_mm2: float
    via_count: int
    via_diameter_mm: float
    via_pitch_mm: float
    estimated_thermal_resistance_c_per_w: float
    coverage_percent: float
    issues: list[ThermalViaIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "component_ref": self.component_ref,
            "pad_area_mm2": round(self.pad_area_mm2, 2),
            "via_count": self.via_count,
            "via_diameter_mm": round(self.via_diameter_mm, 3),
            "via_pitch_mm": round(self.via_pitch_mm, 2),
            "estimated_thermal_resistance_c_per_w": round(self.estimated_thermal_resistance_c_per_w, 1),
            "coverage_percent": round(self.coverage_percent, 1),
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass
class ThermalViaResult:
    """Result of thermal via analysis."""
    components_analyzed: list[ThermalViaAnalysis] = field(default_factory=list)
    components_missing_thermal_vias: list[str] = field(default_factory=list)
    issues: list[ThermalViaIssue] = field(default_factory=list)
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "components_analyzed": [c.to_dict() for c in self.components_analyzed],
            "components_missing_thermal_vias": self.components_missing_thermal_vias,
            "issues": [i.to_dict() for i in self.issues],
            "score": round(self.score, 1),
        }


class ThermalViaAnalyzer:
    """
    Thermal via structure analyzer.

    Analyzes thermal vias for heat dissipation from
    components with exposed pads.

    Usage:
        analyzer = ThermalViaAnalyzer()
        result = analyzer.analyze(
            components=[
                {
                    "ref": "U1",
                    "pad_area_mm2": 25.0,
                    "power_w": 3.0,
                    "vias": [
                        {"diameter_mm": 0.3, "count": 16},
                    ],
                },
            ],
        )
    """

    # Copper thermal conductivity (W/m·K)
    COPPER_K = 385

    def __init__(
        self,
        min_via_density_per_mm2: float = 0.5,
        max_via_thermal_resistance: float = 10.0,
        copper_thickness_mm: float = 0.035,
    ):
        """
        Initialize analyzer.

        Args:
            min_via_density_per_mm2: Minimum via density
            max_via_thermal_resistance: Maximum acceptable thermal resistance
            copper_thickness_mm: Copper thickness (1oz = 0.035mm)
        """
        self.min_density = min_via_density_per_mm2
        self.max_thermal_r = max_via_thermal_resistance
        self.copper_thickness = copper_thickness_mm

    def calculate_via_thermal_resistance(
        self,
        via_diameter_mm: float,
        via_plating_mm: float = 0.025,
        board_thickness_mm: float = 1.6,
        via_filled: bool = False,
    ) -> float:
        """
        Calculate thermal resistance of a single via.

        For a plated-through hole:
        R_th = L / (k * A)

        Where:
        - L = via length (board thickness)
        - k = thermal conductivity of copper
        - A = cross-sectional area of copper annulus

        Args:
            via_diameter_mm: Via drill diameter
            via_plating_mm: Copper plating thickness
            board_thickness_mm: PCB thickness
            via_filled: Whether via is copper-filled

        Returns:
            Thermal resistance in °C/W
        """
        outer_r = via_diameter_mm / 2
        inner_r = outer_r - via_plating_mm

        if via_filled:
            # Filled via: full copper area
            area = math.pi * outer_r ** 2
        else:
            # Plated via: annular copper ring
            area = math.pi * (outer_r ** 2 - inner_r ** 2)

        # Convert to meters
        area_m2 = area * 1e-6
        length_m = board_thickness_mm * 1e-3

        # R = L / (k * A)
        thermal_r = length_m / (self.COPPER_K * area_m2)

        return thermal_r

    def analyze_component(
        self,
        component_ref: str,
        pad_area_mm2: float,
        power_w: float,
        vias: list[dict],
        board_thickness_mm: float = 1.6,
    ) -> ThermalViaAnalysis:
        """
        Analyze thermal vias for a single component.

        Args:
            component_ref: Component reference
            pad_area_mm2: Exposed pad area
            power_w: Power dissipation
            vias: List of via specs {diameter_mm, count, filled}
            board_thickness_mm: PCB thickness

        Returns:
            ThermalViaAnalysis result
        """
        issues = []
        total_via_count = 0
        total_via_area = 0.0
        min_r = float("inf")
        avg_diameter = 0.0

        for via_spec in vias:
            diameter = via_spec.get("diameter_mm", 0.3)
            count = via_spec.get("count", 0)
            filled = via_spec.get("filled", False)

            total_via_count += count
            total_via_area += count * math.pi * (diameter / 2) ** 2
            avg_diameter = diameter  # Use last diameter as representative

            # Calculate thermal resistance of this via
            via_r = self.calculate_via_thermal_resistance(
                diameter, board_thickness_mm=board_thickness_mm, via_filled=filled
            )

            if count > 0:
                # Parallel vias reduce thermal resistance
                effective_r = via_r / count
                if effective_r < min_r:
                    min_r = effective_r

        # Calculate coverage and density
        coverage = (total_via_area / pad_area_mm2 * 100) if pad_area_mm2 > 0 else 0
        density = total_via_count / pad_area_mm2 if pad_area_mm2 > 0 else 0

        # Estimate pitch (assuming square array)
        if total_via_count > 1:
            pitch = math.sqrt(pad_area_mm2 / total_via_count)
        else:
            pitch = 0.0

        # Check for issues
        if total_via_count == 0:
            issues.append(ThermalViaIssue(
                issue_type=ThermalViaIssueType.MISSING_THERMAL_VIAS,
                severity="critical" if power_w > 0.5 else "high",
                description=f"{component_ref} has no thermal vias under exposed pad",
                component_ref=component_ref,
                recommendation="Add thermal vias in a grid pattern",
            ))
            min_r = float("inf")
        else:
            if density < self.min_density:
                issues.append(ThermalViaIssue(
                    issue_type=ThermalViaIssueType.INSUFFICIENT_COUNT,
                    severity="high",
                    description=f"{component_ref} thermal via density {density:.2f}/mm² is low",
                    component_ref=component_ref,
                    recommendation=f"Add more vias (target >{self.min_density}/mm²)",
                ))

            if min_r < float("inf") and min_r > self.max_thermal_r:
                temp_rise = power_w * min_r
                issues.append(ThermalViaIssue(
                    issue_type=ThermalViaIssueType.WRONG_SIZE,
                    severity="medium",
                    description=f"{component_ref} thermal resistance ~{min_r:.1f}°C/W (ΔT≈{temp_rise:.0f}°C)",
                    component_ref=component_ref,
                    recommendation="Use larger or filled vias, or increase count",
                ))

        return ThermalViaAnalysis(
            component_ref=component_ref,
            pad_area_mm2=pad_area_mm2,
            via_count=total_via_count,
            via_diameter_mm=avg_diameter,
            via_pitch_mm=pitch,
            estimated_thermal_resistance_c_per_w=min_r if min_r < float("inf") else 0,
            coverage_percent=coverage,
            issues=issues,
        )

    def analyze(
        self,
        components: list[dict],
        board_thickness_mm: float = 1.6,
    ) -> ThermalViaResult:
        """
        Analyze thermal vias for all components.

        Args:
            components: List of component specs with thermal pad info
            board_thickness_mm: PCB thickness

        Returns:
            ThermalViaResult with analysis
        """
        analyzed = []
        all_issues = []
        missing = []

        for comp in components:
            ref = comp.get("ref", "?")
            pad_area = comp.get("pad_area_mm2", 0)
            power = comp.get("power_w", 0)
            vias = comp.get("vias", [])

            # Only analyze if component has exposed pad
            if pad_area > 0:
                analysis = self.analyze_component(
                    ref, pad_area, power, vias, board_thickness_mm
                )
                analyzed.append(analysis)
                all_issues.extend(analysis.issues)

                if analysis.via_count == 0:
                    missing.append(ref)

        score = self._calculate_score(all_issues, analyzed)

        return ThermalViaResult(
            components_analyzed=analyzed,
            components_missing_thermal_vias=missing,
            issues=all_issues,
            score=score,
        )

    def _calculate_score(
        self,
        issues: list[ThermalViaIssue],
        analyzed: list[ThermalViaAnalysis],
    ) -> float:
        """Calculate thermal via score."""
        score = 100.0

        for issue in issues:
            if issue.severity == "critical":
                score -= 25
            elif issue.severity == "high":
                score -= 15
            elif issue.severity == "medium":
                score -= 8
            else:
                score -= 3

        # Bonus for good coverage
        good_coverage = sum(1 for a in analyzed if a.coverage_percent > 20)
        score = min(100, score + good_coverage * 2)

        return max(0.0, score)

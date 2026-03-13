"""
Power Plane Analyzer.

Analyzes power and ground plane integrity:
- Plane splits and gaps
- Via stitching adequacy
- Plane resonance
- Return path continuity
- Copper coverage
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PlaneIssueType(str, Enum):
    """Types of power plane issues."""
    PLANE_SPLIT = "plane_split"
    INSUFFICIENT_STITCHING = "insufficient_stitching"
    LARGE_VOID = "large_void"
    NARROW_NECK = "narrow_neck"
    RESONANCE_RISK = "resonance_risk"
    RETURN_PATH_DISCONTINUITY = "return_path_discontinuity"
    LOW_COPPER_COVERAGE = "low_copper_coverage"
    ANTI_PAD_CLEARANCE = "anti_pad_clearance"


@dataclass
class PlaneIssue:
    """A power plane issue."""
    issue_type: PlaneIssueType
    severity: str
    description: str
    location: Optional[tuple[float, float]] = None
    affected_signals: list[str] = field(default_factory=list)
    recommendation: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "issue_type": self.issue_type.value,
            "severity": self.severity,
            "description": self.description,
            "location": self.location,
            "affected_signals": self.affected_signals,
            "recommendation": self.recommendation,
        }


@dataclass
class PlaneSplit:
    """A split or gap in a plane."""
    start_point: tuple[float, float]
    end_point: tuple[float, float]
    width_mm: float
    length_mm: float
    affected_signals: list[str] = field(default_factory=list)
    is_intentional: bool = False

    def to_dict(self) -> dict:
        return {
            "start_point": self.start_point,
            "end_point": self.end_point,
            "width_mm": round(self.width_mm, 3),
            "length_mm": round(self.length_mm, 2),
            "affected_signals": self.affected_signals,
            "is_intentional": self.is_intentional,
        }


@dataclass
class PlaneVoid:
    """A void or cutout in a plane."""
    center: tuple[float, float]
    area_mm2: float
    cause: str  # via_antipad, component_clearance, routing_channel, intentional
    affected_signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "center": self.center,
            "area_mm2": round(self.area_mm2, 2),
            "cause": self.cause,
            "affected_signals": self.affected_signals,
        }


@dataclass
class PowerPlaneResult:
    """Result of power plane analysis."""
    layer_name: str
    plane_type: str  # power, ground, mixed
    net_name: str

    # Geometry
    total_area_mm2: float = 0.0
    copper_area_mm2: float = 0.0
    copper_coverage_percent: float = 0.0

    # Splits and voids
    splits: list[PlaneSplit] = field(default_factory=list)
    voids: list[PlaneVoid] = field(default_factory=list)
    narrow_necks: list[tuple[tuple[float, float], float]] = field(default_factory=list)

    # Stitching analysis
    stitching_via_count: int = 0
    stitching_density_per_cm2: float = 0.0
    stitching_adequate: bool = True

    # Resonance analysis
    first_resonance_freq_hz: float = 0.0
    resonance_risk: str = "low"  # low, medium, high

    # Issues
    issues: list[PlaneIssue] = field(default_factory=list)
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "layer_name": self.layer_name,
            "plane_type": self.plane_type,
            "net_name": self.net_name,
            "total_area_mm2": round(self.total_area_mm2, 2),
            "copper_area_mm2": round(self.copper_area_mm2, 2),
            "copper_coverage_percent": round(self.copper_coverage_percent, 1),
            "splits": [s.to_dict() for s in self.splits],
            "voids": [v.to_dict() for v in self.voids],
            "narrow_necks": self.narrow_necks,
            "stitching_via_count": self.stitching_via_count,
            "stitching_density_per_cm2": round(self.stitching_density_per_cm2, 2),
            "stitching_adequate": self.stitching_adequate,
            "first_resonance_freq_hz": self.first_resonance_freq_hz,
            "resonance_risk": self.resonance_risk,
            "issues": [i.to_dict() for i in self.issues],
            "score": round(self.score, 1),
        }


class PowerPlaneAnalyzer:
    """
    Power and ground plane integrity analyzer.

    Analyzes plane structures for:
    - Splits that affect return paths
    - Voids that increase impedance
    - Via stitching for EMC
    - Resonance risks
    - Copper coverage

    Usage:
        analyzer = PowerPlaneAnalyzer()
        result = analyzer.analyze_plane(
            layer_name="GND",
            plane_type="ground",
            net_name="GND",
            board_outline=[(0, 0), (100, 0), (100, 80), (0, 80)],
            plane_polygons=[...],
            vias=[...],
            crossing_signals=["CLK", "DATA0", "DATA1"],
        )
    """

    # Speed of light for resonance calculations
    C0 = 299792458  # m/s

    def __init__(
        self,
        min_copper_coverage: float = 70.0,
        min_stitching_density: float = 4.0,
        max_void_area_mm2: float = 25.0,
        min_neck_width_mm: float = 0.5,
    ):
        """
        Initialize analyzer.

        Args:
            min_copper_coverage: Minimum acceptable copper coverage (%)
            min_stitching_density: Minimum stitching vias per cm²
            max_void_area_mm2: Maximum acceptable void area
            min_neck_width_mm: Minimum acceptable neck width
        """
        self.min_copper_coverage = min_copper_coverage
        self.min_stitching_density = min_stitching_density
        self.max_void_area = max_void_area_mm2
        self.min_neck_width = min_neck_width_mm

    def calculate_polygon_area(
        self,
        vertices: list[tuple[float, float]],
    ) -> float:
        """
        Calculate area of a polygon using shoelace formula.

        Args:
            vertices: List of (x, y) vertices

        Returns:
            Area in mm²
        """
        n = len(vertices)
        if n < 3:
            return 0.0

        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            area += vertices[i][0] * vertices[j][1]
            area -= vertices[j][0] * vertices[i][1]

        return abs(area) / 2.0

    def calculate_plane_resonance(
        self,
        length_mm: float,
        width_mm: float,
        dielectric_constant: float = 4.3,
    ) -> float:
        """
        Calculate first resonance frequency of rectangular plane.

        f_res = c / (2 * sqrt(εr) * sqrt(L² + W²))

        Args:
            length_mm: Plane length in mm
            width_mm: Plane width in mm
            dielectric_constant: Relative permittivity

        Returns:
            First resonance frequency in Hz
        """
        length_m = length_mm / 1000
        width_m = width_mm / 1000
        diagonal = math.sqrt(length_m ** 2 + width_m ** 2)
        
        f_res = self.C0 / (2 * math.sqrt(dielectric_constant) * diagonal)
        return f_res

    def analyze_split_impact(
        self,
        split: PlaneSplit,
        crossing_signals: list[str],
        max_frequency_hz: float = 1e9,
    ) -> PlaneIssue:
        """
        Analyze the impact of a plane split on signals.

        Args:
            split: The plane split
            crossing_signals: Signals that cross the split
            max_frequency_hz: Maximum signal frequency

        Returns:
            PlaneIssue describing the impact
        """
        # Slot antenna resonance frequency
        slot_length = split.length_mm / 1000  # Convert to meters
        slot_resonance = self.C0 / (2 * slot_length)

        severity = "low"
        if split.affected_signals:
            if len(split.affected_signals) > 5:
                severity = "high"
            elif len(split.affected_signals) > 2:
                severity = "medium"

        if slot_resonance < max_frequency_hz:
            severity = "high" if severity != "high" else "critical"

        return PlaneIssue(
            issue_type=PlaneIssueType.PLANE_SPLIT,
            severity=severity,
            description=f"Plane split {split.length_mm:.1f}mm long affects {len(split.affected_signals)} signals",
            location=split.start_point,
            affected_signals=split.affected_signals,
            recommendation="Add stitching capacitors across split or reroute affected signals",
        )

    def analyze_plane(
        self,
        layer_name: str,
        plane_type: str,
        net_name: str,
        board_outline: list[tuple[float, float]],
        plane_polygons: Optional[list[list[tuple[float, float]]]] = None,
        vias: Optional[list[dict]] = None,
        splits: Optional[list[dict]] = None,
        voids: Optional[list[dict]] = None,
        crossing_signals: Optional[list[str]] = None,
        dielectric_constant: float = 4.3,
        max_signal_frequency_hz: float = 1e9,
    ) -> PowerPlaneResult:
        """
        Analyze a power or ground plane.

        Args:
            layer_name: Layer name
            plane_type: "power", "ground", or "mixed"
            net_name: Net name (GND, VCC, etc.)
            board_outline: Board outline vertices
            plane_polygons: List of plane polygon vertices
            vias: List of vias with position
            splits: List of known splits
            voids: List of known voids
            crossing_signals: Signals that cross this plane
            dielectric_constant: Dielectric Er
            max_signal_frequency_hz: Maximum signal frequency

        Returns:
            PowerPlaneResult with analysis
        """
        issues = []
        crossing_signals = crossing_signals or []

        # Calculate board area
        total_area = self.calculate_polygon_area(board_outline)

        # Calculate copper area
        copper_area = 0.0
        if plane_polygons:
            for poly in plane_polygons:
                copper_area += self.calculate_polygon_area(poly)
        else:
            # Assume high coverage if not specified
            copper_area = total_area * 0.85

        coverage = (copper_area / total_area * 100) if total_area > 0 else 0

        # Analyze splits
        analyzed_splits = []
        if splits:
            for s in splits:
                split = PlaneSplit(
                    start_point=s.get("start", (0, 0)),
                    end_point=s.get("end", (0, 0)),
                    width_mm=s.get("width", 0.5),
                    length_mm=s.get("length", 10.0),
                    affected_signals=s.get("signals", []),
                    is_intentional=s.get("intentional", False),
                )
                analyzed_splits.append(split)

                if not split.is_intentional:
                    issue = self.analyze_split_impact(split, crossing_signals, max_signal_frequency_hz)
                    issues.append(issue)

        # Analyze voids
        analyzed_voids = []
        if voids:
            for v in voids:
                void = PlaneVoid(
                    center=v.get("center", (0, 0)),
                    area_mm2=v.get("area", 0),
                    cause=v.get("cause", "unknown"),
                    affected_signals=v.get("signals", []),
                )
                analyzed_voids.append(void)

                if void.area_mm2 > self.max_void_area:
                    issues.append(PlaneIssue(
                        issue_type=PlaneIssueType.LARGE_VOID,
                        severity="medium",
                        description=f"Large void {void.area_mm2:.1f}mm² at {void.center}",
                        location=void.center,
                        affected_signals=void.affected_signals,
                        recommendation="Fill void with copper or reroute affected signals",
                    ))

        # Analyze stitching vias
        stitching_count = 0
        if vias:
            for via in vias:
                if via.get("net") == net_name or via.get("type") == "stitching":
                    stitching_count += 1

        # Calculate stitching density (vias per cm²)
        stitching_density = stitching_count / (total_area / 100) if total_area > 0 else 0
        stitching_adequate = stitching_density >= self.min_stitching_density

        if not stitching_adequate and plane_type == "ground":
            issues.append(PlaneIssue(
                issue_type=PlaneIssueType.INSUFFICIENT_STITCHING,
                severity="medium",
                description=f"Ground stitching density {stitching_density:.1f}/cm² is below recommended {self.min_stitching_density}/cm²",
                recommendation="Add more ground stitching vias, especially near board edges and high-speed signals",
            ))

        # Calculate plane resonance
        # Estimate dimensions from board outline
        xs = [p[0] for p in board_outline]
        ys = [p[1] for p in board_outline]
        length = max(xs) - min(xs)
        width = max(ys) - min(ys)

        first_resonance = self.calculate_plane_resonance(length, width, dielectric_constant)

        resonance_risk = "low"
        if first_resonance < max_signal_frequency_hz:
            resonance_risk = "high"
            issues.append(PlaneIssue(
                issue_type=PlaneIssueType.RESONANCE_RISK,
                severity="high",
                description=f"Plane resonance at {first_resonance/1e9:.2f} GHz is within signal bandwidth",
                recommendation="Add stitching vias or plane-pair capacitors to damp resonance",
            ))
        elif first_resonance < max_signal_frequency_hz * 2:
            resonance_risk = "medium"

        # Check copper coverage
        if coverage < self.min_copper_coverage:
            issues.append(PlaneIssue(
                issue_type=PlaneIssueType.LOW_COPPER_COVERAGE,
                severity="medium",
                description=f"Copper coverage {coverage:.1f}% is below recommended {self.min_copper_coverage}%",
                recommendation="Reduce routing on this layer or add copper fill",
            ))

        # Calculate score
        score = self._calculate_score(
            issues, coverage, stitching_adequate, resonance_risk
        )

        return PowerPlaneResult(
            layer_name=layer_name,
            plane_type=plane_type,
            net_name=net_name,
            total_area_mm2=total_area,
            copper_area_mm2=copper_area,
            copper_coverage_percent=coverage,
            splits=analyzed_splits,
            voids=analyzed_voids,
            stitching_via_count=stitching_count,
            stitching_density_per_cm2=stitching_density,
            stitching_adequate=stitching_adequate,
            first_resonance_freq_hz=first_resonance,
            resonance_risk=resonance_risk,
            issues=issues,
            score=score,
        )

    def _calculate_score(
        self,
        issues: list[PlaneIssue],
        coverage: float,
        stitching_ok: bool,
        resonance_risk: str,
    ) -> float:
        """Calculate plane quality score."""
        score = 100.0

        # Deduct for issues
        for issue in issues:
            if issue.severity == "critical":
                score -= 20
            elif issue.severity == "high":
                score -= 12
            elif issue.severity == "medium":
                score -= 6
            else:
                score -= 2

        # Coverage bonus/penalty
        if coverage >= 90:
            score = min(100, score + 5)
        elif coverage < 60:
            score -= 10

        # Stitching and resonance
        if not stitching_ok:
            score -= 5
        if resonance_risk == "high":
            score -= 10
        elif resonance_risk == "medium":
            score -= 5

        return max(0.0, score)

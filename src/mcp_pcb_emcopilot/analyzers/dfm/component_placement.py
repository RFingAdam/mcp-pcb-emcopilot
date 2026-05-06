"""Component placement analyzer for DFM"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class PlacementResult:
    """Results from component placement analysis"""
    # Board summary
    board_id: str
    total_components: int
    components_top: int
    components_bottom: int

    # Clearance analysis
    clearance_violations: int
    min_clearance_mm: float
    avg_clearance_mm: float

    # Orientation analysis
    orientation_issues: int
    mixed_orientations: bool

    # Keep-out violations
    keepout_violations: int

    # Assessment
    dfm_score: float  # 0-100
    risk_level: str  # low, medium, high, critical

    # Detailed violations
    violations: List[Dict[str, Any]] = field(default_factory=list)

    # Issues and recommendations
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    # Details
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Component:
    """Component placement definition"""
    reference: str
    package: str
    x_mm: float
    y_mm: float
    rotation_deg: float
    side: str  # top, bottom
    width_mm: float
    height_mm: float
    component_type: str = "smd"  # smd, pth, bga, connector


@dataclass
class KeepOut:
    """Keep-out zone definition"""
    name: str
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    zone_type: str = "component"  # component, via, routing, all


class PlacementAnalyzer:
    """
    Component placement analyzer for DFM.

    Analyzes:
    - Component-to-component clearances
    - Component orientations for wave solder
    - Keep-out zone violations
    - Panel edge clearances

    Based on IPC-7351 and assembly process requirements.
    """

    # Minimum clearances by component type (mm)
    MIN_CLEARANCES = {
        ("smd", "smd"): 0.5,
        ("smd", "pth"): 0.75,
        ("pth", "pth"): 1.0,
        ("smd", "bga"): 1.0,
        ("bga", "bga"): 1.5,
        ("smd", "connector"): 1.5,
        ("pth", "connector"): 2.0,
    }

    # Package-specific clearances
    PACKAGE_CLEARANCES = {
        "01005": 0.15,
        "0201": 0.2,
        "0402": 0.25,
        "0603": 0.3,
        "0805": 0.4,
        "1206": 0.5,
        "sot23": 0.5,
        "sot223": 0.75,
        "qfn": 0.5,
        "qfp": 0.75,
        "bga": 1.0,
        "soic": 0.5,
        "tssop": 0.4,
    }

    # Standard orientations for wave solder (degrees)
    WAVE_ORIENTATIONS = [0, 90, 180, 270]

    def __init__(self, process: str = "reflow"):
        """
        Initialize analyzer.

        Args:
            process: Assembly process (reflow, wave, mixed)
        """
        self.process = process

    def analyze_placement(
        self,
        components: List[Component],
        keepouts: Optional[List[KeepOut]] = None,
        board_width_mm: float = 100,
        board_height_mm: float = 100,
        board_id: str = "PCB1",
    ) -> PlacementResult:
        """
        Analyze component placement.

        Args:
            components: List of components
            keepouts: List of keep-out zones
            board_width_mm: Board width
            board_height_mm: Board height
            board_id: Board identifier

        Returns:
            PlacementResult with complete analysis
        """
        if keepouts is None:
            keepouts = []

        violations = []

        # Count by side
        top_count = sum(1 for c in components if c.side == "top")
        bottom_count = len(components) - top_count

        # Analyze clearances
        clearance_violations, min_clearance, clearances = self._analyze_clearances(
            components
        )
        avg_clearance = sum(clearances) / len(clearances) if clearances else 0

        # Analyze orientations
        orientation_issues, mixed_orientations = self._analyze_orientations(components)

        # Analyze keep-outs
        keepout_violations = self._analyze_keepouts(components, keepouts)

        # Analyze board edge clearance
        edge_violations = self._analyze_edge_clearance(
            components, board_width_mm, board_height_mm
        )

        # Combine all violations
        violations.extend([
            {"type": "clearance", **v} for v in clearance_violations
        ])
        violations.extend([
            {"type": "orientation", **v} for v in orientation_issues
        ])
        violations.extend([
            {"type": "keepout", **v} for v in keepout_violations
        ])
        violations.extend([
            {"type": "edge", **v} for v in edge_violations
        ])

        # Calculate score
        score = self._calculate_score(
            len(components),
            len([v for v in violations if v["type"] == "clearance"]),
            len([v for v in violations if v["type"] == "orientation"]),
            len([v for v in violations if v["type"] == "keepout"]),
        )

        # Risk level
        if score >= 80:
            risk_level = "low"
        elif score >= 60:
            risk_level = "medium"
        elif score >= 40:
            risk_level = "high"
        else:
            risk_level = "critical"

        # Generate issues and recommendations
        issues = []
        recommendations = []

        if clearance_violations:
            issues.append(f"{len(clearance_violations)} component clearance violation(s)")
            recommendations.append("Increase spacing between flagged components")

        if orientation_issues and self.process == "wave":
            issues.append(f"{len(orientation_issues)} non-standard orientation(s)")
            recommendations.append("Align components to 0/90/180/270° for wave solder")

        if mixed_orientations:
            issues.append("Mixed component orientations may affect inspection")
            recommendations.append("Consider standardizing component rotations")

        if keepout_violations:
            issues.append(f"{len(keepout_violations)} keep-out zone violation(s)")
            recommendations.append("Move components away from keep-out areas")

        if edge_violations:
            issues.append(f"{len(edge_violations)} board edge clearance violation(s)")
            recommendations.append("Move components away from board edges")

        # Process-specific recommendations
        if self.process == "wave" and bottom_count > 0:
            smd_on_bottom = sum(
                1 for c in components
                if c.side == "bottom" and c.component_type == "smd"
            )
            if smd_on_bottom > 0:
                issues.append(f"{smd_on_bottom} SMD component(s) on wave solder side")
                recommendations.append("Use wave-solderable SMD or move to top side")

        return PlacementResult(
            board_id=board_id,
            total_components=len(components),
            components_top=top_count,
            components_bottom=bottom_count,
            clearance_violations=len([v for v in violations if v["type"] == "clearance"]),
            min_clearance_mm=round(min_clearance, 3) if min_clearance < float('inf') else 0,
            avg_clearance_mm=round(avg_clearance, 3),
            orientation_issues=len([v for v in violations if v["type"] == "orientation"]),
            mixed_orientations=mixed_orientations,
            keepout_violations=len([v for v in violations if v["type"] == "keepout"]),
            dfm_score=round(score, 1),
            risk_level=risk_level,
            violations=violations,
            issues=issues,
            recommendations=recommendations,
            metrics={
                "process": self.process,
                "board_width_mm": board_width_mm,
                "board_height_mm": board_height_mm,
                "component_density": len(components) / (board_width_mm * board_height_mm) * 100,
            },
        )

    def _analyze_clearances(
        self,
        components: List[Component],
    ) -> Tuple[List[Dict], float, List[float]]:
        """Analyze component-to-component clearances."""
        violations = []
        min_clearance = float('inf')
        all_clearances = []

        for i, c1 in enumerate(components):
            for c2 in components[i + 1:]:
                # Skip if on different sides
                if c1.side != c2.side:
                    continue

                # Calculate clearance
                clearance = self._calculate_clearance(c1, c2)
                all_clearances.append(clearance)
                min_clearance = min(min_clearance, clearance)

                # Get minimum required clearance
                sorted_types = sorted([c1.component_type, c2.component_type])
                types: tuple[str, str] = (sorted_types[0], sorted_types[1])
                min_required = self.MIN_CLEARANCES.get(types, 0.5)

                # Also check package-specific clearances
                for pkg, pkg_clearance in self.PACKAGE_CLEARANCES.items():
                    if pkg in c1.package.lower() or pkg in c2.package.lower():
                        min_required = max(min_required, pkg_clearance)

                if clearance < min_required:
                    violations.append({
                        "component1": c1.reference,
                        "component2": c2.reference,
                        "clearance_mm": round(clearance, 3),
                        "required_mm": round(min_required, 3),
                        "deficit_mm": round(min_required - clearance, 3),
                    })

        return violations, min_clearance, all_clearances

    def _get_rotated_corners(self, c: Component) -> List[Tuple[float, float]]:
        """Get the four corners of a component accounting for rotation.

        Args:
            c: Component to get corners for

        Returns:
            List of (x, y) tuples for rotated corners in world coordinates
        """
        w2, h2 = c.width_mm / 2, c.height_mm / 2
        rad = math.radians(c.rotation_deg)
        cos_r, sin_r = math.cos(rad), math.sin(rad)

        # Corners in local coordinates
        corners = [
            (-w2, -h2), (w2, -h2), (w2, h2), (-w2, h2)
        ]

        # Transform to world coordinates
        rotated = []
        for x, y in corners:
            rx = x * cos_r - y * sin_r + c.x_mm
            ry = x * sin_r + y * cos_r + c.y_mm
            rotated.append((rx, ry))

        return rotated

    def _get_rotated_aabb(self, c: Component) -> Tuple[float, float, float, float]:
        """Get axis-aligned bounding box of rotated component.

        Args:
            c: Component to get AABB for

        Returns:
            Tuple (min_x, min_y, max_x, max_y) of bounding box
        """
        corners = self._get_rotated_corners(c)
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        return (min(xs), min(ys), max(xs), max(ys))

    def _separating_axis_test(
        self,
        corners1: List[Tuple[float, float]],
        corners2: List[Tuple[float, float]],
    ) -> Tuple[bool, float]:
        """Perform separating axis test between two rotated rectangles.

        Uses the Separating Axis Theorem (SAT) for accurate collision detection
        between rotated rectangles.

        Args:
            corners1: Corners of first rectangle
            corners2: Corners of second rectangle

        Returns:
            Tuple of (overlapping, min_distance)
            - overlapping: True if shapes overlap
            - min_distance: Minimum separation distance (negative if overlapping)
        """
        def get_axes(corners):
            """Get the two edge normals (axes) for a rectangle."""
            axes = []
            for i in range(len(corners)):
                edge = (
                    corners[(i + 1) % len(corners)][0] - corners[i][0],
                    corners[(i + 1) % len(corners)][1] - corners[i][1]
                )
                # Normal is perpendicular to edge
                length = math.sqrt(edge[0]**2 + edge[1]**2)
                if length > 0:
                    axes.append((-edge[1] / length, edge[0] / length))
            return axes

        def project(corners, axis):
            """Project all corners onto an axis."""
            dots = [c[0] * axis[0] + c[1] * axis[1] for c in corners]
            return min(dots), max(dots)

        # Get axes from both rectangles (only need 2 from each for rectangles)
        axes = get_axes(corners1[:2] + [corners1[2]]) + get_axes(corners2[:2] + [corners2[2]])

        min_overlap = float('inf')

        for axis in axes:
            min1, max1 = project(corners1, axis)
            min2, max2 = project(corners2, axis)

            # Check for gap
            if max1 < min2 or max2 < min1:
                # Separated - calculate gap
                gap = max(min2 - max1, min1 - max2)
                return False, gap

            # Calculate overlap
            overlap = min(max1, max2) - max(min1, min2)
            min_overlap = min(min_overlap, overlap)

        # All axes have overlap - shapes intersect
        return True, -min_overlap

    def _calculate_clearance(self, c1: Component, c2: Component) -> float:
        """Calculate clearance between two components.

        Uses proper rotated geometry for accurate clearance calculation.
        Falls back to AABB for simple cases.
        """
        # Get rotated corners for both components
        corners1 = self._get_rotated_corners(c1)
        corners2 = self._get_rotated_corners(c2)

        # Use separating axis test for accurate collision/gap detection
        overlapping, distance = self._separating_axis_test(corners1, corners2)

        if overlapping:
            return 0  # Components overlap

        # For separated components, calculate minimum distance
        # The SAT gives us the separation along axes, but we need actual clearance
        # Use AABB as a quick approximation for well-separated components
        aabb1 = self._get_rotated_aabb(c1)
        aabb2 = self._get_rotated_aabb(c2)

        # Calculate gap between AABBs
        dx = max(0, max(aabb1[0], aabb2[0]) - min(aabb1[2], aabb2[2]))
        dy = max(0, max(aabb1[1], aabb2[1]) - min(aabb1[3], aabb2[3]))

        if dx == 0 and dy == 0:
            return 0

        return math.sqrt(dx**2 + dy**2)

    def _analyze_orientations(
        self,
        components: List[Component],
    ) -> Tuple[List[Dict], bool]:
        """Analyze component orientations."""
        violations = []
        orientations_used = set()

        for c in components:
            # Normalize rotation to 0-360
            rotation = c.rotation_deg % 360
            orientations_used.add(round(rotation / 45) * 45)  # Round to nearest 45

            # Check for wave solder compatibility
            if self.process == "wave":
                if rotation not in self.WAVE_ORIENTATIONS:
                    violations.append({
                        "component": c.reference,
                        "rotation_deg": rotation,
                        "recommended_deg": min(
                            self.WAVE_ORIENTATIONS,
                            key=lambda x: abs(x - rotation)
                        ),
                    })

        # Check for mixed orientations
        mixed = len(orientations_used) > 2

        return violations, mixed

    def _analyze_keepouts(
        self,
        components: List[Component],
        keepouts: List[KeepOut],
    ) -> List[Dict]:
        """Analyze keep-out zone violations."""
        violations = []

        for c in components:
            for ko in keepouts:
                if ko.zone_type != "component" and ko.zone_type != "all":
                    continue

                # Check overlap
                if self._overlaps(c, ko):
                    violations.append({
                        "component": c.reference,
                        "keepout": ko.name,
                        "keepout_type": ko.zone_type,
                    })

        return violations

    def _overlaps(self, component: Component, keepout: KeepOut) -> bool:
        """Check if component overlaps with keep-out zone.

        Uses rotated component geometry for accurate collision detection.
        Keep-out zones are assumed to be axis-aligned rectangles.
        """
        # Get rotated corners of component
        comp_corners = self._get_rotated_corners(component)

        # Keep-out zone corners (axis-aligned)
        ko_corners = [
            (keepout.x_mm, keepout.y_mm),
            (keepout.x_mm + keepout.width_mm, keepout.y_mm),
            (keepout.x_mm + keepout.width_mm, keepout.y_mm + keepout.height_mm),
            (keepout.x_mm, keepout.y_mm + keepout.height_mm),
        ]

        # Use separating axis test for accurate overlap detection
        overlapping, _ = self._separating_axis_test(comp_corners, ko_corners)
        return overlapping

    def _analyze_edge_clearance(
        self,
        components: List[Component],
        board_width: float,
        board_height: float,
        min_edge_clearance: float = 2.0,
    ) -> List[Dict]:
        """Analyze board edge clearances using rotated component geometry.

        Properly accounts for component rotation when calculating distance
        to board edges.
        """
        violations = []

        for c in components:
            # Get rotated bounding box for accurate edge distance
            aabb = self._get_rotated_aabb(c)
            min_x, min_y, max_x, max_y = aabb

            # Calculate distance to each edge
            left = min_x  # Distance from left edge of board (at x=0)
            right = board_width - max_x  # Distance from right edge
            bottom = min_y  # Distance from bottom edge (at y=0)
            top = board_height - max_y  # Distance from top edge

            min_dist = min(left, right, bottom, top)

            # Identify which edge is violated
            violated_edge = None
            if min_dist < min_edge_clearance:
                if left == min_dist:
                    violated_edge = "left"
                elif right == min_dist:
                    violated_edge = "right"
                elif bottom == min_dist:
                    violated_edge = "bottom"
                else:
                    violated_edge = "top"

                violations.append({
                    "component": c.reference,
                    "min_edge_distance_mm": round(min_dist, 3),
                    "required_mm": min_edge_clearance,
                    "violated_edge": violated_edge,
                    "component_rotation_deg": c.rotation_deg,
                })

        return violations

    def _calculate_score(
        self,
        total_components: int,
        clearance_violations: int,
        orientation_issues: int,
        keepout_violations: int,
    ) -> float:
        """Calculate placement DFM score."""
        if total_components == 0:
            return 100

        score = 100.0

        # Clearance violations (most severe)
        violation_rate = clearance_violations / total_components
        score -= violation_rate * 50

        # Orientation issues (moderate)
        orientation_rate = orientation_issues / total_components
        score -= orientation_rate * 20

        # Keep-out violations (severe)
        keepout_rate = keepout_violations / total_components
        score -= keepout_rate * 40

        return max(0, min(100, score))

    def optimize_placement(
        self,
        components: List[Component],
        board_width_mm: float,
        board_height_mm: float,
    ) -> Dict[str, Any]:
        """
        Suggest placement optimizations.

        Args:
            components: Current component list
            board_width_mm: Board width
            board_height_mm: Board height

        Returns:
            Optimization suggestions
        """
        current_result = self.analyze_placement(
            components,
            board_width_mm=board_width_mm,
            board_height_mm=board_height_mm,
        )

        suggestions = []

        # Find clusters that could be spread out
        for violation in current_result.violations:
            if violation["type"] == "clearance":
                suggestions.append({
                    "action": "increase_spacing",
                    "components": [violation["component1"], violation["component2"]],
                    "current_mm": violation["clearance_mm"],
                    "target_mm": violation["required_mm"],
                })

        # Suggest orientation standardization
        if current_result.mixed_orientations:
            suggestions.append({
                "action": "standardize_orientations",
                "detail": "Consider aligning all similar components to same rotation",
            })

        return {
            "current_score": current_result.dfm_score,
            "total_violations": len(current_result.violations),
            "suggestions": suggestions,
            "priority_fixes": [
                v for v in current_result.violations
                if v["type"] == "clearance" and v.get("deficit_mm", 0) > 0.2
            ][:5],
        }


# Alias for consistent naming with other analyzers
ComponentPlacementAnalyzer = PlacementAnalyzer

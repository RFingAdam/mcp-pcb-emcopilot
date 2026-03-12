"""
Hotspot Detector.

Identifies thermal hotspots from clustered high-power components
and analyzes thermal coupling effects.
"""
import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Hotspot:
    """A thermal hotspot region."""
    center: tuple[float, float]
    radius_mm: float
    total_power_w: float
    component_count: int
    components: list[str]
    severity: str  # critical, high, medium, low
    estimated_temp_rise_c: float

    def to_dict(self) -> dict:
        return {
            "center": self.center,
            "radius_mm": round(self.radius_mm, 1),
            "total_power_w": round(self.total_power_w, 2),
            "component_count": self.component_count,
            "components": self.components,
            "severity": self.severity,
            "estimated_temp_rise_c": round(self.estimated_temp_rise_c, 1),
        }


@dataclass
class HotspotIssue:
    """A hotspot-related issue."""
    severity: str
    description: str
    location: tuple[float, float]
    components_involved: list[str]
    recommendation: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "description": self.description,
            "location": self.location,
            "components_involved": self.components_involved,
            "recommendation": self.recommendation,
        }


@dataclass
class HotspotResult:
    """Result of hotspot detection."""
    hotspots: list[Hotspot] = field(default_factory=list)
    total_hotspot_area_mm2: float = 0.0
    max_power_density_w_per_cm2: float = 0.0
    issues: list[HotspotIssue] = field(default_factory=list)
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "hotspots": [h.to_dict() for h in self.hotspots],
            "total_hotspot_area_mm2": round(self.total_hotspot_area_mm2, 1),
            "max_power_density_w_per_cm2": round(self.max_power_density_w_per_cm2, 2),
            "issues": [i.to_dict() for i in self.issues],
            "score": round(self.score, 1),
        }


class HotspotDetector:
    """
    Thermal hotspot detector using component clustering.

    Identifies regions where multiple power-dissipating components
    are concentrated, creating elevated temperatures.

    Usage:
        detector = HotspotDetector()
        result = detector.detect(
            components=[
                {"ref": "U1", "position": (50, 40), "power_w": 3.0},
                {"ref": "U2", "position": (52, 42), "power_w": 2.0},
                {"ref": "R5", "position": (48, 38), "power_w": 0.5},
            ],
        )
    """

    def __init__(
        self,
        min_cluster_power_w: float = 1.0,
        cluster_radius_mm: float = 15.0,
        critical_power_density_w_per_cm2: float = 5.0,
        high_power_density_w_per_cm2: float = 2.0,
    ):
        """
        Initialize detector.

        Args:
            min_cluster_power_w: Minimum power to form a hotspot
            cluster_radius_mm: Radius for clustering
            critical_power_density_w_per_cm2: Critical density threshold
            high_power_density_w_per_cm2: High density threshold
        """
        self.min_power = min_cluster_power_w
        self.cluster_radius = cluster_radius_mm
        self.critical_density = critical_power_density_w_per_cm2
        self.high_density = high_power_density_w_per_cm2

    def distance(self, p1: tuple[float, float], p2: tuple[float, float]) -> float:
        """Calculate Euclidean distance between two points."""
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    def cluster_components(
        self,
        components: list[dict],
    ) -> list[list[dict]]:
        """
        Cluster components by proximity using simple algorithm.

        Returns list of clusters, each containing component dicts.
        """
        if not components:
            return []

        remaining = list(components)
        clusters = []

        while remaining:
            # Start new cluster with first remaining component
            seed = remaining.pop(0)
            cluster = [seed]
            seed_pos = seed.get("position", (0, 0))

            # Find all components within cluster radius
            to_remove = []
            for i, comp in enumerate(remaining):
                pos = comp.get("position", (0, 0))
                if self.distance(seed_pos, pos) <= self.cluster_radius:
                    cluster.append(comp)
                    to_remove.append(i)

            # Remove clustered components (in reverse order to preserve indices)
            for i in reversed(to_remove):
                remaining.pop(i)

            clusters.append(cluster)

        return clusters

    def analyze_cluster(
        self,
        cluster: list[dict],
    ) -> Optional[Hotspot]:
        """
        Analyze a cluster of components for hotspot potential.

        Returns Hotspot if significant, None otherwise.
        """
        if not cluster:
            return None

        # Calculate cluster properties
        total_power = sum(c.get("power_w", 0) for c in cluster)

        if total_power < self.min_power:
            return None

        # Calculate center of mass (power-weighted)
        cx = sum(c.get("position", (0, 0))[0] * c.get("power_w", 0) for c in cluster)
        cy = sum(c.get("position", (0, 0))[1] * c.get("power_w", 0) for c in cluster)
        if total_power > 0:
            cx /= total_power
            cy /= total_power
        center = (cx, cy)

        # Calculate effective radius
        max_dist = 0.0
        for c in cluster:
            pos = c.get("position", (0, 0))
            dist = self.distance(center, pos)
            if dist > max_dist:
                max_dist = dist

        radius = max(max_dist + 5.0, 10.0)  # Minimum 10mm radius

        # Calculate power density
        area_cm2 = math.pi * (radius / 10) ** 2
        power_density = total_power / area_cm2

        # Determine severity
        if power_density >= self.critical_density:
            severity = "critical"
        elif power_density >= self.high_density:
            severity = "high"
        elif power_density >= self.high_density / 2:
            severity = "medium"
        else:
            severity = "low"

        # Estimate temperature rise (simplified model)
        # Assume spreading resistance ~ 10°C/W for concentrated area
        spreading_r = 10.0 / math.sqrt(area_cm2)
        temp_rise = total_power * spreading_r

        return Hotspot(
            center=center,
            radius_mm=radius,
            total_power_w=total_power,
            component_count=len(cluster),
            components=[c.get("ref", "?") for c in cluster],
            severity=severity,
            estimated_temp_rise_c=temp_rise,
        )

    def detect(
        self,
        components: list[dict],
        board_area_mm2: Optional[float] = None,
    ) -> HotspotResult:
        """
        Detect thermal hotspots.

        Args:
            components: List of components with position and power_w
            board_area_mm2: Total board area for context

        Returns:
            HotspotResult with detected hotspots
        """
        # Filter to only power-dissipating components
        power_components = [c for c in components if c.get("power_w", 0) > 0.01]

        # Cluster by proximity
        clusters = self.cluster_components(power_components)

        # Analyze each cluster
        hotspots = []
        for cluster in clusters:
            hs = self.analyze_cluster(cluster)
            if hs:
                hotspots.append(hs)

        # Calculate totals
        total_area = sum(math.pi * h.radius_mm ** 2 for h in hotspots)
        max_density = 0.0
        for hs in hotspots:
            area_cm2 = math.pi * (hs.radius_mm / 10) ** 2
            density = hs.total_power_w / area_cm2
            if density > max_density:
                max_density = density

        # Generate issues
        issues = []
        for hs in hotspots:
            if hs.severity in ["critical", "high"]:
                issues.append(HotspotIssue(
                    severity=hs.severity,
                    description=f"Thermal hotspot with {hs.total_power_w:.1f}W in {hs.radius_mm:.0f}mm radius",
                    location=hs.center,
                    components_involved=hs.components,
                    recommendation="Spread components, add thermal vias, or consider heat spreader",
                ))

        # Sort hotspots by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        hotspots.sort(key=lambda h: severity_order.get(h.severity, 4))

        score = self._calculate_score(hotspots, issues)

        return HotspotResult(
            hotspots=hotspots,
            total_hotspot_area_mm2=total_area,
            max_power_density_w_per_cm2=max_density,
            issues=issues,
            score=score,
        )

    def _calculate_score(
        self,
        hotspots: list[Hotspot],
        issues: list[HotspotIssue],
    ) -> float:
        """Calculate thermal hotspot score."""
        score = 100.0

        for hs in hotspots:
            if hs.severity == "critical":
                score -= 25
            elif hs.severity == "high":
                score -= 15
            elif hs.severity == "medium":
                score -= 5

        return max(0.0, score)

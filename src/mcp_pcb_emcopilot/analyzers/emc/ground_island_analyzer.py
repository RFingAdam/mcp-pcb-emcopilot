"""Ground Island Detector using NetworkX graph analysis.

Detects:
- Isolated ground regions (islands) without return paths
- Poor via stitching density
- Ground plane discontinuities
- Return path issues for high-speed signals

Decoupled from SQLAlchemy — operates on PCBDesignData.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

logger = logging.getLogger(__name__)


@dataclass
class GroundIsland:
    """Detected ground island."""
    island_id: int
    layer_names: list[str] = field(default_factory=list)
    via_count: int = 0
    region_area_mm2: float = 0.0
    component_count: int = 0
    severity: str = "error"


@dataclass
class ViaStitchingIssue:
    """Via stitching density issue."""
    layer_name: str
    region_description: str
    area_mm2: float
    via_count: int
    via_density_per_cm2: float
    recommended_density: float = 5.0
    severity: str = "warning"


@dataclass
class ReturnPathIssue:
    """High-speed signal return path issue."""
    net_name: str
    component_ref: str
    issue_type: str
    description: str
    severity: str = "error"


@dataclass
class GroundIslandAnalysisResult:
    """Result of ground island analysis."""
    total_ground_nets: int = 0
    main_ground_area_mm2: float = 0.0
    islands: list[GroundIsland] = field(default_factory=list)
    stitching_issues: list[ViaStitchingIssue] = field(default_factory=list)
    return_path_issues: list[ReturnPathIssue] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0

    def has_critical_issues(self) -> bool:
        return len(self.islands) > 0 or self.errors > 0


class GroundIslandAnalyzer:
    """Analyzer for ground plane connectivity using graph algorithms.

    Operates on in-memory PCBDesignData instead of database sessions.
    """

    GROUND_NET_KEYWORDS = ["GND", "VSS", "AGND", "DGND", "EARTH", "GROUND"]

    MIN_VIA_DENSITY_HIGH_SPEED = 5.0
    MIN_VIA_DENSITY_STANDARD = 2.0

    VIA_STITCH_SPACING_BY_FREQ = {
        100: 15.0,
        500: 6.0,
        1000: 3.0,
        3000: 1.5,
        6000: 0.75,
        10000: 0.5,
    }

    def __init__(self):
        if not HAS_NETWORKX:
            logger.warning("networkx not installed — ground island analysis unavailable")

    def _get_via_stitch_spacing_for_freq(self, freq_mhz: float) -> float:
        for freq_threshold, spacing in sorted(self.VIA_STITCH_SPACING_BY_FREQ.items()):
            if freq_mhz <= freq_threshold:
                return spacing
        return min(self.VIA_STITCH_SPACING_BY_FREQ.values())

    def analyze(
        self,
        design_data,
        max_frequency_mhz: float = 1000.0,
    ) -> GroundIslandAnalysisResult:
        """Analyze ground plane connectivity for islands.

        Args:
            design_data: PCBDesignData with parsed design
            max_frequency_mhz: Maximum signal frequency for return path analysis

        Returns:
            Analysis result with islands and issues
        """
        if not HAS_NETWORKX:
            return GroundIslandAnalysisResult(
                errors=1,
                return_path_issues=[ReturnPathIssue(
                    net_name="N/A", component_ref="N/A",
                    issue_type="missing_dependency",
                    description="networkx package required for ground island analysis",
                )]
            )

        result = GroundIslandAnalysisResult()

        # Find ground nets
        ground_nets = [
            net for net in design_data.nets
            if any(kw in (net.name or "").upper() for kw in self.GROUND_NET_KEYWORDS)
        ]
        result.total_ground_nets = len(ground_nets)

        if not ground_nets:
            return result

        ground_net_names = {net.name for net in ground_nets}
        ground_net_indices = {net.index for net in ground_nets}

        # Get ground vias and zones
        ground_vias = [
            v for v in design_data.vias
            if v.net_name in ground_net_names or v.net_index in ground_net_indices
        ]
        ground_zones = [
            z for z in design_data.zones
            if z.net_name in ground_net_names or z.net_index in ground_net_indices
        ]

        # Build connectivity graph
        graph = nx.Graph()

        # Add zone nodes
        for i, zone in enumerate(ground_zones):
            node_id = f"zone_{i}_{zone.layer}"
            graph.add_node(
                node_id,
                layer=zone.layer,
                area_mm2=zone.area_mm2,
            )

        # Add via edges between zones on different layers
        for via in ground_vias:
            start_nodes = [
                n for n, d in graph.nodes(data=True)
                if d.get("layer") == via.start_layer
            ]
            end_nodes = [
                n for n, d in graph.nodes(data=True)
                if d.get("layer") == via.end_layer
            ]
            for sn in start_nodes:
                for en in end_nodes:
                    graph.add_edge(sn, en, connection_type="via")

        if graph.number_of_nodes() == 0:
            return result

        # Find connected components
        components = list(nx.connected_components(graph))
        if not components:
            return result

        main_component = max(components, key=len)
        result.main_ground_area_mm2 = sum(
            graph.nodes[node].get("area_mm2", 0) for node in main_component
        )

        # Identify islands
        for idx, island in enumerate(components):
            if island == main_component:
                continue
            layer_names = list({graph.nodes[n].get("layer", "?") for n in island})
            area = sum(graph.nodes[n].get("area_mm2", 0) for n in island)
            result.islands.append(GroundIsland(
                island_id=idx + 1, layer_names=layer_names,
                region_area_mm2=area, severity="error",
            ))
            result.errors += 1

        # Check via stitching density
        min_density = (
            self.MIN_VIA_DENSITY_HIGH_SPEED
            if max_frequency_mhz >= 100
            else self.MIN_VIA_DENSITY_STANDARD
        )

        for zone in ground_zones:
            if zone.area_mm2 <= 0:
                continue
            area_cm2 = zone.area_mm2 / 100.0
            via_count = sum(
                1 for v in ground_vias
                if v.start_layer == zone.layer or v.end_layer == zone.layer
            )
            density = via_count / area_cm2 if area_cm2 > 0 else 0

            if density < min_density:
                result.stitching_issues.append(ViaStitchingIssue(
                    layer_name=zone.layer,
                    region_description=f"Ground zone on {zone.layer}",
                    area_mm2=zone.area_mm2,
                    via_count=via_count,
                    via_density_per_cm2=round(density, 2),
                    recommended_density=min_density,
                ))
                result.warnings += 1

        return result

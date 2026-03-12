"""Return path analyzer for ground return current tracing and EMI risk assessment.

Traces return current paths for high-speed signals, detects split-plane
crossings, checks via transitions for adequate return vias, and calculates
effective loop areas. This is the CRITICAL differentiator for EMC analysis --
what separates this tool from basic impedance calculators.

Operates on in-memory PCBDesignData from any parser.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Data structures
# =============================================================================

@dataclass
class ReturnPathSegment:
    """One segment of a return current path."""
    layer: str
    start_x_mm: float
    start_y_mm: float
    end_x_mm: float
    end_y_mm: float
    path_type: str  # "plane", "via", "detour"
    impedance_quality: str  # "good", "marginal", "poor"

    def length_mm(self) -> float:
        dx = self.end_x_mm - self.start_x_mm
        dy = self.end_y_mm - self.start_y_mm
        return math.sqrt(dx * dx + dy * dy)


@dataclass
class SplitPlaneCrossing:
    """Signal crossing a ground plane split or slot."""
    net_name: str
    crossing_location_x_mm: float
    crossing_location_y_mm: float
    split_layer: str
    split_width_mm: float
    detour_length_mm: float
    severity: str  # "critical", "warning", "info"
    recommendation: str


@dataclass
class ViaTransitionCheck:
    """Check for return via near signal via."""
    net_name: str
    signal_via_x_mm: float
    signal_via_y_mm: float
    signal_from_layer: str
    signal_to_layer: str
    nearest_ground_via_distance_mm: float
    has_adequate_return: bool
    recommendation: str


@dataclass
class ReturnPathResult:
    """Result for a single net's return path analysis."""
    net_name: str
    net_category: str  # from classifier
    signal_layer_transitions: int = 0
    return_path_segments: list[ReturnPathSegment] = field(default_factory=list)
    effective_loop_area_mm2: float = 0.0
    split_crossings: list[SplitPlaneCrossing] = field(default_factory=list)
    via_transitions: list[ViaTransitionCheck] = field(default_factory=list)
    return_path_quality: str = "good"  # "excellent", "good", "marginal", "poor"
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class ReturnPathAnalysisResult:
    """Complete return path analysis for the design."""
    total_nets_analyzed: int = 0
    nets_with_issues: int = 0
    split_crossings: list[SplitPlaneCrossing] = field(default_factory=list)
    via_transition_issues: list[ViaTransitionCheck] = field(default_factory=list)
    worst_loop_areas: list[dict] = field(default_factory=list)  # top-N worst loop areas
    net_results: list[ReturnPathResult] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0
    recommendations: list[str] = field(default_factory=list)


# =============================================================================
# Constants
# =============================================================================

# Typical frequency content by interface type (MHz)
INTERFACE_FREQUENCIES_MHZ = {
    "ddr": 1600,
    "ddr4": 1200,
    "usb": 240,
    "usb3": 2500,
    "pcie": 4000,
    "ethernet": 62.5,
    "clock": 100,
    "rf": 2400,
    "lvds": 400,
    "spi": 50,
    "i2c": 1,
    "uart": 1,
    "jtag": 10,
    "gpio": 50,
    "analog": 10,
}

# Ground net name keywords
GROUND_NET_KEYWORDS = ("GND", "VSS", "AGND", "DGND", "EARTH", "GROUND", "PGND", "SGND")

# High-speed categories that need return path analysis
HIGH_SPEED_CATEGORIES = {"ddr", "usb", "pcie", "ethernet", "clock", "rf", "lvds"}

# Maximum distance for a return via to be considered "adequate" (mm)
# This is lambda/20 at the signal's frequency content
# At 1 GHz, lambda = 300mm, lambda/20 = 15mm
# At 5 GHz, lambda = 60mm, lambda/20 = 3mm
SPEED_OF_LIGHT_MM_S = 299792458000.0  # mm/s


# =============================================================================
# Helper functions
# =============================================================================

def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance between two points."""
    dx = x2 - x1
    dy = y2 - y1
    return math.sqrt(dx * dx + dy * dy)


def _point_in_polygon(x: float, y: float, polygon: list) -> bool:
    """Ray casting algorithm to check if point is inside polygon.

    Polygon is a list of (x, y) tuples or dicts with x/y keys.
    """
    if not polygon or len(polygon) < 3:
        return False

    # Normalize polygon points
    points = []
    for p in polygon:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            points.append((float(p[0]), float(p[1])))
        elif isinstance(p, dict):
            px = p.get("x", p.get("x_mm", 0))
            py = p.get("y", p.get("y_mm", 0))
            points.append((float(px), float(py)))
        else:
            return False

    n = len(points)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = points[i]
        xj, yj = points[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i

    return inside


def _segment_intersects_gap(
    x1: float, y1: float, x2: float, y2: float,
    zone_outlines: list[list],
) -> tuple[bool, float, float]:
    """Check if a trace segment passes over a gap (area not covered by any zone).

    Uses midpoint and quarter-point sampling to detect if the trace path
    passes through uncovered areas.

    Returns:
        (has_gap, gap_x, gap_y) - whether gap found and approximate location.
    """
    if not zone_outlines:
        return False, 0.0, 0.0

    # Sample points along the trace segment
    num_samples = max(5, int(_distance(x1, y1, x2, y2) / 2.0))
    for i in range(1, num_samples):
        t = i / num_samples
        px = x1 + t * (x2 - x1)
        py = y1 + t * (y2 - y1)

        # Check if this point is inside ANY zone
        in_any_zone = False
        for outline in zone_outlines:
            if _point_in_polygon(px, py, outline):
                in_any_zone = True
                break

        if not in_any_zone:
            return True, px, py

    return False, 0.0, 0.0


def _get_frequency_for_category(category: str, net_name: str = "") -> float:
    """Get typical frequency in MHz for a net category."""
    # Check for subcategory hints in the net name
    name_upper = net_name.upper() if net_name else ""

    if category == "ddr":
        if "DDR5" in name_upper:
            return 2400
        if "DDR4" in name_upper or "LPDDR4" in name_upper:
            return 1200
        if "DDR3" in name_upper:
            return 800
        return 1600
    if category == "usb":
        if "SS" in name_upper or "USB3" in name_upper:
            return 2500
        return 240
    if category == "pcie":
        if "GEN5" in name_upper or "5.0" in name_upper:
            return 8000
        if "GEN4" in name_upper or "4.0" in name_upper:
            return 4000
        return 4000
    if category == "clock":
        # Try to extract frequency from name
        import re
        m = re.search(r'(\d+)\s*M', name_upper)
        if m:
            return float(m.group(1))
        return 100

    return INTERFACE_FREQUENCIES_MHZ.get(category, 50)


def _max_return_via_distance_mm(frequency_mhz: float) -> float:
    """Calculate maximum acceptable distance for a return via.

    Uses lambda/20 rule at the signal frequency.
    """
    if frequency_mhz <= 0:
        return 50.0  # very lenient default
    wavelength_mm = SPEED_OF_LIGHT_MM_S / (frequency_mhz * 1e6)
    return wavelength_mm / 20.0


def _get_layer_height_mm(
    layer_name: str,
    layers: list,
) -> float:
    """Get the Z-height of a layer from the stackup.

    Returns cumulative thickness from bottom. If stackup not detailed
    enough, estimates from layer position.
    """
    if not layers:
        return 0.0

    # Build cumulative heights
    total_height = 0.0
    layer_heights = {}
    for layer in layers:
        layer_heights[layer.name] = total_height
        total_height += layer.thickness_mm if layer.thickness_mm > 0 else 0.2

    return layer_heights.get(layer_name, 0.0)


def _get_reference_plane_for_layer(
    signal_layer: str,
    layers: list,
    ground_zone_layers: set,
) -> Optional[str]:
    """Find the nearest reference (ground/power) plane for a signal layer.

    The return current flows on the nearest plane layer below or above
    the signal layer.
    """
    if not layers:
        return None

    # Find signal layer index
    signal_idx = None
    for i, layer in enumerate(layers):
        if layer.name == signal_layer:
            signal_idx = i
            break

    if signal_idx is None:
        return None

    # Search outward from signal layer for nearest plane
    best_plane = None
    best_distance = float('inf')

    for i, layer in enumerate(layers):
        if layer.layer_type in ("plane", "mixed") or layer.name in ground_zone_layers:
            dist = abs(i - signal_idx)
            if 0 < dist < best_distance:
                best_distance = dist
                best_plane = layer.name

    return best_plane


def _inter_layer_distance_mm(
    layer1: str,
    layer2: str,
    layers: list,
) -> float:
    """Calculate the distance between two layers in mm.

    Uses stackup thickness data if available, otherwise estimates.
    """
    if not layers:
        return 0.2  # default prepreg thickness

    h1 = _get_layer_height_mm(layer1, layers)
    h2 = _get_layer_height_mm(layer2, layers)
    dist = abs(h2 - h1)

    # If we got zero (layers adjacent or stackup not detailed), use estimate
    if dist < 0.01:
        # Find indices and count layers between
        idx1 = idx2 = None
        for i, layer in enumerate(layers):
            if layer.name == layer1:
                idx1 = i
            if layer.name == layer2:
                idx2 = i
        if idx1 is not None and idx2 is not None:
            n_between = abs(idx2 - idx1)
            dist = n_between * 0.2  # ~200um per layer transition
        else:
            dist = 0.2

    return dist


# =============================================================================
# Main analyzer
# =============================================================================

class ReturnPathAnalyzer:
    """Analyzes ground return current paths for high-speed signals.

    For each high-speed signal net:
    1. Traces the signal path (trace segments + vias)
    2. Identifies the reference plane for each segment
    3. Calculates effective loop area = signal_path_length x distance_to_reference
    4. Detects split-plane crossings where return current must detour
    5. Checks via transitions for nearby return vias

    This is the foundation for quantitative EMI risk assessment.
    """

    def analyze(
        self,
        design_data,
        classified_nets=None,
        max_frequency_mhz: float = 0,
    ) -> ReturnPathAnalysisResult:
        """Full return path analysis for all high-speed signal nets.

        Args:
            design_data: PCBDesignData with parsed design
            classified_nets: Optional NetClassificationResult from classifier
            max_frequency_mhz: If >0, only analyze nets with frequency content
                above this threshold

        Returns:
            ReturnPathAnalysisResult with complete analysis
        """
        result = ReturnPathAnalysisResult()

        # Build classification lookup
        net_categories = {}
        if classified_nets is not None:
            for nc in classified_nets.classified_nets:
                net_categories[nc.net_name] = nc.category
        else:
            # Without classifier, treat all non-power/ground nets as signal
            for net in design_data.nets:
                name_upper = (net.name or "").upper()
                is_ground = any(kw in name_upper for kw in GROUND_NET_KEYWORDS)
                is_power = any(kw in name_upper for kw in ("VCC", "VDD", "VBAT", "VIN"))
                if is_ground:
                    net_categories[net.name] = "ground"
                elif is_power:
                    net_categories[net.name] = "power"
                else:
                    net_categories[net.name] = "unknown"

        # Identify which nets to analyze
        nets_to_analyze = []
        for net in design_data.nets:
            category = net_categories.get(net.name, "unknown")
            if category in ("power", "ground"):
                continue  # Skip power and ground nets

            # Check frequency threshold
            if category in HIGH_SPEED_CATEGORIES or category == "unknown":
                freq = _get_frequency_for_category(category, net.name)
                if max_frequency_mhz > 0 and freq < max_frequency_mhz:
                    continue
                nets_to_analyze.append((net, category))

        # Analyze each net
        for net, category in nets_to_analyze:
            try:
                net_result = self.analyze_net(
                    design_data, net.name,
                    net_category=category,
                    net_categories=net_categories,
                )
                result.net_results.append(net_result)
                result.total_nets_analyzed += 1

                if net_result.issues:
                    result.nets_with_issues += 1

                result.split_crossings.extend(net_result.split_crossings)

                for vt in net_result.via_transitions:
                    if not vt.has_adequate_return:
                        result.via_transition_issues.append(vt)

            except Exception as e:
                logger.warning("Failed to analyze net %s: %s", net.name, e)
                result.errors += 1

        # Count warnings
        result.warnings = sum(
            1 for sc in result.split_crossings if sc.severity == "warning"
        )
        result.errors += sum(
            1 for sc in result.split_crossings if sc.severity == "critical"
        )

        # Build worst loop areas (top 10)
        sorted_results = sorted(
            result.net_results,
            key=lambda r: r.effective_loop_area_mm2,
            reverse=True,
        )
        result.worst_loop_areas = [
            {
                "net_name": r.net_name,
                "category": r.net_category,
                "loop_area_mm2": round(r.effective_loop_area_mm2, 2),
                "quality": r.return_path_quality,
                "issue_count": len(r.issues),
            }
            for r in sorted_results[:10]
        ]

        # Build recommendations
        seen_recs = set()
        for nr in result.net_results:
            for rec in nr.recommendations:
                if rec not in seen_recs:
                    result.recommendations.append(rec)
                    seen_recs.add(rec)

        if result.split_crossings:
            rec = (
                f"Found {len(result.split_crossings)} split-plane crossing(s). "
                "Reroute signals to avoid crossing reference plane gaps."
            )
            if rec not in seen_recs:
                result.recommendations.append(rec)

        if result.via_transition_issues:
            rec = (
                f"Found {len(result.via_transition_issues)} via transition(s) without "
                "adequate return vias. Add ground vias near signal vias."
            )
            if rec not in seen_recs:
                result.recommendations.append(rec)

        return result

    def analyze_net(
        self,
        design_data,
        net_name: str,
        net_category: str = "unknown",
        net_categories: Optional[dict] = None,
    ) -> ReturnPathResult:
        """Analyze return path for a specific net.

        Args:
            design_data: PCBDesignData with parsed design
            net_name: Name of the net to analyze
            net_category: Category from classifier (ddr, usb, pcie, etc.)
            net_categories: Full category map for all nets (for ground detection)

        Returns:
            ReturnPathResult with complete analysis for this net
        """
        result = ReturnPathResult(
            net_name=net_name,
            net_category=net_category,
        )

        # Find the net
        net_obj = design_data.get_net_by_name(net_name)
        if net_obj is None:
            result.issues.append(f"Net '{net_name}' not found in design")
            result.return_path_quality = "poor"
            return result

        # Get traces and vias for this net
        traces = design_data.get_traces_on_net(net_obj.index)
        vias = design_data.get_vias_on_net(net_obj.index)

        if not traces and not vias:
            result.issues.append(f"No routing found for net '{net_name}'")
            result.return_path_quality = "poor"
            return result

        # Build ground infrastructure
        if net_categories is None:
            net_categories = {}
            for n in design_data.nets:
                name_upper = (n.name or "").upper()
                if any(kw in name_upper for kw in GROUND_NET_KEYWORDS):
                    net_categories[n.name] = "ground"

        ground_net_names = {
            name for name, cat in net_categories.items() if cat == "ground"
        }
        ground_net_indices = {
            n.index for n in design_data.nets if n.name in ground_net_names
        }

        # Find ground zones by layer
        ground_zones_by_layer = {}
        for zone in design_data.zones:
            if zone.net_name in ground_net_names or zone.net_index in ground_net_indices:
                ground_zones_by_layer.setdefault(zone.layer, []).append(zone)

        # Find ground vias
        ground_vias = [
            v for v in design_data.vias
            if v.net_name in ground_net_names or v.net_index in ground_net_indices
        ]

        # Get set of layers that have ground zones
        ground_zone_layers = set(ground_zones_by_layer.keys())

        # Determine signal frequency
        freq_mhz = _get_frequency_for_category(net_category, net_name)
        max_via_dist = _max_return_via_distance_mm(freq_mhz)

        # Count layer transitions
        signal_layers = set()
        for trace in traces:
            signal_layers.add(trace.layer)
        result.signal_layer_transitions = max(0, len(signal_layers) - 1)

        # Analyze each trace segment
        total_loop_area = 0.0
        for trace in traces:
            # Find reference plane for this layer
            ref_plane = _get_reference_plane_for_layer(
                trace.layer, design_data.layers, ground_zone_layers,
            )

            if ref_plane is None:
                # No reference plane found - very poor return path
                seg = ReturnPathSegment(
                    layer=trace.layer,
                    start_x_mm=trace.x1_mm, start_y_mm=trace.y1_mm,
                    end_x_mm=trace.x2_mm, end_y_mm=trace.y2_mm,
                    path_type="plane",
                    impedance_quality="poor",
                )
                result.return_path_segments.append(seg)
                result.issues.append(
                    f"No reference plane found for signal on {trace.layer}"
                )

                # Loop area with no reference plane - use board thickness as height
                trace_len = trace.calc_length()
                total_loop_area += trace_len * design_data.board_thickness_mm
                continue

            # Calculate distance to reference plane
            layer_dist = _inter_layer_distance_mm(
                trace.layer, ref_plane, design_data.layers,
            )

            # Check if trace crosses a split in the reference plane
            ref_zones = ground_zones_by_layer.get(ref_plane, [])
            ref_outlines = [z.outline for z in ref_zones if z.outline]

            has_gap, gap_x, gap_y = False, 0.0, 0.0
            if ref_outlines:
                has_gap, gap_x, gap_y = _segment_intersects_gap(
                    trace.x1_mm, trace.y1_mm,
                    trace.x2_mm, trace.y2_mm,
                    ref_outlines,
                )

            # Determine quality
            if has_gap:
                quality = "poor"
                # Estimate detour: return current must go around the gap
                # Conservative estimate: 2x the trace segment length
                trace_len = trace.calc_length()
                detour_len = trace_len * 2.0
                split_width = 1.0  # default estimate if we don't have gap geometry

                crossing = SplitPlaneCrossing(
                    net_name=net_name,
                    crossing_location_x_mm=round(gap_x, 2),
                    crossing_location_y_mm=round(gap_y, 2),
                    split_layer=ref_plane,
                    split_width_mm=split_width,
                    detour_length_mm=round(detour_len, 2),
                    severity="critical" if freq_mhz > 100 else "warning",
                    recommendation=(
                        f"Signal '{net_name}' crosses a gap in reference plane "
                        f"'{ref_plane}' at ({gap_x:.1f}, {gap_y:.1f})mm. "
                        "Reroute to avoid this crossing or stitch the planes."
                    ),
                )
                result.split_crossings.append(crossing)

                # Loop area increases dramatically at split crossings
                total_loop_area += trace_len * detour_len
            else:
                quality = "good" if layer_dist < 0.3 else "marginal"
                trace_len = trace.calc_length()
                total_loop_area += trace_len * layer_dist

            seg = ReturnPathSegment(
                layer=trace.layer,
                start_x_mm=trace.x1_mm, start_y_mm=trace.y1_mm,
                end_x_mm=trace.x2_mm, end_y_mm=trace.y2_mm,
                path_type="plane",
                impedance_quality=quality,
            )
            result.return_path_segments.append(seg)

        # Analyze via transitions
        for via in vias:
            vt = self._check_single_via_transition(
                via, net_name, ground_vias, max_via_dist, freq_mhz,
            )
            result.via_transitions.append(vt)

            if not vt.has_adequate_return:
                # Add loop area contribution from poor via transition
                total_loop_area += vt.nearest_ground_via_distance_mm ** 2

        result.effective_loop_area_mm2 = round(total_loop_area, 2)

        # Determine overall return path quality
        poor_count = sum(
            1 for s in result.return_path_segments if s.impedance_quality == "poor"
        )
        marginal_count = sum(
            1 for s in result.return_path_segments if s.impedance_quality == "marginal"
        )
        total_segs = len(result.return_path_segments)

        bad_via_count = sum(
            1 for vt in result.via_transitions if not vt.has_adequate_return
        )

        if poor_count > 0 or result.split_crossings or bad_via_count > 1:
            result.return_path_quality = "poor"
        elif marginal_count > total_segs * 0.3 or bad_via_count == 1:
            result.return_path_quality = "marginal"
        elif marginal_count == 0 and poor_count == 0 and bad_via_count == 0:
            result.return_path_quality = "excellent"
        else:
            result.return_path_quality = "good"

        # Generate issues and recommendations
        if result.return_path_quality == "poor":
            result.issues.append(
                f"Poor return path quality for '{net_name}' "
                f"(loop area: {total_loop_area:.1f} mm^2)"
            )

        if poor_count > 0:
            result.recommendations.append(
                f"Improve reference plane coverage for {poor_count} segment(s) "
                f"of '{net_name}'"
            )

        if bad_via_count > 0:
            result.recommendations.append(
                f"Add ground vias near {bad_via_count} signal via(s) for "
                f"'{net_name}' (within {max_via_dist:.1f}mm)"
            )

        if result.split_crossings:
            result.recommendations.append(
                f"Reroute '{net_name}' to avoid {len(result.split_crossings)} "
                "reference plane split crossing(s)"
            )

        if total_loop_area > 100:  # > 1 cm^2
            result.issues.append(
                f"Large effective loop area ({total_loop_area:.1f} mm^2) -- "
                "significant EMI risk at high frequencies"
            )
            result.recommendations.append(
                "Reduce loop area by routing closer to reference plane or "
                "shortening trace lengths"
            )

        return result

    def find_split_crossings(self, design_data) -> list[SplitPlaneCrossing]:
        """Find all signals crossing ground plane splits.

        This is a standalone convenience method that analyzes all routed nets
        for split-plane crossings.

        Args:
            design_data: PCBDesignData with parsed design

        Returns:
            List of all detected split-plane crossings
        """
        result = self.analyze(design_data)
        return result.split_crossings

    def check_via_transitions(
        self,
        design_data,
        net_name: str,
    ) -> list[ViaTransitionCheck]:
        """Check if signal vias have nearby return vias.

        Args:
            design_data: PCBDesignData with parsed design
            net_name: Name of the net to check

        Returns:
            List of via transition checks
        """
        result = self.analyze_net(design_data, net_name)
        return result.via_transitions

    def _check_single_via_transition(
        self,
        signal_via,
        net_name: str,
        ground_vias: list,
        max_distance_mm: float,
        frequency_mhz: float,
    ) -> ViaTransitionCheck:
        """Check a single signal via for nearby return via.

        Args:
            signal_via: The signal via to check
            net_name: Name of the net
            ground_vias: List of all ground vias
            max_distance_mm: Maximum acceptable distance for return via
            frequency_mhz: Signal frequency for recommendations

        Returns:
            ViaTransitionCheck result
        """
        # Find nearest ground via
        nearest_dist = float('inf')
        for gv in ground_vias:
            dist = _distance(
                signal_via.x_mm, signal_via.y_mm,
                gv.x_mm, gv.y_mm,
            )
            if dist < nearest_dist:
                nearest_dist = dist

        # If no ground vias exist at all
        if nearest_dist == float('inf'):
            nearest_dist = 999.0

        has_adequate = nearest_dist <= max_distance_mm

        # Build recommendation
        if has_adequate:
            recommendation = (
                f"Return via at {nearest_dist:.1f}mm -- adequate for "
                f"{frequency_mhz:.0f}MHz signal (max: {max_distance_mm:.1f}mm)"
            )
        else:
            recommendation = (
                f"Nearest ground via is {nearest_dist:.1f}mm away. "
                f"For {frequency_mhz:.0f}MHz signal, place return via within "
                f"{max_distance_mm:.1f}mm of signal via at "
                f"({signal_via.x_mm:.1f}, {signal_via.y_mm:.1f})mm"
            )

        return ViaTransitionCheck(
            net_name=net_name,
            signal_via_x_mm=round(signal_via.x_mm, 2),
            signal_via_y_mm=round(signal_via.y_mm, 2),
            signal_from_layer=signal_via.start_layer,
            signal_to_layer=signal_via.end_layer,
            nearest_ground_via_distance_mm=round(nearest_dist, 2),
            has_adequate_return=has_adequate,
            recommendation=recommendation,
        )

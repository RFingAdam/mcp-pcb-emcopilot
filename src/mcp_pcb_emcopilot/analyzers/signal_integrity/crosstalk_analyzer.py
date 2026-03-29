"""
Crosstalk Analyzer — detects parallel trace coupling on high-speed nets.

Finds parallel trace segments on the same layer within coupling distance,
estimates NEXT/FEXT using simplified models, and flags critical pairs based
on coupling length, spacing, and net classification.

Coupling distance threshold: < 3 x dielectric_height, or < 0.5 mm default.
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional

from ...models.pcb_data import PCBDesignData

logger = logging.getLogger(__name__)

# High-speed net categories that warrant crosstalk analysis
_HS_CATEGORIES = {"ddr", "usb", "pcie", "ethernet", "emmc", "sdio", "clock", "lvds"}

# Default frequency assumptions per interface (GHz) for FEXT estimation
_FREQ_GHZ: Dict[str, float] = {
    "ddr": 1.6,
    "usb": 5.0,
    "pcie": 8.0,
    "ethernet": 0.125,
    "emmc": 0.2,
    "sdio": 0.208,
    "clock": 0.5,
    "lvds": 0.5,
}

# Thresholds
_CRITICAL_COUPLING_MM = 10.0  # parallel coupling > 10 mm
_WARNING_COUPLING_MM = 5.0    # parallel coupling > 5 mm
_CRITICAL_SPACING_MULT = 2.0  # spacing < 2x trace width
_WARNING_SPACING_MULT = 3.0   # spacing < 3x trace width
_PARALLEL_DOT_THRESHOLD = 0.9  # |dot product| > 0.9 means parallel
_MAX_TRACES_PER_LAYER = 500     # cap per-layer traces to limit O(N^2)
_SPATIAL_BIN_MM = 1.0           # Y-distance bin for spatial filtering


def _segment_direction(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float]:
    """Return unit direction vector of a segment. Returns (0,0) for zero-length."""
    dx = x2 - x1
    dy = y2 - y1
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1e-9:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def _segment_length(x1: float, y1: float, x2: float, y2: float) -> float:
    dx = x2 - x1
    dy = y2 - y1
    return math.sqrt(dx * dx + dy * dy)


def _point_to_line_distance(
    px: float, py: float,
    x1: float, y1: float, x2: float, y2: float,
) -> float:
    """Perpendicular distance from point (px, py) to infinite line through (x1,y1)-(x2,y2)."""
    dx = x2 - x1
    dy = y2 - y1
    denom = math.sqrt(dx * dx + dy * dy)
    if denom < 1e-9:
        return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)
    return abs(dy * px - dx * py + x2 * y1 - y2 * x1) / denom


def _parallel_overlap_length(
    ax1: float, ay1: float, ax2: float, ay2: float,
    bx1: float, by1: float, bx2: float, by2: float,
) -> float:
    """Compute the overlap length of two parallel segments projected onto a common axis."""
    # Project both segments onto the direction of segment A
    dx = ax2 - ax1
    dy = ay2 - ay1
    seg_len = math.sqrt(dx * dx + dy * dy)
    if seg_len < 1e-9:
        return 0.0
    ux, uy = dx / seg_len, dy / seg_len

    # Project start/end of both segments onto this axis
    a_proj_start = ax1 * ux + ay1 * uy
    a_proj_end = ax2 * ux + ay2 * uy
    b_proj_start = bx1 * ux + by1 * uy
    b_proj_end = bx2 * ux + by2 * uy

    a_lo, a_hi = min(a_proj_start, a_proj_end), max(a_proj_start, a_proj_end)
    b_lo, b_hi = min(b_proj_start, b_proj_end), max(b_proj_start, b_proj_end)

    overlap = min(a_hi, b_hi) - max(a_lo, b_lo)
    return max(overlap, 0.0)


def _estimate_spacing(
    ax1: float, ay1: float, ax2: float, ay2: float,
    bx1: float, by1: float, bx2: float, by2: float,
) -> float:
    """Estimate centre-to-centre spacing between two parallel segments."""
    # Use midpoint of segment B projected onto line of segment A
    mid_bx = (bx1 + bx2) / 2
    mid_by = (by1 + by2) / 2
    return _point_to_line_distance(mid_bx, mid_by, ax1, ay1, ax2, ay2)


class CrosstalkAnalyzer:
    """Detect and flag crosstalk risk between high-speed parallel traces.

    For each high-speed net, finds parallel trace segments on the same layer
    within coupling distance and estimates NEXT/FEXT.
    """

    def analyze(
        self,
        design: Any,
        classified_nets: Any = None,
        interfaces: Any = None,
    ) -> List[Dict[str, Any]]:
        """Analyze crosstalk risk across the design.

        Returns a list of finding dicts with keys:
            severity, title, description, recommendation,
            aggressor, victim, layer, coupling_length_mm, spacing_mm,
            next_estimate, fext_estimate, location_x_mm, location_y_mm
        """
        findings: List[Dict[str, Any]] = []
        traces = getattr(design, "traces", [])
        if not traces:
            return findings

        # Determine dielectric height for coupling distance threshold
        dielectric_height = self._get_dielectric_height(design)
        coupling_threshold = min(3.0 * dielectric_height, 0.5) if dielectric_height > 0 else 0.5

        # Build set of high-speed net names
        hs_nets = self._get_hs_net_names(classified_nets)
        if not hs_nets:
            # If no classifier result, still check for nets with suggestive names
            hs_nets = self._guess_hs_nets(traces)

        # Build net category lookup
        net_category: Dict[str, str] = {}
        if classified_nets is not None:
            for nc in getattr(classified_nets, "classified_nets", []):
                if nc.category in _HS_CATEGORIES:
                    net_category[nc.net_name] = nc.category

        # Group high-speed traces by layer for pairwise comparison
        layer_traces: Dict[str, List] = defaultdict(list)
        for trace in traces:
            net_name = getattr(trace, "net_name", None)
            if net_name and net_name in hs_nets:
                layer_traces[trace.layer].append(trace)

        # Track already-flagged pairs to avoid duplicates
        flagged_pairs: set[tuple[str, str, str]] = set()

        for layer, layer_trs in layer_traces.items():
            # Sort by segment length descending — longest segments have most coupling risk
            layer_trs.sort(
                key=lambda t: _segment_length(t.x1_mm, t.y1_mm, t.x2_mm, t.y2_mm),
                reverse=True,
            )
            # Cap at _MAX_TRACES_PER_LAYER to bound the O(N^2) comparison
            layer_trs = layer_trs[:_MAX_TRACES_PER_LAYER]

            # Build spatial bins by Y-coordinate midpoint for fast neighbour lookup
            y_bins: Dict[int, List[int]] = defaultdict(list)
            for idx, tr in enumerate(layer_trs):
                y_mid = (tr.y1_mm + tr.y2_mm) / 2
                bin_key = int(y_mid // _SPATIAL_BIN_MM)
                y_bins[bin_key].append(idx)

            n = len(layer_trs)
            for i in range(n):
                tr_a = layer_trs[i]
                net_a = tr_a.net_name
                dir_a = _segment_direction(tr_a.x1_mm, tr_a.y1_mm, tr_a.x2_mm, tr_a.y2_mm)
                if dir_a == (0.0, 0.0):
                    continue
                len_a = _segment_length(tr_a.x1_mm, tr_a.y1_mm, tr_a.x2_mm, tr_a.y2_mm)
                if len_a < 0.5:
                    continue

                # Only compare against traces in nearby Y bins (within 1mm)
                y_mid_a = (tr_a.y1_mm + tr_a.y2_mm) / 2
                bin_a = int(y_mid_a // _SPATIAL_BIN_MM)
                nearby_indices: set[int] = set()
                for bk in (bin_a - 1, bin_a, bin_a + 1):
                    for idx in y_bins.get(bk, ()):
                        if idx > i:
                            nearby_indices.add(idx)

                for j in nearby_indices:
                    tr_b = layer_trs[j]
                    net_b = tr_b.net_name

                    # Skip same-net segments
                    if net_a == net_b:
                        continue

                    # Skip already-flagged pairs on this layer
                    pair_key = (min(net_a, net_b), max(net_a, net_b), layer)
                    if pair_key in flagged_pairs:
                        continue

                    dir_b = _segment_direction(tr_b.x1_mm, tr_b.y1_mm, tr_b.x2_mm, tr_b.y2_mm)
                    if dir_b == (0.0, 0.0):
                        continue

                    # Check parallelism via dot product
                    dot = abs(dir_a[0] * dir_b[0] + dir_a[1] * dir_b[1])
                    if dot < _PARALLEL_DOT_THRESHOLD:
                        continue

                    # Check spacing (centre-to-centre)
                    spacing = _estimate_spacing(
                        tr_a.x1_mm, tr_a.y1_mm, tr_a.x2_mm, tr_a.y2_mm,
                        tr_b.x1_mm, tr_b.y1_mm, tr_b.x2_mm, tr_b.y2_mm,
                    )

                    # Edge-to-edge spacing
                    avg_width = (getattr(tr_a, "width_mm", 0.15) + getattr(tr_b, "width_mm", 0.15)) / 2
                    edge_spacing = max(spacing - avg_width, 0.0)

                    if edge_spacing > coupling_threshold:
                        continue

                    # Calculate coupling length (overlap projection)
                    coupling_length = _parallel_overlap_length(
                        tr_a.x1_mm, tr_a.y1_mm, tr_a.x2_mm, tr_a.y2_mm,
                        tr_b.x1_mm, tr_b.y1_mm, tr_b.x2_mm, tr_b.y2_mm,
                    )
                    if coupling_length < 1.0:
                        continue

                    # Determine severity
                    cat_a = net_category.get(net_a, "unknown")
                    cat_b = net_category.get(net_b, "unknown")
                    is_clock_adjacent = (cat_a == "clock") != (cat_b == "clock")

                    severity = self._classify_severity(
                        coupling_length, spacing, avg_width, is_clock_adjacent,
                    )
                    if severity is None:
                        continue

                    # Estimate NEXT / FEXT (simplified models)
                    freq_ghz = max(_FREQ_GHZ.get(cat_a, 0.5), _FREQ_GHZ.get(cat_b, 0.5))
                    height = dielectric_height if dielectric_height > 0 else 0.1
                    safe_spacing = max(spacing, 0.01)

                    next_est = coupling_length / (4.0 * safe_spacing)
                    fext_est = (coupling_length ** 2 * freq_ghz) / (safe_spacing * height)

                    # Location: midpoint of segment A
                    loc_x = (tr_a.x1_mm + tr_a.x2_mm) / 2
                    loc_y = (tr_a.y1_mm + tr_a.y2_mm) / 2

                    finding = {
                        "severity": severity,
                        "title": f"Crosstalk risk: {net_a} / {net_b} on {layer}",
                        "description": (
                            f"Parallel traces {net_a} and {net_b} run {coupling_length:.1f} mm "
                            f"on {layer} with {spacing:.3f} mm centre-to-centre spacing "
                            f"({spacing / avg_width:.1f}x trace width). "
                            f"NEXT estimate: {next_est:.3f}, FEXT estimate: {fext_est:.2f}."
                        ),
                        "recommendation": self._recommendation(severity, spacing, avg_width, is_clock_adjacent),
                        "aggressor": net_a,
                        "victim": net_b,
                        "layer": layer,
                        "coupling_length_mm": round(coupling_length, 2),
                        "spacing_mm": round(spacing, 3),
                        "next_estimate": round(next_est, 4),
                        "fext_estimate": round(fext_est, 4),
                        "location_x_mm": round(loc_x, 2),
                        "location_y_mm": round(loc_y, 2),
                    }
                    if is_clock_adjacent:
                        finding["clock_adjacent"] = True

                    findings.append(finding)
                    flagged_pairs.add(pair_key)

        # Sort: critical first, then by coupling length descending
        severity_rank = {"critical": 0, "warning": 1, "info": 2}
        findings.sort(key=lambda f: (severity_rank.get(f["severity"], 9), -f["coupling_length_mm"]))

        return findings

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_dielectric_height(design: Any) -> float:
        """Extract typical dielectric height from stackup layers."""
        layers = getattr(design, "layers", [])
        for layer in layers:
            lt = getattr(layer, "layer_type", "")
            thickness = getattr(layer, "thickness_mm", 0)
            if lt == "dielectric" and thickness > 0:
                return thickness
        return 0.1  # 100 um default

    @staticmethod
    def _get_hs_net_names(classified_nets: Any) -> set[str]:
        """Return set of net names classified as high-speed."""
        if classified_nets is None:
            return set()
        names: set[str] = set()
        for nc in getattr(classified_nets, "classified_nets", []):
            if nc.category in _HS_CATEGORIES:
                names.add(nc.net_name)
        return names

    @staticmethod
    def _guess_hs_nets(traces: list) -> set[str]:
        """Fallback: guess high-speed nets from name patterns."""
        patterns = ("CLK", "CK", "DDR", "USB", "PCIE", "ETH", "RGMII", "MDIO",
                    "SDIO", "EMMC", "SD_", "LVDS", "DP_", "DM_", "TX", "RX")
        names: set[str] = set()
        for trace in traces:
            net_name = getattr(trace, "net_name", "")
            if net_name:
                upper = net_name.upper()
                for pat in patterns:
                    if pat in upper:
                        names.add(net_name)
                        break
        return names

    @staticmethod
    def _classify_severity(
        coupling_mm: float,
        spacing_mm: float,
        avg_width: float,
        is_clock_adjacent: bool,
    ) -> Optional[str]:
        """Determine severity or None if below threshold."""
        # Clock adjacent to data always flagged
        if is_clock_adjacent:
            return "critical" if coupling_mm > _WARNING_COUPLING_MM else "warning"

        safe_width = max(avg_width, 0.01)
        spacing_ratio = spacing_mm / safe_width

        if coupling_mm > _CRITICAL_COUPLING_MM and spacing_ratio < _CRITICAL_SPACING_MULT:
            return "critical"
        if coupling_mm > _WARNING_COUPLING_MM and spacing_ratio < _WARNING_SPACING_MULT:
            return "warning"
        if coupling_mm > _CRITICAL_COUPLING_MM and spacing_ratio < _WARNING_SPACING_MULT:
            return "warning"
        return None

    @staticmethod
    def _recommendation(severity: str, spacing: float, avg_width: float, is_clock: bool) -> str:
        parts = []
        if is_clock:
            parts.append("Route clock nets with guard traces or on a separate layer from data signals.")
        if severity == "critical":
            parts.append(f"Increase spacing to at least {3 * avg_width:.2f} mm (3x trace width).")
            parts.append("Reduce parallel coupling length by adding jogs or layer changes.")
        else:
            parts.append(f"Consider increasing spacing to {3 * avg_width:.2f} mm (3x trace width).")
        parts.append("Use ground guard traces between sensitive pairs where spacing is constrained.")
        return " ".join(parts)

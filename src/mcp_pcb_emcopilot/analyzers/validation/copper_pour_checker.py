"""
Copper pour net assignment and floating copper checker.

Detects:
- Zones with no net assignment (floating copper = EMI antenna)
- Suspiciously small zones that may be copper slivers
- Zones on non-ground nets that may be incorrectly assigned
- Per-layer copper pour distribution summary

Unconnected copper islands act as unintentional antennas, radiating
at resonant frequencies determined by their physical dimensions.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List

from ...models.pcb_data import PCBDesignData

logger = logging.getLogger(__name__)

# Thresholds
_MIN_ZONE_AREA_MM2 = 1.0  # Below this is a potential sliver
_GROUND_KEYWORDS = {"GND", "VSS", "AGND", "DGND", "EARTH", "GROUND", "PGND", "SGND"}


class CopperPourChecker:
    """Check copper pour net assignments and detect floating copper.

    Floating copper (zones with no net) acts as an unintentional antenna.
    Copper slivers create unpredictable resonances and manufacturing issues.
    """

    def analyze(
        self,
        design: Any,
        classified_nets: Any = None,
        interfaces: Any = None,
    ) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []

        zones = getattr(design, "zones", [])
        if not zones:
            return findings

        # Categorize zones
        floating_zones: List[Dict[str, Any]] = []
        sliver_zones: List[Dict[str, Any]] = []
        non_ground_pours: List[Dict[str, Any]] = []

        # Per-layer statistics
        layer_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"total": 0, "assigned": 0, "floating": 0, "total_area_mm2": 0.0}
        )

        for zone in zones:
            layer = getattr(zone, "layer", "unknown")
            net_name = getattr(zone, "net_name", None)
            area_mm2 = getattr(zone, "area_mm2", 0.0)

            stats = layer_stats[layer]
            stats["total"] += 1
            stats["total_area_mm2"] += area_mm2

            is_floating = not net_name or net_name.strip() == ""

            if is_floating:
                stats["floating"] += 1
                floating_zones.append({
                    "layer": layer,
                    "area_mm2": round(area_mm2, 2),
                    "net_index": getattr(zone, "net_index", 0),
                })
            else:
                stats["assigned"] += 1

                # Check for copper slivers (assigned but tiny)
                if 0 < area_mm2 < _MIN_ZONE_AREA_MM2:
                    sliver_zones.append({
                        "layer": layer,
                        "net_name": net_name,
                        "area_mm2": round(area_mm2, 4),
                    })

                # Check for non-ground pours (potential misassignment)
                name_upper = net_name.upper()
                is_ground = any(kw in name_upper for kw in _GROUND_KEYWORDS)
                is_power = any(
                    kw in name_upper
                    for kw in ("VCC", "VDD", "V3P3", "V1P8", "V1P2", "V5P0",
                               "VBAT", "VSYS", "PWR", "+3V3", "+5V", "+12V",
                               "3V3", "5V", "12V", "1V8", "1V2")
                )
                if not is_ground and not is_power and area_mm2 > _MIN_ZONE_AREA_MM2:
                    non_ground_pours.append({
                        "layer": layer,
                        "net_name": net_name,
                        "area_mm2": round(area_mm2, 2),
                    })

        # Report floating copper zones
        if floating_zones:
            findings.append({
                "severity": "critical" if len(floating_zones) > 3 else "warning",
                "category": "validation",
                "description": (
                    f"{len(floating_zones)} copper pour(s) have no net assignment. "
                    "Floating copper acts as an unintentional antenna and radiates "
                    "at frequencies determined by its physical dimensions."
                ),
                "recommendation": (
                    "Assign all copper pours to a net (typically GND). If the copper "
                    "is intentionally unconnected, remove it or add explicit ground "
                    "stitching vias to tie it to the ground plane."
                ),
                "details": {
                    "floating_count": len(floating_zones),
                    "zones": floating_zones[:20],  # Cap for readability
                },
            })

        # Report copper slivers
        if sliver_zones:
            findings.append({
                "severity": "warning",
                "category": "validation",
                "description": (
                    f"{len(sliver_zones)} copper pour(s) are smaller than "
                    f"{_MIN_ZONE_AREA_MM2}mm2. These may be copper slivers that "
                    "cause manufacturing defects or act as small radiating elements."
                ),
                "recommendation": (
                    "Remove small copper fragments or merge them with adjacent pours. "
                    "Copper slivers can detach during manufacturing and cause shorts."
                ),
                "details": {
                    "sliver_count": len(sliver_zones),
                    "zones": sliver_zones[:20],
                },
            })

        # Report non-ground/non-power pours (informational)
        if non_ground_pours:
            findings.append({
                "severity": "info",
                "category": "validation",
                "description": (
                    f"{len(non_ground_pours)} copper pour(s) are assigned to "
                    "signal nets (not ground or power). Verify these are intentional."
                ),
                "recommendation": (
                    "Large copper pours on signal nets are unusual. Verify net "
                    "assignment is correct -- accidental signal pours can cause "
                    "impedance discontinuities and crosstalk."
                ),
                "details": {
                    "non_ground_count": len(non_ground_pours),
                    "zones": non_ground_pours[:20],
                },
            })

        # Summary finding (always emit for visibility)
        total_zones = len(zones)
        total_assigned = sum(s["assigned"] for s in layer_stats.values())
        total_floating = sum(s["floating"] for s in layer_stats.values())
        findings.append({
            "severity": "info",
            "category": "validation",
            "description": (
                f"Copper pour summary: {total_zones} total zones, "
                f"{total_assigned} assigned, {total_floating} floating."
            ),
            "recommendation": "Review per-layer distribution for balanced copper coverage.",
            "details": {
                "total_zones": total_zones,
                "assigned": total_assigned,
                "floating": total_floating,
                "per_layer": {
                    layer: {
                        "total": s["total"],
                        "assigned": s["assigned"],
                        "floating": s["floating"],
                        "total_area_mm2": round(s["total_area_mm2"], 1),
                    }
                    for layer, s in sorted(layer_stats.items())
                },
            },
        })

        return findings

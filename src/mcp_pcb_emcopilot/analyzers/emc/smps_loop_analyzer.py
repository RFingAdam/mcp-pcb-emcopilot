"""
SMPS switching loop area analyzer.

Detects:
- SMPS/buck converter ICs by part number patterns
- Input capacitor, output capacitor, and inductor associated with each regulator
- Estimates the hot switching loop area from component placement distances
- Flags excessive loop areas that increase conducted and radiated EMI

The high di/dt switching loop (IC -> input cap -> inductor -> IC) is the
primary EMI source in SMPS circuits. Minimizing this loop area is the single
most effective EMI mitigation technique for power converters.
"""
from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from ...models.pcb_data import PCBDesignData

logger = logging.getLogger(__name__)

# Thresholds (mm^2)
_LOOP_AREA_WARNING_MM2 = 100.0
_LOOP_AREA_CRITICAL_MM2 = 200.0

# Max search radius for associated components (mm)
_MAX_ASSOCIATION_RADIUS_MM = 25.0

# SMPS IC part number patterns (case-insensitive)
_SMPS_PATTERNS: List[re.Pattern] = [
    re.compile(r"TPS6[0-9]", re.IGNORECASE),       # TI TPS62xxx, TPS65xxx
    re.compile(r"TPS5[0-9]", re.IGNORECASE),       # TI TPS5xxx
    re.compile(r"LT3[0-9]", re.IGNORECASE),        # Analog Devices LT3xxx
    re.compile(r"LTC3[0-9]", re.IGNORECASE),       # Analog Devices LTC3xxx
    re.compile(r"MP[0-9]{4}", re.IGNORECASE),       # MPS MPxxxx
    re.compile(r"RT[0-9]{4}", re.IGNORECASE),       # Richtek RTxxxx
    re.compile(r"NCV[0-9]", re.IGNORECASE),         # ON Semi NCVxxx
    re.compile(r"NCP[0-9]", re.IGNORECASE),         # ON Semi NCPxxx
    re.compile(r"ISL[0-9]{4}", re.IGNORECASE),      # Renesas ISLxxxx
    re.compile(r"MAX[0-9]{4,5}", re.IGNORECASE),    # Maxim MAXxxxxx
    re.compile(r"ADP[0-9]{4}", re.IGNORECASE),      # ADI ADPxxxx
    re.compile(r"TLV6[0-9]", re.IGNORECASE),        # TI TLV62xxx
    re.compile(r"SY[0-9]{4}", re.IGNORECASE),       # Silergy SYxxxx
]

# Value patterns that indicate SMPS-related passives
_INDUCTOR_REF_PATTERN = re.compile(r"^L\d+", re.IGNORECASE)
_CAP_REF_PATTERN = re.compile(r"^C\d+", re.IGNORECASE)


def _distance_mm(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance between two points in mm."""
    dx = x2 - x1
    dy = y2 - y1
    return math.sqrt(dx * dx + dy * dy)


def _triangle_area(p1: Tuple[float, float], p2: Tuple[float, float],
                    p3: Tuple[float, float]) -> float:
    """Area of triangle formed by three points using the shoelace formula."""
    return 0.5 * abs(
        (p2[0] - p1[0]) * (p3[1] - p1[1]) -
        (p3[0] - p1[0]) * (p2[1] - p1[1])
    )


def _is_smps_ic(comp: Any) -> bool:
    """Check if a component looks like an SMPS IC."""
    for attr in ("part_number", "value"):
        val = getattr(comp, attr, None)
        if not val:
            continue
        for pat in _SMPS_PATTERNS:
            if pat.search(val):
                return True
    return False


def _is_inductor(comp: Any) -> bool:
    """Check if a component is an inductor by reference designator."""
    ref = getattr(comp, "reference", "")
    return bool(_INDUCTOR_REF_PATTERN.match(ref))


def _is_capacitor(comp: Any) -> bool:
    """Check if a component is a capacitor by reference designator."""
    ref = getattr(comp, "reference", "")
    return bool(_CAP_REF_PATTERN.match(ref))


def _find_nearest(ic_x: float, ic_y: float, candidates: List[Any],
                  max_radius: float) -> Optional[Any]:
    """Find the nearest candidate component within max_radius."""
    best = None
    best_dist = max_radius + 1.0
    for comp in candidates:
        cx = getattr(comp, "x_mm", 0.0)
        cy = getattr(comp, "y_mm", 0.0)
        d = _distance_mm(ic_x, ic_y, cx, cy)
        if d < best_dist:
            best_dist = d
            best = comp
    return best if best_dist <= max_radius else None


class SMPSLoopAnalyzer:
    """Analyze SMPS switching loop areas from component placement.

    The hot loop (IC -> input cap -> inductor -> IC) carries high di/dt
    switching current. Its area directly determines conducted and radiated
    emissions. This analyzer estimates loop area from component centroids.
    """

    def analyze(
        self,
        design: Any,
        classified_nets: Any = None,
        interfaces: Any = None,
    ) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []

        components = getattr(design, "components", [])
        if not components:
            return findings

        # Identify SMPS ICs
        smps_ics = [c for c in components if _is_smps_ic(c)]
        if not smps_ics:
            return findings

        # Pre-collect inductors and capacitors
        inductors = [c for c in components if _is_inductor(c)]
        capacitors = [c for c in components if _is_capacitor(c)]

        if not inductors and not capacitors:
            findings.append({
                "severity": "info",
                "category": "emc",
                "description": (
                    f"Found {len(smps_ics)} SMPS IC(s) but no inductors or "
                    "capacitors identified for loop analysis."
                ),
                "recommendation": (
                    "Ensure inductor and capacitor reference designators follow "
                    "standard conventions (L*, C*) for automated analysis."
                ),
                "details": {
                    "smps_ics": [
                        {"reference": c.reference,
                         "value": getattr(c, "value", None),
                         "part_number": getattr(c, "part_number", None)}
                        for c in smps_ics
                    ],
                },
            })
            return findings

        for ic in smps_ics:
            ic_x = getattr(ic, "x_mm", 0.0)
            ic_y = getattr(ic, "y_mm", 0.0)
            ic_ref = getattr(ic, "reference", "?")
            ic_pn = getattr(ic, "part_number", None) or getattr(ic, "value", "unknown")

            # Find nearest inductor
            nearest_inductor = _find_nearest(ic_x, ic_y, inductors, _MAX_ASSOCIATION_RADIUS_MM)
            # Find nearest input capacitor (closest cap to IC)
            nearest_cap = _find_nearest(ic_x, ic_y, capacitors, _MAX_ASSOCIATION_RADIUS_MM)

            if not nearest_inductor and not nearest_cap:
                findings.append({
                    "severity": "info",
                    "category": "emc",
                    "description": (
                        f"SMPS IC {ic_ref} ({ic_pn}): no inductor or capacitor "
                        f"found within {_MAX_ASSOCIATION_RADIUS_MM}mm."
                    ),
                    "recommendation": (
                        "Place the input capacitor and inductor as close as possible "
                        "to the SMPS IC to minimize switching loop area."
                    ),
                    "details": {
                        "ic_reference": ic_ref,
                        "ic_part": ic_pn,
                        "ic_position_mm": {"x": round(ic_x, 2), "y": round(ic_y, 2)},
                    },
                })
                continue

            # Compute loop area estimate
            # If we have all 3 points: triangle area (IC, inductor, input cap)
            # If we have 2 points: use rectangular estimate with typical trace width
            ic_pos = (ic_x, ic_y)
            loop_area_mm2 = 0.0
            loop_description = ""

            if nearest_inductor and nearest_cap:
                ind_x = getattr(nearest_inductor, "x_mm", 0.0)
                ind_y = getattr(nearest_inductor, "y_mm", 0.0)
                cap_x = getattr(nearest_cap, "x_mm", 0.0)
                cap_y = getattr(nearest_cap, "y_mm", 0.0)

                loop_area_mm2 = _triangle_area(
                    ic_pos, (ind_x, ind_y), (cap_x, cap_y)
                )
                d_ic_ind = _distance_mm(ic_x, ic_y, ind_x, ind_y)
                d_ic_cap = _distance_mm(ic_x, ic_y, cap_x, cap_y)
                d_ind_cap = _distance_mm(ind_x, ind_y, cap_x, cap_y)

                loop_description = (
                    f"Triangle: {ic_ref}->{nearest_inductor.reference}"
                    f"->{nearest_cap.reference}"
                )
                detail_distances = {
                    "ic_to_inductor_mm": round(d_ic_ind, 2),
                    "ic_to_cap_mm": round(d_ic_cap, 2),
                    "inductor_to_cap_mm": round(d_ind_cap, 2),
                }
            elif nearest_inductor:
                ind_x = getattr(nearest_inductor, "x_mm", 0.0)
                ind_y = getattr(nearest_inductor, "y_mm", 0.0)
                d = _distance_mm(ic_x, ic_y, ind_x, ind_y)
                # Rectangular estimate: distance * typical trace spacing (0.5mm)
                loop_area_mm2 = d * 0.5
                loop_description = f"Estimated: {ic_ref}->{nearest_inductor.reference} (no cap found)"
                detail_distances = {"ic_to_inductor_mm": round(d, 2)}
            else:
                cap_x = getattr(nearest_cap, "x_mm", 0.0)
                cap_y = getattr(nearest_cap, "y_mm", 0.0)
                d = _distance_mm(ic_x, ic_y, cap_x, cap_y)
                loop_area_mm2 = d * 0.5
                loop_description = f"Estimated: {ic_ref}->{nearest_cap.reference} (no inductor found)"
                detail_distances = {"ic_to_cap_mm": round(d, 2)}

            # Determine severity
            if loop_area_mm2 >= _LOOP_AREA_CRITICAL_MM2:
                severity = "critical"
            elif loop_area_mm2 >= _LOOP_AREA_WARNING_MM2:
                severity = "warning"
            else:
                severity = "info"

            details: Dict[str, Any] = {
                "ic_reference": ic_ref,
                "ic_part": ic_pn,
                "ic_position_mm": {"x": round(ic_x, 2), "y": round(ic_y, 2)},
                "loop_area_mm2": round(loop_area_mm2, 1),
                "loop_geometry": loop_description,
                **detail_distances,
            }
            if nearest_inductor:
                details["inductor"] = {
                    "reference": nearest_inductor.reference,
                    "value": getattr(nearest_inductor, "value", None),
                    "position_mm": {
                        "x": round(getattr(nearest_inductor, "x_mm", 0.0), 2),
                        "y": round(getattr(nearest_inductor, "y_mm", 0.0), 2),
                    },
                }
            if nearest_cap:
                details["input_capacitor"] = {
                    "reference": nearest_cap.reference,
                    "value": getattr(nearest_cap, "value", None),
                    "position_mm": {
                        "x": round(getattr(nearest_cap, "x_mm", 0.0), 2),
                        "y": round(getattr(nearest_cap, "y_mm", 0.0), 2),
                    },
                }

            findings.append({
                "severity": severity,
                "category": "emc",
                "description": (
                    f"SMPS {ic_ref} ({ic_pn}) switching loop area: "
                    f"{loop_area_mm2:.1f}mm2. "
                    + (
                        "Loop area is excessive -- expect significant EMI."
                        if severity == "critical"
                        else "Loop area is elevated -- review placement."
                        if severity == "warning"
                        else "Loop area appears acceptable."
                    )
                ),
                "recommendation": (
                    "Minimize the high di/dt switching loop by placing the input "
                    "capacitor and inductor immediately adjacent to the IC. Use "
                    "short, wide traces or direct pad-to-pad routing. Keep the "
                    "loop on a single layer with an unbroken ground return directly "
                    "underneath."
                ),
                "details": details,
            })

        return findings

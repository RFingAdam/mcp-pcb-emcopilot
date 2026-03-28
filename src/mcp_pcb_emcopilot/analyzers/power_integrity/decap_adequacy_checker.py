"""
Per-IC decoupling capacitor adequacy checker.

Verifies that each IC has adequate bypass capacitors on its power pins
within acceptable proximity (typically <2mm for BGA, <3mm for QFP).
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple

# Component patterns for ICs that need decoupling
_IC_PATTERNS = [
    r'(?i)^U\d+',  # All U-prefixed (ICs)
]

# Capacitor patterns
_CAP_PATTERNS = [
    r'(?i)^C\d+',  # C1, C2, C100
]

# Power net patterns — nets that need decoupling
_POWER_NET_KEYWORDS = {
    'VCC', 'VDD', 'AVDD', 'DVDD', 'PVDD', 'VCCO', 'VDDI', 'NVCC',
    'BUCK', 'LDO', '3P3V', '1P8V', '1V8', '3V3', '5V', '1V0', '1V1',
}

# Proximity thresholds (mm)
MAX_DECAP_DISTANCE_BGA = 2.0   # BGA packages — tight routing
MAX_DECAP_DISTANCE_QFP = 3.0   # QFP/SOIC — more relaxed
MAX_DECAP_DISTANCE_DEFAULT = 2.5


def _is_ic(comp: Any) -> bool:
    """Check if component is an IC."""
    return any(re.match(p, comp.reference) for p in _IC_PATTERNS)


def _is_cap(comp: Any) -> bool:
    """Check if component is a capacitor."""
    return any(re.match(p, comp.reference) for p in _CAP_PATTERNS)


def _is_power_net(net_name: str) -> bool:
    """Check if net name looks like a power rail."""
    upper = net_name.upper()
    return any(kw in upper for kw in _POWER_NET_KEYWORDS)


def _distance(c1: Any, c2: Any) -> float:
    """Euclidean distance between two component centers."""
    return math.sqrt((c1.x_mm - c2.x_mm) ** 2 + (c1.y_mm - c2.y_mm) ** 2)


def _estimate_package_type(comp: Any) -> str:
    """Estimate package type from footprint/package string."""
    fp = (getattr(comp, 'footprint', '') or getattr(comp, 'package', '') or '').upper()
    if any(kw in fp for kw in ('BGA', 'CSP', 'WLCSP', 'FBGA')):
        return 'bga'
    if any(kw in fp for kw in ('QFP', 'QFN', 'SOIC', 'SSOP', 'TSSOP', 'LQFP')):
        return 'qfp'
    # If component has many nearby GND vias, likely BGA
    return 'unknown'


class DecapAdequacyChecker:
    """Checks that each IC has adequate bypass capacitors nearby."""

    def analyze(
        self,
        design: Any,
        classified_nets: Any = None,
        interfaces: Any = None,
    ) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []

        ics = [c for c in design.components if _is_ic(c)]
        caps = [c for c in design.components if _is_cap(c)]

        if not ics:
            return findings

        # Build net-to-component map for power nets
        power_nets: Set[str] = set()
        if classified_nets:
            for nc in classified_nets.classified_nets:
                if nc.category == 'power':
                    power_nets.add(nc.net_name)

        # For each IC, find nearby capacitors
        ics_without_decap = []
        ics_with_distant_decap = []

        for ic in ics:
            pkg_type = _estimate_package_type(ic)
            max_dist = {
                'bga': MAX_DECAP_DISTANCE_BGA,
                'qfp': MAX_DECAP_DISTANCE_QFP,
            }.get(pkg_type, MAX_DECAP_DISTANCE_DEFAULT)

            # Find all caps within max distance
            nearby_caps = []
            for cap in caps:
                d = _distance(ic, cap)
                if d <= max_dist:
                    nearby_caps.append((cap, d))

            # Also check within a larger radius for any caps
            wider_caps = []
            for cap in caps:
                d = _distance(ic, cap)
                if d <= max_dist * 2:
                    wider_caps.append((cap, d))

            if not nearby_caps and not wider_caps:
                ics_without_decap.append(ic)
            elif not nearby_caps and wider_caps:
                nearest = min(wider_caps, key=lambda x: x[1])
                ics_with_distant_decap.append((ic, nearest[0], nearest[1], max_dist))

        # Report findings
        if ics_without_decap:
            # Only report ICs with significant power consumption
            # (skip simple ICs like level translators, ESD diodes)
            significant = [ic for ic in ics_without_decap
                          if not any(kw in (ic.value or '').upper()
                                    for kw in ('ESD', 'TVS', 'DIODE', 'LED'))]
            if significant:
                refs = [ic.reference for ic in significant[:10]]
                findings.append({
                    "severity": "warning" if len(significant) <= 3 else "critical",
                    "category": "decap_missing",
                    "description": (
                        f"{len(significant)} IC(s) have no bypass capacitor within "
                        f"recommended distance: {', '.join(refs)}"
                        f"{'...' if len(significant) > 10 else ''}"
                    ),
                    "recommendation": (
                        "Add 100nF (or 220nF) ceramic capacitor within 2mm of each "
                        "IC power pin. For BGA packages, place caps on the opposite "
                        "side of the board directly under the IC."
                    ),
                    "details": {
                        "count": len(significant),
                        "components": [ic.reference for ic in significant],
                    },
                })

        for ic, nearest_cap, dist, max_d in ics_with_distant_decap[:5]:
            findings.append({
                "severity": "info",
                "category": "decap_distance",
                "description": (
                    f"{ic.reference}: nearest cap {nearest_cap.reference} "
                    f"({nearest_cap.value}) is {dist:.1f}mm away "
                    f"(recommended <{max_d:.0f}mm)"
                ),
                "recommendation": (
                    f"Move bypass cap closer to {ic.reference} or add additional "
                    f"cap within {max_d:.0f}mm of IC power pins."
                ),
                "details": {
                    "ic": ic.reference,
                    "nearest_cap": nearest_cap.reference,
                    "distance_mm": round(dist, 2),
                    "threshold_mm": max_d,
                },
            })

        # Summary
        total_ics = len(ics)
        with_nearby = total_ics - len(ics_without_decap) - len(ics_with_distant_decap)
        findings.append({
            "severity": "info",
            "category": "decap_summary",
            "description": (
                f"Decoupling check: {total_ics} ICs, {with_nearby} with nearby caps, "
                f"{len(ics_with_distant_decap)} distant, {len(ics_without_decap)} missing"
            ),
            "recommendation": "",
            "details": {
                "total_ics": total_ics,
                "total_caps": len(caps),
                "with_nearby_decap": with_nearby,
                "distant_decap": len(ics_with_distant_decap),
                "missing_decap": len(ics_without_decap),
            },
        })

        return findings

"""
GNSS RF Path Analyzer.

Analyzes GNSS receiver RF path routing for compliance:
- L1 (1575.42 MHz) and L5 (1176.45 MHz) band support
- Antenna-to-LNA trace length (< 10mm)
- Ground plane integrity under GNSS antenna
- Digital noise isolation (no high-speed traces nearby)
- PPS signal routing (low jitter)
- Switching regulator EMI proximity check
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Optional

from ...models.pcb_data import PCBDesignData

logger = logging.getLogger(__name__)

# GNSS frequency bands
GNSS_BANDS: Dict[str, Dict[str, Any]] = {
    "L1": {
        "frequency_mhz": 1575.42,
        "wavelength_mm": 190.3,
        "description": "GPS/GLONASS/Galileo/BeiDou L1/E1/B1",
    },
    "L5": {
        "frequency_mhz": 1176.45,
        "wavelength_mm": 254.9,
        "description": "GPS L5/Galileo E5a",
    },
}

# Design rule limits
MAX_ANT_TO_LNA_MM = 10.0           # Antenna pad to LNA input
LNA_TO_RECEIVER_MAX_MM = 25.0      # LNA output to GNSS receiver input
DIGITAL_NOISE_CLEARANCE_MM = 5.0   # Min distance from high-speed digital
SMPS_CLEARANCE_MM = 15.0           # Min distance from switching regulators
PPS_MAX_LENGTH_MM = 80.0           # PPS signal max trace length
TARGET_IMPEDANCE_OHM = 50
IMPEDANCE_TOLERANCE_PCT = 10
ANTENNA_GND_CLEARANCE_MM = 8.0     # Ground plane clearance under patch antenna

# Component detection patterns
GNSS_RECEIVER_PATTERNS = [
    r"(?i)gps", r"(?i)gnss", r"(?i)u-?blox", r"(?i)neo-?[m6789]",
    r"(?i)max-?[m8]", r"(?i)sam-?m[0-9]", r"(?i)zed-?f9",
    r"(?i)l[0-9]+[a-z].*gnss", r"(?i)quectel.*l[0-9]",
    r"(?i)unicore", r"(?i)ag335[0-9]",
]

LNA_PATTERNS = [
    r"(?i)lna", r"(?i)low.?noise", r"(?i)gps.*amp",
    r"(?i)gnss.*amp", r"(?i)saw.*lna",
]

SMPS_PATTERNS = [
    r"(?i)buck", r"(?i)boost", r"(?i)dc.?dc", r"(?i)switch.*reg",
    r"(?i)tps6[0-9]", r"(?i)mp[0-9]{4}", r"(?i)lm[0-9]{4}",
    r"(?i)rt[0-9]{4}", r"(?i)inductor", r"(?i)^l[0-9]+$",
]

GNSS_ANTENNA_PATTERNS = [
    r"(?i)gps.*ant", r"(?i)gnss.*ant", r"(?i)ant.*gps",
    r"(?i)ant.*gnss", r"(?i)patch.*ant", r"(?i)ant.*l1",
]

# Net patterns
GNSS_RF_NET_PATTERNS = [
    r"(?i)gps.*rf", r"(?i)gnss.*rf", r"(?i)rf.*gps",
    r"(?i)gnss.*ant", r"(?i)gps.*ant", r"(?i)lna.*in",
    r"(?i)lna.*out", r"(?i)gnss.*in",
]

PPS_NET_PATTERNS = [
    r"(?i)pps", r"(?i)1pps", r"(?i)gps.*pps",
    r"(?i)gnss.*pps", r"(?i)time.*pulse",
]

HIGH_SPEED_DIGITAL_PATTERNS = [
    r"(?i)usb", r"(?i)pcie", r"(?i)ddr", r"(?i)eth",
    r"(?i)mipi", r"(?i)lvds", r"(?i)hdmi",
]


def _component_matches(comp, patterns: list) -> bool:
    """Check if component matches any pattern."""
    combined = f"{comp.reference} {comp.part_number or ''} {comp.value or ''} {comp.footprint or ''}".lower()
    return any(re.search(p, combined) for p in patterns)


def _net_matches(net_name: str, patterns: list) -> bool:
    """Check if net name matches any pattern."""
    return any(re.search(p, net_name) for p in patterns)


def _get_net_total_length(design: PCBDesignData, net_name: str) -> float:
    """Sum trace lengths for a net."""
    total = 0.0
    for trace in design.traces:
        if trace.net_name and trace.net_name.lower() == net_name.lower():
            total += trace.length_mm if trace.length_mm else trace.calc_length()
    return total


def _distance_2d(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance between two points."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


class GNSSAnalyzer:
    """
    GNSS RF path analyzer.

    Validates GNSS antenna-to-receiver routing, LNA placement,
    noise isolation, and PPS signal integrity.

    Usage:
        analyzer = GNSSAnalyzer()
        findings = analyzer.analyze(design, classified_nets, interfaces)
    """

    def __init__(self):
        pass

    def analyze(
        self,
        design: PCBDesignData,
        classified_nets: Any = None,
        interfaces: Any = None,
    ) -> List[Dict[str, Any]]:
        """Analyze GNSS RF path routing.

        Args:
            design: Parsed PCB design data.
            classified_nets: Optional NetClassificationResult.
            interfaces: Optional detected interfaces dict.

        Returns:
            List of finding dicts.
        """
        findings: List[Dict[str, Any]] = []

        # --- Detect GNSS components ---
        gnss_receivers = [c for c in design.components if _component_matches(c, GNSS_RECEIVER_PATTERNS)]
        lna_comps = [c for c in design.components if _component_matches(c, LNA_PATTERNS)]
        gnss_antennas = [c for c in design.components if _component_matches(c, GNSS_ANTENNA_PATTERNS)]
        smps_comps = [c for c in design.components if _component_matches(c, SMPS_PATTERNS)]

        # --- Detect GNSS nets ---
        gnss_rf_nets = [n.name for n in design.nets if _net_matches(n.name, GNSS_RF_NET_PATTERNS)]
        pps_nets = [n.name for n in design.nets if _net_matches(n.name, PPS_NET_PATTERNS)]

        # Also check classified_nets for GNSS-related signals
        if classified_nets is not None:
            for nc in getattr(classified_nets, "classified_nets", []):
                if nc.category == "rf" and nc.subcategory in ("gnss", "gps"):
                    if nc.net_name not in gnss_rf_nets and nc.net_name not in pps_nets:
                        if "pps" in nc.net_name.lower() or "1pps" in nc.net_name.lower():
                            pps_nets.append(nc.net_name)
                        else:
                            gnss_rf_nets.append(nc.net_name)

        if not gnss_receivers and not gnss_rf_nets and not pps_nets:
            findings.append({
                "severity": "info",
                "category": "gnss",
                "description": "No GNSS receiver or RF nets detected in design",
                "recommendation": "Verify component naming if GNSS is expected",
                "details": {"receivers_found": 0, "rf_nets_found": 0},
            })
            return findings

        findings.append({
            "severity": "info",
            "category": "gnss",
            "description": (
                f"GNSS subsystem detected: {len(gnss_receivers)} receiver(s), "
                f"{len(lna_comps)} LNA(s), {len(gnss_antennas)} antenna(s), "
                f"{len(gnss_rf_nets)} RF net(s), {len(pps_nets)} PPS net(s)"
            ),
            "recommendation": "",
            "details": {
                "receivers": [r.reference for r in gnss_receivers],
                "lnas": [l.reference for l in lna_comps],
                "antennas": [a.reference for a in gnss_antennas],
                "rf_nets": gnss_rf_nets,
                "pps_nets": pps_nets,
                "bands": GNSS_BANDS,
            },
        })

        # --- Antenna-to-LNA trace length ---
        for net_name in gnss_rf_nets:
            rf_length = _get_net_total_length(design, net_name)
            if rf_length > MAX_ANT_TO_LNA_MM:
                findings.append({
                    "severity": "critical",
                    "category": "gnss_rf_trace_length",
                    "description": (
                        f"GNSS RF trace {net_name} length {rf_length:.1f}mm exceeds "
                        f"recommended {MAX_ANT_TO_LNA_MM}mm antenna-to-LNA limit"
                    ),
                    "recommendation": (
                        f"Keep GNSS antenna-to-LNA trace under {MAX_ANT_TO_LNA_MM}mm. "
                        "Every mm of trace adds ~0.03dB loss at L1, degrading sensitivity. "
                        "Place LNA immediately adjacent to antenna feed."
                    ),
                    "details": {
                        "net": net_name,
                        "length_mm": round(rf_length, 2),
                        "limit_mm": MAX_ANT_TO_LNA_MM,
                    },
                })

        # --- LNA placement check ---
        if gnss_receivers and not lna_comps:
            # Check if receiver has integrated LNA
            has_integrated_lna = any(
                "lna" in (c.part_number or "").lower() or "active" in (c.value or "").lower()
                for c in gnss_antennas
            )
            if not has_integrated_lna:
                findings.append({
                    "severity": "warning",
                    "category": "gnss_lna",
                    "description": "No discrete LNA detected for GNSS RF path",
                    "recommendation": (
                        "Verify that either an active antenna (with integrated LNA) "
                        "or a discrete LNA is used. Passive antenna without LNA "
                        "will have poor sensitivity in noisy environments."
                    ),
                    "details": {},
                })

        # --- Ground plane integrity under GNSS antenna ---
        ground_zones = [z for z in design.zones if z.net_name and "gnd" in z.net_name.lower()]
        if gnss_antennas and not ground_zones:
            findings.append({
                "severity": "critical",
                "category": "gnss_ground_plane",
                "description": (
                    "No ground zones detected - GNSS antenna requires "
                    "solid ground plane for proper radiation pattern"
                ),
                "recommendation": (
                    "A GNSS patch antenna requires a solid ground plane of at least "
                    "70x70mm underneath it. No voids, splits, or routing under the antenna."
                ),
                "details": {},
            })

        # --- Digital noise isolation ---
        hs_digital_nets = [
            n.name for n in design.nets
            if _net_matches(n.name, HIGH_SPEED_DIGITAL_PATTERNS)
        ]

        if gnss_receivers and hs_digital_nets:
            for receiver in gnss_receivers:
                nearby_hs_traces = []
                for trace in design.traces:
                    if trace.net_name and _net_matches(trace.net_name, HIGH_SPEED_DIGITAL_PATTERNS):
                        # Check if trace passes near GNSS receiver
                        d1 = _distance_2d(receiver.x_mm, receiver.y_mm, trace.x1_mm, trace.y1_mm)
                        d2 = _distance_2d(receiver.x_mm, receiver.y_mm, trace.x2_mm, trace.y2_mm)
                        min_dist = min(d1, d2)
                        if min_dist < DIGITAL_NOISE_CLEARANCE_MM:
                            nearby_hs_traces.append({
                                "net": trace.net_name,
                                "distance_mm": round(min_dist, 2),
                            })

                if nearby_hs_traces:
                    # Deduplicate by net name
                    seen = set()
                    unique_traces = []
                    for t in nearby_hs_traces:
                        if t["net"] not in seen:
                            seen.add(t["net"])
                            unique_traces.append(t)

                    findings.append({
                        "severity": "warning",
                        "category": "gnss_digital_noise",
                        "description": (
                            f"GNSS receiver {receiver.reference} has {len(unique_traces)} "
                            f"high-speed digital trace(s) within {DIGITAL_NOISE_CLEARANCE_MM}mm"
                        ),
                        "recommendation": (
                            f"Route high-speed digital signals (USB, PCIe, DDR, Ethernet) "
                            f"at least {DIGITAL_NOISE_CLEARANCE_MM}mm away from GNSS receiver. "
                            "Digital noise can desensitize the GNSS front end by several dB."
                        ),
                        "details": {
                            "receiver": receiver.reference,
                            "nearby_traces": unique_traces[:10],
                            "clearance_mm": DIGITAL_NOISE_CLEARANCE_MM,
                        },
                    })

        # --- PPS signal routing ---
        for pps_net in pps_nets:
            pps_length = _get_net_total_length(design, pps_net)
            if pps_length > PPS_MAX_LENGTH_MM:
                findings.append({
                    "severity": "warning",
                    "category": "gnss_pps",
                    "description": (
                        f"PPS signal {pps_net} length {pps_length:.1f}mm exceeds "
                        f"recommended {PPS_MAX_LENGTH_MM}mm for low jitter"
                    ),
                    "recommendation": (
                        "Keep PPS trace short and direct. Avoid layer transitions. "
                        "Route away from switching noise sources."
                    ),
                    "details": {
                        "net": pps_net,
                        "length_mm": round(pps_length, 2),
                        "limit_mm": PPS_MAX_LENGTH_MM,
                    },
                })

        # --- Switching regulator EMI proximity ---
        for receiver in gnss_receivers:
            nearby_smps = []
            for smps in smps_comps:
                dist = _distance_2d(receiver.x_mm, receiver.y_mm, smps.x_mm, smps.y_mm)
                if dist < SMPS_CLEARANCE_MM:
                    nearby_smps.append({
                        "reference": smps.reference,
                        "value": smps.value,
                        "distance_mm": round(dist, 2),
                    })

            if nearby_smps:
                findings.append({
                    "severity": "critical" if any(
                        isinstance(s["distance_mm"], (int, float)) and s["distance_mm"] < 8.0
                        for s in nearby_smps
                    ) else "warning",
                    "category": "gnss_smps_emi",
                    "description": (
                        f"GNSS receiver {receiver.reference} has {len(nearby_smps)} "
                        f"switching regulator component(s) within {SMPS_CLEARANCE_MM}mm"
                    ),
                    "recommendation": (
                        f"Switching regulators radiate broadband EMI that desensitizes GNSS. "
                        f"Maintain at least {SMPS_CLEARANCE_MM}mm between GNSS receiver/antenna "
                        "and any SMPS inductor/IC. Use LDO for GNSS supply if possible."
                    ),
                    "details": {
                        "receiver": receiver.reference,
                        "nearby_smps": nearby_smps,
                        "clearance_mm": SMPS_CLEARANCE_MM,
                    },
                })

        # --- RF impedance check ---
        for net_name in gnss_rf_nets:
            for trace in design.traces:
                if trace.net_name and trace.net_name.lower() == net_name.lower():
                    if trace.width_mm < 0.10 or trace.width_mm > 1.5:
                        findings.append({
                            "severity": "warning",
                            "category": "gnss_impedance",
                            "description": (
                                f"GNSS RF trace {net_name} width {trace.width_mm:.3f}mm "
                                f"on {trace.layer} - verify {TARGET_IMPEDANCE_OHM} Ohm impedance"
                            ),
                            "recommendation": (
                                f"GNSS RF path requires {TARGET_IMPEDANCE_OHM} Ohm "
                                "impedance-controlled microstrip. Mismatch causes "
                                "reflection loss degrading receiver sensitivity."
                            ),
                            "details": {
                                "net": net_name,
                                "width_mm": trace.width_mm,
                                "layer": trace.layer,
                                "target_ohm": TARGET_IMPEDANCE_OHM,
                            },
                        })
                    break

        return findings

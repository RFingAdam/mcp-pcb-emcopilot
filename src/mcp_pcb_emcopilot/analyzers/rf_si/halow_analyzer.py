"""
HaLow (802.11ah) Sub-1GHz WiFi Analyzer.

Analyzes HaLow RF path routing for compliance:
- RF trace impedance (50 Ohm)
- Antenna-to-module trace length (< lambda/10)
- Ground plane continuity under RF path
- SAW/BAW filter presence
- Antenna keep-out zone (ground clearance)
- Coupling to WiFi/BLE paths
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Optional

from ...models.pcb_data import PCBDesignData

logger = logging.getLogger(__name__)

# HaLow RF parameters
FREQ_MHZ = 900
WAVELENGTH_MM = 333       # ~333mm at 900MHz (c / f)
MAX_RF_TRACE_MM = 33      # lambda/10 = 33.3mm
TARGET_IMPEDANCE_OHM = 50
IMPEDANCE_TOLERANCE_PCT = 10
ANTENNA_KEEPOUT_MM = 10.0  # Minimum ground clearance around antenna

# Component detection patterns
HALOW_MODULE_PATTERNS = [
    r"(?i)ah\d",           # AH1, AH2, etc.
    r"(?i)halow",
    r"(?i)802\.?11ah",
    r"(?i)if573",          # Common HaLow transceiver ICs
    r"(?i)mm610[0-9]",
    r"(?i)nrc7\d",         # Newracom HaLow ICs
]

ANTENNA_PATTERNS = [
    r"(?i)ant.*halow",
    r"(?i)ant.*900",
    r"(?i)ant.*sub.?g",
    r"(?i)halow.*ant",
    r"(?i)j.*ant.*900",
]

RF_FILTER_PATTERNS = {
    "saw": [r"(?i)saw", r"(?i)surface\s*acoustic"],
    "baw": [r"(?i)baw", r"(?i)bulk\s*acoustic"],
    "lpf": [r"(?i)lpf", r"(?i)low.?pass"],
    "bpf": [r"(?i)bpf", r"(?i)band.?pass.*900", r"(?i)900.*band.?pass"],
}

# Net patterns for HaLow RF signals
HALOW_NET_PATTERNS = [
    r"(?i)halow.*rf",
    r"(?i)rf.*halow",
    r"(?i)ant.*900",
    r"(?i)sub.?g.*rf",
    r"(?i)ah.*rf",
    r"(?i)rf.*900",
    r"(?i)halow.*ant",
]

# WiFi / BLE net patterns for coupling check
WIFI_NET_PATTERNS = [r"(?i)wifi.*rf", r"(?i)wlan.*rf", r"(?i)rf.*2[._]?4", r"(?i)rf.*5g"]
BLE_NET_PATTERNS = [r"(?i)ble.*rf", r"(?i)bt.*rf", r"(?i)bluetooth.*rf"]


def _component_matches(comp, patterns: list) -> bool:
    """Check if component matches any pattern."""
    combined = f"{comp.part_number or ''} {comp.value or ''} {comp.footprint or ''}".lower()
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


def _get_trace_layers(design: PCBDesignData, net_name: str) -> List[str]:
    """Get unique layers used by a net's traces."""
    layers = set()
    for trace in design.traces:
        if trace.net_name and trace.net_name.lower() == net_name.lower():
            layers.add(trace.layer)
    return sorted(layers)


def _distance_2d(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance between two points."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


class HaLowAnalyzer:
    """
    HaLow (802.11ah) sub-1GHz WiFi RF path analyzer.

    Validates RF trace routing, impedance control, filter presence,
    antenna keep-out, and coupling to other radio paths.

    Usage:
        analyzer = HaLowAnalyzer()
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
        """Analyze HaLow RF path routing.

        Args:
            design: Parsed PCB design data.
            classified_nets: Optional NetClassificationResult.
            interfaces: Optional detected interfaces dict.

        Returns:
            List of finding dicts.
        """
        findings: List[Dict[str, Any]] = []

        # --- Detect HaLow modules ---
        halow_modules = [
            comp for comp in design.components
            if _component_matches(comp, HALOW_MODULE_PATTERNS)
        ]

        # --- Detect antenna components ---
        antenna_comps = [
            comp for comp in design.components
            if _component_matches(comp, ANTENNA_PATTERNS)
        ]

        # --- Detect HaLow RF nets ---
        halow_rf_nets: List[str] = []
        for net in design.nets:
            if _net_matches(net.name, HALOW_NET_PATTERNS):
                halow_rf_nets.append(net.name)

        # Also check classified nets
        if classified_nets is not None:
            for nc in getattr(classified_nets, "classified_nets", []):
                if nc.subcategory and "halow" in nc.subcategory.lower():
                    if nc.net_name not in halow_rf_nets:
                        halow_rf_nets.append(nc.net_name)

        if not halow_modules and not halow_rf_nets:
            findings.append({
                "severity": "info",
                "category": "halow",
                "description": "No HaLow (802.11ah) components or RF nets detected",
                "recommendation": "Verify component naming if HaLow radio is expected in design",
                "details": {"modules_found": 0, "rf_nets_found": 0},
            })
            return findings

        findings.append({
            "severity": "info",
            "category": "halow",
            "description": (
                f"HaLow interface detected: {len(halow_modules)} module(s), "
                f"{len(antenna_comps)} antenna(s), {len(halow_rf_nets)} RF net(s)"
            ),
            "recommendation": "",
            "details": {
                "modules": [m.reference for m in halow_modules],
                "antennas": [a.reference for a in antenna_comps],
                "rf_nets": halow_rf_nets,
                "frequency_mhz": FREQ_MHZ,
                "wavelength_mm": WAVELENGTH_MM,
            },
        })

        # --- RF trace impedance check ---
        for net_name in halow_rf_nets:
            for trace in design.traces:
                if trace.net_name and trace.net_name.lower() == net_name.lower():
                    # Flag traces that are likely not 50 Ohm controlled
                    if trace.width_mm < 0.10 or trace.width_mm > 1.5:
                        findings.append({
                            "severity": "warning",
                            "category": "halow_impedance",
                            "description": (
                                f"HaLow RF trace {net_name} width {trace.width_mm:.3f}mm "
                                f"on {trace.layer} - verify {TARGET_IMPEDANCE_OHM} Ohm impedance"
                            ),
                            "recommendation": (
                                f"RF traces must be impedance-controlled to {TARGET_IMPEDANCE_OHM} Ohm "
                                f"+/-{IMPEDANCE_TOLERANCE_PCT}%. Use a stackup impedance calculator."
                            ),
                            "details": {
                                "net": net_name,
                                "width_mm": trace.width_mm,
                                "layer": trace.layer,
                                "target_ohm": TARGET_IMPEDANCE_OHM,
                            },
                        })
                    break  # One check per net

        # --- Antenna-to-module trace length ---
        for net_name in halow_rf_nets:
            rf_length = _get_net_total_length(design, net_name)
            if rf_length > MAX_RF_TRACE_MM:
                findings.append({
                    "severity": "critical",
                    "category": "halow_trace_length",
                    "description": (
                        f"HaLow RF trace {net_name} length {rf_length:.1f}mm exceeds "
                        f"lambda/10 limit of {MAX_RF_TRACE_MM}mm at {FREQ_MHZ}MHz"
                    ),
                    "recommendation": (
                        f"Keep antenna-to-module RF trace under {MAX_RF_TRACE_MM}mm "
                        "to minimize transmission line losses and reflections. "
                        "Place antenna as close to module as possible."
                    ),
                    "details": {
                        "net": net_name,
                        "length_mm": round(rf_length, 2),
                        "limit_mm": MAX_RF_TRACE_MM,
                        "wavelength_mm": WAVELENGTH_MM,
                    },
                })

        # --- Ground plane continuity under RF path ---
        rf_layers = set()
        for net_name in halow_rf_nets:
            rf_layers.update(_get_trace_layers(design, net_name))

        # Check for ground zones on reference layers
        ground_zones = [
            z for z in design.zones
            if z.net_name and "gnd" in z.net_name.lower()
        ]

        if rf_layers and not ground_zones:
            findings.append({
                "severity": "critical",
                "category": "halow_ground_plane",
                "description": (
                    "No ground plane zones detected - HaLow RF path requires "
                    "continuous ground plane on adjacent layer"
                ),
                "recommendation": (
                    "Ensure a solid, unbroken ground plane exists on the layer "
                    "adjacent to the HaLow RF trace. No splits or voids under the RF path."
                ),
                "details": {"rf_layers": list(rf_layers)},
            })

        # --- SAW/BAW filter presence ---
        filters_found: Dict[str, List[str]] = {}
        for comp in design.components:
            for ftype, patterns in RF_FILTER_PATTERNS.items():
                if _component_matches(comp, patterns):
                    filters_found.setdefault(ftype, []).append(comp.reference)

        if not filters_found:
            findings.append({
                "severity": "warning",
                "category": "halow_filter",
                "description": (
                    "No SAW/BAW/BPF filter detected in HaLow RF path — "
                    "both TX and RX paths require filtering"
                ),
                "recommendation": (
                    "Sub-1GHz ISM TX path MUST have a bandpass filter to suppress "
                    "harmonics: 2nd harmonic (1.8GHz) falls in cellular bands, "
                    "3rd harmonic (2.7GHz) near WiFi 5GHz. Without TX filtering, "
                    "FCC Part 15.247 / ETSI EN 300 220 spurious emission limits "
                    "will likely fail. RX-only filtering protects receiver "
                    "sensitivity but does NOT address radiated TX emissions. "
                    "Add a SAW/BAW bandpass filter centered at 900MHz with "
                    "<2dB insertion loss on both TX and RX paths."
                ),
                "details": {"filters_detected": {}},
            })
        else:
            findings.append({
                "severity": "info",
                "category": "halow_filter",
                "description": f"RF filters detected: {filters_found}",
                "recommendation": "",
                "details": {"filters_detected": filters_found},
            })

        # --- Antenna keep-out zone ---
        for ant in antenna_comps:
            nearby_components = []
            for comp in design.components:
                if comp.reference == ant.reference:
                    continue
                dist = _distance_2d(ant.x_mm, ant.y_mm, comp.x_mm, comp.y_mm)
                if dist < ANTENNA_KEEPOUT_MM:
                    nearby_components.append({
                        "reference": comp.reference,
                        "distance_mm": round(dist, 2),
                    })

            if nearby_components:
                findings.append({
                    "severity": "warning",
                    "category": "halow_antenna_keepout",
                    "description": (
                        f"HaLow antenna {ant.reference} has {len(nearby_components)} "
                        f"component(s) within {ANTENNA_KEEPOUT_MM}mm keep-out zone"
                    ),
                    "recommendation": (
                        f"Maintain at least {ANTENNA_KEEPOUT_MM}mm ground clearance "
                        "around the antenna. No copper pours, traces, or components "
                        "in the antenna keep-out area."
                    ),
                    "details": {
                        "antenna": ant.reference,
                        "nearby": nearby_components,
                        "keepout_mm": ANTENNA_KEEPOUT_MM,
                    },
                })

        # --- Coupling to WiFi/BLE paths ---
        wifi_nets = [n.name for n in design.nets if _net_matches(n.name, WIFI_NET_PATTERNS)]
        ble_nets = [n.name for n in design.nets if _net_matches(n.name, BLE_NET_PATTERNS)]

        coupled_radios = []
        if wifi_nets:
            coupled_radios.append(f"WiFi ({len(wifi_nets)} nets)")
        if ble_nets:
            coupled_radios.append(f"BLE ({len(ble_nets)} nets)")

        if coupled_radios and halow_rf_nets:
            findings.append({
                "severity": "warning",
                "category": "halow_coupling",
                "description": (
                    f"HaLow RF path shares board with {', '.join(coupled_radios)} - "
                    "verify routing separation"
                ),
                "recommendation": (
                    "Maintain minimum 5mm separation between HaLow sub-1GHz RF traces "
                    "and WiFi/BLE 2.4GHz paths. Use ground stitching vias between "
                    "RF domains to improve isolation."
                ),
                "details": {
                    "halow_nets": halow_rf_nets,
                    "wifi_nets": wifi_nets,
                    "ble_nets": ble_nets,
                },
            })

        return findings

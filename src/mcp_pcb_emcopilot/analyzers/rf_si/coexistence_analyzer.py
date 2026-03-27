"""
Multi-Radio Coexistence Analyzer.

Analyzes multi-radio PCB designs for coexistence issues:
- Coexistence bus signal detection (GRANT/PRIORITY/REQUEST)
- Antenna isolation between radios
- Shared antenna switching (RF switch placement)
- Routing separation between RF paths
- Intermodulation product analysis
- Ground plane partitioning
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from ...models.pcb_data import PCBDesignData

logger = logging.getLogger(__name__)

# Required antenna isolation between radio pairs (dB)
ISOLATION_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "wifi_ble": {
        "isolation_db": 10,
        "description": "WiFi <-> BLE",
        "freq_a_mhz": 2440,
        "freq_b_mhz": 2440,
    },
    "wifi_halow": {
        "isolation_db": 20,
        "description": "WiFi 2.4GHz <-> HaLow 900MHz",
        "freq_a_mhz": 2440,
        "freq_b_mhz": 900,
    },
    "lte_gnss": {
        "isolation_db": 30,
        "description": "LTE <-> GNSS",
        "freq_a_mhz": 1800,
        "freq_b_mhz": 1575,
    },
    "wifi5_wifi2": {
        "isolation_db": 15,
        "description": "WiFi 5GHz <-> WiFi 2.4GHz",
        "freq_a_mhz": 5500,
        "freq_b_mhz": 2440,
    },
    "lte_wifi": {
        "isolation_db": 20,
        "description": "LTE <-> WiFi",
        "freq_a_mhz": 1800,
        "freq_b_mhz": 2440,
    },
}

# Minimum distance for antenna isolation estimate (mm -> ~dB)
# Rough free-space model: isolation_dB ~ 20*log10(4*pi*d/lambda)
MIN_ANTENNA_SEPARATION_MM = 20.0

# Coexistence bus signal patterns
COEX_PATTERNS = {
    "grant": [r"(?i)coex.*grant", r"(?i)wlan.*grant", r"(?i)bt.*grant"],
    "priority": [r"(?i)coex.*pri", r"(?i)wlan.*pri", r"(?i)bt.*pri", r"(?i)priority"],
    "request": [r"(?i)coex.*req", r"(?i)wlan.*req", r"(?i)bt.*req"],
    "status": [r"(?i)coex.*stat", r"(?i)coex.*act"],
    "tx_active": [r"(?i)tx.*act", r"(?i)pa.*en", r"(?i)rf.*act"],
}

# Radio detection patterns (component-level)
RADIO_PATTERNS: Dict[str, List[str]] = {
    "wifi": [
        r"(?i)wifi", r"(?i)wlan", r"(?i)802\.?11[abgnac]",
        r"(?i)qca[0-9]", r"(?i)cyw[0-9]", r"(?i)esp32",
        r"(?i)nrf70", r"(?i)cc3[12]",
    ],
    "ble": [
        r"(?i)ble", r"(?i)bluetooth", r"(?i)nrf5[0-9]",
        r"(?i)cc26[0-9]", r"(?i)cyw[0-9].*bt",
    ],
    "halow": [
        r"(?i)halow", r"(?i)802\.?11ah", r"(?i)nrc7",
        r"(?i)if573", r"(?i)mm610",
    ],
    "lte": [
        r"(?i)lte", r"(?i)4g", r"(?i)cat.?[m1]",
        r"(?i)quectel.*bg", r"(?i)simcom", r"(?i)telit",
        r"(?i)sara-?r", r"(?i)modem",
    ],
    "gnss": [
        r"(?i)gps", r"(?i)gnss", r"(?i)u-?blox",
        r"(?i)neo-?m", r"(?i)zed-?f",
    ],
    "zigbee": [
        r"(?i)zigbee", r"(?i)802\.?15\.?4", r"(?i)thread",
        r"(?i)cc2652", r"(?i)efr32",
    ],
    "uwb": [
        r"(?i)uwb", r"(?i)ultra.?wide", r"(?i)dw[0-9]{4}",
        r"(?i)nxp.*sr",
    ],
}

# RF net patterns by radio type
RF_NET_PATTERNS: Dict[str, List[str]] = {
    "wifi": [r"(?i)wifi.*rf", r"(?i)wlan.*rf", r"(?i)rf.*2[._]?4", r"(?i)rf.*5g"],
    "ble": [r"(?i)ble.*rf", r"(?i)bt.*rf", r"(?i)bluetooth.*rf"],
    "halow": [r"(?i)halow.*rf", r"(?i)sub.?g.*rf", r"(?i)rf.*900"],
    "lte": [r"(?i)lte.*rf", r"(?i)cell.*rf", r"(?i)modem.*rf", r"(?i)4g.*rf"],
    "gnss": [r"(?i)gps.*rf", r"(?i)gnss.*rf", r"(?i)gnss.*ant"],
}

# Antenna patterns by radio type
ANTENNA_NET_PATTERNS: Dict[str, List[str]] = {
    "wifi": [r"(?i)wifi.*ant", r"(?i)wlan.*ant", r"(?i)ant.*wifi"],
    "ble": [r"(?i)ble.*ant", r"(?i)bt.*ant", r"(?i)ant.*ble"],
    "halow": [r"(?i)halow.*ant", r"(?i)ant.*900", r"(?i)ant.*sub"],
    "lte": [r"(?i)lte.*ant", r"(?i)cell.*ant", r"(?i)ant.*lte"],
    "gnss": [r"(?i)gps.*ant", r"(?i)gnss.*ant", r"(?i)ant.*gps"],
}

# Known intermodulation product pairs
INTERMOD_PAIRS: List[Dict[str, Any]] = [
    {
        "radio_a": "wifi",
        "radio_b": "ble",
        "order": "2*WiFi - BLE",
        "freq_a_mhz": 2440,
        "freq_b_mhz": 2440,
        "imd_mhz": 2440,   # 2*2440 - 2440 = 2440 (in-band)
        "risk": "high",
        "description": "2nd-order WiFi/BLE intermod falls in-band",
    },
    {
        "radio_a": "lte",
        "radio_b": "wifi",
        "order": "LTE_B7_TX + WiFi",
        "freq_a_mhz": 2535,
        "freq_b_mhz": 2440,
        "imd_mhz": 2630,   # Could affect LTE RX
        "risk": "medium",
        "description": "LTE B7 TX + WiFi intermod near LTE RX band",
    },
]


def _component_matches(comp, patterns: list) -> bool:
    """Check if component matches any pattern."""
    combined = f"{comp.reference} {comp.part_number or ''} {comp.value or ''} {comp.footprint or ''}".lower()
    return any(re.search(p, combined) for p in patterns)


def _net_matches(net_name: str, patterns: list) -> bool:
    """Check if net name matches any pattern."""
    return any(re.search(p, net_name) for p in patterns)


def _distance_2d(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance between two points."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def _estimate_free_space_isolation(distance_mm: float, freq_mhz: float) -> float:
    """Estimate free-space isolation in dB at given distance and frequency.

    Uses simplified free-space path loss: FSPL = 20*log10(4*pi*d/lambda).
    This is an optimistic estimate; actual PCB isolation may be lower.
    """
    if distance_mm <= 0 or freq_mhz <= 0:
        return 0.0
    wavelength_mm = 300000.0 / freq_mhz
    if distance_mm < wavelength_mm / 10:
        # Near-field: rough scaling
        return 20.0 * math.log10(max(4.0 * math.pi * distance_mm / wavelength_mm, 0.01))
    return 20.0 * math.log10(4.0 * math.pi * distance_mm / wavelength_mm)


class CoexistenceAnalyzer:
    """
    Multi-radio coexistence analyzer.

    Detects multiple radio subsystems on a PCB and checks for
    antenna isolation, coex bus signals, intermodulation risks,
    RF path separation, and ground plane partitioning.

    Usage:
        analyzer = CoexistenceAnalyzer()
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
        """Analyze multi-radio coexistence.

        Args:
            design: Parsed PCB design data.
            classified_nets: Optional NetClassificationResult.
            interfaces: Optional detected interfaces dict.

        Returns:
            List of finding dicts.
        """
        findings: List[Dict[str, Any]] = []

        # --- Detect radios present on the board ---
        detected_radios: Dict[str, List[str]] = {}
        for radio, patterns in RADIO_PATTERNS.items():
            comps = [c.reference for c in design.components if _component_matches(c, patterns)]
            if comps:
                detected_radios[radio] = comps

        if len(detected_radios) < 2:
            findings.append({
                "severity": "info",
                "category": "coexistence",
                "description": (
                    f"{'Single radio' if detected_radios else 'No radio'} detected - "
                    "coexistence analysis requires 2+ radios"
                ),
                "recommendation": "",
                "details": {"radios": detected_radios},
            })
            return findings

        findings.append({
            "severity": "info",
            "category": "coexistence",
            "description": (
                f"Multi-radio design: {', '.join(detected_radios.keys())} "
                f"({sum(len(v) for v in detected_radios.values())} components)"
            ),
            "recommendation": "",
            "details": {"radios": detected_radios},
        })

        # --- Detect coexistence bus signals ---
        coex_nets: Dict[str, List[str]] = {}
        for sig_type, patterns in COEX_PATTERNS.items():
            nets = [n.name for n in design.nets if _net_matches(n.name, patterns)]
            if nets:
                coex_nets[sig_type] = nets

        if "wifi" in detected_radios and "ble" in detected_radios:
            if not coex_nets:
                findings.append({
                    "severity": "warning",
                    "category": "coex_bus",
                    "description": (
                        "WiFi and BLE detected but no coexistence bus signals found "
                        "(GRANT/PRIORITY/REQUEST)"
                    ),
                    "recommendation": (
                        "Implement a 3-wire coexistence interface between WiFi and BLE "
                        "controllers to coordinate RF access and avoid simultaneous "
                        "TX collisions in the shared 2.4GHz band."
                    ),
                    "details": {"radios": ["wifi", "ble"]},
                })
            else:
                findings.append({
                    "severity": "info",
                    "category": "coex_bus",
                    "description": f"Coexistence bus detected: {coex_nets}",
                    "recommendation": "",
                    "details": {"coex_signals": coex_nets},
                })

        # --- Antenna isolation between radio pairs ---
        radio_antennas: Dict[str, List] = {}
        for radio in detected_radios:
            antennas = [
                c for c in design.components
                if _component_matches(c, ANTENNA_NET_PATTERNS.get(radio, []))
            ]
            if antennas:
                radio_antennas[radio] = antennas

        radio_list = list(detected_radios.keys())
        for i in range(len(radio_list)):
            for j in range(i + 1, len(radio_list)):
                radio_a = radio_list[i]
                radio_b = radio_list[j]

                # Determine isolation requirement
                pair_key = f"{radio_a}_{radio_b}"
                reverse_key = f"{radio_b}_{radio_a}"
                iso_req = ISOLATION_REQUIREMENTS.get(pair_key) or ISOLATION_REQUIREMENTS.get(reverse_key)

                if not iso_req:
                    continue

                # Check component-level separation
                comps_a = [c for c in design.components if c.reference in detected_radios[radio_a]]
                comps_b = [c for c in design.components if c.reference in detected_radios[radio_b]]

                if comps_a and comps_b:
                    min_dist = float("inf")
                    closest_pair = ("", "")
                    for ca in comps_a:
                        for cb in comps_b:
                            d = _distance_2d(ca.x_mm, ca.y_mm, cb.x_mm, cb.y_mm)
                            if d < min_dist:
                                min_dist = d
                                closest_pair = (ca.reference, cb.reference)

                    estimated_iso = _estimate_free_space_isolation(
                        min_dist, (iso_req["freq_a_mhz"] + iso_req["freq_b_mhz"]) / 2
                    )

                    if estimated_iso < iso_req["isolation_db"]:
                        findings.append({
                            "severity": "critical" if estimated_iso < iso_req["isolation_db"] * 0.5 else "warning",
                            "category": "coex_antenna_isolation",
                            "description": (
                                f"{iso_req['description']} antenna separation {min_dist:.1f}mm "
                                f"(est. {estimated_iso:.1f}dB) below required {iso_req['isolation_db']}dB"
                            ),
                            "recommendation": (
                                f"Increase distance between {radio_a} and {radio_b} antennas "
                                f"to achieve >{iso_req['isolation_db']}dB isolation. "
                                "Consider orthogonal antenna polarization or shielding."
                            ),
                            "details": {
                                "radio_a": radio_a,
                                "radio_b": radio_b,
                                "distance_mm": round(min_dist, 1),
                                "estimated_isolation_db": round(estimated_iso, 1),
                                "required_isolation_db": iso_req["isolation_db"],
                                "closest_pair": closest_pair,
                            },
                        })

        # --- RF switch detection for shared antenna ---
        rf_switch_patterns = [r"(?i)rf.?sw", r"(?i)spdt", r"(?i)sp3t", r"(?i)antenna.?sw"]
        rf_switches = [c for c in design.components if _component_matches(c, rf_switch_patterns)]

        if rf_switches:
            findings.append({
                "severity": "info",
                "category": "coex_rf_switch",
                "description": (
                    f"RF switch(es) detected: {[s.reference for s in rf_switches]} - "
                    "shared antenna configuration"
                ),
                "recommendation": (
                    "Verify RF switch is placed immediately adjacent to shared antenna feed. "
                    "Keep switch-to-antenna trace < lambda/10. Check insertion loss spec."
                ),
                "details": {"switches": [s.reference for s in rf_switches]},
            })

        # --- Routing separation between RF paths ---
        rf_net_groups: Dict[str, List[str]] = {}
        for radio, patterns in RF_NET_PATTERNS.items():
            if radio in detected_radios:
                nets = [n.name for n in design.nets if _net_matches(n.name, patterns)]
                if nets:
                    rf_net_groups[radio] = nets

        if len(rf_net_groups) >= 2:
            findings.append({
                "severity": "info",
                "category": "coex_rf_routing",
                "description": (
                    f"Multiple RF domains routed: {list(rf_net_groups.keys())}. "
                    "Verify physical separation between RF trace groups."
                ),
                "recommendation": (
                    "Maintain minimum 3x trace-width spacing between different RF paths. "
                    "Use ground stitching vias between RF domains. "
                    "Never route different RF paths in parallel on adjacent layers."
                ),
                "details": {"rf_groups": {k: v for k, v in rf_net_groups.items()}},
            })

        # --- Intermodulation product analysis ---
        for imd in INTERMOD_PAIRS:
            if imd["radio_a"] in detected_radios and imd["radio_b"] in detected_radios:
                findings.append({
                    "severity": "warning" if imd["risk"] == "high" else "info",
                    "category": "coex_intermod",
                    "description": (
                        f"Intermodulation risk: {imd['order']} = {imd['imd_mhz']}MHz "
                        f"({imd['description']})"
                    ),
                    "recommendation": (
                        "Add band-pass filtering on each RF path to suppress out-of-band "
                        "energy. Increase antenna isolation to reduce coupling. "
                        "Ensure power amplifier linearity is adequate."
                    ),
                    "details": {
                        "radio_a": imd["radio_a"],
                        "radio_b": imd["radio_b"],
                        "freq_a_mhz": imd["freq_a_mhz"],
                        "freq_b_mhz": imd["freq_b_mhz"],
                        "imd_freq_mhz": imd["imd_mhz"],
                        "risk": imd["risk"],
                    },
                })

        # --- Ground plane partitioning ---
        ground_zones = [z for z in design.zones if z.net_name and "gnd" in z.net_name.lower()]
        if len(detected_radios) >= 3 and len(ground_zones) < 2:
            findings.append({
                "severity": "warning",
                "category": "coex_ground_partition",
                "description": (
                    f"Design has {len(detected_radios)} radios but limited ground plane "
                    "partitioning detected"
                ),
                "recommendation": (
                    "For 3+ radio designs, use ground plane partitioning with strategic "
                    "stitching vias to create isolated ground domains per RF section. "
                    "Connect domains at a single star point near the common ground reference."
                ),
                "details": {
                    "radio_count": len(detected_radios),
                    "ground_zones": len(ground_zones),
                },
            })

        return findings

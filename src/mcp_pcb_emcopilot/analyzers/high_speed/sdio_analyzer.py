"""
SDIO Interface Analyzer.

Analyzes SDIO bus routing for compliance across speed modes:
- Default Speed (25MHz)
- High Speed (50MHz)
- SDR50 (100MHz)
- SDR104 (208MHz)
- DDR50 (50MHz DDR)

Checks:
- CLK-to-DATA skew
- Impedance for UHS modes (50 Ohm)
- Data line length matching
- Card detect routing
- Via count and trace length limits
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ...models.pcb_data import PCBDesignData

logger = logging.getLogger(__name__)

# Propagation delay: ~6.5 ps/mm for typical FR-4
PROP_DELAY_PS_PER_MM = 6.5

# SDIO specifications by speed mode
SDIO_SPECS: Dict[str, Dict[str, Any]] = {
    "DEFAULT": {
        "clock_mhz": 25,
        "max_length_mm": 100,
        "clk_data_skew_ps": 1000,
        "impedance_ohm": None,          # No impedance control required
        "data_match_mm": 5.0,
        "max_via_count": 4,
        "description": "SD Default Speed (25MHz)",
    },
    "HIGH_SPEED": {
        "clock_mhz": 50,
        "max_length_mm": 80,
        "clk_data_skew_ps": 500,
        "impedance_ohm": None,
        "data_match_mm": 3.0,
        "max_via_count": 3,
        "description": "SD High Speed (50MHz)",
    },
    "SDR50": {
        "clock_mhz": 100,
        "max_length_mm": 60,
        "clk_data_skew_ps": 300,
        "impedance_ohm": 50,
        "impedance_tolerance_pct": 10,
        "data_match_mm": 2.0,
        "max_via_count": 2,
        "description": "SD UHS-I SDR50 (100MHz)",
    },
    "SDR104": {
        "clock_mhz": 208,
        "max_length_mm": 40,
        "clk_data_skew_ps": 150,
        "impedance_ohm": 50,
        "impedance_tolerance_pct": 10,
        "data_match_mm": 1.5,
        "max_via_count": 2,
        "description": "SD UHS-I SDR104 (208MHz)",
    },
    "DDR50": {
        "clock_mhz": 50,
        "max_length_mm": 60,
        "clk_data_skew_ps": 300,
        "impedance_ohm": 50,
        "impedance_tolerance_pct": 10,
        "data_match_mm": 2.0,
        "max_via_count": 2,
        "description": "SD UHS-I DDR50 (50MHz DDR)",
    },
}

# Signal name patterns for SDIO nets
SDIO_PATTERNS = {
    "clk": [r"(?i)^sd\d?[_]clk", r"(?i)^sdio\d?[_]clk"],
    "cmd": [r"(?i)^sd\d?[_]cmd", r"(?i)^sdio\d?[_]cmd"],
    "data": [r"(?i)^sd\d?[_]d(?:ata)?\d", r"(?i)^sdio\d?[_]d(?:ata)?\d"],
    "cd": [r"(?i)^sd\d?[_]cd", r"(?i)sd.*det", r"(?i)card.*det"],
    "wp": [r"(?i)^sd\d?[_]wp", r"(?i)write.*prot"],
    "vdd": [r"(?i)^sd\d?[_]vdd", r"(?i)^vmmc"],
}


def _match_signal(net_name: str, category: str) -> bool:
    """Check if a net name matches an SDIO signal category."""
    return any(re.search(p, net_name) for p in SDIO_PATTERNS.get(category, []))


def _get_net_total_length(design: PCBDesignData, net_name: str) -> float:
    """Sum trace lengths for a given net name."""
    total = 0.0
    for trace in design.traces:
        if trace.net_name and trace.net_name.lower() == net_name.lower():
            length = trace.length_mm if trace.length_mm else trace.calc_length()
            total += length
    return total


def _get_net_via_count(design: PCBDesignData, net_name: str) -> int:
    """Count vias on a given net."""
    return sum(
        1 for v in design.vias
        if v.net_name and v.net_name.lower() == net_name.lower()
    )


def _detect_sdio_mode(design: PCBDesignData, data_nets: List[str]) -> str:
    """Infer SDIO speed mode from net class or interface context."""
    # Check net class names for UHS hints
    for net_name in data_nets:
        net = design.get_net_by_name(net_name)
        if net and net.net_class:
            nc_lower = net.net_class.lower()
            if "sdr104" in nc_lower or "uhs" in nc_lower:
                return "SDR104"
            if "sdr50" in nc_lower:
                return "SDR50"
            if "ddr50" in nc_lower:
                return "DDR50"
            if "hs" in nc_lower or "high" in nc_lower:
                return "HIGH_SPEED"
    # Default: assume HIGH_SPEED for modern designs
    return "HIGH_SPEED"


class SDIOAnalyzer:
    """
    SDIO interface routing analyzer.

    Analyzes SD/SDIO bus routing for timing, impedance,
    and length matching compliance across speed modes.

    Usage:
        analyzer = SDIOAnalyzer()
        findings = analyzer.analyze(design, classified_nets, interfaces)
    """

    def __init__(self, prop_delay_ps_per_mm: float = PROP_DELAY_PS_PER_MM):
        self.prop_delay = prop_delay_ps_per_mm

    def analyze(
        self,
        design: PCBDesignData,
        classified_nets: Any = None,
        interfaces: Any = None,
    ) -> List[Dict[str, Any]]:
        """Analyze SDIO interface routing.

        Args:
            design: Parsed PCB design data.
            classified_nets: Optional NetClassificationResult.
            interfaces: Optional detected interfaces dict.

        Returns:
            List of finding dicts.
        """
        findings: List[Dict[str, Any]] = []

        # Classify SDIO nets
        clk_nets: List[str] = []
        cmd_nets: List[str] = []
        data_nets: List[str] = []
        cd_nets: List[str] = []

        for net in design.nets:
            name = net.name
            if _match_signal(name, "clk"):
                clk_nets.append(name)
            elif _match_signal(name, "cmd"):
                cmd_nets.append(name)
            elif _match_signal(name, "data"):
                data_nets.append(name)
            elif _match_signal(name, "cd"):
                cd_nets.append(name)

        # Also use classified_nets for SDIO category
        if classified_nets is not None:
            for nc in getattr(classified_nets, "classified_nets", []):
                if nc.category == "sdio":
                    name = nc.net_name
                    sub = (nc.subcategory or "").lower()
                    if (sub == "clock" or _match_signal(name, "clk")) and name not in clk_nets:
                        clk_nets.append(name)
                    elif (sub == "command" or _match_signal(name, "cmd")) and name not in cmd_nets:
                        cmd_nets.append(name)
                    elif (sub == "card_detect" or _match_signal(name, "cd")) and name not in cd_nets:
                        cd_nets.append(name)
                    elif sub == "data" or _match_signal(name, "data"):
                        if name not in data_nets:
                            data_nets.append(name)
                    elif name not in data_nets and 'DATA' in name.upper():
                        data_nets.append(name)

        if not data_nets and not clk_nets:
            findings.append({
                "severity": "info",
                "category": "sdio",
                "description": "No SDIO interface signals detected in design",
                "recommendation": "Verify net naming follows SD/SDIO conventions if SD is present",
                "details": {"signal_count": 0},
            })
            return findings

        # Determine speed mode
        mode = _detect_sdio_mode(design, data_nets)
        spec = SDIO_SPECS[mode]

        findings.append({
            "severity": "info",
            "category": "sdio",
            "description": (
                f"SDIO interface detected ({spec['description']}): "
                f"{len(data_nets)} data, {len(clk_nets)} CLK, "
                f"{len(cmd_nets)} CMD, {len(cd_nets)} CD"
            ),
            "recommendation": "",
            "details": {
                "mode": mode,
                "data_nets": data_nets,
                "clk_nets": clk_nets,
                "cmd_nets": cmd_nets,
                "cd_nets": cd_nets,
            },
        })

        # --- Data line length matching ---
        data_lengths: Dict[str, float] = {}
        for net_name in data_nets:
            data_lengths[net_name] = _get_net_total_length(design, net_name)

        if data_lengths:
            lengths = list(data_lengths.values())
            max_len = max(lengths) if lengths else 0.0
            min_len = min(lengths) if lengths else 0.0
            spread_mm = max_len - min_len

            if spread_mm > spec["data_match_mm"]:
                findings.append({
                    "severity": "critical" if spread_mm > spec["data_match_mm"] * 2 else "warning",
                    "category": "sdio_length_matching",
                    "description": (
                        f"SDIO data line length spread {spread_mm:.2f}mm exceeds "
                        f"{mode} limit of {spec['data_match_mm']}mm"
                    ),
                    "recommendation": (
                        f"Match all SDIO data lines within {spec['data_match_mm']}mm. "
                        "Use serpentine routing to equalize lengths."
                    ),
                    "details": {
                        "spread_mm": round(spread_mm, 2),
                        "limit_mm": spec["data_match_mm"],
                        "lengths": {k: round(v, 2) for k, v in data_lengths.items()},
                    },
                })

        # --- Max trace length ---
        all_sdio_nets = clk_nets + cmd_nets + data_nets
        for net_name in all_sdio_nets:
            length = _get_net_total_length(design, net_name)
            if length > spec["max_length_mm"]:
                findings.append({
                    "severity": "critical",
                    "category": "sdio_trace_length",
                    "description": (
                        f"SDIO signal {net_name} length {length:.1f}mm exceeds "
                        f"{mode} max of {spec['max_length_mm']}mm"
                    ),
                    "recommendation": (
                        "Shorten trace routing. Place SD card connector closer to host controller."
                    ),
                    "details": {
                        "net": net_name,
                        "length_mm": round(length, 2),
                        "limit_mm": spec["max_length_mm"],
                    },
                })

        # --- CLK to DATA skew ---
        if clk_nets and data_lengths:
            clk_length = _get_net_total_length(design, clk_nets[0])
            for net_name, d_len in data_lengths.items():
                skew_mm = abs(d_len - clk_length)
                skew_ps = skew_mm * self.prop_delay
                if skew_ps > spec["clk_data_skew_ps"]:
                    findings.append({
                        "severity": "critical" if skew_ps > spec["clk_data_skew_ps"] * 1.5 else "warning",
                        "category": "sdio_clk_data_skew",
                        "description": (
                            f"SDIO CLK-to-{net_name} skew {skew_ps:.0f}ps exceeds "
                            f"{mode} limit of {spec['clk_data_skew_ps']}ps"
                        ),
                        "recommendation": (
                            f"Reduce CLK-to-DATA length mismatch to keep skew <{spec['clk_data_skew_ps']}ps."
                        ),
                        "details": {
                            "net": net_name,
                            "clk_length_mm": round(clk_length, 2),
                            "data_length_mm": round(d_len, 2),
                            "skew_ps": round(skew_ps, 1),
                            "limit_ps": spec["clk_data_skew_ps"],
                        },
                    })

        # --- Via count check ---
        for net_name in all_sdio_nets:
            via_count = _get_net_via_count(design, net_name)
            if via_count > spec["max_via_count"]:
                findings.append({
                    "severity": "warning",
                    "category": "sdio_via_count",
                    "description": (
                        f"SDIO signal {net_name} has {via_count} vias "
                        f"(max {spec['max_via_count']} for {mode})"
                    ),
                    "recommendation": (
                        "Route SDIO signals on a single layer to minimize via transitions."
                    ),
                    "details": {
                        "net": net_name,
                        "via_count": via_count,
                        "limit": spec["max_via_count"],
                    },
                })

        # --- Impedance check for UHS modes ---
        if spec["impedance_ohm"] is not None:
            target_z = spec["impedance_ohm"]
            for trace in design.traces:
                if trace.net_name and any(
                    trace.net_name.lower() == n.lower() for n in all_sdio_nets
                ):
                    if trace.width_mm < 0.08:
                        findings.append({
                            "severity": "warning",
                            "category": "sdio_impedance",
                            "description": (
                                f"SDIO signal {trace.net_name} trace width {trace.width_mm:.3f}mm "
                                f"is very narrow - verify {target_z} Ohm impedance for {mode}"
                            ),
                            "recommendation": (
                                f"UHS modes require {target_z} Ohm impedance-controlled routing. "
                                "Verify trace geometry with stackup calculator."
                            ),
                            "details": {
                                "net": trace.net_name,
                                "width_mm": trace.width_mm,
                                "target_impedance_ohm": target_z,
                                "layer": trace.layer,
                            },
                        })
                        break

        # --- Card detect routing check ---
        if cd_nets:
            for cd_net in cd_nets:
                cd_length = _get_net_total_length(design, cd_net)
                # Card detect should not be routed near high-speed data
                findings.append({
                    "severity": "info",
                    "category": "sdio_card_detect",
                    "description": (
                        f"Card detect signal {cd_net} found, length {cd_length:.1f}mm"
                    ),
                    "recommendation": (
                        "Ensure card detect has a pull-up resistor and is routed "
                        "away from CLK and data lines to avoid false triggers."
                    ),
                    "details": {
                        "net": cd_net,
                        "length_mm": round(cd_length, 2),
                    },
                })
        else:
            findings.append({
                "severity": "info",
                "category": "sdio_card_detect",
                "description": "No card detect signal found for SDIO interface",
                "recommendation": (
                    "If using a removable SD card, verify card detect is implemented "
                    "via mechanical switch or GPIO polling."
                ),
                "details": {},
            })

        return findings

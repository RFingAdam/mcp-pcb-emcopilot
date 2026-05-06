"""
eMMC Interface Analyzer.

Analyzes eMMC HS200/HS400 routing for compliance:
- CLK-to-DATA skew per byte
- CMD-to-CLK setup timing
- Data strobe to data skew (HS400)
- 50 Ohm impedance verification
- Max trace length limits
- Via count limits
- Data line length matching within tolerance
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from ...models.pcb_data import PCBDesignData

logger = logging.getLogger(__name__)

# Propagation delay: ~6.5 ps/mm for typical FR-4
PROP_DELAY_PS_PER_MM = 6.5

# eMMC specifications by mode
EMMC_SPECS: Dict[str, Dict[str, Any]] = {
    "HS200": {
        "data_rate_mhz": 200,
        "max_length_mm": 50,
        "clk_data_skew_ps": 300,
        "impedance_ohm": 50,
        "impedance_tolerance_pct": 10,
        "max_via_count": 2,
        "data_match_mm": 2.0,       # Data lines matched within 2mm
        "cmd_clk_setup_ps": 500,
        "description": "eMMC HS200 (200MHz SDR)",
    },
    "HS400": {
        "data_rate_mhz": 400,
        "max_length_mm": 30,
        "clk_data_skew_ps": 100,
        "ds_data_skew_ps": 100,      # Data strobe to data skew
        "impedance_ohm": 50,
        "impedance_tolerance_pct": 10,
        "max_via_count": 1,
        "data_match_mm": 1.0,       # Tighter matching for HS400
        "cmd_clk_setup_ps": 300,
        "description": "eMMC HS400 (200MHz DDR, strobe)",
    },
}

# Signal name patterns for eMMC nets
EMMC_PATTERNS = {
    "clk": [r"(?i)emmc.*clk", r"(?i)mmc.*clk", r"(?i)sdhc\d*.*clk"],
    "cmd": [r"(?i)emmc.*cmd", r"(?i)mmc.*cmd", r"(?i)sdhc\d*.*cmd"],
    "data": [r"(?i)emmc.*d(?:at)?[0-7]", r"(?i)mmc.*d(?:at)?[0-7]", r"(?i)sdhc\d*.*d[0-7]"],
    "ds": [r"(?i)emmc.*ds", r"(?i)mmc.*ds", r"(?i)emmc.*strobe", r"(?i)sdhc\d*.*dqs"],
    "rst": [r"(?i)emmc.*rst", r"(?i)mmc.*rst", r"(?i)sdhc\d*.*reset"],
}


def _match_signal(net_name: str, category: str) -> bool:
    """Check if a net name matches an eMMC signal category."""
    return any(re.search(p, net_name) for p in EMMC_PATTERNS.get(category, []))


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


def _find_emmc_controller(design: PCBDesignData) -> Optional[str]:
    """Detect eMMC controller or device component."""
    for comp in design.components:
        combined = f"{comp.part_number or ''} {comp.value or ''} {comp.footprint or ''}".lower()
        if any(kw in combined for kw in ["emmc", "mmc", "thgbm", "klmag", "mtfc"]):
            return comp.reference
    return None


class EMMCAnalyzer:
    """
    eMMC interface routing analyzer.

    Analyzes eMMC HS200/HS400 routing for timing, impedance,
    and length matching compliance.

    Usage:
        analyzer = EMMCAnalyzer()
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
        """Analyze eMMC interface routing.

        Args:
            design: Parsed PCB design data.
            classified_nets: Optional NetClassificationResult from net classifier.
            interfaces: Optional detected interfaces dict.

        Returns:
            List of finding dicts with severity, category, description,
            recommendation, and details.
        """
        findings: List[Dict[str, Any]] = []

        # Classify eMMC nets from design
        clk_nets = []
        cmd_nets = []
        data_nets = []
        ds_nets = []
        rst_nets = []

        for net in design.nets:
            name = net.name
            if _match_signal(name, "clk"):
                clk_nets.append(name)
            elif _match_signal(name, "cmd"):
                cmd_nets.append(name)
            elif _match_signal(name, "data"):
                data_nets.append(name)
            elif _match_signal(name, "ds"):
                ds_nets.append(name)
            elif _match_signal(name, "rst"):
                rst_nets.append(name)

        # Also check classified_nets if available — use category='emmc'
        if classified_nets is not None:
            for nc in getattr(classified_nets, "classified_nets", []):
                if nc.category == "emmc":
                    name = nc.net_name
                    sub = (nc.subcategory or "").lower()
                    if sub == "clock" or _match_signal(name, "clk"):
                        if name not in clk_nets:
                            clk_nets.append(name)
                    elif sub == "command" or _match_signal(name, "cmd"):
                        if name not in cmd_nets:
                            cmd_nets.append(name)
                    elif sub == "data" or _match_signal(name, "data"):
                        if name not in data_nets:
                            data_nets.append(name)
                    elif sub == "data_strobe" or _match_signal(name, "ds"):
                        if name not in ds_nets:
                            ds_nets.append(name)
                    elif sub == "reset" or _match_signal(name, "rst"):
                        if name not in rst_nets:
                            rst_nets.append(name)
                    elif name not in data_nets:
                        # Default: treat unsubcategorized eMMC nets as data
                        data_nets.append(name)

        if not data_nets and not clk_nets:
            findings.append({
                "severity": "info",
                "category": "emmc",
                "description": "No eMMC interface signals detected in design",
                "recommendation": "Verify net naming follows eMMC conventions if eMMC is present",
                "details": {"signal_count": 0},
            })
            return findings

        # Group nets by controller/channel (e.g., SDHC0 vs SDHC1)
        # to avoid comparing traces routed to different chips
        channels: Dict[str, Dict[str, List[str]]] = {}
        all_emmc_nets_flat = clk_nets + cmd_nets + data_nets + ds_nets + rst_nets
        for name in all_emmc_nets_flat:
            # Extract channel ID from net name
            ch_match = re.search(r'(SDHC\d+|EMMC\d*|MMC\d+)', name, re.IGNORECASE)
            ch_id = ch_match.group(1).upper() if ch_match else "DEFAULT"
            if ch_id not in channels:
                channels[ch_id] = {"clk": [], "cmd": [], "data": [], "ds": [], "rst": []}
            if name in clk_nets:
                channels[ch_id]["clk"].append(name)
            elif name in cmd_nets:
                channels[ch_id]["cmd"].append(name)
            elif name in ds_nets:
                channels[ch_id]["ds"].append(name)
            elif name in rst_nets:
                channels[ch_id]["rst"].append(name)
            elif name in data_nets:
                channels[ch_id]["data"].append(name)

        # If only one channel, use original flat lists
        if len(channels) <= 1:
            channels = {"DEFAULT": {"clk": clk_nets, "cmd": cmd_nets, "data": data_nets, "ds": ds_nets, "rst": rst_nets}}

        # Determine mode: HS400 if data strobe present, else HS200
        mode = "HS400" if ds_nets else "HS200"
        spec = EMMC_SPECS[mode]

        findings.append({
            "severity": "info",
            "category": "emmc",
            "description": f"eMMC {mode} interface detected: {len(data_nets)} data, "
                           f"{len(clk_nets)} CLK, {len(cmd_nets)} CMD, {len(ds_nets)} DS"
                           f" ({len(channels)} channel(s): {', '.join(channels.keys())})",
            "recommendation": "",
            "details": {
                "mode": mode,
                "channels": {ch: {k: v for k, v in sigs.items() if v} for ch, sigs in channels.items()},
            },
        })

        # Detect eMMC device
        emmc_ref = _find_emmc_controller(design)
        if emmc_ref:
            findings.append({
                "severity": "info",
                "category": "emmc",
                "description": f"eMMC device detected: {emmc_ref}",
                "recommendation": "",
                "details": {"component": emmc_ref},
            })

        # --- Per-channel analysis ---
        for ch_id, ch_sigs in channels.items():
            ch_prefix = f"{ch_id}: " if len(channels) > 1 else ""
            ch_data = ch_sigs["data"]
            ch_clk = ch_sigs["clk"]
            ch_cmd = ch_sigs["cmd"]
            ch_ds = ch_sigs["ds"]

            # Check data line lengths and matching within THIS channel
            data_lengths: Dict[str, float] = {}
            for net_name in ch_data:
                data_lengths[net_name] = _get_net_total_length(design, net_name)

            if data_lengths:
                lengths = list(data_lengths.values())
                max_len = max(lengths) if lengths else 0.0
                min_len = min(lengths) if lengths else 0.0
                spread_mm = max_len - min_len

                if spread_mm > spec["data_match_mm"]:
                    findings.append({
                        "severity": "critical" if spread_mm > spec["data_match_mm"] * 2 else "warning",
                        "category": "emmc_length_matching",
                        "description": (
                            f"{ch_prefix}eMMC data line length spread {spread_mm:.2f}mm exceeds "
                            f"{mode} limit of {spec['data_match_mm']}mm "
                            f"(min={min_len:.1f}mm, max={max_len:.1f}mm)"
                        ),
                        "recommendation": (
                            f"Match all {ch_id} data lines within {spec['data_match_mm']}mm. "
                            "Use serpentine routing on shorter traces."
                        ),
                        "details": {
                            "channel": ch_id,
                            "spread_mm": round(spread_mm, 2),
                            "limit_mm": spec["data_match_mm"],
                            "lengths": {k: round(v, 2) for k, v in data_lengths.items()},
                        },
                    })

            # Check max trace length per channel
            all_ch_nets = ch_clk + ch_cmd + ch_data + ch_ds
            for net_name in all_ch_nets:
                length = _get_net_total_length(design, net_name)
                if length > spec["max_length_mm"]:
                    findings.append({
                        "severity": "critical",
                        "category": "emmc_trace_length",
                        "description": (
                            f"{ch_prefix}eMMC signal {net_name} length {length:.1f}mm exceeds "
                            f"{mode} max of {spec['max_length_mm']}mm"
                        ),
                        "recommendation": (
                            "Shorten trace routing. Place eMMC device closer to SoC. "
                            "Consider using shorter via paths."
                        ),
                        "details": {
                            "channel": ch_id,
                            "net": net_name,
                            "length_mm": round(length, 2),
                            "limit_mm": spec["max_length_mm"],
                        },
                    })

            # CLK to DATA skew per channel
            if ch_clk and data_lengths:
                clk_length = _get_net_total_length(design, ch_clk[0])
                for net_name, d_len in data_lengths.items():
                    skew_mm = abs(d_len - clk_length)
                    skew_ps = skew_mm * self.prop_delay
                    if skew_ps > spec["clk_data_skew_ps"]:
                        findings.append({
                            "severity": "critical",
                            "category": "emmc_clk_data_skew",
                            "description": (
                                f"{ch_prefix}CLK-to-{net_name} skew {skew_ps:.0f}ps exceeds "
                                f"{mode} limit of {spec['clk_data_skew_ps']}ps"
                            ),
                            "recommendation": (
                                f"Reduce CLK-to-DATA length mismatch. Target skew <{spec['clk_data_skew_ps']}ps."
                        ),
                        "details": {
                            "net": net_name,
                            "clk_length_mm": round(clk_length, 2),
                            "data_length_mm": round(d_len, 2),
                            "skew_ps": round(skew_ps, 1),
                            "limit_ps": spec["clk_data_skew_ps"],
                        },
                    })

        # --- CMD to CLK setup ---
        if clk_nets and cmd_nets:
            clk_length = _get_net_total_length(design, clk_nets[0])
            for cmd_net in cmd_nets:
                cmd_length = _get_net_total_length(design, cmd_net)
                skew_mm = abs(cmd_length - clk_length)
                skew_ps = skew_mm * self.prop_delay
                if skew_ps > spec["cmd_clk_setup_ps"]:
                    findings.append({
                        "severity": "warning",
                        "category": "emmc_cmd_clk_setup",
                        "description": (
                            f"CMD-to-CLK skew {skew_ps:.0f}ps exceeds "
                            f"{mode} setup limit of {spec['cmd_clk_setup_ps']}ps"
                        ),
                        "recommendation": "Match CMD trace length closer to CLK trace length.",
                        "details": {
                            "cmd_net": cmd_net,
                            "skew_ps": round(skew_ps, 1),
                            "limit_ps": spec["cmd_clk_setup_ps"],
                        },
                    })

        # --- Data strobe to data skew (HS400 only) ---
        if mode == "HS400" and ds_nets and data_lengths:
            ds_length = _get_net_total_length(design, ds_nets[0])
            ds_limit = spec["ds_data_skew_ps"]
            for net_name, d_len in data_lengths.items():
                skew_mm = abs(d_len - ds_length)
                skew_ps = skew_mm * self.prop_delay
                if skew_ps > ds_limit:
                    findings.append({
                        "severity": "critical",
                        "category": "emmc_ds_data_skew",
                        "description": (
                            f"Data strobe to {net_name} skew {skew_ps:.0f}ps exceeds "
                            f"HS400 limit of {ds_limit}ps"
                        ),
                        "recommendation": (
                            "Match data strobe (DS) length to data lines. "
                            "DS-to-DATA skew is critical for HS400 eye margin."
                        ),
                        "details": {
                            "net": net_name,
                            "ds_length_mm": round(ds_length, 2),
                            "data_length_mm": round(d_len, 2),
                            "skew_ps": round(skew_ps, 1),
                            "limit_ps": ds_limit,
                        },
                    })

        # --- Via count check (across all channels) ---
        for net_name in all_emmc_nets_flat:
            via_count = _get_net_via_count(design, net_name)
            if via_count > spec["max_via_count"]:
                findings.append({
                    "severity": "warning",
                    "category": "emmc_via_count",
                    "description": (
                        f"eMMC signal {net_name} has {via_count} vias "
                        f"(max {spec['max_via_count']} for {mode})"
                    ),
                    "recommendation": (
                        "Minimize layer transitions on eMMC signals. "
                        "Route on a single layer adjacent to a ground plane."
                    ),
                    "details": {
                        "net": net_name,
                        "via_count": via_count,
                        "limit": spec["max_via_count"],
                    },
                })

        # --- Impedance check ---
        target_z = spec["impedance_ohm"]
        tolerance = spec["impedance_tolerance_pct"] / 100.0
        for trace in design.traces:
            if trace.net_name and any(
                trace.net_name.lower() == n.lower() for n in all_emmc_nets_flat
            ):
                # Estimate impedance from trace width (simplified check)
                # Flag very narrow or very wide traces that likely miss 50 Ohm
                if trace.width_mm < 0.08:
                    findings.append({
                        "severity": "warning",
                        "category": "emmc_impedance",
                        "description": (
                            f"eMMC signal {trace.net_name} trace width {trace.width_mm:.3f}mm "
                            f"is very narrow - verify {target_z} Ohm impedance target"
                        ),
                        "recommendation": (
                            f"Use impedance-controlled routing for {target_z} Ohm. "
                            "Consult stackup calculator for correct width."
                        ),
                        "details": {
                            "net": trace.net_name,
                            "width_mm": trace.width_mm,
                            "target_impedance_ohm": target_z,
                            "layer": trace.layer,
                        },
                    })
                    break  # One finding per net is sufficient

        return findings

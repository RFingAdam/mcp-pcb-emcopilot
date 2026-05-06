"""
Differential pair trace width mismatch checker.

Detects:
- P/N trace width mismatches within differential pairs on the same layer
- Impedance imbalance from width asymmetry (wider trace = lower Z0)
- Common-mode conversion risk from intra-pair width variation

Width mismatch causes differential-to-common-mode conversion, degrading
signal integrity and increasing radiated emissions.
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Thresholds
_WIDTH_MISMATCH_WARNING_PCT = 5.0   # 5-15% -> warning
_WIDTH_MISMATCH_CRITICAL_PCT = 15.0  # >15% -> critical


def _impedance_from_width(width_mm: float, height_mm: float = 0.1,
                          er: float = 4.3, t_mm: float = 0.035) -> float:
    """Estimate microstrip Z0 from trace width (Hammerstad-Jensen)."""
    if width_mm <= 0 or height_mm <= 0 or er <= 0:
        return 0.0
    w_eff = width_mm + (t_mm / math.pi) * (1 + math.log(max(4 * math.pi * width_mm / t_mm, 1e-6)))
    u = w_eff / height_mm
    er_eff = (er + 1) / 2 + (er - 1) / 2 * (1 + 12 / max(u, 1e-6)) ** (-0.5)
    if u <= 1:
        return (60 / math.sqrt(er_eff)) * math.log(8 / u + u / 4)
    return (120 * math.pi) / (math.sqrt(er_eff) * (u + 1.393 + 0.667 * math.log(u + 1.444)))


class DiffPairWidthChecker:
    """Check differential pair P/N trace width symmetry per layer.

    Width asymmetry causes impedance imbalance and differential-to-common-mode
    conversion, which is a primary source of EMI in high-speed links.
    """

    def analyze(
        self,
        design: Any,
        classified_nets: Any = None,
        interfaces: Any = None,
    ) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []

        if classified_nets is None:
            return findings

        diff_pairs = getattr(classified_nets, "differential_pairs", None)
        if not diff_pairs:
            return findings

        # Build net_name -> [traces] index for fast lookup
        traces_by_net: Dict[str, List] = defaultdict(list)
        for trace in getattr(design, "traces", []):
            if trace.net_name:
                traces_by_net[trace.net_name].append(trace)

        for pair in diff_pairs:
            p_net = getattr(pair, "positive_net", None)
            n_net = getattr(pair, "negative_net", None)
            pair_name = getattr(pair, "pair_name", f"{p_net}/{n_net}")

            if not p_net or not n_net:
                continue

            p_traces = traces_by_net.get(p_net, [])
            n_traces = traces_by_net.get(n_net, [])

            if not p_traces and not n_traces:
                continue

            # Group trace widths by layer for each polarity
            p_widths_by_layer: Dict[str, List[float]] = defaultdict(list)
            n_widths_by_layer: Dict[str, List[float]] = defaultdict(list)

            for t in p_traces:
                if t.width_mm > 0:
                    p_widths_by_layer[t.layer].append(t.width_mm)
            for t in n_traces:
                if t.width_mm > 0:
                    n_widths_by_layer[t.layer].append(t.width_mm)

            # Check each layer where both P and N have traces
            all_layers = set(p_widths_by_layer.keys()) | set(n_widths_by_layer.keys())

            for layer in sorted(all_layers):
                p_ws = p_widths_by_layer.get(layer, [])
                n_ws = n_widths_by_layer.get(layer, [])

                if not p_ws or not n_ws:
                    # One side missing on this layer -- routing incomplete, skip
                    continue

                p_avg = sum(p_ws) / len(p_ws)
                n_avg = sum(n_ws) / len(n_ws)

                if p_avg <= 0 or n_avg <= 0:
                    continue

                mean_width = (p_avg + n_avg) / 2.0
                mismatch_mm = abs(p_avg - n_avg)
                mismatch_pct = (mismatch_mm / mean_width) * 100.0

                if mismatch_pct < _WIDTH_MISMATCH_WARNING_PCT:
                    continue

                # Estimate impedance difference
                z_p = _impedance_from_width(p_avg)
                z_n = _impedance_from_width(n_avg)
                z_mismatch_ohm = abs(z_p - z_n)

                if mismatch_pct >= _WIDTH_MISMATCH_CRITICAL_PCT:
                    severity = "critical"
                else:
                    severity = "warning"

                findings.append({
                    "severity": severity,
                    "category": "signal_integrity",
                    "description": (
                        f"Differential pair '{pair_name}' has {mismatch_pct:.1f}% "
                        f"width mismatch on layer {layer}: "
                        f"P={p_avg:.4f}mm vs N={n_avg:.4f}mm"
                    ),
                    "recommendation": (
                        "Match P and N trace widths to within 5%. Width asymmetry "
                        "causes differential-to-common-mode conversion, degrading "
                        "signal quality and increasing radiated EMI."
                    ),
                    "details": {
                        "pair_name": pair_name,
                        "positive_net": p_net,
                        "negative_net": n_net,
                        "layer": layer,
                        "p_width_mm": round(p_avg, 4),
                        "n_width_mm": round(n_avg, 4),
                        "mismatch_pct": round(mismatch_pct, 1),
                        "estimated_z0_p_ohm": round(z_p, 1),
                        "estimated_z0_n_ohm": round(z_n, 1),
                        "z0_mismatch_ohm": round(z_mismatch_ohm, 1),
                        "p_trace_count": len(p_ws),
                        "n_trace_count": len(n_ws),
                    },
                })

        return findings

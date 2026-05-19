"""AI-driven actionable recommendation engine.

Generates specific, coordinate-level fix recommendations for each finding.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

# IPC-2152 width lookup for current capacity
_WIDTH_FOR_CURRENT = {0.5: 0.20, 1.0: 0.38, 1.5: 0.55, 2.0: 0.70, 3.0: 1.00}

# Trace width for target impedance (microstrip, h=0.069mm, Er=4.2)
_WIDTH_FOR_Z0 = {40: 0.125, 45: 0.110, 50: 0.095, 55: 0.080, 60: 0.070}

# RF filter part recommendations
_RF_FILTER_PARTS = {
    900: {"part": "Murata SAFEA915MAL0F00", "desc": "925MHz SAW bandpass, IL<2dB"},
    2400: {"part": "Qualcomm B39921B2672P810", "desc": "2.4GHz BAW bandpass"},
    5800: {"part": "Qualcomm B39871B4377P810", "desc": "5GHz BAW bandpass"},
}


class RecommendationEngine:
    """Generate specific, actionable fix recommendations for design findings."""

    def generate(self, design: Any, review_result: Any) -> List[Dict[str, Any]]:
        """Generate actionable recommendations from review findings."""
        recommendations: List[Dict[str, Any]] = []

        if not review_result:
            return recommendations

        domain_results = getattr(review_result, 'domain_results', [])
        for dr in domain_results:
            for f in dr.findings:
                if f.severity not in ('critical', 'warning', 'high'):
                    continue
                rec = self._generate_for_finding(f, dr.domain, design)
                if rec:
                    recommendations.append(rec)

        return recommendations

    def _generate_for_finding(self, finding: Any, domain: str, design: Any) -> Optional[Dict]:
        """Generate a specific recommendation for a single finding."""
        desc = finding.description or ""
        title = finding.title or ""

        # Power trace width
        if domain == "power_trace_current" and "narrowest trace" in desc:
            return self._rec_power_trace(finding, design)

        # Impedance mismatch
        if "impedance" in domain and "Z₀=" in desc:
            return self._rec_impedance(finding)

        # DDR length matching
        if "ddr" in domain and "skew" in desc.lower():
            return self._rec_ddr_skew(finding)

        # eMMC data spread
        if domain == "emmc" and "spread" in desc:
            return self._rec_emmc_spread(finding)

        # HaLow filter
        if "halow" in domain and ("filter" in desc.lower() or "TX" in desc):
            return self._rec_rf_filter(finding, 900)

        # Decoupling
        if "decap" in domain and "no bypass" in desc.lower():
            return self._rec_decoupling(finding, design)

        return None

    def _rec_power_trace(self, f: Any, design: Any) -> Dict:
        net = f.signal_name or "unknown"
        # Extract coordinates from finding
        x = getattr(f, 'location_x_mm', None)
        y = getattr(f, 'location_y_mm', None)
        layer = getattr(f, 'location_layer', None)
        coord = f"({x:.1f}, {y:.1f})mm on {layer}" if x else "see finding details"

        # Find target width
        target_w = 0.5  # default
        for current, width in _WIDTH_FOR_CURRENT.items():
            if f"estimated {current}" in (f.description or ""):
                target_w = width
                break

        return {
            "priority": "critical", "category": "power_trace_width",
            "action_type": "widen_trace",
            "finding_ref": f"{f.domain}:{f.title}",
            "description": f"Widen {net} trace at {coord} to {target_w:.2f}mm for rated current (IPC-2152, 1oz Cu, 10C rise)",
            "coordinates": {"x_mm": x, "y_mm": y, "layer": layer},
            "parameters": {"net": net, "target_width_mm": target_w},
            "effort": "trivial",
        }

    def _rec_impedance(self, f: Any) -> Dict:
        desc = f.description or ""
        # Extract current and target Z
        import re
        z_match = re.search(r'Z₀=(\d+\.?\d*)Ω.*target (\d+\.?\d*)Ω', desc)
        w_match = re.search(r'w=(\d+\.?\d*)mm', desc)
        layer_match = re.search(r'on (\S+)', desc)

        current_z = float(z_match.group(1)) if z_match else 0
        target_z = float(z_match.group(2)) if z_match else 50
        current_w = float(w_match.group(1)) if w_match else 0
        layer = layer_match.group(1) if layer_match else "unknown"

        target_w = _WIDTH_FOR_Z0.get(int(target_z), current_w * target_z / max(current_z, 1))

        return {
            "priority": "high", "category": "impedance",
            "action_type": "adjust_trace_width",
            "finding_ref": f"{f.domain}:{f.title}",
            "description": f"Change trace width on {layer} from {current_w:.4f}mm to ~{target_w:.4f}mm for {target_z:.0f}Ω target",
            "parameters": {"layer": layer, "current_width_mm": current_w, "target_width_mm": round(target_w, 4), "target_z_ohm": target_z},
            "effort": "moderate",
        }

    def _rec_ddr_skew(self, f: Any) -> Dict:
        desc = f.description or ""
        import re
        skew_match = re.search(r'(\d+\.?\d*)ps exceeds', desc)
        skew_ps = float(skew_match.group(1)) if skew_match else 0

        return {
            "priority": "high", "category": "ddr_length_matching",
            "action_type": "add_serpentine",
            "finding_ref": f"{f.domain}:{f.title}",
            "description": f"Add serpentine to reduce DQ-DQS skew by {skew_ps - 25:.0f}ps ({(skew_ps - 25)/6.5:.1f}mm trace length delta)",
            "parameters": {"skew_ps": skew_ps, "target_ps": 25, "serpentine_mm": round((skew_ps - 25) / 6.5, 2)},
            "effort": "trivial",
        }

    def _rec_emmc_spread(self, f: Any) -> Dict:
        import re
        spread_match = re.search(r'spread (\d+\.?\d*)mm', f.description or "")
        spread = float(spread_match.group(1)) if spread_match else 0

        return {
            "priority": "medium", "category": "emmc_length_matching",
            "action_type": "add_serpentine",
            "finding_ref": f"{f.domain}:{f.title}",
            "description": f"Add serpentine routing to shortest eMMC data lines to reduce spread from {spread:.2f}mm to <1.0mm",
            "parameters": {"current_spread_mm": spread, "target_spread_mm": 1.0},
            "effort": "trivial",
        }

    def _rec_rf_filter(self, f: Any, freq_mhz: int) -> Dict:
        part = _RF_FILTER_PARTS.get(freq_mhz, {"part": "TBD", "desc": "bandpass filter"})
        return {
            "priority": "critical", "category": "rf_filter",
            "action_type": "add_component",
            "finding_ref": f"{f.domain}:{f.title}",
            "description": f"Add {freq_mhz}MHz TX bandpass filter ({part['part']}) between PA output and antenna switch. {part['desc']}.",
            "parameters": {"frequency_mhz": freq_mhz, "part_number": part["part"]},
            "effort": "moderate",
        }

    def _rec_decoupling(self, f: Any, design: Any) -> Dict:
        return {
            "priority": "medium", "category": "decoupling",
            "action_type": "add_component",
            "finding_ref": f"{f.domain}:{f.title}",
            "description": "Add 100nF ceramic capacitor within 2mm of IC power pins. For BGA, place on opposite board side.",
            "parameters": {"cap_value": "100nF", "max_distance_mm": 2.0},
            "effort": "trivial",
        }

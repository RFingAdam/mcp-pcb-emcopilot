"""
Power trace current capacity validator.

Checks that power trace widths can carry expected current based on
IPC-2152 guidelines for copper traces on PCBs.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

# IPC-2152 simplified current capacity (Amps) for given trace width (mm)
# at 10°C temperature rise, 1oz (35μm) copper
# External (microstrip): I = k * (dT^0.44) * (A^0.725) where A = cross-section area
# Simplified lookup for 1oz external copper at 10°C rise:
#   width_mm -> max_current_A (approximate)
_IPC2152_1OZ_EXT_10C = {
    0.05: 0.15, 0.075: 0.20, 0.10: 0.27, 0.125: 0.33,
    0.15: 0.39, 0.20: 0.50, 0.25: 0.61, 0.30: 0.72,
    0.40: 0.92, 0.50: 1.12, 0.75: 1.56, 1.00: 1.97,
    1.50: 2.74, 2.00: 3.44, 3.00: 4.73, 5.00: 7.14,
}

# Internal traces carry ~50% less due to reduced convection
_INTERNAL_DERATING = 0.5

# SMPS component patterns for estimating current
_SMPS_PATTERNS = [
    (r'(?i)(TPS6[2-9]\d|TPS5\d{3}|LT3\d{3}|LTC3\d{3}|MP\d{4}|RT\d{4})', 'buck'),
    (r'(?i)(LDO|AMS1117|TLV7\d|AP21\d|MIC59)', 'ldo'),
    (r'(?i)(PCA9\d{3}|ACT\d{3}|PFUZE)', 'pmic'),
]

# Estimated current by regulator type (conservative defaults)
_CURRENT_ESTIMATES = {
    'buck': 2.0,   # Typical buck: 1-3A
    'ldo': 0.5,    # Typical LDO: 0.3-1A
    'pmic': 1.5,   # PMIC channel: 0.5-3A
}

# Voltage estimation from net names
_VOLTAGE_PATTERNS = [
    (r'(\d+)[Pp](\d+)[Vv]', lambda m: float(m.group(1)) + float(m.group(2)) / 10),  # 3P3V → 3.3
    (r'(\d+)[Vv](\d+)', lambda m: float(m.group(1)) + float(m.group(2)) / 10),  # 3V3 → 3.3
    (r'(\d+\.\d+)[Vv]', lambda m: float(m.group(1))),  # 1.8V
    (r'[_](\d+[Pp]\d+)', lambda m: float(m.group(1).replace('P', '.').replace('p', '.'))),  # _1P8 → 1.8
]


def _estimate_current_capacity(width_mm: float, copper_oz: float = 1.0, is_internal: bool = False) -> float:
    """Estimate current capacity from trace width using IPC-2152.

    Args:
        width_mm: Trace width in mm.
        copper_oz: Copper weight in oz (1oz = 35μm).
        is_internal: True for internal (stripline) layers.

    Returns:
        Estimated maximum current in Amps at 10°C rise.
    """
    # Interpolate from lookup table
    widths = sorted(_IPC2152_1OZ_EXT_10C.keys())
    if width_mm <= widths[0]:
        capacity = _IPC2152_1OZ_EXT_10C[widths[0]]
    elif width_mm >= widths[-1]:
        capacity = _IPC2152_1OZ_EXT_10C[widths[-1]]
    else:
        # Linear interpolation
        for i in range(len(widths) - 1):
            if widths[i] <= width_mm <= widths[i + 1]:
                w1, w2 = widths[i], widths[i + 1]
                c1, c2 = _IPC2152_1OZ_EXT_10C[w1], _IPC2152_1OZ_EXT_10C[w2]
                ratio = (width_mm - w1) / (w2 - w1)
                capacity = c1 + ratio * (c2 - c1)
                break
        else:
            capacity = 0.5  # fallback

    # Scale for copper weight
    capacity *= math.sqrt(copper_oz)

    # Derate for internal layers
    if is_internal:
        capacity *= _INTERNAL_DERATING

    return capacity


def _estimate_voltage(net_name: str) -> float:
    """Extract voltage from net name. Returns 0 if not determinable."""
    for pattern, extractor in _VOLTAGE_PATTERNS:
        m = re.search(pattern, net_name)
        if m:
            try:
                return extractor(m)
            except (ValueError, IndexError):
                continue
    return 0.0


class TraceCurrentValidator:
    """Validates power trace widths against estimated current requirements."""

    def analyze(
        self,
        design: Any,
        classified_nets: Any = None,
        interfaces: Any = None,
    ) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []

        if not classified_nets:
            return findings

        # Get power nets
        power_nets = set()
        switching_nodes = set()
        for nc in classified_nets.classified_nets:
            if nc.category == 'power':
                power_nets.add(nc.net_name)
                if nc.subcategory in ('buck', 'switching_node'):
                    switching_nodes.add(nc.net_name)

        if not power_nets:
            return findings

        # Identify SMPS components for current estimation
        smps_components: Dict[str, str] = {}  # ref → type
        for comp in design.components:
            combined = f"{comp.value or ''} {getattr(comp, 'part_number', '') or ''}".strip()
            for pattern, stype in _SMPS_PATTERNS:
                if re.search(pattern, combined):
                    smps_components[comp.reference] = stype
                    break

        # Determine inner vs outer layers
        copper_layers = [l for l in design.layers if l.layer_type in ('signal', 'plane')]
        outer_layers = set()
        if copper_layers:
            outer_layers.add(copper_layers[0].name)
            outer_layers.add(copper_layers[-1].name)

        # Analyze each power net
        analyzed = 0
        for net_name in sorted(power_nets):
            traces = [t for t in design.traces if t.net_name == net_name]
            if not traces:
                continue

            # Find narrowest trace segment with its location (#104)
            narrowest_trace = min(traces, key=lambda t: t.width_mm)
            min_width = narrowest_trace.width_mm
            max_width = max(t.width_mm for t in traces)
            narrowest_x = (narrowest_trace.x1_mm + narrowest_trace.x2_mm) / 2
            narrowest_y = (narrowest_trace.y1_mm + narrowest_trace.y2_mm) / 2
            narrowest_layer = narrowest_trace.layer
            layers_used = set(t.layer for t in traces)

            # Determine if any segments are on internal layers
            is_any_internal = bool(layers_used - outer_layers)

            # Get copper weight from layer info
            copper_oz = 1.0
            for l in design.layers:
                if l.name in layers_used and hasattr(l, 'copper_weight_oz') and l.copper_weight_oz:
                    copper_oz = l.copper_weight_oz
                    break

            # Estimate current capacity from narrowest segment
            capacity = _estimate_current_capacity(min_width, copper_oz, is_any_internal)

            # Estimate required current
            voltage = _estimate_voltage(net_name)
            is_switching = net_name in switching_nodes or net_name.startswith('LX')
            estimated_current = 1.0  # default assumption

            if is_switching:
                estimated_current = 2.0  # Switching nodes carry full inductor current
            elif voltage > 0:
                # Higher voltage rails tend to have lower current
                if voltage >= 5.0:
                    estimated_current = 0.5
                elif voltage >= 3.0:
                    estimated_current = 1.0
                elif voltage >= 1.5:
                    estimated_current = 1.5
                else:
                    estimated_current = 2.0  # Core voltages often high current

            # Flag if capacity is less than estimated current
            if capacity < estimated_current:
                severity = "critical" if capacity < estimated_current * 0.5 else "warning"
                findings.append({
                    "severity": severity,
                    "category": "power_trace_width",
                    "description": (
                        f"Power net {net_name}: narrowest trace {min_width:.3f}mm "
                        f"at ({narrowest_x:.1f}, {narrowest_y:.1f})mm on {narrowest_layer} "
                        f"(~{capacity:.1f}A capacity at 10°C rise) may be insufficient "
                        f"for estimated {estimated_current:.1f}A load"
                    ),
                    "recommendation": (
                        f"Widen {net_name} trace at ({narrowest_x:.1f}, {narrowest_y:.1f})mm "
                        f"on {narrowest_layer} to at least "
                        f"{self._width_for_current(estimated_current, copper_oz, is_any_internal):.3f}mm "
                        f"for {estimated_current:.1f}A at 10°C rise (IPC-2152). "
                        f"{'Switching node — use wide copper pour with short, direct path.' if is_switching else ''}"
                    ),
                    "details": {
                        "net": net_name,
                        "min_width_mm": round(min_width, 4),
                        "max_width_mm": round(max_width, 4),
                        "location_x_mm": round(narrowest_x, 2),
                        "location_y_mm": round(narrowest_y, 2),
                        "location_layer": narrowest_layer,
                        "capacity_a": round(capacity, 2),
                        "estimated_current_a": estimated_current,
                        "copper_oz": copper_oz,
                        "is_internal": is_any_internal,
                        "voltage_v": voltage,
                    },
                })

            analyzed += 1
            if analyzed > 30:  # Cap analysis to top 30 power nets
                break

        return findings

    @staticmethod
    def _width_for_current(target_a: float, copper_oz: float = 1.0, internal: bool = False) -> float:
        """Calculate required trace width for a target current."""
        # Scale target for copper weight and internal derating
        effective_target = target_a / math.sqrt(copper_oz)
        if internal:
            effective_target /= _INTERNAL_DERATING

        # Reverse lookup from IPC table
        widths = sorted(_IPC2152_1OZ_EXT_10C.keys())
        for i in range(len(widths) - 1):
            c1 = _IPC2152_1OZ_EXT_10C[widths[i]]
            c2 = _IPC2152_1OZ_EXT_10C[widths[i + 1]]
            if c1 <= effective_target <= c2:
                ratio = (effective_target - c1) / (c2 - c1)
                return widths[i] + ratio * (widths[i + 1] - widths[i])

        return widths[-1]  # Max width if beyond table

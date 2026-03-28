"""
Impedance Validator — checks actual trace impedance against interface targets.

Uses the parsed stackup (layer thickness, Er) and trace widths to calculate
Z₀ for each high-speed signal, then compares against interface specifications.
Also detects impedance discontinuities at via transitions between layers.
"""
from __future__ import annotations

import math
import logging
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Interface impedance targets (Ohms)
IMPEDANCE_TARGETS: Dict[str, Dict[str, Any]] = {
    "ddr": {
        "z_single_ended": 40.0,  # LPDDR4/5 DQ target
        "z_differential": 80.0,  # CK, DQS differential
        "tolerance_pct": 15,
        "description": "LPDDR4/5 (JEDEC)",
    },
    "usb": {
        "z_single_ended": 45.0,  # USB 2.0 D+/D-
        "z_differential": 90.0,
        "tolerance_pct": 15,
        "description": "USB 2.0 (USB-IF)",
    },
    "ethernet": {
        "z_single_ended": 50.0,
        "z_differential": 100.0,
        "tolerance_pct": 10,
        "description": "100BASE-TX / GbE (IEEE 802.3)",
    },
    "pcie": {
        "z_single_ended": 50.0,
        "z_differential": 85.0,
        "tolerance_pct": 15,
        "description": "PCIe (PCI-SIG)",
    },
    "rf": {
        "z_single_ended": 50.0,
        "tolerance_pct": 10,
        "description": "RF (general 50Ω system)",
    },
    "emmc": {
        "z_single_ended": 50.0,
        "tolerance_pct": 10,
        "description": "eMMC HS200/HS400 (JEDEC)",
    },
    "sdio": {
        "z_single_ended": 50.0,
        "tolerance_pct": 10,
        "description": "SDIO UHS (SD Association)",
    },
}


def _microstrip_z0(w_mm: float, h_mm: float, er: float, t_mm: float = 0.035) -> float:
    """Hammerstad-Jensen microstrip impedance."""
    if w_mm <= 0 or h_mm <= 0 or er <= 0:
        return 0.0
    w_eff = w_mm + (t_mm / math.pi) * (1 + math.log(max(4 * math.pi * w_mm / t_mm, 1e-6)))
    u = w_eff / h_mm
    er_eff = (er + 1) / 2 + (er - 1) / 2 * (1 + 12 / max(u, 1e-6)) ** (-0.5)
    if u <= 1:
        return (60 / math.sqrt(er_eff)) * math.log(8 / u + u / 4)
    return (120 * math.pi) / (math.sqrt(er_eff) * (u + 1.393 + 0.667 * math.log(u + 1.444)))


def _stripline_z0(w_mm: float, b_mm: float, er: float, t_mm: float = 0.018) -> float:
    """Centered stripline impedance."""
    if w_mm <= 0 or b_mm <= 0 or er <= 0 or b_mm <= t_mm:
        return 0.0
    w_eff = w_mm + (t_mm / math.pi) * (1 + math.log(max(4 * math.pi * w_mm / t_mm, 1e-6)))
    m = 6 * (b_mm - t_mm) / (3 * b_mm - 2 * t_mm)
    denom = 0.67 * (0.8 + w_eff / (b_mm - t_mm))
    if denom <= 0 or m / denom <= 0:
        return 0.0
    return (60 / math.sqrt(er)) * math.log(m / denom)


class ImpedanceValidator:
    """
    Validates trace impedance against interface specifications using
    real stackup data and measured trace widths.
    """

    def analyze(
        self,
        design: Any,
        classified_nets: Any = None,
        interfaces: Any = None,
    ) -> List[Dict[str, Any]]:
        """Analyze impedance for all classified high-speed interfaces."""
        findings: List[Dict[str, Any]] = []

        if not classified_nets or not design.layers:
            return findings

        # Build layer stackup model
        layer_model = self._build_layer_model(design)
        if not layer_model:
            findings.append({
                "severity": "info",
                "category": "impedance",
                "description": "Insufficient stackup data for impedance validation",
                "recommendation": "Provide stackup with dielectric thickness and Er values",
                "details": {},
            })
            return findings

        # Group nets by interface category
        interface_nets: Dict[str, List[str]] = {}
        for nc in classified_nets.classified_nets:
            if nc.category in IMPEDANCE_TARGETS:
                interface_nets.setdefault(nc.category, []).append(nc.net_name)

        if not interface_nets:
            return findings

        # For each interface, check impedance on each layer
        for iface, net_names in interface_nets.items():
            target = IMPEDANCE_TARGETS[iface]
            z_target = target["z_single_ended"]
            tol = target["tolerance_pct"] / 100.0

            # Collect trace widths per layer for this interface
            layer_widths: Dict[str, Set[float]] = {}
            net_layers: Dict[str, Set[str]] = {}  # net → {layers}
            sample_count = 0

            for trace in design.traces:
                if trace.net_name in net_names and trace.width_mm > 0:
                    w = round(trace.width_mm, 4)
                    layer = trace.layer
                    layer_widths.setdefault(layer, set()).add(w)
                    net_layers.setdefault(trace.net_name, set()).add(layer)
                    sample_count += 1
                    if sample_count > 5000:  # Cap for performance
                        break

            if not layer_widths:
                continue

            # Calculate impedance for each layer/width combination
            impedance_issues = []
            layer_impedances: Dict[str, Dict[float, float]] = {}  # layer → {width → Z₀}

            for layer, widths in layer_widths.items():
                lm = layer_model.get(layer.lower())
                if not lm:
                    continue

                for w in widths:
                    z0 = lm["calc_fn"](w, lm["h_mm"], lm["er"], lm.get("t_mm", 0.035))
                    if z0 <= 0:
                        continue

                    layer_impedances.setdefault(layer, {})[w] = z0
                    deviation_pct = abs(z0 - z_target) / z_target

                    if deviation_pct > tol:
                        impedance_issues.append({
                            "layer": layer,
                            "width_mm": w,
                            "z0_ohm": round(z0, 1),
                            "target_ohm": z_target,
                            "deviation_pct": round(deviation_pct * 100, 1),
                        })

            # Report impedance issues
            if impedance_issues:
                # Group by severity
                critical = [i for i in impedance_issues if i["deviation_pct"] > 30]
                warning = [i for i in impedance_issues if 15 < i["deviation_pct"] <= 30]

                for issue in critical:
                    findings.append({
                        "severity": "critical",
                        "category": f"{iface}_impedance",
                        "description": (
                            f"{iface.upper()} trace on {issue['layer']}: Z₀={issue['z0_ohm']}Ω "
                            f"(target {issue['target_ohm']}Ω, {issue['deviation_pct']:.0f}% off) "
                            f"at w={issue['width_mm']:.4f}mm — {target['description']}"
                        ),
                        "recommendation": (
                            f"Adjust trace width on {issue['layer']} to achieve {issue['target_ohm']}Ω. "
                            f"Current width {issue['width_mm']:.4f}mm gives {issue['z0_ohm']}Ω."
                        ),
                        "details": issue,
                    })
                for issue in warning:
                    findings.append({
                        "severity": "warning",
                        "category": f"{iface}_impedance",
                        "description": (
                            f"{iface.upper()} trace on {issue['layer']}: Z₀={issue['z0_ohm']}Ω "
                            f"(target {issue['target_ohm']}Ω, {issue['deviation_pct']:.0f}% off) "
                            f"at w={issue['width_mm']:.4f}mm"
                        ),
                        "recommendation": (
                            f"Review trace width on {issue['layer']} for {issue['target_ohm']}Ω target."
                        ),
                        "details": issue,
                    })

            # Check for impedance discontinuities at layer transitions
            multi_layer_nets = {n: layers for n, layers in net_layers.items()
                                if len(layers) > 1}
            if multi_layer_nets and layer_impedances:
                disc_reported: Set[tuple] = set()
                for net, layers in list(multi_layer_nets.items())[:20]:
                    z_values = {}
                    for layer in layers:
                        lm = layer_model.get(layer.lower())
                        if not lm:
                            continue
                        # Use most common width for this net on this layer
                        net_widths = [t.width_mm for t in design.traces
                                      if t.net_name == net and t.layer == layer]
                        if net_widths:
                            w = round(max(set(net_widths), key=net_widths.count), 4)
                            z = lm["calc_fn"](w, lm["h_mm"], lm["er"])
                            if z > 0:
                                z_values[layer] = z

                    if len(z_values) >= 2:
                        z_list = list(z_values.values())
                        z_min, z_max = min(z_list), max(z_list)
                        discontinuity = z_max - z_min
                        disc_key = (iface, round(z_min), round(z_max))
                        if discontinuity > 10 and disc_key not in disc_reported:
                            disc_reported.add(disc_key)
                            findings.append({
                                "severity": "warning" if discontinuity < 20 else "critical",
                                "category": f"{iface}_impedance_discontinuity",
                                "description": (
                                    f"{iface.upper()} net {net} has {discontinuity:.0f}Ω impedance "
                                    f"discontinuity across layers: "
                                    f"{', '.join(f'{l}={z:.0f}Ω' for l, z in z_values.items())}"
                                ),
                                "recommendation": (
                                    "Use different trace widths per layer to maintain target impedance, "
                                    "or minimize layer transitions for this interface."
                                ),
                                "details": {
                                    "net": net,
                                    "layer_impedances": {l: round(z, 1) for l, z in z_values.items()},
                                    "discontinuity_ohm": round(discontinuity, 1),
                                },
                            })

        return findings

    def _build_layer_model(self, design: Any) -> Dict[str, Dict]:
        """Build impedance calculation model from stackup.

        Returns dict mapping layer_name (lowercase) to calculation parameters.
        """
        model: Dict[str, Dict] = {}
        layers = design.layers
        if not layers:
            return model

        # Find copper and dielectric layers in order
        copper_layers = []
        dielectric_layers = []
        for l in layers:
            if l.layer_type in ('signal', 'plane'):
                copper_layers.append(l)
            elif l.layer_type == 'dielectric':
                dielectric_layers.append(l)

        if not copper_layers or not dielectric_layers:
            return model

        # For each signal layer, determine if it's microstrip (outer) or stripline (inner)
        # and find the adjacent dielectric thickness
        for i, cu in enumerate(copper_layers):
            if cu.layer_type != 'signal':
                continue

            # Check if outer (first or last copper layer) → microstrip
            # or inner → stripline
            is_outer = (i == 0 or i == len(copper_layers) - 1)

            if is_outer:
                # Microstrip: need dielectric to nearest reference plane
                # Find the dielectric between this layer and adjacent reference
                h_mm = self._find_adjacent_dielectric_thickness(cu, layers)
                er = self._find_adjacent_dielectric_er(cu, layers)
                if h_mm > 0 and er > 1:
                    copper_oz = cu.copper_weight_oz or 1.0
                    t_mm = copper_oz * 0.035  # 1oz = 35μm
                    model[cu.name.lower()] = {
                        "type": "microstrip",
                        "h_mm": h_mm,
                        "er": er,
                        "t_mm": t_mm,
                        "calc_fn": _microstrip_z0,
                    }
            else:
                # Stripline: need total dielectric between two reference planes
                h_above, h_below, er = self._find_stripline_params(cu, layers, copper_layers, i)
                if h_above > 0 and h_below > 0 and er > 1:
                    b = h_above + h_below
                    copper_oz = cu.copper_weight_oz or 0.5
                    t_mm = copper_oz * 0.035
                    model[cu.name.lower()] = {
                        "type": "stripline",
                        "h_mm": b,  # total height between planes
                        "er": er,
                        "t_mm": t_mm,
                        "calc_fn": _stripline_z0,
                    }

        return model

    def _find_adjacent_dielectric_thickness(self, copper_layer: Any, all_layers: list) -> float:
        """Find dielectric thickness between copper layer and nearest reference plane."""
        cu_row = getattr(copper_layer, 'number', getattr(copper_layer, 'row', 0))
        # Search for nearest dielectric layer
        for l in all_layers:
            if l.layer_type == 'dielectric' and abs(getattr(l, 'number', getattr(l, 'row', 0)) - cu_row) <= 2:
                if l.thickness_mm and l.thickness_mm > 0:
                    return l.thickness_mm
        return 0.0

    def _find_adjacent_dielectric_er(self, copper_layer: Any, all_layers: list) -> float:
        """Find Er of dielectric adjacent to copper layer."""
        cu_row = getattr(copper_layer, 'number', getattr(copper_layer, 'row', 0))
        for l in all_layers:
            if l.layer_type == 'dielectric' and abs(getattr(l, 'number', getattr(l, 'row', 0)) - cu_row) <= 2:
                if l.dielectric_constant and l.dielectric_constant > 1:
                    return l.dielectric_constant
        return 4.2  # FR-4 default

    def _find_stripline_params(
        self, cu_layer: Any, all_layers: list, copper_layers: list, cu_idx: int
    ) -> tuple:
        """Find stripline parameters (h_above, h_below, er) for inner copper layer."""
        cu_row = getattr(cu_layer, 'number', getattr(cu_layer, 'row', 0))

        # Find dielectric above (between this layer and previous copper)
        h_above = 0.0
        h_below = 0.0
        er = 4.2

        for l in all_layers:
            if l.layer_type != 'dielectric':
                continue
            if getattr(l, 'number', getattr(l, 'row', 0)) < cu_row and abs(getattr(l, 'number', getattr(l, 'row', 0)) - cu_row) <= 2:
                if l.thickness_mm and l.thickness_mm > 0:
                    h_above = l.thickness_mm
                    if l.dielectric_constant and l.dielectric_constant > 1:
                        er = l.dielectric_constant
            elif getattr(l, 'number', getattr(l, 'row', 0)) > cu_row and abs(getattr(l, 'number', getattr(l, 'row', 0)) - cu_row) <= 2:
                if l.thickness_mm and l.thickness_mm > 0:
                    h_below = l.thickness_mm

        return h_above, h_below, er

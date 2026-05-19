"""
Impedance Validator — checks actual trace impedance against interface targets.

Uses the parsed stackup (layer thickness, Er) and trace widths to calculate
Z₀ for each high-speed signal, then compares against interface specifications.
Also detects impedance discontinuities at via transitions between layers.
"""
from __future__ import annotations

import logging
import math
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


def _diff_microstrip_z0(w_mm: float, s_mm: float, h_mm: float, er: float, t_mm: float = 0.035) -> float:
    """Edge-coupled differential microstrip impedance.

    Uses Wadell/Kirschning approximation:
    Z_diff = 2 * Z_se * (1 - 0.48 * exp(-0.96 * s/h))
    where s = edge-to-edge spacing between P and N traces.
    """
    z_se = _microstrip_z0(w_mm, h_mm, er, t_mm)
    if z_se <= 0 or h_mm <= 0:
        return 0.0
    # s is center-to-center spacing; edge-to-edge = s - w
    s_edge = max(s_mm - w_mm, 0.01)
    coupling = 0.48 * math.exp(-0.96 * s_edge / h_mm)
    return 2 * z_se * (1 - coupling)


def _diff_stripline_z0(w_mm: float, s_mm: float, b_mm: float, er: float, t_mm: float = 0.018) -> float:
    """Edge-coupled differential stripline impedance.

    Z_diff = 2 * Z_se * (1 - 0.347 * exp(-2.9 * s/b))
    """
    z_se = _stripline_z0(w_mm, b_mm, er, t_mm)
    if z_se <= 0 or b_mm <= 0:
        return 0.0
    s_edge = max(s_mm - w_mm, 0.01)
    coupling = 0.347 * math.exp(-2.9 * s_edge / b_mm)
    return 2 * z_se * (1 - coupling)


def _measure_diff_pair_spacing(
    design: Any, p_net: str, n_net: str
) -> Optional[tuple]:
    """Measure actual P-N trace spacing from coordinates.

    Returns (median_spacing_mm, trace_width_mm, layer, sample_count) or None.
    """
    p_traces = [t for t in design.traces if t.net_name == p_net]
    n_traces = [t for t in design.traces if t.net_name == n_net]

    if not p_traces or not n_traces:
        return None

    spacings: list[float] = []
    widths: list[float] = []
    layers: list[str] = []

    for pt in p_traces:
        if (pt.length_mm or 0) < 0.5:
            continue
        for nt in n_traces:
            if pt.layer != nt.layer or (nt.length_mm or 0) < 0.5:
                continue
            # Check parallelism via dot product
            pdx, pdy = pt.x2_mm - pt.x1_mm, pt.y2_mm - pt.y1_mm
            ndx, ndy = nt.x2_mm - nt.x1_mm, nt.y2_mm - nt.y1_mm
            p_len = math.sqrt(pdx**2 + pdy**2)
            n_len = math.sqrt(ndx**2 + ndy**2)
            if p_len < 0.3 or n_len < 0.3:
                continue
            dot = (pdx * ndx + pdy * ndy) / (p_len * n_len)
            if abs(dot) < 0.9:
                continue
            # Center-to-center distance
            pcx = (pt.x1_mm + pt.x2_mm) / 2
            pcy = (pt.y1_mm + pt.y2_mm) / 2
            ncx = (nt.x1_mm + nt.x2_mm) / 2
            ncy = (nt.y1_mm + nt.y2_mm) / 2
            dist = math.sqrt((pcx - ncx)**2 + (pcy - ncy)**2)
            if 0.05 < dist < 3.0:
                spacings.append(dist)
                widths.append(pt.width_mm)
                layers.append(pt.layer)

    if len(spacings) < 3:
        return None

    med_idx = len(spacings) // 2
    sorted_s = sorted(spacings)
    med_w = sorted(widths)[len(widths) // 2]
    # Most common layer
    from collections import Counter
    common_layer = Counter(layers).most_common(1)[0][0]

    return (sorted_s[med_idx], med_w, common_layer, len(spacings))


# Differential impedance targets
DIFF_IMPEDANCE_TARGETS: Dict[str, Dict[str, Any]] = {
    "ddr": {"z_diff": 80.0, "tolerance_pct": 15, "desc": "LPDDR4/5 CK/DQS (JEDEC)"},
    "usb": {"z_diff": 90.0, "tolerance_pct": 15, "desc": "USB 2.0 (USB-IF)"},
    "ethernet": {"z_diff": 100.0, "tolerance_pct": 10, "desc": "100BASE-TX/GbE (IEEE 802.3)"},
    "pcie": {"z_diff": 85.0, "tolerance_pct": 15, "desc": "PCIe (PCI-SIG)"},
    "lvds": {"z_diff": 100.0, "tolerance_pct": 10, "desc": "LVDS (ANSI/TIA-644)"},
}


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
            # Skip very short segments (<0.5mm) as they're typically pad
            # transitions or connector landings, not controlled-impedance routing
            layer_widths: Dict[str, Set[float]] = {}
            net_layers: Dict[str, Set[str]] = {}  # net → {layers}
            sample_count = 0
            MIN_TRACE_LENGTH_MM = 0.5  # Ignore pad transitions
            # For inner layers, only flag impedance issues on traces >5mm
            # (short inner-layer segments are typically BGA escape routing,
            # not controlled-impedance traces)
            MIN_INNER_TRACE_MM = 5.0

            for trace in design.traces:
                if trace.net_name in net_names and trace.width_mm > 0:
                    seg_len = trace.length_mm or 0
                    if seg_len < MIN_TRACE_LENGTH_MM:
                        continue  # Skip pad-like short segments
                    w = round(trace.width_mm, 4)
                    layer = trace.layer
                    layer_widths.setdefault(layer, set()).add(w)
                    net_layers.setdefault(trace.net_name, set()).add(layer)
                    sample_count += 1
                    if sample_count > 5000:  # Cap for performance
                        break

            if not layer_widths:
                continue

            # Calculate total trace length per layer for this interface
            layer_total_length: Dict[str, float] = {}
            for trace in design.traces:
                if trace.net_name in net_names and trace.width_mm > 0:
                    seg_len = trace.length_mm or 0
                    layer_total_length[trace.layer] = layer_total_length.get(trace.layer, 0) + seg_len

            # Determine outer vs inner layers
            copper_layers = [l for l in design.layers if l.layer_type in ('signal', 'plane')]
            outer_layer_names = set()
            if copper_layers:
                outer_layer_names.add(copper_layers[0].name)
                outer_layer_names.add(copper_layers[-1].name)

            # Calculate impedance for each layer/width combination
            impedance_issues = []
            layer_impedances: Dict[str, Dict[float, float]] = {}  # layer → {width → Z₀}

            for layer, widths in layer_widths.items():
                lm = layer_model.get(layer.lower())
                if not lm:
                    continue

                # Skip inner layers with minimal routing (< 5mm total) —
                # short BGA escape segments don't need impedance control
                is_inner = layer not in outer_layer_names
                total_on_layer = layer_total_length.get(layer, 0)
                if is_inner and total_on_layer < MIN_INNER_TRACE_MM:
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
                            "total_length_mm": round(total_on_layer, 1),
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

        # === Differential pair impedance analysis ===
        if hasattr(classified_nets, 'differential_pairs'):
            for dp in classified_nets.differential_pairs:
                if dp.category not in DIFF_IMPEDANCE_TARGETS:
                    continue

                target = DIFF_IMPEDANCE_TARGETS[dp.category]
                z_diff_target = target["z_diff"]
                tol = target["tolerance_pct"] / 100.0

                # Measure actual P-N spacing
                measurement = _measure_diff_pair_spacing(
                    design, dp.positive_net, dp.negative_net
                )
                if not measurement:
                    continue

                spacing_mm, width_mm, layer, samples = measurement
                lm = layer_model.get(layer.lower())
                if not lm:
                    continue

                # Calculate differential impedance
                if lm["type"] == "microstrip":
                    z_diff = _diff_microstrip_z0(
                        width_mm, spacing_mm, lm["h_mm"], lm["er"], lm.get("t_mm", 0.035)
                    )
                else:
                    z_diff = _diff_stripline_z0(
                        width_mm, spacing_mm, lm["h_mm"], lm["er"], lm.get("t_mm", 0.018)
                    )

                if z_diff <= 0:
                    continue

                deviation = abs(z_diff - z_diff_target) / z_diff_target
                if deviation > tol:
                    z_se = lm["calc_fn"](width_mm, lm["h_mm"], lm["er"])
                    severity = "critical" if deviation > 0.3 else "warning"
                    findings.append({
                        "severity": severity,
                        "category": f"{dp.category}_diff_impedance",
                        "description": (
                            f"{dp.category.upper()} diff pair {dp.pair_name}: "
                            f"Z_diff={z_diff:.0f}Ω (target {z_diff_target:.0f}Ω, "
                            f"{deviation*100:.0f}% off) — w={width_mm:.4f}mm, "
                            f"s={spacing_mm:.3f}mm, Z_SE={z_se:.0f}Ω on {layer} "
                            f"— {target['desc']}"
                        ),
                        "recommendation": (
                            f"Adjust {dp.pair_name} trace width or spacing to achieve "
                            f"{z_diff_target:.0f}Ω differential. Current: w={width_mm:.4f}mm, "
                            f"spacing={spacing_mm:.3f}mm on {layer}."
                        ),
                        "details": {
                            "pair": dp.pair_name,
                            "z_diff_ohm": round(z_diff, 1),
                            "z_se_ohm": round(z_se, 1),
                            "target_diff_ohm": z_diff_target,
                            "width_mm": round(width_mm, 4),
                            "spacing_mm": round(spacing_mm, 4),
                            "layer": layer,
                            "samples": samples,
                        },
                    })
                else:
                    findings.append({
                        "severity": "info",
                        "category": f"{dp.category}_diff_impedance",
                        "description": (
                            f"{dp.category.upper()} diff pair {dp.pair_name}: "
                            f"Z_diff={z_diff:.0f}Ω ✓ (target {z_diff_target:.0f}Ω) "
                            f"— w={width_mm:.4f}mm, s={spacing_mm:.3f}mm on {layer}"
                        ),
                        "recommendation": "",
                        "details": {
                            "pair": dp.pair_name,
                            "z_diff_ohm": round(z_diff, 1),
                            "target_diff_ohm": z_diff_target,
                            "width_mm": round(width_mm, 4),
                            "spacing_mm": round(spacing_mm, 4),
                            "layer": layer,
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

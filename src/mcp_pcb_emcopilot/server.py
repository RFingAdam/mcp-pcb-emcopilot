#!/usr/bin/env python3
"""MCP server for PCB design review, EMC analysis, and signal integrity.

Provides ~57 tools for PCB engineers covering:
- File parsing (KiCad, ODB++, Gerber, Altium, IPC-2581, STEP)
- Impedance (microstrip, stripline, differential pairs)
- Signal integrity (timing, crosstalk, via transitions)
- EMC compliance (current loops, emissions, shielding, grounding, ESD)
- High-speed digital (DDR, PCIe, USB, Ethernet, length matching)
- Power integrity (PDN, decoupling, VRM)
- DFM (solder paste, placement, assembly, tolerance)
- Thermal (power dissipation, hotspot, copper spreading, thermal via)
- Antenna/EMI (trace antenna, slot, common mode, cable coupling)
- Classification (net classification, interface detection, design type)
- Design validation (cross-validation, BOM, schematic-layout)
- 3D / mechanical (STEP parsing, clearances, enclosure fit)
- Session management

Claude Code acts as the AI orchestrator — this server provides the computational tools.
"""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import asdict
from enum import Enum
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .session import DesignSessionManager
from .models.pcb_data import PCBDesignData
from .parsers import parse_pcb_file, detect_format
from .errors import (
    PCBError, ValidationError, ParseError, SessionError,
    error_response, validate_positive, validate_non_negative,
    validate_range, validate_string,
)

# Physical constants
C0 = 299792458.0
MU0 = 4 * math.pi * 1e-7
EPS0 = 8.854e-12

server = Server("mcp-pcb-emcopilot")
sessions = DesignSessionManager()


# =============================================================================
# Original calculation functions (preserved for regression compatibility)
# =============================================================================

def calc_microstrip_impedance(trace_width_mm: float, dielectric_height_mm: float, trace_thickness_mm: float, dielectric_constant: float) -> dict[str, Any]:
    w = trace_width_mm
    h = dielectric_height_mm
    t = trace_thickness_mm
    er = dielectric_constant
    w_eff = w + (t / math.pi) * math.log(4 * math.e / math.sqrt((t / h) ** 2 + (t / (math.pi * (w + 1.1 * t))) ** 2))
    f_w_h = (1 + 12 * h / w_eff) ** (-0.5)
    er_eff = (er + 1) / 2 + (er - 1) / 2 * f_w_h
    if w_eff / h <= 1:
        z0 = (60 / math.sqrt(er_eff)) * math.log(8 * h / w_eff + 0.25 * w_eff / h)
    else:
        z0 = (120 * math.pi) / (math.sqrt(er_eff) * (w_eff / h + 1.393 + 0.667 * math.log(w_eff / h + 1.444)))
    delay = 84.72 * math.sqrt(er_eff)
    return {
        "impedance_ohms": round(z0, 2),
        "effective_er": round(er_eff, 3),
        "propagation_delay_ps_per_inch": round(delay, 2),
        "trace_type": "microstrip",
        "parameters": {"trace_width_mm": w, "dielectric_height_mm": h, "trace_thickness_mm": t, "dielectric_constant": er, "effective_width_mm": round(w_eff, 4)},
    }


def calc_stripline_impedance(trace_width_mm: float, dielectric_height_mm: float, trace_thickness_mm: float, dielectric_constant: float) -> dict[str, Any]:
    w = trace_width_mm
    b = dielectric_height_mm * 2
    t = trace_thickness_mm
    er = dielectric_constant
    w_eff = w if t == 0 else w + (t / math.pi) * (1 + math.log(4 * math.pi * w / t))
    if w_eff / b <= 0.35:
        z0 = (60 / math.sqrt(er)) * math.log(4 * b / (0.67 * math.pi * (0.8 * w_eff + t)))
    else:
        z0 = (94.15 / math.sqrt(er)) / (w_eff / b + (2 / math.pi) * math.log((math.e * math.pi / 2) * (w_eff / b + 0.94)))
    delay = 84.72 * math.sqrt(er)
    return {
        "impedance_ohms": round(z0, 2),
        "effective_er": round(er, 3),
        "propagation_delay_ps_per_inch": round(delay, 2),
        "trace_type": "stripline",
        "parameters": {"trace_width_mm": w, "dielectric_height_mm": dielectric_height_mm, "total_stackup_height_mm": b, "trace_thickness_mm": t, "dielectric_constant": er},
    }


def calc_differential_impedance(trace_width_mm: float, trace_spacing_mm: float, dielectric_height_mm: float, trace_thickness_mm: float, dielectric_constant: float, trace_type: str = "microstrip") -> dict[str, Any]:
    if trace_type == "microstrip":
        single = calc_microstrip_impedance(trace_width_mm, dielectric_height_mm, trace_thickness_mm, dielectric_constant)
    else:
        single = calc_stripline_impedance(trace_width_mm, dielectric_height_mm, trace_thickness_mm, dielectric_constant)
    z0 = single["impedance_ohms"]
    s, h = trace_spacing_mm, dielectric_height_mm
    if trace_type == "microstrip":
        z_diff = 2 * z0 * (1 - 0.48 * math.exp(-0.96 * s / h))
    else:
        k_odd = math.exp(-2.0 * s / h)
        z_diff = 2 * z0 * math.sqrt(1 - k_odd ** 2)
    return {
        "differential_impedance_ohms": round(z_diff, 2),
        "single_ended_z0": z0,
        "effective_er": single["effective_er"],
        "propagation_delay_ps_per_inch": single["propagation_delay_ps_per_inch"],
        "trace_type": f"differential_{trace_type}",
        "parameters": {"trace_width_mm": trace_width_mm, "trace_spacing_mm": s, "dielectric_height_mm": h, "trace_thickness_mm": trace_thickness_mm, "dielectric_constant": dielectric_constant},
    }


def calc_trace_width_for_current(current_amps: float, temp_rise_c: float, copper_thickness_oz: float, layer_type: str = "external") -> dict[str, Any]:
    thickness_mils = copper_thickness_oz * 1.37
    k = 0.048 if layer_type == "external" else 0.024
    b, c = 0.44, 0.725
    area = (current_amps / (k * (temp_rise_c ** b))) ** (1 / c)
    width_mils = area / thickness_mils
    width_mm = width_mils * 0.0254
    return {"trace_width_mm": round(width_mm, 3), "trace_width_mils": round(width_mils, 1), "cross_section_mils2": round(area, 1), "current_amps": current_amps, "temp_rise_c": temp_rise_c, "copper_oz": copper_thickness_oz, "layer_type": layer_type, "standard": "IPC-2221"}


def analyze_trace_timing(trace_length_mm: float, effective_er: float, data_rate_gbps: float, rise_time_ps: float, setup_time_ps: float, hold_time_ps: float) -> dict[str, Any]:
    prop_delay_ps_per_mm = (1000 / C0) * math.sqrt(effective_er) * 1e12
    total_delay_ps = trace_length_mm * prop_delay_ps_per_mm
    ui_ps = 1e12 / (data_rate_gbps * 1e9)
    setup_margin = ui_ps - total_delay_ps - setup_time_ps - rise_time_ps / 2
    hold_margin = total_delay_ps - hold_time_ps + rise_time_ps / 2
    issues = []
    if setup_margin < 0:
        issues.append(f"Setup timing violated by {-setup_margin:.1f} ps")
    if hold_margin < 0:
        issues.append(f"Hold timing violated by {-hold_margin:.1f} ps")
    if total_delay_ps > ui_ps * 0.7:
        issues.append("Propagation delay > 70% of UI, consider shorter trace")
    return {"propagation_delay_ps": round(total_delay_ps, 1), "setup_margin_ps": round(setup_margin, 1), "hold_margin_ps": round(hold_margin, 1), "timing_valid": len(issues) == 0, "issues": issues}


def analyze_crosstalk(trace_spacing_mm: float, trace_width_mm: float, dielectric_height_mm: float, coupling_length_mm: float, rise_time_ps: float) -> dict[str, Any]:
    s, h, l = trace_spacing_mm, dielectric_height_mm, coupling_length_mm
    coupling_factor = math.exp(-2 * s / h)
    next_percent = 25 * coupling_factor * min(l / 25.4, 1.0)
    rise_time_s = rise_time_ps * 1e-12
    critical_length_mm = (C0 / 2) * rise_time_s / math.sqrt(4.0) * 1000
    fext_percent = 15 * coupling_factor * (l / critical_length_mm) if l > critical_length_mm else 15 * coupling_factor
    max_xtalk = max(next_percent, fext_percent)
    severity = "critical" if max_xtalk > 15 else "warning" if max_xtalk > 10 else "marginal" if max_xtalk > 5 else "acceptable"
    recs = []
    if max_xtalk > 5:
        min_spacing = 3 * trace_width_mm
        if s < min_spacing:
            recs.append(f"Increase spacing to {min_spacing:.2f}mm (3W rule)")
        if l > 50:
            recs.append("Consider adding ground guard traces")
        if h < s:
            recs.append("Consider tighter coupling to reference plane")
    return {"near_end_crosstalk_percent": round(next_percent, 2), "far_end_crosstalk_percent": round(fext_percent, 2), "severity": severity, "recommendations": recs}


def analyze_via(via_diameter_mm: float, via_length_mm: float, pad_diameter_mm: float, antipad_diameter_mm: float, dielectric_constant: float, frequency_ghz: float) -> dict[str, Any]:
    d, h = via_diameter_mm, via_length_mm
    inductance_nh = 5.08 * h * (math.log(4 * h / d) + 1)
    capacitance_pf = 1.41 * dielectric_constant * h * pad_diameter_mm / (antipad_diameter_mm - pad_diameter_mm)
    z_via = math.sqrt(inductance_nh / capacitance_pf) * 1000
    f_res_ghz = 1 / (2 * math.pi * math.sqrt(inductance_nh * 1e-9 * capacitance_pf * 1e-12)) / 1e9
    f = frequency_ghz * 1e9
    omega = 2 * math.pi * f
    xl = omega * inductance_nh * 1e-9
    xc = 1 / (omega * capacitance_pf * 1e-12)
    z_net = abs(xl - xc)
    s21_db = -20 * math.log10(1 + z_net / 100)
    issues = []
    if z_via < 30 or z_via > 70:
        issues.append(f"Via impedance {z_via:.1f} ohms deviates from 50 ohms")
    if f_res_ghz < frequency_ghz * 3:
        issues.append(f"Via resonance at {f_res_ghz:.2f} GHz near operating frequency")
    return {"inductance_nh": round(inductance_nh, 3), "capacitance_pf": round(capacitance_pf, 3), "characteristic_impedance_ohms": round(z_via, 1), "resonant_frequency_ghz": round(f_res_ghz, 2), "insertion_loss_db": round(s21_db, 2), "issues": issues, "parameters": {"via_diameter_mm": d, "via_length_mm": h, "pad_diameter_mm": pad_diameter_mm, "antipad_diameter_mm": antipad_diameter_mm, "dielectric_constant": dielectric_constant, "frequency_ghz": frequency_ghz}}


def analyze_current_loop(loop_area_mm2: float, current_ma: float, frequency_mhz: float) -> dict[str, Any]:
    area_m2 = loop_area_mm2 * 1e-6
    current_a = current_ma * 1e-3
    freq_hz = frequency_mhz * 1e6
    distance = 3.0
    e_field = (120 * math.pi ** 2 * current_a * area_m2 * freq_hz ** 2) / (C0 ** 2 * distance)
    e_field_dbuv = 20 * math.log10(e_field * 1e6)
    limit_dbuv = 40 if frequency_mhz < 88 else 43.5 if frequency_mhz < 216 else 46 if frequency_mhz < 960 else 54
    margin_db = limit_dbuv - e_field_dbuv
    recs = []
    if margin_db < 6:
        recs.append("Reduce loop area by routing signal and return paths closer together")
        recs.append("Consider adding bypass capacitors near high-frequency sources")
    if margin_db < 0:
        recs.append("CRITICAL: Estimated emissions exceed FCC Class B limit")
        recs.append("Add EMI filter or shield")
    return {"e_field_dbuv_m": round(e_field_dbuv, 1), "fcc_class_b_limit_dbuv_m": limit_dbuv, "margin_db": round(margin_db, 1), "compliant": margin_db > 0, "margin_acceptable": margin_db > 6, "recommendations": recs, "parameters": {"loop_area_mm2": loop_area_mm2, "current_ma": current_ma, "frequency_mhz": frequency_mhz, "distance_m": distance}}


def estimate_rise_time_bandwidth(rise_time_ps: float) -> dict[str, Any]:
    rise_time_s = rise_time_ps * 1e-12
    bw_3db_ghz = 0.35 / rise_time_s / 1e9
    f_5th_ghz = 5 * bw_3db_ghz / math.pi
    f_knee_ghz = 1 / (math.pi * rise_time_s) / 1e9
    return {"rise_time_ps": rise_time_ps, "bandwidth_3db_ghz": round(bw_3db_ghz, 2), "knee_frequency_ghz": round(f_knee_ghz, 2), "fifth_harmonic_ghz": round(f_5th_ghz, 2), "notes": [f"PCB traces should be treated as transmission lines above {bw_3db_ghz/10:.2f} GHz", f"EMC concerns extend up to {f_knee_ghz:.2f} GHz"]}


# --- New RF engineering calculators (added from review) ---

def calc_cpw_impedance(trace_width_mm: float, gap_mm: float, dielectric_height_mm: float, trace_thickness_mm: float, dielectric_constant: float, has_ground_plane: bool = True) -> dict[str, Any]:
    """Coplanar waveguide impedance (grounded CPW by default, ungrounded if has_ground_plane=False).

    Uses Wen's conformal mapping method with Hilberg's approximation for K(k)/K'(k).
    """
    w = trace_width_mm
    s = gap_mm
    a = w / 2
    b = w / 2 + s
    t = trace_thickness_mm

    # Effective width accounting for trace thickness
    if t > 0:
        delta = (1.25 * t / math.pi) * (1 + math.log(4 * math.pi * w / t))
        a_eff = a + delta / 2
        b_eff = b - delta / 2
    else:
        a_eff = a
        b_eff = b

    k0 = a_eff / b_eff
    k0_prime = math.sqrt(1 - k0 ** 2)

    # Hilberg approximation for K(k)/K'(k) ratio
    def _kk_ratio(k):
        if k < 1e-10:
            return 0.0
        kp = math.sqrt(1 - k ** 2)
        if k <= 1 / math.sqrt(2):
            return math.pi / math.log(2 * (1 + math.sqrt(kp)) / (1 - math.sqrt(kp)))
        else:
            return math.log(2 * (1 + math.sqrt(k)) / (1 - math.sqrt(k))) / math.pi

    if has_ground_plane:
        # Grounded CPW: includes ground plane effect
        h = dielectric_height_mm
        k1 = math.tanh(math.pi * a_eff / (4 * h)) / math.tanh(math.pi * b_eff / (4 * h))
        k1_prime = math.sqrt(1 - k1 ** 2)

        kk0 = _kk_ratio(k0)
        kk1 = _kk_ratio(k1)

        er_eff = 1 + (dielectric_constant - 1) / 2 * kk1 / kk0 if kk0 > 0 else dielectric_constant
        z0 = (60 * math.pi / math.sqrt(er_eff)) / (kk0 + kk1) if (kk0 + kk1) > 0 else 50.0
        cpw_type = "grounded_cpw"
    else:
        # Ungrounded CPW
        kk0 = _kk_ratio(k0)
        er_eff = (1 + dielectric_constant) / 2
        z0 = (30 * math.pi / math.sqrt(er_eff)) / kk0 if kk0 > 0 else 50.0
        cpw_type = "cpw"

    prop_delay = 1000 / C0 * math.sqrt(er_eff) * 1e12 * 25.4  # ps/inch

    return {
        "impedance_ohms": round(z0, 2),
        "effective_er": round(er_eff, 3),
        "propagation_delay_ps_per_inch": round(prop_delay, 1),
        "cpw_type": cpw_type,
        "parameters": {
            "trace_width_mm": w, "gap_mm": gap_mm,
            "dielectric_height_mm": dielectric_height_mm,
            "trace_thickness_mm": trace_thickness_mm,
            "dielectric_constant": dielectric_constant,
        },
    }


def calc_skin_effect(frequency_mhz: float, copper_thickness_oz: float = 1.0, surface_roughness_um: float = 0.5) -> dict[str, Any]:
    """Calculate skin depth, AC resistance factor, and conductor loss.

    Includes Hammerstad-Bekkadal surface roughness correction.
    """
    f = frequency_mhz * 1e6
    mu0 = 4 * math.pi * 1e-7
    sigma_cu = 5.8e7  # S/m for annealed copper
    rho_cu = 1 / sigma_cu

    # Skin depth
    if f > 0:
        delta = math.sqrt(rho_cu / (math.pi * f * mu0))
    else:
        return {"skin_depth_um": float("inf"), "ac_resistance_factor": 1.0, "notes": ["DC: no skin effect"]}

    delta_um = delta * 1e6
    copper_thickness_um = copper_thickness_oz * 35.0  # 1oz = 35um

    # AC resistance factor (ratio of AC to DC resistance)
    if delta_um < copper_thickness_um:
        ac_factor = copper_thickness_um / delta_um
    else:
        ac_factor = 1.0

    # Hammerstad-Bekkadal surface roughness correction
    rq = surface_roughness_um * 1e-6
    roughness_factor = 1.0
    if delta > 0:
        x = (2 * rq / delta) ** 2
        roughness_factor = 1 + (2 / math.pi) * math.atan(1.4 * x)

    total_ac_factor = ac_factor * roughness_factor

    # Conductor loss per unit length (dB/inch) for a 50-ohm line
    loss_per_inch = 0.0
    if delta_um < copper_thickness_um:
        rs = math.sqrt(math.pi * f * mu0 * rho_cu) * roughness_factor
        loss_per_inch = (rs / (2 * 50)) * 25.4e-3 * 8.686  # Np/m to dB/inch

    notes = []
    if delta_um < copper_thickness_um / 2:
        notes.append(f"Skin depth ({delta_um:.1f} um) << copper ({copper_thickness_um:.0f} um): significant AC loss")
    elif delta_um < copper_thickness_um:
        notes.append(f"Skin depth ({delta_um:.1f} um) < copper ({copper_thickness_um:.0f} um): moderate AC loss")
    else:
        notes.append(f"Skin depth ({delta_um:.1f} um) > copper ({copper_thickness_um:.0f} um): minimal skin effect")
    if surface_roughness_um > 1.0:
        notes.append(f"Surface roughness {surface_roughness_um} um adds {(roughness_factor - 1) * 100:.0f}% additional loss")

    return {
        "skin_depth_um": round(delta_um, 2),
        "ac_resistance_factor": round(total_ac_factor, 2),
        "roughness_correction_factor": round(roughness_factor, 3),
        "conductor_loss_db_per_inch": round(loss_per_inch, 4),
        "frequency_mhz": frequency_mhz,
        "copper_thickness_um": copper_thickness_um,
        "notes": notes,
    }


def calc_dielectric_loss(frequency_mhz: float, dielectric_constant: float, loss_tangent: float, trace_length_mm: float) -> dict[str, Any]:
    """Calculate dielectric loss for a given trace at frequency.

    Uses: alpha_d = (pi * f * sqrt(er_eff) * tan_delta) / c
    """
    f = frequency_mhz * 1e6
    er = dielectric_constant
    tan_d = loss_tangent

    # Dielectric attenuation constant (Np/m)
    if f > 0 and tan_d > 0:
        alpha_d = (math.pi * f * math.sqrt(er) * tan_d) / C0
        loss_db_per_m = alpha_d * 8.686
        loss_db_per_inch = loss_db_per_m * 0.0254
        total_loss_db = loss_db_per_m * (trace_length_mm / 1000)
    else:
        loss_db_per_m = 0.0
        loss_db_per_inch = 0.0
        total_loss_db = 0.0

    notes = []
    if total_loss_db > 3:
        notes.append(f"CRITICAL: {total_loss_db:.1f} dB loss — consider lower-loss laminate")
    elif total_loss_db > 1:
        notes.append(f"Significant dielectric loss ({total_loss_db:.1f} dB) — verify link budget")
    if loss_tangent > 0.02:
        notes.append(f"High loss tangent ({loss_tangent}) — FR4 typical; use Rogers/Megtron for >5 GHz")

    return {
        "dielectric_loss_db_per_inch": round(loss_db_per_inch, 4),
        "dielectric_loss_db_per_m": round(loss_db_per_m, 3),
        "total_loss_db": round(total_loss_db, 3),
        "frequency_mhz": frequency_mhz,
        "trace_length_mm": trace_length_mm,
        "material": {"dielectric_constant": er, "loss_tangent": tan_d},
        "notes": notes,
    }


def calc_plane_resonance(plane_width_mm: float, plane_length_mm: float, dielectric_constant: float, dielectric_height_mm: float) -> dict[str, Any]:
    """Calculate PCB power/ground plane cavity resonance frequencies.

    Cavity model: f_mn = c / (2 * sqrt(er)) * sqrt((m/L)^2 + (n/W)^2)
    """
    er = dielectric_constant
    L = plane_length_mm / 1000  # meters
    W = plane_width_mm / 1000

    resonances: list[dict[str, Any]] = []
    for m in range(0, 4):
        for n in range(0, 4):
            if m == 0 and n == 0:
                continue
            f = (C0 / (2 * math.sqrt(er))) * math.sqrt((m / L) ** 2 + (n / W) ** 2)
            f_mhz = f / 1e6
            if f_mhz < 10000:  # up to 10 GHz
                resonances.append({
                    "mode": f"TM{m}{n}",
                    "frequency_mhz": round(f_mhz, 1),
                    "wavelength_mm": round(C0 / f * 1000, 1),
                })

    resonances.sort(key=lambda r: r["frequency_mhz"])

    # Mitigation suggestions
    notes = []
    if resonances:
        f1 = resonances[0]["frequency_mhz"]
        # Via stitching: spacing < lambda/20 at highest frequency of concern
        max_via_spacing = resonances[0]["wavelength_mm"] / 20
        notes.append(f"First resonance at {f1:.0f} MHz (mode {resonances[0]['mode']})")
        notes.append(f"Place decoupling vias at < {max_via_spacing:.1f} mm spacing to suppress")
        if f1 < 500:
            notes.append("WARNING: Low-frequency resonance — add distributed decoupling capacitors")

    return {
        "resonances": resonances[:10],
        "first_resonance_mhz": resonances[0]["frequency_mhz"] if resonances else None,
        "plane_dimensions_mm": {"width": plane_width_mm, "length": plane_length_mm},
        "dielectric_constant": er,
        "dielectric_height_mm": dielectric_height_mm,
        "notes": notes,
    }


def calc_via_stitching_requirements(max_frequency_mhz: float, dielectric_constant: float) -> dict[str, Any]:
    """Calculate required via stitching density and spacing for EMI containment.

    Rule: via spacing < lambda/20 at max frequency to prevent cavity resonance leakage.
    """
    f = max_frequency_mhz * 1e6
    wavelength = C0 / (f * math.sqrt(dielectric_constant))
    wavelength_mm = wavelength * 1000

    max_spacing_mm = wavelength_mm / 20  # lambda/20 rule
    vias_per_cm = 10 / max_spacing_mm  # along one edge
    vias_per_cm2 = vias_per_cm ** 2  # area density

    notes = []
    if max_spacing_mm < 1.0:
        notes.append(f"Very tight spacing ({max_spacing_mm:.2f} mm) — may require HDI process")
    elif max_spacing_mm < 2.5:
        notes.append(f"Moderate spacing ({max_spacing_mm:.2f} mm) — standard PCB feasible")
    else:
        notes.append(f"Relaxed spacing ({max_spacing_mm:.1f} mm) — easy to implement")

    # Also calculate lambda/10 for critical areas
    critical_spacing = wavelength_mm / 10

    return {
        "max_via_spacing_mm": round(max_spacing_mm, 2),
        "critical_area_spacing_mm": round(critical_spacing, 2),
        "vias_per_cm_edge": round(vias_per_cm, 1),
        "vias_per_cm2_area": round(vias_per_cm2, 1),
        "wavelength_mm": round(wavelength_mm, 1),
        "frequency_mhz": max_frequency_mhz,
        "dielectric_constant": dielectric_constant,
        "notes": notes,
    }


# Reference data
STACKUP_TEMPLATES = [
    {"name": "2-layer FR4", "layers": ["Signal/GND", "Signal/Power"], "thickness_mm": 1.6, "typical_z0": "50-60 ohms microstrip"},
    {"name": "4-layer standard", "layers": ["Signal", "GND", "Power", "Signal"], "thickness_mm": 1.6, "typical_z0": "50 ohms microstrip, 40-45 ohms stripline", "notes": "Good for most designs, solid ground reference"},
    {"name": "6-layer high-speed", "layers": ["Signal", "GND", "Signal", "Signal", "Power", "Signal"], "thickness_mm": 1.6, "typical_z0": "50 ohms single-ended, 90-100 ohms differential", "notes": "USB 2.0/3.0, HDMI, Ethernet"},
    {"name": "8-layer DDR4", "layers": ["Signal", "GND", "Signal", "GND", "Power", "Signal", "GND", "Signal"], "thickness_mm": 1.6, "typical_z0": "40 ohms DDR4", "notes": "Optimized for DDR4 memory interfaces"},
]
MATERIAL_PROPERTIES = [
    {"name": "FR4 (standard)", "er": 4.3, "loss_tangent": 0.02, "tg_c": 130, "notes": "General purpose, <3 GHz"},
    {"name": "High-Tg FR4", "er": 4.2, "loss_tangent": 0.018, "tg_c": 170, "notes": "Lead-free assembly compatible"},
    {"name": "Rogers RO4003C", "er": 3.55, "loss_tangent": 0.0027, "tg_c": 280, "notes": "RF/microwave, <10 GHz"},
    {"name": "Rogers RO4350B", "er": 3.48, "loss_tangent": 0.0037, "tg_c": 280, "notes": "RF/microwave, good thermal"},
    {"name": "Isola I-Speed", "er": 3.6, "loss_tangent": 0.007, "tg_c": 200, "notes": "High-speed digital, >10 Gbps"},
    {"name": "Megtron 6", "er": 3.4, "loss_tangent": 0.002, "tg_c": 185, "notes": "Very low loss, 25+ Gbps"},
    {"name": "Polyimide (Flex)", "er": 3.4, "loss_tangent": 0.002, "tg_c": 250, "notes": "Flexible circuits"},
]


# =============================================================================
# Helper to safely serialize results
# =============================================================================

def _serialize(obj: Any) -> Any:
    """Convert dataclass/object to JSON-safe dict."""
    if hasattr(obj, '__dataclass_fields__'):
        return asdict(obj)
    elif hasattr(obj, 'to_dict'):
        return obj.to_dict()
    elif isinstance(obj, dict):
        return obj
    elif isinstance(obj, (list, tuple)):
        return [_serialize(i) for i in obj]
    elif isinstance(obj, Enum):
        return obj.value
    return str(obj)


def _result(data: Any, success: bool = True) -> Any:
    """Wrap result in standard format."""
    if success:
        if isinstance(data, dict):
            data["success"] = True
        return data
    return {"success": False, "error": str(data)}


# =============================================================================
# Tool definitions
# =============================================================================

def _make_tool(name: str, desc: str, props: dict[str, Any], required: list[str] | None = None) -> Tool:
    """Helper to create Tool with schema."""
    schema = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return Tool(name=name, description=desc, inputSchema=schema)


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all PCB analysis tools."""
    return [
        # =====================================================================
        # FILE PARSING (6 tools)
        # =====================================================================
        _make_tool("pcb_parse_layout", "Parse a PCB layout file (KiCad, ODB++, Gerber, Altium, IPC-2581). Returns session_id for subsequent queries.", {
            "file_path": {"type": "string", "description": "Path to PCB file"},
            "format": {"type": "string", "description": "Force format: kicad, odb, gerber, altium, ipc2581"},
        }, ["file_path"]),
        _make_tool("pcb_get_stackup", "Get layer stackup from a parsed design.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
        }, ["session_id"]),
        _make_tool("pcb_get_components", "Get component list from a parsed design.", {
            "session_id": {"type": "string", "description": "Session ID"},
            "filter": {"type": "string", "description": "Optional ref des pattern to filter (e.g. 'U*' for ICs)"},
        }, ["session_id"]),
        _make_tool("pcb_get_nets", "Get net list from a parsed design.", {
            "session_id": {"type": "string", "description": "Session ID"},
            "filter": {"type": "string", "description": "Optional net name pattern"},
        }, ["session_id"]),
        _make_tool("pcb_get_vias", "Get via list from a parsed design.", {
            "session_id": {"type": "string", "description": "Session ID"},
        }, ["session_id"]),
        _make_tool("pcb_get_traces", "Get trace summary from a parsed design.", {
            "session_id": {"type": "string", "description": "Session ID"},
            "layer": {"type": "string", "description": "Optional layer filter"},
        }, ["session_id"]),
        _make_tool("pcb_get_drill_table", "Get drill table: sizes, counts, plating types, aspect ratios.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
        }, ["session_id"]),
        _make_tool("pcb_get_board_outline", "Get board outline: dimensions, area, vertices, cutouts.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
        }, ["session_id"]),
        _make_tool("pcb_get_design_rules", "Get extracted DRC constraints: min trace, min space, min drill, min annular ring.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
        }, ["session_id"]),
        _make_tool("pcb_get_copper_pours", "Get copper pour/zone data: areas, nets, clearances per layer.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
        }, ["session_id"]),
        _make_tool("pcb_get_manufacturing_notes", "Get fab notes, material specs, and manufacturing info.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
        }, ["session_id"]),

        # =====================================================================
        # IMPEDANCE CALCULATORS (4 tools — original)
        # =====================================================================
        _make_tool("pcb_calc_microstrip_impedance", "Calculate microstrip trace impedance using IPC-2141 formulas.", {
            "trace_width_mm": {"type": "number", "description": "Trace width in mm"},
            "dielectric_height_mm": {"type": "number", "description": "Height to reference plane in mm"},
            "trace_thickness_mm": {"type": "number", "description": "Copper thickness in mm (1oz = 0.035mm)"},
            "dielectric_constant": {"type": "number", "description": "Dielectric constant Er (FR4 ~ 4.3)"},
        }, ["trace_width_mm", "dielectric_height_mm", "trace_thickness_mm", "dielectric_constant"]),
        _make_tool("pcb_calc_stripline_impedance", "Calculate stripline (buried trace between ground planes) impedance.", {
            "trace_width_mm": {"type": "number"}, "dielectric_height_mm": {"type": "number"},
            "trace_thickness_mm": {"type": "number"}, "dielectric_constant": {"type": "number"},
        }, ["trace_width_mm", "dielectric_height_mm", "trace_thickness_mm", "dielectric_constant"]),
        _make_tool("pcb_calc_differential_impedance", "Calculate differential pair impedance for USB, HDMI, Ethernet, etc.", {
            "trace_width_mm": {"type": "number"}, "trace_spacing_mm": {"type": "number"},
            "dielectric_height_mm": {"type": "number"}, "trace_thickness_mm": {"type": "number"},
            "dielectric_constant": {"type": "number"},
            "trace_type": {"type": "string", "enum": ["microstrip", "stripline"]},
        }, ["trace_width_mm", "trace_spacing_mm", "dielectric_height_mm", "trace_thickness_mm", "dielectric_constant"]),
        _make_tool("pcb_calc_trace_width", "Calculate minimum trace width for current capacity (IPC-2221).", {
            "current_amps": {"type": "number"}, "temp_rise_c": {"type": "number"},
            "copper_thickness_oz": {"type": "number"},
            "layer_type": {"type": "string", "enum": ["external", "internal"]},
        }, ["current_amps", "temp_rise_c", "copper_thickness_oz"]),

        # =====================================================================
        # ADVANCED RF CALCULATORS (5 tools)
        # =====================================================================
        _make_tool("pcb_calc_cpw_impedance", "Calculate coplanar waveguide (CPW/GCPW) impedance using conformal mapping. Supports grounded and ungrounded CPW.", {
            "trace_width_mm": {"type": "number", "description": "Center conductor width"},
            "gap_mm": {"type": "number", "description": "Gap between conductor and coplanar ground"},
            "dielectric_height_mm": {"type": "number", "description": "Height to ground plane below"},
            "trace_thickness_mm": {"type": "number", "description": "Copper thickness (1oz = 0.035mm)"},
            "dielectric_constant": {"type": "number"},
            "has_ground_plane": {"type": "boolean", "description": "True for grounded CPW (default), false for ungrounded"},
        }, ["trace_width_mm", "gap_mm", "dielectric_height_mm", "trace_thickness_mm", "dielectric_constant"]),
        _make_tool("pcb_calc_skin_effect", "Calculate skin depth, AC resistance factor, and conductor loss including Hammerstad surface roughness correction.", {
            "frequency_mhz": {"type": "number"},
            "copper_thickness_oz": {"type": "number", "description": "Copper weight (default 1.0 oz)"},
            "surface_roughness_um": {"type": "number", "description": "RMS surface roughness in microns (standard: 0.5, HVLP: 0.3, RTF: 1.5)"},
        }, ["frequency_mhz"]),
        _make_tool("pcb_calc_dielectric_loss", "Calculate dielectric loss (dB/inch, total dB) for a trace at frequency. Accounts for material loss tangent.", {
            "frequency_mhz": {"type": "number"},
            "dielectric_constant": {"type": "number"},
            "loss_tangent": {"type": "number", "description": "Material Df (FR4: 0.02, Megtron6: 0.002, Rogers 4350B: 0.0037)"},
            "trace_length_mm": {"type": "number"},
        }, ["frequency_mhz", "dielectric_constant", "loss_tangent", "trace_length_mm"]),
        _make_tool("pcb_calc_plane_resonance", "Calculate power/ground plane cavity resonance frequencies. Identifies modes that can amplify noise and cause EMI.", {
            "plane_width_mm": {"type": "number"}, "plane_length_mm": {"type": "number"},
            "dielectric_constant": {"type": "number"},
            "dielectric_height_mm": {"type": "number", "description": "Dielectric thickness between planes"},
        }, ["plane_width_mm", "plane_length_mm", "dielectric_constant", "dielectric_height_mm"]),
        _make_tool("pcb_calc_via_stitching", "Calculate required via stitching density and spacing for EMI containment at a given frequency. Uses lambda/20 rule.", {
            "max_frequency_mhz": {"type": "number", "description": "Highest frequency of concern"},
            "dielectric_constant": {"type": "number"},
        }, ["max_frequency_mhz", "dielectric_constant"]),

        # =====================================================================
        # S-PARAMETER / MODE CONVERSION (3 tools — Issues #8 & #12)
        # =====================================================================
        _make_tool("pcb_calc_insertion_loss", "Calculate frequency-swept insertion loss (S21) and return loss (S11) for a PCB trace. Models conductor loss (skin effect + Hammerstad roughness), dielectric loss, and mismatch loss.", {
            "trace_length_mm": {"type": "number", "description": "Trace length in mm"},
            "trace_width_mm": {"type": "number", "description": "Trace width in mm"},
            "dielectric_height_mm": {"type": "number", "description": "Height above reference plane in mm"},
            "dielectric_constant": {"type": "number", "description": "Substrate Er (FR4 ~ 4.3)"},
            "loss_tangent": {"type": "number", "description": "Material Df (FR4: 0.02, Rogers 4350B: 0.0037)"},
            "copper_thickness_oz": {"type": "number", "description": "Copper weight in oz (default 1.0)"},
            "surface_roughness_um": {"type": "number", "description": "RMS roughness in um (standard: 0.5, HVLP: 0.3, RTF: 1.5)"},
            "freq_start_mhz": {"type": "number", "description": "Sweep start frequency in MHz (default 10)"},
            "freq_stop_mhz": {"type": "number", "description": "Sweep stop frequency in MHz (default 10000)"},
            "num_points": {"type": "integer", "description": "Number of sweep points (default 50)"},
        }, ["trace_length_mm", "trace_width_mm", "dielectric_height_mm", "dielectric_constant", "loss_tangent"]),
        _make_tool("pcb_calc_return_loss", "Calculate return loss (S11), mismatch loss, and VSWR from impedance mismatch.", {
            "impedance_ohm": {"type": "number", "description": "Actual trace/load impedance in ohms"},
            "target_impedance_ohm": {"type": "number", "description": "Target (reference) impedance in ohms"},
            "frequency_mhz": {"type": "number", "description": "Frequency of interest in MHz"},
        }, ["impedance_ohm", "target_impedance_ohm", "frequency_mhz"]),
        _make_tool("pcb_analyze_mode_conversion", "Analyze differential pair mode conversion: even/odd mode impedances, SCD21 from length asymmetry, common-mode current estimate, and EMI impact.", {
            "trace_width_mm": {"type": "number", "description": "Width of each trace in mm"},
            "trace_spacing_mm": {"type": "number", "description": "Edge-to-edge spacing in mm"},
            "dielectric_height_mm": {"type": "number", "description": "Height above reference plane in mm"},
            "dielectric_constant": {"type": "number", "description": "Substrate Er"},
            "length_asymmetry_mm": {"type": "number", "description": "Length mismatch between P and N traces in mm"},
            "data_rate_gbps": {"type": "number", "description": "Signaling rate in Gb/s"},
            "trace_type": {"type": "string", "enum": ["microstrip", "stripline"], "description": "Trace type (default microstrip)"},
        }, ["trace_width_mm", "trace_spacing_mm", "dielectric_height_mm", "dielectric_constant", "length_asymmetry_mm", "data_rate_gbps"]),

        # =====================================================================
        # SIGNAL INTEGRITY (5 tools)
        # =====================================================================
        _make_tool("pcb_analyze_timing", "Analyze timing margins for high-speed signals.", {
            "trace_length_mm": {"type": "number"}, "effective_er": {"type": "number"},
            "data_rate_gbps": {"type": "number"}, "rise_time_ps": {"type": "number"},
            "setup_time_ps": {"type": "number"}, "hold_time_ps": {"type": "number"},
        }, ["trace_length_mm", "effective_er", "data_rate_gbps", "rise_time_ps", "setup_time_ps", "hold_time_ps"]),
        _make_tool("pcb_analyze_crosstalk", "Analyze crosstalk between parallel traces (NEXT and FEXT).", {
            "trace_spacing_mm": {"type": "number"}, "trace_width_mm": {"type": "number"},
            "dielectric_height_mm": {"type": "number"}, "coupling_length_mm": {"type": "number"},
            "rise_time_ps": {"type": "number"},
        }, ["trace_spacing_mm", "trace_width_mm", "dielectric_height_mm", "coupling_length_mm", "rise_time_ps"]),
        _make_tool("pcb_analyze_via", "Analyze via electrical characteristics.", {
            "via_diameter_mm": {"type": "number"}, "via_length_mm": {"type": "number"},
            "pad_diameter_mm": {"type": "number"}, "antipad_diameter_mm": {"type": "number"},
            "dielectric_constant": {"type": "number"}, "frequency_ghz": {"type": "number"},
        }, ["via_diameter_mm", "via_length_mm", "pad_diameter_mm", "antipad_diameter_mm", "dielectric_constant", "frequency_ghz"]),
        _make_tool("pcb_analyze_differential_pair", "Analyze differential pair routing quality.", {
            "trace_width_mm": {"type": "number"}, "trace_spacing_mm": {"type": "number"},
            "dielectric_height_mm": {"type": "number"}, "dielectric_constant": {"type": "number"},
            "trace_thickness_mm": {"type": "number", "description": "Copper thickness in mm (1oz = 0.035mm, default 0.035)"},
            "data_rate_gbps": {"type": "number"}, "target_impedance_ohm": {"type": "number", "description": "Target diff impedance (e.g. 90, 100)"},
        }, ["trace_width_mm", "trace_spacing_mm", "dielectric_height_mm", "dielectric_constant", "data_rate_gbps", "target_impedance_ohm"]),
        _make_tool("pcb_analyze_length_matching", "Analyze trace length matching for a group of signals.", {
            "trace_lengths_mm": {"type": "object", "description": "Dict of net_name: length_mm"},
            "max_skew_ps": {"type": "number", "description": "Maximum allowed skew in ps"},
            "effective_er": {"type": "number", "description": "Effective dielectric constant"},
        }, ["trace_lengths_mm", "max_skew_ps", "effective_er"]),
        _make_tool("pcb_calc_eye_diagram", "Calculate statistical eye diagram for a high-speed serial channel. Models lossy transmission line (conductor + dielectric loss) and estimates eye opening, jitter, and pass/fail vs standard thresholds.", {
            "data_rate_gbps": {"type": "number", "description": "Data rate in Gb/s (NRZ)"},
            "trace_length_mm": {"type": "number", "description": "Trace length in mm"},
            "dielectric_constant": {"type": "number", "description": "Substrate Er (FR4 ~ 4.3)"},
            "loss_tangent": {"type": "number", "description": "Dielectric Df (FR4 ~ 0.02, Megtron6 ~ 0.002)"},
            "trace_width_mm": {"type": "number", "description": "Trace width in mm"},
            "dielectric_height_mm": {"type": "number", "description": "Height to reference plane in mm"},
            "copper_thickness_oz": {"type": "number", "description": "Copper weight in oz (default 1.0)"},
            "rise_time_ps": {"type": "number", "description": "Signal rise time 20-80% in ps (default 50)"},
            "v_swing_mv": {"type": "number", "description": "Voltage swing in mV (default 800)"},
            "standard": {"type": "string", "description": "Protocol for thresholds: pcie3, pcie4, pcie5, usb3, sata3, generic_low, generic_high"},
        }, ["data_rate_gbps", "trace_length_mm", "dielectric_constant", "loss_tangent", "trace_width_mm", "dielectric_height_mm"]),

        # =====================================================================
        # EMC (10 tools)
        # =====================================================================
        _make_tool("pcb_analyze_current_loop", "Estimate radiated emissions from a current loop for EMC.", {
            "loop_area_mm2": {"type": "number"}, "current_ma": {"type": "number"}, "frequency_mhz": {"type": "number"},
        }, ["loop_area_mm2", "current_ma", "frequency_mhz"]),
        _make_tool("pcb_estimate_bandwidth", "Estimate signal bandwidth and EMC concerns from rise time.", {
            "rise_time_ps": {"type": "number"},
        }, ["rise_time_ps"]),
        _make_tool("pcb_analyze_shielding", "Analyze shielding effectiveness of an enclosure.", {
            "material": {"type": "string", "description": "Shield material (aluminum, steel, copper, mu_metal)"},
            "thickness_mm": {"type": "number"}, "frequency_mhz": {"type": "number"},
            "aperture_mm": {"type": "number", "description": "Largest aperture dimension in mm"},
        }, ["material", "thickness_mm", "frequency_mhz"]),
        _make_tool("pcb_analyze_esd", "Analyze ESD protection for a circuit.", {
            "interface_type": {"type": "string", "description": "Interface: usb, hdmi, ethernet, gpio, antenna"},
            "has_tvs": {"type": "boolean", "description": "Whether TVS diode is present"},
            "trace_length_mm": {"type": "number", "description": "Trace length from connector to IC"},
            "ground_vias_near_connector": {"type": "integer", "description": "Number of ground vias near connector"},
        }, ["interface_type"]),
        _make_tool("pcb_analyze_grounding", "Analyze grounding topology.", {
            "topology": {"type": "string", "description": "Grounding: single_point, multi_point, hybrid"},
            "max_frequency_mhz": {"type": "number"}, "board_size_mm": {"type": "number"},
            "has_mixed_signal": {"type": "boolean"},
        }, ["topology", "max_frequency_mhz"]),
        _make_tool("pcb_predict_compliance", "Predict EMC compliance for given design parameters.", {
            "clock_frequency_mhz": {"type": "number"}, "rise_time_ps": {"type": "number"},
            "max_loop_area_mm2": {"type": "number"}, "has_shielding": {"type": "boolean"},
            "standard": {"type": "string", "description": "FCC_B, CISPR32_B, CE"},
        }, ["clock_frequency_mhz", "rise_time_ps"]),

        _make_tool("pcb_analyze_return_current_density", "Estimate return current density distribution on a reference plane beneath a signal trace. Shows how current concentrates under the trace at high frequencies and spreads at low frequencies. Identifies crowding near plane gaps/edges.", {
            "trace_x_start": {"type": "number", "description": "Trace start X (mm)"},
            "trace_y_start": {"type": "number", "description": "Trace start Y (mm)"},
            "trace_x_end": {"type": "number", "description": "Trace end X (mm)"},
            "trace_y_end": {"type": "number", "description": "Trace end Y (mm)"},
            "plane_width_mm": {"type": "number", "description": "Reference plane width (mm)"},
            "plane_height_mm": {"type": "number", "description": "Reference plane height (mm)"},
            "frequency_mhz": {"type": "number", "description": "Signal frequency (MHz)"},
            "plane_gaps": {"type": "array", "items": {"type": "object"}, "description": "Optional gap objects with x_start_mm, y_start_mm, x_end_mm, y_end_mm, width_mm"},
        }, ["trace_x_start", "trace_y_start", "trace_x_end", "trace_y_end", "plane_width_mm", "plane_height_mm", "frequency_mhz"]),

        _make_tool("pcb_optimize_ground_stitching", "Optimize ground via stitching pattern for a reference plane. Calculates spacing from lambda/20 rule and suggests via locations accounting for existing vias and plane gaps.", {
            "plane_width_mm": {"type": "number", "description": "Reference plane width (mm)"},
            "plane_height_mm": {"type": "number", "description": "Reference plane height (mm)"},
            "max_frequency_mhz": {"type": "number", "description": "Maximum operating frequency (MHz)"},
            "dielectric_constant": {"type": "number", "description": "Substrate dielectric constant (er)"},
            "existing_vias": {"type": "array", "items": {"type": "object"}, "description": "Existing via locations [{x_mm, y_mm}, ...]"},
            "plane_gaps": {"type": "array", "items": {"type": "object"}, "description": "Plane gap definitions [{x_start_mm, y_start_mm, x_end_mm, y_end_mm, width_mm}, ...]"},
        }, ["plane_width_mm", "plane_height_mm", "max_frequency_mhz", "dielectric_constant"]),

        # =====================================================================
        # HIGH-SPEED DIGITAL (6 tools)
        # =====================================================================
        _make_tool("pcb_analyze_ddr", "Analyze DDR memory interface routing.", {
            "ddr_standard": {"type": "string", "enum": ["DDR3", "DDR4", "DDR5", "LPDDR4", "LPDDR5"]},
            "data_rate_mtps": {"type": "number", "description": "Data rate in MT/s"},
            "trace_length_mm": {"type": "number"}, "trace_impedance_ohm": {"type": "number"},
            "clock_to_data_skew_ps": {"type": "number"},
        }, ["ddr_standard", "data_rate_mtps"]),
        _make_tool("pcb_analyze_pcie", "Analyze PCIe lane routing.", {
            "pcie_gen": {"type": "string", "enum": ["3.0", "4.0", "5.0", "6.0"]},
            "lane_count": {"type": "integer"}, "trace_length_mm": {"type": "number"},
            "differential_impedance_ohm": {"type": "number"},
            "insertion_loss_db": {"type": "number"},
        }, ["pcie_gen"]),
        _make_tool("pcb_calc_pcie_link_budget", "Calculate PCIe link insertion loss budget and equalizer margin. Sums trace, connector, via, and package losses then compares against the PCIe generation spec limit.", {
            "pcie_gen": {"type": "integer", "description": "PCIe generation (1-6)"},
            "trace_length_mm": {"type": "number", "description": "Total PCB trace length (mm)"},
            "dielectric_constant": {"type": "number", "description": "Laminate dielectric constant (default 4.0)"},
            "loss_tangent": {"type": "number", "description": "Dielectric loss tangent (default 0.02)"},
            "copper_thickness_oz": {"type": "number", "description": "Copper weight in oz (default 0.5)"},
            "connector_loss_db": {"type": "number", "description": "Total connector insertion loss (dB)"},
            "via_loss_db": {"type": "number", "description": "Total via transition insertion loss (dB)"},
            "package_loss_db": {"type": "number", "description": "IC package trace/ball insertion loss (dB)"},
        }, ["pcie_gen", "trace_length_mm"]),
        _make_tool("pcb_validate_pcie_lanes", "Validate PCIe lane-to-lane skew against generation-specific spec limits. Calculates per-lane propagation delay and max skew.", {
            "lane_lengths_mm": {"type": "object", "description": "Dict of lane_name: length_mm (e.g. {\"TX0\": 80.5, \"TX1\": 81.2})"},
            "dielectric_constant": {"type": "number", "description": "Dielectric constant for delay calculation (default 4.0)"},
            "pcie_gen": {"type": "integer", "description": "PCIe generation (1-6, default 4)"},
        }, ["lane_lengths_mm"]),
        _make_tool("pcb_analyze_usb", "Analyze USB routing.", {
            "usb_version": {"type": "string", "enum": ["2.0", "3.0", "3.1", "3.2", "4.0"]},
            "trace_length_mm": {"type": "number"}, "differential_impedance_ohm": {"type": "number"},
        }, ["usb_version"]),
        _make_tool("pcb_analyze_ethernet", "Analyze Ethernet PHY routing.", {
            "speed": {"type": "string", "enum": ["100M", "1G", "2.5G", "5G", "10G"]},
            "trace_length_mm": {"type": "number"}, "pair_skew_ps": {"type": "number"},
        }, ["speed"]),
        _make_tool("pcb_validate_ddr_topology", "Auto-detect and validate DDR memory interface topology from classified nets. Checks byte-lane grouping, DQ-DQS skew, inter-byte-lane skew, addr/cmd-to-clock skew, and fly-by topology against JEDEC limits.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
            "ddr_standard": {"type": "string", "enum": ["DDR3", "DDR4", "DDR5", "LPDDR4", "LPDDR5"], "description": "DDR standard (default DDR4)"},
        }, ["session_id"]),
        _make_tool("pcb_analyze_ddr_timing_budget", "Detailed per-lane DDR timing margin analysis against JEDEC budget. Calculates setup/hold margins for each DQ bit relative to DQS.", {
            "ddr_standard": {"type": "string", "enum": ["DDR3", "DDR4", "DDR5", "LPDDR4", "LPDDR5"]},
            "data_rate_mtps": {"type": "number", "description": "Data rate in MT/s (e.g. 3200)"},
            "byte_lanes": {"type": "array", "items": {"type": "object", "properties": {
                "lane": {"type": "integer", "description": "Byte lane number"},
                "dqs_length_mm": {"type": "number", "description": "DQS strobe trace length in mm"},
                "dq_lengths_mm": {"type": "array", "items": {"type": "number"}, "description": "DQ bit trace lengths in mm"},
                "dqs_n_length_mm": {"type": "number", "description": "DQS_N trace length in mm (optional)"},
                "dm_length_mm": {"type": "number", "description": "DM/DBI trace length in mm (optional)"},
            }, "required": ["lane", "dqs_length_mm", "dq_lengths_mm"]}, "description": "List of byte lane data"},
            "dielectric_constant": {"type": "number", "description": "Substrate Er (default 4.3)"},
        }, ["ddr_standard", "data_rate_mtps", "byte_lanes"]),

        # =====================================================================
        # POWER INTEGRITY (4 tools)
        # =====================================================================
        _make_tool("pcb_analyze_pdn", "Analyze power distribution network impedance.", {
            "target_impedance_mohm": {"type": "number", "description": "Target PDN impedance in milliohms"},
            "supply_voltage_v": {"type": "number"}, "max_current_a": {"type": "number"},
            "ripple_percent": {"type": "number", "description": "Allowed voltage ripple %"},
        }, ["supply_voltage_v", "max_current_a"]),
        _make_tool("pcb_calc_pdn_impedance", "Frequency-swept PDN impedance profiling. Models VRM, bulk caps, MLCC decaps, and plane capacitance as parallel RLC networks. Sweeps from freq_start to freq_stop and flags anti-resonance peaks exceeding the target impedance Z_target = V * ripple% / I_max.", {
            "supply_voltage_v": {"type": "number", "description": "Supply rail voltage (V)"},
            "max_current_a": {"type": "number", "description": "Maximum transient load current (A)"},
            "ripple_percent": {"type": "number", "description": "Allowed voltage ripple (%)"},
            "capacitors": {"type": "array", "items": {"type": "object", "properties": {"capacitance_uf": {"type": "number"}, "esr_mohm": {"type": "number"}, "esl_nh": {"type": "number"}, "quantity": {"type": "integer"}}}, "description": "List of capacitor specs: [{capacitance_uf, esr_mohm, esl_nh, quantity}]"},
            "vrm_bandwidth_khz": {"type": "number", "description": "VRM control-loop bandwidth (kHz, default 50)"},
            "vrm_r_out_mohm": {"type": "number", "description": "VRM closed-loop output resistance (mohm, default 1)"},
            "plane_area_mm2": {"type": "number", "description": "Power-ground plane pair area (mm^2)"},
            "dielectric_height_mm": {"type": "number", "description": "Spacing between power and ground planes (mm)"},
            "dielectric_constant": {"type": "number", "description": "Relative permittivity of inter-plane dielectric"},
            "frequency_start_hz": {"type": "number", "description": "Sweep start frequency (Hz, default 1)"},
            "frequency_stop_hz": {"type": "number", "description": "Sweep stop frequency (Hz, default 1e9)"},
            "num_points": {"type": "integer", "description": "Number of logarithmic sweep points (default 500)"},
        }, ["supply_voltage_v", "max_current_a", "ripple_percent", "capacitors"]),
        _make_tool("pcb_analyze_decoupling", "Analyze decoupling capacitor placement.", {
            "ic_power_pins": {"type": "integer", "description": "Number of power pins on IC"},
            "max_frequency_mhz": {"type": "number"}, "target_impedance_mohm": {"type": "number"},
            "cap_values_uf": {"type": "array", "items": {"type": "number"}, "description": "Capacitor values available"},
        }, ["ic_power_pins", "max_frequency_mhz"]),
        _make_tool("pcb_analyze_vrm", "Analyze VRM placement and routing.", {
            "output_voltage_v": {"type": "number"}, "output_current_a": {"type": "number"},
            "input_voltage_v": {"type": "number", "description": "VRM input voltage (default: 12V)"},
            "switching_frequency_khz": {"type": "number"},
            "distance_to_load_mm": {"type": "number"},
        }, ["output_voltage_v", "output_current_a"]),

        # =====================================================================
        # DFM (4 tools)
        # =====================================================================
        _make_tool("pcb_analyze_solder_paste", "Analyze solder paste stencil design.", {
            "pad_width_mm": {"type": "number"}, "pad_length_mm": {"type": "number"},
            "pitch_mm": {"type": "number"}, "stencil_thickness_mm": {"type": "number"},
        }, ["pad_width_mm", "pad_length_mm", "pitch_mm"]),
        _make_tool("pcb_analyze_placement", "Analyze component placement for manufacturability.", {
            "component_pitch_mm": {"type": "number"}, "tallest_component_mm": {"type": "number"},
            "has_bottom_components": {"type": "boolean"}, "board_thickness_mm": {"type": "number"},
        }, ["component_pitch_mm"]),
        _make_tool("pcb_analyze_assembly", "Analyze board assembly process considerations.", {
            "component_count": {"type": "integer"}, "smd_count": {"type": "integer"},
            "through_hole_count": {"type": "integer"}, "bga_count": {"type": "integer"},
            "finest_pitch_mm": {"type": "number"},
        }, ["component_count"]),
        _make_tool("pcb_analyze_tolerance", "Analyze manufacturing tolerance stackup.", {
            "nominal_mm": {"type": "number"}, "tolerances_mm": {"type": "array", "items": {"type": "number"}},
            "method": {"type": "string", "enum": ["worst_case", "rss", "monte_carlo"]},
        }, ["nominal_mm", "tolerances_mm"]),

        # =====================================================================
        # THERMAL (3 tools)
        # =====================================================================
        _make_tool("pcb_analyze_thermal", "Analyze thermal dissipation for a component.", {
            "power_watts": {"type": "number"}, "theta_ja_c_per_w": {"type": "number", "description": "Thermal resistance junction-to-ambient"},
            "ambient_temp_c": {"type": "number"}, "max_junction_temp_c": {"type": "number"},
        }, ["power_watts", "theta_ja_c_per_w"]),
        _make_tool("pcb_analyze_thermal_via", "Analyze thermal via array for heat dissipation.", {
            "via_count": {"type": "integer"}, "via_diameter_mm": {"type": "number"},
            "board_thickness_mm": {"type": "number"}, "copper_fill_percent": {"type": "number"},
            "power_watts": {"type": "number"},
        }, ["via_count", "via_diameter_mm", "power_watts"]),
        _make_tool("pcb_analyze_copper_spreading", "Analyze copper area heat spreading.", {
            "copper_area_mm2": {"type": "number"}, "copper_thickness_oz": {"type": "number"},
            "power_watts": {"type": "number"}, "ambient_temp_c": {"type": "number"},
        }, ["copper_area_mm2", "copper_thickness_oz", "power_watts"]),

        # =====================================================================
        # ANTENNA/EMI (4 tools)
        # =====================================================================
        _make_tool("pcb_analyze_trace_antenna", "Check if a trace could act as unintentional antenna.", {
            "trace_length_mm": {"type": "number"}, "frequency_mhz": {"type": "number"},
            "dielectric_constant": {"type": "number"},
        }, ["trace_length_mm", "frequency_mhz"]),
        _make_tool("pcb_analyze_slot_antenna", "Analyze slot in ground plane as unintentional antenna.", {
            "slot_length_mm": {"type": "number"}, "slot_width_mm": {"type": "number"},
            "frequency_mhz": {"type": "number"},
        }, ["slot_length_mm", "frequency_mhz"]),
        _make_tool("pcb_analyze_common_mode", "Analyze common-mode noise on differential pairs.", {
            "differential_impedance_ohm": {"type": "number"},
            "common_mode_impedance_ohm": {"type": "number"},
            "cable_length_m": {"type": "number"}, "frequency_mhz": {"type": "number"},
        }, ["differential_impedance_ohm", "frequency_mhz"]),
        _make_tool("pcb_analyze_cable_coupling", "Analyze cable-to-cable coupling for EMI.", {
            "cable_spacing_mm": {"type": "number"}, "parallel_length_mm": {"type": "number"},
            "frequency_mhz": {"type": "number"}, "cable_type": {"type": "string", "description": "unshielded, shielded, twisted_pair"},
        }, ["cable_spacing_mm", "parallel_length_mm", "frequency_mhz"]),

        # =====================================================================
        # EMI / RETURN PATH (6 tools)
        # =====================================================================
        _make_tool("pcb_trace_return_path", "Trace ground return current path for a specific net. Shows return path segments, loop area, split crossings, and via transition quality.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
            "net_name": {"type": "string", "description": "Net name to trace return path for"},
        }, ["session_id", "net_name"]),
        _make_tool("pcb_analyze_return_paths", "Analyze return paths for all high-speed signal nets. Identifies split-plane crossings, inadequate return vias, and calculates effective loop areas.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
            "max_frequency_mhz": {"type": "number", "description": "Max signal frequency for analysis (0 = analyze all high-speed nets)"},
        }, ["session_id"]),
        _make_tool("pcb_find_split_crossings", "Find signals crossing ground plane splits/slots. Each crossing forces return current to detour, increasing loop area and EMI risk.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
        }, ["session_id"]),
        _make_tool("pcb_analyze_emi_risk", "Score EMI risk per net and identify top concerns. Combines return path quality, loop area, frequency content, and current to predict emissions.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
            "standard": {"type": "string", "description": "EMC standard: FCC_B, FCC_A, CISPR_B, CISPR_A"},
        }, ["session_id"]),
        _make_tool("pcb_predict_emissions", "Predict radiated emission spectrum vs regulatory limits. Calculates emission level at each harmonic and compares to FCC/CISPR limits.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
            "standard": {"type": "string", "description": "EMC standard for limit comparison (default: FCC_B)"},
            "test_distance_m": {"type": "number", "description": "Measurement distance in meters (default: 3)"},
        }, ["session_id"]),
        _make_tool("pcb_get_emi_hotspots", "Identify board regions with highest EMI risk. Clusters high-risk nets by location and returns spatial hot-spots.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
        }, ["session_id"]),

        # =====================================================================
        # CLASSIFICATION (3 tools)
        # =====================================================================
        _make_tool("pcb_classify_nets", "Classify all nets by function (power, ground, DDR, USB, PCIe, etc.) with confidence scores. Detects differential pairs automatically.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
        }, ["session_id"]),
        _make_tool("pcb_detect_interfaces", "Detect high-speed interfaces (DDR, PCIe, USB, Ethernet, LVDS, RF) with pin counts and associated nets.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
        }, ["session_id"]),
        _make_tool("pcb_classify_design", "Classify overall design type (rf, mixed_signal, high_speed_digital, power, simple_digital) with complexity score (1-10).", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
        }, ["session_id"]),

        # =====================================================================
        # REFERENCE DATA (2 tools — original)
        # =====================================================================
        _make_tool("pcb_get_stackup_templates", "Get common PCB stackup templates with typical impedances.", {}, None),
        _make_tool("pcb_get_material_properties", "Get dielectric properties for common PCB materials.", {}, None),

        # =====================================================================
        # 3D / STEP FILE (3 tools)
        # =====================================================================
        _make_tool("pcb_parse_step", "Parse a STEP (.step/.stp) file for 3D mechanical review. Extracts board outline, component bounding boxes, heights. Returns session_id.", {
            "file_path": {"type": "string", "description": "Path to STEP file (.step or .stp)"},
            "session_id": {"type": "string", "description": "Optional existing session to merge 3D data into"},
        }, ["file_path"]),
        _make_tool("pcb_get_3d_clearances", "Get component-to-component and component-to-board-edge 3D clearances from STEP data.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_step"},
        }, ["session_id"]),
        _make_tool("pcb_check_enclosure_fit", "Check if PCB assembly fits within an enclosure with required clearances.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_step"},
            "enclosure_width_mm": {"type": "number", "description": "Internal enclosure width in mm"},
            "enclosure_depth_mm": {"type": "number", "description": "Internal enclosure depth in mm"},
            "enclosure_height_mm": {"type": "number", "description": "Internal enclosure height in mm"},
            "clearance_mm": {"type": "number", "description": "Required clearance on all sides in mm (default 1.0)"},
        }, ["session_id", "enclosure_width_mm", "enclosure_depth_mm", "enclosure_height_mm"]),

        # =====================================================================
        # VISUALIZATION (4 tools)
        # =====================================================================
        _make_tool("pcb_render_board", "Render SVG board view with component placement, traces, vias. Supports layer filtering, net/component highlighting.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
            "layers": {"type": "array", "items": {"type": "string"}, "description": "Optional layer filter (e.g. ['F.Cu'])"},
            "highlight_nets": {"type": "array", "items": {"type": "string"}, "description": "Net names to highlight in red"},
            "highlight_components": {"type": "array", "items": {"type": "string"}, "description": "Component references to highlight"},
            "width_px": {"type": "integer", "description": "SVG width in pixels (default 800)", "default": 800},
        }, ["session_id"]),
        _make_tool("pcb_render_stackup", "Render SVG cross-section of the PCB layer stackup showing copper, dielectric, solder mask layers with thicknesses.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
        }, ["session_id"]),
        _make_tool("pcb_render_net", "Render SVG highlighting a specific net's traces and vias on the board.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
            "net_name": {"type": "string", "description": "Name of the net to highlight"},
        }, ["session_id", "net_name"]),
        _make_tool("pcb_annotate_board", "Render SVG board view with annotation overlays (arrows, text callouts, highlight regions, warning markers).", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
            "annotations": {"type": "array", "items": {"type": "object", "properties": {
                "type": {"type": "string", "enum": ["arrow", "text", "highlight", "warning"], "description": "Annotation type"},
                "x": {"type": "number", "description": "X position in mm (board coordinates)"},
                "y": {"type": "number", "description": "Y position in mm (board coordinates)"},
                "text": {"type": "string", "description": "Label text (for arrow, text, warning)"},
                "color": {"type": "string", "description": "CSS colour (default red)"},
                "shape": {"type": "string", "enum": ["rect", "circle"], "description": "Highlight shape (default rect)"},
                "width": {"type": "number", "description": "Highlight rect width in mm"},
                "height": {"type": "number", "description": "Highlight rect height in mm"},
                "radius": {"type": "number", "description": "Highlight circle radius in mm"},
                "severity": {"type": "string", "enum": ["warning", "error"], "description": "Warning marker severity"},
            }, "required": ["type", "x", "y"]}, "description": "List of annotation objects"},
        }, ["session_id", "annotations"]),

        # =====================================================================
        # EXPORT / RENDER TO FILE (3 tools)
        # =====================================================================
        _make_tool("pcb_export_render_png", "Export an SVG render (board, stackup, net, annotated) to a PNG image file. Requires cairosvg.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
            "render_type": {"type": "string", "enum": ["board", "stackup", "net", "annotated"], "description": "Type of render to export"},
            "output_path": {"type": "string", "description": "Output PNG file path. If omitted, writes to temp file."},
            "width_px": {"type": "integer", "description": "Output image width in pixels (default 1600)", "default": 1600},
            "net_name": {"type": "string", "description": "Net name (required when render_type='net')"},
            "highlight_nets": {"type": "array", "items": {"type": "string"}, "description": "Nets to highlight (for board render)"},
            "highlight_components": {"type": "array", "items": {"type": "string"}, "description": "Components to highlight (for board render)"},
            "annotations": {"type": "array", "items": {"type": "object"}, "description": "Annotation list (for annotated render)"},
        }, ["session_id", "render_type"]),
        _make_tool("pcb_export_all_renders", "Generate and export all standard renders (board, stackup, key nets, annotated findings) as PNG files to a directory. Returns mapping of label to file path.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
            "output_dir": {"type": "string", "description": "Directory to write PNG files"},
            "width_px": {"type": "integer", "description": "Output image width in pixels (default 1600)", "default": 1600},
        }, ["session_id", "output_dir"]),
        _make_tool("pcb_generate_docx_report", "Generate a professional DOCX design review report with embedded board renders, schematic images, and analysis findings. Requires python-docx and cairosvg.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout (must have run design review first)"},
            "output_path": {"type": "string", "description": "Output .docx file path. If omitted, writes to temp file."},
            "image_dir": {"type": "string", "description": "Directory containing pre-rendered PNG images (from pcb_export_all_renders). If omitted, renders are generated automatically."},
            "title": {"type": "string", "description": "Report title (default: 'PCB Design Review Report')"},
            "subtitle": {"type": "string", "description": "Report subtitle (e.g. project/board name)"},
        }, ["session_id"]),

        # =====================================================================
        # SCHEMATIC PDF (3 tools)
        # =====================================================================
        _make_tool("pcb_parse_schematic_pdf", "Parse a PDF schematic to extract component references, net labels, and page data. Uses text-layer extraction (requires pymupdf for full support). If session_id provided, attaches schematic data to existing layout session for cross-reference.", {
            "file_path": {"type": "string", "description": "Path to the schematic PDF file"},
            "session_id": {"type": "string", "description": "Optional session ID to attach schematic data to an existing layout session"},
        }, ["file_path"]),
        _make_tool("pcb_get_schematic_page", "Get extracted text and annotations for a specific schematic PDF page. Returns page text, detected components, and net labels. If pymupdf is installed, can also render the page as an image.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_schematic_pdf"},
            "page_number": {"type": "integer", "description": "1-based page number"},
            "render_image": {"type": "boolean", "description": "Render page to PNG image (requires pymupdf)"},
        }, ["session_id", "page_number"]),
        _make_tool("pcb_cross_reference_schematic", "Cross-reference schematic components/nets against layout. Finds missing components, extra components, value mismatches, and unrouted nets. Requires both schematic and layout data in the session.", {
            "session_id": {"type": "string", "description": "Session ID with both schematic and layout data loaded"},
        }, ["session_id"]),

        # =====================================================================
        # DESIGN REVIEW ORCHESTRATION (3 tools)
        # =====================================================================
        _make_tool("pcb_set_review_context", "Set design review context: requirements, standards, known issues, operating conditions. Call before pcb_run_design_review.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
            "design_intent": {"type": "string", "description": "Free-text description of the design purpose"},
            "target_standards": {"type": "array", "items": {"type": "string"}, "description": "Target EMC standards (e.g. FCC_B, CISPR_32, CE, automotive)"},
            "known_issues": {"type": "array", "items": {"type": "string"}, "description": "Known issues to investigate"},
            "impedance_targets": {"type": "object", "description": "Dict of net_pattern: impedance_ohm targets"},
            "thermal_limits": {"type": "object", "description": "Thermal constraints (e.g. {max_ambient_c: 40, max_junction_c: 125})"},
            "operating_conditions": {"type": "object", "description": "Operating conditions (e.g. {temp_min_c: -40, temp_max_c: 85, altitude_m: 3000})"},
        }, ["session_id"]),
        _make_tool("pcb_run_design_review", "Run full automated multi-domain design review. Classifies design, selects relevant analyzers, runs analysis, cross-correlates findings, and generates structured results.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
        }, ["session_id"]),
        _make_tool("pcb_generate_report", "Generate structured report from design review results. Must run pcb_run_design_review first.", {
            "session_id": {"type": "string", "description": "Session ID from pcb_parse_layout"},
            "format": {"type": "string", "enum": ["summary", "detailed", "json"], "description": "Report format: summary (pass/fail + top risks), detailed (all findings), json (raw structured data)"},
        }, ["session_id"]),

        # =====================================================================
        # RETURN CURRENT / GROUND STITCHING (2 tools)
        # =====================================================================
        _make_tool("pcb_analyze_return_current", "Calculate return current density profile on reference plane beneath a signal trace. Shows how current spreads laterally and what fraction is contained within N*h of the trace center.", {
            "trace_height_mm": {"type": "number", "description": "Height from signal trace to reference plane (mm)"},
            "signal_current_ma": {"type": "number", "description": "Signal current magnitude (mA). Default 100"},
            "analysis_width_mm": {"type": "number", "description": "Total width to analyze centered on trace (mm). Default 20"},
            "num_points": {"type": "integer", "description": "Number of sample points. Default 100"},
        }, ["trace_height_mm"]),
        _make_tool("pcb_analyze_ground_stitch", "Calculate optimal ground via stitching spacing from wavelength (lambda/N) and return current containment constraints.", {
            "max_frequency_hz": {"type": "number", "description": "Maximum signal frequency or harmonic to contain (Hz)"},
            "dielectric_constant": {"type": "number", "description": "Substrate Er. Default 4.3"},
            "trace_height_mm": {"type": "number", "description": "Height to reference plane (mm). Default 0.1"},
            "target_containment_percent": {"type": "number", "description": "Desired return current containment %. Default 90"},
            "lambda_fraction": {"type": "number", "description": "Wavelength fraction for spacing rule (e.g. 20 for lambda/20). Default 20"},
        }, ["max_frequency_hz"]),

        # =====================================================================
        # CLOCK / SMPS EMI ANALYSIS (2 tools)
        # =====================================================================
        _make_tool("pcb_analyze_clock_emi", "Calculate clock signal harmonic EMI envelope using trapezoidal waveform Fourier analysis. Predicts emission levels vs FCC/CISPR limits. Includes spread-spectrum clocking reduction.", {
            "clock_frequency_mhz": {"type": "number", "description": "Fundamental clock frequency (MHz)"},
            "rise_time_ns": {"type": "number", "description": "Signal rise time 10-90% (ns). Default 1.0"},
            "voltage_swing_v": {"type": "number", "description": "Peak voltage swing (V). Default 3.3"},
            "duty_cycle": {"type": "number", "description": "Duty cycle 0-1. Default 0.5"},
            "num_harmonics": {"type": "integer", "description": "Number of harmonics to compute. Default 20"},
            "ssc_enabled": {"type": "boolean", "description": "Spread-spectrum clocking active. Default false"},
            "ssc_deviation_percent": {"type": "number", "description": "SSC frequency deviation %. Default 0.5"},
            "trace_length_mm": {"type": "number", "description": "Clock trace length (mm). Default 50"},
            "limit_standard": {"type": "string", "enum": ["fcc_classb", "fcc_classa", "cispr32_classb", "cispr32_classa"], "description": "Emission limit standard. Default fcc_classb"},
        }, ["clock_frequency_mhz"]),
        _make_tool("pcb_analyze_smps_emi", "Calculate SMPS switching harmonic EMI from hot loop radiation. Models trapezoidal current waveform harmonics through magnetic dipole antenna model. Compares to emission limits.", {
            "switching_frequency_khz": {"type": "number", "description": "SMPS switching frequency (kHz)"},
            "duty_cycle": {"type": "number", "description": "Switch duty cycle 0-1 (0 = auto from Vin/Vout). Default 0.5"},
            "input_voltage_v": {"type": "number", "description": "Input supply voltage (V). Default 12"},
            "output_voltage_v": {"type": "number", "description": "Output voltage (V). Default 3.3"},
            "output_current_a": {"type": "number", "description": "Output load current (A). Default 2.0"},
            "rise_time_ns": {"type": "number", "description": "Switch transition rise time (ns). Default 10"},
            "inductor_value_uh": {"type": "number", "description": "Output inductor (uH). Default 4.7"},
            "num_harmonics": {"type": "integer", "description": "Number of harmonics. Default 30"},
            "pcb_loop_area_cm2": {"type": "number", "description": "Hot loop area (cm^2). Default 1.0"},
            "limit_standard": {"type": "string", "enum": ["fcc_classb", "fcc_classa", "cispr32_classb", "cispr32_classa"], "description": "Emission limit standard. Default cispr32_classb"},
        }, ["switching_frequency_khz"]),

        # =====================================================================
        # SESSION MANAGEMENT (2 tools)
        # =====================================================================
        _make_tool("pcb_list_sessions", "List all active design sessions.", {}, None),
        _make_tool("pcb_close_session", "Close a design session and free memory.", {
            "session_id": {"type": "string"},
        }, ["session_id"]),
    ]


# =============================================================================
# Tool dispatch
# =============================================================================

@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle all tool calls."""
    try:
        result = _dispatch(name, arguments)
        if not isinstance(result, dict):
            result = {"success": True, "result": _serialize(result)}
        elif "success" not in result:
            result["success"] = True
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
    except PCBError as e:
        return [TextContent(type="text", text=json.dumps(e.to_dict(), indent=2, default=str))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"success": False, "error": str(e)}))]


def _dispatch(name: str, args: dict[str, Any]) -> Any:  # noqa: C901
    """Route tool call to handler."""

    # === FILE PARSING ===
    if name == "pcb_parse_layout":
        data = parse_pcb_file(args["file_path"], args.get("format"))
        sid = sessions.create_session(data)
        return {"success": True, "session_id": sid, **data.to_summary()}

    if name == "pcb_get_stackup":
        data = _get_session(args["session_id"])
        layers = [{"name": l.name, "number": l.number, "type": l.layer_type, "thickness_mm": l.thickness_mm, "er": l.dielectric_constant, "loss_tangent": l.loss_tangent, "material": l.material, "copper_oz": l.copper_weight_oz} for l in data.layers]
        return {"layers": layers, "layer_count": data.layer_count, "thickness_mm": data.board_thickness_mm}

    if name == "pcb_get_components":
        data = _get_session(args["session_id"])
        comps = data.components
        filt = args.get("filter", "")
        if filt:
            import fnmatch
            comps = [c for c in comps if fnmatch.fnmatch(c.reference.upper(), filt.upper())]
        items = [{"reference": c.reference, "value": c.value, "footprint": c.footprint or c.package, "layer": c.layer, "x_mm": round(c.x_mm, 2), "y_mm": round(c.y_mm, 2)} for c in comps[:500]]
        return {"count": len(comps), "components": items}

    if name == "pcb_get_nets":
        data = _get_session(args["session_id"])
        nets = data.nets
        filt = args.get("filter", "")
        if filt:
            import fnmatch
            nets = [n for n in nets if fnmatch.fnmatch(n.name.upper(), filt.upper())]
        items = [{"name": n.name, "index": n.index, "class": n.net_class, "routed_length_mm": round(n.routed_length_mm, 2), "differential": n.is_differential} for n in nets[:500]]
        return {"count": len(nets), "nets": items}

    if name == "pcb_get_vias":
        data = _get_session(args["session_id"])
        items = [{"x_mm": round(v.x_mm, 2), "y_mm": round(v.y_mm, 2), "drill_mm": v.drill_mm, "pad_mm": v.pad_diameter_mm, "type": v.via_type, "net": v.net_name, "layers": f"{v.start_layer}-{v.end_layer}"} for v in data.vias[:500]]
        return {"count": len(data.vias), "vias": items}

    if name == "pcb_get_traces":
        data = _get_session(args["session_id"])
        traces = data.traces
        layer = args.get("layer")
        if layer:
            traces = [t for t in traces if t.layer == layer]
        widths: dict[float, int] = {}
        for t in traces:
            w = round(t.width_mm, 3)
            widths[w] = widths.get(w, 0) + 1
        layers_used = list({t.layer for t in traces})
        return {"count": len(traces), "total_trace_length_mm": round(data.total_trace_length_mm, 1), "width_distribution": widths, "layers": layers_used}

    if name == "pcb_get_drill_table":
        data = _get_session(args["session_id"])
        table = data.drill_table
        total_holes = sum(d.get("count", 0) for d in table)
        unique_sizes = len(table)
        pth_count = sum(d["count"] for d in table if d.get("plating") != "non_plated")
        npth_count = sum(d["count"] for d in table if d.get("plating") == "non_plated")
        smallest = min((d["size_mm"] for d in table), default=0)
        largest = max((d["size_mm"] for d in table), default=0)
        return {
            "drill_table": table,
            "summary": {
                "total_holes": total_holes,
                "unique_sizes": unique_sizes,
                "pth_count": pth_count,
                "npth_count": npth_count,
                "smallest_drill_mm": smallest,
                "largest_drill_mm": largest,
            },
        }

    if name == "pcb_get_board_outline":
        data = _get_session(args["session_id"])
        outline = data.board_outline_detail
        if not outline:
            outline = {
                "width_mm": data.board_width_mm,
                "height_mm": data.board_height_mm,
                "area_mm2": round(data.board_width_mm * data.board_height_mm, 2),
                "vertices": data.board_outline,
                "cutouts": [],
            }
        cutout_count = len(outline.get("cutouts", []))
        return {
            "outline": outline,
            "board_width_mm": outline.get("width_mm", data.board_width_mm),
            "board_height_mm": outline.get("height_mm", data.board_height_mm),
            "board_area_mm2": outline.get("area_mm2", 0),
            "cutout_count": cutout_count,
            "vertex_count": len(outline.get("vertices", [])),
        }

    if name == "pcb_get_design_rules":
        data = _get_session(args["session_id"])
        rules = data.design_rules
        # Also include the top-level min_* fields as fallback
        summary = {
            "min_trace_width_mm": data.min_trace_width_mm,
            "min_clearance_mm": data.min_clearance_mm,
            "min_via_drill_mm": data.min_via_drill_mm,
        }
        # Group rules by type
        by_type: dict[str, list[Any]] = {}
        for r in rules:
            rtype = r.get("type", "other")
            if rtype not in by_type:
                by_type[rtype] = []
            by_type[rtype].append(r)
        return {
            "rules": rules,
            "rule_count": len(rules),
            "by_type": by_type,
            "summary": summary,
        }

    if name == "pcb_get_copper_pours":
        data = _get_session(args["session_id"])
        pours = data.copper_pours
        total_area = sum(p.get("area_mm2", 0) for p in pours)
        layers_with_pours = list({p["layer"] for p in pours})
        nets_with_pours = list({p.get("net_name", "unassigned") for p in pours})
        return {
            "copper_pours": pours,
            "pour_count": len(pours),
            "total_area_mm2": round(total_area, 2),
            "layers_with_pours": layers_with_pours,
            "nets_with_pours": nets_with_pours,
        }

    if name == "pcb_get_manufacturing_notes":
        data = _get_session(args["session_id"])
        notes = data.manufacturing_notes
        return {
            "notes": notes,
            "note_count": len(notes),
        }

    # === IMPEDANCE CALCULATORS ===
    if name == "pcb_calc_microstrip_impedance":
        validate_positive(args.get("trace_width_mm", 0), "trace_width_mm")
        validate_positive(args.get("dielectric_height_mm", 0), "dielectric_height_mm")
        validate_positive(args.get("trace_thickness_mm", 0), "trace_thickness_mm")
        validate_range(args.get("dielectric_constant", 0), 1.0, 100.0, "dielectric_constant")
        return _result(calc_microstrip_impedance(args["trace_width_mm"], args["dielectric_height_mm"], args["trace_thickness_mm"], args["dielectric_constant"]))
    if name == "pcb_calc_stripline_impedance":
        validate_positive(args.get("trace_width_mm", 0), "trace_width_mm")
        validate_positive(args.get("dielectric_height_mm", 0), "dielectric_height_mm")
        validate_positive(args.get("trace_thickness_mm", 0), "trace_thickness_mm")
        validate_range(args.get("dielectric_constant", 0), 1.0, 100.0, "dielectric_constant")
        return _result(calc_stripline_impedance(args["trace_width_mm"], args["dielectric_height_mm"], args["trace_thickness_mm"], args["dielectric_constant"]))
    if name == "pcb_calc_differential_impedance":
        validate_positive(args.get("trace_width_mm", 0), "trace_width_mm")
        validate_positive(args.get("trace_spacing_mm", 0), "trace_spacing_mm")
        validate_positive(args.get("dielectric_height_mm", 0), "dielectric_height_mm")
        validate_positive(args.get("trace_thickness_mm", 0), "trace_thickness_mm")
        validate_range(args.get("dielectric_constant", 0), 1.0, 100.0, "dielectric_constant")
        return _result(calc_differential_impedance(args["trace_width_mm"], args["trace_spacing_mm"], args["dielectric_height_mm"], args["trace_thickness_mm"], args["dielectric_constant"], args.get("trace_type", "microstrip")))
    if name == "pcb_calc_trace_width":
        validate_positive(args.get("current_amps", 0), "current_amps")
        validate_positive(args.get("temp_rise_c", 0), "temp_rise_c")
        validate_positive(args.get("copper_thickness_oz", 0), "copper_thickness_oz")
        return _result(calc_trace_width_for_current(args["current_amps"], args["temp_rise_c"], args["copper_thickness_oz"], args.get("layer_type", "external")))

    # === ADVANCED RF CALCULATORS ===
    if name == "pcb_calc_cpw_impedance":
        validate_positive(args.get("trace_width_mm", 0), "trace_width_mm")
        validate_positive(args.get("gap_mm", 0), "gap_mm")
        validate_positive(args.get("dielectric_height_mm", 0), "dielectric_height_mm")
        validate_non_negative(args.get("trace_thickness_mm", 0), "trace_thickness_mm")
        validate_range(args.get("dielectric_constant", 0), 1.0, 100.0, "dielectric_constant")
        return _result(calc_cpw_impedance(args["trace_width_mm"], args["gap_mm"], args["dielectric_height_mm"], args["trace_thickness_mm"], args["dielectric_constant"], args.get("has_ground_plane", True)))
    if name == "pcb_calc_skin_effect":
        validate_positive(args.get("frequency_mhz", 0), "frequency_mhz")
        validate_positive(args.get("copper_thickness_oz", 1.0), "copper_thickness_oz")
        validate_non_negative(args.get("surface_roughness_um", 0.5), "surface_roughness_um")
        return _result(calc_skin_effect(args["frequency_mhz"], args.get("copper_thickness_oz", 1.0), args.get("surface_roughness_um", 0.5)))
    if name == "pcb_calc_dielectric_loss":
        validate_positive(args.get("frequency_mhz", 0), "frequency_mhz")
        validate_range(args.get("dielectric_constant", 0), 1.0, 100.0, "dielectric_constant")
        validate_non_negative(args.get("loss_tangent", 0), "loss_tangent")
        validate_positive(args.get("trace_length_mm", 0), "trace_length_mm")
        return _result(calc_dielectric_loss(args["frequency_mhz"], args["dielectric_constant"], args["loss_tangent"], args["trace_length_mm"]))
    if name == "pcb_calc_plane_resonance":
        validate_positive(args.get("plane_width_mm", 0), "plane_width_mm")
        validate_positive(args.get("plane_length_mm", 0), "plane_length_mm")
        validate_range(args.get("dielectric_constant", 0), 1.0, 100.0, "dielectric_constant")
        validate_positive(args.get("dielectric_height_mm", 0), "dielectric_height_mm")
        return _result(calc_plane_resonance(args["plane_width_mm"], args["plane_length_mm"], args["dielectric_constant"], args["dielectric_height_mm"]))
    if name == "pcb_calc_via_stitching":
        validate_positive(args.get("max_frequency_mhz", 0), "max_frequency_mhz")
        validate_range(args.get("dielectric_constant", 0), 1.0, 100.0, "dielectric_constant")
        return _result(calc_via_stitching_requirements(args["max_frequency_mhz"], args["dielectric_constant"]))

    # === S-PARAMETER / MODE CONVERSION ===
    if name == "pcb_calc_insertion_loss":
        validate_positive(args.get("trace_length_mm", 0), "trace_length_mm")
        validate_positive(args.get("trace_width_mm", 0), "trace_width_mm")
        validate_positive(args.get("dielectric_height_mm", 0), "dielectric_height_mm")
        validate_range(args.get("dielectric_constant", 0), 1.0, 100.0, "dielectric_constant")
        validate_non_negative(args.get("loss_tangent", 0), "loss_tangent")
        from .analyzers.rf_si.sparam_extractor import calculate_insertion_loss
        return _result(calculate_insertion_loss(
            trace_length_mm=args["trace_length_mm"],
            trace_width_mm=args["trace_width_mm"],
            dielectric_height_mm=args["dielectric_height_mm"],
            dielectric_constant=args["dielectric_constant"],
            loss_tangent=args["loss_tangent"],
            copper_thickness_oz=args.get("copper_thickness_oz", 1.0),
            surface_roughness_um=args.get("surface_roughness_um", 0.5),
            freq_start_mhz=args.get("freq_start_mhz", 10.0),
            freq_stop_mhz=args.get("freq_stop_mhz", 10000.0),
            num_points=args.get("num_points", 50),
        ))
    if name == "pcb_calc_return_loss":
        validate_positive(args.get("impedance_ohm", 0), "impedance_ohm")
        validate_positive(args.get("target_impedance_ohm", 0), "target_impedance_ohm")
        validate_positive(args.get("frequency_mhz", 0), "frequency_mhz")
        from .analyzers.rf_si.sparam_extractor import calculate_return_loss
        return _result(calculate_return_loss(
            impedance_ohm=args["impedance_ohm"],
            target_impedance_ohm=args["target_impedance_ohm"],
            frequency_mhz=args["frequency_mhz"],
        ))
    if name == "pcb_analyze_mode_conversion":
        validate_positive(args.get("trace_width_mm", 0), "trace_width_mm")
        validate_positive(args.get("trace_spacing_mm", 0), "trace_spacing_mm")
        validate_positive(args.get("dielectric_height_mm", 0), "dielectric_height_mm")
        validate_range(args.get("dielectric_constant", 0), 1.0, 100.0, "dielectric_constant")
        validate_non_negative(args.get("length_asymmetry_mm", 0), "length_asymmetry_mm")
        validate_positive(args.get("data_rate_gbps", 0), "data_rate_gbps")
        from .analyzers.rf_si.mode_conversion import analyze_mode_conversion
        return _result(analyze_mode_conversion(
            trace_width_mm=args["trace_width_mm"],
            trace_spacing_mm=args["trace_spacing_mm"],
            dielectric_height_mm=args["dielectric_height_mm"],
            dielectric_constant=args["dielectric_constant"],
            length_asymmetry_mm=args["length_asymmetry_mm"],
            data_rate_gbps=args["data_rate_gbps"],
            trace_type=args.get("trace_type", "microstrip"),
        ))

    # === SIGNAL INTEGRITY ===
    if name == "pcb_analyze_timing":
        validate_positive(args.get("trace_length_mm", 0), "trace_length_mm")
        validate_range(args.get("effective_er", 0), 1.0, 100.0, "effective_er")
        validate_positive(args.get("data_rate_gbps", 0), "data_rate_gbps")
        validate_positive(args.get("rise_time_ps", 0), "rise_time_ps")
        validate_non_negative(args.get("setup_time_ps", 0), "setup_time_ps")
        validate_non_negative(args.get("hold_time_ps", 0), "hold_time_ps")
        return _result(analyze_trace_timing(args["trace_length_mm"], args["effective_er"], args["data_rate_gbps"], args["rise_time_ps"], args["setup_time_ps"], args["hold_time_ps"]))
    if name == "pcb_analyze_crosstalk":
        validate_positive(args.get("trace_spacing_mm", 0), "trace_spacing_mm")
        validate_positive(args.get("trace_width_mm", 0), "trace_width_mm")
        validate_positive(args.get("dielectric_height_mm", 0), "dielectric_height_mm")
        validate_positive(args.get("coupling_length_mm", 0), "coupling_length_mm")
        validate_positive(args.get("rise_time_ps", 0), "rise_time_ps")
        return _result(analyze_crosstalk(args["trace_spacing_mm"], args["trace_width_mm"], args["dielectric_height_mm"], args["coupling_length_mm"], args["rise_time_ps"]))
    if name == "pcb_analyze_via":
        validate_positive(args.get("via_diameter_mm", 0), "via_diameter_mm")
        validate_positive(args.get("via_length_mm", 0), "via_length_mm")
        validate_positive(args.get("pad_diameter_mm", 0), "pad_diameter_mm")
        validate_positive(args.get("antipad_diameter_mm", 0), "antipad_diameter_mm")
        validate_range(args.get("dielectric_constant", 0), 1.0, 100.0, "dielectric_constant")
        validate_positive(args.get("frequency_ghz", 0), "frequency_ghz")
        return _result(analyze_via(args["via_diameter_mm"], args["via_length_mm"], args["pad_diameter_mm"], args["antipad_diameter_mm"], args["dielectric_constant"], args["frequency_ghz"]))

    if name == "pcb_analyze_differential_pair":
        validate_positive(args.get("trace_width_mm", 0), "trace_width_mm")
        validate_positive(args.get("trace_spacing_mm", 0), "trace_spacing_mm")
        validate_positive(args.get("dielectric_height_mm", 0), "dielectric_height_mm")
        validate_range(args.get("dielectric_constant", 0), 1.0, 100.0, "dielectric_constant")
        validate_positive(args.get("target_impedance_ohm", 0), "target_impedance_ohm")
        validate_positive(args.get("data_rate_gbps", 0), "data_rate_gbps")
        res = calc_differential_impedance(args["trace_width_mm"], args["trace_spacing_mm"], args["dielectric_height_mm"], args.get("trace_thickness_mm", 0.035), args["dielectric_constant"])
        z_diff = res["differential_impedance_ohms"]
        target = args["target_impedance_ohm"]
        deviation = abs(z_diff - target) / target * 100
        issues = []
        if deviation > 10:
            issues.append(f"Impedance deviation {deviation:.1f}% exceeds 10% tolerance")
        if deviation > 5:
            issues.append(f"Impedance {z_diff:.1f} ohm vs target {target:.1f} ohm ({deviation:.1f}% off)")
        return {"differential_impedance_ohm": z_diff, "target_impedance_ohm": target, "deviation_percent": round(deviation, 1), "compliant": deviation <= 10, "data_rate_gbps": args["data_rate_gbps"], "issues": issues}

    if name == "pcb_analyze_length_matching":
        validate_positive(args.get("max_skew_ps", 0), "max_skew_ps")
        validate_range(args.get("effective_er", 0), 1.0, 100.0, "effective_er")
        lengths = args["trace_lengths_mm"]
        max_skew_ps = args["max_skew_ps"]
        er = args["effective_er"]
        prop_delay_ps_per_mm = (1000 / C0) * math.sqrt(er) * 1e12
        delays = {n: l * prop_delay_ps_per_mm for n, l in lengths.items()}
        min_d, max_d = min(delays.values()), max(delays.values())
        skew_ps = max_d - min_d
        ref_name = min(delays, key=lambda k: delays[k])
        mismatches = {n: {"length_mm": round(lengths[n], 2), "delay_ps": round(d, 1), "delta_ps": round(d - delays[ref_name], 1)} for n, d in delays.items()}
        return {"max_skew_ps": round(skew_ps, 1), "allowed_skew_ps": max_skew_ps, "compliant": skew_ps <= max_skew_ps, "reference_net": ref_name, "signals": mismatches}

    if name == "pcb_calc_eye_diagram":
        validate_positive(args.get("data_rate_gbps", 0), "data_rate_gbps")
        validate_positive(args.get("trace_length_mm", 0), "trace_length_mm")
        validate_range(args.get("dielectric_constant", 0), 1.0, 100.0, "dielectric_constant")
        validate_non_negative(args.get("loss_tangent", 0), "loss_tangent")
        validate_positive(args.get("trace_width_mm", 0), "trace_width_mm")
        validate_positive(args.get("dielectric_height_mm", 0), "dielectric_height_mm")
        from .analyzers.rf_si.eye_diagram import calculate_eye_opening
        return _result(calculate_eye_opening(
            data_rate_gbps=args["data_rate_gbps"],
            trace_length_mm=args["trace_length_mm"],
            dielectric_constant=args["dielectric_constant"],
            loss_tangent=args["loss_tangent"],
            trace_width_mm=args["trace_width_mm"],
            dielectric_height_mm=args["dielectric_height_mm"],
            copper_thickness_oz=args.get("copper_thickness_oz", 1.0),
            rise_time_ps=args.get("rise_time_ps", 50.0),
            v_swing_mv=args.get("v_swing_mv", 800.0),
            standard=args.get("standard"),
        ))

    # === EMC ===
    if name == "pcb_analyze_current_loop":
        validate_positive(args.get("loop_area_mm2", 0), "loop_area_mm2")
        validate_positive(args.get("current_ma", 0), "current_ma")
        validate_positive(args.get("frequency_mhz", 0), "frequency_mhz")
        return _result(analyze_current_loop(args["loop_area_mm2"], args["current_ma"], args["frequency_mhz"]))
    if name == "pcb_estimate_bandwidth":
        validate_positive(args.get("rise_time_ps", 0), "rise_time_ps")
        return _result(estimate_rise_time_bandwidth(args["rise_time_ps"]))

    if name == "pcb_analyze_shielding":
        from .analyzers.emc.shielding import ShieldingAnalyzer, ShieldConfig
        analyzer = ShieldingAnalyzer()
        apertures = []
        if args.get("aperture_mm"):
            apertures = [{"type": "circular", "diameter": args["aperture_mm"]}]
        config = ShieldConfig(material=args["material"], thickness_mm=args["thickness_mm"], apertures=apertures)
        res = analyzer.analyze_shield(config=config, frequency_mhz=args["frequency_mhz"])  # type: ignore[assignment]
        return _serialize(res)

    if name == "pcb_analyze_esd":
        from .analyzers.emc.esd_assessment import ESDAnalyzer, ESDInterface
        analyzer = ESDAnalyzer()  # type: ignore[assignment]
        iface = ESDInterface(
            name=args["interface_type"], interface_type=args["interface_type"],
            connector_location=(0, 0), has_tvs=args.get("has_tvs", False),
            trace_length_to_ic_mm=args.get("trace_length_mm", 50),
        )
        res = analyzer.analyze_interface(interface=iface)  # type: ignore[attr-defined]
        return _serialize(res)

    if name == "pcb_analyze_grounding":
        from .analyzers.emc.grounding import GroundingAnalyzer, GroundPlane
        analyzer = GroundingAnalyzer()  # type: ignore[assignment]
        size = args.get("board_size_mm", 100)
        planes = [GroundPlane(layer_number=1, name=args["topology"], coverage_percent=90, width_mm=size, height_mm=size)]
        res = analyzer.analyze_grounding(planes=planes, board_width_mm=size, board_height_mm=size, max_frequency_mhz=args["max_frequency_mhz"])  # type: ignore[attr-defined]
        return _serialize(res)

    if name == "pcb_predict_compliance":
        from .analyzers.emc.compliance_predictor import EMCCompliancePredictor, EMCStandard, ClockSource
        predictor = EMCCompliancePredictor()
        predictor.add_clock(ClockSource(name="CLK", frequency_mhz=args["clock_frequency_mhz"], rise_time_ns=args["rise_time_ps"] / 1000.0))
        if args.get("has_shielding"):
            predictor.set_shielding(enclosure_shielding_db=20.0)
        std_map = {"FCC_A": "fcc_class_a", "FCC_B": "fcc_class_b", "CISPR_A": "cispr_32_class_a", "CISPR_B": "cispr_32_class_b"}
        std_val = std_map.get(args.get("standard", "FCC_B"), args.get("standard", "fcc_class_b"))
        res = predictor.predict_compliance(standard=EMCStandard(std_val))  # type: ignore[assignment]
        return _serialize(res)

    if name == "pcb_analyze_return_current_density":
        from .analyzers.emc.current_density import analyze_return_current_density
        return _result(analyze_return_current_density(
            trace_x_start=args["trace_x_start"], trace_y_start=args["trace_y_start"],
            trace_x_end=args["trace_x_end"], trace_y_end=args["trace_y_end"],
            plane_width_mm=args["plane_width_mm"], plane_height_mm=args["plane_height_mm"],
            frequency_mhz=args["frequency_mhz"], plane_gaps=args.get("plane_gaps"),
        ))

    if name == "pcb_optimize_ground_stitching":
        from .analyzers.emc.current_density import optimize_ground_stitching
        return _result(optimize_ground_stitching(
            plane_width_mm=args["plane_width_mm"], plane_height_mm=args["plane_height_mm"],
            max_frequency_mhz=args["max_frequency_mhz"], dielectric_constant=args["dielectric_constant"],
            existing_vias=args.get("existing_vias"), plane_gaps=args.get("plane_gaps"),
        ))

    # === EMI / RETURN PATH ===
    if name == "pcb_trace_return_path":
        from .analyzers.emc.return_path_analyzer import ReturnPathAnalyzer
        from .classifiers.net_classifier import NetClassifier
        data = _get_session(args["session_id"])
        classifier = NetClassifier()
        classified = classifier.classify(data)
        net_categories = {nc.net_name: nc.category for nc in classified.classified_nets}
        category = net_categories.get(args["net_name"], "unknown")
        analyzer = ReturnPathAnalyzer()  # type: ignore[assignment]
        result = analyzer.analyze_net(data, args["net_name"], net_category=category, net_categories=net_categories)  # type: ignore[attr-defined]
        return _serialize(result)

    if name == "pcb_analyze_return_paths":
        from .analyzers.emc.return_path_analyzer import ReturnPathAnalyzer
        from .classifiers.net_classifier import NetClassifier
        data = _get_session(args["session_id"])
        classifier = NetClassifier()
        classified = classifier.classify(data)
        analyzer = ReturnPathAnalyzer()  # type: ignore[assignment]
        result = analyzer.analyze(data, classified, max_frequency_mhz=args.get("max_frequency_mhz", 0))  # type: ignore[attr-defined]
        return _serialize(result)

    if name == "pcb_find_split_crossings":
        from .analyzers.emc.return_path_analyzer import ReturnPathAnalyzer
        data = _get_session(args["session_id"])
        analyzer = ReturnPathAnalyzer()  # type: ignore[assignment]
        crossings = analyzer.find_split_crossings(data)  # type: ignore[attr-defined]
        return {"split_crossings": [_serialize(c) for c in crossings], "count": len(crossings)}

    if name == "pcb_analyze_emi_risk":
        from .analyzers.emc.emi_risk_scorer import EMIRiskScorer
        from .analyzers.emc.return_path_analyzer import ReturnPathAnalyzer
        from .classifiers.net_classifier import NetClassifier
        data = _get_session(args["session_id"])
        classifier = NetClassifier()
        classified = classifier.classify(data)
        rp_analyzer = ReturnPathAnalyzer()
        rp_result = rp_analyzer.analyze(data, classified)
        scorer = EMIRiskScorer()
        result = scorer.score(data, rp_result, classified, standard=args.get("standard", "FCC_B"))
        return _serialize(result)

    if name == "pcb_predict_emissions":
        from .analyzers.emc.emi_risk_scorer import EMIRiskScorer
        from .analyzers.emc.return_path_analyzer import ReturnPathAnalyzer
        from .classifiers.net_classifier import NetClassifier
        data = _get_session(args["session_id"])
        classifier = NetClassifier()
        classified = classifier.classify(data)
        rp_analyzer = ReturnPathAnalyzer()
        rp_result = rp_analyzer.analyze(data, classified)
        scorer = EMIRiskScorer()
        dist = args.get("test_distance_m", 3.0)
        result = scorer.score(data, rp_result, classified, standard=args.get("standard", "FCC_B"), test_distance_m=dist)
        # Return focused emission spectrum data
        compliance = result.standard_compliance
        return {
            "frequency_risks": [_serialize(fr) for fr in result.frequency_risks],
            "predicted_problem_frequencies_mhz": result.predicted_problem_frequencies_mhz,
            "standard_compliance": compliance,
            "test_distance_m": dist,
            "standard": args.get("standard", "FCC_B"),
            "total_frequencies_analyzed": len(result.frequency_risks),
        }

    if name == "pcb_get_emi_hotspots":
        from .analyzers.emc.emi_risk_scorer import EMIRiskScorer
        from .analyzers.emc.return_path_analyzer import ReturnPathAnalyzer
        from .classifiers.net_classifier import NetClassifier
        data = _get_session(args["session_id"])
        classifier = NetClassifier()
        classified = classifier.classify(data)
        rp_analyzer = ReturnPathAnalyzer()
        rp_result = rp_analyzer.analyze(data, classified)
        scorer = EMIRiskScorer()
        result = scorer.score(data, rp_result, classified)
        return {
            "hotspots": [_serialize(r) for r in result.board_regions],
            "count": len(result.board_regions),
            "overall_risk_level": result.overall_risk_level,
            "overall_risk_score": result.overall_risk_score,
        }

    # === HIGH-SPEED DIGITAL ===
    if name == "pcb_analyze_ddr":
        from .analyzers.high_speed.ddr_analyzer import DDRAnalyzer, DDRStandard
        analyzer = DDRAnalyzer()  # type: ignore[assignment]
        tl = args.get("trace_length_mm", 50)
        byte_lanes = [{"name": "DQ0", "data_lengths_mm": [tl] * 8, "dqs_p_length_mm": tl, "dqs_n_length_mm": tl}]
        res = analyzer.analyze(ddr_standard=DDRStandard(args["ddr_standard"]), data_rate_mtps=args.get("data_rate_mtps", 3200), byte_lanes=byte_lanes, trace_impedance_ohm=args.get("trace_impedance_ohm"))  # type: ignore[attr-defined]
        return _serialize(res)

    if name == "pcb_analyze_pcie":
        from .analyzers.high_speed.pcie_analyzer import PCIeAnalyzer, PCIeGeneration
        analyzer = PCIeAnalyzer()  # type: ignore[assignment]
        tl = args.get("trace_length_mm", 100)
        lane_count = args.get("lane_count", 1)
        lanes = [{"name": f"Lane{i}", "tx_p_length_mm": tl, "tx_n_length_mm": tl, "rx_p_length_mm": tl, "rx_n_length_mm": tl} for i in range(lane_count)]
        res = analyzer.analyze(generation=PCIeGeneration(args["pcie_gen"]), lanes=lanes, differential_impedance_ohm=args.get("differential_impedance_ohm"))  # type: ignore[attr-defined]
        return _serialize(res)

    if name == "pcb_calc_pcie_link_budget":
        from .analyzers.high_speed.pcie_link_budget import calculate_pcie_link_budget
        return calculate_pcie_link_budget(
            pcie_gen=args["pcie_gen"],
            trace_length_mm=args["trace_length_mm"],
            dielectric_constant=args.get("dielectric_constant", 4.0),
            loss_tangent=args.get("loss_tangent", 0.02),
            copper_thickness_oz=args.get("copper_thickness_oz", 0.5),
            connector_loss_db=args.get("connector_loss_db", 0.0),
            via_loss_db=args.get("via_loss_db", 0.0),
            package_loss_db=args.get("package_loss_db", 0.0),
        )

    if name == "pcb_validate_pcie_lanes":
        from .analyzers.high_speed.pcie_link_budget import validate_pcie_lanes
        return validate_pcie_lanes(
            lane_lengths_mm=args["lane_lengths_mm"],
            dielectric_constant=args.get("dielectric_constant", 4.0),
            pcie_gen=args.get("pcie_gen", 4),
        )

    if name == "pcb_analyze_usb":
        from .analyzers.high_speed.usb_analyzer import USBAnalyzer, USBVersion
        analyzer = USBAnalyzer()  # type: ignore[assignment]
        tl = args.get("trace_length_mm", 100)
        usb2_pair = {"p_length_mm": tl, "n_length_mm": tl, "via_count": 2}
        res = analyzer.analyze(usb_version=USBVersion(args["usb_version"]), usb2_pair=usb2_pair, usb2_impedance_ohm=args.get("differential_impedance_ohm"))  # type: ignore[attr-defined]
        return _serialize(res)

    if name == "pcb_analyze_ethernet":
        from .analyzers.high_speed.ethernet_analyzer import EthernetAnalyzer, EthernetSpeed
        analyzer = EthernetAnalyzer()  # type: ignore[assignment]
        tl = args.get("trace_length_mm", 50)
        skew = args.get("pair_skew_ps", 0)
        mdi_pairs = [{"name": f"MDI{i}", "p_length_mm": tl, "n_length_mm": tl + skew * 0.17} for i in range(4)]
        res = analyzer.analyze(speed=EthernetSpeed(args["speed"]), mdi_pairs=mdi_pairs)  # type: ignore[attr-defined]
        return _serialize(res)

    if name == "pcb_validate_ddr_topology":
        from .analyzers.high_speed.ddr_topology import validate_ddr_topology
        from .classifiers.net_classifier import NetClassifier
        data = _get_session(args["session_id"])
        classifier = NetClassifier()
        classified = classifier.classify(data)
        # Build trace_lengths from net routed_length data
        trace_lengths = {}
        for net in data.nets:
            if net.routed_length_mm > 0:
                trace_lengths[net.name] = net.routed_length_mm
        ddr_std = args.get("ddr_standard", "DDR4")
        er = 4.3
        if data.layers:
            for layer in data.layers:
                if layer.dielectric_constant and layer.dielectric_constant > 1:
                    er = layer.dielectric_constant
                    break
        return validate_ddr_topology(
            classified_nets=classified,
            trace_lengths=trace_lengths if trace_lengths else None,
            ddr_standard=ddr_std,
            dielectric_constant=er,
        )

    if name == "pcb_analyze_ddr_timing_budget":
        from .analyzers.high_speed.ddr_topology import analyze_ddr_timing_budget
        return analyze_ddr_timing_budget(
            ddr_standard=args["ddr_standard"],
            data_rate_mtps=args["data_rate_mtps"],
            byte_lanes=args["byte_lanes"],
            dielectric_constant=args.get("dielectric_constant", 4.3),
        )

    # === POWER INTEGRITY ===
    if name == "pcb_analyze_pdn":
        from .analyzers.power_integrity.pdn_analyzer import PDNAnalyzer
        analyzer = PDNAnalyzer()  # type: ignore[assignment]
        res = analyzer.analyze(  # type: ignore[attr-defined]
            voltage=args["supply_voltage_v"], max_current=args["max_current_a"],
            ripple_percent=args.get("ripple_percent", 5),
        )
        return _serialize(res)

    if name == "pcb_calc_pdn_impedance":
        from .analyzers.power_integrity.pdn_impedance import calculate_pdn_impedance
        return calculate_pdn_impedance(
            supply_voltage_v=args["supply_voltage_v"],
            max_current_a=args["max_current_a"],
            ripple_percent=args["ripple_percent"],
            capacitors=args["capacitors"],
            vrm_bandwidth_khz=args.get("vrm_bandwidth_khz", 50.0),
            vrm_r_out_mohm=args.get("vrm_r_out_mohm", 1.0),
            plane_area_mm2=args.get("plane_area_mm2", 0.0),
            dielectric_height_mm=args.get("dielectric_height_mm", 0.1),
            dielectric_constant=args.get("dielectric_constant", 4.3),
            freq_start_hz=args.get("frequency_start_hz", 1.0),
            freq_stop_hz=args.get("frequency_stop_hz", 1e9),
            num_points=args.get("num_points", 500),
        )

    if name == "pcb_analyze_decoupling":
        from .analyzers.power_integrity.decap_placement import DecapAnalyzer
        analyzer = DecapAnalyzer()  # type: ignore[assignment]
        cap_values = args.get("cap_values_uf", [0.1, 1.0, 10.0])
        decaps = [{"ref": f"C{i+1}", "capacitance_uf": c, "package": "0402", "position": (i * 2, 0), "via_count": 2} for i, c in enumerate(cap_values)]
        freq_hz = args["max_frequency_mhz"] * 1e6
        res = analyzer.analyze_ic_decoupling(ic_ref="U1", ic_position=(0, 0), power_rail="VCC", target_frequency_hz=freq_hz, decaps=decaps)  # type: ignore[attr-defined]
        return _serialize(res)

    if name == "pcb_analyze_vrm":
        from .analyzers.power_integrity.vrm_analyzer import VRMAnalyzer
        analyzer = VRMAnalyzer()  # type: ignore[assignment]
        dist = args.get("distance_to_load_mm", 25)
        res = analyzer.analyze_vrm(  # type: ignore[attr-defined]
            vrm_ref="U_VRM", vrm_position=(0, 0), output_rail="VOUT",
            output_voltage=args["output_voltage_v"], output_current=args["output_current_a"],
            input_voltage=args.get("input_voltage_v", 12.0), components=[],
            load_positions=[(dist, 0)],
        )
        return _serialize(res)

    # === DFM ===
    if name == "pcb_analyze_solder_paste":
        from .analyzers.dfm.solder_paste import SolderPasteAnalyzer, PadDefinition, ComponentPads
        analyzer = SolderPasteAnalyzer()  # type: ignore[assignment]
        pad = PadDefinition(pad_id="1", width_mm=args["pad_width_mm"], length_mm=args["pad_length_mm"], pitch_mm=args["pitch_mm"])
        comp = ComponentPads(reference="U1", package="custom", pads=[pad])
        res = analyzer.analyze_component(component=comp, stencil_thickness_mm=args.get("stencil_thickness_mm", 0.12))  # type: ignore[attr-defined]
        return _serialize(res)

    if name == "pcb_analyze_placement":
        from .analyzers.dfm.component_placement import PlacementAnalyzer, Component
        analyzer = PlacementAnalyzer()  # type: ignore[assignment]
        pitch = args["component_pitch_mm"]
        comps = [
            Component(reference="U1", package="QFN32", x_mm=0, y_mm=0, width_mm=5, height_mm=5, rotation_deg=0, side="top"),  # type: ignore[list-item]
            Component(reference="U2", package="QFN32", x_mm=pitch, y_mm=0, width_mm=5, height_mm=5, rotation_deg=0, side="bottom" if args.get("has_bottom_components") else "top"),  # type: ignore[list-item]
        ]
        size = max(pitch * 3, 50)
        res = analyzer.analyze_placement(components=comps, board_width_mm=size, board_height_mm=size)  # type: ignore[attr-defined]
        return _serialize(res)

    if name == "pcb_analyze_assembly":
        from .analyzers.dfm.assembly_check import AssemblyAnalyzer, AssemblyComponent
        analyzer = AssemblyAnalyzer.for_standard_smt()  # type: ignore[assignment]
        comps = []
        fp = args.get("finest_pitch_mm", 0.5)
        def _assy_comp(ref, pkg, side="top", pitch=fp, pin_count=2, pad_w=0.3, pad_l=0.5):
            return AssemblyComponent(reference=ref, package=pkg, x_mm=0, y_mm=0, rotation_deg=0, side=side, pad_width_mm=pad_w, pad_length_mm=pad_l, pin_count=pin_count, pitch_mm=pitch)
        for i in range(args.get("smd_count", 0)):
            comps.append(_assy_comp(f"R{i+1}", "0402"))
        for i in range(args.get("through_hole_count", 0)):
            comps.append(_assy_comp(f"J{i+1}", "DIP", pitch=2.54, pin_count=8, pad_w=1.0, pad_l=1.5))
        for i in range(args.get("bga_count", 0)):
            comps.append(_assy_comp(f"U{i+1}", "BGA", pin_count=256, pad_w=0.3, pad_l=0.3))
        if not comps:
            for i in range(args["component_count"]):
                comps.append(_assy_comp(f"C{i+1}", "0603"))
        res = analyzer.analyze_assembly(components=comps)  # type: ignore[attr-defined]
        return _serialize(res)

    if name == "pcb_analyze_tolerance":
        from .analyzers.dfm.tolerance_analysis import ToleranceAnalyzer, ToleranceContributor
        analyzer = ToleranceAnalyzer()  # type: ignore[assignment]
        contributors = [ToleranceContributor(name=f"dim_{i+1}", nominal_mm=args["nominal_mm"] / len(args["tolerances_mm"]), tolerance_plus_mm=t, tolerance_minus_mm=t) for i, t in enumerate(args["tolerances_mm"])]
        total_tol = sum(args["tolerances_mm"])
        spec = (args["nominal_mm"] - total_tol, args["nominal_mm"] + total_tol)
        run_mc = args.get("method", "worst_case") == "monte_carlo"
        res = analyzer.analyze_stack(contributors=contributors, specification_mm=spec, run_monte_carlo=run_mc)  # type: ignore[attr-defined]
        return _serialize(res)

    # === THERMAL ===
    if name == "pcb_analyze_thermal":
        from .analyzers.thermal.power_dissipation import PowerDissipationAnalyzer
        analyzer = PowerDissipationAnalyzer()  # type: ignore[assignment]
        temp_rise = analyzer.estimate_temp_rise(power_w=args["power_watts"], theta_ja=args["theta_ja_c_per_w"])  # type: ignore[attr-defined]
        ambient = args.get("ambient_temp_c", 25)
        max_tj = args.get("max_junction_temp_c", 125)
        junction_temp = ambient + temp_rise
        return {"power_watts": args["power_watts"], "theta_ja_c_per_w": args["theta_ja_c_per_w"], "ambient_temp_c": ambient, "junction_temp_c": round(junction_temp, 1), "temp_rise_c": round(temp_rise, 1), "max_junction_temp_c": max_tj, "margin_c": round(max_tj - junction_temp, 1), "safe": junction_temp < max_tj}

    if name == "pcb_analyze_thermal_via":
        from .analyzers.thermal.thermal_via import ThermalViaAnalyzer
        analyzer = ThermalViaAnalyzer()  # type: ignore[assignment]
        fill = args.get("copper_fill_percent", 25)
        vias = [{"diameter_mm": args["via_diameter_mm"], "count": args["via_count"], "filled": fill >= 90}]
        res = analyzer.analyze_component(  # type: ignore[attr-defined]
            component_ref="U1", pad_area_mm2=args["via_count"] * 3.14 * (args["via_diameter_mm"] / 2) ** 2 * 4,
            power_w=args["power_watts"], vias=vias, board_thickness_mm=args.get("board_thickness_mm", 1.6),
        )
        return _serialize(res)

    if name == "pcb_analyze_copper_spreading":
        from .analyzers.thermal.copper_spreading import CopperSpreadingAnalyzer
        analyzer = CopperSpreadingAnalyzer()  # type: ignore[assignment]
        oz = args["copper_thickness_oz"]
        area = args["copper_area_mm2"]
        res = analyzer.analyze_component(  # type: ignore[attr-defined]
            component_ref="U1", power_w=args["power_watts"],
            footprint_area_mm2=min(area / 4, 100),
            connected_copper=[{"layer": "top", "area_mm2": area, "thickness_oz": oz}],
        )
        return _serialize(res)

    # === ANTENNA/EMI ===
    if name == "pcb_analyze_trace_antenna":
        from .analyzers.antenna.trace_antenna import TraceAntennaAnalyzer
        analyzer = TraceAntennaAnalyzer()  # type: ignore[assignment]
        trace = {"name": "trace", "length_mm": args["trace_length_mm"], "dielectric_constant": args.get("dielectric_constant", 4.3)}
        issues = analyzer.analyze_trace(trace=trace, max_frequency_mhz=args["frequency_mhz"])  # type: ignore[attr-defined]
        return {"trace_length_mm": args["trace_length_mm"], "frequency_mhz": args["frequency_mhz"], "issues": [_serialize(i) for i in issues], "antenna_risk": len(issues) > 0}

    if name == "pcb_analyze_slot_antenna":
        from .analyzers.antenna.slot_antenna import SlotAntennaAnalyzer
        analyzer = SlotAntennaAnalyzer()  # type: ignore[assignment]
        slot = {"id": "slot1", "length_mm": args["slot_length_mm"], "width_mm": args.get("slot_width_mm", 1.0)}
        issue = analyzer.analyze_slot(slot=slot, operating_frequencies=[args["frequency_mhz"]])  # type: ignore[attr-defined]
        return {"slot_length_mm": args["slot_length_mm"], "frequency_mhz": args["frequency_mhz"], "issue": _serialize(issue) if issue else None, "resonant": issue is not None}

    if name == "pcb_analyze_common_mode":
        from .analyzers.antenna.common_mode import CommonModeAnalyzer
        analyzer = CommonModeAnalyzer()  # type: ignore[assignment]
        pair = {
            "name": "pair", "differential_impedance_ohm": args["differential_impedance_ohm"],
            "common_mode_impedance_ohm": args.get("common_mode_impedance_ohm", args["differential_impedance_ohm"] / 2),
            "cable_length_m": args.get("cable_length_m", 1.0), "frequency_mhz": args["frequency_mhz"],
        }
        res = analyzer.analyze_pair(pair=pair)  # type: ignore[attr-defined]
        return _serialize(res)

    if name == "pcb_analyze_cable_coupling":
        from .analyzers.antenna.cable_coupling import CableCouplingAnalyzer
        analyzer = CableCouplingAnalyzer()  # type: ignore[assignment]
        conn = {
            "name": "connector", "cable_spacing_mm": args["cable_spacing_mm"],
            "parallel_length_mm": args["parallel_length_mm"], "frequency_mhz": args["frequency_mhz"],
            "cable_type": args.get("cable_type", "unshielded"),
        }
        res = analyzer.analyze_connector(connector=conn)  # type: ignore[attr-defined]
        return _serialize(res)

    # === CLASSIFICATION ===
    if name == "pcb_classify_nets":
        from .classifiers.net_classifier import NetClassifier
        data = _get_session(args["session_id"])
        classifier = NetClassifier()
        result = classifier.classify(data)
        return result.to_dict()

    if name == "pcb_detect_interfaces":
        from .classifiers.net_classifier import NetClassifier
        from .classifiers.interface_detector import InterfaceDetector
        data = _get_session(args["session_id"])
        classifier = NetClassifier()
        net_cls = classifier.classify(data)
        detector = InterfaceDetector()
        result = detector.detect(data, net_cls)
        return result.to_dict()

    if name == "pcb_classify_design":
        from .classifiers.design_classifier import DesignClassifier
        data = _get_session(args["session_id"])
        classifier = DesignClassifier()  # type: ignore[assignment]
        result = classifier.classify(data)
        return result.to_dict()

    # === REFERENCE DATA ===
    if name == "pcb_get_stackup_templates":
        return {"stackup_templates": STACKUP_TEMPLATES}
    if name == "pcb_get_material_properties":
        return {"materials": MATERIAL_PROPERTIES}

    # === 3D / STEP FILE ===
    if name == "pcb_parse_step":
        from .parsers.step_parser import STEPParser
        parser = STEPParser()
        result = parser.parse_file(args["file_path"])
        board_3d = result.get("board_3d", {})
        step_components = result.get("step_components", [])
        existing_sid = args.get("session_id")
        if existing_sid:
            # Merge 3D data into existing session
            data = _get_session(existing_sid)
            data.step_components = step_components
            data.board_3d = board_3d
            if board_3d.get("width"):
                data.board_width_mm = board_3d["width"]
            if board_3d.get("depth"):
                data.board_height_mm = board_3d["depth"]
            if board_3d.get("thickness"):
                data.board_thickness_mm = board_3d["thickness"]
            sid = existing_sid
        else:
            # Create new session from STEP data
            data = parse_pcb_file(args["file_path"], format_hint="step")
            sid = sessions.create_session(data)
        return {
            "success": True,
            "session_id": sid,
            "board_3d": board_3d,
            "component_count": len(step_components),
            "components": [
                {"reference": c["reference"], "height": c.get("height", 0)}
                for c in step_components[:50]
            ],
            "warnings": result.get("warnings", []),
        }

    if name == "pcb_get_3d_clearances":
        from .parsers.step_parser import compute_3d_clearances
        data = _get_session(args["session_id"])
        if not data.step_components and not data.board_3d:
            raise ValueError("No STEP/3D data in session. Use pcb_parse_step first.")
        result = compute_3d_clearances(data.board_3d, data.step_components)
        return result

    if name == "pcb_check_enclosure_fit":
        from .parsers.step_parser import check_enclosure_fit
        data = _get_session(args["session_id"])
        if not data.board_3d:
            raise ValueError("No STEP/3D data in session. Use pcb_parse_step first.")
        result = check_enclosure_fit(
            board_3d=data.board_3d,
            step_components=data.step_components,
            enclosure_width_mm=args["enclosure_width_mm"],
            enclosure_depth_mm=args["enclosure_depth_mm"],
            enclosure_height_mm=args["enclosure_height_mm"],
            clearance_mm=args.get("clearance_mm", 1.0),
        )
        return result

    # === VISUALIZATION ===
    if name == "pcb_render_board":
        from .visualization.board_renderer import BoardRenderer
        data = _get_session(args["session_id"])
        width_px = args.get("width_px", 800)
        renderer = BoardRenderer(data, width_px=width_px)
        svg = renderer.render_board(
            layers=args.get("layers"),
            highlight_nets=args.get("highlight_nets"),
            highlight_components=args.get("highlight_components"),
        )
        return {"svg": svg, "width_px": width_px, "height_px": renderer.height_px}

    if name == "pcb_render_stackup":
        from .visualization.stackup_renderer import StackupRenderer
        data = _get_session(args["session_id"])
        renderer = StackupRenderer(data)  # type: ignore[assignment]
        svg = renderer.render()  # type: ignore[attr-defined]
        return {"svg": svg}

    if name == "pcb_render_net":
        from .visualization.board_renderer import BoardRenderer
        data = _get_session(args["session_id"])
        renderer = BoardRenderer(data)
        svg = renderer.render_net(args["net_name"])
        return {"svg": svg, "net_name": args["net_name"]}

    if name == "pcb_annotate_board":
        from .visualization.annotator import Annotator
        data = _get_session(args["session_id"])
        annotator = Annotator(data)
        svg = annotator.render_annotated_board(annotations=args["annotations"])
        return {"svg": svg, "annotation_count": len(args["annotations"])}

    # === EXPORT / RENDER TO FILE ===
    if name == "pcb_export_render_png":
        from .visualization.exporter import svg_to_png
        data = _get_session(args["session_id"])
        render_type = args["render_type"]
        width_px = args.get("width_px", 1600)
        output_path = args.get("output_path")

        if render_type == "board":
            from .visualization.board_renderer import BoardRenderer
            renderer = BoardRenderer(data, width_px=width_px)
            svg = renderer.render_board(
                highlight_nets=args.get("highlight_nets"),
                highlight_components=args.get("highlight_components"),
            )
        elif render_type == "stackup":
            from .visualization.stackup_renderer import StackupRenderer
            renderer = StackupRenderer(data)  # type: ignore[assignment]
            svg = renderer.render()  # type: ignore[attr-defined]
        elif render_type == "net":
            net_name = args.get("net_name")
            if not net_name:
                return {"success": False, "error": "net_name required for render_type='net'"}
            from .visualization.board_renderer import BoardRenderer
            renderer = BoardRenderer(data)
            svg = renderer.render_net(net_name)
        elif render_type == "annotated":
            annots = args.get("annotations", [])
            if not annots:
                return {"success": False, "error": "annotations required for render_type='annotated'"}
            from .visualization.annotator import Annotator
            annotator = Annotator(data)
            svg = annotator.render_annotated_board(annotations=annots)
        else:
            return {"success": False, "error": f"Unknown render_type: {render_type}"}

        png_path = svg_to_png(svg, output_path, width=width_px)
        import os
        return {
            "success": True,
            "output_path": png_path,
            "file_size_bytes": os.path.getsize(png_path),
            "render_type": render_type,
        }

    if name == "pcb_export_all_renders":
        from .reports.docx_report import generate_all_renders
        data = _get_session(args["session_id"])
        output_dir = args["output_dir"]
        width_px = args.get("width_px", 1600)
        render_map = generate_all_renders(data, args["session_id"], output_dir, width_px)
        return {
            "success": True,
            "output_dir": output_dir,
            "renders": render_map,
            "count": len(render_map),
        }

    if name == "pcb_generate_docx_report":
        from .reports.docx_report import generate_docx_report, generate_all_renders
        data = _get_session(args["session_id"])
        image_dir = args.get("image_dir")
        output_path = args.get("output_path")

        # Auto-generate renders if no image_dir provided
        if not image_dir:
            import tempfile
            image_dir = tempfile.mkdtemp(prefix="pcb_report_images_")
            generate_all_renders(data, args["session_id"], image_dir)

        docx_path = generate_docx_report(
            design=data,
            session_id=args["session_id"],
            output_path=output_path,
            image_dir=image_dir,
            title=args.get("title", "PCB Design Review Report"),
            subtitle=args.get("subtitle", ""),
        )
        import os
        return {
            "success": True,
            "output_path": docx_path,
            "file_size_bytes": os.path.getsize(docx_path),
            "image_dir": image_dir,
        }

    # === SCHEMATIC PDF ===
    if name == "pcb_parse_schematic_pdf":
        from .parsers.pdf_schematic_parser import PDFSchematicParser

        parser = PDFSchematicParser()  # type: ignore[assignment]
        pdf_result = parser.parse(args["file_path"])  # type: ignore[attr-defined]

        page_dicts = []
        for pg in pdf_result.pages:
            page_dicts.append({
                "page_number": pg.page_number,
                "text": pg.text,
                "components": pg.components,
                "nets": pg.nets,
                "width_pts": pg.width_pts,
                "height_pts": pg.height_pts,
            })

        session_id = args.get("session_id")
        if session_id:
            data = _get_session(session_id)
            data.schematic_components = pdf_result.components
            data.schematic_nets = pdf_result.nets
            data.schematic_pages = page_dicts
            data.schematic_pdf_path = pdf_result.file_path
        else:
            from .models.pcb_data import PCBDesignData
            data = PCBDesignData(
                source_file=args["file_path"],
                source_format="schematic_pdf",
                schematic_components=pdf_result.components,
                schematic_nets=pdf_result.nets,
                schematic_pages=page_dicts,
                schematic_pdf_path=pdf_result.file_path,
            )
            session_id = sessions.create_session(data)

        return {
            "success": True,
            "session_id": session_id,
            **pdf_result.to_summary(),
        }

    if name == "pcb_get_schematic_page":
        data = _get_session(args["session_id"])
        page_number = args["page_number"]

        if not data.schematic_pages:
            raise ValueError("No schematic PDF data in this session. Use pcb_parse_schematic_pdf first.")

        if page_number < 1 or page_number > len(data.schematic_pages):
            raise ValueError(f"Page {page_number} out of range (1-{len(data.schematic_pages)})")

        page = data.schematic_pages[page_number - 1]
        result = {
            "page_number": page["page_number"],
            "text": page.get("text", ""),
            "components": page.get("components", []),
            "nets": page.get("nets", []),
            "component_count": len(page.get("components", [])),
            "net_count": len(page.get("nets", [])),
            "width_pts": page.get("width_pts", 0),
            "height_pts": page.get("height_pts", 0),
        }

        if args.get("render_image") and data.schematic_pdf_path:
            from .parsers.pdf_schematic_parser import PDFSchematicParser
            import tempfile
            parser = PDFSchematicParser()  # type: ignore[assignment]
            output_dir = tempfile.mkdtemp(prefix="pcb_schematic_")
            image_path = parser.render_page_image(  # type: ignore[attr-defined]
                data.schematic_pdf_path, page_number, output_dir
            )
            if image_path:
                result["image_path"] = image_path
            else:
                result["image_note"] = "PyMuPDF not installed. Cannot render page image."

        return result

    if name == "pcb_cross_reference_schematic":
        from .analyzers.validation.schematic_layout_validator import SchematicLayoutValidator
        data = _get_session(args["session_id"])

        if not data.schematic_components:
            raise ValueError(
                "No schematic data in this session. "
                "Use pcb_parse_schematic_pdf (with session_id) to attach schematic data first."
            )
        if not data.components:
            raise ValueError(
                "No layout data in this session. "
                "Use pcb_parse_layout to load a PCB layout first, then attach schematic data."
            )

        validator = SchematicLayoutValidator()
        validation = validator.validate(data)

        return {
            "total_schematic_components": validation.total_schematic_components,
            "total_layout_components": validation.total_layout_components,
            "matching_components": validation.matching_components,
            "match_percentage": round(validation.calculate_match_percentage(), 1),
            "errors": validation.errors,
            "warnings": validation.warnings,
            "component_mismatches": [_serialize(m) for m in validation.component_mismatches],
            "net_mismatches": [_serialize(m) for m in validation.net_mismatches],
        }

    # === DESIGN REVIEW ORCHESTRATION ===
    if name == "pcb_set_review_context":
        from .orchestrator import set_review_context
        data = _get_session(args["session_id"])
        ctx = set_review_context(
            design=data,
            design_intent=args.get("design_intent", ""),
            target_standards=args.get("target_standards"),
            known_issues=args.get("known_issues"),
            impedance_targets=args.get("impedance_targets"),
            thermal_limits=args.get("thermal_limits"),
            operating_conditions=args.get("operating_conditions"),
        )
        return {"success": True, "session_id": args["session_id"], "review_context": ctx}

    if name == "pcb_run_design_review":
        from .orchestrator import run_design_review
        data = _get_session(args["session_id"])
        result = run_design_review(data, args["session_id"])
        return result.to_dict()

    if name == "pcb_generate_report":
        from .orchestrator import generate_report
        data = _get_session(args["session_id"])
        report = generate_report(data, args["session_id"], args.get("format", "detailed"))
        return report

    # === RETURN CURRENT / GROUND STITCHING ===
    if name == "pcb_analyze_return_current":
        from .analyzers.emc.current_density import calculate_return_current_density
        return calculate_return_current_density(
            trace_height_mm=args["trace_height_mm"],
            signal_current_ma=args.get("signal_current_ma", 100.0),
            analysis_width_mm=args.get("analysis_width_mm", 20.0),
            num_points=args.get("num_points", 100),
        )

    if name == "pcb_analyze_ground_stitch":
        from .analyzers.emc.current_density import calculate_ground_stitch_spacing
        return calculate_ground_stitch_spacing(
            max_frequency_hz=args["max_frequency_hz"],
            dielectric_constant=args.get("dielectric_constant", 4.3),
            trace_height_mm=args.get("trace_height_mm", 0.1),
            target_containment_percent=args.get("target_containment_percent", 90.0),
            lambda_fraction=args.get("lambda_fraction", 20.0),
        )

    # === CLOCK / SMPS EMI ===
    if name == "pcb_analyze_clock_emi":
        from .analyzers.emc.clock_emi_analyzer import calculate_clock_emi
        return calculate_clock_emi(
            clock_frequency_mhz=args["clock_frequency_mhz"],
            rise_time_ns=args.get("rise_time_ns", 1.0),
            voltage_swing_v=args.get("voltage_swing_v", 3.3),
            duty_cycle=args.get("duty_cycle", 0.5),
            num_harmonics=args.get("num_harmonics", 20),
            ssc_enabled=args.get("ssc_enabled", False),
            ssc_deviation_percent=args.get("ssc_deviation_percent", 0.5),
            trace_length_mm=args.get("trace_length_mm", 50.0),
            limit_standard=args.get("limit_standard", "fcc_classb"),
        )

    if name == "pcb_analyze_smps_emi":
        from .analyzers.emc.clock_emi_analyzer import calculate_smps_emi
        return calculate_smps_emi(
            switching_frequency_khz=args["switching_frequency_khz"],
            duty_cycle=args.get("duty_cycle", 0.5),
            input_voltage_v=args.get("input_voltage_v", 12.0),
            output_voltage_v=args.get("output_voltage_v", 3.3),
            output_current_a=args.get("output_current_a", 2.0),
            rise_time_ns=args.get("rise_time_ns", 10.0),
            inductor_value_uh=args.get("inductor_value_uh", 4.7),
            num_harmonics=args.get("num_harmonics", 30),
            pcb_loop_area_cm2=args.get("pcb_loop_area_cm2", 1.0),
            limit_standard=args.get("limit_standard", "cispr32_classb"),
        )

    # === SESSION MANAGEMENT ===
    if name == "pcb_list_sessions":
        return {"sessions": sessions.list_sessions(), "count": sessions.session_count}
    if name == "pcb_close_session":
        closed = sessions.close_session(args["session_id"])
        return {"closed": closed, "session_id": args["session_id"]}

    raise ValueError(f"Unknown tool: {name}")


def _get_session(session_id: str) -> PCBDesignData:
    """Get session or raise SessionError."""
    data = sessions.get_session(session_id)
    if data is None:
        raise SessionError(
            "INVALID_SESSION",
            f"No active session with ID '{session_id}'. Use pcb_parse_layout to create one first.",
            {"session_id": session_id},
        )
    return data


def main() -> None:
    """Run the MCP server."""
    async def run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    asyncio.run(run())


if __name__ == "__main__":
    main()

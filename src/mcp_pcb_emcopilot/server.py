#!/usr/bin/env python3
"""MCP server for PCB design review, EMC analysis, and signal integrity.

This server provides tools for PCB engineers to analyze:
- Impedance (microstrip, stripline, differential pairs)
- Signal integrity (timing, crosstalk, via transitions)
- EMC compliance (current loops, emissions estimation)
- Design rule checking (trace widths, clearances)

Usage:
    python -m mcp_pcb_emcopilot.server
"""

import asyncio
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Physical constants
C0 = 299792458.0  # Speed of light in m/s
MU0 = 4 * math.pi * 1e-7  # Permeability of free space
EPS0 = 8.854e-12  # Permittivity of free space


# =============================================================================
# Data Models
# =============================================================================


class TraceType(str, Enum):
    MICROSTRIP = "microstrip"
    STRIPLINE = "stripline"
    COPLANAR = "coplanar"
    DIFFERENTIAL = "differential"


class ViaType(str, Enum):
    THROUGH = "through"
    BLIND = "blind"
    BURIED = "buried"
    MICROVIA = "microvia"


@dataclass
class ImpedanceResult:
    """Result of impedance calculation."""
    impedance_ohms: float
    effective_er: float
    propagation_delay_ps_per_inch: float
    trace_type: str
    parameters: dict


@dataclass
class TimingResult:
    """Result of timing analysis."""
    propagation_delay_ps: float
    rise_time_ps: float
    setup_margin_ps: float
    hold_margin_ps: float
    valid: bool
    issues: list[str]


@dataclass
class CrosstalkResult:
    """Result of crosstalk analysis."""
    near_end_xtalk_percent: float
    far_end_xtalk_percent: float
    coupling_length_mm: float
    spacing_mm: float
    severity: str
    recommendations: list[str]


# =============================================================================
# Impedance Calculations
# =============================================================================


def calc_microstrip_impedance(
    trace_width_mm: float,
    dielectric_height_mm: float,
    trace_thickness_mm: float,
    dielectric_constant: float,
) -> ImpedanceResult:
    """Calculate microstrip impedance using IPC-2141 formulas."""
    w = trace_width_mm
    h = dielectric_height_mm
    t = trace_thickness_mm
    er = dielectric_constant

    # Effective width accounting for trace thickness
    w_eff = w + (t / math.pi) * math.log(4 * math.e / math.sqrt((t / h) ** 2 + (t / (math.pi * (w + 1.1 * t))) ** 2))

    # Effective dielectric constant
    f_w_h = (1 + 12 * h / w_eff) ** (-0.5)
    er_eff = (er + 1) / 2 + (er - 1) / 2 * f_w_h

    # Characteristic impedance
    if w_eff / h <= 1:
        z0 = (60 / math.sqrt(er_eff)) * math.log(8 * h / w_eff + 0.25 * w_eff / h)
    else:
        z0 = (120 * math.pi) / (math.sqrt(er_eff) * (w_eff / h + 1.393 + 0.667 * math.log(w_eff / h + 1.444)))

    # Propagation delay (ps/inch)
    delay_ps_per_inch = 84.72 * math.sqrt(er_eff)

    return ImpedanceResult(
        impedance_ohms=round(z0, 2),
        effective_er=round(er_eff, 3),
        propagation_delay_ps_per_inch=round(delay_ps_per_inch, 2),
        trace_type="microstrip",
        parameters={
            "trace_width_mm": w,
            "dielectric_height_mm": h,
            "trace_thickness_mm": t,
            "dielectric_constant": er,
            "effective_width_mm": round(w_eff, 4),
        }
    )


def calc_stripline_impedance(
    trace_width_mm: float,
    dielectric_height_mm: float,
    trace_thickness_mm: float,
    dielectric_constant: float,
) -> ImpedanceResult:
    """Calculate stripline (buried trace) impedance."""
    w = trace_width_mm
    b = dielectric_height_mm * 2  # Total distance between ground planes
    t = trace_thickness_mm
    er = dielectric_constant

    # Effective width
    w_eff = w if t == 0 else w + (t / math.pi) * (1 + math.log(4 * math.pi * w / t))

    # For centered stripline
    if w_eff / b <= 0.35:
        z0 = (60 / math.sqrt(er)) * math.log(4 * b / (0.67 * math.pi * (0.8 * w_eff + t)))
    else:
        z0 = (94.15 / math.sqrt(er)) / (w_eff / b + (2 / math.pi) * math.log((math.e * math.pi / 2) * (w_eff / b + 0.94)))

    # Propagation delay
    delay_ps_per_inch = 84.72 * math.sqrt(er)

    return ImpedanceResult(
        impedance_ohms=round(z0, 2),
        effective_er=round(er, 3),
        propagation_delay_ps_per_inch=round(delay_ps_per_inch, 2),
        trace_type="stripline",
        parameters={
            "trace_width_mm": w,
            "dielectric_height_mm": dielectric_height_mm,
            "total_stackup_height_mm": b,
            "trace_thickness_mm": t,
            "dielectric_constant": er,
        }
    )


def calc_differential_impedance(
    trace_width_mm: float,
    trace_spacing_mm: float,
    dielectric_height_mm: float,
    trace_thickness_mm: float,
    dielectric_constant: float,
    trace_type: str = "microstrip",
) -> ImpedanceResult:
    """Calculate differential pair impedance."""
    # First calculate single-ended impedance
    if trace_type == "microstrip":
        single = calc_microstrip_impedance(trace_width_mm, dielectric_height_mm, trace_thickness_mm, dielectric_constant)
    else:
        single = calc_stripline_impedance(trace_width_mm, dielectric_height_mm, trace_thickness_mm, dielectric_constant)

    z0 = single.impedance_ohms
    s = trace_spacing_mm
    h = dielectric_height_mm
    w = trace_width_mm

    # Coupling factor
    if trace_type == "microstrip":
        # Microstrip differential coupling
        k_odd = math.exp(-1.0 * s / h)
        z_diff = 2 * z0 * (1 - 0.48 * math.exp(-0.96 * s / h))
    else:
        # Stripline differential coupling
        k_odd = math.exp(-2.0 * s / h)
        z_diff = 2 * z0 * math.sqrt(1 - k_odd ** 2)

    return ImpedanceResult(
        impedance_ohms=round(z_diff, 2),
        effective_er=single.effective_er,
        propagation_delay_ps_per_inch=single.propagation_delay_ps_per_inch,
        trace_type=f"differential_{trace_type}",
        parameters={
            "trace_width_mm": w,
            "trace_spacing_mm": s,
            "dielectric_height_mm": h,
            "trace_thickness_mm": trace_thickness_mm,
            "dielectric_constant": dielectric_constant,
            "single_ended_z0": z0,
        }
    )


# =============================================================================
# Trace Width Calculator
# =============================================================================


def calc_trace_width_for_current(
    current_amps: float,
    temp_rise_c: float,
    copper_thickness_oz: float,
    layer_type: str = "external",
) -> dict:
    """Calculate required trace width for a given current (IPC-2221)."""
    # Convert oz/ft² to mils
    thickness_mils = copper_thickness_oz * 1.37

    # IPC-2221 constants
    if layer_type == "external":
        k = 0.048
        b = 0.44
        c = 0.725
    else:  # internal
        k = 0.024
        b = 0.44
        c = 0.725

    # Cross-sectional area in mils²
    area = (current_amps / (k * (temp_rise_c ** b))) ** (1 / c)

    # Width in mils
    width_mils = area / thickness_mils
    width_mm = width_mils * 0.0254

    return {
        "success": True,
        "trace_width_mm": round(width_mm, 3),
        "trace_width_mils": round(width_mils, 1),
        "cross_section_mils2": round(area, 1),
        "current_amps": current_amps,
        "temp_rise_c": temp_rise_c,
        "copper_oz": copper_thickness_oz,
        "layer_type": layer_type,
        "standard": "IPC-2221",
    }


# =============================================================================
# Signal Integrity Analysis
# =============================================================================


def analyze_trace_timing(
    trace_length_mm: float,
    effective_er: float,
    data_rate_gbps: float,
    rise_time_ps: float,
    setup_time_ps: float,
    hold_time_ps: float,
) -> TimingResult:
    """Analyze timing margins for a trace."""
    # Propagation delay
    prop_delay_ps_per_mm = (1000 / C0) * math.sqrt(effective_er) * 1e12
    total_delay_ps = trace_length_mm * prop_delay_ps_per_mm

    # Unit interval
    ui_ps = 1e12 / (data_rate_gbps * 1e9)

    # Timing margins
    setup_margin = ui_ps - total_delay_ps - setup_time_ps - rise_time_ps / 2
    hold_margin = total_delay_ps - hold_time_ps + rise_time_ps / 2

    issues = []
    if setup_margin < 0:
        issues.append(f"Setup timing violated by {-setup_margin:.1f} ps")
    if hold_margin < 0:
        issues.append(f"Hold timing violated by {-hold_margin:.1f} ps")
    if total_delay_ps > ui_ps * 0.7:
        issues.append("Propagation delay > 70% of UI, consider shorter trace")

    return TimingResult(
        propagation_delay_ps=round(total_delay_ps, 1),
        rise_time_ps=rise_time_ps,
        setup_margin_ps=round(setup_margin, 1),
        hold_margin_ps=round(hold_margin, 1),
        valid=len(issues) == 0,
        issues=issues,
    )


def analyze_crosstalk(
    trace_spacing_mm: float,
    trace_width_mm: float,
    dielectric_height_mm: float,
    coupling_length_mm: float,
    rise_time_ps: float,
) -> CrosstalkResult:
    """Analyze crosstalk between parallel traces."""
    s = trace_spacing_mm
    w = trace_width_mm
    h = dielectric_height_mm
    l = coupling_length_mm

    # Simplified crosstalk model (3W rule basis)
    # NEXT (near-end) and FEXT (far-end) estimation
    coupling_factor = math.exp(-2 * s / h)

    # Near-end crosstalk (backward)
    next_percent = 25 * coupling_factor * min(l / 25.4, 1.0)  # Saturates at ~1 inch

    # Far-end crosstalk (forward) - depends on rise time
    # Critical length for FEXT
    rise_time_s = rise_time_ps * 1e-12
    critical_length_m = (C0 / 2) * rise_time_s / math.sqrt(4.0)  # Assume Er=4
    critical_length_mm = critical_length_m * 1000

    if l > critical_length_mm:
        fext_percent = 15 * coupling_factor * (l / critical_length_mm)
    else:
        fext_percent = 15 * coupling_factor

    # Determine severity
    max_xtalk = max(next_percent, fext_percent)
    if max_xtalk > 15:
        severity = "critical"
    elif max_xtalk > 10:
        severity = "warning"
    elif max_xtalk > 5:
        severity = "marginal"
    else:
        severity = "acceptable"

    recommendations = []
    if max_xtalk > 5:
        min_spacing = 3 * w  # 3W rule
        if s < min_spacing:
            recommendations.append(f"Increase spacing to {min_spacing:.2f}mm (3W rule)")
        if l > 50:
            recommendations.append("Consider adding ground guard traces")
        if h < s:
            recommendations.append("Consider tighter coupling to reference plane")

    return CrosstalkResult(
        near_end_xtalk_percent=round(next_percent, 2),
        far_end_xtalk_percent=round(fext_percent, 2),
        coupling_length_mm=l,
        spacing_mm=s,
        severity=severity,
        recommendations=recommendations,
    )


# =============================================================================
# Via Analysis
# =============================================================================


def analyze_via(
    via_diameter_mm: float,
    via_length_mm: float,
    pad_diameter_mm: float,
    antipad_diameter_mm: float,
    dielectric_constant: float,
    frequency_ghz: float,
) -> dict:
    """Analyze via electrical characteristics."""
    # Via inductance (simplified model)
    d = via_diameter_mm
    h = via_length_mm

    # Inductance in nH (simplified cylindrical model)
    inductance_nh = 5.08 * h * (math.log(4 * h / d) + 1)

    # Via capacitance
    d_pad = pad_diameter_mm
    d_anti = antipad_diameter_mm
    er = dielectric_constant

    # Capacitance in pF
    capacitance_pf = 1.41 * er * h * d_pad / (d_anti - d_pad)

    # Characteristic impedance of via
    z_via = math.sqrt(inductance_nh / capacitance_pf) * 1000  # Convert to ohms

    # Resonant frequency
    f_res_ghz = 1 / (2 * math.pi * math.sqrt(inductance_nh * 1e-9 * capacitance_pf * 1e-12)) / 1e9

    # Insertion loss estimate at given frequency
    f = frequency_ghz * 1e9
    omega = 2 * math.pi * f
    xl = omega * inductance_nh * 1e-9
    xc = 1 / (omega * capacitance_pf * 1e-12)

    # Simple S21 estimate
    z_net = abs(xl - xc)
    s21_db = -20 * math.log10(1 + z_net / 100)  # Assuming 50 ohm system

    issues = []
    if z_via < 30 or z_via > 70:
        issues.append(f"Via impedance {z_via:.1f} ohms deviates significantly from 50 ohms")
    if f_res_ghz < frequency_ghz * 3:
        issues.append(f"Via resonance at {f_res_ghz:.2f} GHz is close to operating frequency")

    return {
        "success": True,
        "inductance_nh": round(inductance_nh, 3),
        "capacitance_pf": round(capacitance_pf, 3),
        "characteristic_impedance_ohms": round(z_via, 1),
        "resonant_frequency_ghz": round(f_res_ghz, 2),
        "insertion_loss_db": round(s21_db, 2),
        "issues": issues,
        "via_type": "through",
        "parameters": {
            "via_diameter_mm": d,
            "via_length_mm": h,
            "pad_diameter_mm": d_pad,
            "antipad_diameter_mm": d_anti,
            "dielectric_constant": er,
            "frequency_ghz": frequency_ghz,
        }
    }


# =============================================================================
# EMC Analysis
# =============================================================================


def analyze_current_loop(
    loop_area_mm2: float,
    current_ma: float,
    frequency_mhz: float,
) -> dict:
    """Analyze EMI from current loop (differential mode emissions)."""
    # Convert to SI units
    area_m2 = loop_area_mm2 * 1e-6
    current_a = current_ma * 1e-3
    freq_hz = frequency_mhz * 1e6

    # Far-field electric field at 3m (FCC limit reference)
    distance = 3.0  # meters
    wavelength = C0 / freq_hz

    # E-field magnitude (V/m) for small loop
    # E = (120 * pi^2 * I * A * f^2) / (c^2 * r)
    e_field = (120 * math.pi ** 2 * current_a * area_m2 * freq_hz ** 2) / (C0 ** 2 * distance)

    # Convert to dBuV/m
    e_field_dbuv = 20 * math.log10(e_field * 1e6)

    # FCC Class B limit at various frequencies (approximate)
    if frequency_mhz < 88:
        limit_dbuv = 40
    elif frequency_mhz < 216:
        limit_dbuv = 43.5
    elif frequency_mhz < 960:
        limit_dbuv = 46
    else:
        limit_dbuv = 54

    margin_db = limit_dbuv - e_field_dbuv

    recommendations = []
    if margin_db < 6:
        recommendations.append("Reduce loop area by routing signal and return paths closer together")
        recommendations.append("Consider adding bypass capacitors near high-frequency sources")
    if margin_db < 0:
        recommendations.append("CRITICAL: Estimated emissions exceed FCC Class B limit")
        recommendations.append("Add EMI filter or shield")

    return {
        "success": True,
        "e_field_dbuv_m": round(e_field_dbuv, 1),
        "fcc_class_b_limit_dbuv_m": limit_dbuv,
        "margin_db": round(margin_db, 1),
        "compliant": margin_db > 0,
        "margin_acceptable": margin_db > 6,
        "recommendations": recommendations,
        "parameters": {
            "loop_area_mm2": loop_area_mm2,
            "current_ma": current_ma,
            "frequency_mhz": frequency_mhz,
            "distance_m": distance,
        }
    }


def estimate_rise_time_bandwidth(rise_time_ps: float) -> dict:
    """Estimate signal bandwidth from rise time."""
    # 3dB bandwidth
    rise_time_s = rise_time_ps * 1e-12
    bw_3db_hz = 0.35 / rise_time_s
    bw_3db_ghz = bw_3db_hz / 1e9

    # 5th harmonic frequency
    f_5th_ghz = 5 * bw_3db_ghz / math.pi

    # Knee frequency (for EMC analysis)
    f_knee_ghz = 1 / (math.pi * rise_time_s) / 1e9

    return {
        "success": True,
        "rise_time_ps": rise_time_ps,
        "bandwidth_3db_ghz": round(bw_3db_ghz, 2),
        "knee_frequency_ghz": round(f_knee_ghz, 2),
        "fifth_harmonic_ghz": round(f_5th_ghz, 2),
        "notes": [
            f"PCB traces should be treated as transmission lines above {bw_3db_ghz/10:.2f} GHz",
            f"EMC concerns extend up to {f_knee_ghz:.2f} GHz",
        ]
    }


# =============================================================================
# MCP Server
# =============================================================================

server = Server("mcp-pcb-emcopilot")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available PCB analysis tools."""
    return [
        # Impedance Tools
        Tool(
            name="pcb_calc_microstrip_impedance",
            description="Calculate microstrip trace impedance using IPC-2141 formulas. Essential for controlled impedance routing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "trace_width_mm": {"type": "number", "description": "Trace width in mm"},
                    "dielectric_height_mm": {"type": "number", "description": "Height from trace to reference plane in mm"},
                    "trace_thickness_mm": {"type": "number", "description": "Copper thickness in mm (1oz = 0.035mm)"},
                    "dielectric_constant": {"type": "number", "description": "Dielectric constant (Er) of PCB material (FR4 ~ 4.3)"},
                },
                "required": ["trace_width_mm", "dielectric_height_mm", "trace_thickness_mm", "dielectric_constant"],
            },
        ),
        Tool(
            name="pcb_calc_stripline_impedance",
            description="Calculate stripline (buried trace between two ground planes) impedance.",
            inputSchema={
                "type": "object",
                "properties": {
                    "trace_width_mm": {"type": "number", "description": "Trace width in mm"},
                    "dielectric_height_mm": {"type": "number", "description": "Distance from trace to nearest ground plane in mm"},
                    "trace_thickness_mm": {"type": "number", "description": "Copper thickness in mm"},
                    "dielectric_constant": {"type": "number", "description": "Dielectric constant (Er)"},
                },
                "required": ["trace_width_mm", "dielectric_height_mm", "trace_thickness_mm", "dielectric_constant"],
            },
        ),
        Tool(
            name="pcb_calc_differential_impedance",
            description="Calculate differential pair impedance for USB, HDMI, Ethernet, etc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "trace_width_mm": {"type": "number", "description": "Width of each trace in mm"},
                    "trace_spacing_mm": {"type": "number", "description": "Gap between traces in mm"},
                    "dielectric_height_mm": {"type": "number", "description": "Height to reference plane in mm"},
                    "trace_thickness_mm": {"type": "number", "description": "Copper thickness in mm"},
                    "dielectric_constant": {"type": "number", "description": "Dielectric constant (Er)"},
                    "trace_type": {"type": "string", "description": "microstrip or stripline", "enum": ["microstrip", "stripline"]},
                },
                "required": ["trace_width_mm", "trace_spacing_mm", "dielectric_height_mm", "trace_thickness_mm", "dielectric_constant"],
            },
        ),
        Tool(
            name="pcb_calc_trace_width",
            description="Calculate minimum trace width for a given current capacity (IPC-2221).",
            inputSchema={
                "type": "object",
                "properties": {
                    "current_amps": {"type": "number", "description": "Current in Amps"},
                    "temp_rise_c": {"type": "number", "description": "Allowable temperature rise in Celsius (typically 10-20C)"},
                    "copper_thickness_oz": {"type": "number", "description": "Copper weight in oz/ft² (1oz, 2oz, etc.)"},
                    "layer_type": {"type": "string", "description": "external or internal", "enum": ["external", "internal"]},
                },
                "required": ["current_amps", "temp_rise_c", "copper_thickness_oz"],
            },
        ),
        # Signal Integrity Tools
        Tool(
            name="pcb_analyze_timing",
            description="Analyze timing margins for high-speed signals (setup/hold times).",
            inputSchema={
                "type": "object",
                "properties": {
                    "trace_length_mm": {"type": "number", "description": "Total trace length in mm"},
                    "effective_er": {"type": "number", "description": "Effective dielectric constant (from impedance calc)"},
                    "data_rate_gbps": {"type": "number", "description": "Data rate in Gbps"},
                    "rise_time_ps": {"type": "number", "description": "Signal rise time in ps"},
                    "setup_time_ps": {"type": "number", "description": "Required setup time in ps"},
                    "hold_time_ps": {"type": "number", "description": "Required hold time in ps"},
                },
                "required": ["trace_length_mm", "effective_er", "data_rate_gbps", "rise_time_ps", "setup_time_ps", "hold_time_ps"],
            },
        ),
        Tool(
            name="pcb_analyze_crosstalk",
            description="Analyze crosstalk between parallel traces (NEXT and FEXT).",
            inputSchema={
                "type": "object",
                "properties": {
                    "trace_spacing_mm": {"type": "number", "description": "Edge-to-edge spacing between traces in mm"},
                    "trace_width_mm": {"type": "number", "description": "Trace width in mm"},
                    "dielectric_height_mm": {"type": "number", "description": "Height to reference plane in mm"},
                    "coupling_length_mm": {"type": "number", "description": "Length of parallel run in mm"},
                    "rise_time_ps": {"type": "number", "description": "Signal rise time in ps"},
                },
                "required": ["trace_spacing_mm", "trace_width_mm", "dielectric_height_mm", "coupling_length_mm", "rise_time_ps"],
            },
        ),
        Tool(
            name="pcb_analyze_via",
            description="Analyze via electrical characteristics (inductance, capacitance, impedance).",
            inputSchema={
                "type": "object",
                "properties": {
                    "via_diameter_mm": {"type": "number", "description": "Via hole diameter in mm"},
                    "via_length_mm": {"type": "number", "description": "Via length (board thickness) in mm"},
                    "pad_diameter_mm": {"type": "number", "description": "Via pad diameter in mm"},
                    "antipad_diameter_mm": {"type": "number", "description": "Clearance hole diameter in planes in mm"},
                    "dielectric_constant": {"type": "number", "description": "Board dielectric constant"},
                    "frequency_ghz": {"type": "number", "description": "Operating frequency in GHz"},
                },
                "required": ["via_diameter_mm", "via_length_mm", "pad_diameter_mm", "antipad_diameter_mm", "dielectric_constant", "frequency_ghz"],
            },
        ),
        # EMC Tools
        Tool(
            name="pcb_analyze_current_loop",
            description="Estimate radiated emissions from a current loop for EMC compliance.",
            inputSchema={
                "type": "object",
                "properties": {
                    "loop_area_mm2": {"type": "number", "description": "Current loop area in mm²"},
                    "current_ma": {"type": "number", "description": "Loop current in mA"},
                    "frequency_mhz": {"type": "number", "description": "Frequency in MHz"},
                },
                "required": ["loop_area_mm2", "current_ma", "frequency_mhz"],
            },
        ),
        Tool(
            name="pcb_estimate_bandwidth",
            description="Estimate signal bandwidth and EMC concerns from rise time.",
            inputSchema={
                "type": "object",
                "properties": {
                    "rise_time_ps": {"type": "number", "description": "Signal rise time in picoseconds"},
                },
                "required": ["rise_time_ps"],
            },
        ),
        # Reference Tools
        Tool(
            name="pcb_get_stackup_templates",
            description="Get common PCB stackup templates with typical impedances.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="pcb_get_material_properties",
            description="Get dielectric properties for common PCB materials.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle PCB analysis tool calls."""
    try:
        if name == "pcb_calc_microstrip_impedance":
            res = calc_microstrip_impedance(
                trace_width_mm=arguments["trace_width_mm"],
                dielectric_height_mm=arguments["dielectric_height_mm"],
                trace_thickness_mm=arguments["trace_thickness_mm"],
                dielectric_constant=arguments["dielectric_constant"],
            )
            result = {
                "success": True,
                "impedance_ohms": res.impedance_ohms,
                "effective_er": res.effective_er,
                "propagation_delay_ps_per_inch": res.propagation_delay_ps_per_inch,
                "trace_type": res.trace_type,
                "parameters": res.parameters,
            }

        elif name == "pcb_calc_stripline_impedance":
            res = calc_stripline_impedance(
                trace_width_mm=arguments["trace_width_mm"],
                dielectric_height_mm=arguments["dielectric_height_mm"],
                trace_thickness_mm=arguments["trace_thickness_mm"],
                dielectric_constant=arguments["dielectric_constant"],
            )
            result = {
                "success": True,
                "impedance_ohms": res.impedance_ohms,
                "effective_er": res.effective_er,
                "propagation_delay_ps_per_inch": res.propagation_delay_ps_per_inch,
                "trace_type": res.trace_type,
                "parameters": res.parameters,
            }

        elif name == "pcb_calc_differential_impedance":
            res = calc_differential_impedance(
                trace_width_mm=arguments["trace_width_mm"],
                trace_spacing_mm=arguments["trace_spacing_mm"],
                dielectric_height_mm=arguments["dielectric_height_mm"],
                trace_thickness_mm=arguments["trace_thickness_mm"],
                dielectric_constant=arguments["dielectric_constant"],
                trace_type=arguments.get("trace_type", "microstrip"),
            )
            result = {
                "success": True,
                "differential_impedance_ohms": res.impedance_ohms,
                "effective_er": res.effective_er,
                "propagation_delay_ps_per_inch": res.propagation_delay_ps_per_inch,
                "trace_type": res.trace_type,
                "parameters": res.parameters,
            }

        elif name == "pcb_calc_trace_width":
            result = calc_trace_width_for_current(
                current_amps=arguments["current_amps"],
                temp_rise_c=arguments["temp_rise_c"],
                copper_thickness_oz=arguments["copper_thickness_oz"],
                layer_type=arguments.get("layer_type", "external"),
            )

        elif name == "pcb_analyze_timing":
            res = analyze_trace_timing(
                trace_length_mm=arguments["trace_length_mm"],
                effective_er=arguments["effective_er"],
                data_rate_gbps=arguments["data_rate_gbps"],
                rise_time_ps=arguments["rise_time_ps"],
                setup_time_ps=arguments["setup_time_ps"],
                hold_time_ps=arguments["hold_time_ps"],
            )
            result = {
                "success": True,
                "propagation_delay_ps": res.propagation_delay_ps,
                "setup_margin_ps": res.setup_margin_ps,
                "hold_margin_ps": res.hold_margin_ps,
                "timing_valid": res.valid,
                "issues": res.issues,
            }

        elif name == "pcb_analyze_crosstalk":
            res = analyze_crosstalk(
                trace_spacing_mm=arguments["trace_spacing_mm"],
                trace_width_mm=arguments["trace_width_mm"],
                dielectric_height_mm=arguments["dielectric_height_mm"],
                coupling_length_mm=arguments["coupling_length_mm"],
                rise_time_ps=arguments["rise_time_ps"],
            )
            result = {
                "success": True,
                "near_end_crosstalk_percent": res.near_end_xtalk_percent,
                "far_end_crosstalk_percent": res.far_end_xtalk_percent,
                "severity": res.severity,
                "recommendations": res.recommendations,
            }

        elif name == "pcb_analyze_via":
            result = analyze_via(
                via_diameter_mm=arguments["via_diameter_mm"],
                via_length_mm=arguments["via_length_mm"],
                pad_diameter_mm=arguments["pad_diameter_mm"],
                antipad_diameter_mm=arguments["antipad_diameter_mm"],
                dielectric_constant=arguments["dielectric_constant"],
                frequency_ghz=arguments["frequency_ghz"],
            )

        elif name == "pcb_analyze_current_loop":
            result = analyze_current_loop(
                loop_area_mm2=arguments["loop_area_mm2"],
                current_ma=arguments["current_ma"],
                frequency_mhz=arguments["frequency_mhz"],
            )

        elif name == "pcb_estimate_bandwidth":
            result = estimate_rise_time_bandwidth(
                rise_time_ps=arguments["rise_time_ps"],
            )

        elif name == "pcb_get_stackup_templates":
            result = {
                "success": True,
                "stackup_templates": [
                    {
                        "name": "2-layer FR4",
                        "layers": ["Signal/GND", "Signal/Power"],
                        "thickness_mm": 1.6,
                        "typical_z0": "50-60 ohms microstrip",
                    },
                    {
                        "name": "4-layer standard",
                        "layers": ["Signal", "GND", "Power", "Signal"],
                        "thickness_mm": 1.6,
                        "typical_z0": "50 ohms microstrip, 40-45 ohms stripline",
                        "notes": "Good for most designs, solid ground reference",
                    },
                    {
                        "name": "6-layer high-speed",
                        "layers": ["Signal", "GND", "Signal", "Signal", "Power", "Signal"],
                        "thickness_mm": 1.6,
                        "typical_z0": "50 ohms single-ended, 90-100 ohms differential",
                        "notes": "USB 2.0/3.0, HDMI, Ethernet",
                    },
                    {
                        "name": "8-layer DDR4",
                        "layers": ["Signal", "GND", "Signal", "GND", "Power", "Signal", "GND", "Signal"],
                        "thickness_mm": 1.6,
                        "typical_z0": "40 ohms DDR4",
                        "notes": "Optimized for DDR4 memory interfaces",
                    },
                ],
            }

        elif name == "pcb_get_material_properties":
            result = {
                "success": True,
                "materials": [
                    {"name": "FR4 (standard)", "er": 4.3, "loss_tangent": 0.02, "tg_c": 130, "notes": "General purpose, <3 GHz"},
                    {"name": "High-Tg FR4", "er": 4.2, "loss_tangent": 0.018, "tg_c": 170, "notes": "Lead-free assembly compatible"},
                    {"name": "Rogers RO4003C", "er": 3.55, "loss_tangent": 0.0027, "tg_c": 280, "notes": "RF/microwave, <10 GHz"},
                    {"name": "Rogers RO4350B", "er": 3.48, "loss_tangent": 0.0037, "tg_c": 280, "notes": "RF/microwave, good thermal"},
                    {"name": "Isola I-Speed", "er": 3.6, "loss_tangent": 0.007, "tg_c": 200, "notes": "High-speed digital, >10 Gbps"},
                    {"name": "Megtron 6", "er": 3.4, "loss_tangent": 0.002, "tg_c": 185, "notes": "Very low loss, 25+ Gbps"},
                    {"name": "Polyimide (Flex)", "er": 3.4, "loss_tangent": 0.002, "tg_c": 250, "notes": "Flexible circuits"},
                ],
            }

        else:
            result = {"success": False, "error": f"Unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        error_result = {"success": False, "error": str(e)}
        return [TextContent(type="text", text=json.dumps(error_result))]


def main():
    """Run the MCP server."""
    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()

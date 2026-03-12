#!/usr/bin/env python3
"""MCP server for PCB design review, EMC analysis, and signal integrity.

Provides ~45 tools for PCB engineers covering:
- File parsing (KiCad, ODB++, Gerber, Altium, IPC-2581)
- Impedance (microstrip, stripline, differential pairs)
- Signal integrity (timing, crosstalk, via transitions)
- EMC compliance (current loops, emissions, shielding, grounding, ESD)
- High-speed digital (DDR, PCIe, USB, Ethernet, length matching)
- Power integrity (PDN, decoupling, VRM)
- DFM (solder paste, placement, assembly, tolerance)
- Thermal (power dissipation, hotspot, copper spreading, thermal via)
- Antenna/EMI (trace antenna, slot, common mode, cable coupling)
- Design validation (cross-validation, BOM, schematic-layout)
- Session management

Claude Code acts as the AI orchestrator — this server provides the computational tools.
"""

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
from .parsers import parse_pcb_file, detect_format

# Physical constants
C0 = 299792458.0
MU0 = 4 * math.pi * 1e-7
EPS0 = 8.854e-12

server = Server("mcp-pcb-emcopilot")
sessions = DesignSessionManager()


# =============================================================================
# Original calculation functions (preserved for regression compatibility)
# =============================================================================

def calc_microstrip_impedance(trace_width_mm, dielectric_height_mm, trace_thickness_mm, dielectric_constant):
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


def calc_stripline_impedance(trace_width_mm, dielectric_height_mm, trace_thickness_mm, dielectric_constant):
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


def calc_differential_impedance(trace_width_mm, trace_spacing_mm, dielectric_height_mm, trace_thickness_mm, dielectric_constant, trace_type="microstrip"):
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


def calc_trace_width_for_current(current_amps, temp_rise_c, copper_thickness_oz, layer_type="external"):
    thickness_mils = copper_thickness_oz * 1.37
    k = 0.048 if layer_type == "external" else 0.024
    b, c = 0.44, 0.725
    area = (current_amps / (k * (temp_rise_c ** b))) ** (1 / c)
    width_mils = area / thickness_mils
    width_mm = width_mils * 0.0254
    return {"trace_width_mm": round(width_mm, 3), "trace_width_mils": round(width_mils, 1), "cross_section_mils2": round(area, 1), "current_amps": current_amps, "temp_rise_c": temp_rise_c, "copper_oz": copper_thickness_oz, "layer_type": layer_type, "standard": "IPC-2221"}


def analyze_trace_timing(trace_length_mm, effective_er, data_rate_gbps, rise_time_ps, setup_time_ps, hold_time_ps):
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


def analyze_crosstalk(trace_spacing_mm, trace_width_mm, dielectric_height_mm, coupling_length_mm, rise_time_ps):
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


def analyze_via(via_diameter_mm, via_length_mm, pad_diameter_mm, antipad_diameter_mm, dielectric_constant, frequency_ghz):
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


def analyze_current_loop(loop_area_mm2, current_ma, frequency_mhz):
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


def estimate_rise_time_bandwidth(rise_time_ps):
    rise_time_s = rise_time_ps * 1e-12
    bw_3db_ghz = 0.35 / rise_time_s / 1e9
    f_5th_ghz = 5 * bw_3db_ghz / math.pi
    f_knee_ghz = 1 / (math.pi * rise_time_s) / 1e9
    return {"rise_time_ps": rise_time_ps, "bandwidth_3db_ghz": round(bw_3db_ghz, 2), "knee_frequency_ghz": round(f_knee_ghz, 2), "fifth_harmonic_ghz": round(f_5th_ghz, 2), "notes": [f"PCB traces should be treated as transmission lines above {bw_3db_ghz/10:.2f} GHz", f"EMC concerns extend up to {f_knee_ghz:.2f} GHz"]}


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

def _serialize(obj):
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


def _result(data, success=True):
    """Wrap result in standard format."""
    if success:
        if isinstance(data, dict):
            data["success"] = True
        return data
    return {"success": False, "error": str(data)}


# =============================================================================
# Tool definitions
# =============================================================================

def _make_tool(name, desc, props, required=None):
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
            "data_rate_gbps": {"type": "number"}, "target_impedance_ohm": {"type": "number", "description": "Target diff impedance (e.g. 90, 100)"},
        }, ["trace_width_mm", "trace_spacing_mm", "dielectric_height_mm", "dielectric_constant", "data_rate_gbps", "target_impedance_ohm"]),
        _make_tool("pcb_analyze_length_matching", "Analyze trace length matching for a group of signals.", {
            "trace_lengths_mm": {"type": "object", "description": "Dict of net_name: length_mm"},
            "max_skew_ps": {"type": "number", "description": "Maximum allowed skew in ps"},
            "effective_er": {"type": "number", "description": "Effective dielectric constant"},
        }, ["trace_lengths_mm", "max_skew_ps", "effective_er"]),

        # =====================================================================
        # EMC (6 tools)
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

        # =====================================================================
        # HIGH-SPEED DIGITAL (4 tools)
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
        _make_tool("pcb_analyze_usb", "Analyze USB routing.", {
            "usb_version": {"type": "string", "enum": ["2.0", "3.0", "3.1", "3.2", "4.0"]},
            "trace_length_mm": {"type": "number"}, "differential_impedance_ohm": {"type": "number"},
        }, ["usb_version"]),
        _make_tool("pcb_analyze_ethernet", "Analyze Ethernet PHY routing.", {
            "speed": {"type": "string", "enum": ["100M", "1G", "2.5G", "5G", "10G"]},
            "trace_length_mm": {"type": "number"}, "pair_skew_ps": {"type": "number"},
        }, ["speed"]),

        # =====================================================================
        # POWER INTEGRITY (3 tools)
        # =====================================================================
        _make_tool("pcb_analyze_pdn", "Analyze power distribution network impedance.", {
            "target_impedance_mohm": {"type": "number", "description": "Target PDN impedance in milliohms"},
            "supply_voltage_v": {"type": "number"}, "max_current_a": {"type": "number"},
            "ripple_percent": {"type": "number", "description": "Allowed voltage ripple %"},
        }, ["supply_voltage_v", "max_current_a"]),
        _make_tool("pcb_analyze_decoupling", "Analyze decoupling capacitor placement.", {
            "ic_power_pins": {"type": "integer", "description": "Number of power pins on IC"},
            "max_frequency_mhz": {"type": "number"}, "target_impedance_mohm": {"type": "number"},
            "cap_values_uf": {"type": "array", "items": {"type": "number"}, "description": "Capacitor values available"},
        }, ["ic_power_pins", "max_frequency_mhz"]),
        _make_tool("pcb_analyze_vrm", "Analyze VRM placement and routing.", {
            "output_voltage_v": {"type": "number"}, "output_current_a": {"type": "number"},
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
        # REFERENCE DATA (2 tools — original)
        # =====================================================================
        _make_tool("pcb_get_stackup_templates", "Get common PCB stackup templates with typical impedances.", {}, None),
        _make_tool("pcb_get_material_properties", "Get dielectric properties for common PCB materials.", {}, None),

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
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"success": False, "error": str(e)}))]


def _dispatch(name: str, args: dict) -> dict:
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
        widths = {}
        for t in traces:
            w = round(t.width_mm, 3)
            widths[w] = widths.get(w, 0) + 1
        layers_used = list({t.layer for t in traces})
        return {"count": len(traces), "total_trace_length_mm": round(data.total_trace_length_mm, 1), "width_distribution": widths, "layers": layers_used}

    # === IMPEDANCE CALCULATORS ===
    if name == "pcb_calc_microstrip_impedance":
        return _result(calc_microstrip_impedance(args["trace_width_mm"], args["dielectric_height_mm"], args["trace_thickness_mm"], args["dielectric_constant"]))
    if name == "pcb_calc_stripline_impedance":
        return _result(calc_stripline_impedance(args["trace_width_mm"], args["dielectric_height_mm"], args["trace_thickness_mm"], args["dielectric_constant"]))
    if name == "pcb_calc_differential_impedance":
        return _result(calc_differential_impedance(args["trace_width_mm"], args["trace_spacing_mm"], args["dielectric_height_mm"], args["trace_thickness_mm"], args["dielectric_constant"], args.get("trace_type", "microstrip")))
    if name == "pcb_calc_trace_width":
        return _result(calc_trace_width_for_current(args["current_amps"], args["temp_rise_c"], args["copper_thickness_oz"], args.get("layer_type", "external")))

    # === SIGNAL INTEGRITY ===
    if name == "pcb_analyze_timing":
        return _result(analyze_trace_timing(args["trace_length_mm"], args["effective_er"], args["data_rate_gbps"], args["rise_time_ps"], args["setup_time_ps"], args["hold_time_ps"]))
    if name == "pcb_analyze_crosstalk":
        return _result(analyze_crosstalk(args["trace_spacing_mm"], args["trace_width_mm"], args["dielectric_height_mm"], args["coupling_length_mm"], args["rise_time_ps"]))
    if name == "pcb_analyze_via":
        return _result(analyze_via(args["via_diameter_mm"], args["via_length_mm"], args["pad_diameter_mm"], args["antipad_diameter_mm"], args["dielectric_constant"], args["frequency_ghz"]))

    if name == "pcb_analyze_differential_pair":
        res = calc_differential_impedance(args["trace_width_mm"], args["trace_spacing_mm"], args["dielectric_height_mm"], 0.035, args["dielectric_constant"])
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
        lengths = args["trace_lengths_mm"]
        max_skew_ps = args["max_skew_ps"]
        er = args["effective_er"]
        prop_delay_ps_per_mm = (1000 / C0) * math.sqrt(er) * 1e12
        delays = {n: l * prop_delay_ps_per_mm for n, l in lengths.items()}
        min_d, max_d = min(delays.values()), max(delays.values())
        skew_ps = max_d - min_d
        ref_name = min(delays, key=delays.get)
        mismatches = {n: {"length_mm": round(lengths[n], 2), "delay_ps": round(d, 1), "delta_ps": round(d - delays[ref_name], 1)} for n, d in delays.items()}
        return {"max_skew_ps": round(skew_ps, 1), "allowed_skew_ps": max_skew_ps, "compliant": skew_ps <= max_skew_ps, "reference_net": ref_name, "signals": mismatches}

    # === EMC ===
    if name == "pcb_analyze_current_loop":
        return _result(analyze_current_loop(args["loop_area_mm2"], args["current_ma"], args["frequency_mhz"]))
    if name == "pcb_estimate_bandwidth":
        return _result(estimate_rise_time_bandwidth(args["rise_time_ps"]))

    if name == "pcb_analyze_shielding":
        from .analyzers.emc.shielding import ShieldingAnalyzer, ShieldConfig
        analyzer = ShieldingAnalyzer()
        apertures = []
        if args.get("aperture_mm"):
            apertures = [{"type": "circular", "diameter": args["aperture_mm"]}]
        config = ShieldConfig(material=args["material"], thickness_mm=args["thickness_mm"], apertures=apertures)
        res = analyzer.analyze_shield(config=config, frequency_mhz=args["frequency_mhz"])
        return _serialize(res)

    if name == "pcb_analyze_esd":
        from .analyzers.emc.esd_assessment import ESDAnalyzer, ESDInterface
        analyzer = ESDAnalyzer()
        iface = ESDInterface(
            name=args["interface_type"], interface_type=args["interface_type"],
            connector_location=(0, 0), has_tvs=args.get("has_tvs", False),
            trace_length_to_ic_mm=args.get("trace_length_mm", 50),
        )
        res = analyzer.analyze_interface(interface=iface)
        return _serialize(res)

    if name == "pcb_analyze_grounding":
        from .analyzers.emc.grounding import GroundingAnalyzer, GroundPlane
        analyzer = GroundingAnalyzer()
        size = args.get("board_size_mm", 100)
        planes = [GroundPlane(layer_number=1, name=args["topology"], coverage_percent=90, width_mm=size, height_mm=size)]
        res = analyzer.analyze_grounding(planes=planes, board_width_mm=size, board_height_mm=size, max_frequency_mhz=args["max_frequency_mhz"])
        return _serialize(res)

    if name == "pcb_predict_compliance":
        from .analyzers.emc.compliance_predictor import EMCCompliancePredictor, EMCStandard, ClockSource
        predictor = EMCCompliancePredictor()
        predictor.add_clock(ClockSource(name="CLK", frequency_mhz=args["clock_frequency_mhz"], rise_time_ns=args["rise_time_ps"] / 1000.0))
        if args.get("has_shielding"):
            predictor.set_shielding(enclosure_shielding_db=20.0)
        std_map = {"FCC_A": "fcc_class_a", "FCC_B": "fcc_class_b", "CISPR_A": "cispr_32_class_a", "CISPR_B": "cispr_32_class_b"}
        std_val = std_map.get(args.get("standard", "FCC_B"), args.get("standard", "fcc_class_b"))
        res = predictor.predict_compliance(standard=EMCStandard(std_val))
        return _serialize(res)

    # === HIGH-SPEED DIGITAL ===
    if name == "pcb_analyze_ddr":
        from .analyzers.high_speed.ddr_analyzer import DDRAnalyzer, DDRStandard
        analyzer = DDRAnalyzer()
        tl = args.get("trace_length_mm", 50)
        byte_lanes = [{"name": "DQ0", "data_lengths_mm": [tl] * 8, "dqs_p_length_mm": tl, "dqs_n_length_mm": tl}]
        res = analyzer.analyze(ddr_standard=DDRStandard(args["ddr_standard"]), data_rate_mtps=args.get("data_rate_mtps", 3200), byte_lanes=byte_lanes, trace_impedance_ohm=args.get("trace_impedance_ohm"))
        return _serialize(res)

    if name == "pcb_analyze_pcie":
        from .analyzers.high_speed.pcie_analyzer import PCIeAnalyzer, PCIeGeneration
        analyzer = PCIeAnalyzer()
        tl = args.get("trace_length_mm", 100)
        lane_count = args.get("lane_count", 1)
        lanes = [{"name": f"Lane{i}", "tx_p_length_mm": tl, "tx_n_length_mm": tl, "rx_p_length_mm": tl, "rx_n_length_mm": tl} for i in range(lane_count)]
        res = analyzer.analyze(generation=PCIeGeneration(args["pcie_gen"]), lanes=lanes, differential_impedance_ohm=args.get("differential_impedance_ohm"))
        return _serialize(res)

    if name == "pcb_analyze_usb":
        from .analyzers.high_speed.usb_analyzer import USBAnalyzer, USBVersion
        analyzer = USBAnalyzer()
        tl = args.get("trace_length_mm", 100)
        usb2_pair = {"p_length_mm": tl, "n_length_mm": tl, "via_count": 2}
        res = analyzer.analyze(usb_version=USBVersion(args["usb_version"]), usb2_pair=usb2_pair, usb2_impedance_ohm=args.get("differential_impedance_ohm"))
        return _serialize(res)

    if name == "pcb_analyze_ethernet":
        from .analyzers.high_speed.ethernet_analyzer import EthernetAnalyzer, EthernetSpeed
        analyzer = EthernetAnalyzer()
        tl = args.get("trace_length_mm", 50)
        skew = args.get("pair_skew_ps", 0)
        mdi_pairs = [{"name": f"MDI{i}", "p_length_mm": tl, "n_length_mm": tl + skew * 0.17} for i in range(4)]
        res = analyzer.analyze(speed=EthernetSpeed(args["speed"]), mdi_pairs=mdi_pairs)
        return _serialize(res)

    # === POWER INTEGRITY ===
    if name == "pcb_analyze_pdn":
        from .analyzers.power_integrity.pdn_analyzer import PDNAnalyzer
        analyzer = PDNAnalyzer()
        res = analyzer.analyze(
            voltage=args["supply_voltage_v"], max_current=args["max_current_a"],
            ripple_percent=args.get("ripple_percent", 5),
        )
        return _serialize(res)

    if name == "pcb_analyze_decoupling":
        from .analyzers.power_integrity.decap_placement import DecapAnalyzer
        analyzer = DecapAnalyzer()
        cap_values = args.get("cap_values_uf", [0.1, 1.0, 10.0])
        decaps = [{"ref": f"C{i+1}", "capacitance_uf": c, "package": "0402", "position": (i * 2, 0), "via_count": 2} for i, c in enumerate(cap_values)]
        freq_hz = args["max_frequency_mhz"] * 1e6
        res = analyzer.analyze_ic_decoupling(ic_ref="U1", ic_position=(0, 0), power_rail="VCC", target_frequency_hz=freq_hz, decaps=decaps)
        return _serialize(res)

    if name == "pcb_analyze_vrm":
        from .analyzers.power_integrity.vrm_analyzer import VRMAnalyzer
        analyzer = VRMAnalyzer()
        dist = args.get("distance_to_load_mm", 25)
        res = analyzer.analyze_vrm(
            vrm_ref="U_VRM", vrm_position=(0, 0), output_rail="VOUT",
            output_voltage=args["output_voltage_v"], output_current=args["output_current_a"],
            input_voltage=args["output_voltage_v"] * 3, components=[],
            load_positions=[(dist, 0)],
        )
        return _serialize(res)

    # === DFM ===
    if name == "pcb_analyze_solder_paste":
        from .analyzers.dfm.solder_paste import SolderPasteAnalyzer, PadDefinition, ComponentPads
        analyzer = SolderPasteAnalyzer()
        pad = PadDefinition(pad_id="1", width_mm=args["pad_width_mm"], length_mm=args["pad_length_mm"], pitch_mm=args["pitch_mm"])
        comp = ComponentPads(reference="U1", package="custom", pads=[pad])
        res = analyzer.analyze_component(component=comp, stencil_thickness_mm=args.get("stencil_thickness_mm", 0.12))
        return _serialize(res)

    if name == "pcb_analyze_placement":
        from .analyzers.dfm.component_placement import PlacementAnalyzer, Component
        analyzer = PlacementAnalyzer()
        pitch = args["component_pitch_mm"]
        comps = [
            Component(reference="U1", package="QFN32", x_mm=0, y_mm=0, width_mm=5, height_mm=5, rotation_deg=0, side="top"),
            Component(reference="U2", package="QFN32", x_mm=pitch, y_mm=0, width_mm=5, height_mm=5, rotation_deg=0, side="bottom" if args.get("has_bottom_components") else "top"),
        ]
        size = max(pitch * 3, 50)
        res = analyzer.analyze_placement(components=comps, board_width_mm=size, board_height_mm=size)
        return _serialize(res)

    if name == "pcb_analyze_assembly":
        from .analyzers.dfm.assembly_check import AssemblyAnalyzer, AssemblyComponent
        analyzer = AssemblyAnalyzer.for_standard_smt()
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
        res = analyzer.analyze_assembly(components=comps)
        return _serialize(res)

    if name == "pcb_analyze_tolerance":
        from .analyzers.dfm.tolerance_analysis import ToleranceAnalyzer, ToleranceContributor
        analyzer = ToleranceAnalyzer()
        contributors = [ToleranceContributor(name=f"dim_{i+1}", nominal_mm=args["nominal_mm"] / len(args["tolerances_mm"]), tolerance_plus_mm=t, tolerance_minus_mm=t) for i, t in enumerate(args["tolerances_mm"])]
        total_tol = sum(args["tolerances_mm"])
        spec = (args["nominal_mm"] - total_tol, args["nominal_mm"] + total_tol)
        run_mc = args.get("method", "worst_case") == "monte_carlo"
        res = analyzer.analyze_stack(contributors=contributors, specification_mm=spec, run_monte_carlo=run_mc)
        return _serialize(res)

    # === THERMAL ===
    if name == "pcb_analyze_thermal":
        from .analyzers.thermal.power_dissipation import PowerDissipationAnalyzer
        analyzer = PowerDissipationAnalyzer()
        temp_rise = analyzer.estimate_temp_rise(power_w=args["power_watts"], theta_ja=args["theta_ja_c_per_w"])
        ambient = args.get("ambient_temp_c", 25)
        max_tj = args.get("max_junction_temp_c", 125)
        junction_temp = ambient + temp_rise
        return {"power_watts": args["power_watts"], "theta_ja_c_per_w": args["theta_ja_c_per_w"], "ambient_temp_c": ambient, "junction_temp_c": round(junction_temp, 1), "temp_rise_c": round(temp_rise, 1), "max_junction_temp_c": max_tj, "margin_c": round(max_tj - junction_temp, 1), "safe": junction_temp < max_tj}

    if name == "pcb_analyze_thermal_via":
        from .analyzers.thermal.thermal_via import ThermalViaAnalyzer
        analyzer = ThermalViaAnalyzer()
        fill = args.get("copper_fill_percent", 25)
        vias = [{"diameter_mm": args["via_diameter_mm"], "count": args["via_count"], "filled": fill >= 90}]
        res = analyzer.analyze_component(
            component_ref="U1", pad_area_mm2=args["via_count"] * 3.14 * (args["via_diameter_mm"] / 2) ** 2 * 4,
            power_w=args["power_watts"], vias=vias, board_thickness_mm=args.get("board_thickness_mm", 1.6),
        )
        return _serialize(res)

    if name == "pcb_analyze_copper_spreading":
        from .analyzers.thermal.copper_spreading import CopperSpreadingAnalyzer
        analyzer = CopperSpreadingAnalyzer()
        oz = args["copper_thickness_oz"]
        area = args["copper_area_mm2"]
        res = analyzer.analyze_component(
            component_ref="U1", power_w=args["power_watts"],
            footprint_area_mm2=min(area / 4, 100),
            connected_copper=[{"layer": "top", "area_mm2": area, "thickness_oz": oz}],
        )
        return _serialize(res)

    # === ANTENNA/EMI ===
    if name == "pcb_analyze_trace_antenna":
        from .analyzers.antenna.trace_antenna import TraceAntennaAnalyzer
        analyzer = TraceAntennaAnalyzer()
        trace = {"name": "trace", "length_mm": args["trace_length_mm"], "dielectric_constant": args.get("dielectric_constant", 4.3)}
        issues = analyzer.analyze_trace(trace=trace, max_frequency_mhz=args["frequency_mhz"])
        return {"trace_length_mm": args["trace_length_mm"], "frequency_mhz": args["frequency_mhz"], "issues": [_serialize(i) for i in issues], "antenna_risk": len(issues) > 0}

    if name == "pcb_analyze_slot_antenna":
        from .analyzers.antenna.slot_antenna import SlotAntennaAnalyzer
        analyzer = SlotAntennaAnalyzer()
        slot = {"id": "slot1", "length_mm": args["slot_length_mm"], "width_mm": args.get("slot_width_mm", 1.0)}
        issue = analyzer.analyze_slot(slot=slot, operating_frequencies=[args["frequency_mhz"]])
        return {"slot_length_mm": args["slot_length_mm"], "frequency_mhz": args["frequency_mhz"], "issue": _serialize(issue) if issue else None, "resonant": issue is not None}

    if name == "pcb_analyze_common_mode":
        from .analyzers.antenna.common_mode import CommonModeAnalyzer
        analyzer = CommonModeAnalyzer()
        pair = {
            "name": "pair", "differential_impedance_ohm": args["differential_impedance_ohm"],
            "common_mode_impedance_ohm": args.get("common_mode_impedance_ohm", args["differential_impedance_ohm"] / 2),
            "cable_length_m": args.get("cable_length_m", 1.0), "frequency_mhz": args["frequency_mhz"],
        }
        res = analyzer.analyze_pair(pair=pair)
        return _serialize(res)

    if name == "pcb_analyze_cable_coupling":
        from .analyzers.antenna.cable_coupling import CableCouplingAnalyzer
        analyzer = CableCouplingAnalyzer()
        conn = {
            "name": "connector", "cable_spacing_mm": args["cable_spacing_mm"],
            "parallel_length_mm": args["parallel_length_mm"], "frequency_mhz": args["frequency_mhz"],
            "cable_type": args.get("cable_type", "unshielded"),
        }
        res = analyzer.analyze_connector(connector=conn)
        return _serialize(res)

    # === REFERENCE DATA ===
    if name == "pcb_get_stackup_templates":
        return {"stackup_templates": STACKUP_TEMPLATES}
    if name == "pcb_get_material_properties":
        return {"materials": MATERIAL_PROPERTIES}

    # === SESSION MANAGEMENT ===
    if name == "pcb_list_sessions":
        return {"sessions": sessions.list_sessions(), "count": sessions.session_count}
    if name == "pcb_close_session":
        closed = sessions.close_session(args["session_id"])
        return {"closed": closed, "session_id": args["session_id"]}

    return {"success": False, "error": f"Unknown tool: {name}"}


def _get_session(session_id: str):
    """Get session or raise error."""
    data = sessions.get_session(session_id)
    if data is None:
        raise ValueError(f"No session found: {session_id}. Use pcb_parse_layout first.")
    return data


def main():
    """Run the MCP server."""
    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    asyncio.run(run())


if __name__ == "__main__":
    main()

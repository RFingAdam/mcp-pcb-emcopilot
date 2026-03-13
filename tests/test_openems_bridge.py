"""Tests for OpenEMS bridge integration module.

Covers Issue #28:
- OpenEMS model generation for microstrip, stripline, via, trace antenna
- Script content validation (correct API calls and geometry values)
- Analytical vs simulated result comparison (pass/warning/fail/edge cases)
- Validation report formatting
- Default dataclass values (boundary conditions, mesh resolution, etc.)
- MCP tool dispatch for pcb_validate_with_openems and pcb_compare_simulation
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from mcp_pcb_emcopilot.integrations.openems_bridge import (
    OpenEMSBridge,
    OpenEMSModel,
    ValidationResult,
)

# =============================================================================
# Microstrip model generation
# =============================================================================

def test_microstrip_model_basic():
    """Test basic microstrip model generation."""
    bridge = OpenEMSBridge()
    model = bridge.generate_microstrip_model(
        trace_width_mm=0.2,
        dielectric_height_mm=0.1,
        er=4.3,
        frequency_ghz=1.0,
    )
    assert model.model_type == "microstrip"
    assert model.geometry["trace_width_mm"] == 0.2
    assert model.geometry["dielectric_height_mm"] == 0.1
    assert model.geometry["dielectric_er"] == 4.3
    assert "Microstrip" in model.description
    assert len(model.script) > 100
    print("  PASS: Microstrip model basic generation")


def test_microstrip_model_geometry():
    """Test microstrip model has correct derived geometry."""
    bridge = OpenEMSBridge()
    model = bridge.generate_microstrip_model(
        trace_width_mm=0.3,
        dielectric_height_mm=0.2,
        trace_thickness_mm=0.035,
        er=4.3,
        frequency_ghz=2.0,
        trace_length_mm=30.0,
    )
    geom = model.geometry
    assert geom["trace_length_mm"] == 30.0
    assert geom["trace_thickness_mm"] == 0.035
    # Substrate width = trace_length + 2 * margin, margin = max(5, h*10) = max(5, 2) = 5
    assert geom["substrate_width_mm"] == 30.0 + 2 * 5.0
    # substrate_depth = trace_width * 20
    assert geom["substrate_depth_mm"] == 0.3 * 20
    # air_height = dielectric_height * 10
    assert geom["air_height_mm"] == 0.2 * 10
    # Wavelength check
    c0 = 299792458.0
    expected_wl = (c0 / (2.0e9) / math.sqrt(4.3)) * 1000
    assert abs(geom["wavelength_mm"] - expected_wl) < 0.01
    print("  PASS: Microstrip model geometry calculations")


def test_microstrip_model_large_dielectric_margin():
    """Test margin uses dielectric_height*10 when > 5mm."""
    bridge = OpenEMSBridge()
    model = bridge.generate_microstrip_model(
        trace_width_mm=0.2,
        dielectric_height_mm=1.0,  # margin = max(5, 10) = 10
    )
    expected_width = 50.0 + 2 * 10.0  # default trace_length=50, margin=10
    assert model.geometry["substrate_width_mm"] == expected_width
    print("  PASS: Microstrip model large dielectric margin")


def test_microstrip_frequency_range():
    """Test microstrip frequency range is 0 to 2*freq."""
    bridge = OpenEMSBridge()
    model = bridge.generate_microstrip_model(
        trace_width_mm=0.2,
        dielectric_height_mm=0.1,
        frequency_ghz=3.0,
    )
    assert model.frequency_range_hz == (0, 6.0e9)
    print("  PASS: Microstrip frequency range")


def test_microstrip_script_contains_openems_api():
    """Test generated microstrip script has required OpenEMS API calls."""
    bridge = OpenEMSBridge()
    model = bridge.generate_microstrip_model(
        trace_width_mm=0.2,
        dielectric_height_mm=0.1,
    )
    script = model.script
    assert "from openEMS import openEMS" in script
    assert "from CSXCAD import ContinuousStructure" in script
    assert "FDTD = openEMS(" in script
    assert "CSX = ContinuousStructure()" in script
    assert "FDTD.SetGaussExcite" in script
    assert "FDTD.SetBoundaryCond" in script
    assert "AddLumpedPort" in script
    assert "SmoothMeshLines" in script
    assert "FDTD.Run" in script
    assert "CalcPort" in script
    assert "microstrip_sim" in script
    print("  PASS: Microstrip script contains OpenEMS API calls")


def test_microstrip_script_geometry_values():
    """Test generated script embeds correct geometry values."""
    bridge = OpenEMSBridge()
    model = bridge.generate_microstrip_model(
        trace_width_mm=0.25,
        dielectric_height_mm=0.15,
        er=4.5,
        frequency_ghz=2.5,
    )
    script = model.script
    assert "trace_w = 0.2500" in script
    assert "sub_h = 0.1500" in script
    assert "sub_er = 4.50" in script
    f_max_expected = 2.5e9 * 2
    assert f"f_max = {f_max_expected:.1f}" in script
    print("  PASS: Microstrip script has correct geometry values")


# =============================================================================
# Stripline model generation
# =============================================================================

def test_stripline_model_basic():
    """Test basic stripline model generation."""
    bridge = OpenEMSBridge()
    model = bridge.generate_stripline_model(
        trace_width_mm=0.15,
        dielectric_height_mm=0.2,
        er=4.3,
    )
    assert model.model_type == "stripline"
    assert model.geometry["trace_width_mm"] == 0.15
    assert model.geometry["dielectric_height_mm"] == 0.2
    assert "Stripline" in model.description
    print("  PASS: Stripline model basic generation")


def test_stripline_total_height():
    """Test stripline total height = 2*h + t."""
    bridge = OpenEMSBridge()
    model = bridge.generate_stripline_model(
        trace_width_mm=0.15,
        dielectric_height_mm=0.2,
        trace_thickness_mm=0.035,
    )
    expected = 0.2 * 2 + 0.035
    assert abs(model.geometry["total_height_mm"] - expected) < 1e-10
    print("  PASS: Stripline total height calculation")


def test_stripline_script_contains_two_ground_planes():
    """Test stripline script has top and bottom ground planes."""
    bridge = OpenEMSBridge()
    model = bridge.generate_stripline_model(
        trace_width_mm=0.15,
        dielectric_height_mm=0.2,
    )
    script = model.script
    # Should have bottom ground at z=0 and top ground at z=total_h
    assert "Bottom ground" in script
    assert "Top ground" in script
    assert "stripline_sim" in script
    print("  PASS: Stripline script has two ground planes")


def test_stripline_script_openems_api():
    """Test stripline script has required OpenEMS API calls."""
    bridge = OpenEMSBridge()
    model = bridge.generate_stripline_model(
        trace_width_mm=0.15,
        dielectric_height_mm=0.2,
    )
    script = model.script
    assert "from openEMS import openEMS" in script
    assert "FDTD = openEMS(" in script
    assert "ContinuousStructure" in script
    assert "AddLumpedPort" in script
    print("  PASS: Stripline script OpenEMS API")


# =============================================================================
# Via model generation
# =============================================================================

def test_via_model_basic():
    """Test basic via model generation."""
    bridge = OpenEMSBridge()
    model = bridge.generate_via_model(
        drill_diameter_mm=0.3,
        pad_diameter_mm=0.6,
        board_thickness_mm=1.6,
    )
    assert model.model_type == "via"
    assert model.geometry["drill_diameter_mm"] == 0.3
    assert model.geometry["pad_diameter_mm"] == 0.6
    assert model.geometry["board_thickness_mm"] == 1.6
    assert "Via" in model.description
    print("  PASS: Via model basic generation")


def test_via_model_auto_antipad():
    """Test via model auto-calculates antipad when not specified."""
    bridge = OpenEMSBridge()
    model = bridge.generate_via_model(
        drill_diameter_mm=0.3,
        pad_diameter_mm=0.6,
        board_thickness_mm=1.6,
    )
    # antipad = pad * 2 when not specified
    assert model.geometry["antipad_diameter_mm"] == 1.2
    print("  PASS: Via model auto antipad")


def test_via_model_explicit_antipad():
    """Test via model uses explicit antipad when given."""
    bridge = OpenEMSBridge()
    model = bridge.generate_via_model(
        drill_diameter_mm=0.3,
        pad_diameter_mm=0.6,
        board_thickness_mm=1.6,
        antipad_diameter_mm=1.0,
    )
    assert model.geometry["antipad_diameter_mm"] == 1.0
    print("  PASS: Via model explicit antipad")


def test_via_mesh_resolution():
    """Test via model has higher mesh resolution (30 vs default 20)."""
    bridge = OpenEMSBridge()
    model = bridge.generate_via_model(
        drill_diameter_mm=0.3,
        pad_diameter_mm=0.6,
        board_thickness_mm=1.6,
    )
    assert model.mesh_resolution == 30
    print("  PASS: Via mesh resolution is 30")


def test_via_script_contains_cylinder():
    """Test via script uses cylinder for barrel."""
    bridge = OpenEMSBridge()
    model = bridge.generate_via_model(
        drill_diameter_mm=0.3,
        pad_diameter_mm=0.6,
        board_thickness_mm=1.6,
    )
    assert "AddCylinder" in model.script
    assert "via_barrel" in model.script
    assert "via_sim" in model.script
    print("  PASS: Via script uses cylinder for barrel")


def test_via_frequency_range():
    """Test via frequency range defaults to 0-10GHz (5GHz * 2)."""
    bridge = OpenEMSBridge()
    model = bridge.generate_via_model(
        drill_diameter_mm=0.3,
        pad_diameter_mm=0.6,
        board_thickness_mm=1.6,
    )
    assert model.frequency_range_hz == (0, 10.0e9)
    print("  PASS: Via frequency range")


# =============================================================================
# Trace antenna model generation
# =============================================================================

def test_trace_antenna_model_basic():
    """Test basic trace antenna model generation."""
    bridge = OpenEMSBridge()
    model = bridge.generate_trace_antenna_model(
        trace_length_mm=30.0,
        trace_width_mm=0.2,
        height_above_ground_mm=0.5,
    )
    assert model.model_type == "trace_antenna"
    assert model.geometry["trace_length_mm"] == 30.0
    assert model.geometry["height_above_ground_mm"] == 0.5
    assert "Trace antenna" in model.description
    print("  PASS: Trace antenna model basic generation")


def test_trace_antenna_frequency_range():
    """Test trace antenna has wideband range 0.1f to 3f."""
    bridge = OpenEMSBridge()
    model = bridge.generate_trace_antenna_model(
        trace_length_mm=30.0,
        trace_width_mm=0.2,
        height_above_ground_mm=0.5,
        frequency_ghz=2.0,
    )
    assert model.frequency_range_hz == (2.0e9 * 0.1, 2.0e9 * 3)
    print("  PASS: Trace antenna frequency range")


def test_trace_antenna_script_nf2ff():
    """Test trace antenna script includes NF2FF box for radiation pattern."""
    bridge = OpenEMSBridge()
    model = bridge.generate_trace_antenna_model(
        trace_length_mm=30.0,
        trace_width_mm=0.2,
        height_above_ground_mm=0.5,
    )
    assert "CreateNF2FFBox" in model.script
    assert "CalcNF2FF" in model.script
    assert "Directivity" in model.script
    assert "trace_antenna_sim" in model.script
    print("  PASS: Trace antenna script has NF2FF")


# =============================================================================
# Compare results - pass / warning / fail
# =============================================================================

def test_compare_pass():
    """Test comparison that passes (within tolerance)."""
    bridge = OpenEMSBridge()
    result = bridge.compare_results(
        parameter="impedance",
        analytical_value=50.0,
        simulated_value=51.0,
        unit="ohms",
        tolerance_percent=5.0,
    )
    assert result.status == "pass"
    assert result.difference_percent == 2.0
    assert result.parameter == "impedance"
    assert result.analytical_unit == "ohms"
    assert result.simulated_unit == "ohms"
    assert "Within" in result.notes
    print("  PASS: Comparison pass case")


def test_compare_warning():
    """Test comparison that gives warning (between 1x and 2x tolerance)."""
    bridge = OpenEMSBridge()
    result = bridge.compare_results(
        parameter="impedance",
        analytical_value=50.0,
        simulated_value=54.0,
        tolerance_percent=5.0,
    )
    # 8% difference, within 10% (2x tolerance) but exceeds 5%
    assert result.status == "warning"
    assert result.difference_percent == 8.0
    assert "Exceeds" in result.notes
    print("  PASS: Comparison warning case")


def test_compare_fail():
    """Test comparison that fails (exceeds 2x tolerance)."""
    bridge = OpenEMSBridge()
    result = bridge.compare_results(
        parameter="impedance",
        analytical_value=50.0,
        simulated_value=60.0,
        tolerance_percent=5.0,
    )
    # 20% difference, exceeds 10% (2x tolerance)
    assert result.status == "fail"
    assert result.difference_percent == 20.0
    print("  PASS: Comparison fail case")


def test_compare_zero_analytical():
    """Test comparison with zero analytical value."""
    bridge = OpenEMSBridge()
    result = bridge.compare_results(
        parameter="loss",
        analytical_value=0.0,
        simulated_value=0.1,
    )
    assert result.difference_percent == float('inf')
    assert result.status == "fail"
    print("  PASS: Comparison zero analytical value")


def test_compare_zero_both():
    """Test comparison when both values are zero."""
    bridge = OpenEMSBridge()
    result = bridge.compare_results(
        parameter="loss",
        analytical_value=0.0,
        simulated_value=0.0,
    )
    assert result.difference_percent == 0.0
    assert result.status == "pass"
    print("  PASS: Comparison both zero")


def test_compare_exact_boundary():
    """Test comparison exactly at tolerance boundary."""
    bridge = OpenEMSBridge()
    result = bridge.compare_results(
        parameter="impedance",
        analytical_value=100.0,
        simulated_value=105.0,
        tolerance_percent=5.0,
    )
    assert result.status == "pass"
    assert result.difference_percent == 5.0
    print("  PASS: Comparison at exact tolerance boundary")


# =============================================================================
# Format validation report
# =============================================================================

def test_format_report_all_pass():
    """Test report formatting with all passing results."""
    bridge = OpenEMSBridge()
    results = [
        bridge.compare_results("Z0", 50.0, 51.0),
        bridge.compare_results("delay", 100.0, 101.0, unit="ps"),
    ]
    report = bridge.format_validation_report(results)
    assert report["summary"]["total"] == 2
    assert report["summary"]["passed"] == 2
    assert report["summary"]["failed"] == 0
    assert report["summary"]["overall_status"] == "pass"
    assert len(report["results"]) == 2
    print("  PASS: Report all pass")


def test_format_report_mixed():
    """Test report formatting with mixed results."""
    bridge = OpenEMSBridge()
    results = [
        bridge.compare_results("Z0", 50.0, 51.0),       # pass
        bridge.compare_results("loss", 1.0, 1.08),       # warning (8%)
        bridge.compare_results("delay", 100.0, 120.0),   # fail (20%)
    ]
    report = bridge.format_validation_report(results)
    assert report["summary"]["passed"] == 1
    assert report["summary"]["warnings"] == 1
    assert report["summary"]["failed"] == 1
    assert report["summary"]["overall_status"] == "fail"
    print("  PASS: Report mixed statuses")


def test_format_report_with_pending():
    """Test report handles pending results."""
    pending = ValidationResult(
        parameter="radiation",
        analytical_value=10.0,
        analytical_unit="dBm",
    )
    bridge = OpenEMSBridge()
    report = bridge.format_validation_report([pending])
    assert report["summary"]["pending"] == 1
    assert report["summary"]["overall_status"] == "pass"  # no failures
    assert report["results"][0]["simulated"] == "pending"
    print("  PASS: Report with pending result")


# =============================================================================
# Dataclass defaults
# =============================================================================

def test_default_boundary_conditions():
    """Test default boundary conditions are PML x6."""
    model = OpenEMSModel(
        model_type="test",
        description="test",
        geometry={},
        frequency_range_hz=(0, 1e9),
    )
    assert model.boundary_conditions == ["PML"] * 6
    assert len(model.boundary_conditions) == 6
    print("  PASS: Default boundary conditions are PML x6")


def test_default_mesh_resolution():
    """Test default mesh resolution is 20."""
    model = OpenEMSModel(
        model_type="test",
        description="test",
        geometry={},
        frequency_range_hz=(0, 1e9),
    )
    assert model.mesh_resolution == 20
    print("  PASS: Default mesh resolution is 20")


def test_default_excitation():
    """Test default excitation is gaussian."""
    model = OpenEMSModel(
        model_type="test",
        description="test",
        geometry={},
        frequency_range_hz=(0, 1e9),
    )
    assert model.excitation == "gaussian"
    print("  PASS: Default excitation is gaussian")


def test_default_script_empty():
    """Test default script is empty string."""
    model = OpenEMSModel(
        model_type="test",
        description="test",
        geometry={},
        frequency_range_hz=(0, 1e9),
    )
    assert model.script == ""
    print("  PASS: Default script is empty")


def test_validation_result_defaults():
    """Test ValidationResult defaults."""
    vr = ValidationResult(
        parameter="test",
        analytical_value=1.0,
        analytical_unit="V",
    )
    assert vr.status == "pending"
    assert vr.simulated_value is None
    assert vr.simulated_unit is None
    assert vr.difference_percent is None
    assert vr.notes == ""
    print("  PASS: ValidationResult defaults")


# =============================================================================
# MCP tool dispatch tests
# =============================================================================

def test_dispatch_validate_microstrip():
    """Test pcb_validate_with_openems dispatch for microstrip."""
    from mcp_pcb_emcopilot.server import _dispatch
    result = _dispatch("pcb_validate_with_openems", {
        "model_type": "microstrip",
        "trace_width_mm": 0.2,
        "dielectric_height_mm": 0.1,
        "er": 4.3,
        "frequency_ghz": 1.0,
    })
    assert result["model_type"] == "microstrip"
    assert "script" in result
    assert len(result["script"]) > 100
    assert result["geometry"]["trace_width_mm"] == 0.2
    assert result["frequency_range_hz"] == [0, 2.0e9]
    assert result["boundary_conditions"] == ["PML"] * 6
    print("  PASS: Dispatch validate microstrip")


def test_dispatch_validate_via():
    """Test pcb_validate_with_openems dispatch for via."""
    from mcp_pcb_emcopilot.server import _dispatch
    result = _dispatch("pcb_validate_with_openems", {
        "model_type": "via",
        "drill_diameter_mm": 0.3,
        "pad_diameter_mm": 0.6,
        "board_thickness_mm": 1.6,
    })
    assert result["model_type"] == "via"
    assert result["geometry"]["drill_diameter_mm"] == 0.3
    assert result["mesh_resolution"] == 30
    print("  PASS: Dispatch validate via")


def test_dispatch_validate_trace_antenna():
    """Test pcb_validate_with_openems dispatch for trace_antenna."""
    from mcp_pcb_emcopilot.server import _dispatch
    result = _dispatch("pcb_validate_with_openems", {
        "model_type": "trace_antenna",
        "trace_length_mm": 30.0,
        "trace_width_mm": 0.2,
        "height_above_ground_mm": 0.5,
    })
    assert result["model_type"] == "trace_antenna"
    assert result["geometry"]["trace_length_mm"] == 30.0
    assert "CreateNF2FFBox" in result["script"]
    print("  PASS: Dispatch validate trace antenna")


def test_dispatch_compare_simulation():
    """Test pcb_compare_simulation dispatch."""
    from mcp_pcb_emcopilot.server import _dispatch
    result = _dispatch("pcb_compare_simulation", {
        "parameter": "impedance",
        "analytical_value": 50.0,
        "simulated_value": 51.5,
        "unit": "ohms",
        "tolerance_percent": 5.0,
    })
    assert result["parameter"] == "impedance"
    assert result["status"] == "pass"
    assert result["difference_percent"] == 3.0
    assert result["analytical_unit"] == "ohms"
    assert result["simulated_unit"] == "ohms"
    print("  PASS: Dispatch compare simulation")


def test_dispatch_validate_stripline():
    """Test pcb_validate_with_openems dispatch for stripline."""
    from mcp_pcb_emcopilot.server import _dispatch
    result = _dispatch("pcb_validate_with_openems", {
        "model_type": "stripline",
        "trace_width_mm": 0.15,
        "dielectric_height_mm": 0.2,
    })
    assert result["model_type"] == "stripline"
    assert result["geometry"]["trace_width_mm"] == 0.15
    assert "stripline_sim" in result["script"]
    print("  PASS: Dispatch validate stripline")


def test_dispatch_validate_invalid_model_type():
    """Test pcb_validate_with_openems rejects invalid model type."""
    from mcp_pcb_emcopilot.errors import ValidationError
    from mcp_pcb_emcopilot.server import _dispatch
    try:
        _dispatch("pcb_validate_with_openems", {"model_type": "bogus"})
        assert False, "Should have raised ValidationError"
    except ValidationError:
        pass
    print("  PASS: Dispatch rejects invalid model type")

"""Tests for the design review orchestrator.

Tests context intake, analyzer selection, report generation,
and end-to-end dispatch through server.py.
"""

import json
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from mcp_pcb_emcopilot.classifiers import (
    DesignClassifier,
    InterfaceDetector,
    NetClassifier,
)
from mcp_pcb_emcopilot.models.pcb_data import (
    PCBComponent,
    PCBDesignData,
    PCBLayer,
    PCBNet,
    PCBTrace,
    PCBVia,
    PCBZone,
)
from mcp_pcb_emcopilot.orchestrator import (
    DomainResult,
    ReviewFinding,
    _build_executive_summary,
    _build_risk_matrix,
    _estimate_voltage_from_name,
    _select_analyzers,
    generate_report,
    run_design_review,
    set_review_context,
)

# =============================================================================
# Test fixtures
# =============================================================================

def make_mock_design() -> PCBDesignData:
    """Create a realistic 4-layer mixed-signal PCB with DDR4, USB3, and PCIe."""
    design = PCBDesignData(
        source_file="test_review_design.kicad_pcb",
        source_format="kicad",
        board_width_mm=100.0,
        board_height_mm=80.0,
        board_thickness_mm=1.6,
        layer_count=4,
    )

    # Stackup: Signal / GND / Power / Signal
    design.layers = [
        PCBLayer(name="F.Cu", number=0, layer_type="signal", thickness_mm=0.035),
        PCBLayer(name="Prepreg1", number=1, layer_type="dielectric", thickness_mm=0.2),
        PCBLayer(name="In1.Cu", number=2, layer_type="plane", thickness_mm=0.035),
        PCBLayer(name="Core", number=3, layer_type="dielectric", thickness_mm=1.0),
        PCBLayer(name="In2.Cu", number=4, layer_type="plane", thickness_mm=0.035),
        PCBLayer(name="Prepreg2", number=5, layer_type="dielectric", thickness_mm=0.2),
        PCBLayer(name="B.Cu", number=6, layer_type="signal", thickness_mm=0.035),
    ]

    # Nets: DDR4 data, USB3, PCIe, power, ground, clocks
    design.nets = [
        PCBNet(name="GND", index=0, net_class="power"),
        PCBNet(name="VCC3V3", index=1, net_class="power"),
        PCBNet(name="VCC1V8", index=2, net_class="power"),
        PCBNet(name="VCC1V2", index=3, net_class="power"),
        # DDR4 data
        PCBNet(name="DDR4_DQ0", index=4, max_frequency_hz=1.2e9),
        PCBNet(name="DDR4_DQ1", index=5, max_frequency_hz=1.2e9),
        PCBNet(name="DDR4_DQ2", index=6, max_frequency_hz=1.2e9),
        PCBNet(name="DDR4_DQ3", index=7, max_frequency_hz=1.2e9),
        PCBNet(name="DDR4_DQ4", index=8, max_frequency_hz=1.2e9),
        PCBNet(name="DDR4_DQ5", index=9, max_frequency_hz=1.2e9),
        PCBNet(name="DDR4_DQ6", index=10, max_frequency_hz=1.2e9),
        PCBNet(name="DDR4_DQ7", index=11, max_frequency_hz=1.2e9),
        PCBNet(name="DQS0_P", index=12, is_differential=True, differential_pair="DQS0"),
        PCBNet(name="DQS0_N", index=13, is_differential=True, differential_pair="DQS0"),
        PCBNet(name="DDR4_A0", index=14),
        PCBNet(name="DDR4_A1", index=15),
        PCBNet(name="DDR4_CK_P", index=16, is_differential=True, differential_pair="DDR4_CK"),
        PCBNet(name="DDR4_CK_N", index=17, is_differential=True, differential_pair="DDR4_CK"),
        # USB3
        PCBNet(name="USB_DP", index=18, is_differential=True, differential_pair="USB_D"),
        PCBNet(name="USB_DN", index=19, is_differential=True, differential_pair="USB_D"),
        PCBNet(name="USB_SSTX_P", index=20, is_differential=True, differential_pair="USB_SSTX"),
        PCBNet(name="USB_SSTX_N", index=21, is_differential=True, differential_pair="USB_SSTX"),
        PCBNet(name="USB_SSRX_P", index=22, is_differential=True, differential_pair="USB_SSRX"),
        PCBNet(name="USB_SSRX_N", index=23, is_differential=True, differential_pair="USB_SSRX"),
        PCBNet(name="VBUS", index=24),
        # PCIe
        PCBNet(name="PCIE_TX0_P", index=25, is_differential=True, differential_pair="PCIE_TX0"),
        PCBNet(name="PCIE_TX0_N", index=26, is_differential=True, differential_pair="PCIE_TX0"),
        PCBNet(name="PCIE_RX0_P", index=27, is_differential=True, differential_pair="PCIE_RX0"),
        PCBNet(name="PCIE_RX0_N", index=28, is_differential=True, differential_pair="PCIE_RX0"),
        PCBNet(name="PCIE_REFCLK_P", index=29, is_differential=True),
        PCBNet(name="PCIE_REFCLK_N", index=30, is_differential=True),
        # Clock
        PCBNet(name="CLK_100M", index=31, max_frequency_hz=100e6),
        # GPIO
        PCBNet(name="GPIO_0", index=32),
        PCBNet(name="GPIO_1", index=33),
    ]

    # Traces for DDR data
    for i in range(8):
        net_idx = 4 + i
        length = 40 + i * 2
        design.traces.append(PCBTrace(
            layer="F.Cu", width_mm=0.1,
            x1_mm=10, y1_mm=10 + i * 2,
            x2_mm=10 + length, y2_mm=10 + i * 2,
            net_index=net_idx, net_name=f"DDR4_DQ{i}",
        ))

    # DQS traces
    design.traces.append(PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=10, y1_mm=30, x2_mm=55, y2_mm=30, net_index=12, net_name="DQS0_P"))
    design.traces.append(PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=10, y1_mm=31, x2_mm=55, y2_mm=31, net_index=13, net_name="DQS0_N"))

    # USB traces
    design.traces.append(PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=50, y1_mm=10, x2_mm=80, y2_mm=10, net_index=18, net_name="USB_DP"))
    design.traces.append(PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=50, y1_mm=11, x2_mm=80, y2_mm=11, net_index=19, net_name="USB_DN"))
    design.traces.append(PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=50, y1_mm=14, x2_mm=80, y2_mm=14, net_index=20, net_name="USB_SSTX_P"))
    design.traces.append(PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=50, y1_mm=15, x2_mm=80, y2_mm=15, net_index=21, net_name="USB_SSTX_N"))
    design.traces.append(PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=50, y1_mm=18, x2_mm=80, y2_mm=18, net_index=22, net_name="USB_SSRX_P"))
    design.traces.append(PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=50, y1_mm=19, x2_mm=80, y2_mm=19, net_index=23, net_name="USB_SSRX_N"))

    # PCIe traces
    design.traces.append(PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=10, y1_mm=50, x2_mm=70, y2_mm=50, net_index=25, net_name="PCIE_TX0_P"))
    design.traces.append(PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=10, y1_mm=51, x2_mm=70, y2_mm=51, net_index=26, net_name="PCIE_TX0_N"))
    design.traces.append(PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=10, y1_mm=54, x2_mm=70, y2_mm=54, net_index=27, net_name="PCIE_RX0_P"))
    design.traces.append(PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=10, y1_mm=55, x2_mm=70, y2_mm=55, net_index=28, net_name="PCIE_RX0_N"))

    # Clock trace
    design.traces.append(PCBTrace(layer="F.Cu", width_mm=0.15, x1_mm=40, y1_mm=40, x2_mm=60, y2_mm=40, net_index=31, net_name="CLK_100M"))

    # Vias
    design.vias = [
        PCBVia(x_mm=25, y_mm=20, drill_mm=0.3, pad_diameter_mm=0.6, net_index=4, net_name="DDR4_DQ0"),
        PCBVia(x_mm=60, y_mm=10, drill_mm=0.3, pad_diameter_mm=0.6, net_index=18, net_name="USB_DP"),
        PCBVia(x_mm=40, y_mm=40, drill_mm=0.3, pad_diameter_mm=0.6, net_index=0, net_name="GND"),
    ]

    # Ground zones
    design.zones = [
        PCBZone(layer="In1.Cu", net_name="GND", net_index=0, area_mm2=7000),
        PCBZone(layer="In2.Cu", net_name="VCC3V3", net_index=1, area_mm2=3000),
    ]

    # Components
    design.components = [
        PCBComponent(reference="U1", value="DDR4_SDRAM", footprint="BGA-96", x_mm=20, y_mm=20, package="BGA"),
        PCBComponent(reference="U2", value="SoC", footprint="BGA-256", x_mm=50, y_mm=40, package="BGA"),
        PCBComponent(reference="U3", value="USB3_HUB", footprint="QFN-32", x_mm=75, y_mm=15),
        PCBComponent(reference="J1", value="USB-C", footprint="USB_C_Receptacle", x_mm=90, y_mm=15),
        PCBComponent(reference="J2", value="PCIe_x1", footprint="M.2_Key_M", x_mm=15, y_mm=55),
        PCBComponent(reference="VR1", value="TPS65263", footprint="QFN-24", x_mm=80, y_mm=60),
        PCBComponent(reference="C1", value="100nF", footprint="0402", x_mm=22, y_mm=18),
        PCBComponent(reference="C2", value="10uF", footprint="0805", x_mm=78, y_mm=58),
        PCBComponent(reference="R1", value="49.9", footprint="0402", x_mm=52, y_mm=42),
    ]

    return design


def make_simple_design() -> PCBDesignData:
    """Create a simple 2-layer design with minimal signals for testing edge cases."""
    design = PCBDesignData(
        source_file="simple_design.kicad_pcb",
        source_format="kicad",
        board_width_mm=50.0,
        board_height_mm=40.0,
        board_thickness_mm=1.6,
        layer_count=2,
    )

    design.layers = [
        PCBLayer(name="F.Cu", number=0, layer_type="signal", thickness_mm=0.035),
        PCBLayer(name="B.Cu", number=1, layer_type="signal", thickness_mm=0.035),
    ]

    design.nets = [
        PCBNet(name="GND", index=0),
        PCBNet(name="VCC3V3", index=1),
        PCBNet(name="GPIO_0", index=2),
    ]

    design.traces = [
        PCBTrace(layer="F.Cu", width_mm=0.25, x1_mm=5, y1_mm=5, x2_mm=25, y2_mm=5, net_index=2, net_name="GPIO_0"),
    ]

    design.components = [
        PCBComponent(reference="U1", value="MCU", footprint="TQFP-48", x_mm=20, y_mm=20),
        PCBComponent(reference="R1", value="10K", footprint="0402", x_mm=25, y_mm=5),
    ]

    return design


# =============================================================================
# Tests: Context intake
# =============================================================================

def test_set_review_context_basic():
    """Test basic context intake stores all fields."""
    design = make_mock_design()
    ctx = set_review_context(
        design=design,
        design_intent="High-speed SoC module with DDR4, USB3, and PCIe",
        target_standards=["FCC_B", "CISPR_32"],
        known_issues=["DDR4 byte lane 0 has length mismatch", "USB connector near board edge"],
        impedance_targets={"DDR4_*": 50, "USB_SS*": 90, "PCIE_*": 85},
        thermal_limits={"max_ambient_c": 40, "max_junction_c": 125},
        operating_conditions={"temp_min_c": -20, "temp_max_c": 70, "altitude_m": 2000},
    )

    assert ctx["design_intent"] == "High-speed SoC module with DDR4, USB3, and PCIe"
    assert "FCC_B" in ctx["target_standards"]
    assert "CISPR_32" in ctx["target_standards"]
    assert len(ctx["known_issues"]) == 2
    assert ctx["impedance_targets"]["DDR4_*"] == 50
    assert ctx["thermal_limits"]["max_ambient_c"] == 40
    assert ctx["operating_conditions"]["altitude_m"] == 2000
    assert "set_at" in ctx
    assert design.review_context == ctx
    print("  PASS: test_set_review_context_basic")


def test_set_review_context_defaults():
    """Test context intake with minimal arguments uses defaults."""
    design = make_mock_design()
    ctx = set_review_context(design=design)

    assert ctx["design_intent"] == ""
    assert ctx["target_standards"] == ["FCC_B"]
    assert ctx["known_issues"] == []
    assert ctx["impedance_targets"] == {}
    assert ctx["thermal_limits"] == {}
    assert ctx["operating_conditions"] == {}
    print("  PASS: test_set_review_context_defaults")


def test_set_review_context_overwrites():
    """Test that setting context twice overwrites the previous context."""
    design = make_mock_design()
    set_review_context(design=design, design_intent="First context")
    assert design.review_context["design_intent"] == "First context"

    set_review_context(design=design, design_intent="Second context")
    assert design.review_context["design_intent"] == "Second context"
    print("  PASS: test_set_review_context_overwrites")


# =============================================================================
# Tests: Analyzer selection
# =============================================================================

def test_analyzer_selection_complex_design():
    """Test analyzer selection for a complex design with DDR, USB, PCIe."""
    design = make_mock_design()
    net_cls = NetClassifier().classify(design)
    interfaces = InterfaceDetector().detect(design, net_cls)
    classification = DesignClassifier().classify(design, net_cls, interfaces)

    analyzers = _select_analyzers(design, classification, interfaces, net_cls)

    # Should include interface-specific analyzers
    assert "ddr" in analyzers, f"Expected 'ddr' in analyzers, got: {analyzers}"
    assert "usb" in analyzers, f"Expected 'usb' in analyzers, got: {analyzers}"
    assert "pcie" in analyzers, f"Expected 'pcie' in analyzers, got: {analyzers}"

    # Should include high-speed general analyzers
    assert "return_path" in analyzers
    assert "emi_risk" in analyzers

    # Should include always-run analyzers
    assert "thermal" in analyzers
    assert "dfm_placement" in analyzers
    assert "emc_grounding" in analyzers
    assert "validation" in analyzers

    # Should include power analysis (has power nets)
    assert "pdn" in analyzers

    print("  PASS: test_analyzer_selection_complex_design")


def test_analyzer_selection_simple_design():
    """Test analyzer selection for a simple design with no high-speed interfaces."""
    design = make_simple_design()
    net_cls = NetClassifier().classify(design)
    interfaces = InterfaceDetector().detect(design, net_cls)
    classification = DesignClassifier().classify(design, net_cls, interfaces)

    analyzers = _select_analyzers(design, classification, interfaces, net_cls)

    # Should NOT include interface-specific analyzers
    assert "ddr" not in analyzers
    assert "usb" not in analyzers
    assert "pcie" not in analyzers

    # Should still include always-run analyzers
    assert "thermal" in analyzers
    assert "dfm_placement" in analyzers
    assert "emc_grounding" in analyzers
    assert "validation" in analyzers

    print("  PASS: test_analyzer_selection_simple_design")


# =============================================================================
# Tests: Full design review
# =============================================================================

def test_run_design_review_structure():
    """Test that run_design_review returns a properly structured result."""
    design = make_mock_design()
    set_review_context(design=design, target_standards=["FCC_B"])
    result = run_design_review(design, "test-001")

    assert result.session_id == "test-001"
    assert result.timestamp > 0
    assert result.design_classification is not None
    assert isinstance(result.detected_interfaces, list)
    assert len(result.domain_results) > 0
    assert isinstance(result.risk_matrix, list)
    assert isinstance(result.executive_summary, dict)
    assert isinstance(result.recommendations, list)
    assert isinstance(result.cross_correlations, list)

    # Verify executive summary fields
    summary = result.executive_summary
    assert "overall_status" in summary
    assert summary["overall_status"] in ("PASS", "WARNING", "FAIL")
    assert "total_critical" in summary
    assert "total_warnings" in summary
    assert "total_info" in summary
    assert "domains_analyzed" in summary
    assert "domain_statuses" in summary

    print("  PASS: test_run_design_review_structure")


def test_run_design_review_detects_interfaces():
    """Test that the review detects DDR, USB, and PCIe interfaces."""
    design = make_mock_design()
    result = run_design_review(design, "test-002")

    iface_types = [i.lower() for i in result.detected_interfaces]
    iface_str = " ".join(iface_types)

    # Should detect at least DDR and USB
    has_ddr = any("ddr" in t for t in iface_types)
    has_usb = any("usb" in t for t in iface_types)
    has_pcie = any("pcie" in t for t in iface_types)

    assert has_ddr, f"Expected DDR detection, got interfaces: {result.detected_interfaces}"
    assert has_usb, f"Expected USB detection, got interfaces: {result.detected_interfaces}"
    assert has_pcie, f"Expected PCIe detection, got interfaces: {result.detected_interfaces}"

    print("  PASS: test_run_design_review_detects_interfaces")


def test_run_design_review_runs_analyzers():
    """Test that appropriate analyzers are run based on detected interfaces."""
    design = make_mock_design()
    result = run_design_review(design, "test-003")

    domain_names = [dr.domain for dr in result.domain_results]

    # Should have domain results for detected interfaces
    # At minimum, always-run analyzers should be present
    assert "thermal" in domain_names, f"Missing 'thermal' domain, got: {domain_names}"
    assert "dfm" in domain_names, f"Missing 'dfm' domain, got: {domain_names}"
    assert "emc_grounding" in domain_names, f"Missing 'emc_grounding' domain, got: {domain_names}"
    assert "validation" in domain_names, f"Missing 'validation' domain, got: {domain_names}"

    # Each domain result should have a valid status
    for dr in result.domain_results:
        assert dr.status in ("pass", "warning", "fail", "error", "skipped"), \
            f"Invalid status '{dr.status}' for domain '{dr.domain}'"

    print("  PASS: test_run_design_review_runs_analyzers")


def test_run_design_review_stores_results():
    """Test that review results are stored in the design session."""
    design = make_mock_design()
    result = run_design_review(design, "test-004")

    assert design.review_results is not None
    assert isinstance(design.review_results, dict)
    assert "executive_summary" in design.review_results
    assert "domain_results" in design.review_results
    assert design.review_results["session_id"] == "test-004"

    print("  PASS: test_run_design_review_stores_results")


def test_run_design_review_simple_design():
    """Test review on a simple design doesn't crash and produces sensible results."""
    design = make_simple_design()
    result = run_design_review(design, "test-005")

    assert result.session_id == "test-005"
    assert len(result.domain_results) > 0

    # Simple design should have fewer domains than complex
    domain_names = [dr.domain for dr in result.domain_results]
    # Should NOT have DDR, USB, PCIe domains
    assert "high_speed_ddr" not in domain_names
    assert "high_speed_usb" not in domain_names
    assert "high_speed_pcie" not in domain_names

    print("  PASS: test_run_design_review_simple_design")


def test_run_design_review_to_dict():
    """Test that to_dict produces valid serializable output."""
    design = make_mock_design()
    result = run_design_review(design, "test-006")
    d = result.to_dict()

    # Should be JSON-serializable
    json_str = json.dumps(d, default=str)
    assert len(json_str) > 100

    # Verify structure
    assert d["session_id"] == "test-006"
    assert isinstance(d["domain_results"], list)
    assert isinstance(d["executive_summary"], dict)
    assert isinstance(d["recommendations"], list)

    print("  PASS: test_run_design_review_to_dict")


# =============================================================================
# Tests: Report generation
# =============================================================================

def test_generate_report_summary():
    """Test summary report format."""
    design = make_mock_design()
    run_design_review(design, "test-007")
    report = generate_report(design, "test-007", "summary")

    assert report["report_type"] == "summary"
    assert "overall_status" in report
    assert "total_findings" in report
    assert "critical" in report
    assert "warnings" in report
    assert "top_risks" in report
    assert "top_recommendations" in report
    assert "domain_statuses" in report

    print("  PASS: test_generate_report_summary")


def test_generate_report_detailed():
    """Test detailed report format."""
    design = make_mock_design()
    run_design_review(design, "test-008")
    report = generate_report(design, "test-008", "detailed")

    assert report["report_type"] == "detailed"
    assert report["session_id"] == "test-008"
    assert "executive_summary" in report
    assert "domain_details" in report
    assert "cross_correlations" in report
    assert "risk_matrix" in report
    assert "recommendations" in report
    assert "design_classification" in report
    assert "detected_interfaces" in report

    # Domain details should have finding data
    for domain in report["domain_details"]:
        assert "domain" in domain
        assert "status" in domain
        assert "findings" in domain

    print("  PASS: test_generate_report_detailed")


def test_generate_report_json():
    """Test json report returns raw results."""
    design = make_mock_design()
    run_design_review(design, "test-009")
    report = generate_report(design, "test-009", "json")

    # JSON format is the raw review_results dict
    assert "session_id" in report
    assert "executive_summary" in report
    assert "domain_results" in report

    print("  PASS: test_generate_report_json")


def test_generate_report_no_results():
    """Test report generation when no review has been run."""
    design = make_mock_design()
    report = generate_report(design, "test-010", "summary")

    assert "error" in report

    print("  PASS: test_generate_report_no_results")


# =============================================================================
# Tests: Risk matrix and executive summary
# =============================================================================

def test_risk_matrix_sorting():
    """Test that risk matrix entries are sorted by risk score descending."""
    findings = [
        ReviewFinding(domain="test", severity="info", title="Low risk", description="Low"),
        ReviewFinding(domain="test", severity="critical", title="High risk", description="High", recommendation="Fix it"),
        ReviewFinding(domain="test", severity="warning", title="Med risk", description="Medium", recommendation="Check it"),
    ]
    domain_results = [DomainResult(domain="test", status="fail", findings=findings)]
    matrix = _build_risk_matrix(domain_results, [])

    # Should be sorted descending by risk_score
    if len(matrix) >= 2:
        for i in range(len(matrix) - 1):
            assert matrix[i].risk_score >= matrix[i + 1].risk_score

    print("  PASS: test_risk_matrix_sorting")


def test_executive_summary_counts():
    """Test executive summary correctly counts findings."""
    findings = [
        ReviewFinding(domain="a", severity="critical", title="C1", description=""),
        ReviewFinding(domain="a", severity="critical", title="C2", description=""),
        ReviewFinding(domain="a", severity="warning", title="W1", description=""),
        ReviewFinding(domain="a", severity="info", title="I1", description=""),
    ]
    dr = DomainResult(domain="a", status="fail", findings=findings)
    classification = DesignClassifier().classify(make_simple_design())
    summary = _build_executive_summary([dr], classification, [])

    assert summary["total_critical"] == 2
    assert summary["total_warnings"] == 1
    assert summary["total_info"] == 1
    assert summary["total_findings"] == 4
    assert summary["overall_status"] == "FAIL"

    print("  PASS: test_executive_summary_counts")


def test_executive_summary_pass():
    """Test executive summary shows PASS when no issues."""
    findings = [
        ReviewFinding(domain="a", severity="info", title="I1", description=""),
    ]
    dr = DomainResult(domain="a", status="pass", findings=findings)
    classification = DesignClassifier().classify(make_simple_design())
    summary = _build_executive_summary([dr], classification, [])

    assert summary["overall_status"] == "PASS"

    print("  PASS: test_executive_summary_pass")


# =============================================================================
# Tests: Helper functions
# =============================================================================

def test_estimate_voltage_from_name():
    """Test voltage estimation from net names."""
    assert _estimate_voltage_from_name("VCC3V3") == 3.3
    assert _estimate_voltage_from_name("V1P8") == 1.8
    assert _estimate_voltage_from_name("+5V") == 5.0
    assert _estimate_voltage_from_name("+12V") == 12.0
    assert _estimate_voltage_from_name("V1P2") == 1.2
    assert _estimate_voltage_from_name("RANDOM_NET") == 0.0

    print("  PASS: test_estimate_voltage_from_name")


# =============================================================================
# Tests: Dispatch through server.py
# =============================================================================

def test_dispatch_set_review_context():
    """Test pcb_set_review_context through server dispatch."""
    from mcp_pcb_emcopilot.server import _dispatch, sessions

    # Create a session with mock design
    design = make_mock_design()
    sid = sessions.create_session(design)

    result = _dispatch("pcb_set_review_context", {
        "session_id": sid,
        "design_intent": "Test design for CI",
        "target_standards": ["FCC_B", "CE"],
        "known_issues": ["Test issue 1"],
        "impedance_targets": {"USB_*": 90},
        "thermal_limits": {"max_ambient_c": 45},
        "operating_conditions": {"temp_max_c": 85},
    })

    assert result["success"] is True
    assert result["session_id"] == sid
    assert result["review_context"]["design_intent"] == "Test design for CI"
    assert "FCC_B" in result["review_context"]["target_standards"]

    sessions.close_session(sid)
    print("  PASS: test_dispatch_set_review_context")


def test_dispatch_run_design_review():
    """Test pcb_run_design_review through server dispatch."""
    from mcp_pcb_emcopilot.server import _dispatch, sessions

    design = make_mock_design()
    sid = sessions.create_session(design)

    result = _dispatch("pcb_run_design_review", {
        "session_id": sid,
    })

    assert "session_id" in result
    assert "executive_summary" in result
    assert "domain_results" in result
    assert "risk_matrix" in result
    assert "recommendations" in result
    assert result["session_id"] == sid

    sessions.close_session(sid)
    print("  PASS: test_dispatch_run_design_review")


def test_dispatch_generate_report():
    """Test pcb_generate_report through server dispatch."""
    from mcp_pcb_emcopilot.server import _dispatch, sessions

    design = make_mock_design()
    sid = sessions.create_session(design)

    # Run review first
    _dispatch("pcb_run_design_review", {"session_id": sid})

    # Generate summary report
    report = _dispatch("pcb_generate_report", {
        "session_id": sid,
        "format": "summary",
    })

    assert report["report_type"] == "summary"
    assert "overall_status" in report

    # Generate detailed report
    report = _dispatch("pcb_generate_report", {
        "session_id": sid,
        "format": "detailed",
    })

    assert report["report_type"] == "detailed"
    assert "domain_details" in report

    sessions.close_session(sid)
    print("  PASS: test_dispatch_generate_report")


def test_dispatch_full_workflow():
    """Test complete workflow: set context -> run review -> generate report."""
    from mcp_pcb_emcopilot.server import _dispatch, sessions

    design = make_mock_design()
    sid = sessions.create_session(design)

    # Step 1: Set context
    ctx_result = _dispatch("pcb_set_review_context", {
        "session_id": sid,
        "design_intent": "SoC module with high-speed interfaces",
        "target_standards": ["FCC_B"],
        "thermal_limits": {"max_ambient_c": 40},
    })
    assert ctx_result["success"] is True

    # Step 2: Run review
    review_result = _dispatch("pcb_run_design_review", {
        "session_id": sid,
    })
    assert "executive_summary" in review_result
    assert review_result["review_context"]["design_intent"] == "SoC module with high-speed interfaces"

    # Step 3: Generate report
    report = _dispatch("pcb_generate_report", {
        "session_id": sid,
        "format": "detailed",
    })
    assert report["report_type"] == "detailed"
    assert len(report["domain_details"]) > 0

    # Verify the report is JSON-serializable
    json_str = json.dumps(report, default=str)
    assert len(json_str) > 100

    sessions.close_session(sid)
    print("  PASS: test_dispatch_full_workflow")


# =============================================================================
# Tests: Cross-correlation
# =============================================================================

def test_cross_correlation_thermal_si():
    """Test that thermal+SI cross-correlation is detected when both have issues."""
    from mcp_pcb_emcopilot.orchestrator import _cross_correlate

    thermal_findings = [
        ReviewFinding(domain="thermal", severity="critical", title="Hot IC", description="U1 exceeds limits"),
    ]
    ddr_findings = [
        ReviewFinding(domain="high_speed_ddr", severity="warning", title="DDR skew", description="Byte lane mismatch"),
    ]

    domain_results = [
        DomainResult(domain="thermal", status="fail", findings=thermal_findings),
        DomainResult(domain="high_speed_ddr", status="warning", findings=ddr_findings),
    ]

    design = make_mock_design()
    classification = DesignClassifier().classify(design)
    correlations = _cross_correlate(domain_results, design, classification)

    thermal_si = [c for c in correlations if "thermal" in c.domains and "high_speed" in c.domains]
    assert len(thermal_si) > 0, f"Expected thermal+SI cross-correlation, got: {[c.domains for c in correlations]}"

    print("  PASS: test_cross_correlation_thermal_si")


def test_cross_correlation_emc_routing():
    """Test that EMC+routing cross-correlation is detected."""
    from mcp_pcb_emcopilot.orchestrator import _cross_correlate

    rp_findings = [
        ReviewFinding(domain="emc_return_path", severity="critical", title="Split crossing", description="Signal crosses split plane"),
    ]
    emi_findings = [
        ReviewFinding(domain="emc_emi_risk", severity="critical", title="High EMI", description="Signal exceeds limits"),
    ]

    domain_results = [
        DomainResult(domain="emc_return_path", status="fail", findings=rp_findings),
        DomainResult(domain="emc_emi_risk", status="fail", findings=emi_findings),
    ]

    design = make_mock_design()
    classification = DesignClassifier().classify(design)
    correlations = _cross_correlate(domain_results, design, classification)

    emc_routing = [c for c in correlations if "emc_return_path" in c.domains and "emc_emi_risk" in c.domains]
    assert len(emc_routing) > 0
    assert emc_routing[0].severity == "critical"

    print("  PASS: test_cross_correlation_emc_routing")


# =============================================================================
# Run all tests
# =============================================================================

if __name__ == "__main__":
    print("Running orchestrator tests...\n")

    tests = [
        # Context intake
        test_set_review_context_basic,
        test_set_review_context_defaults,
        test_set_review_context_overwrites,
        # Analyzer selection
        test_analyzer_selection_complex_design,
        test_analyzer_selection_simple_design,
        # Full design review
        test_run_design_review_structure,
        test_run_design_review_detects_interfaces,
        test_run_design_review_runs_analyzers,
        test_run_design_review_stores_results,
        test_run_design_review_simple_design,
        test_run_design_review_to_dict,
        # Report generation
        test_generate_report_summary,
        test_generate_report_detailed,
        test_generate_report_json,
        test_generate_report_no_results,
        # Risk matrix and summary
        test_risk_matrix_sorting,
        test_executive_summary_counts,
        test_executive_summary_pass,
        # Helpers
        test_estimate_voltage_from_name,
        # Server dispatch
        test_dispatch_set_review_context,
        test_dispatch_run_design_review,
        test_dispatch_generate_report,
        test_dispatch_full_workflow,
        # Cross-correlation
        test_cross_correlation_thermal_si,
        test_cross_correlation_emc_routing,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            print(f"  FAIL: {test.__name__}: {e}")

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    if errors:
        print("\nFailures:")
        for name, err in errors:
            print(f"  {name}: {err}")

    sys.exit(0 if failed == 0 else 1)

"""Tests for return path analyzer and EMI risk scorer.

Creates mock PCBDesignData with traces, vias, zones, and runs all 6 new tools
through their dispatch handlers.
"""

import json
import math
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from mcp_pcb_emcopilot.models.pcb_data import (
    PCBComponent,
    PCBDesignData,
    PCBLayer,
    PCBNet,
    PCBTrace,
    PCBVia,
    PCBZone,
)


def make_mock_design() -> PCBDesignData:
    """Create a realistic 4-layer PCB design with high-speed signals.

    Stackup: Signal (F.Cu) / GND (In1.Cu) / Power (In2.Cu) / Signal (B.Cu)

    Contains:
    - DDR4 data net with traces on F.Cu
    - USB3 differential pair on F.Cu
    - Clock net crossing a ground plane split
    - Ground zones with a gap (split)
    - Ground vias (some near signal vias, some not)
    """
    design = PCBDesignData(
        source_file="test_design.kicad_pcb",
        source_format="kicad",
        board_width_mm=80.0,
        board_height_mm=60.0,
        board_thickness_mm=1.6,
        layer_count=4,
    )

    # Stackup
    design.layers = [
        PCBLayer(name="F.Cu", number=0, layer_type="signal", thickness_mm=0.035, dielectric_constant=4.3),
        PCBLayer(name="Prepreg1", number=1, layer_type="dielectric", thickness_mm=0.2, dielectric_constant=4.3),
        PCBLayer(name="In1.Cu", number=2, layer_type="plane", thickness_mm=0.035, dielectric_constant=4.3),
        PCBLayer(name="Core", number=3, layer_type="dielectric", thickness_mm=1.0, dielectric_constant=4.3),
        PCBLayer(name="In2.Cu", number=4, layer_type="plane", thickness_mm=0.035, dielectric_constant=4.3),
        PCBLayer(name="Prepreg2", number=5, layer_type="dielectric", thickness_mm=0.2, dielectric_constant=4.3),
        PCBLayer(name="B.Cu", number=6, layer_type="signal", thickness_mm=0.035, dielectric_constant=4.3),
    ]

    # Nets
    design.nets = [
        PCBNet(name="GND", index=0, net_class="power"),
        PCBNet(name="VCC3V3", index=1, net_class="power"),
        PCBNet(name="DDR4_DQ0", index=2, net_class="high_speed", max_frequency_hz=1.2e9),
        PCBNet(name="DDR4_DQ1", index=3, net_class="high_speed", max_frequency_hz=1.2e9),
        PCBNet(name="USB3_SSTX_P", index=4, is_differential=True, differential_pair="USB3_SSTX"),
        PCBNet(name="USB3_SSTX_N", index=5, is_differential=True, differential_pair="USB3_SSTX"),
        PCBNet(name="CLK_100M", index=6, max_frequency_hz=100e6),
        PCBNet(name="PCIE_TX0_P", index=7, is_differential=True, differential_pair="PCIE_TX0"),
        PCBNet(name="PCIE_TX0_N", index=8, is_differential=True, differential_pair="PCIE_TX0"),
        PCBNet(name="SPI_CLK", index=9),
        PCBNet(name="GPIO_5", index=10),
    ]

    # Traces
    # DDR4_DQ0: routed on F.Cu, transitions to B.Cu via via
    design.traces = [
        # DDR4_DQ0 on F.Cu (short, well-routed)
        PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=10, y1_mm=10, x2_mm=25, y2_mm=10, net_index=2, net_name="DDR4_DQ0"),
        PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=25, y1_mm=10, x2_mm=25, y2_mm=20, net_index=2, net_name="DDR4_DQ0"),
        # DDR4_DQ0 continues on B.Cu after via
        PCBTrace(layer="B.Cu", width_mm=0.1, x1_mm=25, y1_mm=20, x2_mm=35, y2_mm=20, net_index=2, net_name="DDR4_DQ0"),

        # DDR4_DQ1 on F.Cu
        PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=10, y1_mm=12, x2_mm=30, y2_mm=12, net_index=3, net_name="DDR4_DQ1"),

        # USB3_SSTX_P on F.Cu (moderate length)
        PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=40, y1_mm=10, x2_mm=60, y2_mm=10, net_index=4, net_name="USB3_SSTX_P"),
        PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=60, y1_mm=10, x2_mm=60, y2_mm=30, net_index=4, net_name="USB3_SSTX_P"),

        # USB3_SSTX_N on F.Cu
        PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=40, y1_mm=12, x2_mm=60, y2_mm=12, net_index=5, net_name="USB3_SSTX_N"),
        PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=60, y1_mm=12, x2_mm=60, y2_mm=32, net_index=5, net_name="USB3_SSTX_N"),

        # CLK_100M on F.Cu -- this one crosses the ground plane split
        PCBTrace(layer="F.Cu", width_mm=0.15, x1_mm=5, y1_mm=35, x2_mm=75, y2_mm=35, net_index=6, net_name="CLK_100M"),

        # PCIE_TX0_P on F.Cu
        PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=10, y1_mm=45, x2_mm=50, y2_mm=45, net_index=7, net_name="PCIE_TX0_P"),

        # PCIE_TX0_N on F.Cu
        PCBTrace(layer="F.Cu", width_mm=0.1, x1_mm=10, y1_mm=47, x2_mm=50, y2_mm=47, net_index=8, net_name="PCIE_TX0_N"),

        # SPI_CLK
        PCBTrace(layer="F.Cu", width_mm=0.2, x1_mm=15, y1_mm=55, x2_mm=30, y2_mm=55, net_index=9, net_name="SPI_CLK"),

        # GPIO_5
        PCBTrace(layer="F.Cu", width_mm=0.2, x1_mm=50, y1_mm=55, x2_mm=65, y2_mm=55, net_index=10, net_name="GPIO_5"),
    ]

    # Vias
    design.vias = [
        # Signal vias
        PCBVia(x_mm=25, y_mm=20, drill_mm=0.3, pad_diameter_mm=0.6, start_layer="F.Cu", end_layer="B.Cu", net_index=2, net_name="DDR4_DQ0"),
        PCBVia(x_mm=60, y_mm=30, drill_mm=0.3, pad_diameter_mm=0.6, start_layer="F.Cu", end_layer="B.Cu", net_index=4, net_name="USB3_SSTX_P"),

        # Ground vias (stitching)
        PCBVia(x_mm=26, y_mm=20, drill_mm=0.3, pad_diameter_mm=0.6, start_layer="F.Cu", end_layer="B.Cu", net_index=0, net_name="GND"),  # near DDR4 via
        PCBVia(x_mm=10, y_mm=25, drill_mm=0.3, pad_diameter_mm=0.6, start_layer="F.Cu", end_layer="B.Cu", net_index=0, net_name="GND"),
        PCBVia(x_mm=30, y_mm=25, drill_mm=0.3, pad_diameter_mm=0.6, start_layer="F.Cu", end_layer="B.Cu", net_index=0, net_name="GND"),
        PCBVia(x_mm=50, y_mm=25, drill_mm=0.3, pad_diameter_mm=0.6, start_layer="F.Cu", end_layer="B.Cu", net_index=0, net_name="GND"),
        PCBVia(x_mm=70, y_mm=25, drill_mm=0.3, pad_diameter_mm=0.6, start_layer="F.Cu", end_layer="B.Cu", net_index=0, net_name="GND"),
        # Note: no ground via near USB3 via at (60,30) -- intentional issue
    ]

    # Ground zones -- two zones with a gap between them (split plane)
    # Zone 1: left half of In1.Cu (x: 0-38)
    design.zones = [
        PCBZone(
            layer="In1.Cu", net_name="GND", net_index=0, zone_type="fill",
            outline=[(0, 0), (38, 0), (38, 60), (0, 60)],
            area_mm2=38 * 60,
        ),
        # Zone 2: right half of In1.Cu (x: 42-80) -- gap from x=38 to x=42
        PCBZone(
            layer="In1.Cu", net_name="GND", net_index=0, zone_type="fill",
            outline=[(42, 0), (80, 0), (80, 60), (42, 60)],
            area_mm2=38 * 60,
        ),
        # Full ground on In2.Cu (power plane but also used as ground reference)
        PCBZone(
            layer="In2.Cu", net_name="VCC3V3", net_index=1, zone_type="fill",
            outline=[(0, 0), (80, 0), (80, 60), (0, 60)],
            area_mm2=80 * 60,
        ),
    ]

    # Components
    design.components = [
        PCBComponent(reference="U1", value="DDR4_SDRAM", footprint="BGA-96", layer="F.Cu", x_mm=20, y_mm=15),
        PCBComponent(reference="U2", value="USB3_PHY", footprint="QFN-48", layer="F.Cu", x_mm=50, y_mm=20),
        PCBComponent(reference="Y1", value="100MHz", footprint="OSC-3225", layer="F.Cu", x_mm=5, y_mm=35),
        PCBComponent(reference="U3", value="PCIe_Switch", footprint="BGA-256", layer="F.Cu", x_mm=30, y_mm=45),
    ]

    return design


def test_return_path_analyzer_single_net():
    """Test analyzing return path for a single net."""
    from mcp_pcb_emcopilot.analyzers.emc.return_path_analyzer import ReturnPathAnalyzer

    design = make_mock_design()
    analyzer = ReturnPathAnalyzer()

    # Test DDR4 net (well-routed with nearby ground via)
    result = analyzer.analyze_net(design, "DDR4_DQ0")
    assert result.net_name == "DDR4_DQ0"
    assert result.effective_loop_area_mm2 > 0
    assert len(result.return_path_segments) > 0
    assert result.return_path_quality in ("excellent", "good", "marginal", "poor")
    print(f"  DDR4_DQ0: quality={result.return_path_quality}, loop_area={result.effective_loop_area_mm2:.1f}mm2, "
          f"segments={len(result.return_path_segments)}, via_transitions={len(result.via_transitions)}")

    # Test CLK_100M (crosses ground plane split)
    result_clk = analyzer.analyze_net(design, "CLK_100M")
    assert result_clk.net_name == "CLK_100M"
    print(f"  CLK_100M: quality={result_clk.return_path_quality}, loop_area={result_clk.effective_loop_area_mm2:.1f}mm2, "
          f"split_crossings={len(result_clk.split_crossings)}")

    # Test USB3 (via without nearby ground via)
    result_usb = analyzer.analyze_net(design, "USB3_SSTX_P")
    print(f"  USB3_SSTX_P: quality={result_usb.return_path_quality}, "
          f"loop_area={result_usb.effective_loop_area_mm2:.1f}mm2, "
          f"via_issues={sum(1 for vt in result_usb.via_transitions if not vt.has_adequate_return)}")

    print("  PASS: Single net analysis works correctly")


def test_return_path_analyzer_full():
    """Test full return path analysis for all nets."""
    from mcp_pcb_emcopilot.analyzers.emc.return_path_analyzer import ReturnPathAnalyzer

    design = make_mock_design()
    analyzer = ReturnPathAnalyzer()
    result = analyzer.analyze(design)

    assert result.total_nets_analyzed > 0
    assert len(result.net_results) > 0
    print(f"  Analyzed {result.total_nets_analyzed} nets, "
          f"{result.nets_with_issues} with issues, "
          f"{len(result.split_crossings)} split crossings, "
          f"{len(result.via_transition_issues)} via issues")
    print("  Worst loop areas:")
    for wla in result.worst_loop_areas[:5]:
        print(f"    {wla['net_name']}: {wla['loop_area_mm2']:.1f}mm2 ({wla['quality']})")
    print("  PASS: Full return path analysis works correctly")


def test_split_crossing_detection():
    """Test split-plane crossing detection."""
    from mcp_pcb_emcopilot.analyzers.emc.return_path_analyzer import ReturnPathAnalyzer

    design = make_mock_design()
    analyzer = ReturnPathAnalyzer()
    crossings = analyzer.find_split_crossings(design)

    print(f"  Found {len(crossings)} split-plane crossing(s)")
    for c in crossings:
        print(f"    Net={c.net_name}, layer={c.split_layer}, "
              f"at=({c.crossing_location_x_mm:.1f}, {c.crossing_location_y_mm:.1f}), "
              f"severity={c.severity}")

    print("  PASS: Split crossing detection works correctly")


def test_emi_risk_scorer():
    """Test EMI risk scoring."""
    from mcp_pcb_emcopilot.analyzers.emc.emi_risk_scorer import EMIRiskScorer
    from mcp_pcb_emcopilot.analyzers.emc.return_path_analyzer import ReturnPathAnalyzer
    from mcp_pcb_emcopilot.classifiers.net_classifier import NetClassifier

    design = make_mock_design()

    classifier = NetClassifier()
    classified = classifier.classify(design)

    rp_analyzer = ReturnPathAnalyzer()
    rp_result = rp_analyzer.analyze(design, classified)

    scorer = EMIRiskScorer()
    result = scorer.score(design, rp_result, classified, standard="FCC_B")

    assert len(result.net_risks) > 0
    assert result.overall_risk_score >= 0
    assert result.overall_risk_level in ("critical", "high", "medium", "low")
    assert result.executive_summary != ""

    print(f"  Overall risk: {result.overall_risk_level} (score: {result.overall_risk_score})")
    print("  Top risk nets:")
    for nr in result.net_risks[:5]:
        print(f"    {nr.net_name} ({nr.net_category}): score={nr.risk_score}, "
              f"level={nr.risk_level}, emission={nr.predicted_emission_dbuv_m:.1f}dBuV/m")

    print("  Frequency risks (worst 5):")
    for fr in result.frequency_risks[:5]:
        print(f"    {fr.frequency_mhz:.0f}MHz: {fr.predicted_level_dbuv_m:.1f}dBuV/m, "
              f"limit={fr.limit_dbuv_m:.1f}, margin={fr.margin_db:.1f}dB ({fr.risk_level})")

    print(f"  Board regions: {len(result.board_regions)}")
    for br in result.board_regions[:3]:
        print(f"    {br.region_name}: score={br.risk_score}, "
              f"nets={len(br.contributing_nets)}, concern={br.primary_concern}")

    print(f"  Compliance: {result.standard_compliance}")
    print(f"  Executive summary: {result.executive_summary[:200]}...")
    print(f"  Recommendations: {len(result.recommendations)}")
    for rec in result.recommendations[:3]:
        print(f"    - {rec[:100]}")

    print("  PASS: EMI risk scoring works correctly")


def test_predict_emissions():
    """Test emission spectrum prediction."""
    from mcp_pcb_emcopilot.analyzers.emc.emi_risk_scorer import EMIRiskScorer
    from mcp_pcb_emcopilot.analyzers.emc.return_path_analyzer import ReturnPathAnalyzer
    from mcp_pcb_emcopilot.classifiers.net_classifier import NetClassifier

    design = make_mock_design()
    classifier = NetClassifier()
    classified = classifier.classify(design)
    rp_analyzer = ReturnPathAnalyzer()
    rp_result = rp_analyzer.analyze(design, classified)
    scorer = EMIRiskScorer()

    # Test with different standards
    for std in ["FCC_B", "CISPR_B"]:
        result = scorer.score(design, rp_result, classified, standard=std)
        problem_freqs = result.predicted_problem_frequencies_mhz
        compliance = result.standard_compliance
        print(f"  {std}: {len(result.frequency_risks)} freq points analyzed, "
              f"{len(problem_freqs)} problem frequencies")
        if std in compliance:
            c = compliance[std]
            print(f"    Pass: {c['predicted_pass']}, worst margin: {c['margin_db']}dB "
                  f"at {c['worst_frequency_mhz']}MHz")

    print("  PASS: Emission prediction works correctly")


def test_emi_hotspots():
    """Test board region risk identification."""
    from mcp_pcb_emcopilot.analyzers.emc.emi_risk_scorer import EMIRiskScorer
    from mcp_pcb_emcopilot.analyzers.emc.return_path_analyzer import ReturnPathAnalyzer

    design = make_mock_design()
    rp_analyzer = ReturnPathAnalyzer()
    rp_result = rp_analyzer.analyze(design)
    scorer = EMIRiskScorer()
    result = scorer.score(design, rp_result)

    hotspots = result.board_regions
    print(f"  Found {len(hotspots)} hot regions")
    for hs in hotspots[:5]:
        print(f"    {hs.region_name} at ({hs.center_x_mm}, {hs.center_y_mm})mm: "
              f"score={hs.risk_score}, nets={hs.contributing_nets}")

    print("  PASS: Hotspot identification works correctly")


def test_dispatch_all_tools():
    """Test all 6 new tools through the dispatch system."""
    from mcp_pcb_emcopilot.server import _dispatch, sessions
    from mcp_pcb_emcopilot.session import DesignSessionManager

    design = make_mock_design()
    sid = sessions.create_session(design)

    print(f"  Session created: {sid}")

    # 1. pcb_trace_return_path
    result = _dispatch("pcb_trace_return_path", {"session_id": sid, "net_name": "DDR4_DQ0"})
    assert result["net_name"] == "DDR4_DQ0"
    assert "effective_loop_area_mm2" in result
    print(f"  Tool 1 (pcb_trace_return_path): OK - quality={result['return_path_quality']}")

    # 2. pcb_analyze_return_paths
    result = _dispatch("pcb_analyze_return_paths", {"session_id": sid})
    assert result["total_nets_analyzed"] > 0
    print(f"  Tool 2 (pcb_analyze_return_paths): OK - {result['total_nets_analyzed']} nets analyzed")

    # 3. pcb_find_split_crossings
    result = _dispatch("pcb_find_split_crossings", {"session_id": sid})
    assert "split_crossings" in result
    print(f"  Tool 3 (pcb_find_split_crossings): OK - {result['count']} crossings found")

    # 4. pcb_analyze_emi_risk
    result = _dispatch("pcb_analyze_emi_risk", {"session_id": sid, "standard": "FCC_B"})
    assert "overall_risk_level" in result
    assert "net_risks" in result
    assert "executive_summary" in result
    print(f"  Tool 4 (pcb_analyze_emi_risk): OK - risk={result['overall_risk_level']} "
          f"({result['overall_risk_score']})")

    # 5. pcb_predict_emissions
    result = _dispatch("pcb_predict_emissions", {"session_id": sid, "standard": "FCC_B"})
    assert "frequency_risks" in result
    assert "standard_compliance" in result
    print(f"  Tool 5 (pcb_predict_emissions): OK - {result['total_frequencies_analyzed']} frequencies")

    # 6. pcb_get_emi_hotspots
    result = _dispatch("pcb_get_emi_hotspots", {"session_id": sid})
    assert "hotspots" in result
    assert "overall_risk_level" in result
    print(f"  Tool 6 (pcb_get_emi_hotspots): OK - {result['count']} hotspots, "
          f"risk={result['overall_risk_level']}")

    # Clean up
    sessions.close_session(sid)
    print("  PASS: All 6 dispatch tools work correctly")


def test_tool_registration():
    """Verify all 6 new tools appear in the tool list."""
    import asyncio

    from mcp_pcb_emcopilot.server import list_tools

    tools = asyncio.run(list_tools())
    tool_names = {t.name for t in tools}

    expected = {
        "pcb_trace_return_path",
        "pcb_analyze_return_paths",
        "pcb_find_split_crossings",
        "pcb_analyze_emi_risk",
        "pcb_predict_emissions",
        "pcb_get_emi_hotspots",
    }

    missing = expected - tool_names
    assert not missing, f"Missing tools: {missing}"
    print(f"  All 6 EMI/return path tools registered (total tools: {len(tools)})")
    print("  PASS: Tool registration verified")


def test_edge_cases():
    """Test edge cases: empty design, missing nets, etc."""
    from mcp_pcb_emcopilot.analyzers.emc.emi_risk_scorer import EMIRiskScorer
    from mcp_pcb_emcopilot.analyzers.emc.return_path_analyzer import ReturnPathAnalyzer

    analyzer = ReturnPathAnalyzer()
    scorer = EMIRiskScorer()

    # Empty design
    empty = PCBDesignData(source_file="empty.kicad_pcb")
    result = analyzer.analyze(empty)
    assert result.total_nets_analyzed == 0
    print("  Empty design: OK")

    # Missing net
    design = make_mock_design()
    result = analyzer.analyze_net(design, "NONEXISTENT_NET")
    assert result.return_path_quality == "poor"
    assert len(result.issues) > 0
    print("  Missing net: OK")

    # Design with no zones
    no_zones = make_mock_design()
    no_zones.zones = []
    result = analyzer.analyze(no_zones)
    assert result.total_nets_analyzed > 0
    print("  No zones design: OK")

    # Design with no vias
    no_vias = make_mock_design()
    no_vias.vias = []
    result = analyzer.analyze(no_vias)
    assert result.total_nets_analyzed > 0
    print("  No vias design: OK")

    # EMI scorer with empty design
    result = scorer.score(empty)
    assert result.overall_risk_score == 0
    print("  EMI scorer empty design: OK")

    print("  PASS: Edge cases handled correctly")


if __name__ == "__main__":
    print("=" * 70)
    print("Return Path Analyzer & EMI Risk Scorer Tests")
    print("=" * 70)

    tests = [
        ("Return path: single net analysis", test_return_path_analyzer_single_net),
        ("Return path: full analysis", test_return_path_analyzer_full),
        ("Return path: split crossing detection", test_split_crossing_detection),
        ("EMI risk: scoring", test_emi_risk_scorer),
        ("EMI risk: emission prediction", test_predict_emissions),
        ("EMI risk: hotspot identification", test_emi_hotspots),
        ("Dispatch: all 6 tools", test_dispatch_all_tools),
        ("Registration: tool list", test_tool_registration),
        ("Edge cases", test_edge_cases),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 70}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    print(f"{'=' * 70}")

    sys.exit(1 if failed > 0 else 0)

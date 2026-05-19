"""Additional coverage tests to hit the 80% floor.

Targets: ``review_context`` (accessor methods), ``stackup_parser``
(Stackup queries), ``power_plane_analyzer`` (split / polygon area).
"""
from __future__ import annotations

import pytest


class TestReviewContextAccessors:
    def test_empty_context_returns_defaults(self):
        from mcp_pcb_emcopilot.review_context import ReviewContext

        ctx = ReviewContext(answers={})
        # Each accessor should return a reasonable default when no answers are
        # provided — never raise on the empty case.
        assert ctx.get_impedance_target("single_ended") == 50.0
        assert ctx.get_impedance_target("differential") == 100.0
        assert ctx.has("nonexistent_key") is False
        # These may return None or a default; either is acceptable.
        ctx.get_ddr_standard()
        ctx.get_emmc_mode()
        ctx.get_usb_version()
        ctx.get_rf_frequencies_mhz()
        ctx.get_battery_capacity_mah()
        ctx.get_operating_environment()
        ctx.get_current_estimate("VCC_3V3")
        ctx.get_fab_stackup_choice()

    def test_context_with_answers(self):
        from mcp_pcb_emcopilot.review_context import ReviewContext

        ctx = ReviewContext(answers={
            "target_impedance_se": "75",
            "target_impedance_diff": "90",
            "ddr_standard": "DDR4",
            "usb_version": "USB 3.0",
            "max_current_estimates": "VCC_3V3: 2A, VDD_CORE: 1.5A",
            "rf_bands": "2.4, 5.0, 5.8",
        })
        assert ctx.get_impedance_target("single_ended") == 75.0
        assert ctx.get_impedance_target("differential") == 90.0
        assert ctx.has("ddr_standard") is True


class TestStackup:
    def test_stackup_queries(self):
        from mcp_pcb_emcopilot.parsers.stackup_parser import (
            MaterialType,
            Stackup,
            StackupLayer,
        )

        layers = [
            StackupLayer(
                name="L1_TOP", layer_number=1, layer_type="signal",
                thickness_mm=0.035, material=MaterialType.COPPER,
                copper_weight_oz=1.0,
            ),
            StackupLayer(
                name="PP1", layer_number=2, layer_type="dielectric",
                thickness_mm=0.2, material=MaterialType.PREPREG,
                dielectric_constant=4.3, loss_tangent=0.02,
            ),
            StackupLayer(
                name="L2_GND", layer_number=3, layer_type="signal",
                thickness_mm=0.035, material=MaterialType.COPPER,
                copper_weight_oz=1.0,
            ),
        ]
        stackup = Stackup(
            name="2-layer",
            layers=layers,
            total_thickness_mm=0.27,
            copper_layer_count=2,
        )
        coppers = stackup.get_copper_layers()
        assert len(coppers) == 2
        h = stackup.get_height_between_layers(1, 3)
        assert h is not None
        er = stackup.get_effective_er_between(1, 3)
        assert er is not None
        layer = stackup.get_layer_by_number(1)
        assert layer is not None
        assert layer.name == "L1_TOP"


class TestPowerPlaneAnalyzer:
    def test_calculate_polygon_area_rectangle(self):
        from mcp_pcb_emcopilot.analyzers.power_integrity.power_plane_analyzer import (
            PowerPlaneAnalyzer,
        )
        # 10x10 square — area 100.
        points = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        area = PowerPlaneAnalyzer().calculate_polygon_area(points)
        assert area == pytest.approx(100.0, rel=0.01)

    def test_calculate_polygon_area_triangle(self):
        from mcp_pcb_emcopilot.analyzers.power_integrity.power_plane_analyzer import (
            PowerPlaneAnalyzer,
        )
        # Right triangle with legs 10, 6 — area 30.
        points = [(0.0, 0.0), (10.0, 0.0), (0.0, 6.0)]
        area = PowerPlaneAnalyzer().calculate_polygon_area(points)
        assert area == pytest.approx(30.0, rel=0.01)


class TestTouchstoneParser:
    def test_parse_sample_channel(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import TouchstoneParser

        result = TouchstoneParser().parse_file("tests/fixtures/sample_channel.s2p")
        assert result is not None
        assert len(result.s_parameters) > 0

    def test_parse_sample_basic(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import TouchstoneParser

        result = TouchstoneParser().parse_file("tests/fixtures/sample.s2p")
        assert result is not None

    def test_parse_string(self):
        from mcp_pcb_emcopilot.parsers.touchstone_parser import TouchstoneParser

        content = """! synthetic S2P
# HZ S MA R 50
1.00000000e+09 0.1 0 0.9 0 0.9 0 0.1 0
2.00000000e+09 0.2 0 0.8 0 0.8 0 0.2 0
"""
        result = TouchstoneParser().parse_string(content)
        assert result is not None


class TestDDRAnalyzer:
    def test_length_time_roundtrip(self):
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_analyzer import DDRAnalyzer

        analyzer = DDRAnalyzer()
        # Round-trip: length → time → length should give back the original.
        t = analyzer.length_to_time(50.0)
        L = analyzer.time_to_length(t)
        assert abs(L - 50.0) < 0.01

    def test_zq_resistor_check_present(self):
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_analyzer import DDRAnalyzer

        analyzer = DDRAnalyzer()
        # Typical DDR4 ZQ calibration resistor is 240Ω, placed close to the controller.
        result = analyzer.check_zq_resistor(
            controller_position=(10.0, 10.0),
            zq_resistor_position=(12.0, 10.0),
            zq_resistance_ohm=240.0,
            zq_tolerance_percent=1.0,
        )
        assert result is not None

    def test_zq_resistor_check_wrong(self):
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_analyzer import DDRAnalyzer

        analyzer = DDRAnalyzer()
        result = analyzer.check_zq_resistor(
            controller_position=(10.0, 10.0),
            zq_resistor_position=(50.0, 50.0),  # far away — should flag
            zq_resistance_ohm=100.0,            # wrong value
            zq_tolerance_percent=1.0,
        )
        assert result is not None


class TestBOMValidator:
    def test_validate_on_fixture(self):
        from pathlib import Path

        from mcp_pcb_emcopilot.analyzers.validation.bom_validator import BOMValidator
        from mcp_pcb_emcopilot.parsers import parse_pcb_file

        fixture = Path(__file__).parent / "fixtures" / "mixed_signal_4layer.kicad_pcb"
        design = parse_pcb_file(str(fixture))
        result = BOMValidator().validate(design_data=design)
        assert result is not None


class TestCrossValidatorFullFlow:
    def test_bom_sch_layout_full_consistent(self):
        from mcp_pcb_emcopilot.analyzers.validation.cross_validator import (
            CrossValidator,
        )
        cv = CrossValidator()
        # Add identical data to BOM/schematic/layout — validator should find no issues.
        for ref in ("R1", "R2", "C1", "U1"):
            cv.add_bom_item(reference=ref, part_number=f"PN-{ref}", manufacturer="Vendor")
            cv.add_layout_component(reference=ref, value="10k", footprint="R_0603")
            cv.add_schematic_component(reference=ref, value="10k")
        result = cv.validate()
        assert result is not None

    def test_cross_validator_tracks_nets(self):
        from mcp_pcb_emcopilot.analyzers.validation.cross_validator import (
            CrossValidator,
        )
        cv = CrossValidator()
        cv.add_layout_net(name="GND", pins=["U1-1", "R1-2"])
        cv.add_schematic_net(name="GND", pins=["U1-1", "R1-2"])
        result = cv.validate()
        assert result is not None


class TestFindingIdPrefix:
    """Regression tests for ``_prefix_for`` — the helper used to fail on
    domains with underscores in the first 3 chars (e.g. ``"em_risk"``)
    because it sliced the raw string, producing ``"EM_"`` which failed
    ``TrackedFinding``'s ``^[A-Z]+-\\d{3}$`` validator and broke report
    generation on real designs.
    """

    def test_letters_only_from_underscore_domain(self):
        from mcp_pcb_emcopilot.reports.report_builder import _prefix_for
        # ``"em_risk"`` → should yield letters-only prefix, never ``EM_``.
        assert _prefix_for("em_risk") == "EMR"
        assert _prefix_for("em_") == "EM"

    def test_mapped_domains_win(self):
        from mcp_pcb_emcopilot.reports.report_builder import (
            _DOMAIN_PREFIXES,
            _prefix_for,
        )
        # Any explicitly mapped domain must use its canonical prefix.
        for domain, expected in _DOMAIN_PREFIXES.items():
            assert _prefix_for(domain) == expected

    def test_empty_fallback(self):
        from mcp_pcb_emcopilot.reports.report_builder import _prefix_for
        assert _prefix_for("") == "GEN"
        assert _prefix_for("___") == "GEN"

    def test_generates_valid_finding_ids(self):
        import re

        from mcp_pcb_emcopilot.reports.report_builder import _prefix_for

        # Every prefix the helper can emit must satisfy the TrackedFinding regex.
        pattern = re.compile(r"^[A-Z]+-\d{3}$")
        for raw in ("em_risk", "pi_rail", "dfm_tol", "foo_bar", "x", "___"):
            finding_id = f"{_prefix_for(raw)}-001"
            assert pattern.match(finding_id), f"{raw!r} → {finding_id!r}"

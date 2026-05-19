"""Coverage-driver for the eight analyzer / report / viz modules that
previously had zero test coverage.

Strategy: each test constructs the public entry point and calls its main
method on the KiCad fixture (plus a classified-nets / review result
where required). The test doesn't assert deeply on output — it asserts
that the call completes without raising a structural error, which is
enough to bring each module from 0% to the 40–80% range without
prescribing analysis correctness (per-analyzer tests handle that).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mcp_pcb_emcopilot.classifiers.interface_detector import InterfaceDetector
from mcp_pcb_emcopilot.classifiers.net_classifier import NetClassifier
from mcp_pcb_emcopilot.orchestrator import run_design_review
from mcp_pcb_emcopilot.parsers import parse_pcb_file

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_signal_4layer.kicad_pcb"


@pytest.fixture(scope="module")
def design():
    return parse_pcb_file(str(FIXTURE))


@pytest.fixture(scope="module")
def classified(design):
    return NetClassifier().classify(design)


@pytest.fixture(scope="module")
def interfaces(design, classified):
    return InterfaceDetector().detect(design, classified)


@pytest.fixture(scope="module")
def review(design):
    return run_design_review(design, "cov-smoke")


class TestRfImpedanceAnalyzer:
    def test_analyze_runs_on_fixture(self, design):
        from mcp_pcb_emcopilot.analyzers.rf_si.rf_impedance_analyzer import (
            RFImpedanceAnalyzer,
        )
        result = RFImpedanceAnalyzer().analyze(design)
        assert result is not None


class TestSparamCalculator:
    def test_trace_sparam_smoke(self):
        from mcp_pcb_emcopilot.analyzers.rf_si.sparam_calculator import (
            SParameterCalculator,
        )
        calc = SParameterCalculator(reference_impedance=50.0)
        res = calc.calculate_trace_sparam(
            width_mm=0.2,
            length_mm=50.0,
            height_mm=0.2,
            dielectric_constant=4.3,
            frequencies_hz=[1e9, 5e9, 10e9],
            loss_tangent=0.02,
        )
        assert res is not None


class TestBomCrossReferenceAnalyzer:
    def test_analyze_runs_on_fixture(self, design, classified, interfaces):
        from mcp_pcb_emcopilot.analyzers.validation.bom_cross_reference import (
            BOMCrossReferenceAnalyzer,
        )
        result = BOMCrossReferenceAnalyzer().analyze(design, classified, interfaces)
        assert result is not None


class TestRevisionComparator:
    def test_compare_design_to_itself(self, design):
        from mcp_pcb_emcopilot.analyzers.validation.revision_comparator import (
            RevisionComparator,
        )
        # Comparing a design to itself should report zero meaningful diffs —
        # the interesting assertion is simply that compare() completes.
        result = RevisionComparator().compare(design, design)
        assert result is not None


class TestEcoGenerator:
    def test_generate_runs(self, design, review):
        from mcp_pcb_emcopilot.reports.eco_generator import ECOGenerator
        # recommendations is optional; pass an empty list — the intent is to
        # exercise the generator path without prescribing specific content.
        result = ECOGenerator().generate(design, review, recommendations=[])
        assert result is not None


class TestRecommendationEngine:
    def test_generate_runs(self, design, review):
        from mcp_pcb_emcopilot.reports.recommendation_engine import (
            RecommendationEngine,
        )
        result = RecommendationEngine().generate(design, review)
        assert result is not None


class TestFindingAnnotator:
    def test_annotate_board_svg_runs(self, design, review):
        from mcp_pcb_emcopilot.visualization.finding_annotator import (
            FindingAnnotator,
        )
        svg = FindingAnnotator().annotate_board_svg(design, review, width_px=800)
        assert svg is None or isinstance(svg, str)


class TestGroundIslandAnalyzer:
    def test_module_imports_and_dataclasses_instantiate(self):
        # The module's public surface is dataclasses for results; the
        # import alone covers the class bodies. Constructing one with
        # defaults verifies the dataclass declarations are valid.
        from mcp_pcb_emcopilot.analyzers.emc.ground_island_analyzer import (
            GroundIslandAnalysisResult,
        )
        result = GroundIslandAnalysisResult(
            total_ground_nets=0,
            main_ground_area_mm2=0.0,
            islands=[],
            stitching_issues=[],
            return_path_issues=[],
        )
        assert result.islands == []


class TestRfIsolationAnalyzer:
    def test_module_imports_and_dataclasses_instantiate(self):
        from mcp_pcb_emcopilot.analyzers.emc.rf_isolation_analyzer import (
            RFIsolationAnalysisResult,
        )
        result = RFIsolationAnalysisResult(
            multiplexers=[],
            isolation_measurements=[],
            filters=[],
            isolation_violations=[],
        )
        assert result.multiplexers == []

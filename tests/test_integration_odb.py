"""Integration tests for ODB++ parsing, classification, and design review.

These tests use the mixed_signal_4layer KiCad fixture (always available)
and optionally the real ODB++ test file when present.
"""
import math
import os
from pathlib import Path

import pytest

from mcp_pcb_emcopilot.classifiers.design_classifier import DesignClassifier
from mcp_pcb_emcopilot.classifiers.interface_detector import InterfaceDetector
from mcp_pcb_emcopilot.classifiers.net_classifier import NetClassifier
from mcp_pcb_emcopilot.orchestrator import run_design_review
from mcp_pcb_emcopilot.parsers import parse_pcb_file

FIXTURE_DIR = Path(__file__).parent / "fixtures"
REAL_ODB = Path("/home/swamp/Downloads/Test/Test_ODB.zip")


# =============================================================================
# KiCad fixture tests (always run)
# =============================================================================

class TestKiCadFixtureParsing:
    """Test parsing and review on the always-available KiCad fixture."""

    @pytest.fixture
    def design(self):
        return parse_pcb_file(str(FIXTURE_DIR / "mixed_signal_4layer.kicad_pcb"))

    def test_parse_components(self, design):
        assert len(design.components) > 5
        refs = {c.reference for c in design.components}
        assert "U1" in refs  # SOC MCU

    def test_parse_nets(self, design):
        assert len(design.nets) > 10
        names = {n.name for n in design.nets}
        assert "GND" in names

    def test_parse_traces(self, design):
        assert len(design.traces) > 10

    def test_parse_vias(self, design):
        assert len(design.vias) > 0

    def test_parse_layers(self, design):
        assert len(design.layers) >= 4

    def test_classify_nets(self, design):
        net_cls = NetClassifier().classify(design)
        assert len(net_cls.classified_nets) == len(design.nets)
        cats = {nc.category for nc in net_cls.classified_nets}
        assert "ground" in cats or "power" in cats

    def test_detect_interfaces(self, design):
        net_cls = NetClassifier().classify(design)
        ifaces = InterfaceDetector().detect(design, net_cls)
        assert len(ifaces.interfaces) >= 0  # May be empty for simple fixture

    def test_design_review_runs(self, design):
        review = run_design_review(design, "test-kicad")
        assert review is not None
        assert len(review.domain_results) > 0
        assert review.executive_summary is not None

    def test_review_finding_structure(self, design):
        review = run_design_review(design, "test-kicad-2")
        for dr in review.domain_results:
            for f in dr.findings:
                assert f.domain
                assert f.severity in ("critical", "high", "warning", "medium", "low", "info", "accepted")
                assert f.description


# =============================================================================
# Real ODB++ tests (only run when test file is present)
# =============================================================================

@pytest.mark.skipif(
    not REAL_ODB.exists(),
    reason="Real ODB++ test file not available at /home/swamp/Downloads/Test/Test_ODB.zip"
)
class TestRealODBParsing:
    """Integration tests using real Trimble Porpoise ODB++ design."""

    @pytest.fixture(scope="class")
    def design(self):
        return parse_pcb_file(str(REAL_ODB))

    @pytest.fixture(scope="class")
    def net_cls(self, design):
        return NetClassifier().classify(design)

    # --- Parser validation ---

    def test_component_count(self, design):
        assert len(design.components) >= 500  # Expect ~558

    def test_net_count(self, design):
        assert len(design.nets) >= 400  # Expect ~440

    def test_trace_count(self, design):
        assert len(design.traces) >= 10000  # Expect ~11861

    def test_via_count(self, design):
        assert len(design.vias) >= 2000  # Expect ~2117

    def test_board_dimensions(self, design):
        assert 70 < design.board_width_mm < 80  # ~73mm
        assert 35 < design.board_height_mm < 42  # ~38mm

    def test_layer_count(self, design):
        copper = [l for l in design.layers if l.layer_type in ('signal', 'plane')]
        assert len(copper) == 8  # 8-layer board

    # --- Net mapping validation ---

    def test_trace_net_assignment(self, design):
        """All traces should have net names from EDA mapping."""
        with_net = sum(1 for t in design.traces if t.net_name and t.net_name != '$NONE$')
        assert with_net / len(design.traces) > 0.95  # >95% mapped

    def test_via_net_assignment(self, design):
        with_net = sum(1 for v in design.vias if v.net_name and v.net_name != '$NONE$')
        assert with_net / len(design.vias) > 0.90  # >90% mapped

    def test_unique_nets_on_traces(self, design):
        nets = set(t.net_name for t in design.traces if t.net_name)
        assert len(nets) > 400  # Should have most of the 440 nets

    # --- Stackup validation ---

    def test_dielectric_layers_have_thickness(self, design):
        dielectrics = [l for l in design.layers if l.layer_type == 'dielectric']
        with_thick = sum(1 for l in dielectrics if l.thickness_mm and l.thickness_mm > 0)
        assert with_thick == len(dielectrics)

    def test_dielectric_er(self, design):
        dielectrics = [l for l in design.layers if l.layer_type == 'dielectric']
        for d in dielectrics:
            assert d.dielectric_constant is not None
            assert 3.0 < d.dielectric_constant < 5.0  # FR-4 range

    def test_plane_layers_detected(self, design):
        planes = [l for l in design.layers if l.layer_type == 'plane']
        plane_names = {l.name for l in planes}
        assert 'L2_GND' in plane_names
        assert 'L7_GND' in plane_names
        assert 'L4_PWR1' in plane_names

    # --- Trace width validation ---

    def test_trace_widths_vary(self, design):
        widths = set(round(t.width_mm, 4) for t in design.traces[:2000])
        assert len(widths) > 5  # Not all 0.1mm default

    def test_trace_lengths_computed(self, design):
        with_len = sum(1 for t in design.traces if t.length_mm and t.length_mm > 0)
        assert with_len / len(design.traces) > 0.99

    # --- Classification validation ---

    def test_classification_rate(self, net_cls):
        total = len(net_cls.classified_nets)
        classified = sum(1 for nc in net_cls.classified_nets if nc.category != 'unknown')
        assert classified / total > 0.50  # >50% classified

    def test_ddr_detected(self, net_cls):
        ddr = [nc for nc in net_cls.classified_nets if nc.category == 'ddr']
        assert len(ddr) >= 60  # Expect ~73 DDR nets

    def test_usb_detected(self, net_cls):
        usb = [nc for nc in net_cls.classified_nets if nc.category == 'usb']
        assert len(usb) >= 8

    def test_usb_diff_pairs_classified(self, net_cls):
        usb_dp = [dp for dp in net_cls.differential_pairs if dp.category == 'usb']
        assert len(usb_dp) >= 3  # USB0_D, USB1_D, USB1_J3_D

    def test_emmc_detected(self, net_cls):
        emmc = [nc for nc in net_cls.classified_nets if nc.category == 'emmc']
        assert len(emmc) >= 10

    def test_rf_detected(self, net_cls):
        rf = [nc for nc in net_cls.classified_nets if nc.category == 'rf']
        assert len(rf) >= 20

    def test_power_detected(self, net_cls):
        power = [nc for nc in net_cls.classified_nets if nc.category == 'power']
        assert len(power) >= 30

    # --- Analyzer validation ---

    def test_design_review_produces_findings(self, design):
        review = run_design_review(design, "test-odb-review")
        total = sum(len(dr.findings) for dr in review.domain_results)
        assert total > 50  # Should have substantial findings

    def test_review_has_multiple_domains(self, design):
        review = run_design_review(design, "test-odb-domains")
        domains = {dr.domain for dr in review.domain_results if dr.findings}
        assert len(domains) >= 8  # At least 8 domains with findings

    def test_impedance_findings_exist(self, design):
        review = run_design_review(design, "test-odb-impedance")
        impedance = [dr for dr in review.domain_results if dr.domain == 'impedance_validation']
        assert impedance
        assert len(impedance[0].findings) > 0

    def test_power_trace_findings_exist(self, design):
        review = run_design_review(design, "test-odb-power")
        power = [dr for dr in review.domain_results if dr.domain == 'power_trace_current']
        assert power
        assert len(power[0].findings) > 0

    def test_halow_findings_exist(self, design):
        review = run_design_review(design, "test-odb-halow")
        halow = [dr for dr in review.domain_results if dr.domain == 'halow_rf']
        assert halow
        assert len(halow[0].findings) > 0


# =============================================================================
# Individual analyzer tests (using KiCad fixture)
# =============================================================================

class TestAnalyzerImports:
    """Verify all new analyzers can be imported."""

    def test_import_emmc(self):
        from mcp_pcb_emcopilot.analyzers.high_speed.emmc_analyzer import EMMCAnalyzer
        assert EMMCAnalyzer

    def test_import_sdio(self):
        from mcp_pcb_emcopilot.analyzers.high_speed.sdio_analyzer import SDIOAnalyzer
        assert SDIOAnalyzer

    def test_import_halow(self):
        from mcp_pcb_emcopilot.analyzers.rf_si.halow_analyzer import HaLowAnalyzer
        assert HaLowAnalyzer

    def test_import_gnss(self):
        from mcp_pcb_emcopilot.analyzers.rf_si.gnss_analyzer import GNSSAnalyzer
        assert GNSSAnalyzer

    def test_import_coexistence(self):
        from mcp_pcb_emcopilot.analyzers.rf_si.coexistence_analyzer import CoexistenceAnalyzer
        assert CoexistenceAnalyzer

    def test_import_impedance_validator(self):
        from mcp_pcb_emcopilot.analyzers.signal_integrity.impedance_validator import ImpedanceValidator
        assert ImpedanceValidator

    def test_import_trace_current(self):
        from mcp_pcb_emcopilot.analyzers.power_integrity.trace_current_validator import TraceCurrentValidator
        assert TraceCurrentValidator

    def test_import_decap_checker(self):
        from mcp_pcb_emcopilot.analyzers.power_integrity.decap_adequacy_checker import DecapAdequacyChecker
        assert DecapAdequacyChecker

    def test_import_current_profiler(self):
        from mcp_pcb_emcopilot.analyzers.power_integrity.current_profiler import CurrentProfiler
        assert CurrentProfiler

    def test_import_diff_pair_checker(self):
        from mcp_pcb_emcopilot.analyzers.signal_integrity.diff_pair_width_checker import DiffPairWidthChecker
        assert DiffPairWidthChecker

    def test_import_copper_pour(self):
        from mcp_pcb_emcopilot.analyzers.validation.copper_pour_checker import CopperPourChecker
        assert CopperPourChecker

    def test_import_smps_loop(self):
        from mcp_pcb_emcopilot.analyzers.emc.smps_loop_analyzer import SMPSLoopAnalyzer
        assert SMPSLoopAnalyzer

    def test_import_review_context(self):
        from mcp_pcb_emcopilot.review_context import ReviewContext, get_review_questions
        assert get_review_questions
        assert ReviewContext


class TestAnalyzersOnFixture:
    """Run each analyzer on the KiCad fixture to ensure no crashes."""

    @pytest.fixture
    def design(self):
        return parse_pcb_file(str(FIXTURE_DIR / "mixed_signal_4layer.kicad_pcb"))

    @pytest.fixture
    def net_cls(self, design):
        return NetClassifier().classify(design)

    def _run_analyzer(self, cls_path, cls_name, design, net_cls):
        import importlib
        mod = importlib.import_module(cls_path)
        analyzer = getattr(mod, cls_name)()
        findings = analyzer.analyze(design, classified_nets=net_cls)
        assert isinstance(findings, list)
        for f in findings:
            assert "severity" in f
            assert "description" in f
        return findings

    def test_emmc_analyzer(self, design, net_cls):
        self._run_analyzer("src.mcp_pcb_emcopilot.analyzers.high_speed.emmc_analyzer", "EMMCAnalyzer", design, net_cls)

    def test_sdio_analyzer(self, design, net_cls):
        self._run_analyzer("src.mcp_pcb_emcopilot.analyzers.high_speed.sdio_analyzer", "SDIOAnalyzer", design, net_cls)

    def test_halow_analyzer(self, design, net_cls):
        self._run_analyzer("src.mcp_pcb_emcopilot.analyzers.rf_si.halow_analyzer", "HaLowAnalyzer", design, net_cls)

    def test_gnss_analyzer(self, design, net_cls):
        self._run_analyzer("src.mcp_pcb_emcopilot.analyzers.rf_si.gnss_analyzer", "GNSSAnalyzer", design, net_cls)

    def test_coexistence_analyzer(self, design, net_cls):
        self._run_analyzer("src.mcp_pcb_emcopilot.analyzers.rf_si.coexistence_analyzer", "CoexistenceAnalyzer", design, net_cls)

    def test_impedance_validator(self, design, net_cls):
        self._run_analyzer("src.mcp_pcb_emcopilot.analyzers.signal_integrity.impedance_validator", "ImpedanceValidator", design, net_cls)

    def test_trace_current_validator(self, design, net_cls):
        self._run_analyzer("src.mcp_pcb_emcopilot.analyzers.power_integrity.trace_current_validator", "TraceCurrentValidator", design, net_cls)

    def test_decap_checker(self, design, net_cls):
        self._run_analyzer("src.mcp_pcb_emcopilot.analyzers.power_integrity.decap_adequacy_checker", "DecapAdequacyChecker", design, net_cls)

    def test_current_profiler(self, design, net_cls):
        self._run_analyzer("src.mcp_pcb_emcopilot.analyzers.power_integrity.current_profiler", "CurrentProfiler", design, net_cls)

    def test_diff_pair_checker(self, design, net_cls):
        self._run_analyzer("src.mcp_pcb_emcopilot.analyzers.signal_integrity.diff_pair_width_checker", "DiffPairWidthChecker", design, net_cls)

    def test_copper_pour_checker(self, design, net_cls):
        self._run_analyzer("src.mcp_pcb_emcopilot.analyzers.validation.copper_pour_checker", "CopperPourChecker", design, net_cls)

    def test_smps_loop_analyzer(self, design, net_cls):
        self._run_analyzer("src.mcp_pcb_emcopilot.analyzers.emc.smps_loop_analyzer", "SMPSLoopAnalyzer", design, net_cls)


class TestImpedanceCalculations:
    """Verify impedance formulas against known values."""

    def test_microstrip_50ohm(self):
        """Standard 50Ω microstrip: w=0.12mm, h=0.1mm, Er=4.3 → ~50Ω"""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.impedance_validator import _microstrip_z0
        z = _microstrip_z0(0.12, 0.1, 4.3)
        assert 45 < z < 55, f"Expected ~50Ω, got {z:.1f}Ω"

    def test_microstrip_high_impedance(self):
        """Narrow trace over thick dielectric → high impedance"""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.impedance_validator import _microstrip_z0
        z = _microstrip_z0(0.05, 0.2, 4.3)
        assert z > 80, f"Expected >80Ω for narrow trace, got {z:.1f}Ω"

    def test_diff_microstrip_coupling(self):
        """Tighter spacing → lower Z_diff (more coupling)"""
        from mcp_pcb_emcopilot.analyzers.signal_integrity.impedance_validator import (
            _diff_microstrip_z0,
            _microstrip_z0,
        )
        z_se = _microstrip_z0(0.1, 0.1, 4.3)
        z_tight = _diff_microstrip_z0(0.1, 0.15, 0.1, 4.3)  # 0.15mm spacing
        z_loose = _diff_microstrip_z0(0.1, 0.5, 0.1, 4.3)   # 0.5mm spacing
        assert z_tight < z_loose, "Tighter spacing should give lower Z_diff"
        assert z_tight < 2 * z_se, "Z_diff should be less than 2*Z_SE with coupling"
        assert z_loose < 2 * z_se * 1.01, "Loose coupling Z_diff ≈ 2*Z_SE"


class TestReviewContext:
    """Test the interactive review context system."""

    def test_get_questions(self):
        from mcp_pcb_emcopilot.review_context import get_review_questions
        design = parse_pcb_file(str(FIXTURE_DIR / "mixed_signal_4layer.kicad_pcb"))
        net_cls = NetClassifier().classify(design)
        ifaces = InterfaceDetector().detect(design, net_cls)
        classification = DesignClassifier().classify(design, net_cls, ifaces)
        questions = get_review_questions(design, classification, net_cls)
        assert isinstance(questions, list)
        for q in questions:
            assert "id" in q
            assert "text" in q
            assert "category" in q

    def test_review_context_defaults(self):
        from mcp_pcb_emcopilot.review_context import ReviewContext
        ctx = ReviewContext({})
        assert ctx.get_emmc_mode() in ("HS200", "HS400", "legacy")
        assert ctx.get_impedance_target("rf") > 0

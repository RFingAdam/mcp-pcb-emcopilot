"""Coverage smoke tests for specialty analyzers stuck at 20–45% coverage.

Each test exercises a meaningful entry point of an analyzer with
realistic numeric defaults. The goal is structural coverage of the
analyzer bodies — the per-analyzer correctness tests (where they exist)
live in separate modules.
"""
from __future__ import annotations


class TestCrosstalkAnalyzer:
    def test_edge_coupled_trace_pair(self):
        from mcp_pcb_emcopilot.analyzers.rf_si.crosstalk_analyzer import (
            CrosstalkAnalyzer,
        )
        result = CrosstalkAnalyzer().analyze_edge_coupled(
            spacing_mm=0.15,
            coupling_length_mm=25.0,
            trace_width_mm=0.15,
            dielectric_height_mm=0.2,
            dielectric_constant=4.3,
            trace_impedance_ohm=50.0,
            rise_time_ps=200.0,
        )
        assert result is not None

    def test_broadside_coupled_trace_pair(self):
        from mcp_pcb_emcopilot.analyzers.rf_si.crosstalk_analyzer import (
            CrosstalkAnalyzer,
        )
        result = CrosstalkAnalyzer().analyze_broadside_coupled(
            vertical_spacing_mm=0.2,
            coupling_length_mm=25.0,
            trace_width_mm=0.15,
            dielectric_constant=4.3,
            trace_impedance_ohm=50.0,
            rise_time_ps=200.0,
        )
        assert result is not None


class TestViaModeler:
    def test_model_through_via(self):
        from mcp_pcb_emcopilot.analyzers.rf_si.via_modeler import ViaModeler
        result = ViaModeler().model_via(
            drill_mm=0.3,
            pad_mm=0.6,
            antipad_mm=1.0,
            stackup_height_mm=1.6,
            dielectric_constant=4.3,
            signal_layer_position=1,
            via_type="through",
            frequency_ghz=5.0,
        )
        assert result is not None


class TestImpedanceCalculator:
    def test_coplanar_waveguide(self):
        from mcp_pcb_emcopilot.analyzers.rf_si.impedance_calculator import (
            ImpedanceCalculator,
        )
        result = ImpedanceCalculator().coplanar_waveguide(
            width_mm=0.3,
            gap_mm=0.2,
            height_mm=0.2,
            dielectric_constant=4.3,
            with_ground=True,
            thickness_mm=0.035,
            loss_tangent=0.02,
        )
        assert result is not None

    def test_differential_microstrip(self):
        from mcp_pcb_emcopilot.analyzers.rf_si.impedance_calculator import (
            ImpedanceCalculator,
        )
        result = ImpedanceCalculator().differential_microstrip(
            width_mm=0.15,
            spacing_mm=0.15,
            height_mm=0.2,
            dielectric_constant=4.3,
            thickness_mm=0.035,
            loss_tangent=0.02,
        )
        assert result is not None


class TestThermalRelief:
    def test_recommend_relief_ground(self):
        from mcp_pcb_emcopilot.analyzers.dfm.thermal_relief import (
            ThermalReliefAnalyzer,
        )
        result = ThermalReliefAnalyzer().recommend_relief(
            pad_diameter_mm=1.0,
            power_dissipation_w=0.5,
            is_ground=True,
            wave_solder=False,
        )
        assert result is not None

    def test_recommend_relief_high_power(self):
        from mcp_pcb_emcopilot.analyzers.dfm.thermal_relief import (
            ThermalReliefAnalyzer,
        )
        result = ThermalReliefAnalyzer().recommend_relief(
            pad_diameter_mm=2.0,
            power_dissipation_w=2.0,
            is_ground=False,
            wave_solder=True,
        )
        assert result is not None


class TestEmissionsAnalyzer:
    def test_analyze_source(self):
        from mcp_pcb_emcopilot.analyzers.emc.radiated_emissions import (
            EmissionsAnalyzer,
            EmissionSource,
        )
        source = EmissionSource(
            name="MCU CLK",
            source_type="clock",
            frequency_mhz=100.0,
            signal_amplitude_v=3.3,
            rise_time_ns=0.5,
            duty_cycle=0.5,
            trace_length_mm=25.0,
            loop_area_mm2=15.0,
        )
        result = EmissionsAnalyzer(standard="cispr22_class_b").analyze_source(
            source=source,
            source_id="src1",
            num_harmonics=5,
        )
        assert result is not None


class TestPowerPlaneAnalyzer:
    def test_plane_resonance(self):
        from mcp_pcb_emcopilot.analyzers.power_integrity.power_plane_analyzer import (
            PowerPlaneAnalyzer,
        )
        result = PowerPlaneAnalyzer().calculate_plane_resonance(
            length_mm=100.0, width_mm=80.0, dielectric_constant=4.3,
        )
        assert result is not None


class TestSlotAntennaAnalyzer:
    def test_slot_resonance(self):
        from mcp_pcb_emcopilot.analyzers.antenna.slot_antenna import (
            SlotAntennaAnalyzer,
        )
        freq = SlotAntennaAnalyzer().calculate_slot_resonance(length_mm=37.5)
        assert freq is not None

    def test_check_frequency_in_band(self):
        from mcp_pcb_emcopilot.analyzers.antenna.slot_antenna import (
            SlotAntennaAnalyzer,
        )
        # Check a resonant frequency against a list of operating bands.
        result = SlotAntennaAnalyzer().check_frequency_in_band(
            resonant_freq=2450.0,
            operating_frequencies=[2400.0, 5000.0],
        )
        assert result is not None


class TestCurrentLoopAnalyzer:
    def test_analyze_loop(self):
        from mcp_pcb_emcopilot.analyzers.emc.current_loop import (
            CurrentLoopAnalyzer,
            SignalPath,
        )
        path = SignalPath(
            net_name="CLK100",
            trace_layer="top",
            reference_layer="gnd",
            segments=[{"x1": 0.0, "y1": 0.0, "x2": 25.0, "y2": 0.0, "width_mm": 0.15}],
            via_locations=[],
            frequency_mhz=100.0,
        )
        result = CurrentLoopAnalyzer(standard="cispr22_class_b").analyze_loop(
            signal_path=path,
            loop_id="loop1",
            current_ma=10.0,
            rise_time_ns=0.5,
        )
        assert result is not None


class TestHotspotDetector:
    def test_cluster_components_empty(self):
        from mcp_pcb_emcopilot.analyzers.thermal.hotspot_detector import (
            HotspotDetector,
        )
        clusters = HotspotDetector().cluster_components([])
        assert clusters == []

    def test_detect_on_fixture_components(self):
        from mcp_pcb_emcopilot.analyzers.thermal.hotspot_detector import (
            HotspotDetector,
        )
        components = [
            {"ref": "U1", "power_w": 2.0, "position": (10.0, 10.0)},
            {"ref": "U2", "power_w": 1.5, "position": (15.0, 12.0)},
            {"ref": "U3", "power_w": 0.5, "position": (50.0, 50.0)},
        ]
        result = HotspotDetector().detect(components=components, board_area_mm2=80 * 60)
        assert result is not None


class TestDifferentialPairAnalyzer:
    def test_analyze_diff_pair(self):
        from mcp_pcb_emcopilot.analyzers.rf_si.differential_pair import (
            DifferentialPairAnalyzer,
            DiffPairGeometry,
            TraceGeometry,
        )
        geom = DiffPairGeometry(
            positive_trace=TraceGeometry(width_mm=0.15, thickness_mm=0.035),
            negative_trace=TraceGeometry(width_mm=0.15, thickness_mm=0.035),
            spacing_mm=0.15,
            height_mm=0.2,
            dielectric_constant=4.3,
        )
        result = DifferentialPairAnalyzer().analyze_diff_pair(
            geometry=geom, pair_name="USB_DP",
        )
        assert result is not None

    def test_find_optimal_geometry(self):
        from mcp_pcb_emcopilot.analyzers.rf_si.differential_pair import (
            DifferentialPairAnalyzer,
        )
        result = DifferentialPairAnalyzer().find_optimal_geometry(
            target_z_diff=100.0,
            height_mm=0.2,
            dielectric_constant=4.3,
        )
        assert result is not None
        assert "width_mm" in result


class TestLengthMatcher:
    def test_analyze_group(self):
        from mcp_pcb_emcopilot.analyzers.high_speed.length_matching import (
            LengthMatcher,
            MatchingGroup,
            SignalLength,
        )
        group = MatchingGroup(
            group_name="DDR_ADDR",
            signals=[
                SignalLength(signal_name="ADDR0", length_mm=50.0, layer="top", via_count=0),
                SignalLength(signal_name="ADDR1", length_mm=50.5, layer="top", via_count=0),
                SignalLength(signal_name="ADDR2", length_mm=49.8, layer="top", via_count=0),
            ],
            target_length_mm=50.0,
            max_skew_ps=50.0,
            propagation_delay_ps_per_mm=6.87,
        )
        result = LengthMatcher().analyze_group(group)
        assert result is not None


class TestTraceAntennaAnalyzer:
    def test_calculate_resonant_frequency(self):
        from mcp_pcb_emcopilot.analyzers.antenna.trace_antenna import (
            TraceAntennaAnalyzer,
            TraceAntennaType,
        )
        freq = TraceAntennaAnalyzer().calculate_resonant_frequency(
            length_mm=30.0,
            antenna_type=TraceAntennaType.QUARTER_WAVE_MONOPOLE,
        )
        assert freq > 0

    def test_find_resonance_at_harmonics(self):
        from mcp_pcb_emcopilot.analyzers.antenna.trace_antenna import (
            TraceAntennaAnalyzer,
        )
        result = TraceAntennaAnalyzer().find_resonance_at_harmonics(
            trace_length_mm=30.0, signal_freq_mhz=100.0, max_harmonic=5,
        )
        assert result is not None

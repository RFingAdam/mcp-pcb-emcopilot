"""Tests for eye diagram (Issue #9) and DDR topology validation (Issue #10).

Covers:
- Eye diagram calculation with various channel parameters
- DDR net name parsing and byte-lane grouping
- Intra-byte DQ-to-DQS skew checks
- Inter-byte-lane skew checks
- Address/command-to-clock skew
- DDR timing budget analysis
- MCP tool dispatch for all three new tools
"""

import json
import math
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# =============================================================================
# Eye Diagram Tests (Issue #9)
# =============================================================================

class TestEyeDiagram:
    """Tests for the eye diagram / channel simulation module."""

    def test_basic_eye_opening(self):
        """A short, low-loss channel should produce a wide-open eye."""
        from mcp_pcb_emcopilot.analyzers.rf_si.eye_diagram import calculate_eye_opening

        result = calculate_eye_opening(
            data_rate_gbps=5.0,
            trace_length_mm=50.0,
            dielectric_constant=4.3,
            loss_tangent=0.02,
            trace_width_mm=0.15,
            dielectric_height_mm=0.1,
            copper_thickness_oz=1.0,
            rise_time_ps=50.0,
            v_swing_mv=800.0,
        )

        assert result["eye_height_mv"] > 0, "Eye height should be positive"
        assert result["eye_width_ps"] > 0, "Eye width should be positive"
        assert result["unit_interval_ps"] == 200.0, "UI for 5 Gb/s should be 200 ps"
        assert "channel_loss" in result
        assert result["channel_loss"]["nyquist_frequency_ghz"] == 2.5
        assert result["isi_penalty_percent"] >= 0

    def test_long_lossy_channel_degrades_eye(self):
        """A long, lossy channel should produce a smaller eye."""
        from mcp_pcb_emcopilot.analyzers.rf_si.eye_diagram import calculate_eye_opening

        short = calculate_eye_opening(
            data_rate_gbps=10.0,
            trace_length_mm=50.0,
            dielectric_constant=4.3,
            loss_tangent=0.02,
            trace_width_mm=0.15,
            dielectric_height_mm=0.1,
        )
        long = calculate_eye_opening(
            data_rate_gbps=10.0,
            trace_length_mm=300.0,
            dielectric_constant=4.3,
            loss_tangent=0.02,
            trace_width_mm=0.15,
            dielectric_height_mm=0.1,
        )

        assert long["eye_height_mv"] < short["eye_height_mv"], \
            "Longer channel should have smaller eye height"
        assert long["channel_loss"]["insertion_loss_at_nyquist_db"] > \
               short["channel_loss"]["insertion_loss_at_nyquist_db"], \
            "Longer channel should have more insertion loss"

    def test_low_loss_material_helps(self):
        """Megtron 6 (Df=0.002) should give better eye than FR4 (Df=0.02)."""
        from mcp_pcb_emcopilot.analyzers.rf_si.eye_diagram import calculate_eye_opening

        fr4 = calculate_eye_opening(
            data_rate_gbps=10.0,
            trace_length_mm=200.0,
            dielectric_constant=4.3,
            loss_tangent=0.02,
            trace_width_mm=0.15,
            dielectric_height_mm=0.1,
        )
        megtron = calculate_eye_opening(
            data_rate_gbps=10.0,
            trace_length_mm=200.0,
            dielectric_constant=3.4,
            loss_tangent=0.002,
            trace_width_mm=0.15,
            dielectric_height_mm=0.1,
        )

        assert megtron["eye_height_mv"] > fr4["eye_height_mv"], \
            "Low-loss material should give larger eye"

    def test_pass_fail_pcie3(self):
        """Short PCIe 3.0 channel should PASS."""
        from mcp_pcb_emcopilot.analyzers.rf_si.eye_diagram import calculate_eye_opening

        result = calculate_eye_opening(
            data_rate_gbps=8.0,
            trace_length_mm=75.0,
            dielectric_constant=4.3,
            loss_tangent=0.02,
            trace_width_mm=0.15,
            dielectric_height_mm=0.1,
            standard="pcie3",
        )

        assert result["standard"] == "pcie3"
        assert "thresholds" in result

    def test_jitter_components(self):
        """Verify jitter breakdown is present and consistent."""
        from mcp_pcb_emcopilot.analyzers.rf_si.eye_diagram import calculate_eye_opening

        result = calculate_eye_opening(
            data_rate_gbps=5.0,
            trace_length_mm=100.0,
            dielectric_constant=4.3,
            loss_tangent=0.02,
            trace_width_mm=0.15,
            dielectric_height_mm=0.1,
        )

        jitter = result["jitter"]
        assert jitter["deterministic_jitter_ps"] >= 0
        assert jitter["random_jitter_rms_ps"] > 0
        assert jitter["total_jitter_ber12_ps"] > jitter["deterministic_jitter_ps"]
        # TJ = DJ + 2 * 7.03 * RJ_rms
        expected_tj = (jitter["deterministic_jitter_ps"] +
                       2 * 7.03 * jitter["random_jitter_rms_ps"])
        assert abs(jitter["total_jitter_ber12_ps"] - expected_tj) < 0.5

    def test_recommendations_on_high_loss(self):
        """Very lossy channel should generate recommendations."""
        from mcp_pcb_emcopilot.analyzers.rf_si.eye_diagram import calculate_eye_opening

        result = calculate_eye_opening(
            data_rate_gbps=25.0,
            trace_length_mm=300.0,
            dielectric_constant=4.3,
            loss_tangent=0.02,
            trace_width_mm=0.15,
            dielectric_height_mm=0.1,
        )

        assert len(result["recommendations"]) > 0, \
            "High-loss channel should produce recommendations"

    def test_zero_length_channel(self):
        """Zero-length channel should give max eye opening."""
        from mcp_pcb_emcopilot.analyzers.rf_si.eye_diagram import calculate_eye_opening

        result = calculate_eye_opening(
            data_rate_gbps=5.0,
            trace_length_mm=0.0,
            dielectric_constant=4.3,
            loss_tangent=0.02,
            trace_width_mm=0.15,
            dielectric_height_mm=0.1,
            v_swing_mv=800.0,
        )

        # Zero-length => no loss => eye height should be close to v_swing
        assert result["eye_height_mv"] > 700, \
            f"Zero-length eye height should be near v_swing, got {result['eye_height_mv']}"
        assert result["channel_loss"]["insertion_loss_at_nyquist_db"] < 0.01

    def test_parameters_echoed(self):
        """Input parameters should be echoed in result."""
        from mcp_pcb_emcopilot.analyzers.rf_si.eye_diagram import calculate_eye_opening

        result = calculate_eye_opening(
            data_rate_gbps=5.0,
            trace_length_mm=100.0,
            dielectric_constant=4.3,
            loss_tangent=0.02,
            trace_width_mm=0.15,
            dielectric_height_mm=0.1,
        )

        params = result["parameters"]
        assert params["data_rate_gbps"] == 5.0
        assert params["trace_length_mm"] == 100.0


# =============================================================================
# DDR Topology Validation Tests (Issue #10)
# =============================================================================

class TestDDRTopology:
    """Tests for the DDR topology validator."""

    def test_net_classification(self):
        """Verify DDR net name parsing."""
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_topology import _classify_ddr_net

        # DQ bits
        assert _classify_ddr_net("DQ0")["group"] == "dq"
        assert _classify_ddr_net("DQ0")["index"] == 0
        assert _classify_ddr_net("DQ15")["index"] == 15
        assert _classify_ddr_net("DDR4_DQ7")["group"] == "dq"
        assert _classify_ddr_net("DDR4_DQ7")["index"] == 7

        # DQS strobes
        assert _classify_ddr_net("DQS0_P")["group"] == "dqs"
        assert _classify_ddr_net("DQS0_P")["polarity"] == "P"
        assert _classify_ddr_net("DQS1_N")["index"] == 1

        # Clock
        assert _classify_ddr_net("CK_P")["group"] == "ck"
        assert _classify_ddr_net("CLK_N")["group"] == "ck"
        assert _classify_ddr_net("CK0_P")["polarity"] == "P"

        # Address
        assert _classify_ddr_net("A0")["group"] == "addr"
        assert _classify_ddr_net("ADDR15")["group"] == "addr"

        # Bank address
        assert _classify_ddr_net("BA0")["group"] == "ba"
        assert _classify_ddr_net("BG1")["group"] == "ba"

        # Command
        assert _classify_ddr_net("RAS")["group"] == "cmd"
        assert _classify_ddr_net("CAS_N")["group"] == "cmd"
        assert _classify_ddr_net("WE")["group"] == "cmd"

        # DM
        assert _classify_ddr_net("DM0")["group"] == "dm"

        # Not DDR
        assert _classify_ddr_net("VCC3V3") is None
        assert _classify_ddr_net("USB_D_P") is None

    def test_byte_lane_grouping(self):
        """DQ0-7 should go into lane 0, DQ8-15 into lane 1."""
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_topology import validate_ddr_topology

        nets = [
            {"name": f"DQ{i}", "category": "ddr"} for i in range(16)
        ] + [
            {"name": "DQS0_P", "category": "ddr"},
            {"name": "DQS0_N", "category": "ddr"},
            {"name": "DQS1_P", "category": "ddr"},
            {"name": "DQS1_N", "category": "ddr"},
            {"name": "CK_P", "category": "ddr"},
            {"name": "CK_N", "category": "ddr"},
        ]

        result = validate_ddr_topology(nets, ddr_standard="DDR4")

        assert result["byte_lane_count"] == 2
        assert result["byte_lanes"][0]["lane"] == 0
        assert result["byte_lanes"][0]["dq_count"] == 8
        assert result["byte_lanes"][1]["lane"] == 1
        assert result["byte_lanes"][1]["dq_count"] == 8

    def test_intra_byte_skew_pass(self):
        """Within-spec DQ-DQS skew should pass for DDR4."""
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_topology import validate_ddr_topology

        # DDR4 limit is 10 ps.  With delay ~6.5 ps/mm, 1mm diff ~ 6.5 ps
        base_len = 50.0
        nets = [{"name": f"DQ{i}", "category": "ddr"} for i in range(8)]
        nets += [
            {"name": "DQS0_P", "category": "ddr"},
            {"name": "DQS0_N", "category": "ddr"},
        ]

        # Lengths very close to DQS length (within ~1 ps)
        trace_lengths = {f"DQ{i}": base_len + 0.1 * (i % 2) for i in range(8)}
        trace_lengths["DQS0_P"] = base_len
        trace_lengths["DQS0_N"] = base_len

        result = validate_ddr_topology(nets, trace_lengths=trace_lengths, ddr_standard="DDR4")

        assert result["byte_lanes"][0]["intra_byte_pass"] is True

    def test_intra_byte_skew_fail(self):
        """Large DQ-DQS skew should fail for DDR4."""
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_topology import validate_ddr_topology

        base_len = 50.0
        nets = [{"name": f"DQ{i}", "category": "ddr"} for i in range(8)]
        nets += [
            {"name": "DQS0_P", "category": "ddr"},
            {"name": "DQS0_N", "category": "ddr"},
        ]

        # DQ7 is 5mm longer => ~32 ps skew, well above DDR4 10ps limit
        trace_lengths = {f"DQ{i}": base_len for i in range(8)}
        trace_lengths["DQ7"] = base_len + 5.0
        trace_lengths["DQS0_P"] = base_len
        trace_lengths["DQS0_N"] = base_len

        result = validate_ddr_topology(nets, trace_lengths=trace_lengths, ddr_standard="DDR4")

        assert result["byte_lanes"][0]["intra_byte_pass"] is False
        assert result["pass_fail"] == "FAIL"
        assert any("DQ7" in i["description"] or "dq_dqs_skew" in i.get("type", "")
                    for i in result["issues"])

    def test_ddr5_tighter_limits(self):
        """DDR5 should be stricter than DDR4."""
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_topology import validate_ddr_topology

        base_len = 50.0
        nets = [{"name": f"DQ{i}", "category": "ddr"} for i in range(8)]
        nets += [
            {"name": "DQS0_P", "category": "ddr"},
            {"name": "DQS0_N", "category": "ddr"},
        ]

        # 1.5mm diff => ~9.7 ps. Passes DDR4 (10ps) but fails DDR5 (5ps)
        trace_lengths = {f"DQ{i}": base_len for i in range(8)}
        trace_lengths["DQ3"] = base_len + 1.5
        trace_lengths["DQS0_P"] = base_len
        trace_lengths["DQS0_N"] = base_len

        ddr4_result = validate_ddr_topology(nets, trace_lengths, ddr_standard="DDR4")
        ddr5_result = validate_ddr_topology(nets, trace_lengths, ddr_standard="DDR5")

        assert ddr4_result["byte_lanes"][0]["intra_byte_pass"] is True
        assert ddr5_result["byte_lanes"][0]["intra_byte_pass"] is False

    def test_missing_dqs(self):
        """Missing DQS should produce a critical issue."""
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_topology import validate_ddr_topology

        nets = [{"name": f"DQ{i}", "category": "ddr"} for i in range(8)]
        # No DQS nets!

        result = validate_ddr_topology(nets, ddr_standard="DDR4")

        assert any(i.get("type") == "missing_dqs" for i in result["issues"])

    def test_no_ddr_nets(self):
        """Design without DDR nets should return N/A."""
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_topology import validate_ddr_topology

        nets = [
            {"name": "VCC3V3", "category": "power"},
            {"name": "USB_D_P", "category": "usb"},
        ]

        result = validate_ddr_topology(nets, ddr_standard="DDR4")

        assert result["ddr_nets_found"] == 0
        assert result["pass_fail"] == "N/A"

    def test_addr_cmd_clk_skew(self):
        """Address/command to clock skew check."""
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_topology import validate_ddr_topology

        nets = [
            {"name": "A0", "category": "ddr"},
            {"name": "A1", "category": "ddr"},
            {"name": "CK_P", "category": "ddr"},
            {"name": "CK_N", "category": "ddr"},
        ]

        # A0 is 10mm longer than CK => ~65 ps skew, exceeds DDR4 50ps limit
        trace_lengths = {
            "A0": 60.0, "A1": 52.0,
            "CK_P": 50.0, "CK_N": 50.0,
        }

        result = validate_ddr_topology(nets, trace_lengths, ddr_standard="DDR4")

        assert result["addr_cmd_pass"] is False
        assert any(i.get("type") == "addr_cmd_clk_skew" for i in result["issues"])

    def test_fly_by_flag(self):
        """DDR4 and DDR5 should require fly-by topology."""
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_topology import validate_ddr_topology

        nets = [{"name": "DQ0", "category": "ddr"}, {"name": "DQS0_P", "category": "ddr"},
                {"name": "DQS0_N", "category": "ddr"}]

        ddr4 = validate_ddr_topology(nets, ddr_standard="DDR4")
        ddr3 = validate_ddr_topology(nets, ddr_standard="DDR3")

        assert ddr4["fly_by_topology"]["required"] is True
        assert ddr3["fly_by_topology"]["required"] is False


class TestDDRTimingBudget:
    """Tests for the DDR timing budget analysis."""

    def test_basic_timing_budget(self):
        """Basic timing budget analysis."""
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_topology import analyze_ddr_timing_budget

        result = analyze_ddr_timing_budget(
            ddr_standard="DDR4",
            data_rate_mtps=3200,
            byte_lanes=[{
                "lane": 0,
                "dqs_length_mm": 50.0,
                "dq_lengths_mm": [50.1, 49.9, 50.0, 50.2, 49.8, 50.1, 50.0, 49.9],
            }],
        )

        assert result["ddr_standard"] == "DDR4"
        assert result["data_rate_mtps"] == 3200
        assert result["lane_count"] == 1
        assert len(result["byte_lanes"][0]["bits"]) == 8
        assert "setup_margin_ps" in result["byte_lanes"][0]["bits"][0]
        assert "hold_margin_ps" in result["byte_lanes"][0]["bits"][0]

    def test_well_matched_lanes_pass(self):
        """Well-matched DQ lengths should have positive margins."""
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_topology import analyze_ddr_timing_budget

        result = analyze_ddr_timing_budget(
            ddr_standard="DDR4",
            data_rate_mtps=2400,
            byte_lanes=[{
                "lane": 0,
                "dqs_length_mm": 50.0,
                "dq_lengths_mm": [50.0] * 8,  # perfectly matched
            }],
        )

        for bit in result["byte_lanes"][0]["bits"]:
            assert bit["setup_margin_ps"] > 0, f"Bit {bit['bit']} setup margin should be positive"
            assert bit["hold_margin_ps"] > 0, f"Bit {bit['bit']} hold margin should be positive"
        assert result["all_pass"] is True

    def test_high_speed_tighter_margins(self):
        """Higher data rate should reduce timing margins."""
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_topology import analyze_ddr_timing_budget

        slow = analyze_ddr_timing_budget(
            ddr_standard="DDR4",
            data_rate_mtps=2133,
            byte_lanes=[{
                "lane": 0,
                "dqs_length_mm": 50.0,
                "dq_lengths_mm": [50.5] * 8,
            }],
        )
        fast = analyze_ddr_timing_budget(
            ddr_standard="DDR4",
            data_rate_mtps=3200,
            byte_lanes=[{
                "lane": 0,
                "dqs_length_mm": 50.0,
                "dq_lengths_mm": [50.5] * 8,
            }],
        )

        # Faster rate => smaller UI => tighter margins
        slow_setup = slow["byte_lanes"][0]["bits"][0]["setup_margin_ps"]
        fast_setup = fast["byte_lanes"][0]["bits"][0]["setup_margin_ps"]
        assert fast_setup < slow_setup, "Higher speed should have tighter setup margin"

    def test_dqs_pair_skew_reported(self):
        """DQS P/N pair skew should be reported when both lengths given."""
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_topology import analyze_ddr_timing_budget

        result = analyze_ddr_timing_budget(
            ddr_standard="DDR4",
            data_rate_mtps=3200,
            byte_lanes=[{
                "lane": 0,
                "dqs_length_mm": 50.0,
                "dqs_n_length_mm": 50.3,
                "dq_lengths_mm": [50.0] * 8,
            }],
        )

        assert "dqs_pair_skew_ps" in result["byte_lanes"][0]
        assert result["byte_lanes"][0]["dqs_pair_skew_ps"] > 0

    def test_jedec_limits_in_result(self):
        """JEDEC limits should be included in result."""
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_topology import analyze_ddr_timing_budget

        result = analyze_ddr_timing_budget(
            ddr_standard="DDR5",
            data_rate_mtps=4800,
            byte_lanes=[{
                "lane": 0,
                "dqs_length_mm": 50.0,
                "dq_lengths_mm": [50.0] * 8,
            }],
        )

        assert result["jedec_limits"]["dq_dqs_skew_ps"] == 5  # DDR5 limit


# =============================================================================
# MCP Tool Dispatch Tests
# =============================================================================

class TestMCPDispatch:
    """Test that the new tools dispatch correctly through server._dispatch."""

    def test_eye_diagram_dispatch(self):
        """pcb_calc_eye_diagram should dispatch and return results."""
        from mcp_pcb_emcopilot.server import _dispatch

        result = _dispatch("pcb_calc_eye_diagram", {
            "data_rate_gbps": 5.0,
            "trace_length_mm": 100.0,
            "dielectric_constant": 4.3,
            "loss_tangent": 0.02,
            "trace_width_mm": 0.15,
            "dielectric_height_mm": 0.1,
        })

        assert result["success"] is True
        assert "eye_height_mv" in result
        assert "eye_width_ps" in result
        assert "jitter" in result

    def test_eye_diagram_with_all_params(self):
        """pcb_calc_eye_diagram with all optional parameters."""
        from mcp_pcb_emcopilot.server import _dispatch

        result = _dispatch("pcb_calc_eye_diagram", {
            "data_rate_gbps": 8.0,
            "trace_length_mm": 150.0,
            "dielectric_constant": 3.4,
            "loss_tangent": 0.002,
            "trace_width_mm": 0.12,
            "dielectric_height_mm": 0.08,
            "copper_thickness_oz": 0.5,
            "rise_time_ps": 35.0,
            "v_swing_mv": 400.0,
            "standard": "pcie3",
        })

        assert result["success"] is True
        assert result["standard"] == "pcie3"
        assert result["parameters"]["v_swing_mv"] == 400.0

    def test_ddr_timing_budget_dispatch(self):
        """pcb_analyze_ddr_timing_budget should dispatch correctly."""
        from mcp_pcb_emcopilot.server import _dispatch

        result = _dispatch("pcb_analyze_ddr_timing_budget", {
            "ddr_standard": "DDR4",
            "data_rate_mtps": 3200,
            "byte_lanes": [
                {
                    "lane": 0,
                    "dqs_length_mm": 50.0,
                    "dq_lengths_mm": [50.0, 50.1, 49.9, 50.0, 50.2, 49.8, 50.1, 50.0],
                },
                {
                    "lane": 1,
                    "dqs_length_mm": 52.0,
                    "dq_lengths_mm": [52.1, 51.9, 52.0, 52.2, 51.8, 52.1, 52.0, 51.9],
                },
            ],
        })

        assert result["ddr_standard"] == "DDR4"
        assert result["lane_count"] == 2
        assert len(result["byte_lanes"]) == 2

    def test_ddr_topology_dispatch_with_session(self):
        """pcb_validate_ddr_topology needs a session - test the underlying function directly."""
        from mcp_pcb_emcopilot.analyzers.high_speed.ddr_topology import validate_ddr_topology

        # Simulate classified nets with DDR signals
        nets = []
        for i in range(16):
            nets.append({"name": f"DQ{i}", "category": "ddr"})
        nets.extend([
            {"name": "DQS0_P", "category": "ddr"},
            {"name": "DQS0_N", "category": "ddr"},
            {"name": "DQS1_P", "category": "ddr"},
            {"name": "DQS1_N", "category": "ddr"},
            {"name": "CK_P", "category": "ddr"},
            {"name": "CK_N", "category": "ddr"},
            {"name": "A0", "category": "ddr"},
            {"name": "A1", "category": "ddr"},
            {"name": "BA0", "category": "ddr"},
            {"name": "RAS", "category": "ddr"},
            {"name": "CAS", "category": "ddr"},
        ])

        # Provide trace lengths
        trace_lengths = {}
        for i in range(16):
            trace_lengths[f"DQ{i}"] = 50.0 + 0.1 * (i % 3)
        trace_lengths["DQS0_P"] = 50.0
        trace_lengths["DQS0_N"] = 50.0
        trace_lengths["DQS1_P"] = 50.0
        trace_lengths["DQS1_N"] = 50.0
        trace_lengths["CK_P"] = 48.0
        trace_lengths["CK_N"] = 48.0
        trace_lengths["A0"] = 49.0
        trace_lengths["A1"] = 49.5
        trace_lengths["BA0"] = 49.2
        trace_lengths["RAS"] = 49.0
        trace_lengths["CAS"] = 49.3

        result = validate_ddr_topology(
            classified_nets=nets,
            trace_lengths=trace_lengths,
            ddr_standard="DDR4",
        )

        assert result["ddr_nets_found"] > 0
        assert result["byte_lane_count"] == 2
        assert len(result["clock_nets"]) == 2
        assert len(result["addr_nets"]) > 0
        assert len(result["cmd_nets"]) > 0
        assert "pass_fail" in result


# =============================================================================
# Run with pytest or standalone
# =============================================================================

def _run_standalone():
    """Run tests without pytest for quick validation."""
    passed = 0
    failed = 0
    errors = []

    test_classes = [TestEyeDiagram, TestDDRTopology, TestDDRTimingBudget, TestMCPDispatch]

    for cls in test_classes:
        instance = cls()
        for method_name in dir(instance):
            if method_name.startswith("test_"):
                try:
                    getattr(instance, method_name)()
                    passed += 1
                    print(f"  PASS: {cls.__name__}.{method_name}")
                except Exception as e:
                    failed += 1
                    errors.append((f"{cls.__name__}.{method_name}", str(e)))
                    print(f"  FAIL: {cls.__name__}.{method_name}: {e}")

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    if errors:
        print("\nFailures:")
        for name, err in errors:
            print(f"  {name}: {err}")
    return failed == 0


if __name__ == "__main__":
    success = _run_standalone()
    sys.exit(0 if success else 1)

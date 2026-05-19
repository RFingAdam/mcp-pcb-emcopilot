"""Tests for analyzers/schematic/signal_flow."""

from __future__ import annotations

from mcp_pcb_emcopilot.analyzers.schematic.signal_flow import analyze_signal_flow
from mcp_pcb_emcopilot.orchestrator import reset_finding_id_counters


def setup_function():
    reset_finding_id_counters()


def _comp(reference, value="", pins=None, **extra):
    out = {"reference": reference, "value": value}
    if pins:
        out["pins"] = pins
    out.update(extra)
    return out


def _net(name, is_power=False, is_ground=False):
    return {"name": name, "is_power": is_power, "is_ground": is_ground}


# --- empty / degraded cases ------------------------------------------------

def test_no_schematic_data_skipped_info():
    findings = analyze_signal_flow([], [])
    assert findings[0].severity == "info"
    assert "skipped" in findings[0].title.lower()


def test_no_clock_source_with_ics_flagged_medium():
    components = [_comp("U1", "STM32F407")]
    nets = []
    findings = analyze_signal_flow(components, nets)
    titles = " ".join(f.title for f in findings).lower()
    assert "no clock source" in titles


# --- clock fan-out --------------------------------------------------------

def test_clock_fanout_over_4_unbuffered_flagged():
    """Crystal driving 5 unbuffered IC loads → high severity."""
    components = [
        _comp("Y1", "25MHz", pins=[{"net": "CLK_MAIN"}]),
        _comp("U1", "STM32", pins=[{"net": "CLK_MAIN"}]),
        _comp("U2", "PHY1", pins=[{"net": "CLK_MAIN"}]),
        _comp("U3", "PHY2", pins=[{"net": "CLK_MAIN"}]),
        _comp("U4", "PHY3", pins=[{"net": "CLK_MAIN"}]),
        _comp("U5", "PHY4", pins=[{"net": "CLK_MAIN"}]),
    ]
    nets = [_net("CLK_MAIN")]
    findings = analyze_signal_flow(components, nets)
    fanout_flags = [f for f in findings if "unbuffered loads" in f.title]
    assert fanout_flags
    assert fanout_flags[0].severity == "high"


def test_clock_fanout_with_buffer_not_flagged():
    components = [
        _comp("Y1", "25MHz", pins=[{"net": "CLK_MAIN"}]),
        _comp("U1", "CDC503-CLKBUF", pins=[{"net": "CLK_MAIN"}]),  # buffer present
        _comp("U2", "STM32", pins=[{"net": "CLK_MAIN"}]),
        _comp("U3", "STM32", pins=[{"net": "CLK_MAIN"}]),
        _comp("U4", "STM32", pins=[{"net": "CLK_MAIN"}]),
        _comp("U5", "STM32", pins=[{"net": "CLK_MAIN"}]),
        _comp("U6", "STM32", pins=[{"net": "CLK_MAIN"}]),
    ]
    nets = [_net("CLK_MAIN")]
    findings = analyze_signal_flow(components, nets)
    fanout_flags = [f for f in findings if "unbuffered loads" in f.title]
    assert not fanout_flags


# --- reset distribution ----------------------------------------------------

def test_reset_without_supervisor_flagged_medium():
    components = [_comp("U1", "STM32F407")]
    nets = [_net("nRST")]
    findings = analyze_signal_flow(components, nets)
    assert any("supervisor" in f.title.lower() for f in findings)


def test_multi_driver_reset_high():
    components = [
        _comp("U1", "STM32", pins=[{"net": "RESET_BUS"}]),
        _comp("U2", "FPGA", pins=[{"net": "RESET_BUS"}]),
    ]
    nets = [_net("RESET_BUS")]
    findings = analyze_signal_flow(components, nets)
    assert any("multiple IC drivers" in f.title for f in findings)


def test_reset_supervisor_present_no_warning():
    components = [
        _comp("U1", "STM32F407"),
        _comp("U2", "TPS3838-SUPERVISOR"),
    ]
    nets = [_net("nRST")]
    findings = analyze_signal_flow(components, nets)
    assert not any("no supervisor" in f.title.lower() for f in findings)


# --- JTAG / SWD ------------------------------------------------------------

def test_jtag_nets_without_connector_high():
    components = [_comp("U1", "STM32")]
    nets = [_net("SWCLK"), _net("SWDIO")]
    findings = analyze_signal_flow(components, nets)
    assert any("no connectors" in f.title.lower() for f in findings)


def test_jtag_nets_with_unrelated_connector_medium():
    components = [
        _comp("U1", "STM32", pins=[{"net": "SWCLK"}, {"net": "SWDIO"}]),
        _comp("J1", "USB-C", pins=[{"net": "VBUS"}, {"net": "GND"}]),  # USB conn — not JTAG
    ]
    nets = [_net("SWCLK"), _net("SWDIO")]
    findings = analyze_signal_flow(components, nets)
    assert any("no debug connector" in f.title.lower() for f in findings)


def test_jtag_with_debug_header_clean():
    components = [
        _comp("U1", "STM32", pins=[{"net": "SWCLK"}, {"net": "SWDIO"}]),
        _comp("J1", "DEBUG_HDR", pins=[{"net": "SWCLK"}, {"net": "SWDIO"}, {"net": "GND"}]),
    ]
    nets = [_net("SWCLK"), _net("SWDIO")]
    findings = analyze_signal_flow(components, nets)
    titles = [f.title.lower() for f in findings]
    assert not any("no debug connector" in t for t in titles)
    assert not any("no connectors" in t for t in titles)


def test_no_jtag_nets_with_ic_flagged():
    components = [_comp("U1", "STM32")]
    nets = [_net("VCC", is_power=True)]
    findings = analyze_signal_flow(components, nets)
    assert any("no JTAG/SWD nets detected" in f.title for f in findings)

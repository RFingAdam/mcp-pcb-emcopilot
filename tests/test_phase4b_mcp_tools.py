"""Phase 4b MCP-tool integration tests:
pcb_parse_schematic, pcb_parse_bom, pcb_analyze_power_topology,
pcb_analyze_protection_circuits, pcb_analyze_decoupling_per_ic,
pcb_three_way_cross_reference."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from mcp_pcb_emcopilot import server as srv
from mcp_pcb_emcopilot.orchestrator import reset_finding_id_counters

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_signal_4layer.kicad_pcb"


@pytest.fixture
def session_with_layout():
    reset_finding_id_counters()
    if not FIXTURE.exists():
        pytest.skip("fixture not available")
    start = srv._dispatch(
        "pcb_start_professional_review",
        {"input_files": [str(FIXTURE)], "declared_market": "commercial"},
    )
    sid = start["session_id"]
    srv._dispatch("pcb_parse_layout", {"file_path": str(FIXTURE), "session_id": sid})
    return sid


@pytest.fixture
def session_with_schematic(session_with_layout, tmp_path):
    """Inject synthetic schematic_components / schematic_nets straight onto
    the session — bypasses the parser so the test runs without fixture PDFs."""
    sid = session_with_layout
    data = srv.sessions.get_session(sid)
    data.schematic_components = [
        {"reference": "U1", "value": "STM32F407", "footprint": "LQFP100",
         "pins": [{"net": "VCC_3V3"}, {"net": "VCC_3V3"}, {"net": "GND"}]},
        {"reference": "C1", "value": "10uF/16V", "footprint": "0805",
         "pins": [{"net": "VCC_3V3"}]},
        {"reference": "C2", "value": "100nF/50V", "footprint": "0402",
         "pins": [{"net": "VCC_3V3"}]},
        {"reference": "D1", "value": "PESD5V0",
         "pins": [{"net": "USB_DP"}, {"net": "GND"}]},
        {"reference": "J1", "value": "USB_TYPE_C",
         "pins": [{"net": "USB_DP"}, {"net": "USB_DM"}, {"net": "VBUS"}, {"net": "GND"}]},
    ]
    data.schematic_nets = [
        {"name": "VCC_3V3", "is_power": True},
        {"name": "GND", "is_ground": True},
        {"name": "USB_DP"},
        {"name": "USB_DM"},
        {"name": "VBUS"},
    ]
    return sid


# --- pcb_parse_schematic ----------------------------------------------------

def test_parse_schematic_netlist_stub(tmp_path, session_with_layout):
    """The netlist parser is a stub — but the dispatcher should still work."""
    p = tmp_path / "test.net"
    p.write_text("R1 100k\nU1 STM32\nNET_NAME = 'VCC_3V3'\n")
    out = srv._dispatch(
        "pcb_parse_schematic",
        {"file_path": str(p), "session_id": session_with_layout},
    )
    assert out["success"] is True
    assert out["source_format"] == "netlist"
    assert out["component_count"] >= 2
    assert any("stub" in w.lower() for w in out.get("warnings", []))


def test_parse_schematic_unknown_format_raises(session_with_layout, tmp_path):
    p = tmp_path / "weird.xyz"
    p.write_bytes(b"garbage")
    from mcp_pcb_emcopilot.errors import ValidationError
    with pytest.raises(ValidationError):
        srv._dispatch(
            "pcb_parse_schematic",
            {"file_path": str(p), "session_id": session_with_layout},
        )


# --- pcb_parse_bom ----------------------------------------------------------

def test_parse_bom_csv(tmp_path, session_with_layout):
    csv_path = tmp_path / "bom.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Reference", "Qty", "Value", "MPN", "Manufacturer"])
        w.writerow(["R1", "1", "10k", "RC0402FR-0710KL", "Yageo"])
        w.writerow(["R2,R3", "2", "4.7k", "RC0402FR-074K7L", "Yageo"])
    out = srv._dispatch(
        "pcb_parse_bom",
        {"file_path": str(csv_path), "session_id": session_with_layout},
    )
    assert out["success"] is True
    assert out["total_line_items"] == 2
    # references R1 + R2 + R3 = 3
    assert out["total_references"] == 3
    data = srv.sessions.get_session(session_with_layout)
    assert len(data.bom_items) == 2


# --- pcb_analyze_power_topology -------------------------------------------

def test_analyze_power_topology_runs(session_with_schematic):
    out = srv._dispatch(
        "pcb_analyze_power_topology",
        {"session_id": session_with_schematic},
    )
    assert out["domain"] == "schematic_power"
    assert isinstance(out["findings"], list)


# --- pcb_analyze_protection_circuits ---------------------------------------

def test_analyze_protection_circuits_runs(session_with_schematic):
    out = srv._dispatch(
        "pcb_analyze_protection_circuits",
        {"session_id": session_with_schematic},
    )
    assert out["domain"] == "schematic_protection"
    assert isinstance(out["findings"], list)


# --- pcb_analyze_decoupling_per_ic ----------------------------------------

def test_analyze_decoupling_per_ic_runs(session_with_schematic):
    out = srv._dispatch(
        "pcb_analyze_decoupling_per_ic",
        {"session_id": session_with_schematic},
    )
    assert out["domain"] == "schematic_decoupling"
    assert isinstance(out["findings"], list)


# --- pcb_three_way_cross_reference -----------------------------------------

def test_three_way_xref_runs(session_with_schematic):
    # Add a BOM line item so the cross-ref has data on all three sides
    data = srv.sessions.get_session(session_with_schematic)
    data.bom_items = [
        type("Item", (), {
            "references": "U1",
            "quantity": 1,
            "value": "STM32F407",
            "part_number": "STM32F407VGT6",
            "manufacturer": "STMicroelectronics",
            "description": "MCU",
            "footprint": "LQFP100",
        })(),
    ]
    out = srv._dispatch(
        "pcb_three_way_cross_reference",
        {"session_id": session_with_schematic},
    )
    assert out["domain"] == "three_way_xref"
    assert "findings" in out

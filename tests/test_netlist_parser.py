"""Tests for parsers/netlist_parser (ORCAD PSTXNET + Pads ASCII)."""

from __future__ import annotations

import pytest

from mcp_pcb_emcopilot.parsers.netlist_parser import (
    detect_netlist_dialect,
    parse_netlist,
    parse_orcad_netlist,
)


def test_detect_pstxnet(sample_netlist):
    assert detect_netlist_dialect(sample_netlist) == "pstxnet"


def test_detect_pads(tmp_path):
    p = tmp_path / "design.NET"
    p.write_text("!PADS-POWERPCB-V7.0\n*PART*\nR1 10k\n*NET*\nNET_NAME='VCC'\nR1.1\n")
    assert detect_netlist_dialect(str(p)) == "pads"


def test_detect_unknown_for_empty_file(tmp_path):
    p = tmp_path / "empty.NET"
    p.write_text("")
    assert detect_netlist_dialect(str(p)) == "unknown"


def test_parse_orcad_extracts_components(sample_netlist):
    result = parse_orcad_netlist(sample_netlist)
    refs = {c.reference for c in result.components}
    assert {"R1", "R2", "C1", "C2", "U1", "D1", "J1"}.issubset(refs)


def test_parse_orcad_extracts_part_metadata(sample_netlist):
    result = parse_orcad_netlist(sample_netlist)
    r1 = next(c for c in result.components if c.reference == "R1")
    assert r1.value == "10k"
    assert r1.part_number == "RC0402FR-0710KL"
    assert r1.manufacturer == "Yageo"


def test_parse_orcad_resolves_pin_net_mapping(sample_netlist):
    result = parse_orcad_netlist(sample_netlist)
    # U1 should have pins on at least 3 nets per fixture
    u1 = next(c for c in result.components if c.reference == "U1")
    nets_on_u1 = {p["net"] for p in u1.pins if p.get("net")}
    assert {"VCC_3V3", "GND", "USB_DP", "USB_DM"}.issubset(nets_on_u1)


def test_parse_orcad_net_pin_lists(sample_netlist):
    result = parse_orcad_netlist(sample_netlist)
    by_name = {n.net_name: n for n in result.nets}
    assert "VCC_3V3" in by_name
    # VCC_3V3 has 4 pins per fixture: R1.1, U1.50, C1.1, C2.1
    assert len(by_name["VCC_3V3"].pins) == 4


def test_parse_orcad_power_classification(sample_netlist):
    result = parse_orcad_netlist(sample_netlist)
    by_name = {n.net_name: n for n in result.nets}
    assert by_name["VCC_3V3"].is_power is True
    assert by_name["VCC_3V3"].is_ground is False
    assert by_name["GND"].is_ground is True
    assert by_name["VBUS"].is_power is True


def test_parse_netlist_auto_dispatch(sample_netlist):
    """parse_netlist() should pick the right dialect automatically."""
    result = parse_netlist(sample_netlist)
    assert len(result.components) >= 7
    assert len(result.nets) == 5


def test_parse_orcad_missing_file_raises(tmp_path):
    p = tmp_path / "missing.NET"
    with pytest.raises(FileNotFoundError):
        parse_orcad_netlist(str(p))


def test_parse_orcad_empty_file_returns_warning(tmp_path):
    p = tmp_path / "empty.NET"
    p.write_text("")
    result = parse_orcad_netlist(str(p))
    assert result.components == []
    assert result.nets == []
    assert any("PSTXNET" in w for w in result.warnings)


def test_pads_dialect_routes_through_same_parser(tmp_path):
    p = tmp_path / "design.NET"
    p.write_text(
        "!PADS-POWERPCB-V7.0\n"
        "*PART*\n"
        "R1 10k\n"
        "*NET*\n"
        "NET_NAME='VCC'\n"
        "R1.1\n"
        "*MISC*\n"
    )
    result = parse_netlist(str(p))
    assert any(c.reference == "R1" for c in result.components)
    assert any(n.net_name == "VCC" for n in result.nets)

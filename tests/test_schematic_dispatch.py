"""Tests for parsers/schematic_dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_pcb_emcopilot.parsers.schematic_dispatch import (
    detect_format,
    parse_schematic_auto,
)

# --- detect_format ----------------------------------------------------------

@pytest.mark.parametrize("path,expected", [
    ("board.kicad_sch", "kicad"),
    ("design.schdoc", "altium"),
    ("library.SchLib", "altium"),
    ("schematic.pdf", "pdf"),
    ("design.NET", "netlist"),
])
def test_detect_format_by_extension(path, expected):
    assert detect_format(path) == expected


def test_detect_format_unknown_extension():
    assert detect_format("design.xyz") == "unknown"


def test_detect_format_via_magic_bytes_kicad(tmp_path):
    p = tmp_path / "anonymous"
    p.write_text("(kicad_sch (version 20231120) (generator eeschema))\n")
    assert detect_format(str(p)) == "kicad"


def test_detect_format_via_magic_bytes_pdf(tmp_path):
    p = tmp_path / "anonymous"
    p.write_bytes(b"%PDF-1.7\n%binary garbage\n")
    assert detect_format(str(p)) == "pdf"


def test_detect_format_via_magic_bytes_altium_ole(tmp_path):
    p = tmp_path / "anonymous"
    p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32)
    assert detect_format(str(p)) == "altium"


# --- parse_schematic_auto error paths --------------------------------------

def test_parse_unknown_format_raises():
    with pytest.raises(ValueError):
        parse_schematic_auto("/nonexistent/file.xyz")


def test_parse_image_only_pdf_is_refused(tmp_path, monkeypatch):
    """Patch _is_image_only_pdf to True for any path so we exercise the gate."""
    from mcp_pcb_emcopilot.parsers import schematic_dispatch
    p = tmp_path / "scan.pdf"
    p.write_bytes(b"%PDF-1.7\n%dummy")
    monkeypatch.setattr(schematic_dispatch, "_is_image_only_pdf", lambda _p: True)
    with pytest.raises(ValueError) as exc:
        parse_schematic_auto(str(p))
    assert "image-only" in str(exc.value).lower()


def test_parse_netlist_stub_returns_components_and_nets(tmp_path):
    p = tmp_path / "design.net"
    p.write_text("\n".join([
        "R1 100k",
        "R2 4.7k",
        "U1 STM32F407",
        "NET_NAME = 'VCC_3V3'",
        "NET_NAME = 'GND'",
    ]))
    parsed = parse_schematic_auto(str(p))
    assert parsed["source_format"] == "netlist"
    refs = {c["reference"] for c in parsed["components"]}
    assert {"R1", "R2", "U1"}.issubset(refs)
    names = {n["name"] for n in parsed["nets"]}
    assert "VCC_3V3" in names
    assert "GND" in names


def test_parse_schematic_auto_pdf_fixture():
    """If a real PDF schematic fixture exists, parse it end-to-end."""
    fixture = Path(__file__).parent / "fixtures" / "schematic.pdf"
    if not fixture.exists():
        pytest.skip("schematic.pdf fixture not available")
    parsed = parse_schematic_auto(str(fixture))
    assert parsed["source_format"] == "pdf"
    assert "components" in parsed
    assert "nets" in parsed

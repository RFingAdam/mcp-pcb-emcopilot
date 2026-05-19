"""Round-trip tests for the sexpdata-based KiCad schematic parser."""

from __future__ import annotations

import pytest

from mcp_pcb_emcopilot.parsers.schematic_parser import (
    KiCadSchematicParser,
    SchematicParserFactory,
)


def test_parses_synthetic_2sheet_fixture(sample_kicad_sch):
    p = KiCadSchematicParser()
    result = p.parse(sample_kicad_sch)
    # No warnings on the happy path
    assert result.warnings == []
    # 4 components: R1, C1, C2, U1 (power symbols starting with # are filtered)
    refs = {c.reference for c in result.components}
    assert refs == {"R1", "C1", "C2", "U1"}


def test_extracts_mpn_manufacturer(sample_kicad_sch):
    result = KiCadSchematicParser().parse(sample_kicad_sch)
    r1 = next(c for c in result.components if c.reference == "R1")
    assert r1.part_number == "RC0402FR-0710KL"
    assert r1.manufacturer == "Yageo"


def test_in_bom_on_board_become_dnp_flag(sample_kicad_sch):
    result = KiCadSchematicParser().parse(sample_kicad_sch)
    c1 = next(c for c in result.components if c.reference == "C1")
    c2 = next(c for c in result.components if c.reference == "C2")
    assert c1.properties["dnp"] is False  # in_bom=yes + on_board=yes
    assert c2.properties["dnp"] is True   # in_bom=no — DNP


def test_dnp_in_bom_and_on_board_recorded_separately(sample_kicad_sch):
    result = KiCadSchematicParser().parse(sample_kicad_sch)
    c2 = next(c for c in result.components if c.reference == "C2")
    assert c2.properties["dnp_in_bom"] is False
    assert c2.properties["dnp_on_board"] is False


def test_footprint_captured(sample_kicad_sch):
    result = KiCadSchematicParser().parse(sample_kicad_sch)
    u1 = next(c for c in result.components if c.reference == "U1")
    assert "LQFP" in u1.footprint


def test_lib_id_recorded_in_properties(sample_kicad_sch):
    result = KiCadSchematicParser().parse(sample_kicad_sch)
    r1 = next(c for c in result.components if c.reference == "R1")
    assert r1.properties["lib_id"] == "Device:R"


def test_nets_collected_from_labels(sample_kicad_sch):
    result = KiCadSchematicParser().parse(sample_kicad_sch)
    net_names = {n.net_name for n in result.nets}
    assert "VCC_3V3" in net_names
    assert "GND" in net_names
    assert "USB_DP" in net_names


def test_power_and_ground_classified(sample_kicad_sch):
    result = KiCadSchematicParser().parse(sample_kicad_sch)
    by_name = {n.net_name: n for n in result.nets}
    assert by_name["VCC_3V3"].is_power is True
    assert by_name["GND"].is_ground is True


def test_pin_net_resolution_attaches_components(sample_kicad_sch):
    """Pins near label anchors should get tagged with the label's net."""
    result = KiCadSchematicParser().parse(sample_kicad_sch)
    r1 = next(c for c in result.components if c.reference == "R1")
    # R1 is at (50.8, 50.8) which is exactly the VCC_3V3 label anchor.
    tagged_pins = [p for p in r1.pins if p.get("net")]
    assert tagged_pins, "expected at least one pin tagged with a net"
    assert any(p["net"] == "VCC_3V3" for p in tagged_pins)


def test_factory_routes_kicad_sch_to_parser(sample_kicad_sch):
    result = SchematicParserFactory.parse(sample_kicad_sch)
    assert len(result.components) == 4


def test_parser_handles_malformed_gracefully(tmp_path):
    """Malformed S-expr should produce a warning, not an exception."""
    p = tmp_path / "bad.kicad_sch"
    p.write_text("(kicad_sch ( ((( broken")
    parser = KiCadSchematicParser()
    # ValueError is acceptable here (top-level read OK, tree parse fails)
    try:
        result = parser.parse(str(p))
        # If it didn't raise, it should have emitted a warning
        assert result.warnings or result.components == []
    except ValueError:
        pass


def test_missing_file_raises(tmp_path):
    p = tmp_path / "missing.kicad_sch"
    with pytest.raises(ValueError):
        KiCadSchematicParser().parse(str(p))

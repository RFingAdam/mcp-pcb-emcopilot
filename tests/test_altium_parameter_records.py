"""Integration tests for AltiumSchematicParser._parse_fileheader.

Real .SchDoc files are OLE2 compound binaries — impractical to synthesise.
But the FileHeader stream they wrap is just a sequence of length-prefixed
pipe-delimited records, which is easy to build. These tests build the
inner byte stream and call ``_parse_fileheader`` directly, so we exercise
production code rather than a mirror of it.

Covered:
- Parameter records (#41): VALUE, PARTNUMBER + MPN aliases, MANUFACTURER,
  DESCRIPTION (no overwrite), DNP (TRUE / YES / DONOTPLACE aliases / FALSE
  noop), COMPONENTCLASS, unknown-name stash.
- Pin records (#2) with explicit NetIdentifier.
- Pin records (#2) resolved geometrically via WIRE (#27) + NET_LABEL (#25).
- Sheet hierarchy: SHEET_SYMBOL (#15) + FILE_NAME (#33) link by owner_idx.
- ``altium_to_parsed_schematic`` field mapping.
- ``SchematicParserFactory.parse`` returns ``ParsedSchematicData`` for
  Altium input.
"""
from __future__ import annotations

import struct
from typing import Any

from mcp_pcb_emcopilot.parsers.altium_parser import (
    AltiumComponent,
    AltiumNet,
    AltiumSchematicData,
    AltiumSchematicParser,
    AltiumSheetSymbol,
    altium_to_parsed_schematic,
)
from mcp_pcb_emcopilot.parsers.schematic_parser import (
    ParsedSchematicData,
    SchematicParserFactory,
)


def _record(record_type: int, **fields: Any) -> bytes:
    """Build one length-prefixed Altium FileHeader record."""
    parts = [f"RECORD={record_type}"] + [f"{k}={v}" for k, v in fields.items()]
    payload = ("|" + "|".join(parts) + "|").encode("utf-8")
    return struct.pack("<I", len(payload)) + payload


# Real Altium .SchDoc streams have a leading HEADER-record sentinel
# at record_index=0; child records use OWNERINDEX relative to that
# offset (the production parser compensates via ``owner_idx + 1``).
# Our synthetic streams have to match the same shape, so we prepend
# a HEADER (#31) here. Tests then place COMPONENT/SHEET_SYMBOL at
# record_index=1 and reference them with OWNERINDEX=0.
_HEADER = _record(31, HEADER="schematic")


def _stream(*records: bytes) -> bytes:
    return _HEADER + b"".join(records)


def _parse(stream: bytes) -> AltiumSchematicData:
    """Run a synthetic FileHeader stream through the production parser."""
    data = AltiumSchematicData(source_file="<synthetic>")
    AltiumSchematicParser()._parse_fileheader(stream, data)
    return data


# ---------------------------------------------------------------------------
# 1-11 — Parameter-record handling (exercises real _parse_fileheader)
# ---------------------------------------------------------------------------


def test_value_param_populates_value_attribute():
    stream = _stream(
        _record(1),                            # COMPONENT @ idx 0
        _record(34, OWNERINDEX=0, TEXT="R1"),  # DESIGNATOR
        _record(41, OWNERINDEX=0, NAME="VALUE", TEXT="10k"),
    )
    data = _parse(stream)
    assert data.components[0].value == "10k"


def test_partnumber_param_populates_mpn():
    stream = _stream(
        _record(1),
        _record(34, OWNERINDEX=0, TEXT="C1"),
        _record(41, OWNERINDEX=0, NAME="PARTNUMBER", TEXT="GRM21BR"),
    )
    data = _parse(stream)
    assert data.components[0].part_number == "GRM21BR"


def test_mpn_via_manufacturer_part_number_alias():
    """The MANUFACTURER_PART_NUMBER alias must populate part_number too."""
    stream = _stream(
        _record(1),
        _record(34, OWNERINDEX=0, TEXT="U1"),
        _record(41, OWNERINDEX=0, NAME="MANUFACTURER_PART_NUMBER", TEXT="STM32F407VGT6"),
    )
    data = _parse(stream)
    assert data.components[0].part_number == "STM32F407VGT6"


def test_manufacturer_param_populates_attribute():
    stream = _stream(
        _record(1),
        _record(34, OWNERINDEX=0, TEXT="U1"),
        _record(41, OWNERINDEX=0, NAME="MANUFACTURER", TEXT="STMicro"),
    )
    data = _parse(stream)
    assert data.components[0].manufacturer == "STMicro"


def test_description_param_does_not_overwrite_existing():
    stream = _stream(
        _record(1, COMPONENTDESCRIPTION="original"),
        _record(34, OWNERINDEX=0, TEXT="U1"),
        _record(41, OWNERINDEX=0, NAME="DESCRIPTION", TEXT="overwritten"),
    )
    data = _parse(stream)
    assert data.components[0].description == "original"


def test_dnp_param_true_sets_dnp_property():
    stream = _stream(
        _record(1),
        _record(34, OWNERINDEX=0, TEXT="R1"),
        _record(41, OWNERINDEX=0, NAME="DNP", TEXT="True"),
    )
    data = _parse(stream)
    assert data.components[0].properties.get("dnp") is True


def test_dnp_param_yes_alias_via_donotplace():
    stream = _stream(
        _record(1),
        _record(34, OWNERINDEX=0, TEXT="R1"),
        _record(41, OWNERINDEX=0, NAME="DONOTPLACE", TEXT="yes"),
    )
    data = _parse(stream)
    assert data.components[0].properties.get("dnp") is True


def test_dnp_param_false_does_not_set_dnp():
    stream = _stream(
        _record(1),
        _record(34, OWNERINDEX=0, TEXT="R1"),
        _record(41, OWNERINDEX=0, NAME="DNP", TEXT="False"),
    )
    data = _parse(stream)
    assert "dnp" not in data.components[0].properties


def test_component_class_recorded():
    stream = _stream(
        _record(1),
        _record(34, OWNERINDEX=0, TEXT="U1"),
        _record(41, OWNERINDEX=0, NAME="COMPONENTCLASS", TEXT="Power"),
    )
    data = _parse(stream)
    assert data.components[0].properties["component_class"] == "Power"


def test_unknown_param_stashed_lowercased():
    stream = _stream(
        _record(1),
        _record(34, OWNERINDEX=0, TEXT="R1"),
        _record(41, OWNERINDEX=0, NAME="TOLERANCE", TEXT="1%"),
    )
    data = _parse(stream)
    assert data.components[0].properties["tolerance"] == "1%"


def test_multiple_params_per_component():
    stream = _stream(
        _record(1),
        _record(34, OWNERINDEX=0, TEXT="U1"),
        _record(41, OWNERINDEX=0, NAME="VALUE", TEXT="STM32F407"),
        _record(41, OWNERINDEX=0, NAME="PARTNUMBER", TEXT="STM32F407VGT6"),
        _record(41, OWNERINDEX=0, NAME="MANUFACTURER", TEXT="STMicro"),
        _record(41, OWNERINDEX=0, NAME="DNP", TEXT="False"),
        _record(41, OWNERINDEX=0, NAME="COMPONENTCLASS", TEXT="Microcontroller"),
        _record(41, OWNERINDEX=0, NAME="TOLERANCE", TEXT="0.5%"),
    )
    data = _parse(stream)
    u1 = data.components[0]
    assert u1.value == "STM32F407"
    assert u1.part_number == "STM32F407VGT6"
    assert u1.manufacturer == "STMicro"
    assert u1.properties["component_class"] == "Microcontroller"
    assert u1.properties["tolerance"] == "0.5%"
    assert "dnp" not in u1.properties


# ---------------------------------------------------------------------------
# 12-15 — New record-type handling
# ---------------------------------------------------------------------------


def test_pin_record_attached_to_owner_component():
    """PIN (#2) with explicit NetIdentifier resolves into component.pins[0]['net']."""
    stream = _stream(
        _record(1),                                # COMPONENT @ idx 0
        _record(34, OWNERINDEX=0, TEXT="U1"),      # DESIGNATOR
        _record(2, OWNERINDEX=0, DESIGNATOR=1, NAME="VDD",
                NETIDENTIFIER="VCC_3V3",
                ELECTRICAL="POWER"),
    )
    data = _parse(stream)
    pins = data.components[0].pins
    assert len(pins) == 1
    assert pins[0]["pin_number"] == "1"
    assert pins[0]["name"] == "VDD"
    assert pins[0]["net"] == "VCC_3V3"
    assert pins[0]["electrical_type"] == "POWER"


def test_pin_geometric_resolution_via_wire_and_label():
    """Pins without NetIdentifier match a NET_LABEL by coordinate proximity."""
    # Component at origin (0, 0). Pin offset at (0, 0) — absolute (0, 0).
    # WIRE from (0, 0) to (100, 0) [mil → 2.54mm]. NET_LABEL "DATA" anchored
    # at (100, 0) [mil → 2.54mm].
    stream = _stream(
        _record(1, **{"LOCATION.X": 0, "LOCATION.Y": 0}),     # COMPONENT
        _record(34, OWNERINDEX=0, TEXT="U1"),                  # DESIGNATOR
        _record(2, OWNERINDEX=0, DESIGNATOR=1, NAME="DATA_OUT",
                **{"LOCATION.X": 100, "LOCATION.Y": 0}),       # PIN, no NetIdentifier
        _record(27, **{"LOCATION.X": 0, "LOCATION.Y": 0,
                       "CORNER.X": 100, "CORNER.Y": 0}),       # WIRE
        _record(25, TEXT="DATA",
                **{"LOCATION.X": 100, "LOCATION.Y": 0}),       # NET_LABEL
    )
    data = _parse(stream)
    pins = data.components[0].pins
    assert len(pins) == 1
    assert pins[0]["net"] == "DATA", (
        f"expected geometric resolver to tag pin with 'DATA', got "
        f"{pins[0].get('net')!r}"
    )


def test_sheet_symbol_collects_filename_via_owner_link():
    """SHEET_SYMBOL (#15) + FILE_NAME (#33) link by owner_idx."""
    stream = _stream(
        _record(15, DESIGNATOR="PowerStage"),               # SHEET_SYMBOL @ idx 0
        _record(33, OWNERINDEX=0, TEXT="power_stage.SchDoc"),  # FILE_NAME
    )
    data = _parse(stream)
    assert len(data.sheet_symbols) == 1
    assert data.sheet_symbols[0].name == "PowerStage"
    assert data.sheet_symbols[0].filename == "power_stage.SchDoc"


def test_child_sheets_top_level_list_populated():
    """Multiple SHEET_SYMBOLs surface in data.child_sheets."""
    stream = _stream(
        _record(15, DESIGNATOR="Power"),                       # idx 0
        _record(33, OWNERINDEX=0, TEXT="power.SchDoc"),        # idx 1
        _record(15, DESIGNATOR="RF"),                          # idx 2
        _record(33, OWNERINDEX=2, TEXT="rf.SchDoc"),           # idx 3
    )
    data = _parse(stream)
    assert sorted(data.child_sheets) == ["power.SchDoc", "rf.SchDoc"]


# ---------------------------------------------------------------------------
# 16-17 — Converter + dispatch integration
# ---------------------------------------------------------------------------


def test_altium_to_parsed_schematic_converter_maps_pins_and_dnp():
    data = AltiumSchematicData(source_file="/tmp/x.SchDoc")
    data.components.append(AltiumComponent(
        reference="U1",
        value="STM32",
        part_number="STM32F407VGT6",
        manufacturer="STMicro",
        description="ARM MCU",
        x_mm=10.0,
        y_mm=20.0,
        properties={"dnp": True, "component_class": "Microcontroller"},
        pins=[{"pin_number": "1", "name": "VDD", "net": "VCC_3V3"}],
    ))
    data.nets.append(AltiumNet(name="VCC_3V3"))
    data.nets.append(AltiumNet(name="GND"))
    data.sheet_symbols.append(AltiumSheetSymbol(
        name="Power", filename="power.SchDoc"
    ))
    data.child_sheets = ["power.SchDoc"]

    parsed = altium_to_parsed_schematic(data)

    assert isinstance(parsed, ParsedSchematicData)
    assert len(parsed.components) == 1
    pc = parsed.components[0]
    assert pc.reference == "U1"
    assert pc.part_number == "STM32F407VGT6"
    assert pc.manufacturer == "STMicro"
    assert pc.properties["dnp"] is True
    assert pc.properties["component_class"] == "Microcontroller"
    assert pc.properties["description"] == "ARM MCU"
    assert pc.pins[0]["net"] == "VCC_3V3"

    nets_by_name = {n.net_name: n for n in parsed.nets}
    assert nets_by_name["VCC_3V3"].is_power is True
    assert nets_by_name["GND"].is_ground is True

    assert parsed.sheet_count == 2  # parent + 1 child
    assert parsed.properties["child_sheets"] == ["power.SchDoc"]
    assert parsed.properties["sheet_symbols"][0]["filename"] == "power.SchDoc"


def test_schematic_parser_factory_returns_parsed_for_altium(tmp_path, monkeypatch):
    """SchematicParserFactory.parse() must convert Altium results to ParsedSchematicData."""
    # Stub AltiumSchematicParser.parse to return a pre-built AltiumSchematicData
    # so we exercise the converter wiring without needing a real .SchDoc fixture.
    pre_built = AltiumSchematicData(source_file="<stub>")
    pre_built.components.append(AltiumComponent(
        reference="C42",
        value="100nF",
        part_number="CL10B104KB8NNNC",
        manufacturer="Samsung",
        properties={"dnp": True},
        pins=[{"pin_number": "1", "name": "P1", "net": "GND"}],
    ))
    pre_built.nets.append(AltiumNet(name="GND"))

    def fake_parse(self, file_path: str) -> AltiumSchematicData:  # noqa: ARG001
        return pre_built

    monkeypatch.setattr(AltiumSchematicParser, "parse", fake_parse)

    fake_file = tmp_path / "fake.SchDoc"
    fake_file.write_bytes(b"")  # exists check inside Factory only inspects extension

    result = SchematicParserFactory.parse(str(fake_file))

    assert isinstance(result, ParsedSchematicData)
    assert result.components[0].reference == "C42"
    assert result.components[0].part_number == "CL10B104KB8NNNC"
    assert result.components[0].properties["dnp"] is True
    assert result.components[0].pins[0]["net"] == "GND"

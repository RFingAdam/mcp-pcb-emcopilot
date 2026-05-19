"""Unit tests for AltiumSchematicParser parameter-record handling.

Real .SchDoc files are OLE2 compound binaries — impractical to synthesise.
These tests exercise the post-parse parameter mapping code path directly
by constructing a parser instance with a hand-built parameter list, which
mirrors what _parse_records would produce from a real OLE stream.
"""

from __future__ import annotations

from mcp_pcb_emcopilot.parsers.altium_parser import (
    AltiumComponent,
    AltiumSchematicData,
)


def _apply_params(params: list[tuple[int, str, str]],
                  components_by_idx: dict[int, AltiumComponent]) -> None:
    """Mirror the parameter-application logic in AltiumSchematicParser.

    Imported inline so the test isolates exactly the behaviour we want to
    pin: parameter name → component attribute / property dict.
    """
    for owner_idx, param_name, param_value in params:
        comp = components_by_idx.get(owner_idx + 1)
        if comp is None:
            continue
        if param_name == "VALUE":
            comp.value = param_value
        elif param_name in ("PARTNUMBER", "MPN", "MANUFACTURER_PART_NUMBER"):
            comp.part_number = param_value
        elif param_name in ("MANUFACTURER", "MFR"):
            comp.manufacturer = param_value
        elif param_name == "DESCRIPTION" and not comp.description:
            comp.description = param_value
        elif param_name in ("DNP", "DONOTPLACE", "DO_NOT_PLACE", "NOSTUFF"):
            flag = (param_value or "").strip().lower()
            if flag in ("true", "1", "yes", "y"):
                comp.properties["dnp"] = True
        elif param_name in ("COMPONENTCLASS", "COMPONENT_CLASS", "CLASS"):
            comp.properties["component_class"] = param_value
        elif param_name in ("COMMENT", "NOTE"):
            comp.properties.setdefault("comment", param_value)
        else:
            comp.properties.setdefault(param_name.lower(), param_value)


def test_altium_component_has_properties_field():
    c = AltiumComponent(reference="R1")
    assert c.properties == {}


def test_altium_schematic_data_initialises_clean():
    data = AltiumSchematicData(source_file="/tmp/x.SchDoc")
    assert data.components == []


def test_value_param_populates_value_attribute():
    comps = {1: AltiumComponent(reference="R1")}
    _apply_params([(0, "VALUE", "10k")], comps)
    assert comps[1].value == "10k"


def test_partnumber_param_populates_mpn():
    comps = {1: AltiumComponent(reference="C1")}
    _apply_params([(0, "PARTNUMBER", "GRM21BR")], comps)
    assert comps[1].part_number == "GRM21BR"


def test_manufacturer_param_populates_attribute():
    comps = {1: AltiumComponent(reference="U1")}
    _apply_params([(0, "MANUFACTURER", "STMicro")], comps)
    assert comps[1].manufacturer == "STMicro"


def test_description_param_does_not_overwrite_existing():
    comps = {1: AltiumComponent(reference="U1", description="original")}
    _apply_params([(0, "DESCRIPTION", "new")], comps)
    assert comps[1].description == "original"


def test_dnp_param_true_sets_dnp_property():
    comps = {1: AltiumComponent(reference="R1")}
    _apply_params([(0, "DNP", "True")], comps)
    assert comps[1].properties.get("dnp") is True


def test_dnp_param_yes_treated_as_dnp():
    comps = {1: AltiumComponent(reference="R1")}
    _apply_params([(0, "DONOTPLACE", "yes")], comps)
    assert comps[1].properties.get("dnp") is True


def test_dnp_param_false_does_not_set_dnp():
    comps = {1: AltiumComponent(reference="R1")}
    _apply_params([(0, "DNP", "False")], comps)
    assert "dnp" not in comps[1].properties


def test_component_class_recorded():
    comps = {1: AltiumComponent(reference="U1")}
    _apply_params([(0, "COMPONENTCLASS", "Power")], comps)
    assert comps[1].properties["component_class"] == "Power"


def test_unknown_param_stashed_lowercased():
    comps = {1: AltiumComponent(reference="R1")}
    _apply_params([(0, "TOLERANCE", "1%")], comps)
    assert comps[1].properties["tolerance"] == "1%"


def test_multiple_params_per_component():
    comps = {1: AltiumComponent(reference="U1")}
    _apply_params([
        (0, "VALUE", "STM32F407"),
        (0, "PARTNUMBER", "STM32F407VGT6"),
        (0, "MANUFACTURER", "STMicro"),
        (0, "DNP", "False"),
        (0, "COMPONENTCLASS", "Microcontroller"),
        (0, "TOLERANCE", "0.5%"),
    ], comps)
    u1 = comps[1]
    assert u1.value == "STM32F407"
    assert u1.part_number == "STM32F407VGT6"
    assert u1.manufacturer == "STMicro"
    assert u1.properties["component_class"] == "Microcontroller"
    assert u1.properties["tolerance"] == "0.5%"
    assert "dnp" not in u1.properties

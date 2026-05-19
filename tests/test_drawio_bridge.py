"""Tests for integrations/drawio_bridge — diagram intent emission."""

from __future__ import annotations

from mcp_pcb_emcopilot.integrations.drawio_bridge import (
    build_diagram_intents,
    build_emc_test_setup_intent,
    build_rf_chain_intent,
    build_schematic_markup_intent,
    build_stackup_intent,
)

# --- Individual builders ----------------------------------------------------

def test_stackup_intent():
    layers = [{"name": "Top", "type": "signal", "thickness_mm": 0.035}]
    a = build_stackup_intent(layers, board_thickness_mm=1.6)
    assert a.mcp_server == "drawio-engineering"
    assert a.tool_name == "create_pcb_stackup"
    assert a.params["layers"] == layers
    assert a.params["board_thickness_mm"] == 1.6


def test_rf_chain_intent():
    a = build_rf_chain_intent(frequencies_mhz=[2400.0, 5800.0])
    assert a.tool_name == "create_rf_block_diagram"
    assert a.params["frequencies_mhz"] == [2400.0, 5800.0]


def test_emc_test_setup_intent_automotive_picks_cispr25():
    a = build_emc_test_setup_intent("automotive")
    assert a.params["standard"] == "CISPR_25"
    assert a.params["market"] == "automotive"


def test_emc_test_setup_intent_medical_picks_iec_60601():
    a = build_emc_test_setup_intent("medical")
    assert a.params["standard"] == "IEC_60601_1_2"


def test_emc_test_setup_intent_explicit_standard_overrides_default():
    a = build_emc_test_setup_intent("commercial", standard="EN_55032")
    assert a.params["standard"] == "EN_55032"


def test_schematic_markup_intent():
    a = build_schematic_markup_intent("/tmp/sch.pdf", annotations=[{"page": 1}])
    assert a.tool_name == "markup_schematic"
    assert a.params["schematic_path"] == "/tmp/sch.pdf"
    assert a.params["annotations"] == [{"page": 1}]


# --- build_diagram_intents (composite) -------------------------------------

def test_full_set_emits_all_four_when_inputs_present():
    intents = build_diagram_intents(
        stackup_layers=[{"name": "Top", "thickness_mm": 0.035}],
        board_thickness_mm=1.6,
        detected_interfaces=["BLE", "USB2"],
        target_markets=["automotive"],
        schematic_path="/tmp/sch.pdf",
        rf_frequencies_mhz=[2400.0],
    )
    tools = [a.tool_name for a in intents]
    assert tools == [
        "create_pcb_stackup",
        "create_rf_block_diagram",
        "create_emc_test_setup",
        "markup_schematic",
    ]


def test_skips_rf_chain_when_no_rf():
    intents = build_diagram_intents(
        stackup_layers=[{"name": "Top"}],
        detected_interfaces=["USB2", "DDR4"],
        target_markets=["commercial"],
    )
    tools = [a.tool_name for a in intents]
    assert "create_rf_block_diagram" not in tools


def test_emits_one_test_setup_per_market():
    intents = build_diagram_intents(
        stackup_layers=[{"name": "L1"}],
        target_markets=["automotive", "wireless"],
    )
    setup_intents = [a for a in intents if a.tool_name == "create_emc_test_setup"]
    assert len(setup_intents) == 2
    markets = {a.params["market"] for a in setup_intents}
    assert markets == {"automotive", "wireless"}


def test_skips_schematic_markup_when_no_path():
    intents = build_diagram_intents(
        stackup_layers=[{"name": "L1"}],
        schematic_path=None,
    )
    tools = [a.tool_name for a in intents]
    assert "markup_schematic" not in tools


def test_skips_stackup_when_no_layers():
    intents = build_diagram_intents(stackup_layers=[])
    tools = [a.tool_name for a in intents]
    assert "create_pcb_stackup" not in tools

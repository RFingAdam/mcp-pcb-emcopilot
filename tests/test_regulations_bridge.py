"""Tests for integrations/regulations_bridge — intent emission + result ingest."""

from __future__ import annotations

import pytest

from mcp_pcb_emcopilot.analyzers.emc.limits_provider import (
    clear_live_cache,
    get_limit,
)
from mcp_pcb_emcopilot.integrations.regulations_bridge import (
    apply_limit_result,
    build_intents_for_standards,
    build_limit_lookup_intent,
    tool_name_for_standard,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_live_cache()
    yield
    clear_live_cache()


# --- Tool mapping -----------------------------------------------------------

def test_tool_mapping_known_standards():
    assert tool_name_for_standard("CISPR_25") == "cispr25_limit"
    assert tool_name_for_standard("FCC_PART_15_B") == "fcc_part15_limit"
    assert tool_name_for_standard("CISPR_32") == "cispr_limit"
    assert tool_name_for_standard("ISO_11452_4") == "iso11452_levels"
    assert tool_name_for_standard("IEC_60601_1_2_ED_4_1") == "medical_immunity_levels"


def test_tool_mapping_unknown_falls_back_to_source_search():
    assert tool_name_for_standard("MIL_STD_461G") == "source_search"


# --- Intent emission --------------------------------------------------------

def test_build_intent_basics():
    intent = build_limit_lookup_intent("CISPR_25", "3", 150.0, "QP",
                                        linked_finding_ids=["EMC-001"])
    assert intent.mcp_server == "emc-regulations"
    assert intent.tool_name == "cispr25_limit"
    assert intent.params["standard"] == "CISPR_25"
    assert intent.params["frequency_mhz"] == 150.0
    assert intent.linked_finding_ids == ["EMC-001"]


def test_build_intents_for_standards_emits_one_per_freq():
    intents = build_intents_for_standards(
        standards=["CISPR_25", "FCC_PART_15_B"],
        sample_frequencies_mhz=(30.0, 150.0),
    )
    assert len(intents) == 4
    # All point at emc-regulations
    for i in intents:
        assert i.mcp_server == "emc-regulations"
    # Each standard has its own tool
    tools = {i.tool_name for i in intents}
    assert tools == {"cispr25_limit", "fcc_part15_limit"}


def test_build_intents_respects_pinned_class():
    intents = build_intents_for_standards(
        standards=["CISPR_25"],
        classes_by_standard={"CISPR_25": "5"},
        sample_frequencies_mhz=(150.0,),
    )
    assert intents[0].params["class_or_level"] == "5"


def test_build_intents_defaults_class_when_unpinned():
    [intent] = build_intents_for_standards(
        standards=["FCC_PART_15_B"], sample_frequencies_mhz=(100.0,),
    )
    assert intent.params["class_or_level"] == "B"


# --- Result ingestion -------------------------------------------------------

def test_apply_limit_result_writes_to_provider_cache():
    intent = build_limit_lookup_intent("CISPR_25", "3", 150.0, "QP")
    payload = {
        "limit_dbuv_per_m": 8.5,
        "band_min_mhz": 144.0,
        "band_max_mhz": 172.0,
    }
    point = apply_limit_result(intent, payload)
    assert point is not None
    assert point.limit_value == 8.5
    assert point.source == "live_regs"
    # And provider returns the cached value
    live = get_limit("CISPR_25", "3", 150.0)
    assert live.limit_value == 8.5
    assert live.source == "live_regs"


def test_apply_limit_result_supports_alternate_keys():
    intent = build_limit_lookup_intent("FCC_PART_15_B", "B", 100.0, "QP")
    payload = {"value": 42.0, "unit": "dBuV/m"}
    p = apply_limit_result(intent, payload)
    assert p is not None and p.limit_value == 42.0


def test_apply_limit_result_returns_none_on_unrecognisable_payload():
    intent = build_limit_lookup_intent("CISPR_25", "3", 150.0)
    assert apply_limit_result(intent, {"random": "data"}) is None


def test_apply_limit_result_returns_none_on_non_dict():
    intent = build_limit_lookup_intent("CISPR_25", "3", 150.0)
    assert apply_limit_result(intent, []) is None  # type: ignore[arg-type]

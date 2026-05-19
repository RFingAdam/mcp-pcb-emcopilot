"""Tests for the Phase 4 multi-market intake extensions to review_context."""

from __future__ import annotations

from dataclasses import dataclass, field

from mcp_pcb_emcopilot.review_context import (
    ReviewContext,
    get_active_markets,
    get_review_questions,
    get_target_standards_for,
)

# --- Lightweight stubs ------------------------------------------------------

class _Net:
    def __init__(self, category: str, subcategory: str | None = None) -> None:
        self.category = category
        self.subcategory = subcategory


@dataclass
class _NetCls:
    classified_nets: list = field(default_factory=list)
    differential_pairs: list = field(default_factory=list)


@dataclass
class _DesignCls:
    primary_type: str = "mixed_signal"
    complexity_score: int = 50


class _Design:
    """Minimal stand-in for PCBDesignData — only the fields review_context uses."""
    def __init__(self, review_context: dict | None = None) -> None:
        self.review_context = review_context or {}


# --- get_active_markets ----------------------------------------------------

def test_explicit_markets_list_wins():
    design = _Design({"markets": ["automotive", "wireless"]})
    assert get_active_markets(design, _DesignCls(), _NetCls()) == ["automotive", "wireless"]


def test_playbook_declared_market_used_when_no_explicit_list():
    design = _Design({"playbook": {"declared_market": "medical"}})
    assert get_active_markets(design, _DesignCls(), _NetCls()) == ["medical"]


def test_unknown_declared_market_is_ignored():
    design = _Design({"playbook": {"declared_market": "unknown"}})
    assert get_active_markets(design, _DesignCls(), _NetCls()) == []


def test_inference_falls_back_to_rf_when_no_market_declared():
    nets = _NetCls(classified_nets=[_Net("rf"), _Net("power")])
    design = _Design()
    assert get_active_markets(design, _DesignCls(), nets) == ["wireless"]


def test_explicit_invalid_market_filtered_out():
    design = _Design({"markets": ["nonsense", "automotive"]})
    assert get_active_markets(design, _DesignCls(), _NetCls()) == ["automotive"]


# --- get_review_questions ---------------------------------------------------

def test_core_pack_returned_when_no_markets():
    design = _Design()
    qs = get_review_questions(design, _DesignCls(), _NetCls())
    ids = {q["id"] for q in qs}
    assert "operating_environment" in ids   # core
    assert "vehicle_class" not in ids       # automotive — not active


def test_automotive_market_adds_pack():
    design = _Design({"playbook": {"declared_market": "automotive"}})
    qs = get_review_questions(design, _DesignCls(), _NetCls())
    ids = {q["id"] for q in qs}
    assert "vehicle_class" in ids
    assert "iso7637_pulses" in ids


def test_multi_market_merges_packs_without_duplicates():
    design = _Design({"markets": ["medical", "wireless"]})
    qs = get_review_questions(design, _DesignCls(), _NetCls())
    ids = [q["id"] for q in qs]
    # Both medical and wireless ids appear
    assert "device_class" in ids
    assert "tx_power_dbm" in ids
    # No duplicates
    assert len(ids) == len(set(ids))


# --- get_target_standards_for ----------------------------------------------

def test_target_standards_automotive():
    design = _Design({"markets": ["automotive"]})
    standards = get_target_standards_for(design, _DesignCls(), _NetCls())
    assert "CISPR_25" in standards
    assert "ISO_11452_4" in standards


def test_target_standards_unions_multi_market():
    design = _Design({"markets": ["medical", "wireless"]})
    standards = get_target_standards_for(design, _DesignCls(), _NetCls())
    assert "IEC_60601_1_2_ED_4_1" in standards
    assert "FCC_47_CFR_15C" in standards


# --- Typed getters ---------------------------------------------------------

def test_typed_getter_vehicle_class():
    ctx = ReviewContext({"vehicle_class": "passenger"})
    assert ctx.get_vehicle_class() == "passenger"


def test_typed_getter_iso7637_pulses_list_form():
    ctx = ReviewContext({"iso7637_pulses": ["1", "2a", "5b"]})
    assert ctx.get_iso7637_pulses() == ["1", "2a", "5b"]


def test_typed_getter_iso7637_pulses_text_form():
    ctx = ReviewContext({"iso7637_pulses": "1, 2a, 5b"})
    assert ctx.get_iso7637_pulses() == ["1", "2a", "5b"]


def test_typed_getter_cispr25_class_coerces_int():
    ctx = ReviewContext({"cispr25_class": "3"})
    assert ctx.get_cispr25_class() == 3


def test_typed_getter_intentional_radiator_bool_and_string_forms():
    assert ReviewContext({"intentional_radiator": True}).get_intentional_radiator() is True
    assert ReviewContext({"intentional_radiator": "yes"}).get_intentional_radiator() is True
    assert ReviewContext({"intentional_radiator": "false"}).get_intentional_radiator() is False
    assert ReviewContext({}).get_intentional_radiator() is False


def test_typed_getter_iec60601_edition_default():
    ctx = ReviewContext({})
    assert ctx.get_iec60601_edition() == "4.1"


def test_typed_getter_target_regions():
    ctx = ReviewContext({"target_regions": ["US", "EU", "JP"]})
    assert ctx.get_target_regions() == ["US", "EU", "JP"]


def test_typed_getter_hazloc_class_none_is_normalised_to_none():
    ctx = ReviewContext({"hazloc_class": "none"})
    assert ctx.get_hazloc_class() is None


def test_typed_getter_surge_target_kv_accepts_both_casings():
    assert ReviewContext({"surge_target_kV": "2"}).get_surge_target_kV() == 2.0
    assert ReviewContext({"surge_target_kv": "4"}).get_surge_target_kV() == 4.0

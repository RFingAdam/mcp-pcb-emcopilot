"""Tests for analyzers/emc/limits_provider — local fallback + live cache."""

from __future__ import annotations

import pytest

from mcp_pcb_emcopilot.analyzers.emc.limits_provider import (
    LimitPoint,
    cache_live_result,
    clear_live_cache,
    get_limit,
    has_live_value,
)


@pytest.fixture(autouse=True)
def _isolate_live_cache():
    """Each test starts with an empty live-regs cache."""
    clear_live_cache()
    yield
    clear_live_cache()


# --- Local fallback ---------------------------------------------------------

def test_cispr25_radiated_class_3_mid_band():
    p = get_limit("CISPR_25", "3", 150.0, detector="QP")
    assert p is not None
    # 144 -- 172 MHz band, class 3, limit dict {3: 12}
    assert p.limit_value == 12
    assert p.limit_unit == "dBuV/m"
    assert p.source == "local_fallback"
    assert p.band_min_mhz == 144 and p.band_max_mhz == 172


def test_cispr25_radiated_class_5_strict():
    p = get_limit("CISPR_25", "5", 150.0)
    assert p is not None and p.limit_value == -8


def test_cispr25_conducted_class_3_avg_band():
    # 1.0 MHz lives in the 0.53–1.8 MHz conducted band — avg limit is 50 dBuV.
    p = get_limit("CISPR_25", "3", 1.0, detector="AVG")
    assert p is not None
    assert p.limit_value == 50
    assert p.limit_unit == "dBuV"


def test_fcc_part_15_b_radiated():
    p = get_limit("FCC_PART_15_B", "B", 100.0)
    assert p is not None and p.limit_value == 43.5


def test_fcc_part_15_b_conducted_below_30_mhz():
    p = get_limit("FCC_PART_15_B", "B", 1.0, detector="QP")
    assert p is not None and p.limit_unit == "dBuV"
    assert p.limit_value == 56


def test_cispr_32_class_b_radiated():
    p = get_limit("CISPR_32", "B", 500.0)
    assert p is not None and p.limit_value == 47.0


def test_iso_11452_4_bci_level_3():
    p = get_limit("ISO_11452_4", "3", 200.0)
    assert p is not None
    assert p.limit_value == 10  # 10 mA at level 3
    assert p.limit_unit == "mA"


def test_iso_11452_2_field_level_4():
    p = get_limit("ISO_11452_2", "4", 100.0)
    assert p is not None
    assert p.limit_value == 30
    assert p.limit_unit == "V/m"


def test_iec_60601_ed_4_1_rf_immunity():
    p = get_limit("IEC_60601_1_2_ED_4_1", "4.1", 100.0)
    assert p is not None and p.limit_value == 10.0
    assert p.limit_unit == "V/m"


def test_unknown_standard_returns_none():
    assert get_limit("MIL_STD_461G", "RE102", 100.0) is None


def test_freq_outside_any_band_returns_none():
    # CISPR-25 doesn't cover 3000 MHz
    assert get_limit("CISPR_25", "3", 3000.0) is None


# --- Live-regs cache -------------------------------------------------------

def test_live_cache_overrides_fallback():
    # Fallback says 12 dBuV/m at 150 MHz Class 3
    fallback = get_limit("CISPR_25", "3", 150.0)
    assert fallback.limit_value == 12 and fallback.source == "local_fallback"
    # Cache an override
    cache_live_result(LimitPoint(
        standard="CISPR_25",
        class_or_level="3",
        frequency_mhz=150.0,
        detector="QP",
        limit_value=9.0,
        limit_unit="dBuV/m",
        band_min_mhz=144.0,
        band_max_mhz=172.0,
        source="live_regs",
        notes="emc-regulations live lookup",
    ))
    live = get_limit("CISPR_25", "3", 150.0)
    assert live.limit_value == 9.0
    assert live.source == "live_regs"


def test_has_live_value_true_after_cache():
    assert has_live_value("CISPR_25", "3", 150.0) is False
    cache_live_result(LimitPoint(
        standard="CISPR_25", class_or_level="3", frequency_mhz=150.0,
        detector="QP", limit_value=9.0, limit_unit="dBuV/m",
        band_min_mhz=144.0, band_max_mhz=172.0, source="live_regs",
    ))
    assert has_live_value("CISPR_25", "3", 150.0) is True


def test_clear_live_cache_restores_fallback():
    cache_live_result(LimitPoint(
        standard="CISPR_25", class_or_level="3", frequency_mhz=150.0,
        detector="QP", limit_value=9.0, limit_unit="dBuV/m",
        band_min_mhz=144.0, band_max_mhz=172.0, source="live_regs",
    ))
    clear_live_cache()
    p = get_limit("CISPR_25", "3", 150.0)
    assert p.source == "local_fallback"


def test_clock_emi_uses_provider():
    """The clock_emi analyzer was refactored to read through the provider —
    a live override should change its returned limit too."""
    from mcp_pcb_emcopilot.analyzers.emc.clock_emi_analyzer import (
        _get_regulatory_limit,
    )
    baseline = _get_regulatory_limit(100.0, standard="fcc_b")
    cache_live_result(LimitPoint(
        standard="FCC_PART_15_B",
        class_or_level="B",
        frequency_mhz=100.0,
        detector="QP",
        limit_value=999.0,  # deliberately silly value to prove override
        limit_unit="dBuV/m",
        band_min_mhz=88.0,
        band_max_mhz=216.0,
        source="live_regs",
    ))
    overridden = _get_regulatory_limit(100.0, standard="fcc_b")
    assert baseline != overridden
    assert overridden == 999.0

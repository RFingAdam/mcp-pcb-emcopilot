"""Tests for standards/coverage — STANDARD_TO_ANALYZERS map + helpers."""

from __future__ import annotations

from mcp_pcb_emcopilot.standards.coverage import (
    STANDARD_TO_ANALYZERS,
    get_coverage,
    summarise_coverage,
)

# --- Map structural invariants ---------------------------------------------

def test_every_entry_has_required_keys():
    for std, meta in STANDARD_TO_ANALYZERS.items():
        assert "required_analyzers" in meta, std
        assert "limit_source" in meta, std
        assert "coverage_level" in meta, std
        assert "pack" in meta, std
        assert meta["coverage_level"] in ("full", "partial", "stub", "unimplemented"), std


def test_pack_values_are_in_known_packs():
    known = {"automotive", "medical", "wireless", "commercial", "industrial", "military", "unknown"}
    for std, meta in STANDARD_TO_ANALYZERS.items():
        assert meta["pack"] in known, f"{std}: pack {meta['pack']} not in {known}"


# --- get_coverage ----------------------------------------------------------

def test_coverage_marks_fully_covered_when_required_analyzers_all_ran():
    cov = get_coverage(["CISPR_25"], ran_analyzers={
        "automotive_emc", "return_paths", "smps_emi", "clock_emi",
    })
    assert len(cov) == 1
    assert cov[0].standard == "CISPR_25"
    assert cov[0].missing_analyzers == []
    assert cov[0].fully_covered is True


def test_coverage_lists_missing_when_some_analyzers_didnt_run():
    cov = get_coverage(["CISPR_25"], ran_analyzers={"automotive_emc"})
    assert cov[0].missing_analyzers == ["return_paths", "smps_emi", "clock_emi"]
    assert cov[0].fully_covered is False


def test_coverage_stub_standard_never_fully_covered():
    cov = get_coverage(["ISO_7637_2"], ran_analyzers=set())
    assert cov[0].coverage_level == "stub"
    assert cov[0].fully_covered is False


def test_coverage_unknown_standard_marked_unimplemented():
    cov = get_coverage(["NEW_DRAFT_2027"])
    assert cov[0].coverage_level == "unimplemented"
    assert cov[0].pack == "unknown"


# --- summarise_coverage ----------------------------------------------------

def test_summarise_rollup_counts_correct():
    cov = get_coverage(
        ["CISPR_25", "ISO_7637_2", "MIL_STD_461G"],
        ran_analyzers={
            "automotive_emc", "return_paths", "smps_emi", "clock_emi",
        },
    )
    summary = summarise_coverage(cov)
    assert summary["total_standards"] == 3
    assert summary["fully_covered"] == 1
    assert summary["stub"] == 1
    assert summary["unimplemented"] == 1
    assert summary["ready_for_report"] is False


def test_summarise_ready_for_report_when_no_stub_or_unimplemented():
    cov = get_coverage(["CISPR_25"], ran_analyzers={
        "automotive_emc", "return_paths", "smps_emi", "clock_emi",
    })
    summary = summarise_coverage(cov)
    assert summary["ready_for_report"] is True


def test_summarise_partial_does_not_block_report_readiness():
    """A 'partial' coverage entry is informational; only stub/unimplemented
    blocks ready_for_report so the reviewer can still ship with caveats."""
    cov = get_coverage(["ISO_11452_5"], ran_analyzers={"immunity_margin"})
    summary = summarise_coverage(cov)
    assert summary["partial"] == 1
    assert summary["stub"] == 0
    assert summary["unimplemented"] == 0
    assert summary["ready_for_report"] is True

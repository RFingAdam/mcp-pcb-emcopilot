"""Ingest completeness gate: partial/garbage parses must not read as success.

The gate only inspects list lengths and board dimensions, so tests build a
PCBDesignData and stuff its element lists with placeholder objects rather than
constructing full parsers' output.
"""
from __future__ import annotations

import types
from pathlib import Path

from mcp_pcb_emcopilot.models.pcb_data import PCBDesignData
from mcp_pcb_emcopilot.orchestrator import DomainResult, _build_executive_summary
from mcp_pcb_emcopilot.parsers import (
    _completeness_warnings,
    _parse_format,
    parse_pcb_file,
)

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_signal_4layer.kicad_pcb"


def _design(**kw) -> PCBDesignData:
    d = PCBDesignData(source_file="x.kicad_pcb")
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def test_nothing_extracted_is_flagged():
    warns = _completeness_warnings(_design(), "kicad")
    assert warns and any("no components" in w.lower() for w in warns)


def test_components_but_no_nets_flagged():
    d = _design(components=[object(), object()], traces=[object()],
                board_width_mm=10, board_height_mm=10)
    assert any("0 nets" in w for w in _completeness_warnings(d, "kicad"))


def test_components_but_no_traces_flagged():
    d = _design(components=[object()], nets=[object()],
                board_width_mm=10, board_height_mm=10)
    assert any("0 traces" in w for w in _completeness_warnings(d, "kicad"))


def test_zero_board_area_flagged():
    d = _design(components=[object()], nets=[object()], traces=[object()])
    assert any("area" in w.lower() for w in _completeness_warnings(d, "kicad"))


def test_complete_design_has_no_warnings():
    d = _design(components=[object()], nets=[object()], traces=[object()],
                board_width_mm=20, board_height_mm=15)
    assert _completeness_warnings(d, "kicad") == []


def test_parse_format_marks_partial_and_keeps_data():
    def fake_parser(_path):
        return _design(components=[object()])  # no nets/traces/area

    d = _parse_format("kicad", "ignored", fake_parser)
    assert d.parse_is_partial and d.parse_completeness == "partial"
    assert d.warnings  # surfaced, not silent


def test_parse_format_complete_stays_complete():
    def fake_parser(_path):
        return _design(components=[object()], nets=[object()], traces=[object()],
                       board_width_mm=20, board_height_mm=15)

    d = _parse_format("kicad", "ignored", fake_parser)
    assert not d.parse_is_partial and d.parse_completeness == "complete"


def test_real_fixture_parses_complete():
    d = parse_pcb_file(str(FIXTURE))
    assert d.parse_completeness == "complete"
    assert not d.parse_is_partial


def test_to_summary_surfaces_completeness_and_warnings():
    d = _design(components=[object()])
    d.warnings.append("something odd")
    d.parse_completeness = "partial"
    summ = d.to_summary()
    assert summ["parse_completeness"] == "partial"
    assert "something odd" in summ["warnings"]


def test_partial_parse_forces_inconclusive_verdict():
    cls = types.SimpleNamespace(design_type="x", complexity_label="y")
    # A single passing domain would otherwise be a clean PASS.
    drs = [DomainResult(domain="a", status="pass")]
    s = _build_executive_summary(drs, cls, [], parse_partial=True)
    assert s["overall_status"] == "INCONCLUSIVE"
    assert s["parse_partial"] is True

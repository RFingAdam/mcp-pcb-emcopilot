"""Tests for the Phase 3 cross-MCP intent queue dataclasses + helpers."""

from __future__ import annotations

import pytest

from mcp_pcb_emcopilot.integrations.external_actions import (
    PRIORITY_CRITICAL,
    PRIORITY_HIGH,
    PRIORITY_NORMAL,
    STATUS_COMPLETED,
    STATUS_PENDING,
    ExternalAction,
    ExternalResult,
    dedupe_actions,
    filter_pending,
    has_pending_critical,
    sort_by_priority,
)

# --- ExternalAction ----------------------------------------------------------

def test_external_action_auto_assigns_id():
    a = ExternalAction(mcp_server="openems", tool_name="openems_create_microstrip",
                       params={"trace_width_mm": 0.2}, rationale="verify")
    assert a.action_id != ""
    assert len(a.action_id) == 8


def test_external_action_to_dict_round_trip():
    a = ExternalAction(
        mcp_server="emc-regulations",
        tool_name="cispr25_limit",
        params={"class": 3, "freq_mhz": 150},
        rationale="CISPR-25 Class 3 limit lookup",
        linked_finding_ids=["EMC-001"],
        priority=PRIORITY_HIGH,
    )
    d = a.to_dict()
    assert d["mcp_server"] == "emc-regulations"
    assert d["tool_name"] == "cispr25_limit"
    assert d["fully_qualified_tool_name"] == "mcp__emc-regulations__cispr25_limit"
    assert d["params"] == {"class": 3, "freq_mhz": 150}
    assert d["priority"] == PRIORITY_HIGH
    assert d["status"] == STATUS_PENDING


def test_external_action_rejects_invalid_status():
    with pytest.raises(ValueError):
        ExternalAction(
            mcp_server="openems",
            tool_name="x",
            params={},
            rationale="r",
            status="garbage",
        )


# --- ExternalResult ----------------------------------------------------------

def test_external_result_succeeded_when_no_error():
    r = ExternalResult(action_id="abc12345", result={"z0": 50.1})
    assert r.succeeded is True
    d = r.to_dict()
    assert d["error"] is None
    assert d["succeeded"] is True


def test_external_result_failed_when_error_set():
    r = ExternalResult(action_id="abc12345", result={}, error="simulation timed out")
    assert r.succeeded is False


# --- dedupe_actions ----------------------------------------------------------

def test_dedupe_actions_merges_linked_findings():
    a1 = ExternalAction(
        mcp_server="openems",
        tool_name="openems_create_microstrip",
        params={"trace_width_mm": 0.2, "dielectric_height_mm": 0.1},
        rationale="r1",
        linked_finding_ids=["EMC-001"],
    )
    a2 = ExternalAction(
        mcp_server="openems",
        tool_name="openems_create_microstrip",
        params={"trace_width_mm": 0.2, "dielectric_height_mm": 0.1},
        rationale="r2 (duplicate)",
        linked_finding_ids=["SI-007"],
    )
    out = dedupe_actions([a1, a2])
    assert len(out) == 1
    assert set(out[0].linked_finding_ids) == {"EMC-001", "SI-007"}


def test_dedupe_actions_keeps_highest_priority():
    a_low = ExternalAction(
        mcp_server="openems",
        tool_name="t",
        params={"k": 1},
        rationale="r",
        priority=PRIORITY_NORMAL,
    )
    a_critical = ExternalAction(
        mcp_server="openems",
        tool_name="t",
        params={"k": 1},
        rationale="r2",
        priority=PRIORITY_CRITICAL,
    )
    out = dedupe_actions([a_low, a_critical])
    assert len(out) == 1
    # Lowest priority number wins (most-critical first)
    assert out[0].priority == PRIORITY_CRITICAL


def test_dedupe_actions_preserves_distinct_signatures():
    a1 = ExternalAction(mcp_server="openems", tool_name="t",
                        params={"k": 1}, rationale="r1")
    a2 = ExternalAction(mcp_server="openems", tool_name="t",
                        params={"k": 2}, rationale="r2")
    out = dedupe_actions([a1, a2])
    assert len(out) == 2


def test_dedupe_actions_handles_nested_params():
    a1 = ExternalAction(
        mcp_server="openems",
        tool_name="t",
        params={"geometry": {"w_mm": 0.2, "h_mm": 0.1}, "tags": ["si", "emc"]},
        rationale="r1",
    )
    a2 = ExternalAction(
        mcp_server="openems",
        tool_name="t",
        params={"geometry": {"w_mm": 0.2, "h_mm": 0.1}, "tags": ["si", "emc"]},
        rationale="r2",
    )
    out = dedupe_actions([a1, a2])
    assert len(out) == 1


# --- sort + filter -----------------------------------------------------------

def test_sort_by_priority_ascending():
    a_low = ExternalAction(mcp_server="o", tool_name="t", params={"k": 1}, rationale="r", priority=4)
    a_high = ExternalAction(mcp_server="o", tool_name="t", params={"k": 2}, rationale="r", priority=1)
    a_mid = ExternalAction(mcp_server="o", tool_name="t", params={"k": 3}, rationale="r", priority=2)
    out = sort_by_priority([a_low, a_high, a_mid])
    assert [a.priority for a in out] == [1, 2, 4]


def test_filter_pending_drops_completed():
    a = ExternalAction(mcp_server="o", tool_name="t", params={}, rationale="r")
    b = ExternalAction(mcp_server="o", tool_name="t2", params={}, rationale="r",
                       status=STATUS_COMPLETED)
    pending = filter_pending([a, b])
    assert pending == [a]


def test_has_pending_critical_true():
    a = ExternalAction(mcp_server="o", tool_name="t", params={}, rationale="r",
                       priority=PRIORITY_CRITICAL)
    assert has_pending_critical([a]) is True


def test_has_pending_critical_false_when_completed():
    a = ExternalAction(mcp_server="o", tool_name="t", params={}, rationale="r",
                       priority=PRIORITY_CRITICAL, status=STATUS_COMPLETED)
    assert has_pending_critical([a]) is False


def test_has_pending_critical_false_when_only_normal():
    a = ExternalAction(mcp_server="o", tool_name="t", params={}, rationale="r",
                       priority=PRIORITY_NORMAL)
    assert has_pending_critical([a]) is False

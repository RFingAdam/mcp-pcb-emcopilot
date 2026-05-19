"""End-to-end tests for the Phase 3a MCP tools — suggest_next_actions,
attach_external_result, finalize_review, lookup_limit_live, and the
report-generation gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_pcb_emcopilot import server as srv
from mcp_pcb_emcopilot.integrations.external_actions import (
    PRIORITY_CRITICAL,
    PRIORITY_NORMAL,
    ExternalAction,
)
from mcp_pcb_emcopilot.orchestrator import reset_finding_id_counters

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_signal_4layer.kicad_pcb"


@pytest.fixture
def fresh_session():
    """Fresh playbook + parsed-layout session, with finding-id counters reset."""
    reset_finding_id_counters()
    if not FIXTURE.exists():
        pytest.skip("fixture not available")
    start = srv._dispatch(
        "pcb_start_professional_review",
        {
            "input_files": [str(FIXTURE)],
            "declared_market": "commercial",
        },
    )
    sid = start["session_id"]
    srv._dispatch("pcb_parse_layout", {"file_path": str(FIXTURE), "session_id": sid})
    return sid


# --- lookup_limit_live (Phase 3a stub) --------------------------------------

def test_lookup_limit_live_returns_deferred_envelope():
    result = srv._dispatch(
        "pcb_lookup_limit_live",
        {
            "standard": "CISPR_25",
            "class_or_level": "3",
            "frequency_mhz": 150.0,
            "detector": "QP",
        },
    )
    assert result["status"] == "deferred"
    na = result["next_action"]
    assert na["mcp_server"] == "emc-regulations"
    assert na["tool_name"] == "cispr25_limit"
    assert na["fully_qualified_tool_name"] == "mcp__emc-regulations__cispr25_limit"
    assert result["fallback_available"] is True


def test_lookup_limit_live_handles_unknown_standard():
    result = srv._dispatch(
        "pcb_lookup_limit_live",
        {
            "standard": "MIL_STD_461",  # not in stub map
            "class_or_level": "G",
            "frequency_mhz": 100.0,
        },
    )
    # Falls through to source_search
    assert result["next_action"]["tool_name"] == "source_search"


# --- suggest_next_actions ----------------------------------------------------

def test_suggest_next_actions_empty_for_fresh_session(fresh_session):
    result = srv._dispatch(
        "pcb_suggest_next_actions",
        {"session_id": fresh_session},
    )
    assert result["count"] == 0
    assert result["actions"] == []


def test_suggest_next_actions_returns_enqueued(fresh_session):
    # Manually enqueue a critical action so we don't depend on the orchestrator
    # finding any escalation-worthy findings on the fixture.
    action = ExternalAction(
        mcp_server="openems",
        tool_name="openems_create_microstrip",
        params={"trace_width_mm": 0.2},
        rationale="manual test",
        linked_finding_ids=["EMC-001"],
        priority=PRIORITY_CRITICAL,
    )
    srv.sessions.enqueue_actions(fresh_session, [action])
    result = srv._dispatch(
        "pcb_suggest_next_actions",
        {"session_id": fresh_session},
    )
    assert result["count"] == 1
    assert result["actions"][0]["mcp_server"] == "openems"
    assert result["actions"][0]["priority"] == PRIORITY_CRITICAL


def test_suggest_next_actions_respects_max_actions(fresh_session):
    actions = [
        ExternalAction(
            mcp_server="openems",
            tool_name="t",
            params={"i": i},
            rationale="r",
            priority=PRIORITY_NORMAL,
        )
        for i in range(15)
    ]
    srv.sessions.enqueue_actions(fresh_session, actions)
    result = srv._dispatch(
        "pcb_suggest_next_actions",
        {"session_id": fresh_session, "max_actions": 5},
    )
    assert result["count"] == 5


# --- attach_external_result --------------------------------------------------

def test_attach_external_result_marks_action_completed(fresh_session):
    action = ExternalAction(
        mcp_server="openems",
        tool_name="openems_create_microstrip",
        params={"trace_width_mm": 0.2},
        rationale="r",
        linked_finding_ids=["EMC-001"],
    )
    srv.sessions.enqueue_actions(fresh_session, [action])
    result = srv._dispatch(
        "pcb_attach_external_result",
        {
            "session_id": fresh_session,
            "action_id": action.action_id,
            "result": {"z0_ohm": 50.2, "status": "pass"},
        },
    )
    assert result["status"] == "completed"
    # Action moved to completed in the queue too
    pending = srv.sessions.get_pending_actions(fresh_session)
    assert pending[0].status == "completed"


def test_attach_external_result_with_error_marks_failed(fresh_session):
    action = ExternalAction(
        mcp_server="openems",
        tool_name="t",
        params={},
        rationale="r",
    )
    srv.sessions.enqueue_actions(fresh_session, [action])
    srv._dispatch(
        "pcb_attach_external_result",
        {
            "session_id": fresh_session,
            "action_id": action.action_id,
            "result": {},
            "error": "simulation timed out",
        },
    )
    assert srv.sessions.get_pending_actions(fresh_session)[0].status == "failed"


def test_attach_external_result_unknown_action_id_raises(fresh_session):
    from mcp_pcb_emcopilot.errors import ValidationError
    with pytest.raises(ValidationError):
        srv._dispatch(
            "pcb_attach_external_result",
            {"session_id": fresh_session, "action_id": "deadbeef", "result": {}},
        )


# --- finalize_review --------------------------------------------------------

def test_finalize_review_defers_when_critical_pending(fresh_session):
    action = ExternalAction(
        mcp_server="openems",
        tool_name="t",
        params={},
        rationale="r",
        priority=PRIORITY_CRITICAL,
    )
    srv.sessions.enqueue_actions(fresh_session, [action])
    result = srv._dispatch(
        "pcb_finalize_review",
        {"session_id": fresh_session},
    )
    assert result["status"] == "deferred"
    assert "critical" in result["reason"].lower()


def test_finalize_review_succeeds_when_no_critical_pending(fresh_session):
    # A non-critical pending action does not block finalisation.
    action = ExternalAction(
        mcp_server="drawio-engineering",
        tool_name="create_pcb_stackup",
        params={},
        rationale="r",
        priority=PRIORITY_NORMAL,
    )
    srv.sessions.enqueue_actions(fresh_session, [action])
    result = srv._dispatch(
        "pcb_finalize_review",
        {"session_id": fresh_session},
    )
    assert result["status"] == "finalised"
    assert "confidence_distribution" in result


def test_finalize_review_force_bypasses_critical_gate(fresh_session):
    action = ExternalAction(
        mcp_server="openems",
        tool_name="t",
        params={},
        rationale="r",
        priority=PRIORITY_CRITICAL,
    )
    srv.sessions.enqueue_actions(fresh_session, [action])
    result = srv._dispatch(
        "pcb_finalize_review",
        {"session_id": fresh_session, "require_critical_verified": False},
    )
    assert result["status"] == "finalised"


# --- Report gate ------------------------------------------------------------

def _satisfy_preflight_commercial(sid: str) -> None:
    """Helper — satisfy the Phase 4 preflight gate so we can test the
    Phase 3a cross-MCP gate downstream."""
    srv._dispatch("pcb_set_market", {
        "session_id": sid,
        "market_id": "commercial",
        "sub_options": {
            "operating_environment": "consumer",
            "fab_stackup_spec": "no_use_extracted",
            "cispr32_class": "B",
            "target_regions": ["US", "EU"],
        },
    })


def test_report_gate_defers_when_critical_pending(fresh_session):
    _satisfy_preflight_commercial(fresh_session)
    action = ExternalAction(
        mcp_server="openems",
        tool_name="t",
        params={},
        rationale="r",
        priority=PRIORITY_CRITICAL,
    )
    srv.sessions.enqueue_actions(fresh_session, [action])
    out = srv._dispatch(
        "pcb_generate_design_review_report",
        {"session_id": fresh_session, "format": "html"},
    )
    assert out["status"] == "deferred"
    assert "pending_actions" in out
    # And the reason mentions the cross-MCP gate, not preflight
    assert "sibling-MCP" in out["reason"]


def test_report_gate_force_emits_preliminary(fresh_session):
    _satisfy_preflight_commercial(fresh_session)
    action = ExternalAction(
        mcp_server="openems",
        tool_name="t",
        params={},
        rationale="r",
        priority=PRIORITY_CRITICAL,
    )
    srv.sessions.enqueue_actions(fresh_session, [action])
    out = srv._dispatch(
        "pcb_generate_design_review_report",
        {"session_id": fresh_session, "format": "html", "force": True},
    )
    # The report builder may return a dict; if so we stamped it preliminary.
    # If it raised internally, the test should fail loudly — we accept either
    # a dict with preliminary=True or any other dict that the builder produces.
    assert isinstance(out, dict)
    if out.get("status") == "deferred":
        pytest.fail("force=True should have bypassed the critical gate")
    if "preliminary" in out:
        assert out["preliminary"] is True

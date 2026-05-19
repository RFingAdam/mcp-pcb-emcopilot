"""End-to-end test for the openEMS verification loop:

orchestrator emits action → Claude attaches a simulated value via
pcb_attach_external_result → compare_results runs → finding's verified /
confidence / severity update accordingly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_pcb_emcopilot import server as srv
from mcp_pcb_emcopilot.integrations.external_actions import (
    PRIORITY_HIGH,
    ExternalAction,
)
from mcp_pcb_emcopilot.orchestrator import reset_finding_id_counters

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_signal_4layer.kicad_pcb"


@pytest.fixture
def session_with_finding():
    """Session with one synthetic openEMS-bound action linked to one finding."""
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
    # Inject a synthetic finding into the session's review_results so the
    # attach handler has something to update.
    data = srv.sessions.get_session(sid)
    data.review_results = {
        "domain_results": [
            {
                "domain": "signal_integrity",
                "findings": [
                    {
                        "finding_id": "SI-001",
                        "domain": "signal_integrity",
                        "severity": "high",
                        "title": "Impedance mismatch",
                        "description": "trace measured at 55 ohms vs 50 target",
                        "confidence": 0.65,
                        "verified": False,
                        "source": "analytical",
                    }
                ],
            }
        ],
    }
    action = ExternalAction(
        mcp_server="openems",
        tool_name="openems_create_microstrip",
        params={
            "trace_width_mm": 0.2,
            "dielectric_height_mm": 0.1,
            "frequency_ghz": 1.0,
            "analytical_value": 55.0,
        },
        rationale="verify SI-001",
        linked_finding_ids=["SI-001"],
        priority=PRIORITY_HIGH,
    )
    srv.sessions.enqueue_actions(sid, [action])
    return sid, action


def _find_finding(sid: str, fid: str) -> dict:
    data = srv.sessions.get_session(sid)
    for dr in data.review_results["domain_results"]:
        for f in dr["findings"]:
            if f["finding_id"] == fid:
                return f
    raise AssertionError(f"finding {fid} not found")


def test_attach_passing_sim_sets_verified_and_high_confidence(session_with_finding):
    sid, action = session_with_finding
    # Simulated value within 5% tolerance → "pass"
    out = srv._dispatch(
        "pcb_attach_external_result",
        {
            "session_id": sid,
            "action_id": action.action_id,
            "result": {
                "simulated_value": 56.0,
                "analytical_value": 55.0,
                "unit": "ohms",
                "parameter": "impedance",
            },
        },
    )
    assert out["sim_status"] == "pass"
    f = _find_finding(sid, "SI-001")
    assert f["verified"] is True
    assert f["confidence"] == 0.95
    assert f["source"] == "openems"
    # Severity unchanged on pass
    assert f["severity"] == "high"


def test_attach_warning_sim_keeps_severity_lowers_confidence(session_with_finding):
    sid, action = session_with_finding
    # Difference 8% — outside 5% pass tolerance but within 10% warning band
    out = srv._dispatch(
        "pcb_attach_external_result",
        {
            "session_id": sid,
            "action_id": action.action_id,
            "result": {
                "simulated_value": 59.5,
                "analytical_value": 55.0,
                "unit": "ohms",
                "parameter": "impedance",
            },
        },
    )
    assert out["sim_status"] == "warning"
    f = _find_finding(sid, "SI-001")
    assert f["verified"] is True
    assert f["source"] == "openems"
    # Severity unchanged
    assert f["severity"] == "high"


def test_attach_failing_sim_escalates_to_critical(session_with_finding):
    sid, action = session_with_finding
    # Difference 30% — well past 2x tolerance → "fail"
    out = srv._dispatch(
        "pcb_attach_external_result",
        {
            "session_id": sid,
            "action_id": action.action_id,
            "result": {
                "simulated_value": 71.5,
                "analytical_value": 55.0,
                "unit": "ohms",
                "parameter": "impedance",
            },
        },
    )
    assert out["sim_status"] == "fail"
    f = _find_finding(sid, "SI-001")
    assert f["verified"] is True
    assert f["severity"] == "critical"
    assert f["source"] == "openems"
    assert "invalidates" in f["description"].lower()


def test_emc_regulations_attach_caches_live_value(session_with_finding):
    """Attaching an emc-regulations result should write to limits_provider."""
    from mcp_pcb_emcopilot.analyzers.emc.limits_provider import (
        clear_live_cache,
        get_limit,
    )

    sid, _openems_action = session_with_finding
    clear_live_cache()

    # Enqueue a regs action and attach a result for it.
    regs_action = ExternalAction(
        mcp_server="emc-regulations",
        tool_name="cispr25_limit",
        params={
            "standard": "CISPR_25",
            "class_or_level": "3",
            "frequency_mhz": 150.0,
            "detector": "QP",
        },
        rationale="live lookup",
        linked_finding_ids=["SI-001"],
    )
    srv.sessions.enqueue_actions(sid, [regs_action])

    out = srv._dispatch(
        "pcb_attach_external_result",
        {
            "session_id": sid,
            "action_id": regs_action.action_id,
            "result": {
                "limit_dbuv_per_m": 7.0,
                "band_min_mhz": 144.0,
                "band_max_mhz": 172.0,
            },
        },
    )
    assert out["live_limit_cached"] is True
    point = get_limit("CISPR_25", "3", 150.0)
    assert point.limit_value == 7.0
    assert point.source == "live_regs"
    clear_live_cache()

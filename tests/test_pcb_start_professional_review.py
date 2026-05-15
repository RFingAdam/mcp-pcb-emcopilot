"""End-to-end test for the pcb_start_professional_review MCP tool — the
entry point of the Claude-driven meticulous review workflow."""

from __future__ import annotations

import pytest

from mcp_pcb_emcopilot import server as srv


def test_dispatch_returns_playbook_and_manifest():
    result = srv._dispatch(
        "pcb_start_professional_review",
        {
            "input_files": [
                "board.kicad_pcb",
                "schematic.pdf",
                "stackup.json",
                "bom.csv",
                "model.step",
            ],
            "declared_market": "automotive",
            "product_description": "12 V dashboard accessory",
        },
    )
    assert isinstance(result, dict)
    # Mandatory keys are present
    for key in (
        "session_id",
        "playbook_markdown",
        "input_manifest",
        "gaps",
        "interview_pack",
        "standards_shortlist",
        "analyzer_shortlist",
        "pass_checklist",
        "declared_market",
    ):
        assert key in result, f"missing key {key}"
    # Manifest classified every input
    kinds = {m["kind"] for m in result["input_manifest"]}
    assert kinds == {"layout", "schematic", "stackup", "bom", "step"}
    # Automotive standards in shortlist
    assert "CISPR_25" in result["standards_shortlist"]
    # Automotive-pack questions appended to core
    qids = {q["id"] for q in result["interview_pack"]}
    assert "vehicle_class" in qids
    # No critical gaps (layout present)
    assert "layout" not in result["gaps"]
    # Pass checklist contains all 9 passes
    assert result["pass_checklist"] == ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]


def test_dispatch_creates_session_with_playbook_state():
    result = srv._dispatch(
        "pcb_start_professional_review",
        {
            "input_files": ["board.kicad_pcb"],
            "declared_market": "wireless",
        },
    )
    sid = result["session_id"]
    # Session was created and stored
    sess = srv.sessions.get_session(sid)
    assert sess is not None
    # Playbook state lives in review_context
    pb = sess.review_context.get("playbook")
    assert pb is not None
    assert pb["declared_market"] == "wireless"
    assert "FCC_47_CFR_15C" in pb["standards_shortlist"]


def test_dispatch_rejects_empty_input_files():
    from mcp_pcb_emcopilot.errors import ValidationError
    with pytest.raises(ValidationError):
        srv._dispatch(
            "pcb_start_professional_review",
            {"input_files": [], "declared_market": "automotive"},
        )


def test_dispatch_handles_unknown_market_gracefully():
    result = srv._dispatch(
        "pcb_start_professional_review",
        {
            "input_files": ["board.kicad_pcb"],
            "declared_market": "unknown",
        },
    )
    # Falls back to core questions only
    assert result["standards_shortlist"] == []
    assert any("market" in n.lower() for n in result["notes"])


def test_dispatch_handles_multi_market_combination():
    result = srv._dispatch(
        "pcb_start_professional_review",
        {
            "input_files": ["board.kicad_pcb"],
            "declared_market": "medical",
            "extra_markets": ["wireless"],
        },
    )
    # Both medical and wireless standards appear in the union
    s = set(result["standards_shortlist"])
    assert "IEC_60601_1_2_ED_4_1" in s
    assert "FCC_47_CFR_15C" in s
    # Question pack contains both medical and wireless ids
    qids = {q["id"] for q in result["interview_pack"]}
    assert "device_class" in qids  # medical
    assert "tx_power_dbm" in qids  # wireless


def test_parse_layout_can_reuse_playbook_session(tmp_path):
    """Confirm pcb_parse_layout accepts an existing session_id from
    pcb_start_professional_review and preserves the playbook state."""
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "mixed_signal_4layer.kicad_pcb"
    if not fixture.exists():
        pytest.skip("fixture not available")

    start_result = srv._dispatch(
        "pcb_start_professional_review",
        {
            "input_files": [str(fixture)],
            "declared_market": "commercial",
        },
    )
    sid = start_result["session_id"]
    parse_result = srv._dispatch(
        "pcb_parse_layout",
        {"file_path": str(fixture), "session_id": sid},
    )
    assert parse_result["session_id"] == sid
    # Playbook state is preserved through the parse
    sess = srv.sessions.get_session(sid)
    assert sess is not None
    assert sess.review_context.get("playbook", {}).get("declared_market") == "commercial"
    # And the design data is now populated
    assert sess.source_format != "pending-parse"

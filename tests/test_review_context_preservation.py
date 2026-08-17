"""set_review_context must not destroy sibling review_context buckets.

``review_context`` is a shared namespace written by four different tools:

- ``pcb_start_professional_review`` -> ``playbook``
- ``pcb_set_market``               -> ``markets``, ``target_standards``
- ``pcb_answer_review_questions``  -> ``interactive_answers``
- ``pcb_set_review_context``       -> design_intent, known_issues, ...

``set_review_context`` assigned a freshly-built dict over the whole namespace,
so calling it after any of the others silently discarded their state. In the
documented workflow order (start review -> set market -> set context -> run
review) that means the playbook, the selected markets and every answered
interactive question were gone by the time the review ran — and the review then
proceeded against defaults with no indication anything was lost.
"""
from __future__ import annotations

from mcp_pcb_emcopilot.models.pcb_data import PCBDesignData
from mcp_pcb_emcopilot.orchestrator import set_review_context


def _design_with_sibling_buckets() -> PCBDesignData:
    """A session mid-workflow: playbook + market + answers already stored."""
    d = PCBDesignData(source_file="/tmp/b.kicad_pcb")
    d.review_context = {
        "playbook": {
            "input_manifest": [{"path": "board.kicad_pcb", "kind": "layout"}],
            "gaps": ["no stackup supplied"],
            "standards_shortlist": ["CISPR_32"],
        },
        "markets": ["wireless"],
        "interactive_answers": {"q_enclosure": "plastic", "q_cable": "shielded"},
        "target_standards": ["CISPR_32", "FCC_B"],
    }
    return d


def test_playbook_bucket_survives():
    d = _design_with_sibling_buckets()
    set_review_context(design=d, design_intent="10-layer module")
    assert "playbook" in d.review_context
    assert d.review_context["playbook"]["standards_shortlist"] == ["CISPR_32"]


def test_markets_bucket_survives():
    d = _design_with_sibling_buckets()
    set_review_context(design=d, design_intent="10-layer module")
    assert d.review_context["markets"] == ["wireless"]


def test_interactive_answers_survive():
    d = _design_with_sibling_buckets()
    set_review_context(design=d, design_intent="10-layer module")
    assert d.review_context["interactive_answers"]["q_enclosure"] == "plastic"
    assert len(d.review_context["interactive_answers"]) == 2


def test_unspecified_target_standards_are_not_reset_to_the_default():
    """A market-derived shortlist must not be clobbered by the FCC_B default.

    This is the subtlest half of the bug: the caller did not ask to change
    target_standards, so replacing them with the function's own default is a
    silent downgrade of the review's scope.
    """
    d = _design_with_sibling_buckets()
    set_review_context(design=d, design_intent="unchanged standards")
    assert d.review_context["target_standards"] == ["CISPR_32", "FCC_B"]


def test_explicitly_supplied_values_still_win():
    d = _design_with_sibling_buckets()
    set_review_context(design=d, target_standards=["CISPR_25"])
    assert d.review_context["target_standards"] == ["CISPR_25"]


def test_unspecified_design_intent_is_preserved():
    d = _design_with_sibling_buckets()
    set_review_context(design=d, design_intent="first")
    set_review_context(design=d, known_issues=["late issue"])
    assert d.review_context["design_intent"] == "first"
    assert d.review_context["known_issues"] == ["late issue"]


def test_returned_context_matches_what_was_stored():
    """Existing contract: the return value is the stored context, not a subset."""
    d = _design_with_sibling_buckets()
    ctx = set_review_context(design=d, design_intent="x")
    assert d.review_context == ctx
    assert "playbook" in ctx


def test_fresh_design_still_gets_documented_defaults():
    """Regression guard for the no-prior-context path."""
    d = PCBDesignData(source_file="/tmp/b.kicad_pcb")
    ctx = set_review_context(design=d)
    assert ctx["design_intent"] == ""
    assert ctx["target_standards"] == ["FCC_B"]
    assert ctx["known_issues"] == []
    assert ctx["impedance_targets"] == {}
    assert ctx["thermal_limits"] == {}
    assert ctx["operating_conditions"] == {}
    assert "set_at" in ctx

"""A missing input must produce a refusal, never a fabricated number.

Several analyzers iterate a collection that is empty on an unparsed or
partially-parsed design, produce zero findings, and report that as a clean
result. For a compliance-adjacent tool, "we could not look" and "we looked and
it is fine" must never serialise to the same thing.

This covers the mechanism itself — the typed error, the `require_data` helper,
the MCP serialisation contract, and the orchestrator's third coverage-gap
status. Producers are wired up separately; a mechanism with no producers is
deliberately a no-op so it can be reviewed on its own.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from mcp_pcb_emcopilot import server as srv
from mcp_pcb_emcopilot.errors import (
    AnalysisError,
    InsufficientDataError,
    InsufficientSystemContextError,
    PCBError,
    ValidationError,
    require_data,
)
from mcp_pcb_emcopilot.orchestrator import DomainResult, _build_executive_summary


def _cls():
    import types
    return types.SimpleNamespace(design_type="mixed_signal", complexity_label="moderate")


# ---------------------------------------------------------------------------
# require_data
# ---------------------------------------------------------------------------

def test_require_data_is_silent_when_everything_is_present():
    require_data("x", nets=[1], layers=[2], vias=[3])  # must not raise


def test_require_data_names_every_missing_input():
    with pytest.raises(InsufficientDataError) as exc:
        require_data("return path analysis", nets=[], layers=[], vias=[1])
    assert exc.value.context["missing"] == ["layers", "nets"]  # sorted
    assert exc.value.context["analysis"] == "return path analysis"
    assert exc.value.code == "INSUFFICIENT_DATA"


def test_require_data_message_says_it_is_not_a_pass():
    """The message is the last line of defence if a caller logs it verbatim."""
    with pytest.raises(InsufficientDataError) as exc:
        require_data("stitching analysis", vias=[])
    assert "not a pass" in exc.value.message
    assert "vias" in exc.value.message


@pytest.mark.parametrize("empty", [[], {}, None, 0, "", set()])
def test_all_falsy_input_shapes_are_treated_as_missing(empty):
    with pytest.raises(InsufficientDataError):
        require_data("x", thing=empty)


# ---------------------------------------------------------------------------
# Type relationships — these decide how the error travels.
# ---------------------------------------------------------------------------

def test_is_a_pcberror_so_the_mcp_layer_serialises_it():
    assert issubclass(InsufficientDataError, PCBError)


def test_is_distinct_from_validation_and_analysis_errors():
    """Different meanings: bad input vs failed computation vs absent input."""
    assert not issubclass(InsufficientDataError, ValidationError)
    assert not issubclass(InsufficientDataError, AnalysisError)


def test_is_not_an_importerror():
    """test_all_tools_smoke treats ImportError as a structural dispatch failure.

    If InsufficientDataError were one, every guarded tool would fail the
    full-surface smoke test rather than being recognised as behaving correctly.
    """
    assert not issubclass(InsufficientDataError, ImportError)


def test_is_not_classified_as_a_structural_smoke_failure():
    from test_all_tools_smoke import _is_structural_failure
    err = InsufficientDataError("INSUFFICIENT_DATA", "no nets", {"missing": ["nets"]})
    assert _is_structural_failure(err) is False


def test_system_context_error_is_a_subclass_but_identifiable():
    """Missing carrier dimensions is a data gap with a different remedy."""
    assert issubclass(InsufficientSystemContextError, InsufficientDataError)
    err = InsufficientSystemContextError("INSUFFICIENT_SYSTEM_CONTEXT", "no carrier", {})
    assert isinstance(err, InsufficientDataError)
    assert err.to_dict()["error_type"] == "InsufficientSystemContextError"


# ---------------------------------------------------------------------------
# MCP serialisation: a refusal must be distinguishable from a result.
# ---------------------------------------------------------------------------

def test_pcberror_response_carries_success_false():
    """`to_dict()` omits `success`, and the success path defaults it to True.

    Without an explicit False a structured refusal was indistinguishable from
    an answer to any client reading the `success` field.
    """
    content = asyncio.run(srv.call_tool("pcb_parse_layout", {"file_path": "/nonexistent/x.kicad_pcb"}))
    payload = json.loads(content[0].text)
    assert payload["success"] is False
    assert payload["code"] == "FILE_NOT_FOUND"
    assert payload["message"]


def test_error_payload_keeps_the_diagnostic_fields():
    content = asyncio.run(srv.call_tool("pcb_parse_layout", {"file_path": "/nonexistent/x.kicad_pcb"}))
    payload = json.loads(content[0].text)
    assert payload["error_type"] == "ParseError"
    assert "context" in payload


def test_successful_call_still_reports_success_true():
    """Regression guard: the refusal fix must not disturb the success path."""
    content = asyncio.run(srv.call_tool(
        "pcb_calc_via_stitching", {"max_frequency_mhz": 600.0, "dielectric_constant": 4.3}
    ))
    payload = json.loads(content[0].text)
    assert payload["success"] is True


# ---------------------------------------------------------------------------
# Orchestrator plumbing.
# ---------------------------------------------------------------------------

def test_domain_result_carries_missing_inputs():
    dr = DomainResult(
        domain="emc_return_path",
        status="insufficient_data",
        missing_inputs=["nets", "layers"],
    )
    d = dr.to_dict()
    assert d["status"] == "insufficient_data"
    assert d["missing_inputs"] == ["nets", "layers"]


def test_missing_inputs_is_omitted_when_empty():
    """Keep the payload clean for the overwhelmingly common case."""
    assert "missing_inputs" not in DomainResult(domain="x", status="pass").to_dict()


def test_insufficient_data_is_a_coverage_gap_not_a_pass():
    assessed = DomainResult(domain="emc_grounding", status="pass")
    no_data = DomainResult(
        domain="emc_return_path", status="insufficient_data", missing_inputs=["nets"]
    )
    s = _build_executive_summary([assessed, no_data], _cls(), [])
    assert s["overall_status"] == "INCONCLUSIVE"
    assert s["domains_insufficient"] == 1
    assert s["coverage_complete"] is False
    assert "insufficient data" in s["verdict_reason"]


def test_insufficient_data_does_not_count_as_assessed():
    no_data = DomainResult(domain="emc_return_path", status="insufficient_data")
    s = _build_executive_summary([no_data], _cls(), [])
    assert s["domains_assessed"] == 0
    assert s["overall_status"] == "INCONCLUSIVE"


def test_a_critical_finding_still_outranks_an_insufficient_data_gap():
    """A real critical on partial data is actionable and must not be softened."""
    import types
    crit = DomainResult(
        domain="emc", status="fail",
        findings=[types.SimpleNamespace(severity="critical")],
    )
    no_data = DomainResult(domain="pdn", status="insufficient_data")
    s = _build_executive_summary([crit, no_data], _cls(), [])
    assert s["overall_status"] == "FAIL"

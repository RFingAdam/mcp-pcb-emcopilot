"""Full-surface smoke test: invoke every MCP tool on a parsed fixture.

Existence proof that all 116 tool-dispatch branches are structurally
sound. For each registered tool the test:

1. reads the tool's declared ``inputSchema`` from :func:`list_tools`
   (the same schema returned to MCP clients);
2. synthesises minimal-but-plausible arguments from that schema —
   numbers default to small positive reals, integers to 1, strings to
   per-field domain-valid defaults (e.g. ``"DDR4"`` for ``ddr_standard``,
   ``"copper"`` for ``material``), arrays to single-element lists, etc.;
3. invokes the dispatch function and asserts no *structural* exception
   escapes. "Structural" = :class:`AttributeError`, :class:`NameError`,
   :class:`ImportError`, or a :class:`TypeError` from a signature
   mismatch — these always indicate a broken dispatch branch. Domain
   validation errors (``ValueError``, ``KeyError`` on unknown inputs,
   domain-specific ``ValidationError``) are considered *correct* tool
   behaviour — the tool rejected synthetic input and that's fine.

The test also verifies registry ↔ dispatch parity: every tool declared
to clients has a dispatch branch, and vice-versa.

Assertion is aggregate — the test reports every failing tool at once
so a broad regression produces a complete punch-list, not a one-at-a-
time iteration loop.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import pytest

from mcp_pcb_emcopilot import server as srv
from mcp_pcb_emcopilot.parsers import parse_pcb_file

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_signal_4layer.kicad_pcb"

# Domain-meaningful defaults keyed by property name substring. Checked in
# order — first match wins. Keeps the mapping terse while covering the
# cases where a generic number default (0.1) would fail semantic validation.
_STRING_DEFAULTS: dict[str, str] = {
    "ddr_standard": "DDR4",
    "pcie_gen": "gen3",
    "usb_version": "USB 2.0",
    "ethernet_speed": "100BASE-TX",
    "topology": "pi",
    "material": "copper",
    "conductor": "copper",
    "shield_material": "copper",
    "interface_type": "DDR",
    "render_type": "board",
    "model_type": "microstrip",
    "structure_type": "microstrip",
    "file_path": str(FIXTURE),
    "output_path": "",
    "output_dir": "",
    "net_name": "GND",
    "class_level": "3",
    "severity": "L3",
    "format": "detailed",
    "parameter": "impedance_ohm",
    "finding_id": "EMC-001",
    "session_id_a": "",  # replaced per-call
    "session_id_b": "",  # replaced per-call
    "schematic_path": "",
}


def _default_for_schema(prop: str, spec: dict[str, Any]) -> Any:
    """Return a minimal-valid value for a schema property."""
    t = spec.get("type")
    if isinstance(t, list):  # e.g. ["number", "null"]
        t = next((x for x in t if x != "null"), t[0])

    if t == "number":
        return 1.0
    if t == "integer":
        return 1
    if t == "boolean":
        return False
    if t == "array":
        item = spec.get("items", {})
        return [_default_for_schema(prop, item)]
    if t == "object":
        return {}
    # String — prefer a domain-meaningful default if the property name hints.
    lower = prop.lower()
    for key, val in _STRING_DEFAULTS.items():
        if key in lower:
            return val
    return "default"


def _build_args(schema: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Build a minimal-valid arg dict from a tool's inputSchema."""
    props = schema.get("properties", {})
    required = schema.get("required", [])
    args: dict[str, Any] = {}
    for name in required:
        if name == "session_id":
            args[name] = session_id
        elif name in ("session_id_a", "session_id_b"):
            args[name] = session_id
        elif name == "file_path":
            args[name] = str(FIXTURE)
        else:
            args[name] = _default_for_schema(name, props.get(name, {}))
    # A few tools take optional session_id without declaring it required.
    if "session_id" in props and "session_id" not in args:
        args["session_id"] = session_id
    return args


# ---------------------------------------------------------------------------
# Classification of dispatch exceptions
# ---------------------------------------------------------------------------

# Structural: dispatch wiring is broken — always a defect.
_STRUCTURAL_EXC = (AttributeError, NameError)


def _is_structural_failure(exc: BaseException) -> bool:
    """True if the exception indicates a broken dispatch branch.

    Validation errors (domain-specific ``ValidationError``, ``KeyError``
    on a synthesised arg the analyzer didn't accept, ``ValueError`` /
    ``FileNotFoundError`` when we hand the tool an implausible input) are
    the tool working correctly. ``TypeError`` is structural iff it's a
    signature mismatch (``unexpected keyword argument`` /
    ``missing N required positional`` / ``got multiple values``).
    """
    if isinstance(exc, _STRUCTURAL_EXC):
        return True
    if isinstance(exc, ImportError):
        return True
    if isinstance(exc, TypeError):
        msg = str(exc)
        return any(tok in msg for tok in (
            "unexpected keyword argument",
            "missing",
            "got multiple values",
            "positional argument",
        ))
    return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def session_id() -> str:
    data = parse_pcb_file(str(FIXTURE))
    return srv.sessions.create_session(data)


@pytest.fixture(scope="module")
def registered_tools() -> list:
    return asyncio.run(srv.list_tools())


@pytest.fixture(scope="module")
def registered_tool_names(registered_tools) -> list[str]:
    return [t.name for t in registered_tools]


@pytest.fixture(scope="module")
def dispatch_branch_names() -> set[str]:
    source = Path(srv.__file__).read_text()
    return set(re.findall(r'if name == "(pcb_[a-z0-9_]+)"', source))


# ---------------------------------------------------------------------------
# Structural: registry ↔ dispatch parity
# ---------------------------------------------------------------------------

class TestToolSurfaceParity:
    def test_registered_tool_count(self, registered_tool_names):
        assert len(registered_tool_names) == 130

    def test_every_registered_tool_has_dispatch_branch(
        self, registered_tool_names, dispatch_branch_names
    ):
        missing = [t for t in registered_tool_names if t not in dispatch_branch_names]
        assert not missing, f"registered tools without dispatch branch: {missing}"

    def test_every_dispatch_branch_has_registered_tool(
        self, registered_tool_names, dispatch_branch_names
    ):
        extra = dispatch_branch_names - set(registered_tool_names)
        assert not extra, f"dispatch branches without registered tool: {extra}"


# ---------------------------------------------------------------------------
# Behavioural: every dispatch branch is structurally sound
# ---------------------------------------------------------------------------

class TestEveryToolStructurallySound:
    def test_no_structural_failures(self, session_id, registered_tools):
        structural: list[str] = []
        malformed_errors: list[str] = []

        for tool in registered_tools:
            args = _build_args(tool.inputSchema or {}, session_id)
            try:
                result = srv._dispatch(tool.name, args)
            except Exception as e:
                if _is_structural_failure(e):
                    structural.append(f"{tool.name}: {type(e).__name__}: {e}")
                # Domain-validation exceptions are the tool behaving correctly.
                continue

            if isinstance(result, dict) and result.get("success") is False:
                if not (result.get("error") or result.get("message")):
                    malformed_errors.append(
                        f"{tool.name}: error response without 'error'/'message': {result!r}"
                    )

        failures = structural + malformed_errors
        assert not failures, (
            "tool smoke failures:\n" + "\n".join(failures)
        )

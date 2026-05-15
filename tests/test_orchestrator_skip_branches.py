"""Regression tests for the five ``result.status = "skipped"`` branches
in :mod:`mcp_pcb_emcopilot.orchestrator`.

Each analyzer domain (PDN, DDR, USB, PCIe, Ethernet) emits ``skipped``
only when the input truly lacks applicable data — never to paper over a
bug. These tests pin that contract: they build the minimal design state
that should drive each branch to ``skipped``, and assert the orchestrator
returns that status cleanly.

If any of these start failing, the skip logic has drifted — either a
classifier changed its output format, or a genuine defect is hiding
behind a silent bypass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mcp_pcb_emcopilot.classifiers.interface_detector import InterfaceDetectionResult
from mcp_pcb_emcopilot.classifiers.net_classifier import NetClassificationResult
from mcp_pcb_emcopilot.orchestrator import (
    _run_ddr_analysis,
    _run_ethernet_analysis,
    _run_pcie_analysis,
    _run_pdn_analysis,
    _run_usb_analysis,
)
from mcp_pcb_emcopilot.parsers import parse_pcb_file

FIXTURE = Path(__file__).parent / "fixtures" / "mixed_signal_4layer.kicad_pcb"


@dataclass
class _FakeNet:
    name: str
    category: str = "unknown"


@dataclass
class _FakeClassification:
    """Minimal stand-in for :class:`NetClassificationResult`."""
    classified_nets: list[_FakeNet] = field(default_factory=list)


@dataclass
class _FakeInterface:
    interface_type: str


@dataclass
class _FakeInterfaceResult:
    interfaces: list[_FakeInterface] = field(default_factory=list)


def _empty_design():
    return parse_pcb_file(str(FIXTURE))


def _empty_nets() -> NetClassificationResult:
    # NetClassifier().classify() expects a design; we need a result whose
    # ``classified_nets`` is an iterable of things exposing ``.category``
    # and ``.name``. The orchestrator only reads those two fields on this
    # branch, so a duck-typed stand-in is sufficient and keeps the test
    # fast and deterministic.
    return _FakeClassification(classified_nets=[_FakeNet(name="SIG1", category="signal")])  # type: ignore[return-value]


def _empty_interfaces() -> InterfaceDetectionResult:
    return _FakeInterfaceResult(interfaces=[])  # type: ignore[return-value]


def test_pdn_skips_when_no_power_nets():
    design = _empty_design()
    nets = _empty_nets()  # only signal, no power
    result = _run_pdn_analysis(design, nets)
    assert result.status == "skipped"
    assert result.error is None


def test_ddr_skips_when_no_ddr_interface():
    design = _empty_design()
    result = _run_ddr_analysis(design, _empty_interfaces(), _empty_nets())
    assert result.status == "skipped"
    assert result.error is None


def test_usb_skips_when_no_usb_interface():
    design = _empty_design()
    result = _run_usb_analysis(design, _empty_interfaces(), _empty_nets())
    assert result.status == "skipped"
    assert result.error is None


def test_pcie_skips_when_no_pcie_interface():
    design = _empty_design()
    result = _run_pcie_analysis(design, _empty_interfaces(), _empty_nets())
    assert result.status == "skipped"
    assert result.error is None


def test_ethernet_skips_when_no_ethernet_interface():
    design = _empty_design()
    result = _run_ethernet_analysis(design, _empty_interfaces(), _empty_nets())
    assert result.status == "skipped"
    assert result.error is None


def test_ethernet_substring_match_catches_future_variants():
    """Pins the substring fix at orchestrator.py:1113.

    Prior to the fix, the Ethernet branch used exact-membership on a
    fixed tuple (``"gbe"``, ``"100base-tx"``, ``"sgmii"``, ``"ethernet"``),
    which meant any new variant (``"1000BASE-T"``, ``"2.5GbE"``, ``"10GbE"``)
    would silently skip. The branch now substring-matches the same four
    tokens, bringing symmetry with DDR/USB/PCIe.
    """
    design = _empty_design()
    interfaces = _FakeInterfaceResult(interfaces=[_FakeInterface(interface_type="1000BASE-T")])
    # The call must not return ``skipped`` — the interface should be picked up.
    # It may legitimately fail with another status once the analyzer runs on
    # the stub interface; what matters is that skip-on-absence is gone.
    result = _run_ethernet_analysis(design, interfaces, _empty_nets())  # type: ignore[arg-type]
    assert result.status != "skipped", (
        "1000BASE-T variant should be caught by substring match"
    )

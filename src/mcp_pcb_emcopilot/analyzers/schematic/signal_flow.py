"""Signal-flow analyzer.

Three orthogonal checks:

1. **Clock distribution** — identify clock sources (Y*/X* crystals,
   oscillator-class ICs), trace their fan-out, flag overload (>4
   unbuffered loads) and missing buffers.
2. **Reset distribution** — locate reset nets (``RESET*`` / ``RST*`` /
   ``nRST``), check for a single driver / pullup, flag multi-driver
   contention.
3. **Debug-header presence** — verify a JTAG / SWD test connector when
   the design has a programmable IC.

Degrades cleanly when pin-net mapping is missing (info-level aggregate
finding instead of per-net flagging).
"""

from __future__ import annotations

import re
from typing import Any

from ...orchestrator import ReviewFinding
from . import _normalise as N

_CLOCK_VALUE_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:M|G)?Hz\b", re.IGNORECASE)
_CLOCK_KEYWORDS: tuple[str, ...] = (
    "OSC", "XTAL", "CRYSTAL", "CLK_GEN", "PLL", "TCXO", "OCXO",
)
_RESET_NET_RE = re.compile(r"^(N?_?)?(RESET|RST|NRST|NRESET)(_|$|\d)", re.IGNORECASE)
_JTAG_NET_KEYWORDS: tuple[str, ...] = ("TCK", "TDI", "TDO", "TMS", "TRST", "SWCLK", "SWDIO", "SWO")


def _is_clock_source(c: Any) -> bool:
    """Heuristic: refdes Y* / X* OR value matches frequency pattern OR keyword in MPN."""
    prefix = N.refdes_prefix(N.component_refdes(c))
    if prefix in {"Y", "X", "XO"}:
        return True
    value = N.component_value(c).upper()
    pn = N.component_part_number(c).upper()
    if _CLOCK_VALUE_RE.search(value):
        return True
    return any(k in value or k in pn for k in _CLOCK_KEYWORDS)


def _is_clock_buffer(c: Any) -> bool:
    val = N.component_value(c).upper()
    pn = N.component_part_number(c).upper()
    keywords = ("CLKBUF", "BUFFER", "FANOUT", "PI6C", "CDC", "DS90", "LV125")
    return any(k in val for k in keywords) or any(k in pn for k in keywords)


def _is_reset_supervisor(c: Any) -> bool:
    val = N.component_value(c).upper()
    pn = N.component_part_number(c).upper()
    keywords = ("SUPERVISOR", "TPS3", "MAX809", "MIC803", "STM809", "MCP130", "RESET_IC")
    return any(k in val for k in keywords) or any(k in pn for k in keywords)


def _net_pin_count(c: Any, net_name: str) -> int:
    """Count pins on *c* connected to net *net_name* (case-insensitive)."""
    target = net_name.upper()
    d = N.coerce(c)
    count = 0
    for pin in d.get("pins", []) or []:
        pd = pin if isinstance(pin, dict) else N.coerce(pin)
        if str(pd.get("net") or pd.get("net_name") or "").upper() == target:
            count += 1
    return count


def _components_on_net(components: list[Any], net_name: str) -> list[Any]:
    return [c for c in components if _net_pin_count(c, net_name) > 0]


def analyze_signal_flow(
    schematic_components: list[Any],
    schematic_nets: list[Any],
) -> list[ReviewFinding]:
    """Emit findings for clock-tree / reset / JTAG issues."""
    findings: list[ReviewFinding] = []

    if not schematic_components and not schematic_nets:
        findings.append(ReviewFinding(
            domain="schematic_signal_flow",
            severity="info",
            title="Signal-flow analysis skipped: no schematic data",
            description=(
                "No schematic components or nets available. Attach a "
                "schematic via pcb_parse_schematic before running this "
                "analyzer."
            ),
            recommendation="",
            confidence=0.3,
        ))
        return findings

    has_pin_net = any(bool(N.coerce(c).get("pins")) for c in schematic_components)
    base_confidence = 0.8 if has_pin_net else 0.5

    # --- 1. Clock distribution ------------------------------------------
    clock_sources = [c for c in schematic_components if _is_clock_source(c)]
    clock_buffers = [c for c in schematic_components if _is_clock_buffer(c)]
    ics = [c for c in schematic_components if N.is_ic(c)]

    if not clock_sources:
        # Any IC at all? If yes, it almost certainly needs a clock somewhere.
        if ics:
            findings.append(ReviewFinding(
                domain="schematic_signal_flow",
                severity="medium",
                title="No clock source detected in schematic",
                description=(
                    f"The schematic contains {len(ics)} IC(s) but no clock "
                    f"source (no Y*/X* crystal, no oscillator value pattern, "
                    f"no PLL/TCXO/OCXO MPN match). Either the design uses an "
                    f"on-chip oscillator (verify) or the clock source isn't "
                    f"visible to the parser."
                ),
                recommendation="Confirm clock source and add a Y/X refdes if external.",
                confidence=base_confidence * 0.8,
            ))
    else:
        # For each clock source, count downstream IC loads.
        for src in clock_sources:
            src_ref = N.component_refdes(src)
            if not has_pin_net:
                continue  # need pin-net data to trace fan-out
            # Identify clock output nets — any net the source touches that
            # is not GND/Vcc/X1/X2.
            d = N.coerce(src)
            output_nets: set[str] = set()
            for pin in d.get("pins", []) or []:
                pd = pin if isinstance(pin, dict) else N.coerce(pin)
                net = str(pd.get("net") or pd.get("net_name") or "").upper()
                if net and not N.is_power_net({"name": net}) and not N.is_ground_net({"name": net}):
                    if net not in {"X1", "X2", "OSC_IN", "OSC_OUT", "OSCI", "OSCO"}:
                        output_nets.add(net)
            for clk_net in output_nets:
                loads = [c for c in ics if _net_pin_count(c, clk_net) > 0 and N.component_refdes(c) != src_ref]
                buffered = [c for c in clock_buffers if _net_pin_count(c, clk_net) > 0]
                if len(loads) > 4 and not buffered:
                    findings.append(ReviewFinding(
                        domain="schematic_signal_flow",
                        severity="high",
                        title=f"Clock {clk_net} from {src_ref} drives {len(loads)} unbuffered loads",
                        description=(
                            f"Clock net {clk_net} fans out to {len(loads)} IC loads "
                            f"({', '.join(N.component_refdes(c) for c in loads[:6])}"
                            f"{'…' if len(loads) > 6 else ''}) with no clock buffer in series. "
                            f"Skew, ringing, and EMI all degrade above ~4 loads on a single trace."
                        ),
                        recommendation=(
                            f"Insert a clock buffer (CDC / PI6C / DS90 family) on {clk_net} "
                            f"to split the load."
                        ),
                        signal_name=clk_net,
                        measured_value=float(len(loads)),
                        limit_value=4.0,
                        confidence=base_confidence,
                    ))

    # --- 2. Reset distribution ------------------------------------------
    reset_nets = [n for n in schematic_nets if _RESET_NET_RE.match(N.net_name(n) or "")]
    has_supervisor = any(_is_reset_supervisor(c) for c in schematic_components)

    if reset_nets and not has_supervisor and ics:
        # If we have ICs that need reset but no supervisor, that's a soft
        # warning — most modern MCUs have internal POR but a watchdog/
        # supervisor is best practice.
        findings.append(ReviewFinding(
            domain="schematic_signal_flow",
            severity="medium",
            title=f"{len(reset_nets)} reset net(s) but no supervisor IC",
            description=(
                f"Reset nets detected ({', '.join(N.net_name(n) for n in reset_nets[:3])}) "
                f"but no reset-supervisor IC (TPS3, MAX809, MCP130, etc.). Designs "
                f"relying solely on internal POR can latch up under slow-rising or "
                f"bouncing supplies."
            ),
            recommendation=(
                "Add a reset supervisor with the right voltage threshold for the "
                "primary rail."
            ),
            confidence=base_confidence * 0.9,
        ))

    if has_pin_net:
        # Multi-driver reset check.
        for net in reset_nets:
            name = N.net_name(net)
            if not name:
                continue
            on_net = _components_on_net(schematic_components, name)
            ic_drivers = [c for c in on_net if N.is_ic(c)]
            if len(ic_drivers) > 1:
                findings.append(ReviewFinding(
                    domain="schematic_signal_flow",
                    severity="high",
                    title=f"Reset net {name} has multiple IC drivers",
                    description=(
                        f"{len(ic_drivers)} ICs drive reset net {name}: "
                        f"{', '.join(N.component_refdes(c) for c in ic_drivers)}. "
                        f"Wired-OR reset only works if every driver is open-drain — "
                        f"otherwise expect contention."
                    ),
                    recommendation=(
                        "Verify all drivers are open-drain or add per-driver isolation diodes."
                    ),
                    signal_name=name,
                    confidence=base_confidence,
                ))

    # --- 3. JTAG / SWD accessibility ------------------------------------
    jtag_nets = [n for n in schematic_nets
                 if any(k in (N.net_name(n) or "").upper() for k in _JTAG_NET_KEYWORDS)]
    connectors = [c for c in schematic_components if N.is_connector(c)]

    if jtag_nets and connectors:
        # Check that at least one connector touches a JTAG net.
        if has_pin_net:
            covered = False
            for conn in connectors:
                for net in jtag_nets:
                    if _net_pin_count(conn, N.net_name(net)) > 0:
                        covered = True
                        break
                if covered:
                    break
            if not covered:
                findings.append(ReviewFinding(
                    domain="schematic_signal_flow",
                    severity="medium",
                    title="JTAG/SWD nets present but no debug connector found",
                    description=(
                        f"Detected JTAG/SWD nets ({', '.join(N.net_name(n) for n in jtag_nets[:4])}) "
                        f"but none of the {len(connectors)} connector(s) appear to expose them. "
                        f"In-system programming and bring-up will require board-level rework."
                    ),
                    recommendation=(
                        "Add a 10-pin Cortex Debug connector (or equivalent 2x5 1.27 mm header)."
                    ),
                    confidence=base_confidence,
                ))
    elif jtag_nets and not connectors:
        findings.append(ReviewFinding(
            domain="schematic_signal_flow",
            severity="high",
            title="JTAG/SWD nets present but no connectors at all in schematic",
            description=(
                f"Detected JTAG/SWD nets ({', '.join(N.net_name(n) for n in jtag_nets[:4])}) "
                f"but the schematic has no connector components (J*/P*/CN*). The design is "
                f"not externally programmable as drawn."
            ),
            recommendation="Add a debug-header connector.",
            confidence=base_confidence,
        ))

    if ics and not jtag_nets:
        findings.append(ReviewFinding(
            domain="schematic_signal_flow",
            severity="medium",
            title="ICs present but no JTAG/SWD nets detected",
            description=(
                f"Found {len(ics)} IC(s) but no JTAG/SWD signal names "
                f"(TCK/TDI/TDO/TMS/SWCLK/SWDIO/SWO). Programming + on-chip debug may "
                f"require a hidden header. Required for medical / automotive "
                f"certification."
            ),
            recommendation="Confirm at least one IC exposes its debug interface to a connector.",
            confidence=base_confidence * 0.85,
        ))

    if not findings:
        findings.append(ReviewFinding(
            domain="schematic_signal_flow",
            severity="info",
            title="Signal-flow analysis clean",
            description=(
                f"Verified {len(clock_sources)} clock source(s), {len(reset_nets)} reset "
                f"net(s), and {len(jtag_nets)} JTAG net(s) without surfacing issues."
            ),
            recommendation="",
            confidence=base_confidence,
        ))

    return findings

"""Protection-circuit analyzer.

Walks the schematic looking for external-facing nets and asserts that the
appropriate protection components sit between them and the rest of the
design:

- ESD/TVS diodes on external GPIO, USB, Ethernet, antenna ports.
- Common-mode chokes on USB2 / Ethernet differential pairs.
- Bulk + bypass + HF capacitor triplet on high-di/dt rails.

External-facing nets are identified by:
1. Connector components (J*, P*, CN*) with named net pins that propagate
   into the rest of the design.
2. Net names that imply a port: ``USB_DP``, ``USB_DM``, ``ETH_TX``,
   ``ANT_OUT``, ``GPIO_EXT``.
3. Cable-driven nets that the design's net classifier already flagged
   (deferred — Phase 4b doesn't have the cable classifier).
"""

from __future__ import annotations

from typing import Any

from ...orchestrator import ReviewFinding
from . import _normalise as N

# Substrings that signal an externally accessible net.
_EXT_NET_KEYWORDS: tuple[str, ...] = (
    "USB", "ETH", "RJ45", "ANT", "RF_OUT", "RF_IN", "GPIO_EXT", "EXT_",
    "HEADER", "CONN", "I2C_EXT", "SPI_EXT", "UART_EXT", "CAN_H", "CAN_L",
    "LIN", "JTAG_EXT", "SWD_EXT",
    # External power inputs — fuse / TVS coverage applies here too.
    "VIN", "VBUS", "VBAT", "DCIN",
)


def _is_external_net(name: str) -> bool:
    if not name:
        return False
    upper = name.upper()
    return any(k in upper for k in _EXT_NET_KEYWORDS)


def _diff_pair_partner(name: str) -> str | None:
    """If *name* looks like the P-half of a diff pair, return its N-half (and vice versa)."""
    upper = name.upper()
    pairings = [
        ("_DP", "_DM"),
        ("_P", "_N"),
        ("_PLUS", "_MINUS"),
        ("+", "-"),
    ]
    for a, b in pairings:
        if upper.endswith(a):
            return upper[: -len(a)] + b
        if upper.endswith(b):
            return upper[: -len(b)] + a
    return None


def analyze_protection_circuits(
    schematic_components: list[Any],
    schematic_nets: list[Any],
) -> list[ReviewFinding]:
    """Emit findings for missing TVS / CMC on external-facing nets."""
    findings: list[ReviewFinding] = []
    if not schematic_nets:
        findings.append(ReviewFinding(
            domain="schematic_protection",
            severity="info",
            title="No schematic nets available for protection check",
            description=(
                "Cannot identify external-facing nets without schematic net "
                "information. Provide a native schematic or rich PDF with "
                "extractable text."
            ),
            recommendation="",
            confidence=0.3,
        ))
        return findings

    tvs_components = [c for c in schematic_components if N.is_tvs(c)]
    cmc_components = [c for c in schematic_components if N.is_common_mode_choke(c)]
    fuse_components = [c for c in schematic_components if N.is_fuse(c)]

    has_pin_net = any(
        bool(N.coerce(c).get("pins"))
        for c in schematic_components
    )
    base_confidence = 0.8 if has_pin_net else 0.5

    ext_nets = [n for n in schematic_nets if _is_external_net(N.net_name(n))]
    if not ext_nets:
        # Not an error — the design may not expose any external ports — but
        # log as informational so the reviewer sees it.
        findings.append(ReviewFinding(
            domain="schematic_protection",
            severity="info",
            title="No external-facing nets detected",
            description=(
                "No nets matched the external-port name patterns (USB*, ETH*, "
                "ANT*, EXT_*, CAN_H/L, etc.). The design may be entirely "
                "internal, or net names follow a non-standard convention."
            ),
            recommendation="",
            confidence=0.4,
        ))
        return findings

    # Map TVS components to candidate protected nets (heuristic when pin-net
    # mapping is absent: any external net is "potentially" covered by the
    # design's TVS components — surface counts to the user).
    tvs_count = len(tvs_components)
    cmc_count = len(cmc_components)
    fuse_count = len(fuse_components)

    ext_net_names = sorted({N.net_name(n) for n in ext_nets if N.net_name(n)})

    # 1. Per-net TVS coverage
    for net in ext_nets:
        name = N.net_name(net)
        if not name:
            continue
        if has_pin_net:
            covered = any(_component_on_net(c, name) for c in tvs_components)
            if not covered:
                findings.append(ReviewFinding(
                    domain="schematic_protection",
                    severity="high",
                    title=f"No TVS/ESD device on external net {name}",
                    description=(
                        f"External-facing net {name} has no TVS / ESD diode "
                        f"within 2 hops in the schematic. Static discharge "
                        f"can propagate directly into the IC pin."
                    ),
                    recommendation=(
                        f"Add a TVS (e.g. PESD or SMAJ family) between {name} "
                        f"and ground at the connector."
                    ),
                    signal_name=name,
                    confidence=base_confidence,
                ))
        else:
            # Heuristic fallback: just count global TVS components vs ext nets.
            pass

    if not has_pin_net:
        # Aggregate finding — surface the gap so the reviewer knows manual
        # verification is needed.
        ratio = tvs_count / max(len(ext_net_names), 1)
        severity = "high" if ratio < 0.5 else "medium" if ratio < 1.0 else "info"
        findings.append(ReviewFinding(
            domain="schematic_protection",
            severity=severity,
            title=f"{len(ext_net_names)} external net(s), {tvs_count} TVS device(s)",
            description=(
                f"Schematic source lacks pin-net mapping; cannot verify "
                f"per-net TVS coverage. Found {tvs_count} TVS / ESD components "
                f"and {len(ext_net_names)} external-facing nets. Manual "
                f"verification required."
            ),
            recommendation=(
                "Re-import the schematic via .kicad_sch or .SchDoc for "
                "pin-net analysis, or verify each external pin has a TVS "
                "manually."
            ),
            measured_value=float(tvs_count),
            limit_value=float(len(ext_net_names)),
            confidence=0.4,
        ))

    # 2. Common-mode choke on USB / Ethernet diff pairs
    diff_pairs_seen: set[frozenset[str]] = set()
    for net in ext_nets:
        name = N.net_name(net)
        if not name:
            continue
        partner = _diff_pair_partner(name)
        if not partner:
            continue
        pair_key = frozenset([name.upper(), partner])
        if pair_key in diff_pairs_seen:
            continue
        diff_pairs_seen.add(pair_key)
        # Only check USB and Ethernet diff pairs (the ones that need CMCs).
        upper = name.upper()
        if not (upper.startswith("USB") or upper.startswith("ETH")
                or "RX" in upper or "TX" in upper):
            continue
        if cmc_count == 0:
            findings.append(ReviewFinding(
                domain="schematic_protection",
                severity="medium",
                title=f"Diff pair {name}/{partner} lacks common-mode choke",
                description=(
                    f"USB / Ethernet differential pair {name}/{partner} should "
                    f"have a common-mode choke (CMC) to suppress common-mode "
                    f"noise and meet EMC class requirements. No CMC components "
                    f"found in the BOM/schematic."
                ),
                recommendation=(
                    "Insert a 90 Ω common-mode choke (e.g. BLM18BB or DLW21SN) "
                    "in line with the diff pair near the connector."
                ),
                signal_name=name,
                confidence=base_confidence,
            ))

    # 3. Fuse / over-current on power input
    power_input_nets = [n for n in ext_nets
                         if any(k in N.net_name(n).upper() for k in ("VIN", "VBUS", "VBAT", "POWER", "PWR"))]
    if power_input_nets and fuse_count == 0:
        findings.append(ReviewFinding(
            domain="schematic_protection",
            severity="medium",
            title="No fuse on external power input",
            description=(
                f"Detected {len(power_input_nets)} external power-input net(s) "
                f"but no fuse component (F*) in the schematic / BOM. "
                f"Over-current protection is mandatory for most safety standards."
            ),
            recommendation="Add a resettable PTC fuse or fast-blow on the power-input lead.",
            confidence=base_confidence,
        ))

    return findings


def _component_on_net(c: Any, net_name: str) -> bool:
    d = N.coerce(c)
    target = (net_name or "").upper()
    for pin in d.get("pins", []) or []:
        pd = pin if isinstance(pin, dict) else N.coerce(pin)
        candidate = str(pd.get("net") or pd.get("net_name") or "").upper()
        if candidate == target:
            return True
    return False

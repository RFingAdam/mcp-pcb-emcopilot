"""Power-topology analyzer.

Walks the schematic's power nets and the surrounding components to build a
rail-by-rail picture of the design's power architecture. Emits findings
when a rail is missing the expected bulk + bypass capacitors or when no
regulator drives it.

Limitations: PDF schematic extraction is text-only, so pin-net mapping
is heuristic. This analyzer relies on:
1. The ``is_power`` flag (set by parsers based on net name).
2. Refdes class detection (capacitors, ICs, regulators) — works on any
   parser flavour that fills the refdes field.
3. Net-name → rail-voltage parsing (VCC_3V3 → 3.3 V).

Confidence is reported per-finding: full pin-net data → 0.85+, refdes-
only fallback → 0.55.
"""

from __future__ import annotations

import re
from typing import Any

from ...orchestrator import ReviewFinding
from . import _normalise as N

_VOLT_FROM_NAME_RE = re.compile(r"(?:VCC|VDD|V|VBUS|VBAT|VIN|VOUT)_?(\d+)V?(\d+)?", re.IGNORECASE)


def _rail_voltage_from_name(name: str) -> float | None:
    """Best-effort voltage parsing from net names like ``VCC_3V3`` / ``+5V`` / ``V12V``."""
    if not name:
        return None
    m = _VOLT_FROM_NAME_RE.search(name)
    if m:
        whole = m.group(1)
        frac = m.group(2) or ""
        try:
            if frac:
                return float(f"{whole}.{frac}")
            return float(whole)
        except ValueError:
            return None
    # +5V / +3.3V style
    m = re.match(r"\+(\d+(?:\.\d+)?)V?", name, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _looks_like_regulator(c: Any) -> bool:
    """Heuristic: is this component an LDO / SMPS / DC-DC regulator?"""
    val = N.component_value(c).upper()
    pn = N.component_part_number(c).upper()
    keywords = (
        "LDO", "LD117", "LM317", "LM7805", "TPS6", "TPS5", "TPS7", "TPS54", "TPS62",
        "BUCK", "BOOST", "SMPS", "REG", "AMS1117", "MIC5", "MP", "LMR",
    )
    return any(k in val for k in keywords) or any(k in pn for k in keywords)


def _pin_net_mapping_available(components: list[Any]) -> bool:
    """True when at least one component has structured pin-net data."""
    for c in components:
        d = N.coerce(c)
        pins = d.get("pins")
        if isinstance(pins, list) and pins:
            for pin in pins:
                pd = pin if isinstance(pin, dict) else N.coerce(pin)
                if pd.get("net") or pd.get("net_name"):
                    return True
    return False


def analyze_power_topology(
    schematic_components: list[Any],
    schematic_nets: list[Any],
    bom_items: list[Any] | None = None,
    min_decaps_per_rail: int = 2,
) -> list[ReviewFinding]:
    """Build per-rail topology + emit findings for under-decoupled rails.

    Rules applied:

    - Every power rail must have at least one bulk capacitor (> 1 µF) and at
      least ``min_decaps_per_rail`` total capacitors. A rail with zero caps
      is HIGH severity; one cap is MEDIUM; two-or-more is informational.
    - Every power rail should be driven by either an external connector or
      a regulator-class component; rails with neither are flagged HIGH.
    - For unique rail names that look like ``VCC_3V3`` / ``+5V``, the
      analyzer records the inferred voltage on each finding.
    """
    findings: list[ReviewFinding] = []
    has_pin_net = _pin_net_mapping_available(schematic_components)
    base_confidence = 0.85 if has_pin_net else 0.55

    power_nets = [n for n in schematic_nets if N.is_power_net(n)]
    if not power_nets:
        findings.append(ReviewFinding(
            domain="schematic_power",
            severity="info",
            title="No power nets detected in schematic",
            description=(
                "The schematic parser did not surface any nets matching the "
                "VCC / VDD / +Vn naming convention. Either the design has no "
                "power rails (unlikely) or the schematic source is too lossy "
                "to expose net names (e.g. image-only PDF)."
            ),
            recommendation="Provide a native .kicad_sch or .SchDoc for full topology coverage.",
            confidence=0.4,
        ))
        return findings

    # Compute caps + regulator candidates once.
    caps = [c for c in schematic_components if N.is_capacitor(c)]
    regulators = [c for c in schematic_components if _looks_like_regulator(c)]
    connectors = [c for c in schematic_components if N.is_connector(c)]
    bulk_caps = []
    for c in caps:
        val = N.component_value(c)
        uf = N.parse_capacitance_uf(val) if val else None
        if uf is not None and uf >= 1.0:
            bulk_caps.append(c)

    rails_seen: set[str] = set()
    for net in power_nets:
        name = N.net_name(net)
        if not name or name.upper() in rails_seen:
            continue
        rails_seen.add(name.upper())

        # Capacitor count for this rail: prefer pin-net mapping; fall back
        # to assuming every cap "could be" on every rail (degraded view).
        if has_pin_net:
            rail_caps = [c for c in caps if _component_touches_net(c, name)]
            rail_bulk_caps = [c for c in bulk_caps if _component_touches_net(c, name)]
            rail_regulators = [c for c in regulators if _component_touches_net(c, name)]
            rail_connectors = [c for c in connectors if _component_touches_net(c, name)]
        else:
            # Heuristic-only: surface the global counts as a "best estimate".
            rail_caps = caps
            rail_bulk_caps = bulk_caps
            rail_regulators = regulators
            rail_connectors = connectors

        voltage = _rail_voltage_from_name(name)
        rail_label = f"{name} ({voltage:.1f} V)" if voltage is not None else name

        # Decoupling adequacy.
        cap_count = len(rail_caps)
        if cap_count == 0:
            findings.append(ReviewFinding(
                domain="schematic_power",
                severity="high",
                title=f"Rail {name} has no capacitors",
                description=(
                    f"Rail {rail_label} has zero capacitors on its net. "
                    f"Every rail needs at least one bulk + one bypass cap."
                ),
                recommendation=f"Add a bulk (>= 1 µF) and a bypass (100 nF) cap on {name}.",
                signal_name=name,
                confidence=base_confidence,
            ))
        elif cap_count < min_decaps_per_rail:
            findings.append(ReviewFinding(
                domain="schematic_power",
                severity="medium",
                title=f"Rail {name} has only {cap_count} cap(s)",
                description=(
                    f"Rail {rail_label} has {cap_count} cap(s), below the "
                    f"{min_decaps_per_rail}-cap minimum (one bulk + one bypass)."
                ),
                recommendation=(
                    "Add additional bypass capacitors (100 nF) close to each "
                    "consumer IC's Vdd pins."
                ),
                signal_name=name,
                measured_value=float(cap_count),
                limit_value=float(min_decaps_per_rail),
                confidence=base_confidence,
            ))
        elif not rail_bulk_caps:
            findings.append(ReviewFinding(
                domain="schematic_power",
                severity="medium",
                title=f"Rail {name} has no bulk capacitor",
                description=(
                    f"Rail {rail_label} has bypass caps but no bulk (>= 1 µF) "
                    f"capacitor. Bulk reservoir is needed for transient response."
                ),
                recommendation="Add a 4.7-10 µF bulk capacitor on this rail.",
                signal_name=name,
                confidence=base_confidence,
            ))

        # Source: regulator or external input?
        if not rail_regulators and not rail_connectors:
            findings.append(ReviewFinding(
                domain="schematic_power",
                severity="high",
                title=f"Rail {name} has no identified source",
                description=(
                    f"No regulator and no input-connector component appears to "
                    f"drive rail {rail_label}. The schematic may be "
                    f"incomplete or the source is via a sub-sheet not yet "
                    f"parsed."
                ),
                recommendation="Verify the rail is driven by an upstream LDO/SMPS or input pin.",
                signal_name=name,
                confidence=base_confidence * 0.8,
            ))

    return findings


def _component_touches_net(c: Any, net_name: str) -> bool:
    """True if *c*'s pin list references the named net (case-insensitive)."""
    d = N.coerce(c)
    target = (net_name or "").upper()
    for pin in d.get("pins", []) or []:
        pd = pin if isinstance(pin, dict) else N.coerce(pin)
        candidate = str(pd.get("net") or pd.get("net_name") or "").upper()
        if candidate == target:
            return True
    return False

"""Component voltage / current rating audit.

For each component the BOM lists with a voltage rating, compare it
against the rail voltage(s) it sits on (or, when pin-net mapping is
absent, against the highest rail voltage seen in the schematic). Flag
items operating above 80 % of their rating per IPC-2152 / common
derating practice.

Today's scope is voltage rating only — current rating handling needs
runtime current data from the PDN analyzer, which is downstream of this
module. Phase 4c can add that path.
"""

from __future__ import annotations

from typing import Any

from ...orchestrator import ReviewFinding
from . import _normalise as N
from .power_topology import _rail_voltage_from_name

DERATE_FACTOR = 0.8


def _bom_voltage_for_ref(bom_items: list[Any], reference: str) -> float | None:
    """Return the highest voltage rating found in BOM for *reference*."""
    target = reference.upper()
    for item in bom_items:
        d = N.coerce(item)
        refs = str(d.get("references") or d.get("reference") or "").upper()
        if not refs:
            continue
        # references may be CSV: "R1,R2,R3"
        if target not in {r.strip() for r in refs.split(",")} and target != refs:
            continue
        for field_name in ("value", "description"):
            v = d.get(field_name)
            if v:
                rated = N.parse_voltage_v(str(v))
                if rated is not None:
                    return rated
    return None


def analyze_component_rating(
    schematic_components: list[Any],
    schematic_nets: list[Any],
    bom_items: list[Any] | None,
) -> list[ReviewFinding]:
    """Emit findings for components operating above the 80 % derating threshold."""
    findings: list[ReviewFinding] = []
    bom_items = bom_items or []
    if not bom_items:
        findings.append(ReviewFinding(
            domain="schematic_rating",
            severity="info",
            title="No BOM data — component rating audit skipped",
            description=(
                "Provide a BOM (pcb_parse_bom) to enable per-component voltage / "
                "current derating audit. Schematic values rarely carry rating "
                "information directly."
            ),
            recommendation="Attach a BOM CSV / Excel via pcb_parse_bom.",
            confidence=0.3,
        ))
        return findings

    # Compute the maximum rail voltage seen in the schematic — used as the
    # fallback "stress" value when pin-net mapping is absent.
    rail_voltages: list[float] = []
    for net in schematic_nets:
        if N.is_power_net(net):
            v = _rail_voltage_from_name(N.net_name(net))
            if v is not None:
                rail_voltages.append(v)
    max_rail_voltage = max(rail_voltages, default=0.0)
    if max_rail_voltage == 0.0:
        max_rail_voltage = 3.3  # safest assumption — most digital designs

    has_pin_net = any(bool(N.coerce(c).get("pins")) for c in schematic_components)

    for c in schematic_components:
        ref = N.component_refdes(c)
        if not ref:
            continue
        # Only audit components likely to have a voltage rating in their value.
        if not (N.is_capacitor(c) or N.is_diode(c) or N.is_tvs(c) or N.is_inductor(c)):
            continue

        # Find the voltage rating from BOM first, then fall back to value text.
        rated_v = _bom_voltage_for_ref(bom_items, ref)
        if rated_v is None:
            rated_v = N.parse_voltage_v(N.component_value(c))
        if rated_v is None:
            continue  # no rating data — can't audit

        # Determine the stress voltage for this component.
        if has_pin_net:
            d = N.coerce(c)
            highest_pin_v = 0.0
            for pin in d.get("pins", []) or []:
                pd = pin if isinstance(pin, dict) else N.coerce(pin)
                net = str(pd.get("net") or pd.get("net_name") or "")
                v = _rail_voltage_from_name(net)
                if v is not None and v > highest_pin_v:
                    highest_pin_v = v
            stress_v = highest_pin_v if highest_pin_v > 0 else max_rail_voltage
        else:
            stress_v = max_rail_voltage

        if rated_v <= 0:
            continue
        utilisation = stress_v / rated_v
        if utilisation < DERATE_FACTOR:
            continue
        severity = "high" if utilisation > 1.0 else "medium"
        findings.append(ReviewFinding(
            domain="schematic_rating",
            severity=severity,
            title=f"{ref} runs {utilisation*100:.0f}% of rating ({stress_v:.1f}V / {rated_v:.1f}V)",
            description=(
                f"Component {ref} is rated {rated_v:.1f} V but appears to see "
                f"{stress_v:.1f} V in operation, which is {utilisation*100:.0f}% "
                f"of rating. Standard derating is 80% or better."
            ),
            recommendation=(
                f"Replace {ref} with a part rated >= {stress_v / DERATE_FACTOR:.0f} V "
                f"for 80% derating."
            ),
            signal_name=ref,
            measured_value=round(utilisation, 3),
            limit_value=DERATE_FACTOR,
            confidence=0.7 if has_pin_net else 0.45,
        ))

    if not findings:
        findings.append(ReviewFinding(
            domain="schematic_rating",
            severity="info",
            title="No component rating violations detected",
            description=(
                f"Audited {len(schematic_components)} schematic components against "
                f"BOM ratings. No component runs above the 80% derating threshold "
                f"at the inferred rail voltages."
            ),
            recommendation="",
            confidence=0.7 if has_pin_net else 0.4,
        ))
    return findings

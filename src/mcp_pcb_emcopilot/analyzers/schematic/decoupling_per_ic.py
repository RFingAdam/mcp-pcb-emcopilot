"""Per-IC decoupling analyzer.

For every IC (refdes U*) in the schematic, count how many capacitors sit
on a Vdd-class net the IC also touches. The rule of thumb is one bypass
capacitor per Vdd pin plus at least one bulk cap on the rail.

The analyzer degrades cleanly when pin-net information is missing — it
falls back to counting all caps vs all ICs and reports the ratio. That
output is INFO-level so it never blocks review generation.
"""

from __future__ import annotations

from typing import Any

from ...orchestrator import ReviewFinding
from . import _normalise as N


def _ic_vdd_pin_count(c: Any) -> int:
    """Count pins on *c* whose net name resembles a power rail."""
    d = N.coerce(c)
    count = 0
    for pin in d.get("pins", []) or []:
        pd = pin if isinstance(pin, dict) else N.coerce(pin)
        net = str(pd.get("net") or pd.get("net_name") or "").upper()
        if net.startswith(("VCC", "VDD", "VAA", "AVDD", "DVDD", "VBAT", "V_"))\
                or net in ("VBUS", "VIN"):
            count += 1
    return count


def _ic_power_nets(c: Any) -> set[str]:
    d = N.coerce(c)
    out: set[str] = set()
    for pin in d.get("pins", []) or []:
        pd = pin if isinstance(pin, dict) else N.coerce(pin)
        net = str(pd.get("net") or pd.get("net_name") or "").upper()
        if N.is_power_net({"name": net}):
            out.add(net)
    return out


def _caps_on_net(caps: list[Any], net_upper: str) -> int:
    count = 0
    for c in caps:
        d = N.coerce(c)
        for pin in d.get("pins", []) or []:
            pd = pin if isinstance(pin, dict) else N.coerce(pin)
            if str(pd.get("net") or pd.get("net_name") or "").upper() == net_upper:
                count += 1
                break
    return count


def analyze_decoupling_per_ic(
    schematic_components: list[Any],
    schematic_nets: list[Any],
    min_caps_per_vdd_pin: float = 1.0,
) -> list[ReviewFinding]:
    """Emit findings for ICs whose Vdd pins are under-decoupled."""
    findings: list[ReviewFinding] = []
    ics = [c for c in schematic_components if N.is_ic(c)]
    caps = [c for c in schematic_components if N.is_capacitor(c)]
    if not ics:
        findings.append(ReviewFinding(
            domain="schematic_decoupling",
            severity="info",
            title="No ICs detected in schematic",
            description=(
                "The schematic surface did not surface any components with the U* "
                "refdes prefix. Either the design is component-light (passives "
                "only) or the parser missed the IC class."
            ),
            recommendation="",
            confidence=0.4,
        ))
        return findings

    has_pin_net = any(bool(N.coerce(c).get("pins")) for c in ics)

    if not has_pin_net:
        # Aggregate ratio fallback.
        ratio = len(caps) / max(len(ics), 1)
        if ratio < 2.0:
            findings.append(ReviewFinding(
                domain="schematic_decoupling",
                severity="medium",
                title=f"Low overall decoupling ratio: {len(caps)} caps / {len(ics)} ICs",
                description=(
                    f"Schematic source lacks pin-net mapping; cannot verify "
                    f"per-IC decoupling. Aggregate ratio is {ratio:.2f} caps/IC, "
                    f"below the typical 2-4 caps/IC guideline."
                ),
                recommendation=(
                    "Re-import via .kicad_sch / .SchDoc for per-IC analysis, "
                    "or verify each IC has at least one bypass cap per Vdd pin."
                ),
                measured_value=float(round(ratio, 2)),
                limit_value=2.0,
                confidence=0.4,
            ))
        else:
            findings.append(ReviewFinding(
                domain="schematic_decoupling",
                severity="info",
                title=f"Aggregate decoupling: {len(caps)} caps / {len(ics)} ICs (~{ratio:.1f} caps/IC)",
                description=(
                    "Heuristic-only check (no pin-net mapping). Ratio looks "
                    "reasonable but per-IC verification is recommended."
                ),
                recommendation="",
                measured_value=float(round(ratio, 2)),
                limit_value=2.0,
                confidence=0.4,
            ))
        return findings

    # Pin-net mapping available — do the per-IC analysis.
    for ic in ics:
        refdes = N.component_refdes(ic)
        vdd_pin_count = _ic_vdd_pin_count(ic)
        if vdd_pin_count == 0:
            # No Vdd pins detected — could be a passive-like part or pinout
            # uses non-standard net names. Skip silently.
            continue
        power_nets = _ic_power_nets(ic)
        total_caps = 0
        for rail in power_nets:
            total_caps += _caps_on_net(caps, rail)
        required = max(int(vdd_pin_count * min_caps_per_vdd_pin), 1)
        if total_caps < required:
            findings.append(ReviewFinding(
                domain="schematic_decoupling",
                severity="medium",
                title=f"{refdes} under-decoupled: {total_caps} caps for {vdd_pin_count} Vdd pin(s)",
                description=(
                    f"IC {refdes} has {vdd_pin_count} Vdd-class pin(s) on rail(s) "
                    f"{sorted(power_nets)} but only {total_caps} capacitor(s) on "
                    f"those rails in the schematic."
                ),
                recommendation=(
                    f"Add {required - total_caps} additional bypass cap(s) "
                    f"(100 nF ceramic, X7R) close to {refdes}'s Vdd pins."
                ),
                measured_value=float(total_caps),
                limit_value=float(required),
                signal_name=refdes,
                confidence=0.85,
            ))

    return findings

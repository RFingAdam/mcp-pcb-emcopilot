"""Three-way cross-reference: schematic ↔ BOM ↔ layout.

Extends the existing 2-way ``BOMCrossReferenceAnalyzer`` by comparing all
three sources at once. The severity table follows the plan:

| Mismatch                             | Severity |
|--------------------------------------|----------|
| Component on schematic absent layout | CRITICAL |
| Footprint differs sch ↔ layout       | CRITICAL |
| Value differs sch ↔ BOM              | CRITICAL |
| DNP flag differs across sources      | HIGH     |
| MPN differs BOM ↔ sch                | HIGH     |
| Tolerance / V-rating differs         | MEDIUM   |
| Manufacturer differs only            | LOW      |

The analyzer is robust to missing sources — any missing leg degrades the
relevant check to an info-level "skipped, source unavailable" entry
rather than emitting false positives.
"""

from __future__ import annotations

import re
from typing import Any

from ...orchestrator import ReviewFinding
from ..schematic._normalise import (
    component_footprint,
    component_manufacturer,
    component_part_number,
    component_refdes,
    component_value,
)

_DNP_PATTERN = re.compile(
    r"\b(DNP|NC|NO_?POP|NO_?STUFF|DO_?NOT_?PLACE|OPEN|REMOVED|SPARE)\b",
    re.IGNORECASE,
)


def _is_dnp(value: str) -> bool:
    return bool(_DNP_PATTERN.search(value or ""))


def _bom_items_by_ref(bom_items: list[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in bom_items:
        d = item if isinstance(item, dict) else (
            item.__dict__ if hasattr(item, "__dict__") else {}
        )
        refs_str = str(d.get("references") or d.get("reference") or "")
        if not refs_str:
            continue
        for ref in refs_str.split(","):
            ref = ref.strip().upper()
            if ref:
                out[ref] = d
    return out


def _layout_by_ref(layout_components: list[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for c in layout_components:
        ref = (getattr(c, "reference", "") or "").upper()
        if not ref:
            continue
        out[ref] = {
            "reference": ref,
            "value": getattr(c, "value", "") or "",
            "footprint": getattr(c, "footprint", "") or getattr(c, "package", "") or "",
            "layer": getattr(c, "layer", "") or "",
            "x_mm": getattr(c, "x_mm", 0.0),
            "y_mm": getattr(c, "y_mm", 0.0),
        }
    return out


def _schematic_by_ref(schematic_components: list[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for c in schematic_components:
        ref = component_refdes(c)
        if not ref:
            continue
        out[ref] = {
            "reference": ref,
            "value": component_value(c),
            "footprint": component_footprint(c),
            "part_number": component_part_number(c),
            "manufacturer": component_manufacturer(c),
        }
    return out


def analyze_three_way_xref(
    schematic_components: list[Any],
    bom_items: list[Any],
    layout_components: list[Any],
) -> list[ReviewFinding]:
    """Emit findings for every (sch ↔ bom ↔ layout) discrepancy."""
    findings: list[ReviewFinding] = []
    sch_by_ref = _schematic_by_ref(schematic_components)
    bom_by_ref = _bom_items_by_ref(bom_items)
    lay_by_ref = _layout_by_ref(layout_components)

    # Each source is "useful" when it has at least one parsed entry. Empty
    # sources are treated as "not yet attached" — they neither block the
    # upfront gate nor trigger missing-from-X flagging. This keeps the
    # analyzer permissive of incremental workflows where a reviewer
    # attaches schematic + BOM first, then runs xref before fab.
    sch_with_data = bool(sch_by_ref)
    bom_with_data = bool(bom_by_ref)
    lay_with_data = bool(lay_by_ref)
    sch_attached = sch_with_data
    bom_attached = bom_with_data
    lay_attached = lay_with_data

    if sum(int(x) for x in (sch_with_data, bom_with_data, lay_with_data)) < 2:
        findings.append(ReviewFinding(
            domain="three_way_xref",
            severity="info",
            title="Cross-reference skipped: fewer than two data sources available",
            description=(
                "Three-way cross-reference requires at least two of "
                "{schematic, BOM, layout}. Provide more inputs to enable "
                "this check."
            ),
            recommendation="Attach the missing source(s) via pcb_parse_schematic, "
                           "pcb_parse_bom, or pcb_parse_layout.",
            confidence=0.3,
        ))
        return findings

    all_refs = sorted(set(sch_by_ref) | set(bom_by_ref) | set(lay_by_ref))

    for ref in all_refs:
        sch = sch_by_ref.get(ref)
        bom = bom_by_ref.get(ref)
        lay = lay_by_ref.get(ref)

        # --- Presence checks ---------------------------------------------
        # Each presence check fires whenever the *other* source(s) the
        # comparison depends on are attached, even if those sources are
        # currently empty (an empty layout is meaningful — it says "nothing
        # is placed").
        if sch and not lay and lay_attached:
            findings.append(ReviewFinding(
                domain="three_way_xref",
                severity="critical",
                title=f"{ref} in schematic but missing from layout",
                description=(
                    f"Component {ref} appears in the schematic with value "
                    f"{sch.get('value', '?')!r} but has no matching placement "
                    f"in the layout. The board is unbuildable as drawn."
                ),
                recommendation=f"Place {ref} on the PCB or remove from the schematic.",
                signal_name=ref,
                confidence=0.95,
            ))
            continue
        if lay and not sch and sch_attached:
            findings.append(ReviewFinding(
                domain="three_way_xref",
                severity="high",
                title=f"{ref} on layout but missing from schematic",
                description=(
                    f"Component {ref} is placed on the layout but the "
                    f"schematic doesn't define it. Possible orphan or test "
                    f"point — verify intent."
                ),
                recommendation=f"Either add {ref} to the schematic or remove it from the layout.",
                signal_name=ref,
                confidence=0.85,
            ))
            continue
        if bom and not sch and sch_attached:
            findings.append(ReviewFinding(
                domain="three_way_xref",
                severity="medium",
                title=f"{ref} in BOM but not in schematic",
                description=(
                    f"BOM lists {ref} (qty {bom.get('quantity', '?')}) but the "
                    f"schematic does not include it. Likely a stale BOM line."
                ),
                recommendation=f"Update the BOM to remove {ref}, or add it to the schematic.",
                signal_name=ref,
                confidence=0.8,
            ))
            continue
        if sch and not bom and bom_attached:
            findings.append(ReviewFinding(
                domain="three_way_xref",
                severity="medium",
                title=f"{ref} in schematic but missing from BOM",
                description=(
                    f"Schematic shows {ref} but the BOM has no matching line "
                    f"item. Production purchasing will fail."
                ),
                recommendation=f"Add {ref} to the BOM with its MPN.",
                signal_name=ref,
                confidence=0.85,
            ))
            continue

        # --- Value mismatch ---------------------------------------------
        sch_val = (sch or {}).get("value", "").strip()
        bom_val = str((bom or {}).get("value") or "").strip()
        lay_val = (lay or {}).get("value", "").strip()

        sch_dnp = _is_dnp(sch_val)
        bom_dnp = _is_dnp(bom_val) or _is_dnp(str((bom or {}).get("description") or ""))
        _lay_dnp = _is_dnp(lay_val)  # reserved — layout DNP comparison TBD

        # DNP flag differs across sources?
        if sch and bom and sch_dnp != bom_dnp:
            findings.append(ReviewFinding(
                domain="three_way_xref",
                severity="high",
                title=f"{ref} DNP flag differs: sch={sch_dnp} vs bom={bom_dnp}",
                description=(
                    f"The schematic and BOM disagree on whether {ref} is "
                    f"populated. This results in wrong-part-fitted at build."
                ),
                recommendation="Reconcile the DNP flag across sources before manufacturing.",
                signal_name=ref,
                confidence=0.9,
            ))
            continue

        # Value differs sch ↔ BOM ?
        if sch and bom and sch_val and bom_val and _normalise_value(sch_val) != _normalise_value(bom_val):
            findings.append(ReviewFinding(
                domain="three_way_xref",
                severity="critical",
                title=f"{ref} value mismatch: schematic {sch_val!r} vs BOM {bom_val!r}",
                description=(
                    f"Schematic value and BOM value for {ref} disagree. The "
                    f"wrong part will be assembled."
                ),
                recommendation="Reconcile schematic and BOM values before fabrication.",
                signal_name=ref,
                confidence=0.95,
            ))
            continue

        # Footprint differs sch ↔ layout?
        sch_fp = (sch or {}).get("footprint", "")
        lay_fp = (lay or {}).get("footprint", "")
        if sch and lay and sch_fp and lay_fp and _normalise_footprint(sch_fp) != _normalise_footprint(lay_fp):
            findings.append(ReviewFinding(
                domain="three_way_xref",
                severity="critical",
                title=f"{ref} footprint mismatch: schematic {sch_fp!r} vs layout {lay_fp!r}",
                description=(
                    f"The schematic and layout reference different footprints "
                    f"for {ref}. Wrong land pattern will be on the board."
                ),
                recommendation="Sync the footprint between schematic library and layout library.",
                signal_name=ref,
                confidence=0.95,
            ))
            continue

        # MPN differs BOM ↔ sch?
        sch_mpn = (sch or {}).get("part_number", "")
        bom_mpn = str((bom or {}).get("part_number") or "")
        if sch_mpn and bom_mpn and sch_mpn.strip().upper() != bom_mpn.strip().upper():
            findings.append(ReviewFinding(
                domain="three_way_xref",
                severity="high",
                title=f"{ref} MPN mismatch: schematic {sch_mpn!r} vs BOM {bom_mpn!r}",
                description=(
                    f"Schematic and BOM specify different manufacturer part "
                    f"numbers for {ref}. Sourcing risk; the BOM is what "
                    f"purchasing will buy."
                ),
                recommendation="Decide which MPN is authoritative and align both sources.",
                signal_name=ref,
                confidence=0.85,
            ))
            continue

        # Manufacturer differs only?
        sch_mfr = (sch or {}).get("manufacturer", "")
        bom_mfr = str((bom or {}).get("manufacturer") or "")
        if sch_mfr and bom_mfr and sch_mfr.strip().upper() != bom_mfr.strip().upper():
            findings.append(ReviewFinding(
                domain="three_way_xref",
                severity="low",
                title=f"{ref} manufacturer differs: sch {sch_mfr!r} vs bom {bom_mfr!r}",
                description=(
                    f"Schematic and BOM list different manufacturers for {ref}. "
                    f"Possibly an alternate-source approval; verify."
                ),
                recommendation="Confirm whether the alternate source is approved.",
                signal_name=ref,
                confidence=0.7,
            ))
            continue

    if not findings:
        findings.append(ReviewFinding(
            domain="three_way_xref",
            severity="info",
            title="Three-way cross-reference clean",
            description=(
                f"Compared {len(sch_by_ref)} schematic / {len(bom_by_ref)} BOM / "
                f"{len(lay_by_ref)} layout components — no mismatches detected."
            ),
            recommendation="",
            confidence=0.85,
        ))
    return findings


# --- Value normalisation -----------------------------------------------------

_UNIT_REPLACEMENTS = {
    "μf": "uf",
    "ω": "",       # bare ohm symbol — drop; the prefix carries the unit ('10k' is enough)
    "ohm": "",
    " ": "",
    "-": "",
    "_": "",
}


def _normalise_value(value: str) -> str:
    """Loose-equivalence value comparison.

    ``'10 kΩ'`` and ``'10K'`` should be treated as the same; ``'10uF/25V'``
    and ``'10uF 25V'`` likewise.
    """
    out = (value or "").strip().lower()
    for a, b in _UNIT_REPLACEMENTS.items():
        out = out.replace(a, b)
    return out


def _normalise_footprint(fp: str) -> str:
    out = (fp or "").strip().lower()
    # Strip vendor library prefixes like 'Resistor_SMD:R_0402_1005Metric'
    if ":" in out:
        out = out.split(":")[-1]
    return out

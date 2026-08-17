"""Parsers for the sidecar files Altium exports alongside Gerber + drill data.

A Gerber set describes copper shapes and nothing else. Four sidecars carry the
information that turns those shapes into an analysable board, and none of them
were read before:

``.LDP`` — the layer-pair map. **The single most important file in an HDI
export.** It states which copper layers each drill file spans. Without it every
via looks like a through-hole, and on a build-up board that makes ground
stitching and return-path analysis look dramatically healthier than reality: a
microvia between two adjacent layers gets credited with connecting the entire
stack.

``.EXTREP`` — maps each file extension to its layer name, which is how ``.G4``
becomes "L5 GND" rather than "some inner layer".

``.DRR`` — the fabrication drill report. Its per-span hole counts are derived
independently of the coordinate files, making it a genuine cross-check on drill
parsing rather than a restatement of it.

``.RUL`` — the exported DRC rules. Real design intent, in place of the library
default constraints that would otherwise be reported as if extracted.

These live in one module because they are one artifact family and are only
meaningful jointly: ``.LDP``'s ``DrillFile`` has to be reconciled against
``.DRR``'s ASCII filename and against ``.EXTREP``'s extension table. Splitting
them across four near-empty modules would scatter that reconciliation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MIL_TO_MM = 0.0254

# Rule kinds whose Minimum is a physical length, used by the units heuristic.
_LENGTH_RULE_KINDS = {"clearance", "width", "holesize", "soldermaskexpansion",
                      "pastemaskexpansion", "annularring", "holetoholeclearance"}


# ===========================================================================
# .LDP — layer pair map
# ===========================================================================

@dataclass
class LayerPairSpan:
    """One drill file and the copper layers it spans."""

    set_name: str
    drill_file: str
    layer_tokens: list[str]
    start_ordinal: int = 0
    end_ordinal: int = 0
    span_kind: str = "unknown"  # through | blind | buried | micro | unknown
    name_ordinals: Optional[tuple[int, int]] = None

    @property
    def drill_basename(self) -> str:
        return Path(self.drill_file).name.lower()


@dataclass
class LayerPairMap:
    source_file: str
    spans: list[LayerPairSpan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def find_by_drill_file(self, filename: str) -> Optional[LayerPairSpan]:
        """Match a drill file to its span, case-insensitively by basename.

        Altium lowercases the filename inside the .LDP while the file on disk
        keeps its original case, so an exact match fails on case-sensitive
        filesystems.
        """
        target = Path(filename).name.lower()
        for span in self.spans:
            if span.drill_basename == target:
                return span
        return None


_RE_SET_NAME_ORDINALS = re.compile(r"L(\d+)\b")


def parse_layer_pair_map(path: str | Path) -> LayerPairMap:
    """Parse an Altium ``.LDP`` layer-pair export.

    Line form (after a leading header line naming the source PcbDoc)::

        LayersSetName=<name>|DrillFile=<file>|DrillLayers=<tok,tok,...>

    ``DrillLayers`` lists *every* layer the span crosses as bare lowercase
    extension tokens (``gtl``, ``g1``, ``gbl``) — ten entries for a full
    through-hole span, two for an adjacent pair.
    """
    p = Path(path)
    result = LayerPairMap(source_file=p.name)
    text = p.read_text(encoding="utf-8", errors="replace")

    for raw in text.splitlines():
        line = raw.strip()
        if not line or "LayersSetName" not in line:
            continue  # header/path line
        fields: dict[str, str] = {}
        for part in line.split("|"):
            if "=" not in part:
                continue
            key, _, value = part.partition("=")
            fields[key.strip().lower()] = value.strip()

        set_name = fields.get("layerssetname", "")
        drill_file = fields.get("drillfile", "")
        tokens = [
            t.strip().lower()
            for t in (fields.get("drilllayers", "") or "").split(",")
            if t.strip()
        ]
        if not tokens:
            result.warnings.append(
                f"layer-pair entry {set_name!r} lists no DrillLayers; its span "
                "cannot be determined."
            )
        if not drill_file:
            result.warnings.append(
                f"layer-pair entry {set_name!r} names no DrillFile."
            )

        ordinals = _RE_SET_NAME_ORDINALS.findall(set_name)
        name_ordinals = None
        if len(ordinals) >= 2:
            name_ordinals = (int(ordinals[0]), int(ordinals[1]))

        lowered = set_name.lower()
        if "thru" in lowered or "through" in lowered:
            kind = "through"
        elif "blind" in lowered:
            kind = "blind"
        elif "buried" in lowered:
            kind = "buried"
        elif "micro" in lowered:
            kind = "micro"
        else:
            kind = "unknown"

        result.spans.append(LayerPairSpan(
            set_name=set_name,
            drill_file=drill_file,
            layer_tokens=tokens,
            span_kind=kind,
            name_ordinals=name_ordinals,
        ))

    if not result.spans:
        result.warnings.append(
            "no layer-pair entries found — every via would otherwise default to "
            "a through-hole span."
        )
    return result


# ===========================================================================
# .EXTREP — extension to layer name
# ===========================================================================

@dataclass
class ExtensionReport:
    source_file: str
    by_extension: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def ordinal_for(self, ext: str) -> Optional[int]:
        """Leading ``L<n>`` of the layer name for *ext*, if present.

        ``.G4`` -> "L5 GND" -> 5. Returns None for non-copper layers such as
        "Profile" or "Solder Mask Top", which carry no ordinal.
        """
        name = self.by_extension.get(ext.lower())
        if not name:
            return None
        m = re.match(r"\s*L(\d+)\b", name)
        return int(m.group(1)) if m else None

    def name_for(self, ext: str) -> Optional[str]:
        return self.by_extension.get(ext.lower())


# Tolerant of column drift: an extension token, then 2+ spaces, then the name.
# Descriptions contain single spaces ("L1 Top", "Solder Mask Top"), so the
# separator must require two.
_RE_EXTREP_ROW = re.compile(r"^\s*(\.[A-Za-z0-9]{1,5})\s{2,}(\S.*?)\s*$")


def parse_extension_report(path: str | Path) -> ExtensionReport:
    """Parse an Altium ``.EXTREP`` Gerber-extension report."""
    p = Path(path)
    result = ExtensionReport(source_file=p.name)
    text = p.read_text(encoding="utf-8", errors="replace")

    for raw in text.splitlines():
        if set(raw.strip()) <= {"-"} or not raw.strip():
            continue
        m = _RE_EXTREP_ROW.match(raw)
        if not m:
            continue
        ext, name = m.group(1).lower(), m.group(2).strip()
        if ext in result.by_extension and result.by_extension[ext] != name:
            result.warnings.append(
                f"extension {ext} listed twice with different names "
                f"({result.by_extension[ext]!r} then {name!r})."
            )
        result.by_extension[ext] = name

    if not result.by_extension:
        result.warnings.append("no extension/layer-name rows were recognised.")
    return result


# ===========================================================================
# .DRR — drill report
# ===========================================================================

@dataclass
class DrillToolReport:
    tool_code: int
    diameter_mm: float
    diameter_mil: float
    hole_type: str = "round"
    hole_count: int = 0
    plated: bool = True
    tool_travel_mm: Optional[float] = None


@dataclass
class DrillReportBlock:
    layer_pair: Optional[str] = None
    ascii_file: Optional[str] = None
    eia_file: Optional[str] = None
    tools: list[DrillToolReport] = field(default_factory=list)
    total_holes: int = 0

    @property
    def summed_tool_holes(self) -> int:
        return sum(t.hole_count for t in self.tools)


@dataclass
class DrillReport:
    source_file: str
    blocks: list[DrillReportBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # The file-level grand total that follows the last per-span block. Kept
    # separate from the block totals precisely so the two can be compared: it is
    # an independent statement of the same quantity.
    reported_grand_total: Optional[int] = None

    @property
    def total_holes(self) -> int:
        return sum(b.total_holes for b in self.blocks)

    @property
    def grand_total_agrees(self) -> Optional[bool]:
        """Does the file's own grand total match the sum of its blocks?

        None when the file states no grand total.
        """
        if self.reported_grand_total is None:
            return None
        return self.reported_grand_total == self.total_holes

    def find_block(self, ascii_filename: str) -> Optional[DrillReportBlock]:
        target = Path(ascii_filename).name.lower()
        for block in self.blocks:
            if block.ascii_file and Path(block.ascii_file).name.lower() == target:
                return block
        return None


_RE_DRR_LAYER_PAIR = re.compile(r"^Layer Pair\s*:\s*(.+?)\s*$", re.I)
_RE_DRR_ASCII = re.compile(r"^ASCII.*?File\s*:\s*(\S+)", re.I)
_RE_DRR_EIA = re.compile(r"^EIA\s*File\s*:\s*(\S+)", re.I)
_RE_DRR_TOTALS = re.compile(r"^Totals?\s+(\d+)", re.I)
_RE_DRR_TOOL = re.compile(
    r"^T(\d+)\s+([0-9.]+)\s*mil\s*\(\s*([0-9.]+)\s*mm\s*\)(?P<rest>.*)$", re.I
)
_RE_DRR_TOOL_MM_ONLY = re.compile(
    r"^T(\d+)\s+([0-9.]+)\s*mm(?P<rest>.*)$", re.I
)
_RE_DRR_TRAVEL = re.compile(r"([0-9.]+)\s*inch\s*\(\s*([0-9.]+)\s*mm\s*\)", re.I)
_RE_DRR_HOLE_TYPE = re.compile(r"\b(Round|Slot|Square|Oval)\b", re.I)
_RE_DRR_PLATING = re.compile(r"\b(PTH|NPTH)\b", re.I)


def parse_drill_report(path: str | Path) -> DrillReport:
    """Parse an Altium ``.DRR`` NC-drill report.

    Per-span blocks look like::

        Layer Pair : L5 GND to L6 SIG2
        ASCII Plated RoundHoles File : job-Plated.TX5
        EIA File   : job.DR5

        Tool    Hole Size    ...  Hole Type  Hole Count  Plated  Tool Travel
        T2      8mil (0.203mm)     Round     677         PTH     32.96inch (837.06mm)
        Totals                                677

    Counts here are produced independently of the coordinate files, which is
    what makes them a real cross-check on drill parsing.
    """
    p = Path(path)
    result = DrillReport(source_file=p.name)
    text = p.read_text(encoding="utf-8", errors="replace")

    current: Optional[DrillReportBlock] = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        if current.total_holes == 0 and current.tools:
            current.total_holes = current.summed_tool_holes
        elif current.tools and current.total_holes != current.summed_tool_holes:
            result.warnings.append(
                f"block {current.layer_pair or current.ascii_file!r}: Totals row "
                f"says {current.total_holes} but the tool rows sum to "
                f"{current.summed_tool_holes}."
            )
        result.blocks.append(current)
        current = None

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or set(line.strip()) <= {"-", "="}:
            continue

        m = _RE_DRR_LAYER_PAIR.match(line.strip())
        if m:
            flush()
            current = DrillReportBlock(layer_pair=m.group(1))
            continue

        m = _RE_DRR_ASCII.match(line.strip())
        if m:
            if current is None:
                current = DrillReportBlock()
            current.ascii_file = m.group(1)
            continue

        m = _RE_DRR_EIA.match(line.strip())
        if m:
            if current is None:
                current = DrillReportBlock()
            current.eia_file = m.group(1)
            continue

        m = _RE_DRR_TOTALS.match(line.strip())
        if m:
            value = int(m.group(1))
            # A file-level grand total follows the last per-span block, using the
            # same "Totals" keyword. Without this guard it overwrote the final
            # block's count with the whole-file figure — which is exactly the
            # kind of error the cross-check exists to catch, so capture it as
            # the independent grand total instead of letting it clobber.
            if current is None or current.total_holes:
                result.reported_grand_total = value
            else:
                current.total_holes = value
            continue

        tool = _RE_DRR_TOOL.match(line.strip())
        mm_only = None if tool else _RE_DRR_TOOL_MM_ONLY.match(line.strip())
        if tool or mm_only:
            if current is None:
                current = DrillReportBlock()
            if tool:
                code = int(tool.group(1))
                dia_mil = float(tool.group(2))
                dia_mm = float(tool.group(3))
                rest = tool.group("rest")
            else:
                code = int(mm_only.group(1))          # type: ignore[union-attr]
                dia_mm = float(mm_only.group(2))      # type: ignore[union-attr]
                dia_mil = dia_mm / MIL_TO_MM
                rest = mm_only.group("rest")          # type: ignore[union-attr]

            # The hole count is the first integer after the hole-type word; the
            # diameter is also a number, so position alone is not enough.
            hole_count = 0
            type_match = _RE_DRR_HOLE_TYPE.search(rest)
            hole_type = type_match.group(1).lower() if type_match else "round"
            tail = rest[type_match.end():] if type_match else rest
            count_match = re.search(r"\b(\d+)\b", tail)
            if count_match:
                hole_count = int(count_match.group(1))

            plating = _RE_DRR_PLATING.search(rest)
            travel = _RE_DRR_TRAVEL.search(rest)

            current.tools.append(DrillToolReport(
                tool_code=code,
                diameter_mm=dia_mm,
                diameter_mil=dia_mil,
                hole_type=hole_type,
                hole_count=hole_count,
                plated=(plating.group(1).upper() != "NPTH") if plating else True,
                tool_travel_mm=float(travel.group(2)) if travel else None,
            ))
            continue

    flush()

    if not result.blocks:
        result.warnings.append(
            "no drill-report blocks were recognised; per-span hole counts are "
            "unavailable for cross-checking."
        )
    if result.grand_total_agrees is False:
        result.warnings.append(
            f"the report's own grand total ({result.reported_grand_total}) does "
            f"not match the sum of its per-span blocks ({result.total_holes})."
        )
    return result


# ===========================================================================
# .RUL — exported DRC rules
# ===========================================================================

@dataclass
class AltiumRule:
    kind: str
    name: str
    scope: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    preferred: Optional[float] = None
    allowed: Optional[bool] = None
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def is_length_rule(self) -> bool:
        return self.kind.lower().replace("_", "") in _LENGTH_RULE_KINDS


@dataclass
class RuleSet:
    source_file: str
    rules: list[AltiumRule] = field(default_factory=list)
    units: str = "mil"
    units_source: str = "heuristic"
    warnings: list[str] = field(default_factory=list)

    def by_kind(self, kind: str) -> list[AltiumRule]:
        k = kind.lower()
        return [r for r in self.rules if r.kind.lower() == k]


def _to_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_rule_file(path: str | Path) -> RuleSet:
    """Parse an Altium ``.RUL`` DRC-rules export.

    Line form::

        RuleKind=Clearance|RuleName=Clearance_GND|Scope=Board|Minimum=5.00

    The file declares no units. They are inferred from magnitude: a minimum
    clearance or trace width above ~0.5 is mils, because 0.5 mm would be an
    extraordinarily coarse constraint while 0.5 mil would be unmanufacturable.
    The decision and its basis are recorded on the result rather than applied
    silently.
    """
    p = Path(path)
    result = RuleSet(source_file=p.name)
    text = p.read_text(encoding="utf-8", errors="replace")

    for raw in text.splitlines():
        line = raw.strip()
        if not line or "RuleKind" not in line:
            continue
        fields: dict[str, str] = {}
        for part in line.split("|"):
            if "=" not in part:
                continue
            key, _, value = part.partition("=")
            fields[key.strip()] = value.strip()

        allowed_raw = fields.get("Allowed")
        allowed: Optional[bool] = None
        if allowed_raw is not None:
            allowed = allowed_raw.strip() not in ("0", "false", "False")

        result.rules.append(AltiumRule(
            kind=fields.get("RuleKind", ""),
            name=fields.get("RuleName", ""),
            scope=fields.get("Scope", ""),
            minimum=_to_float(fields.get("Minimum", "")),
            maximum=_to_float(fields.get("Maximum", "")),
            preferred=_to_float(fields.get("Preferred", "")),
            allowed=allowed,
            raw=dict(fields),
        ))

    # Units heuristic over length-bearing rules only.
    length_minima = [
        r.minimum for r in result.rules
        if r.is_length_rule and r.minimum is not None and r.minimum > 0
    ]
    if length_minima:
        smallest = min(length_minima)
        if smallest >= 0.5:
            result.units = "mil"
            result.warnings.append(
                f"units not declared in the file; inferred MILS because the "
                f"smallest length constraint is {smallest:g} "
                f"({smallest:g} mm would be implausibly coarse)."
            )
        else:
            result.units = "mm"
            result.warnings.append(
                f"units not declared in the file; inferred MILLIMETRES because "
                f"the smallest length constraint is {smallest:g} "
                f"({smallest:g} mil would be unmanufacturable)."
            )
    else:
        result.warnings.append(
            "no length-bearing rules found; unit inference was not possible."
        )

    if not result.rules:
        result.warnings.append("no rules were recognised in this file.")
    return result


def rules_to_design_rules(rs: RuleSet) -> tuple[list[dict], dict[str, float]]:
    """Convert a :class:`RuleSet` into the model's design-rule shapes.

    Returns ``(rule_dicts, scalars)``. ``rule_dicts`` matches the existing
    ODB++ schema — ``{name, type, value_mm, scope}`` — plus ``value_mil`` and a
    ``source`` marker, so consumers of ``PCBDesignData.design_rules`` need no
    changes. ``scalars`` carries the minima that back
    ``min_trace_width_mm`` / ``min_clearance_mm``.
    """
    factor = MIL_TO_MM if rs.units == "mil" else 1.0
    out: list[dict] = []
    widths: list[float] = []
    clearances: list[float] = []

    for rule in rs.rules:
        value_mm: Optional[float] = None
        if rule.minimum is not None and rule.is_length_rule:
            value_mm = rule.minimum * factor
        entry = {
            "name": rule.name,
            "type": rule.kind,
            "value_mm": value_mm,
            "scope": rule.scope,
            "source": "altium_rul",
        }
        if rule.minimum is not None and rule.is_length_rule:
            entry["value_mil"] = rule.minimum if rs.units == "mil" else rule.minimum / MIL_TO_MM
        if rule.allowed is not None:
            entry["allowed"] = rule.allowed
        out.append(entry)

        kind = rule.kind.lower()
        if value_mm is not None:
            if kind == "width":
                widths.append(value_mm)
            elif kind == "clearance":
                clearances.append(value_mm)

    scalars: dict[str, float] = {}
    if widths:
        scalars["min_trace_width_mm"] = min(widths)
    if clearances:
        scalars["min_clearance_mm"] = min(clearances)
    return out, scalars

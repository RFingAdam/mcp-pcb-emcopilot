"""ORCAD PSTXNET + Pads ASCII netlist parser.

Replaces the regex stub in :mod:`schematic_dispatch._parse_simple_netlist`
with real section-aware readers that recover per-net pin lists. These two
formats are the long-tail of EDA schematic export — Altium and KiCad have
native parsers, but ORCAD/Allegro/Pads workflows export to one of these
plain-text formats.

The parser auto-detects PSTXNET vs Pads from the first non-blank line:

- PSTXNET starts with ``PSTXNET`` and uses ``*PART*`` / ``*NET*`` sections.
- Pads ASCII starts with ``!PADS-POWERPCB-V*`` and uses ``*PART*`` /
  ``*NET*`` / ``*VIA*`` / ``*MISC*`` sections.

Both share enough structure that one section walker handles both.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from .schematic_parser import ParsedComponent, ParsedNet, ParsedSchematicData

logger = logging.getLogger(__name__)


# Section delimiters used by both PSTXNET and Pads.
_SECTION_RE = re.compile(r"^\s*\*(PART|NET|VIA|MISC|REMARK|CONNECTION|PIN)\*\s*$", re.IGNORECASE)
# `NET_NAME='FOO'` or `NET_NAME=FOO` followed on the next line(s) by pin list.
_NET_NAME_RE = re.compile(r"^\s*NET_NAME\s*[:=]\s*['\"]?([\w\+\-\.]+)['\"]?\s*$", re.IGNORECASE)
# `REFDES.PIN` references (e.g. `R1.1`, `U1.50`).
_PIN_REF_RE = re.compile(r"\b([A-Z]+\d+[A-Z]?)\.([\w\-]+)\b")
# A part line is typically "REFDES VALUE PART_NUMBER MANUFACTURER" — whitespace separated.
_PART_LINE_RE = re.compile(r"^\s*([A-Z]+\d+[A-Z]?)\s+(.+)$")


def detect_netlist_dialect(file_path: str) -> str:
    """Return ``"pstxnet"`` / ``"pads"`` / ``"unknown"`` by sniffing the head."""
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            head = f.read(2048)
    except OSError:
        return "unknown"
    upper = head.upper()
    if "PSTXNET" in upper:
        return "pstxnet"
    if "!PADS" in upper or "PADS-POWERPCB" in upper:
        return "pads"
    # Fall back to looking for shared section markers.
    if re.search(r"\*PART\*", upper) and re.search(r"\*NET\*", upper):
        return "pstxnet"  # safest default
    return "unknown"


def parse_netlist(file_path: str) -> ParsedSchematicData:
    """Parse a netlist file, auto-detecting the dialect."""
    dialect = detect_netlist_dialect(file_path)
    if dialect == "pads":
        return parse_pads_netlist(file_path)
    return parse_orcad_netlist(file_path)


def parse_orcad_netlist(file_path: str) -> ParsedSchematicData:
    """Parse an ORCAD PSTXNET netlist.

    Pin-net mapping is recovered from ``*NET*`` sections; component
    metadata (value / MPN / manufacturer) from ``*PART*``. Component
    refdes alone is enough for downstream schematic analyzers to run.
    """
    components: dict[str, ParsedComponent] = {}
    nets: dict[str, ParsedNet] = {}
    warnings: list[str] = []

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"netlist file not found: {file_path}")

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        raise ValueError(f"could not read netlist {file_path}: {e}") from e

    section: Optional[str] = None
    current_net: Optional[str] = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        m = _SECTION_RE.match(line)
        if m:
            section = m.group(1).upper()
            current_net = None
            continue

        if section == "PART":
            _absorb_part_line(line, components)
            continue

        if section == "NET":
            net_match = _NET_NAME_RE.match(line)
            if net_match:
                current_net = net_match.group(1)
                if current_net not in nets:
                    nets[current_net] = ParsedNet(
                        net_name=current_net,
                        is_power=_looks_like_power(current_net),
                        is_ground=_looks_like_ground(current_net),
                    )
                continue
            # Otherwise assume this line is a pin list for the current net.
            if current_net is None:
                continue
            for refdes, pin in _PIN_REF_RE.findall(line):
                comp = components.setdefault(refdes, ParsedComponent(reference=refdes))
                # Record pin reference on the component
                if not any(p.get("pin_number") == pin for p in comp.pins):
                    comp.pins.append({"pin_number": pin, "net": current_net})
                else:
                    # Update net on existing pin
                    for p in comp.pins:
                        if p.get("pin_number") == pin:
                            p["net"] = current_net
                # And on the net
                nets[current_net].pins.append({
                    "component": refdes,
                    "pin_number": pin,
                })

    if not components and not nets:
        warnings.append(
            "PSTXNET parser found neither *PART* nor *NET* sections — "
            "file may use a non-standard dialect."
        )

    return ParsedSchematicData(
        components=list(components.values()),
        nets=list(nets.values()),
        warnings=warnings,
    )


def parse_pads_netlist(file_path: str) -> ParsedSchematicData:
    """Parse a Pads ASCII netlist.

    The Pads dialect is structurally identical to PSTXNET for the parts
    we care about (sections, pin lists), so we delegate. The distinction
    matters when handling Pads-specific records like ``*VIA*`` (drill
    table) and ``*MISC*`` (board outline) — neither contributes to the
    schematic-side data this module produces.
    """
    return parse_orcad_netlist(file_path)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _absorb_part_line(line: str, components: dict[str, ParsedComponent]) -> None:
    """Absorb a single ``*PART*`` row into the components dict.

    Layout is whitespace-separated: ``REFDES VALUE [MPN] [MANUFACTURER...]``.
    """
    m = _PART_LINE_RE.match(line)
    if not m:
        return
    refdes = m.group(1).upper()
    rest = m.group(2).strip()
    tokens = rest.split(maxsplit=2)
    value = tokens[0] if len(tokens) >= 1 else None
    mpn = tokens[1] if len(tokens) >= 2 else None
    manufacturer = tokens[2] if len(tokens) >= 3 else None
    comp = components.get(refdes)
    if comp is None:
        comp = ParsedComponent(reference=refdes)
        components[refdes] = comp
    if value and not comp.value:
        comp.value = value
    if mpn and not comp.part_number:
        comp.part_number = mpn
    if manufacturer and not comp.manufacturer:
        comp.manufacturer = manufacturer


def _looks_like_power(name: str) -> bool:
    upper = (name or "").upper()
    return upper.startswith(("VCC", "VDD", "+", "VBAT", "VBUS", "VIN", "V3", "V5"))


def _looks_like_ground(name: str) -> bool:
    upper = (name or "").upper()
    return upper.startswith(("GND", "VSS", "AGND", "DGND", "PGND"))

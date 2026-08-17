"""ASCII Excellon (NC drill) parser.

Excellon is the near-universal drill format emitted alongside Gerber copper
layers. Without it a Gerber job has no via or hole data at all, so every
via-dependent analysis — return-path stitching, ground continuity, aspect
ratios, drill tables — has nothing to work from.

Two properties of the format cause most real-world misreads, and both are
handled explicitly here.

**Zero suppression is the opposite of Gerber's.** A Gerber ``%FSLAX25Y25`` means
leading zeros are *omitted*, so coordinate tokens are right-aligned and must be
left-padded. Excellon ``INCH,LZ`` means leading zeros are *kept* — trailing ones
are suppressed instead — so tokens are left-aligned and must be right-padded.
Applying the Gerber rule to an Excellon file yields coordinates that are wrong
by orders of magnitude while still parsing cleanly, which is the worst kind of
failure. See :func:`decode_coordinate`.

**The format spec lives in a comment.** ``;FILE_FORMAT=2:5`` is a comment line,
so a parser that skips comments (as the Gerber parser deliberately does) loses
the integer/decimal split and silently falls back to a default.

Binary EIA drill files are detected and rejected rather than parsed as text: an
Altium export ships both an ASCII set and a binary twin, and decoding the binary
one as ASCII produces plausible-looking garbage.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

INCH_TO_MM = 25.4
MIL_TO_MM = 0.0254

# How much of a file to inspect when deciding text-vs-binary.
_SNIFF_BYTES = 4096


@dataclass
class ExcellonTool:
    """A drill tool: a diameter plus its usage count."""

    code: int
    diameter_mm: float
    plated: bool = True
    feed: Optional[float] = None
    speed: Optional[float] = None
    hit_count: int = 0

    @property
    def diameter_mil(self) -> float:
        return self.diameter_mm / MIL_TO_MM


@dataclass
class ExcellonHit:
    """A single drilled hole (or a routed slot when the end point is set)."""

    x_mm: float
    y_mm: float
    tool_code: int
    diameter_mm: float
    slot_end_x_mm: Optional[float] = None
    slot_end_y_mm: Optional[float] = None

    @property
    def is_slot(self) -> bool:
        return self.slot_end_x_mm is not None


@dataclass
class ExcellonData:
    """Everything recovered from one ASCII Excellon file."""

    source_file: str
    units: str = "inch"  # inch | mm
    integer_digits: int = 2
    decimal_digits: int = 4
    # keep_leading  == "LZ": leading zeros present, trailing suppressed
    # keep_trailing == "TZ": trailing zeros present, leading suppressed
    zeros_mode: str = "keep_leading"
    plated: Optional[bool] = None
    format_source: str = "default"
    tools: dict[int, ExcellonTool] = field(default_factory=dict)
    hits: list[ExcellonHit] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    min_x: float = float("inf")
    max_x: float = float("-inf")
    min_y: float = float("inf")
    max_y: float = float("-inf")
    warnings: list[str] = field(default_factory=list)

    @property
    def hit_count(self) -> int:
        return len(self.hits)

    def counts_by_diameter(self) -> dict[float, int]:
        """Hit counts keyed by drill diameter in mm, rounded to 4 dp."""
        counts: dict[float, int] = {}
        for hit in self.hits:
            key = round(hit.diameter_mm, 4)
            counts[key] = counts.get(key, 0) + 1
        return counts

    @property
    def extent_mm(self) -> tuple[float, float, float, float]:
        """(min_x, min_y, max_x, max_y); zeros when there are no hits."""
        if not self.hits:
            return (0.0, 0.0, 0.0, 0.0)
        return (self.min_x, self.min_y, self.max_x, self.max_y)


class ExcellonBinaryError(ValueError):
    """Raised when a drill file is binary EIA rather than ASCII Excellon."""


def is_binary_excellon(data: bytes) -> bool:
    """Heuristic: is this drill file binary rather than ASCII Excellon?

    Altium emits an ASCII set (``.TXT``/``.TXn``) and a binary EIA twin
    (``.DRL``/``.DRn``) for the same holes. Decoding the binary one as text
    yields plausible-looking coordinates, so the distinction has to be made
    before parsing rather than discovered afterwards.
    """
    head = data[:_SNIFF_BYTES]
    if not head:
        return True
    if b"\x00" in head:
        return True
    printable = sum(
        1 for b in head if 32 <= b < 127 or b in (9, 10, 13, 12)
    )
    if printable / len(head) < 0.95:
        return True
    # An ASCII Excellon file opens with M48 (or at least a comment) very early.
    return b"M48" not in data[:512]


def decode_coordinate(
    token: str,
    integer_digits: int,
    decimal_digits: int,
    zeros_mode: str,
    units: str,
) -> float:
    """Decode one Excellon coordinate token to millimetres.

    ``token`` is the digits after the axis letter, e.g. ``"0003173"``.

    An explicit decimal point overrides everything. Otherwise the token is
    padded to ``integer_digits + decimal_digits`` on the side the zero-
    suppression mode implies:

    - ``keep_leading`` (``LZ``): leading zeros are present and trailing ones
      suppressed, so pad on the **right**.
    - ``keep_trailing`` (``TZ``): trailing zeros are present and leading ones
      suppressed, so pad on the **left**.

    Worked examples at 2:5 inch, LZ — both taken from real exports:

    >>> round(decode_coordinate("0003173", 2, 5, "keep_leading", "inch"), 5)
    0.80594
    >>> round(decode_coordinate("01244", 2, 5, "keep_leading", "inch"), 4)
    31.5976

    The second is the case that catches a Gerber-style decoder: left-padding
    ``01244`` gives 0.01244 in (0.32 mm) instead of 1.244 in (31.6 mm), a 100x
    error that still looks like a coordinate.
    """
    negative = token.startswith("-")
    text = token.lstrip("+-").strip()
    if not text:
        return 0.0

    if "." in text:
        value = float(text)
    else:
        total = integer_digits + decimal_digits
        if len(text) < total:
            text = text.ljust(total, "0") if zeros_mode == "keep_leading" else text.rjust(total, "0")
        if len(text) > total:
            # More digits than the declared format: the surplus belongs to the
            # integer part. Trust the decimal width, which is the stable half.
            int_part = text[:-decimal_digits] or "0"
            frac_part = text[-decimal_digits:]
        else:
            int_part = text[:integer_digits] or "0"
            frac_part = text[integer_digits:] or "0"
        value = int(int_part) + int(frac_part) / (10 ** decimal_digits)

    if negative:
        value = -value
    return value * (INCH_TO_MM if units == "inch" else 1.0)


# Header/body token patterns.
_RE_FILE_FORMAT = re.compile(r";\s*FILE_FORMAT\s*=\s*(\d+)\s*:\s*(\d+)", re.I)
_RE_FORMAT_ALT = re.compile(r"^;\s*FORMAT\s*=\s*(\d+)\s*[:.]\s*(\d+)", re.I)
_RE_UNITS = re.compile(r"^(INCH|METRIC|IN|MM)\b(.*)$", re.I)
_RE_TYPE = re.compile(r";\s*TYPE\s*=\s*(\w+)", re.I)
_RE_TOOL_DEF = re.compile(r"^T(\d+)")
_RE_TOOL_DIA = re.compile(r"C\s*([0-9]*\.?[0-9]+)", re.I)
_RE_TOOL_FEED = re.compile(r"F\s*([0-9]*\.?[0-9]+)", re.I)
_RE_TOOL_SPEED = re.compile(r"S\s*([0-9]*\.?[0-9]+)", re.I)
_RE_TOOL_SEL = re.compile(r"^T(\d+)\s*$")
_RE_COORD = re.compile(r"([XY])([+-]?[0-9]*\.?[0-9]+)", re.I)


class ExcellonParser:
    """Parse ASCII Excellon drill files into :class:`ExcellonData`."""

    def parse(self, file_path: str | Path) -> ExcellonData:
        path = Path(file_path)
        content = path.read_bytes()
        if is_binary_excellon(content):
            raise ExcellonBinaryError(
                f"{path.name} is a binary EIA drill file, not ASCII Excellon. "
                "Altium exports a binary twin (.DRL/.DRn) alongside the ASCII "
                "set (.TXT/.TXn); supply the ASCII file instead."
            )
        return self.parse_from_bytes(content, path.name)

    def parse_from_bytes(self, content: bytes, filename: str = "drill.txt") -> ExcellonData:
        text = content.decode("utf-8", errors="replace")
        data = ExcellonData(source_file=filename)

        in_header = True
        current_tool: Optional[int] = None
        # Excellon omits an axis when it does not change between hits, so the
        # last value of each axis has to persist. Without this, a bare "X..."
        # line silently drops to Y=0 and puts the hole on the board edge.
        last_x: Optional[float] = None
        last_y: Optional[float] = None
        pending_slot_start: Optional[tuple[float, float]] = None

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith(";"):
                data.comments.append(line)
                self._parse_comment(line, data)
                continue

            upper = line.upper()

            if upper == "M48":
                in_header = True
                continue
            if upper in ("%", "M95"):
                in_header = False
                continue
            if upper in ("M30", "M00", "M02"):
                break
            if upper in ("G90", "G05", "G00"):
                continue
            if upper == "G91":
                data.warnings.append(
                    "G91 incremental mode is not supported; coordinates were "
                    "read as absolute and may be wrong."
                )
                continue
            if upper == "M71":
                data.units = "mm"
                continue
            if upper == "M72":
                data.units = "inch"
                continue
            if upper.startswith("FMAT"):
                continue

            units_match = _RE_UNITS.match(upper)
            if units_match and in_header:
                self._parse_units(units_match, data)
                continue

            if in_header and _RE_TOOL_DEF.match(upper) and _RE_TOOL_DIA.search(upper):
                self._parse_tool_definition(upper, data)
                continue

            sel = _RE_TOOL_SEL.match(upper)
            if sel:
                current_tool = int(sel.group(1))
                if current_tool not in data.tools and not in_header:
                    data.warnings.append(
                        f"tool T{current_tool:02d} selected but never defined; "
                        "its hits are recorded with an unknown diameter."
                    )
                continue

            if "X" in upper or "Y" in upper:
                consumed = self._parse_hit(
                    upper, data, current_tool, last_x, last_y, pending_slot_start
                )
                if consumed is not None:
                    last_x, last_y = consumed
                continue

        self._finalise(data)
        return data

    # -- header -----------------------------------------------------------

    def _parse_comment(self, line: str, data: ExcellonData) -> None:
        fmt = _RE_FILE_FORMAT.search(line) or _RE_FORMAT_ALT.search(line)
        if fmt:
            data.integer_digits = int(fmt.group(1))
            data.decimal_digits = int(fmt.group(2))
            data.format_source = "file_format_comment"
        type_match = _RE_TYPE.search(line)
        if type_match:
            data.plated = type_match.group(1).upper().startswith("PLATED")

    def _parse_units(self, match: re.Match, data: ExcellonData) -> None:
        word = match.group(1).upper()
        data.units = "mm" if word in ("METRIC", "MM") else "inch"
        rest = match.group(2) or ""
        if "LZ" in rest:
            data.zeros_mode = "keep_leading"
        elif "TZ" in rest:
            data.zeros_mode = "keep_trailing"
        if data.format_source == "default":
            # Units line without a FILE_FORMAT comment: fall back to the
            # conventional widths for the unit system rather than leaving the
            # inch default in place for a metric file.
            if data.units == "mm":
                data.integer_digits, data.decimal_digits = 3, 3
            else:
                data.integer_digits, data.decimal_digits = 2, 4
            data.format_source = "units_token"

    def _parse_tool_definition(self, line: str, data: ExcellonData) -> None:
        code = int(_RE_TOOL_DEF.match(line).group(1))  # type: ignore[union-attr]
        dia_match = _RE_TOOL_DIA.search(line)
        if not dia_match:
            return
        raw = float(dia_match.group(1))
        diameter_mm = raw * (INCH_TO_MM if data.units == "inch" else 1.0)
        feed = _RE_TOOL_FEED.search(line)
        speed = _RE_TOOL_SPEED.search(line)
        data.tools[code] = ExcellonTool(
            code=code,
            diameter_mm=diameter_mm,
            plated=True if data.plated is None else data.plated,
            feed=float(feed.group(1)) if feed else None,
            speed=float(speed.group(1)) if speed else None,
        )

    # -- body -------------------------------------------------------------

    def _parse_hit(
        self,
        line: str,
        data: ExcellonData,
        current_tool: Optional[int],
        last_x: Optional[float],
        last_y: Optional[float],
        pending_slot_start: Optional[tuple[float, float]],
    ) -> Optional[tuple[Optional[float], Optional[float]]]:
        """Parse one coordinate line. Returns the updated (x, y) sticky pair."""
        is_slot = "G85" in line
        segments = line.split("G85") if is_slot else [line]

        points: list[tuple[Optional[float], Optional[float]]] = []
        for segment in segments:
            x_val: Optional[float] = None
            y_val: Optional[float] = None
            for axis, token in _RE_COORD.findall(segment):
                value = decode_coordinate(
                    token,
                    data.integer_digits,
                    data.decimal_digits,
                    data.zeros_mode,
                    data.units,
                )
                if axis.upper() == "X":
                    x_val = value
                else:
                    y_val = value
            points.append((x_val, y_val))

        if not points:
            return None

        # Resolve sticky coordinates against the previous hit.
        resolved: list[tuple[float, float]] = []
        cur_x, cur_y = last_x, last_y
        for x_val, y_val in points:
            if x_val is not None:
                cur_x = x_val
            if y_val is not None:
                cur_y = y_val
            if cur_x is None or cur_y is None:
                # A first hit that names only one axis is unresolvable; record
                # it rather than defaulting the other axis to 0.
                data.warnings.append(
                    "coordinate line with only one axis and no previous "
                    f"position: {line!r}"
                )
                return None
            resolved.append((cur_x, cur_y))

        if current_tool is None:
            # Never silently: a dropped hit changes every downstream count.
            data.warnings.append(
                f"hit at {resolved[0]} ignored — no tool selected. Drill counts "
                "will not reconcile against the fabrication report."
            )
            return (cur_x, cur_y)

        tool = data.tools.get(current_tool)
        diameter = tool.diameter_mm if tool else 0.0
        start = resolved[0]
        end = resolved[1] if len(resolved) > 1 else None

        data.hits.append(ExcellonHit(
            x_mm=start[0],
            y_mm=start[1],
            tool_code=current_tool,
            diameter_mm=diameter,
            slot_end_x_mm=end[0] if end else None,
            slot_end_y_mm=end[1] if end else None,
        ))
        if tool:
            tool.hit_count += 1

        for px, py in resolved:
            data.min_x = min(data.min_x, px)
            data.max_x = max(data.max_x, px)
            data.min_y = min(data.min_y, py)
            data.max_y = max(data.max_y, py)

        return (cur_x, cur_y)

    def _finalise(self, data: ExcellonData) -> None:
        if not data.hits:
            data.warnings.append("no drill hits were parsed from this file.")
        if data.format_source == "default" and data.hits:
            data.warnings.append(
                "coordinate format was not declared (no FILE_FORMAT comment and "
                f"no units line); assumed {data.integer_digits}:"
                f"{data.decimal_digits} {data.units}. Verify the drill extents "
                "against the board outline."
            )
        undefined = {h.tool_code for h in data.hits if h.tool_code not in data.tools}
        if undefined:
            data.warnings.append(
                "hits reference undefined tool(s) "
                f"{sorted(undefined)}; their diameters are unknown."
            )


def parse_excellon(file_path: str | Path) -> ExcellonData:
    """Convenience wrapper around :class:`ExcellonParser`."""
    return ExcellonParser().parse(file_path)

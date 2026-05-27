"""Schematic file parsers for KiCad and other EDA formats.

Supports:
- KiCad .kicad_sch (S-expression format) - Priority #1
- Future: Altium, OrCAD, Eagle formats
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# sexpdata-tree helpers (used by KiCadSchematicParser._parse_tree)
#
# sexpdata returns nested lists where Symbol("foo") objects encode bare
# identifiers and Python strings/ints/floats stay as-is. These helpers
# normalise that into Python primitives so the parser body stays readable.
# =============================================================================


def _is_sexp(node: Any) -> bool:
    return isinstance(node, list) and len(node) > 0


def _car(node: Any) -> str:
    """Return the head symbol of an S-expr node as a string."""
    if not _is_sexp(node):
        return ""
    head = node[0]
    if hasattr(head, "value"):
        return str(head.value())
    return str(head)


def _cdr(node: Any) -> list[Any]:
    return list(node[1:]) if _is_sexp(node) else []


def _nth(node: Any, n: int) -> Any:
    if not isinstance(node, list) or n >= len(node):
        return None
    return node[n]


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value())
    return str(value)


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if hasattr(value, "value"):
        try:
            return float(value.value())
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _to_yes(value: Any) -> bool:
    """KiCad uses (in_bom yes) / (on_board no) — Symbol "yes" / "no"."""
    return _to_str(value).lower() == "yes"


def _looks_like_power(name: str) -> bool:
    upper = (name or "").upper()
    return upper.startswith(("VCC", "VDD", "+", "VBAT", "VBUS", "VIN", "V3", "V5"))


def _looks_like_ground(name: str) -> bool:
    upper = (name or "").upper()
    return upper.startswith(("GND", "VSS", "AGND", "DGND", "PGND"))


@dataclass
class ParsedComponent:
    """Component extracted from schematic."""
    reference: str
    value: Optional[str] = None
    part_number: Optional[str] = None
    manufacturer: Optional[str] = None
    footprint: Optional[str] = None
    sheet_number: int = 1
    x_coord: float = 0.0
    y_coord: float = 0.0
    properties: dict = field(default_factory=dict)
    pins: list[dict] = field(default_factory=list)


@dataclass
class ParsedNet:
    """Net extracted from schematic."""
    net_name: str
    net_code: Optional[int] = None
    pins: list[dict] = field(default_factory=list)
    is_power: bool = False
    is_ground: bool = False


@dataclass
class ParsedSchematicData:
    """Complete parsed schematic data."""
    components: list[ParsedComponent] = field(default_factory=list)
    nets: list[ParsedNet] = field(default_factory=list)
    sheet_count: int = 1
    title: Optional[str] = None
    revision: Optional[str] = None
    designer: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    properties: dict = field(default_factory=dict)


class KiCadSchematicParser:
    """Parser for KiCad .kicad_sch files (S-expression format).

    Uses :mod:`sexpdata` to walk the document as a real tree. Falls back to
    the legacy regex parser when sexpdata is unavailable so the package
    remains usable without the optional dependency.

    What it surfaces today:

    - Component refdes, value, footprint, MPN, Manufacturer, Datasheet.
    - ``in_bom`` / ``on_board`` → ``properties['dnp']`` and ``dnp_in_bom``
      / ``dnp_on_board`` for the three-way cross-reference analyzer.
    - Per-component pins (``ParsedComponent.pins``) with ``pin_number``
      and ``net`` once net resolution is run.
    - Net resolution from ``(wire)`` ↔ ``(label)`` ↔ ``(junction)``
      proximity, including hierarchical / global labels.
    - Sub-sheet references (``ParsedComponent.properties['sheet_path']``).
    """

    # Coordinate tolerance for snapping a label to a wire endpoint, in mm.
    _LABEL_SNAP_MM = 0.51

    def __init__(self) -> None:
        self.components: list[ParsedComponent] = []
        self.nets: dict[str, ParsedNet] = {}
        self.warnings: list[str] = []

    def parse(self, file_path: str) -> ParsedSchematicData:
        """Parse a KiCad schematic file."""
        logger.info("Parsing KiCad schematic: %s", file_path)

        try:
            with open(file_path, encoding='utf-8') as f:
                content = f.read()
        except OSError as e:
            raise ValueError(f"Could not read {file_path}: {e}") from e

        # Try the sexpdata-based parser first. If sexpdata isn't installed,
        # or the file is malformed in a way that confuses it, fall back to
        # the regex path so we never go fully blind on a real design.
        try:
            import sexpdata
            tree = sexpdata.loads(content)
            self._parse_tree(tree)
        except ImportError:
            self.warnings.append(
                "sexpdata not installed; falling back to regex parser. "
                "Install with: pip install sexpdata (or pip install -e '.[all]')."
            )
            self._parse_kicad_sch(content)
        except Exception as e:
            self.warnings.append(
                f"sexpdata tree-walk failed ({e!s}); falling back to regex parser."
            )
            self.components.clear()
            self.nets.clear()
            self._parse_kicad_sch(content)

        result = ParsedSchematicData(
            components=self.components,
            nets=list(self.nets.values()),
            warnings=self.warnings,
        )
        logger.info("Parsed %d components, %d nets", len(result.components), len(result.nets))
        return result

    # ------------------------------------------------------------------
    # sexpdata-based parsing
    # ------------------------------------------------------------------

    def _parse_tree(self, tree: Any) -> None:
        """Walk a parsed (kicad_sch ...) S-expr tree."""
        if not _is_sexp(tree) or _car(tree) != "kicad_sch":
            raise ValueError("not a kicad_sch document")

        # Collect raw elements then post-process net resolution.
        wires: list[dict[str, Any]] = []
        labels: list[dict[str, Any]] = []
        junctions: list[dict[str, Any]] = []

        for node in _cdr(tree):
            tag = _car(node) if _is_sexp(node) else None
            if tag == "symbol":
                comp = self._parse_symbol_node(node)
                if comp is not None:
                    self.components.append(comp)
            elif tag == "wire":
                w = self._parse_wire_node(node)
                if w:
                    wires.append(w)
            elif tag in {"label", "global_label", "hierarchical_label"}:
                label = self._parse_label_node(node)
                if label:
                    labels.append(label)
                    name = label["name"]
                    if name not in self.nets:
                        self.nets[name] = ParsedNet(
                            net_name=name,
                            is_power=_looks_like_power(name),
                            is_ground=_looks_like_ground(name),
                        )
            elif tag == "junction":
                j = self._parse_junction_node(node)
                if j:
                    junctions.append(j)

        # Resolve pin → net by associating each pin coordinate with a label
        # in proximity (via wires + junctions). Pure-geometry heuristic;
        # KiCad never exports an explicit netlist in .kicad_sch.
        self._resolve_pin_nets(wires, labels, junctions)

    def _parse_symbol_node(self, node: Any) -> Optional[ParsedComponent]:
        """Parse a single ``(symbol ...)`` block."""
        lib_id: str = ""
        reference: str = ""
        value: Optional[str] = None
        footprint: Optional[str] = None
        part_number: Optional[str] = None
        manufacturer: Optional[str] = None
        datasheet: Optional[str] = None
        x_coord: float = 0.0
        y_coord: float = 0.0
        in_bom = True
        on_board = True
        pins: list[dict[str, Any]] = []
        properties: dict[str, Any] = {}

        for child in _cdr(node):
            if not _is_sexp(child):
                continue
            tag = _car(child)
            if tag == "lib_id":
                lib_id = _to_str(_nth(child, 1))
            elif tag == "at":
                x_coord = _to_float(_nth(child, 1))
                y_coord = _to_float(_nth(child, 2))
            elif tag == "in_bom":
                in_bom = _to_yes(_nth(child, 1))
            elif tag == "on_board":
                on_board = _to_yes(_nth(child, 1))
            elif tag == "property":
                key = _to_str(_nth(child, 1))
                val = _to_str(_nth(child, 2))
                if key == "Reference":
                    reference = val
                elif key == "Value":
                    value = val
                elif key == "Footprint":
                    footprint = val
                elif key == "Datasheet":
                    datasheet = val
                elif key in {"MPN", "Mfr_No", "Manufacturer_Part_Number"}:
                    part_number = val
                elif key in {"Manufacturer", "Mfr"}:
                    manufacturer = val
                else:
                    properties[key] = val
            elif tag == "pin":
                pin_num = _to_str(_nth(child, 1)) or str(len(pins) + 1)
                pins.append({
                    "pin_number": pin_num,
                    "x_offset": 0.0,
                    "y_offset": 0.0,
                    "net": None,
                    # Component-relative position resolved during net mapping.
                    "x_abs": x_coord,
                    "y_abs": y_coord,
                })

        # Skip placeholder power symbols (KiCad uses #PWR refdes).
        if not reference or reference.startswith("#"):
            return None

        # Datasheet-as-part-number fallback for KiCad libs that don't use MPN.
        if part_number is None and datasheet and datasheet not in {"~", ""}:
            part_number = datasheet

        properties["lib_id"] = lib_id
        properties["dnp_in_bom"] = in_bom
        properties["dnp_on_board"] = on_board
        # Composite DNP flag — either toggle off means "don't populate".
        properties["dnp"] = not (in_bom and on_board)

        return ParsedComponent(
            reference=reference,
            value=value,
            part_number=part_number,
            manufacturer=manufacturer,
            footprint=footprint,
            x_coord=x_coord,
            y_coord=y_coord,
            properties=properties,
            pins=pins,
        )

    @staticmethod
    def _parse_wire_node(node: Any) -> Optional[dict[str, Any]]:
        pts: list[tuple[float, float]] = []
        for child in _cdr(node):
            if _is_sexp(child) and _car(child) == "pts":
                for xy in _cdr(child):
                    if _is_sexp(xy) and _car(xy) == "xy":
                        pts.append((_to_float(_nth(xy, 1)), _to_float(_nth(xy, 2))))
        return {"pts": pts} if pts else None

    @staticmethod
    def _parse_label_node(node: Any) -> Optional[dict[str, Any]]:
        if len(node) < 2:
            return None
        name = _to_str(_nth(node, 1))
        x, y = 0.0, 0.0
        scope = _to_str(_nth(node, 0))  # "label" | "global_label" | "hierarchical_label"
        for child in _cdr(node):
            if _is_sexp(child) and _car(child) == "at":
                x = _to_float(_nth(child, 1))
                y = _to_float(_nth(child, 2))
        if not name:
            return None
        return {"name": name, "x": x, "y": y, "scope": scope}

    @staticmethod
    def _parse_junction_node(node: Any) -> Optional[dict[str, Any]]:
        for child in _cdr(node):
            if _is_sexp(child) and _car(child) == "at":
                return {
                    "x": _to_float(_nth(child, 1)),
                    "y": _to_float(_nth(child, 2)),
                }
        return None

    def _resolve_pin_nets(
        self,
        wires: list[dict[str, Any]],
        labels: list[dict[str, Any]],
        junctions: list[dict[str, Any]],
    ) -> None:
        """Best-effort pin → net mapping via the shared resolver."""
        from ._pin_net_geometric import resolve_pins_by_geometry
        resolve_pins_by_geometry(
            self.components, wires, labels, junctions,
            nets=self.nets, snap_mm=self._LABEL_SNAP_MM,
        )

    def _parse_kicad_sch(self, content: str) -> None:
        """Parse KiCad schematic S-expression content."""
        # Extract symbols (components)
        symbol_pattern = r'\(symbol\s+\(lib_id\s+"([^"]+)"\)'
        symbols = re.finditer(symbol_pattern, content)

        for match in symbols:
            try:
                component = self._parse_symbol_section(content, match.start())
                if component:
                    self.components.append(component)
            except Exception as e:
                self.warnings.append(f"Failed to parse symbol: {str(e)}")

        # Extract nets from hierarchical labels and global labels
        self._extract_nets_from_labels(content)

        # Extract power symbols (VCC, GND, etc.)
        self._extract_power_nets(content)

    def _parse_symbol_section(self, content: str, start_pos: int) -> Optional[ParsedComponent]:
        """Parse individual symbol section."""
        # Find the complete symbol block
        depth = 0
        end_pos = start_pos
        for i in range(start_pos, len(content)):
            if content[i] == '(':
                depth += 1
            elif content[i] == ')':
                depth -= 1
                if depth == 0:
                    end_pos = i + 1
                    break

        symbol_text = content[start_pos:end_pos]

        # Extract reference designator
        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', symbol_text)
        if not ref_match:
            return None

        reference = ref_match.group(1)

        # Skip power symbols (like #PWR)
        if reference.startswith('#'):
            return None

        # Extract value
        value_match = re.search(r'\(property\s+"Value"\s+"([^"]+)"', symbol_text)
        value = value_match.group(1) if value_match else None

        # Extract footprint
        footprint_match = re.search(r'\(property\s+"Footprint"\s+"([^"]+)"', symbol_text)
        footprint = footprint_match.group(1) if footprint_match else None

        # Extract datasheet/part number
        datasheet_match = re.search(r'\(property\s+"Datasheet"\s+"([^"]+)"', symbol_text)
        part_number = datasheet_match.group(1) if datasheet_match else None

        # Extract position
        pos_match = re.search(r'\(at\s+([-\d.]+)\s+([-\d.]+)', symbol_text)
        x_coord = float(pos_match.group(1)) if pos_match else 0.0
        y_coord = float(pos_match.group(2)) if pos_match else 0.0

        # Build component
        component = ParsedComponent(
            reference=reference,
            value=value,
            part_number=part_number,
            footprint=footprint,
            x_coord=x_coord,
            y_coord=y_coord,
        )

        # Extract pins
        component.pins = self._extract_pins(symbol_text, reference)

        return component

    def _extract_pins(self, symbol_text: str, reference: str) -> list[dict]:
        """Extract pin information from symbol."""
        pins = []

        # Find all pin declarations
        pin_pattern = r'\(pin\s+\w+\s+line\s+\(at\s+([-\d.]+)\s+([-\d.]+)\s+\d+\)'
        pin_matches = re.finditer(pin_pattern, symbol_text)

        pin_num = 1
        for match in pin_matches:
            pins.append({
                "pin_number": str(pin_num),
                "x_offset": float(match.group(1)),
                "y_offset": float(match.group(2)),
            })
            pin_num += 1

        return pins

    def _extract_nets_from_labels(self, content: str) -> None:
        """Extract nets from hierarchical and global labels."""
        # Hierarchical labels
        hier_label_pattern = r'\(hierarchical_label\s+"([^"]+)"'
        for match in re.finditer(hier_label_pattern, content):
            net_name = match.group(1)
            if net_name not in self.nets:
                self.nets[net_name] = ParsedNet(net_name=net_name)

        # Global labels
        global_label_pattern = r'\(global_label\s+"([^"]+)"'
        for match in re.finditer(global_label_pattern, content):
            net_name = match.group(1)
            if net_name not in self.nets:
                self.nets[net_name] = ParsedNet(net_name=net_name)

    def _extract_power_nets(self, content: str) -> None:
        """Extract power symbols and classify as power/ground nets."""
        # Power port pattern (e.g., +3V3, VCC, GND, etc.)
        power_pattern = r'\(lib_id\s+"power:([^"]+)"\)'

        for match in re.finditer(power_pattern, content):
            power_symbol = match.group(1)

            if power_symbol not in self.nets:
                is_ground = any(gnd in power_symbol.upper() for gnd in ['GND', 'VSS', 'EARTH'])
                is_power = not is_ground

                self.nets[power_symbol] = ParsedNet(
                    net_name=power_symbol,
                    is_power=is_power,
                    is_ground=is_ground,
                )


class SchematicParserFactory:
    """Factory to create appropriate parser based on file type."""

    @staticmethod
    def create_parser(file_path: str) -> KiCadSchematicParser | object:
        """Create parser based on file extension.

        Args:
            file_path: Path to schematic file

        Returns:
            Appropriate parser instance

        Raises:
            ValueError: If file type is not supported
        """
        path = Path(file_path)
        extension = path.suffix.lower()

        if extension == '.kicad_sch':
            return KiCadSchematicParser()
        elif extension == '.schdoc':
            # Altium schematic format
            from .altium_parser import AltiumSchematicParser
            return AltiumSchematicParser()
        elif extension == '.sch':
            # Could be OrCAD or legacy format - not yet supported
            raise ValueError(f"Legacy .sch format not yet supported: {extension}")
        else:
            raise ValueError(f"Unknown schematic file format: {extension}")

    @staticmethod
    def parse(file_path: str) -> ParsedSchematicData:
        """Parse schematic file with automatic format detection.

        For ``.SchDoc`` files the concrete parser returns the Altium-shape
        ``AltiumSchematicData``; we convert it to ``ParsedSchematicData``
        here so downstream analyzers see one uniform shape regardless of
        the source format.

        Args:
            file_path: Path to schematic file

        Returns:
            ParsedSchematicData

        Raises:
            ValueError: If file format is not supported
            TypeError: If the concrete parser returns an unexpected type
        """
        parser = SchematicParserFactory.create_parser(file_path)
        result = parser.parse(file_path)  # type: ignore[attr-defined]
        if isinstance(result, ParsedSchematicData):
            return result
        from .altium_parser import AltiumSchematicData, altium_to_parsed_schematic
        if isinstance(result, AltiumSchematicData):
            return altium_to_parsed_schematic(result)
        raise TypeError(
            f"Parser for {file_path!r} returned unexpected type "
            f"{type(result).__name__}; expected ParsedSchematicData or "
            "AltiumSchematicData."
        )

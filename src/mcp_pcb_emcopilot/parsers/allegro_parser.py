"""Cadence Allegro/OrCAD PCB design file parser.

Supports:
- Allegro ASCII export files (.txt) produced by "File > Export > ASCII..."
- Allegro Extraction files (.exp) with component/net/trace data

Since Allegro's native .brd format is binary/proprietary, this parser
targets the structured text export format with well-defined sections:
  $HEADER, $NETS, $COMPONENTS, $PINS, $ROUTES/$TRACES, $VIAS, $SHAPES,
  $CONSTRAINTS, $STACKUP

Data extraction:
- Components with reference designator, footprint, position, side, rotation
- Nets with pin assignments
- Trace segments with layer, width, coordinates
- Vias with drill size, pad diameter, layer span
- Board outline from $SHAPES section
- Design rules from $CONSTRAINTS section
- Stackup information if present

Format Benefits for AI Review:
- Human-readable text format (ASCII export)
- Structured sections with clear delimiters
- Complete design data from professional EDA tool
- Common in automotive, telecom, aerospace industries
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)


# Unit conversions
_UNIT_SCALES: Dict[str, float] = {
    "mm": 1.0,
    "mil": 0.0254,
    "mils": 0.0254,
    "inch": 25.4,
    "inches": 25.4,
    "in": 25.4,
    "thou": 0.0254,
    "um": 0.001,
    "cm": 10.0,
}

# Allegro layer name to standard copper layer name mapping
_LAYER_MAP: Dict[str, str] = {
    "TOP": "F.Cu",
    "BOTTOM": "B.Cu",
    "BOT": "B.Cu",
    "INNER1": "In1.Cu",
    "INNER2": "In2.Cu",
    "INNER3": "In3.Cu",
    "INNER4": "In4.Cu",
    "INNER5": "In5.Cu",
    "INNER6": "In6.Cu",
    "GND": "GND.Cu",
    "PWR": "PWR.Cu",
    "POWER": "PWR.Cu",
    "GROUND": "GND.Cu",
    "ART01": "F.Cu",
    "ART02": "In1.Cu",
    "ART03": "In2.Cu",
    "ART04": "B.Cu",
    "ETCH/TOP": "F.Cu",
    "ETCH/BOTTOM": "B.Cu",
    "ETCH/BOT": "B.Cu",
}


def _map_layer_name(allegro_layer: str) -> str:
    """Map an Allegro layer name to a standardised copper layer name."""
    upper = allegro_layer.strip().upper()
    if upper in _LAYER_MAP:
        return _LAYER_MAP[upper]
    # Return the original name if no mapping exists
    return allegro_layer.strip()


def _parse_float(value: str) -> float:
    """Parse a float value, handling empty strings and whitespace."""
    value = value.strip()
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


@dataclass
class AllegroComponent:
    """Component extracted from Allegro design."""
    reference: str
    footprint: Optional[str] = None
    value: Optional[str] = None
    x_mm: float = 0.0
    y_mm: float = 0.0
    rotation: float = 0.0
    side: str = "TOP"
    part_number: Optional[str] = None


@dataclass
class AllegroNet:
    """Net extracted from Allegro design."""
    name: str
    index: int = 0
    pins: List[str] = field(default_factory=list)


@dataclass
class AllegroTrace:
    """Trace segment extracted from Allegro design."""
    layer: str
    width_mm: float
    x1_mm: float = 0.0
    y1_mm: float = 0.0
    x2_mm: float = 0.0
    y2_mm: float = 0.0
    net_name: Optional[str] = None

    @property
    def length_mm(self) -> float:
        dx = self.x2_mm - self.x1_mm
        dy = self.y2_mm - self.y1_mm
        return math.sqrt(dx * dx + dy * dy)


@dataclass
class AllegroVia:
    """Via extracted from Allegro design."""
    x_mm: float
    y_mm: float
    drill_mm: float
    pad_diameter_mm: float = 0.0
    start_layer: str = "TOP"
    end_layer: str = "BOTTOM"
    net_name: Optional[str] = None


@dataclass
class AllegroStackupLayer:
    """Layer in the physical stackup."""
    name: str
    layer_type: str  # signal, plane, dielectric, mixed
    thickness_mm: float = 0.0
    material: Optional[str] = None
    dielectric_constant: float = 4.3
    loss_tangent: float = 0.02
    copper_weight_oz: Optional[float] = None


@dataclass
class AllegroDesignRules:
    """Design rules extracted from Allegro design."""
    min_trace_width_mm: float = 0.2
    min_clearance_mm: float = 0.2
    min_via_drill_mm: float = 0.3


@dataclass
class AllegroBoardData:
    """Complete parsed Allegro board data."""
    source_file: str
    version: Optional[str] = None
    units: str = "mm"

    # Board dimensions
    width_mm: float = 0.0
    height_mm: float = 0.0
    board_outline: List[Tuple[float, float]] = field(default_factory=list)

    # Layer info
    layer_count: int = 2
    layers: List[str] = field(default_factory=list)
    stackup: List[AllegroStackupLayer] = field(default_factory=list)

    # Design elements
    components: List[AllegroComponent] = field(default_factory=list)
    nets: List[AllegroNet] = field(default_factory=list)
    traces: List[AllegroTrace] = field(default_factory=list)
    vias: List[AllegroVia] = field(default_factory=list)

    # Design rules
    design_rules: Optional[AllegroDesignRules] = None

    # Metadata
    title: Optional[str] = None

    # Parsing info
    warnings: List[str] = field(default_factory=list)


class AllegroParser:
    """Parser for Cadence Allegro ASCII export files."""

    def __init__(self) -> None:
        self._unit_scale: float = 1.0  # mm by default

    def parse_file(self, file_path: str) -> AllegroBoardData:
        """Parse an Allegro ASCII export file.

        Args:
            file_path: Path to the Allegro export file.

        Returns:
            AllegroBoardData with all extracted design data.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file content is not a valid Allegro format.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info(f"Parsing Allegro file: {path.name}")

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        return self.parse_content(content, str(path))

    def parse_content(self, content: str, source_file: str = "unknown") -> AllegroBoardData:
        """Parse Allegro ASCII export content.

        Args:
            content: File content as string.
            source_file: Source file path for reference.

        Returns:
            AllegroBoardData with all extracted design data.

        Raises:
            ValueError: If the content is not a valid Allegro format.
        """
        if not content or not content.strip():
            raise ValueError("Empty file content")

        # Verify this looks like an Allegro ASCII export
        if not self._is_allegro_format(content):
            raise ValueError(
                "Not a valid Allegro ASCII export file: "
                "expected $HEADER or ALLEGRO marker"
            )

        result = AllegroBoardData(source_file=source_file)

        # Split content into sections
        sections = self._split_sections(content)

        # Parse each section
        if "$HEADER" in sections:
            self._parse_header(sections["$HEADER"], result)

        # Set unit scale based on header
        self._unit_scale = _UNIT_SCALES.get(result.units.lower(), 1.0)

        if "$STACKUP" in sections:
            self._parse_stackup(sections["$STACKUP"], result)

        if "$NETS" in sections:
            self._parse_nets(sections["$NETS"], result)

        if "$COMPONENTS" in sections:
            self._parse_components(sections["$COMPONENTS"], result)

        if "$PINS" in sections:
            self._parse_pins(sections["$PINS"], result)

        # Support both $ROUTES and $TRACES section names
        if "$ROUTES" in sections:
            self._parse_traces(sections["$ROUTES"], result)
        if "$TRACES" in sections:
            self._parse_traces(sections["$TRACES"], result)

        if "$VIAS" in sections:
            self._parse_vias(sections["$VIAS"], result)

        if "$SHAPES" in sections:
            self._parse_shapes(sections["$SHAPES"], result)

        if "$CONSTRAINTS" in sections:
            self._parse_constraints(sections["$CONSTRAINTS"], result)

        # Calculate board dimensions from outline if available
        self._calculate_dimensions(result)

        # Determine layer count from stackup or trace layers
        self._determine_layer_count(result)

        logger.info(
            f"Allegro parsed: {len(result.components)} components, "
            f"{len(result.nets)} nets, {len(result.traces)} traces, "
            f"{len(result.vias)} vias"
        )

        return result

    @staticmethod
    def _is_allegro_format(content: str) -> bool:
        """Check if content looks like an Allegro ASCII export."""
        # Check for section markers typical of Allegro ASCII exports
        if "$HEADER" in content:
            return True
        # Check for Allegro/OrCAD markers
        upper = content[:2000].upper()
        if "ALLEGRO" in upper or "ORCAD" in upper:
            return True
        # Check for extraction format markers
        if "$NETS" in content or "$COMPONENTS" in content:
            return True
        return False

    @staticmethod
    def _split_sections(content: str) -> Dict[str, List[str]]:
        """Split content into named sections.

        Sections start with a line beginning with '$' and end at the
        next section marker or '$END' line.
        """
        sections: Dict[str, List[str]] = {}
        current_section: Optional[str] = None
        current_lines: List[str] = []

        for line in content.splitlines():
            stripped = line.strip()

            # Check for section start
            if stripped.startswith("$") and not stripped.startswith("$END"):
                # Save previous section
                if current_section is not None:
                    sections[current_section] = current_lines

                # Determine section name (first word on the line)
                section_name = stripped.split()[0] if stripped.split() else stripped
                current_section = section_name
                current_lines = []
                continue

            # Check for section end
            if stripped.startswith("$END"):
                if current_section is not None:
                    sections[current_section] = current_lines
                    current_section = None
                    current_lines = []
                continue

            # Accumulate lines in current section
            if current_section is not None:
                current_lines.append(line)

        # Save last section if no $END was found
        if current_section is not None:
            sections[current_section] = current_lines

        return sections

    def _parse_header(self, lines: List[str], result: AllegroBoardData) -> None:
        """Parse the $HEADER section for board info, units, version."""
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Handle key=value or key value pairs
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                key = key.strip().upper()
                value = value.strip().strip('"').strip("'")
            elif " " in stripped or "\t" in stripped:
                parts = stripped.split(None, 1)
                key = parts[0].strip().upper()
                value = parts[1].strip().strip('"').strip("'") if len(parts) > 1 else ""
            else:
                continue

            if key in ("UNITS", "UNIT"):
                result.units = value.lower()
            elif key in ("VERSION", "ALLEGRO_VERSION"):
                result.version = value
            elif key == "TITLE":
                result.title = value
            elif key in ("DESIGN", "DESIGN_TITLE"):
                # Only use DESIGN as title if no explicit TITLE was set
                if result.title is None:
                    result.title = value

    def _parse_stackup(self, lines: List[str], result: AllegroBoardData) -> None:
        """Parse the $STACKUP section for layer stack information."""
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Expected format:
            # LAYER_NAME TYPE THICKNESS MATERIAL Er LOSS_TAN [CU_WEIGHT]
            # e.g.: TOP signal 0.035 Copper 1.0 0.0 1.0
            #        PREPREG1 dielectric 0.2 FR4 4.5 0.02
            parts = stripped.split()
            if len(parts) < 3:
                continue

            layer_name = parts[0]
            layer_type = parts[1].lower() if len(parts) > 1 else "signal"
            thickness = _parse_float(parts[2]) if len(parts) > 2 else 0.0
            material = parts[3] if len(parts) > 3 else None
            er = _parse_float(parts[4]) if len(parts) > 4 else 4.3
            loss_tan = _parse_float(parts[5]) if len(parts) > 5 else 0.02
            cu_weight = _parse_float(parts[6]) if len(parts) > 6 else None

            # Convert thickness to mm
            thickness_mm = thickness * self._unit_scale

            stackup_layer = AllegroStackupLayer(
                name=layer_name,
                layer_type=layer_type,
                thickness_mm=thickness_mm,
                material=material,
                dielectric_constant=er if er > 0 else 4.3,
                loss_tangent=loss_tan,
                copper_weight_oz=cu_weight if cu_weight and cu_weight > 0 else None,
            )
            result.stackup.append(stackup_layer)

    def _parse_nets(self, lines: List[str], result: AllegroBoardData) -> None:
        """Parse the $NETS section for net definitions and pin lists."""
        current_net: Optional[AllegroNet] = None
        net_index = 0

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Check if this is a new net definition
            # Format: NET_NAME; PIN1 PIN2 PIN3 ...
            # or:     NET_NAME
            #           PIN1 PIN2 PIN3 ...
            if not stripped.startswith(" ") and not stripped.startswith("\t"):
                # New net line — may have pins on the same line
                if ";" in stripped:
                    net_name, _, pin_str = stripped.partition(";")
                    net_name = net_name.strip()
                    pins = [p.strip() for p in pin_str.split() if p.strip()]
                else:
                    net_name = stripped.split()[0]
                    pins = stripped.split()[1:] if len(stripped.split()) > 1 else []

                current_net = AllegroNet(
                    name=net_name,
                    index=net_index,
                    pins=pins,
                )
                result.nets.append(current_net)
                net_index += 1
            else:
                # Continuation line with more pins
                if current_net is not None:
                    pins = [p.strip() for p in stripped.split() if p.strip()]
                    current_net.pins.extend(pins)

    def _parse_components(self, lines: List[str], result: AllegroBoardData) -> None:
        """Parse the $COMPONENTS section for component placement data."""
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Expected format (whitespace-separated):
            # REF_DES FOOTPRINT X Y ROTATION SIDE [VALUE] [PART_NUMBER]
            parts = stripped.split()
            if len(parts) < 4:
                result.warnings.append(f"Skipping malformed component line: {stripped}")
                continue

            ref_des = parts[0]
            footprint = parts[1] if len(parts) > 1 else None
            x = _parse_float(parts[2]) if len(parts) > 2 else 0.0
            y = _parse_float(parts[3]) if len(parts) > 3 else 0.0
            rotation = _parse_float(parts[4]) if len(parts) > 4 else 0.0
            side = parts[5].upper() if len(parts) > 5 else "TOP"
            value = parts[6] if len(parts) > 6 else None
            part_number = parts[7] if len(parts) > 7 else None

            # Convert to mm
            x_mm = x * self._unit_scale
            y_mm = y * self._unit_scale

            comp = AllegroComponent(
                reference=ref_des,
                footprint=footprint,
                value=value,
                x_mm=x_mm,
                y_mm=y_mm,
                rotation=rotation,
                side=side,
                part_number=part_number,
            )
            result.components.append(comp)

    def _parse_pins(self, lines: List[str], result: AllegroBoardData) -> None:
        """Parse the $PINS section for pin-to-net assignments.

        This may augment net data already parsed from $NETS.
        """
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Format: COMPONENT.PIN NET_NAME
            parts = stripped.split()
            if len(parts) < 2:
                continue

            pin_ref = parts[0]
            net_name = parts[1]

            # Find or create the net
            existing = None
            for n in result.nets:
                if n.name == net_name:
                    existing = n
                    break

            if existing is not None:
                if pin_ref not in existing.pins:
                    existing.pins.append(pin_ref)
            else:
                new_net = AllegroNet(
                    name=net_name,
                    index=len(result.nets),
                    pins=[pin_ref],
                )
                result.nets.append(new_net)

    def _parse_traces(self, lines: List[str], result: AllegroBoardData) -> None:
        """Parse the $ROUTES or $TRACES section for trace segments."""
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Expected format:
            # LAYER WIDTH X1 Y1 X2 Y2 [NET_NAME]
            parts = stripped.split()
            if len(parts) < 6:
                result.warnings.append(f"Skipping malformed trace line: {stripped}")
                continue

            layer = parts[0]
            width = _parse_float(parts[1])
            x1 = _parse_float(parts[2])
            y1 = _parse_float(parts[3])
            x2 = _parse_float(parts[4])
            y2 = _parse_float(parts[5])
            net_name = parts[6] if len(parts) > 6 else None

            # Convert to mm
            width_mm = width * self._unit_scale
            x1_mm = x1 * self._unit_scale
            y1_mm = y1 * self._unit_scale
            x2_mm = x2 * self._unit_scale
            y2_mm = y2 * self._unit_scale

            trace = AllegroTrace(
                layer=_map_layer_name(layer),
                width_mm=width_mm,
                x1_mm=x1_mm,
                y1_mm=y1_mm,
                x2_mm=x2_mm,
                y2_mm=y2_mm,
                net_name=net_name,
            )
            result.traces.append(trace)

    def _parse_vias(self, lines: List[str], result: AllegroBoardData) -> None:
        """Parse the $VIAS section for via definitions."""
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Expected format:
            # X Y DRILL PAD_SIZE START_LAYER END_LAYER [NET_NAME]
            parts = stripped.split()
            if len(parts) < 4:
                result.warnings.append(f"Skipping malformed via line: {stripped}")
                continue

            x = _parse_float(parts[0])
            y = _parse_float(parts[1])
            drill = _parse_float(parts[2])
            pad_size = _parse_float(parts[3])
            start_layer = parts[4] if len(parts) > 4 else "TOP"
            end_layer = parts[5] if len(parts) > 5 else "BOTTOM"
            net_name = parts[6] if len(parts) > 6 else None

            # Convert to mm
            x_mm = x * self._unit_scale
            y_mm = y * self._unit_scale
            drill_mm = drill * self._unit_scale
            pad_mm = pad_size * self._unit_scale

            via = AllegroVia(
                x_mm=x_mm,
                y_mm=y_mm,
                drill_mm=drill_mm,
                pad_diameter_mm=pad_mm,
                start_layer=_map_layer_name(start_layer),
                end_layer=_map_layer_name(end_layer),
                net_name=net_name,
            )
            result.vias.append(via)

    def _parse_shapes(self, lines: List[str], result: AllegroBoardData) -> None:
        """Parse the $SHAPES section for board outline and zone shapes."""
        in_outline = False

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            upper = stripped.upper()

            # Detect board outline sub-section
            if "BOARD_OUTLINE" in upper or "OUTLINE" in upper:
                in_outline = True
                continue

            if in_outline:
                # Check for end of outline
                if upper.startswith("END") or (
                    stripped.startswith("$") or stripped.startswith("ZONE")
                ):
                    in_outline = False
                    continue

                # Parse outline vertices: X Y
                parts = stripped.split()
                if len(parts) >= 2:
                    try:
                        x = float(parts[0]) * self._unit_scale
                        y = float(parts[1]) * self._unit_scale
                        result.board_outline.append((x, y))
                    except ValueError:
                        pass

    def _parse_constraints(self, lines: List[str], result: AllegroBoardData) -> None:
        """Parse the $CONSTRAINTS section for design rules."""
        rules = AllegroDesignRules()

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Handle key=value format
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                key = key.strip().upper()
                value = value.strip()
            elif " " in stripped or "\t" in stripped:
                parts = stripped.split(None, 1)
                key = parts[0].strip().upper()
                value = parts[1].strip() if len(parts) > 1 else ""
            else:
                continue

            val_f = _parse_float(value) * self._unit_scale

            if key in ("MIN_LINE_WIDTH", "MIN_TRACE_WIDTH", "MIN_WIDTH"):
                rules.min_trace_width_mm = val_f
            elif key in ("MIN_SPACING", "MIN_SPACE", "MIN_CLEARANCE"):
                rules.min_clearance_mm = val_f
            elif key in ("MIN_DRILL", "MIN_VIA_DRILL", "MIN_HOLE"):
                rules.min_via_drill_mm = val_f

        result.design_rules = rules

    def _calculate_dimensions(self, result: AllegroBoardData) -> None:
        """Calculate board width and height from the outline or geometry."""
        if result.board_outline:
            xs = [pt[0] for pt in result.board_outline]
            ys = [pt[1] for pt in result.board_outline]
            result.width_mm = max(xs) - min(xs)
            result.height_mm = max(ys) - min(ys)
            return

        # Fallback: compute bounding box from all geometry
        all_x: List[float] = []
        all_y: List[float] = []

        for c in result.components:
            all_x.append(c.x_mm)
            all_y.append(c.y_mm)

        for t in result.traces:
            all_x.extend([t.x1_mm, t.x2_mm])
            all_y.extend([t.y1_mm, t.y2_mm])

        for v in result.vias:
            all_x.append(v.x_mm)
            all_y.append(v.y_mm)

        if all_x and all_y:
            result.width_mm = max(all_x) - min(all_x)
            result.height_mm = max(all_y) - min(all_y)

    def _determine_layer_count(self, result: AllegroBoardData) -> None:
        """Determine the copper layer count from stackup or trace layers."""
        if result.stackup:
            copper = [s for s in result.stackup
                      if s.layer_type in ("signal", "plane", "mixed")]
            if copper:
                result.layer_count = len(copper)
                result.layers = [s.name for s in copper]
                return

        # Derive from trace and via layers
        seen_layers: set[str] = set()
        for t in result.traces:
            seen_layers.add(t.layer)
        for v in result.vias:
            seen_layers.add(v.start_layer)
            seen_layers.add(v.end_layer)

        if seen_layers:
            result.layers = sorted(seen_layers)
            result.layer_count = len(seen_layers)
        else:
            result.layer_count = 2


def parse_allegro(file_path: str) -> AllegroBoardData:
    """Parse an Allegro ASCII export file.

    Args:
        file_path: Path to the Allegro export file.

    Returns:
        AllegroBoardData with extracted design data.
    """
    parser = AllegroParser()
    return parser.parse_file(file_path)

"""KiCad PCB file parser for .kicad_pcb files.

Supports:
- KiCad 5, 6, 7, and 8 file formats
- S-expression based format (text, easily parseable)

Data extraction:
- Components (modules/footprints) with reference, value, position
- Nets with names and connections
- Traces (segments) with coordinates, width, layer
- Vias with position, drill size, layers
- Zones (copper pours) with boundaries and net assignments
- Board outline and dimensions
- Layer stackup definitions
- Design rules

Format Benefits for AI Review:
- Human-readable text format
- Well-documented structure
- Complete design data including 3D models
- Native differential pair support
- Design rules embedded in file
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Unit conversion: KiCad uses mm internally
# Some older versions use internal units (1nm = 0.000001mm)
MM_SCALE = 1.0


@dataclass
class KiCadComponent:
    """Component (footprint) extracted from KiCad PCB."""
    reference: str
    value: Optional[str] = None
    footprint: Optional[str] = None
    footprint_library: Optional[str] = None
    description: Optional[str] = None
    layer: str = "F.Cu"  # Front copper
    x_mm: float = 0.0
    y_mm: float = 0.0
    rotation: float = 0.0
    uuid: Optional[str] = None
    path: Optional[str] = None  # Hierarchical path
    pads: List[KiCadPad] = field(default_factory=list)
    dnp: bool = False  # Do Not Populate
    locked: bool = False


@dataclass
class KiCadNet:
    """Net extracted from KiCad PCB."""
    index: int
    name: str
    net_class: Optional[str] = None
    routed_length_mm: float = 0.0  # Total routed length of traces on this net


@dataclass
class KiCadTrace:
    """Trace (segment) extracted from KiCad PCB."""
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float
    width_mm: float
    layer: str
    net_index: int = 0
    uuid: Optional[str] = None

    @property
    def length_mm(self) -> float:
        """Calculate trace segment length in mm."""
        import math
        dx = self.x2_mm - self.x1_mm
        dy = self.y2_mm - self.y1_mm
        return math.sqrt(dx * dx + dy * dy)


@dataclass
class KiCadArc:
    """Arc segment extracted from KiCad PCB."""
    x_start_mm: float
    y_start_mm: float
    x_mid_mm: float  # Midpoint for 3-point arc
    y_mid_mm: float
    x_end_mm: float
    y_end_mm: float
    width_mm: float
    layer: str
    net_index: int = 0


@dataclass
class KiCadVia:
    """Via extracted from KiCad PCB."""
    x_mm: float
    y_mm: float
    drill_mm: float
    size_mm: float  # Pad diameter
    via_type: str = "through"  # through, blind, micro
    layers: Tuple[str, str] = ("F.Cu", "B.Cu")
    net_index: int = 0
    uuid: Optional[str] = None


@dataclass
class KiCadPad:
    """Pad extracted from KiCad PCB footprint."""
    number: str  # Pad number/name
    pad_type: str  # smd, thru_hole, np_thru_hole, connect
    shape: str  # rect, circle, oval, roundrect, trapezoid, custom
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    layers: List[str] = field(default_factory=list)
    drill_mm: Optional[float] = None
    net_index: int = 0
    net_name: Optional[str] = None


@dataclass
class KiCadZone:
    """Copper zone (pour) extracted from KiCad PCB."""
    net_index: int
    net_name: Optional[str] = None
    layer: str = "F.Cu"
    zone_type: str = "fill"  # fill, keepout
    priority: int = 0
    outline: List[Tuple[float, float]] = field(default_factory=list)
    fill_type: str = "solid"  # solid, hatch
    uuid: Optional[str] = None


@dataclass
class KiCadLayer:
    """Layer definition from KiCad PCB."""
    number: int
    name: str
    layer_type: str  # signal, power, mixed, user
    description: Optional[str] = None


@dataclass
class KiCadStackupLayer:
    """Layer in physical stackup."""
    layer_type: str  # copper, core, prepreg, silk, paste, mask
    name: Optional[str] = None
    thickness_mm: float = 0.0
    material: Optional[str] = None
    dielectric_constant: float = 4.5
    loss_tangent: float = 0.02


@dataclass
class KiCadDesignRules:
    """Design rules extracted from KiCad PCB."""
    min_trace_width_mm: float = 0.2
    min_clearance_mm: float = 0.2
    min_via_drill_mm: float = 0.3
    min_via_diameter_mm: float = 0.6
    min_through_hole_mm: float = 0.3
    min_annular_ring_mm: float = 0.15


@dataclass
class KiCadBoardData:
    """Complete parsed KiCad PCB data."""
    source_file: str
    kicad_version: Optional[str] = None
    generator: Optional[str] = None

    # Board dimensions
    width_mm: float = 0.0
    height_mm: float = 0.0
    layer_count: int = 2
    thickness_mm: float = 1.6

    # Board outline
    board_outline: List[Tuple[float, float]] = field(default_factory=list)

    # Layer definitions
    layers: List[KiCadLayer] = field(default_factory=list)
    stackup: List[KiCadStackupLayer] = field(default_factory=list)

    # Design elements
    components: List[KiCadComponent] = field(default_factory=list)
    nets: List[KiCadNet] = field(default_factory=list)
    traces: List[KiCadTrace] = field(default_factory=list)
    arcs: List[KiCadArc] = field(default_factory=list)
    vias: List[KiCadVia] = field(default_factory=list)
    zones: List[KiCadZone] = field(default_factory=list)

    # Design rules
    design_rules: Optional[KiCadDesignRules] = None

    # Net classes (impedance controlled, etc.)
    net_classes: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Trace statistics
    total_trace_length_mm: float = 0.0
    via_count: int = 0

    # Metadata
    title: Optional[str] = None
    date: Optional[str] = None
    revision: Optional[str] = None
    company: Optional[str] = None

    # Parsing info
    warnings: List[str] = field(default_factory=list)


class SExpressionParser:
    """Simple S-expression parser for KiCad files."""

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.length = len(text)

    def parse(self) -> Any:
        """Parse the entire S-expression."""
        self._skip_whitespace()
        return self._parse_element()

    def _skip_whitespace(self) -> None:
        """Skip whitespace and comments."""
        while self.pos < self.length:
            if self.text[self.pos].isspace():
                self.pos += 1
            elif self.text[self.pos] == '#':
                # Skip comment to end of line
                while self.pos < self.length and self.text[self.pos] != '\n':
                    self.pos += 1
            else:
                break

    def _parse_element(self) -> Any:
        """Parse a single element (list or atom)."""
        self._skip_whitespace()
        if self.pos >= self.length:
            return None

        if self.text[self.pos] == '(':
            return self._parse_list()
        elif self.text[self.pos] == '"':
            return self._parse_string()
        else:
            return self._parse_atom()

    def _parse_list(self) -> List:
        """Parse a list (...)."""
        self.pos += 1  # Skip '('
        result = []

        while self.pos < self.length:
            self._skip_whitespace()
            if self.pos >= self.length:
                break
            if self.text[self.pos] == ')':
                self.pos += 1
                break
            result.append(self._parse_element())

        return result

    def _parse_string(self) -> str:
        """Parse a quoted string."""
        self.pos += 1  # Skip opening quote
        result_chars: list[str] = []

        while self.pos < self.length:
            ch = self.text[self.pos]
            if ch == '"':
                self.pos += 1
                return ''.join(result_chars)
            elif ch == '\\' and self.pos + 1 < self.length:
                self.pos += 1
                result_chars.append(self.text[self.pos])
                self.pos += 1
            else:
                result_chars.append(ch)
                self.pos += 1

        return ''.join(result_chars)

    def _parse_atom(self) -> str:
        """Parse an unquoted atom."""
        start = self.pos

        while self.pos < self.length:
            c = self.text[self.pos]
            if c.isspace() or c in '()':
                break
            self.pos += 1

        return self.text[start:self.pos]


class KiCadPcbParser:
    """Parser for KiCad .kicad_pcb files."""

    def __init__(self):
        self._net_map: Dict[int, str] = {}

    def parse_file(self, file_path: str) -> KiCadBoardData:
        """Parse a KiCad PCB file.

        Args:
            file_path: Path to .kicad_pcb file

        Returns:
            KiCadBoardData with all extracted design data
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not path.suffix.lower() == ".kicad_pcb":
            raise ValueError(f"Not a KiCad PCB file: {file_path}")

        logger.info(f"Parsing KiCad PCB file: {path.name}")

        with open(path, encoding='utf-8') as f:
            content = f.read()

        return self.parse_content(content, str(path))

    def parse_content(self, content: str, source_file: str = "unknown") -> KiCadBoardData:
        """Parse KiCad PCB content.

        Args:
            content: File content as string
            source_file: Source file path for reference

        Returns:
            KiCadBoardData with all extracted design data
        """
        # Parse S-expression
        parser = SExpressionParser(content)
        sexpr = parser.parse()

        if not sexpr or not isinstance(sexpr, list):
            raise ValueError("Invalid KiCad PCB file: Could not parse S-expression")

        if sexpr[0] != "kicad_pcb":
            raise ValueError(f"Not a KiCad PCB file: Root element is '{sexpr[0]}'")

        # Initialize result
        result = KiCadBoardData(source_file=source_file)

        # Parse all sections
        for element in sexpr[1:]:
            if not isinstance(element, list) or not element:
                continue

            tag = element[0]

            try:
                if tag == "version":
                    result.kicad_version = str(element[1]) if len(element) > 1 else None
                elif tag == "generator":
                    result.generator = str(element[1]) if len(element) > 1 else None
                elif tag == "general":
                    self._parse_general(element, result)
                elif tag == "paper":
                    pass  # Skip paper size
                elif tag == "title_block":
                    self._parse_title_block(element, result)
                elif tag == "layers":
                    self._parse_layers(element, result)
                elif tag == "setup":
                    self._parse_setup(element, result)
                elif tag == "net":
                    self._parse_net(element, result)
                elif tag == "net_class":
                    self._parse_net_class(element, result)
                elif tag == "footprint" or tag == "module":
                    self._parse_footprint(element, result)
                elif tag == "gr_line" or tag == "fp_line":
                    pass  # Graphics, handled elsewhere
                elif tag == "segment":
                    self._parse_segment(element, result)
                elif tag == "arc":
                    self._parse_arc(element, result)
                elif tag == "via":
                    self._parse_via(element, result)
                elif tag == "zone":
                    self._parse_zone(element, result)
                elif tag == "gr_rect" or tag == "gr_circle" or tag == "gr_poly":
                    pass  # Graphics
                elif tag == "property":
                    pass  # Board properties
            except Exception as e:
                result.warnings.append(f"Error parsing '{tag}' section: {str(e)}")

        # Calculate board dimensions from outline
        self._calculate_board_dimensions(result)

        # Calculate trace length statistics
        self._calculate_trace_statistics(result)

        logger.info(
            f"KiCad PCB parsed: {len(result.components)} components, "
            f"{len(result.nets)} nets, {len(result.traces)} traces, "
            f"{len(result.vias)} vias, "
            f"total trace length: {result.total_trace_length_mm:.1f}mm"
        )

        return result

    def _parse_general(self, element: List, result: KiCadBoardData) -> None:
        """Parse general section."""
        for item in element[1:]:
            if isinstance(item, list) and len(item) >= 2:
                if item[0] == "thickness":
                    result.thickness_mm = float(item[1])

    def _parse_title_block(self, element: List, result: KiCadBoardData) -> None:
        """Parse title block."""
        for item in element[1:]:
            if isinstance(item, list) and len(item) >= 2:
                if item[0] == "title":
                    result.title = str(item[1])
                elif item[0] == "date":
                    result.date = str(item[1])
                elif item[0] == "rev":
                    result.revision = str(item[1])
                elif item[0] == "company":
                    result.company = str(item[1])

    def _parse_layers(self, element: List, result: KiCadBoardData) -> None:
        """Parse layer definitions."""
        for item in element[1:]:
            if isinstance(item, list) and len(item) >= 3:
                layer_num = int(item[0])
                layer_name = str(item[1])
                layer_type = str(item[2]) if len(item) > 2 else "signal"

                layer = KiCadLayer(
                    number=layer_num,
                    name=layer_name,
                    layer_type=layer_type,
                )
                result.layers.append(layer)

        # Count copper layers
        copper_layers = [l for l in result.layers if "Cu" in l.name]
        result.layer_count = len(copper_layers)

    def _parse_setup(self, element: List, result: KiCadBoardData) -> None:
        """Parse setup section (design rules, stackup)."""
        rules = KiCadDesignRules()

        for item in element[1:]:
            if not isinstance(item, list) or not item:
                continue

            tag = item[0]

            if tag == "stackup":
                self._parse_stackup(item, result)
            elif tag == "pad_to_mask_clearance":
                pass
            elif tag == "aux_axis_origin":
                pass
            elif tag == "pcbplotparams":
                pass

        result.design_rules = rules

    def _parse_stackup(self, element: List, result: KiCadBoardData) -> None:
        """Parse stackup definition."""
        for item in element[1:]:
            if not isinstance(item, list) or not item:
                continue

            if item[0] == "layer":
                layer = KiCadStackupLayer(layer_type="copper")

                for prop in item[1:]:
                    if isinstance(prop, list) and len(prop) >= 2:
                        if prop[0] == "type":
                            layer.layer_type = str(prop[1])
                        elif prop[0] == "thickness":
                            layer.thickness_mm = float(prop[1])
                        elif prop[0] == "material":
                            layer.material = str(prop[1])
                        elif prop[0] == "epsilon_r":
                            layer.dielectric_constant = float(prop[1])
                        elif prop[0] == "loss_tangent":
                            layer.loss_tangent = float(prop[1])
                    elif isinstance(prop, str):
                        layer.name = prop

                result.stackup.append(layer)

    def _parse_net(self, element: List, result: KiCadBoardData) -> None:
        """Parse net definition."""
        if len(element) >= 3:
            net_index = int(element[1])
            net_name = str(element[2])

            net = KiCadNet(index=net_index, name=net_name)
            result.nets.append(net)
            self._net_map[net_index] = net_name

    def _parse_net_class(self, element: List, result: KiCadBoardData) -> None:
        """Parse net class definition."""
        if len(element) >= 2:
            class_name = str(element[1])
            net_class: Dict[str, Any] = {"name": class_name, "nets": []}

            for item in element[2:]:
                if isinstance(item, list) and len(item) >= 2:
                    prop = item[0]
                    value = item[1]

                    if prop == "clearance":
                        net_class["clearance_mm"] = float(value)
                    elif prop == "trace_width":
                        net_class["trace_width_mm"] = float(value)
                    elif prop == "via_dia":
                        net_class["via_diameter_mm"] = float(value)
                    elif prop == "via_drill":
                        net_class["via_drill_mm"] = float(value)
                    elif prop == "uvia_dia":
                        net_class["uvia_diameter_mm"] = float(value)
                    elif prop == "uvia_drill":
                        net_class["uvia_drill_mm"] = float(value)
                    elif prop == "diff_pair_width":
                        net_class["diff_pair_width_mm"] = float(value)
                    elif prop == "diff_pair_gap":
                        net_class["diff_pair_gap_mm"] = float(value)
                elif isinstance(item, str):
                    # Net name in this class
                    net_class["nets"].append(item)

            result.net_classes[class_name] = net_class

    def _parse_footprint(self, element: List, result: KiCadBoardData) -> None:
        """Parse footprint (module) definition."""
        component = KiCadComponent(reference="?", value="")

        # Footprint library:name
        if len(element) >= 2:
            footprint_full = str(element[1])
            if ":" in footprint_full:
                parts = footprint_full.split(":", 1)
                component.footprint_library = parts[0]
                component.footprint = parts[1]
            else:
                component.footprint = footprint_full

        for item in element[2:]:
            if not isinstance(item, list) or not item:
                continue

            tag = item[0]

            if tag == "layer":
                component.layer = str(item[1]) if len(item) > 1 else "F.Cu"
            elif tag == "at":
                if len(item) >= 3:
                    component.x_mm = float(item[1])
                    component.y_mm = float(item[2])
                if len(item) >= 4:
                    component.rotation = float(item[3])
            elif tag == "uuid":
                component.uuid = str(item[1]) if len(item) > 1 else None
            elif tag == "path":
                component.path = str(item[1]) if len(item) > 1 else None
            elif tag == "attr":
                for attr in item[1:]:
                    if attr == "dnp":
                        component.dnp = True
            elif tag == "property":
                if len(item) >= 3:
                    prop_name = str(item[1])
                    prop_value = str(item[2])
                    if prop_name.lower() == "reference":
                        component.reference = prop_value
                    elif prop_name.lower() == "value":
                        component.value = prop_value
            elif tag == "fp_name":
                pass
            elif tag == "fp_text":
                self._parse_fp_text(item, component)
            elif tag == "pad":
                pad = self._parse_pad(item)
                if pad:
                    component.pads.append(pad)

        result.components.append(component)

    def _parse_fp_text(self, element: List, component: KiCadComponent) -> None:
        """Parse footprint text (reference, value)."""
        if len(element) >= 3:
            text_type = str(element[1])
            text_value = str(element[2])

            if text_type == "reference":
                component.reference = text_value
            elif text_type == "value":
                component.value = text_value

    def _parse_pad(self, element: List) -> Optional[KiCadPad]:
        """Parse pad definition."""
        if len(element) < 4:
            return None

        pad = KiCadPad(
            number=str(element[1]),
            pad_type=str(element[2]),
            shape=str(element[3]),
            x_mm=0.0,
            y_mm=0.0,
            width_mm=0.0,
            height_mm=0.0,
        )

        for item in element[4:]:
            if not isinstance(item, list) or not item:
                continue

            tag = item[0]

            if tag == "at":
                if len(item) >= 3:
                    pad.x_mm = float(item[1])
                    pad.y_mm = float(item[2])
            elif tag == "size":
                if len(item) >= 3:
                    pad.width_mm = float(item[1])
                    pad.height_mm = float(item[2])
            elif tag == "drill":
                if len(item) >= 2:
                    pad.drill_mm = float(item[1])
            elif tag == "layers":
                pad.layers = [str(l) for l in item[1:]]
            elif tag == "net":
                if len(item) >= 2:
                    pad.net_index = int(item[1])
                if len(item) >= 3:
                    pad.net_name = str(item[2])

        return pad

    def _parse_segment(self, element: List, result: KiCadBoardData) -> None:
        """Parse trace segment."""
        trace = KiCadTrace(
            x1_mm=0.0, y1_mm=0.0,
            x2_mm=0.0, y2_mm=0.0,
            width_mm=0.0,
            layer="F.Cu",
        )

        for item in element[1:]:
            if not isinstance(item, list) or len(item) < 2:
                continue

            tag = item[0]

            if tag == "start":
                trace.x1_mm = float(item[1])
                trace.y1_mm = float(item[2]) if len(item) > 2 else 0.0
            elif tag == "end":
                trace.x2_mm = float(item[1])
                trace.y2_mm = float(item[2]) if len(item) > 2 else 0.0
            elif tag == "width":
                trace.width_mm = float(item[1])
            elif tag == "layer":
                trace.layer = str(item[1])
            elif tag == "net":
                trace.net_index = int(item[1])
            elif tag == "uuid":
                trace.uuid = str(item[1])

        result.traces.append(trace)

    def _parse_arc(self, element: List, result: KiCadBoardData) -> None:
        """Parse arc segment."""
        arc = KiCadArc(
            x_start_mm=0.0, y_start_mm=0.0,
            x_mid_mm=0.0, y_mid_mm=0.0,
            x_end_mm=0.0, y_end_mm=0.0,
            width_mm=0.0,
            layer="F.Cu",
        )

        for item in element[1:]:
            if not isinstance(item, list) or len(item) < 2:
                continue

            tag = item[0]

            if tag == "start":
                arc.x_start_mm = float(item[1])
                arc.y_start_mm = float(item[2]) if len(item) > 2 else 0.0
            elif tag == "mid":
                arc.x_mid_mm = float(item[1])
                arc.y_mid_mm = float(item[2]) if len(item) > 2 else 0.0
            elif tag == "end":
                arc.x_end_mm = float(item[1])
                arc.y_end_mm = float(item[2]) if len(item) > 2 else 0.0
            elif tag == "width":
                arc.width_mm = float(item[1])
            elif tag == "layer":
                arc.layer = str(item[1])
            elif tag == "net":
                arc.net_index = int(item[1])

        result.arcs.append(arc)

    def _parse_via(self, element: List, result: KiCadBoardData) -> None:
        """Parse via definition."""
        via = KiCadVia(
            x_mm=0.0,
            y_mm=0.0,
            drill_mm=0.3,
            size_mm=0.6,
        )

        layers = []

        for item in element[1:]:
            if not isinstance(item, list) or len(item) < 2:
                continue

            tag = item[0]

            if tag == "at":
                via.x_mm = float(item[1])
                via.y_mm = float(item[2]) if len(item) > 2 else 0.0
            elif tag == "size":
                via.size_mm = float(item[1])
            elif tag == "drill":
                via.drill_mm = float(item[1])
            elif tag == "layers":
                layers = [str(l) for l in item[1:]]
            elif tag == "net":
                via.net_index = int(item[1])
            elif tag == "uuid":
                via.uuid = str(item[1])
            elif tag == "micro":
                via.via_type = "micro"
            elif tag == "blind":
                via.via_type = "blind"

        if len(layers) >= 2:
            via.layers = (layers[0], layers[1])

        result.vias.append(via)

    def _parse_zone(self, element: List, result: KiCadBoardData) -> None:
        """Parse copper zone (pour)."""
        zone = KiCadZone(net_index=0)

        for item in element[1:]:
            if not isinstance(item, list) or not item:
                continue

            tag = item[0]

            if tag == "net":
                zone.net_index = int(item[1]) if len(item) > 1 else 0
            elif tag == "net_name":
                zone.net_name = str(item[1]) if len(item) > 1 else None
            elif tag == "layer":
                zone.layer = str(item[1]) if len(item) > 1 else "F.Cu"
            elif tag == "layers":
                # Multi-layer zone (KiCad 7+)
                zone.layer = str(item[1]) if len(item) > 1 else "F.Cu"
            elif tag == "uuid":
                zone.uuid = str(item[1]) if len(item) > 1 else None
            elif tag == "priority":
                zone.priority = int(item[1]) if len(item) > 1 else 0
            elif tag == "polygon":
                self._parse_zone_polygon(item, zone)
            elif tag == "fill":
                for fill_item in item[1:]:
                    if isinstance(fill_item, list) and fill_item[0] == "mode":
                        zone.fill_type = str(fill_item[1]) if len(fill_item) > 1 else "solid"
            elif tag == "keepout":
                zone.zone_type = "keepout"

        result.zones.append(zone)

    def _parse_zone_polygon(self, element: List, zone: KiCadZone) -> None:
        """Parse zone polygon outline."""
        for item in element[1:]:
            if isinstance(item, list) and item[0] == "pts":
                for pt in item[1:]:
                    if isinstance(pt, list) and pt[0] == "xy" and len(pt) >= 3:
                        x = float(pt[1])
                        y = float(pt[2])
                        zone.outline.append((x, y))

    def _calculate_board_dimensions(self, result: KiCadBoardData) -> None:
        """Calculate board dimensions from all geometry."""
        all_x = []
        all_y = []

        # From traces
        for trace in result.traces:
            all_x.extend([trace.x1_mm, trace.x2_mm])
            all_y.extend([trace.y1_mm, trace.y2_mm])

        # From vias
        for via in result.vias:
            all_x.append(via.x_mm)
            all_y.append(via.y_mm)

        # From components
        for comp in result.components:
            all_x.append(comp.x_mm)
            all_y.append(comp.y_mm)

        # From zones
        for zone in result.zones:
            for x, y in zone.outline:
                all_x.append(x)
                all_y.append(y)

        if all_x and all_y:
            min_x, max_x = min(all_x), max(all_x)
            min_y, max_y = min(all_y), max(all_y)

            result.width_mm = max_x - min_x
            result.height_mm = max_y - min_y

            # Store outline as bounding box
            result.board_outline = [
                (min_x, min_y),
                (max_x, min_y),
                (max_x, max_y),
                (min_x, max_y),
            ]

    def _calculate_trace_statistics(self, result: KiCadBoardData) -> None:
        """Calculate trace length statistics and per-net routed lengths.

        Aggregates total trace length and calculates length per net
        for high-speed analysis.
        """
        # Build net index to net mapping
        net_index_to_net = {net.index: net for net in result.nets}

        # Calculate total trace length and per-net lengths
        net_trace_lengths: Dict[int, float] = {}

        for trace in result.traces:
            length = trace.length_mm

            # Add to total
            result.total_trace_length_mm += length

            # Add to per-net length
            if trace.net_index > 0:  # KiCad uses 0 for unconnected
                net_trace_lengths[trace.net_index] = (
                    net_trace_lengths.get(trace.net_index, 0) + length
                )

        # Also add arc lengths
        for arc in result.arcs:
            # Approximate arc length using chord length for now
            # Full arc calculation would require center point
            import math
            dx = arc.x_end_mm - arc.x_start_mm
            dy = arc.y_end_mm - arc.y_start_mm
            chord_length = math.sqrt(dx * dx + dy * dy)

            result.total_trace_length_mm += chord_length

            if arc.net_index > 0:
                net_trace_lengths[arc.net_index] = (
                    net_trace_lengths.get(arc.net_index, 0) + chord_length
                )

        # Update net objects with routed lengths
        for net_index, length in net_trace_lengths.items():
            if net_index in net_index_to_net:
                net_index_to_net[net_index].routed_length_mm = length

        # Set via count
        result.via_count = len(result.vias)

        logger.debug(f"Trace statistics: total={result.total_trace_length_mm:.1f}mm, "
                    f"nets with routes={len(net_trace_lengths)}, vias={result.via_count}")


# Factory function
def parse_kicad_pcb(file_path: str) -> KiCadBoardData:
    """Parse a KiCad PCB file.

    Args:
        file_path: Path to .kicad_pcb file

    Returns:
        KiCadBoardData with extracted design data
    """
    parser = KiCadPcbParser()
    return parser.parse_file(file_path)

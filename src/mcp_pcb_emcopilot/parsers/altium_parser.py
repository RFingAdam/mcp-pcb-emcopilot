"""Altium Designer file parser for SchDoc and PcbDoc files.

Supports:
- .SchDoc (Schematic Document) - OLE compound document with pipe-delimited records
- .PcbDoc (PCB Document) - OLE compound document with components, nets, traces, vias

Data extraction:
- Components with reference, value, footprint, position
- Nets with names and connected pins
- Traces with coordinates, width, layer
- Vias with position, drill size, layers
- Pads with shape, size, layer
- Board dimensions and stackup

Format Benefits for AI Review:
- SchDoc: Native schematic with full hierarchy, electrical connectivity
- PcbDoc: Complete design data including 3D models, design rules
- Rich metadata: Part numbers, manufacturers, descriptions

Format Limitations:
- Binary/OLE format requires specialized parsing
- Complex record structure with variable-length fields
- Track data is binary (requires struct unpacking)
"""

from __future__ import annotations

import logging
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import olefile
    HAS_OLEFILE = True
except ImportError:
    HAS_OLEFILE = False

logger = logging.getLogger(__name__)


# Unit conversion: Altium uses mils internally (1 mil = 0.0254 mm)
MIL_TO_MM = 0.0254
# Some coordinates are in internal units (1/10000 mil)
INTERNAL_TO_MM = 0.0254 / 10000


@dataclass
class AltiumComponent:
    """Component extracted from Altium design."""
    reference: str
    value: Optional[str] = None
    footprint: Optional[str] = None
    part_number: Optional[str] = None
    manufacturer: Optional[str] = None
    description: Optional[str] = None
    layer: str = "TOP"
    x_mm: float = 0.0
    y_mm: float = 0.0
    rotation: float = 0.0
    unique_id: Optional[str] = None
    library_ref: Optional[str] = None
    source_library: Optional[str] = None


@dataclass
class AltiumNet:
    """Net extracted from Altium design."""
    name: str
    color: Optional[int] = None
    visible: bool = True
    pins: List[Dict[str, str]] = field(default_factory=list)
    routed_length_mm: float = 0.0  # Total routed length of traces on this net


@dataclass
class AltiumTrace:
    """Trace extracted from Altium PcbDoc."""
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float
    width_mm: float
    layer: int
    net_index: int = -1

    @property
    def length_mm(self) -> float:
        """Calculate trace segment length in mm."""
        import math
        dx = self.x2_mm - self.x1_mm
        dy = self.y2_mm - self.y1_mm
        return math.sqrt(dx * dx + dy * dy)


@dataclass
class AltiumVia:
    """Via extracted from Altium PcbDoc."""
    x_mm: float
    y_mm: float
    drill_mm: float
    size_mm: float
    start_layer: int
    end_layer: int
    net_index: int = -1
    via_type: str = "through"  # through, blind, buried, microvia

    def classify_via_type(self, total_layers: int) -> str:
        """Classify via type based on layer span.

        Args:
            total_layers: Total number of copper layers in the board

        Returns:
            Via type: 'through', 'blind', 'buried', or 'microvia'
        """
        if total_layers <= 2:
            return "through"

        is_top_connected = self.start_layer == 1
        is_bottom_connected = self.end_layer == total_layers or self.end_layer == 32
        layer_span = abs(self.end_layer - self.start_layer) + 1

        if is_top_connected and is_bottom_connected:
            return "through"
        elif is_top_connected or is_bottom_connected:
            # Connects to outer layer but not through
            if layer_span <= 2:
                return "microvia"  # Single layer span from outer
            return "blind"
        else:
            # Doesn't connect to either outer layer
            if layer_span <= 2:
                return "microvia"
            return "buried"


@dataclass
class AltiumPad:
    """Pad extracted from Altium PcbDoc."""
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    shape: str  # ROUND, RECTANGLE, OCTAGONAL
    layer: int
    component_index: int = -1
    net_index: int = -1
    pin_designator: Optional[str] = None


@dataclass
class AltiumArc:
    """Arc extracted from Altium PcbDoc."""
    cx_mm: float  # Center X
    cy_mm: float  # Center Y
    radius_mm: float
    start_angle: float
    end_angle: float
    width_mm: float
    layer: int


@dataclass
class AltiumBoardOutline:
    """Board outline segment (line or arc)."""
    segment_type: str  # "line" or "arc"
    x1_mm: float = 0.0
    y1_mm: float = 0.0
    x2_mm: float = 0.0
    y2_mm: float = 0.0
    # For arcs
    cx_mm: float = 0.0
    cy_mm: float = 0.0
    radius_mm: float = 0.0
    start_angle: float = 0.0
    end_angle: float = 0.0


@dataclass
class AltiumLayerInfo:
    """Layer stack information."""
    layer_id: int
    name: str
    layer_type: str  # "signal", "plane", "dielectric", "solder_mask", etc.
    thickness_mm: float = 0.0
    copper_weight_oz: float = 1.0
    dielectric_constant: float = 4.2


@dataclass
class AltiumBoardData:
    """Complete parsed Altium PcbDoc data."""
    source_file: str

    # Board dimensions
    width_mm: float = 0.0
    height_mm: float = 0.0
    layer_count: int = 2

    # Board outline (for precise dimensions)
    board_outline: List[AltiumBoardOutline] = field(default_factory=list)

    # Layer stack
    layer_stack: List[AltiumLayerInfo] = field(default_factory=list)

    # Design elements
    components: List[AltiumComponent] = field(default_factory=list)
    nets: List[AltiumNet] = field(default_factory=list)
    traces: List[AltiumTrace] = field(default_factory=list)
    vias: List[AltiumVia] = field(default_factory=list)
    pads: List[AltiumPad] = field(default_factory=list)
    arcs: List[AltiumArc] = field(default_factory=list)

    # Design rules
    design_rules: Dict[str, Any] = field(default_factory=dict)
    differential_pairs: List[Dict[str, str]] = field(default_factory=list)

    # Trace statistics
    total_trace_length_mm: float = 0.0
    via_count: int = 0

    # Metadata
    warnings: List[str] = field(default_factory=list)
    properties: Dict[str, str] = field(default_factory=dict)


@dataclass
class AltiumSchematicData:
    """Complete parsed Altium SchDoc data."""
    source_file: str

    # Schematic info
    title: Optional[str] = None
    revision: Optional[str] = None
    sheet_number: int = 1

    # Components and nets
    components: List[AltiumComponent] = field(default_factory=list)
    nets: List[AltiumNet] = field(default_factory=list)

    # Power symbols
    power_symbols: List[Dict[str, Any]] = field(default_factory=list)

    # Warnings
    warnings: List[str] = field(default_factory=list)


class AltiumPcbParser:
    """Parser for Altium .PcbDoc files.

    Extracts:
    - Components with reference, footprint, position
    - Nets with connectivity
    - Traces with coordinates, width, layer
    - Vias with drill size and span
    - Pads with shape and size
    - Board outline and dimensions

    Usage:
        parser = AltiumPcbParser()
        data = parser.parse("board.PcbDoc")
        print(f"Found {len(data.components)} components")
    """

    # Layer mapping (Altium layer numbers to names)
    LAYER_NAMES = {
        1: "TOP",
        2: "MID1",
        3: "MID2",
        4: "MID3",
        5: "MID4",
        6: "MID5",
        7: "MID6",
        8: "MID7",
        9: "MID8",
        10: "MID9",
        11: "MID10",
        32: "BOTTOM",
        33: "TOP_OVERLAY",
        34: "BOTTOM_OVERLAY",
        35: "TOP_PASTE",
        36: "BOTTOM_PASTE",
        37: "TOP_SOLDER",
        38: "BOTTOM_SOLDER",
        39: "DRILL_GUIDE",
        40: "KEEPOUT",
        41: "MECHANICAL1",
        42: "MECHANICAL2",
        43: "MECHANICAL3",
        44: "MECHANICAL4",
        74: "MULTILAYER",
    }

    def __init__(self):
        if not HAS_OLEFILE:
            raise ImportError("olefile library required for Altium parsing. Install with: pip install olefile")

    def parse(self, file_path: str) -> AltiumBoardData:
        """Parse Altium PcbDoc file.

        Args:
            file_path: Path to .PcbDoc file

        Returns:
            AltiumBoardData with all extracted information
        """  # type: ignore[assignment]
        file_path = Path(file_path)  # type: ignore[assignment]
  # type: ignore[attr-defined]
        if not file_path.exists():  # type: ignore[attr-defined]
            raise FileNotFoundError(f"PcbDoc file not found: {file_path}")

        data = AltiumBoardData(source_file=str(file_path))

        try:
            ole = olefile.OleFileIO(str(file_path))

            # Parse each section
            self._parse_board_info(ole, data)
            self._parse_layer_stack(ole, data)
            self._parse_board_outline(ole, data)
            self._parse_components(ole, data)
            self._parse_nets(ole, data)
            self._parse_tracks(ole, data)
            self._parse_vias(ole, data)
            self._parse_pads(ole, data)
            self._parse_arcs(ole, data)
            self._parse_regions(ole, data)  # For board outline from regions
            self._parse_rules(ole, data)
            self._parse_differential_pairs(ole, data)

            ole.close()

            # Calculate layer count from actual data if not set
            self._calculate_layer_count(data)

            # Calculate board dimensions from outline or geometry
            self._calculate_board_dimensions(data)

            # Calculate trace lengths and statistics
            self._calculate_trace_statistics(data)

            logger.info(f"Parsed PcbDoc: {len(data.components)} components, "
                       f"{len(data.nets)} nets, {len(data.traces)} traces, "
                       f"{len(data.vias)} vias, {data.layer_count} layers, "
                       f"board: {data.width_mm:.1f}x{data.height_mm:.1f}mm, "
                       f"total trace length: {data.total_trace_length_mm:.1f}mm")

            return data

        except Exception as e:
            logger.error(f"Failed to parse PcbDoc: {e}")
            raise ValueError(f"PcbDoc parse error: {str(e)}")

    def _parse_pipe_delimited(self, raw_data: bytes) -> List[Dict[str, str]]:
        """Parse pipe-delimited records from Altium data stream.

        Format: <length><data>|KEY=VALUE|KEY=VALUE|...
        """
        records = []
        pos = 0

        while pos < len(raw_data):
            # First 4 bytes are record length
            if pos + 4 > len(raw_data):
                break

            record_len = struct.unpack('<I', raw_data[pos:pos+4])[0]
            pos += 4

            if record_len == 0 or pos + record_len > len(raw_data):
                break

            # Extract record data
            record_data = raw_data[pos:pos+record_len]
            pos += record_len

            # Parse pipe-delimited fields
            try:
                text = record_data.decode('utf-8', errors='ignore')
                fields = {}

                for part in text.split('|'):
                    if '=' in part:
                        key, value = part.split('=', 1)
                        fields[key.strip()] = value.strip()

                if fields:
                    records.append(fields)

            except Exception as e:
                # Log but continue - one malformed record shouldn't break entire parse
                logger.debug(f"Skipped malformed pipe-delimited record: {e}")
                continue

        return records

    def _parse_board_info(self, ole: olefile.OleFileIO, data: AltiumBoardData) -> None:
        """Parse board dimensions and layer info from Board6 stream.

        Note: SHEETWIDTH/SHEETHEIGHT are the page size, not board outline.
        We store these as fallback, but prefer actual board outline.
        """
        try:
            if ole.exists(['Board6', 'Data']):
                board_data = ole.openstream(['Board6', 'Data']).read()
                records = self._parse_pipe_delimited(board_data)

                for record in records:
                    # Store sheet dimensions as fallback (will be overridden by board outline)
                    if 'SHEETWIDTH' in record and data.width_mm == 0:
                        width_mil = self._parse_mil_value(record.get('SHEETWIDTH', '0'))
                        data.width_mm = width_mil * MIL_TO_MM

                    if 'SHEETHEIGHT' in record and data.height_mm == 0:
                        height_mil = self._parse_mil_value(record.get('SHEETHEIGHT', '0'))
                        data.height_mm = height_mil * MIL_TO_MM

                    # Look for board origin to help calculate real dimensions
                    if 'ORIGINX' in record:
                        data.properties['ORIGIN_X_MM'] = str(
                            self._parse_mil_value(record.get('ORIGINX', '0')) * MIL_TO_MM
                        )
                    if 'ORIGINY' in record:
                        data.properties['ORIGIN_Y_MM'] = str(
                            self._parse_mil_value(record.get('ORIGINY', '0')) * MIL_TO_MM
                        )

                    # Try to extract layer count from various property names
                    for key in ['V9_LAYERCOUNT', 'LAYERCOUNT', 'INNERLAYERCOUNT',
                                'V9_SIGNALLAYERCOUNT', 'SIGNALLAYERCOUNT',
                                'LAYERSTA_V9STACKLAYER']:
                        if key in record:
                            try:
                                layer_val = int(record[key])
                                # Only use reasonable layer counts (2-32)
                                if 2 <= layer_val <= 32 and layer_val > data.layer_count:
                                    data.layer_count = layer_val
                            except (ValueError, TypeError):
                                pass

                    # Properties
                    for key, value in record.items():
                        data.properties[key] = value

        except Exception as e:
            data.warnings.append(f"Failed to parse board info: {e}")

    def _parse_layer_stack(self, ole: olefile.OleFileIO, data: AltiumBoardData) -> None:
        """Parse layer stack information from Layer6 or LayerStackManager streams."""
        try:
            # Try LayerStackManager6 first (newer format)
            if ole.exists(['LayerStackManager6', 'Data']):
                stack_data = ole.openstream(['LayerStackManager6', 'Data']).read()
                records = self._parse_pipe_delimited(stack_data)

                signal_layers = 0
                for record in records:
                    layer_id = self._parse_int(record.get('LAYERID', '-1'))
                    if layer_id < 0:
                        continue

                    name = record.get('NAME', record.get('LAYERNAME', f'Layer{layer_id}'))
                    layer_type = record.get('LAYERTYPE', record.get('LAYERKIND', 'signal')).lower()

                    # Determine layer type
                    if 'signal' in layer_type or 'component' in layer_type:
                        layer_type = 'signal'
                        signal_layers += 1
                    elif 'plane' in layer_type or 'power' in layer_type or 'ground' in layer_type:
                        layer_type = 'plane'
                        signal_layers += 1
                    elif 'dielectric' in layer_type or 'prepreg' in layer_type or 'core' in layer_type:
                        layer_type = 'dielectric'
                    elif 'solder' in layer_type:
                        layer_type = 'solder_mask'
                    elif 'silk' in layer_type or 'overlay' in layer_type:
                        layer_type = 'silkscreen'
                    else:
                        layer_type = 'other'

                    # Parse thickness (in mils or um)
                    thickness = self._parse_mil_value(record.get('DIELECTRICTHICKNESS',
                                                                 record.get('COPPERTHICKNESS', '0')))
                    thickness_mm = thickness * MIL_TO_MM

                    # Parse copper weight
                    copper_weight = self._parse_float(record.get('COPPERWEIGHT', '1'))
                    if copper_weight == 0:
                        copper_weight = 1.0

                    # Dielectric constant
                    dk = self._parse_float(record.get('DIELECTRICCONST',
                                                      record.get('DIELECTRICCONSTANT', '4.2')))

                    layer_info = AltiumLayerInfo(
                        layer_id=layer_id,
                        name=name,
                        layer_type=layer_type,
                        thickness_mm=thickness_mm,
                        copper_weight_oz=copper_weight,
                        dielectric_constant=dk if dk > 0 else 4.2,
                    )
                    data.layer_stack.append(layer_info)

                # Update layer count from stack if more accurate
                if signal_layers > data.layer_count:
                    data.layer_count = signal_layers

            # Try Layer6 as fallback
            elif ole.exists(['Layer6', 'Data']):
                layer_data = ole.openstream(['Layer6', 'Data']).read()
                records = self._parse_pipe_delimited(layer_data)

                for record in records:
                    layer_id = self._parse_int(record.get('LAYER_ID', record.get('V7_LAYERID', '-1')))
                    if layer_id < 0:
                        continue

                    name = record.get('NAME', record.get('V7_LAYERNAME', ''))
                    if name:
                        layer_info = AltiumLayerInfo(
                            layer_id=layer_id,
                            name=name,
                            layer_type='signal' if layer_id <= 32 else 'other',
                        )
                        data.layer_stack.append(layer_info)

                # Count copper layers
                copper_layers = len([l for l in data.layer_stack
                                    if l.layer_type in ('signal', 'plane') and l.layer_id <= 32])
                if copper_layers > data.layer_count:
                    data.layer_count = copper_layers

        except Exception as e:
            data.warnings.append(f"Failed to parse layer stack: {e}")

    def _parse_board_outline(self, ole: olefile.OleFileIO, data: AltiumBoardData) -> None:
        """Parse board outline from various sources.

        Board outline can be in:
        - Board6 stream (as special records)
        - Tracks6 on mechanical layer 1 (layer 41)
        - Regions6 as keepout or board outline region
        """
        try:
            # Check for tracks on mechanical layer 1 (common for board outline)
            outline_tracks = []

            if ole.exists(['Tracks6', 'Data']):
                track_data = ole.openstream(['Tracks6', 'Data']).read()

                # Try pipe-delimited first (some versions)
                records = self._parse_pipe_delimited(track_data)
                for record in records:
                    layer = self._parse_int(record.get('LAYER', '0'))
                    # Mechanical layer 1 = 41, Keepout = 40
                    if layer in (40, 41, 42, 43, 44):
                        x1 = self._parse_mil_value(record.get('X1', '0')) * MIL_TO_MM
                        y1 = self._parse_mil_value(record.get('Y1', '0')) * MIL_TO_MM
                        x2 = self._parse_mil_value(record.get('X2', '0')) * MIL_TO_MM
                        y2 = self._parse_mil_value(record.get('Y2', '0')) * MIL_TO_MM

                        if x1 != 0 or y1 != 0 or x2 != 0 or y2 != 0:
                            outline_segment = AltiumBoardOutline(
                                segment_type="line",
                                x1_mm=x1, y1_mm=y1,
                                x2_mm=x2, y2_mm=y2,
                            )
                            outline_tracks.append(outline_segment)

            # Check arcs on mechanical layers
            if ole.exists(['Arcs6', 'Data']):
                arc_data = ole.openstream(['Arcs6', 'Data']).read()
                records = self._parse_pipe_delimited(arc_data)

                for record in records:
                    layer = self._parse_int(record.get('LAYER', '0'))
                    if layer in (40, 41, 42, 43, 44):
                        cx = self._parse_mil_value(record.get('LOCATION.X', '0')) * MIL_TO_MM
                        cy = self._parse_mil_value(record.get('LOCATION.Y', '0')) * MIL_TO_MM
                        radius = self._parse_mil_value(record.get('RADIUS', '0')) * MIL_TO_MM
                        start_angle = self._parse_float(record.get('STARTANGLE', '0'))
                        end_angle = self._parse_float(record.get('ENDANGLE', '0'))

                        if radius > 0:
                            outline_segment = AltiumBoardOutline(
                                segment_type="arc",
                                cx_mm=cx, cy_mm=cy,
                                radius_mm=radius,
                                start_angle=start_angle,
                                end_angle=end_angle,
                            )
                            outline_tracks.append(outline_segment)

            # Store outline if found
            if outline_tracks:
                data.board_outline = outline_tracks

        except Exception as e:
            data.warnings.append(f"Failed to parse board outline: {e}")

    def _parse_regions(self, ole: olefile.OleFileIO, data: AltiumBoardData) -> None:
        """Parse regions for board outline and other polygons."""
        try:
            if ole.exists(['Regions6', 'Data']):
                region_data = ole.openstream(['Regions6', 'Data']).read()
                records = self._parse_pipe_delimited(region_data)

                for record in records:
                    layer = self._parse_int(record.get('LAYER', '0'))
                    kind = record.get('KIND', record.get('REGIONKIND', '')).upper()

                    # Board outline or keepout region
                    if kind in ('BOARDOUTLINE', 'BOARD', 'OUTLINE') or layer in (40, 41):
                        # Parse region vertices from OUTLINE data
                        outline_str = record.get('OUTLINE', record.get('VERTICES', ''))
                        if outline_str:
                            vertices = self._parse_region_vertices(outline_str)
                            if vertices and len(vertices) >= 3:
                                # Convert vertices to line segments
                                for i in range(len(vertices)):
                                    v1 = vertices[i]
                                    v2 = vertices[(i + 1) % len(vertices)]
                                    segment = AltiumBoardOutline(
                                        segment_type="line",
                                        x1_mm=v1[0], y1_mm=v1[1],
                                        x2_mm=v2[0], y2_mm=v2[1],
                                    )
                                    data.board_outline.append(segment)

        except Exception as e:
            data.warnings.append(f"Failed to parse regions: {e}")

    def _parse_region_vertices(self, outline_str: str) -> List[Tuple[float, float]]:
        """Parse region vertices from outline string.

        Format varies but typically: X1=val|Y1=val|X2=val|Y2=val|...
        """
        vertices = []
        try:
            parts = outline_str.split('|')
            current_x, current_y = None, None

            for part in parts:
                if '=' in part:
                    key, value = part.split('=', 1)
                    key = key.upper()
                    val_mm = self._parse_mil_value(value) * MIL_TO_MM

                    if key.startswith('X') and key[1:].isdigit():
                        current_x = val_mm
                    elif key.startswith('Y') and key[1:].isdigit():
                        current_y = val_mm
                        if current_x is not None:
                            vertices.append((current_x, current_y))
                            current_x = None

        except Exception as e:
            # Log but return partial results - vertices parsing is best-effort
            logger.debug(f"Error parsing region vertices: {e}")

        return vertices

    def _calculate_board_dimensions(self, data: AltiumBoardData) -> None:
        """Calculate actual board dimensions from outline or component/trace bounding box.

        Priority:
        1. Board outline geometry (most accurate)
        2. Component bounding box
        3. Trace/via bounding box
        4. Keep sheet size as fallback
        """
        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = float('-inf'), float('-inf')

        # Option 1: Calculate from board outline
        if data.board_outline:
            for segment in data.board_outline:
                if segment.segment_type == "line":
                    min_x = min(min_x, segment.x1_mm, segment.x2_mm)
                    min_y = min(min_y, segment.y1_mm, segment.y2_mm)
                    max_x = max(max_x, segment.x1_mm, segment.x2_mm)
                    max_y = max(max_y, segment.y1_mm, segment.y2_mm)
                elif segment.segment_type == "arc":
                    # For arcs, use center +/- radius as approximation
                    min_x = min(min_x, segment.cx_mm - segment.radius_mm)
                    min_y = min(min_y, segment.cy_mm - segment.radius_mm)
                    max_x = max(max_x, segment.cx_mm + segment.radius_mm)
                    max_y = max(max_y, segment.cy_mm + segment.radius_mm)

        # Option 2: If no outline, use component bounding box with adaptive margins
        if (min_x == float('inf') or max_x == float('-inf')) and data.components:
            # Calculate component-aware bounding box with footprint sizes
            comp_min_x, comp_min_y = float('inf'), float('inf')
            comp_max_x, comp_max_y = float('-inf'), float('-inf')
            max_footprint_size = 0.0

            for comp in data.components:
                # Estimate footprint size from component type
                footprint_size = self._estimate_footprint_size(comp)
                max_footprint_size = max(max_footprint_size, footprint_size)

                # Use center point +/- half footprint for rough bounds
                half_size = footprint_size / 2
                comp_min_x = min(comp_min_x, comp.x_mm - half_size)
                comp_min_y = min(comp_min_y, comp.y_mm - half_size)
                comp_max_x = max(comp_max_x, comp.x_mm + half_size)
                comp_max_y = max(comp_max_y, comp.y_mm + half_size)

            # Calculate adaptive margin based on board size and component density
            # Small boards (< 50mm): ~2mm margin
            # Medium boards (50-150mm): ~3mm margin
            # Large boards (> 150mm): ~5mm margin
            estimated_width = comp_max_x - comp_min_x
            estimated_height = comp_max_y - comp_min_y
            estimated_size = max(estimated_width, estimated_height)

            if estimated_size < 50:
                adaptive_margin = 2.0
            elif estimated_size < 150:
                adaptive_margin = 3.0
            else:
                adaptive_margin = 5.0

            # Ensure margin accounts for edge components
            adaptive_margin = max(adaptive_margin, max_footprint_size / 2)

            min_x = comp_min_x - adaptive_margin
            min_y = comp_min_y - adaptive_margin
            max_x = comp_max_x + adaptive_margin
            max_y = comp_max_y + adaptive_margin

            data.properties['DIMENSION_SOURCE'] = 'component_bounding_box'  # type: ignore[assignment]
            data.properties['DIMENSION_MARGIN_MM'] = adaptive_margin  # type: ignore[assignment]

        # Option 3: If still no bounds, use traces
        if (min_x == float('inf') or max_x == float('-inf')) and data.traces:
            for trace in data.traces:
                min_x = min(min_x, trace.x1_mm, trace.x2_mm)
                min_y = min(min_y, trace.y1_mm, trace.y2_mm)
                max_x = max(max_x, trace.x1_mm, trace.x2_mm)
                max_y = max(max_y, trace.y1_mm, trace.y2_mm)

        # Option 4: Vias
        if (min_x == float('inf') or max_x == float('-inf')) and data.vias:
            for via in data.vias:
                min_x = min(min_x, via.x_mm)
                min_y = min(min_y, via.y_mm)
                max_x = max(max_x, via.x_mm)
                max_y = max(max_y, via.y_mm)

        # Update dimensions if we found valid bounds
        if min_x != float('inf') and max_x != float('-inf'):
            calculated_width = max_x - min_x
            calculated_height = max_y - min_y

            # Only use calculated dimensions if they're reasonable
            # (not too small, and smaller than sheet size which is usually page size)
            if calculated_width > 1.0 and calculated_height > 1.0:
                # If calculated is smaller than sheet size, it's likely more accurate
                if calculated_width < data.width_mm * 0.9 or calculated_height < data.height_mm * 0.9:
                    data.width_mm = calculated_width
                    data.height_mm = calculated_height
                    data.properties['DIMENSION_SOURCE'] = 'calculated_from_geometry'
                elif data.board_outline:
                    # Board outline is explicitly defined, trust it
                    data.width_mm = calculated_width
                    data.height_mm = calculated_height
                    data.properties['DIMENSION_SOURCE'] = 'board_outline'

    def _calculate_trace_statistics(self, data: AltiumBoardData) -> None:
        """Calculate trace length statistics and per-net routed lengths.

        Aggregates total trace length and calculates length per net
        for high-speed analysis.
        """
        # Build net index to net name mapping
        net_index_to_name = {}
        for idx, net in enumerate(data.nets):
            net_index_to_name[idx] = net.name

        # Calculate total trace length and per-net lengths
        net_trace_lengths: Dict[str, float] = {}

        for trace in data.traces:
            length = trace.length_mm

            # Add to total
            data.total_trace_length_mm += length

            # Add to per-net length
            if trace.net_index >= 0:
                net_name = net_index_to_name.get(trace.net_index, f"Net_{trace.net_index}")
                net_trace_lengths[net_name] = net_trace_lengths.get(net_name, 0) + length

        # Update net objects with routed lengths
        for net in data.nets:
            net.routed_length_mm = net_trace_lengths.get(net.name, 0)

        # Set via count and classify via types
        data.via_count = len(data.vias)

        # Classify via types based on layer span
        via_type_counts = {"through": 0, "blind": 0, "buried": 0, "microvia": 0}
        for via in data.vias:
            via.via_type = via.classify_via_type(data.layer_count)
            via_type_counts[via.via_type] = via_type_counts.get(via.via_type, 0) + 1

        logger.debug(f"Trace statistics: total={data.total_trace_length_mm:.1f}mm, "
                    f"nets with routes={len(net_trace_lengths)}, vias={data.via_count}")
        if any(v > 0 for k, v in via_type_counts.items() if k != "through"):
            logger.debug(f"Via types: {via_type_counts}")

    def _calculate_layer_count(self, data: AltiumBoardData) -> None:
        """Calculate layer count from traces, vias, and pads.

        Altium layer numbering:
        - 1 = Top copper
        - 2-31 = Inner copper layers
        - 32 = Bottom copper
        - 33-39 = Internal planes
        - 40+ = Mechanical, keepout, etc.
        - 74 = Multi-layer (vias/pads that span all layers)
        """
        # Collect all used copper layers (1-32 range only)
        copper_layers_used = set()

        # Check traces for copper layers
        for trace in data.traces:
            if isinstance(trace.layer, int) and 1 <= trace.layer <= 32:
                copper_layers_used.add(trace.layer)

        # Check vias layer spans
        for via in data.vias:
            if isinstance(via.start_layer, int) and 1 <= via.start_layer <= 32:
                copper_layers_used.add(via.start_layer)
            if isinstance(via.end_layer, int) and 1 <= via.end_layer <= 32:
                copper_layers_used.add(via.end_layer)

        # Check pads for copper layers
        for pad in data.pads:
            if isinstance(pad.layer, int) and 1 <= pad.layer <= 32:
                copper_layers_used.add(pad.layer)

        # Calculate actual layer count
        if copper_layers_used:
            has_top = 1 in copper_layers_used
            has_bottom = 32 in copper_layers_used
            inner_layers = {l for l in copper_layers_used if 2 <= l <= 31}

            if has_top and has_bottom:
                # Standard multi-layer: top + inner + bottom
                calculated_count = 2 + len(inner_layers)
            elif has_top or has_bottom:
                # Has one outer layer
                calculated_count = 1 + len(inner_layers) + (1 if (has_top or has_bottom) else 0)
            else:
                # Only inner layers (unlikely but handle it)
                calculated_count = len(inner_layers) if inner_layers else 2

            # Use calculated count if it makes more sense
            if calculated_count >= 2 and (data.layer_count <= 2 or data.layer_count > 32):
                data.layer_count = calculated_count

        # Bound layer count to reasonable PCB range (2-32 layers)
        if data.layer_count < 2:
            data.layer_count = 2
        elif data.layer_count > 32:
            # If we got a bogus high value, try to use layer stack count
            if data.layer_stack:
                signal_layers = sum(1 for l in data.layer_stack if l.layer_type in ('signal', 'plane'))
                if signal_layers >= 2:
                    data.layer_count = signal_layers
                else:
                    data.layer_count = 2
            else:
                data.layer_count = 2

        # Also check properties for explicit layer count hints (but cap at 32)
        for key, value in data.properties.items():
            if 'LAYER' in key.upper() and 'COUNT' in key.upper():
                try:
                    prop_layers = int(value)
                    # Only use if reasonable and we don't have better data
                    if 2 <= prop_layers <= 32:
                        # Use this value if we're still at default
                        if data.layer_count == 2:
                            data.layer_count = prop_layers
                except (ValueError, TypeError):
                    pass

    def _parse_components(self, ole: olefile.OleFileIO, data: AltiumBoardData) -> None:
        """Parse components from Components6 stream."""
        try:
            if ole.exists(['Components6', 'Data']):
                comp_data = ole.openstream(['Components6', 'Data']).read()
                records = self._parse_pipe_delimited(comp_data)

                for record in records:
                    reference = record.get('SOURCEDESIGNATOR', '')
                    if not reference:
                        continue

                    component = AltiumComponent(
                        reference=reference,
                        footprint=record.get('PATTERN', ''),
                        layer=record.get('LAYER', 'TOP'),
                        x_mm=self._parse_mil_value(record.get('X', '0')) * MIL_TO_MM,
                        y_mm=self._parse_mil_value(record.get('Y', '0')) * MIL_TO_MM,
                        rotation=self._parse_float(record.get('ROTATION', '0')),
                        unique_id=record.get('UNIQUEID', ''),
                        description=record.get('SOURCEDESCRIPTION', ''),
                        library_ref=record.get('SOURCELIBREFERENCE', ''),
                        source_library=record.get('SOURCECOMPONENTLIBRARY', ''),
                    )

                    data.components.append(component)

        except Exception as e:
            data.warnings.append(f"Failed to parse components: {e}")

    def _parse_nets(self, ole: olefile.OleFileIO, data: AltiumBoardData) -> None:
        """Parse nets from Nets6 stream."""
        try:
            if ole.exists(['Nets6', 'Data']):
                net_data = ole.openstream(['Nets6', 'Data']).read()
                records = self._parse_pipe_delimited(net_data)

                for record in records:
                    name = record.get('NAME', '')
                    if not name:
                        continue

                    net = AltiumNet(
                        name=name,
                        color=int(record.get('COLOR', '0')) if record.get('COLOR', '').isdigit() else None,
                        visible=record.get('VISIBLE', 'TRUE').upper() == 'TRUE',
                    )

                    data.nets.append(net)

        except Exception as e:
            data.warnings.append(f"Failed to parse nets: {e}")

    def _parse_tracks(self, ole: olefile.OleFileIO, data: AltiumBoardData) -> None:
        """Parse tracks from Tracks6 stream.

        Altium tracks can be in two formats:
        1. Binary format with fixed-size records (legacy)
        2. Pipe-delimited text records (modern)

        We try pipe-delimited first as it's more reliable, then fall back to binary.
        """
        try:
            if ole.exists(['Tracks6', 'Data']):
                track_data = ole.openstream(['Tracks6', 'Data']).read()

                # First try pipe-delimited format (more reliable)
                records = self._parse_pipe_delimited(track_data)

                if records:
                    for record in records:
                        # Skip non-track records
                        if 'X1' not in record and 'LOCATION.X' not in record:
                            continue

                        # Parse coordinates - try both naming conventions
                        x1 = self._parse_mil_value(
                            record.get('X1', record.get('LOCATION.X', '0'))
                        ) * MIL_TO_MM
                        y1 = self._parse_mil_value(
                            record.get('Y1', record.get('LOCATION.Y', '0'))
                        ) * MIL_TO_MM
                        x2 = self._parse_mil_value(record.get('X2', '0')) * MIL_TO_MM
                        y2 = self._parse_mil_value(record.get('Y2', '0')) * MIL_TO_MM
                        width = self._parse_mil_value(record.get('WIDTH', '0')) * MIL_TO_MM
                        layer = self._parse_int(record.get('LAYER', '1'))
                        net_idx = self._parse_int(record.get('NET', '-1'))

                        # Only add valid tracks with reasonable dimensions
                        if width > 0 and width < 100:  # < 100mm width is reasonable
                            trace = AltiumTrace(
                                x1_mm=x1,
                                y1_mm=y1,
                                x2_mm=x2,
                                y2_mm=y2,
                                width_mm=width,
                                layer=layer,
                                net_index=net_idx,
                            )
                            data.traces.append(trace)

                    # If we got tracks from pipe-delimited, we're done
                    if data.traces:
                        return

                # Fall back to binary parsing for older file formats
                self._parse_tracks_binary(track_data, data)

        except Exception as e:
            data.warnings.append(f"Failed to parse tracks: {e}")

    def _parse_tracks_binary(self, track_data: bytes, data: AltiumBoardData) -> None:
        """Parse tracks from binary format (legacy Altium versions).

        Binary format has multiple possible record structures depending on
        Altium Designer version:
        - Type 0x04: Standard track record
        - Type 0x0B: Extended track record with net info

        Record header: 4 bytes record type + length
        """
        pos = 0

        # Try to detect format by checking for record length markers
        while pos + 4 < len(track_data):
            try:
                # Read record header
                header = struct.unpack('<I', track_data[pos:pos+4])[0]

                # Check if this looks like a record type marker
                record_type = header & 0xFF
                record_len = (header >> 8) & 0xFFFFFF

                # Validate record length
                if record_len == 0 or record_len > 500 or pos + 4 + record_len > len(track_data):
                    # Try alternate interpretation - fixed size records
                    record_len = 45  # Common track record size
                    if pos + record_len > len(track_data):
                        pos += 1
                        continue

                record = track_data[pos+4:pos+4+record_len]

                # Parse based on record type (track = 4 or 0x04)
                if record_type == 4 and len(record) >= 35:
                    # Standard track record structure:
                    # Bytes 0-1: Layer (little-endian short)
                    # Bytes 2-3: Net index
                    # Bytes 4-7: Unknown
                    # Bytes 8-11: X1 (internal units, 1/10000 mil)
                    # Bytes 12-15: Y1
                    # Bytes 16-19: X2
                    # Bytes 20-23: Y2
                    # Bytes 24-27: Width

                    layer = struct.unpack('<H', record[0:2])[0]
                    net_idx = struct.unpack('<h', record[2:4])[0]
                    x1 = struct.unpack('<i', record[8:12])[0] * INTERNAL_TO_MM
                    y1 = struct.unpack('<i', record[12:16])[0] * INTERNAL_TO_MM
                    x2 = struct.unpack('<i', record[16:20])[0] * INTERNAL_TO_MM
                    y2 = struct.unpack('<i', record[20:24])[0] * INTERNAL_TO_MM
                    width = struct.unpack('<i', record[24:28])[0] * INTERNAL_TO_MM

                    # Validate and add track
                    if 0 < width < 100 and layer <= 74:
                        trace = AltiumTrace(
                            x1_mm=x1,
                            y1_mm=y1,
                            x2_mm=x2,
                            y2_mm=y2,
                            width_mm=width,
                            layer=layer,
                            net_index=net_idx,
                        )
                        data.traces.append(trace)

                pos += 4 + record_len

            except struct.error:
                pos += 1
                continue

        # If binary parsing got very few results, try the simple fixed-size approach
        if len(data.traces) < 10:
            self._parse_tracks_simple_binary(track_data, data)

    def _parse_tracks_simple_binary(self, track_data: bytes, data: AltiumBoardData) -> None:
        """Simple binary parsing fallback - scan for coordinate patterns.

        This is a last resort that looks for plausible coordinate sequences
        in the binary data.
        """
        # Track records are typically 45-50 bytes
        # Look for patterns that look like tracks
        min_record_size = 35

        for offset in [8, 10, 12, 14]:  # Try different starting offsets
            pos = offset
            found_tracks = []

            while pos + min_record_size <= len(track_data):
                try:
                    # Try to parse as coordinate block
                    x1 = struct.unpack('<i', track_data[pos:pos+4])[0] * INTERNAL_TO_MM
                    y1 = struct.unpack('<i', track_data[pos+4:pos+8])[0] * INTERNAL_TO_MM
                    x2 = struct.unpack('<i', track_data[pos+8:pos+12])[0] * INTERNAL_TO_MM
                    y2 = struct.unpack('<i', track_data[pos+12:pos+16])[0] * INTERNAL_TO_MM
                    width = struct.unpack('<i', track_data[pos+16:pos+20])[0] * INTERNAL_TO_MM

                    # Check if values are plausible (board < 1m x 1m)
                    coords_valid = all(abs(c) < 1000 for c in [x1, y1, x2, y2])
                    width_valid = 0.01 < width < 50  # 0.01mm to 50mm trace width

                    if coords_valid and width_valid:
                        layer = track_data[pos+20] if pos+20 < len(track_data) else 1
                        if layer > 74:
                            layer = 1

                        found_tracks.append(AltiumTrace(
                            x1_mm=x1,
                            y1_mm=y1,
                            x2_mm=x2,
                            y2_mm=y2,
                            width_mm=width,
                            layer=layer,
                        ))

                    pos += min_record_size

                except struct.error:
                    pos += 1

            # If this offset found more tracks, use it
            if len(found_tracks) > len(data.traces):
                data.traces = found_tracks

    def _parse_vias(self, ole: olefile.OleFileIO, data: AltiumBoardData) -> None:
        """Parse vias from Vias6 stream."""
        try:
            if ole.exists(['Vias6', 'Data']):
                via_data = ole.openstream(['Vias6', 'Data']).read()
                records = self._parse_pipe_delimited(via_data)

                for record in records:
                    x = self._parse_mil_value(record.get('X', '0')) * MIL_TO_MM
                    y = self._parse_mil_value(record.get('Y', '0')) * MIL_TO_MM
                    drill = self._parse_mil_value(record.get('HOLESIZE', '0')) * MIL_TO_MM
                    size = self._parse_mil_value(record.get('SIZE', '0')) * MIL_TO_MM

                    # Extract layer span for via type classification
                    start_layer = int(record.get('STARTLAYER', '1') or '1')
                    end_layer = int(record.get('ENDLAYER', '32') or '32')

                    if size > 0:
                        via = AltiumVia(
                            x_mm=x,
                            y_mm=y,
                            drill_mm=drill,
                            size_mm=size,
                            start_layer=start_layer,
                            end_layer=end_layer,
                        )
                        data.vias.append(via)

        except Exception as e:
            data.warnings.append(f"Failed to parse vias: {e}")

    def _parse_pads(self, ole: olefile.OleFileIO, data: AltiumBoardData) -> None:
        """Parse pads from Pads6 stream."""
        try:
            if ole.exists(['Pads6', 'Data']):
                pad_data = ole.openstream(['Pads6', 'Data']).read()
                records = self._parse_pipe_delimited(pad_data)

                for record in records:
                    x = self._parse_mil_value(record.get('X', '0')) * MIL_TO_MM
                    y = self._parse_mil_value(record.get('Y', '0')) * MIL_TO_MM
                    width = self._parse_mil_value(record.get('XSIZE', '0')) * MIL_TO_MM
                    height = self._parse_mil_value(record.get('YSIZE', '0')) * MIL_TO_MM
                    shape = record.get('SHAPE', 'ROUND')
                    layer = self._parse_int(record.get('LAYER', '1'))

                    if width > 0:
                        pad = AltiumPad(
                            x_mm=x,
                            y_mm=y,
                            width_mm=width,
                            height_mm=height if height > 0 else width,
                            shape=shape,
                            layer=layer,
                            pin_designator=record.get('NAME', ''),
                        )
                        data.pads.append(pad)

        except Exception as e:
            data.warnings.append(f"Failed to parse pads: {e}")

    def _parse_arcs(self, ole: olefile.OleFileIO, data: AltiumBoardData) -> None:
        """Parse arcs from Arcs6 stream."""
        try:
            if ole.exists(['Arcs6', 'Data']):
                arc_data = ole.openstream(['Arcs6', 'Data']).read()
                records = self._parse_pipe_delimited(arc_data)

                for record in records:
                    cx = self._parse_mil_value(record.get('LOCATION.X', '0')) * MIL_TO_MM
                    cy = self._parse_mil_value(record.get('LOCATION.Y', '0')) * MIL_TO_MM
                    radius = self._parse_mil_value(record.get('RADIUS', '0')) * MIL_TO_MM
                    start_angle = self._parse_float(record.get('STARTANGLE', '0'))
                    end_angle = self._parse_float(record.get('ENDANGLE', '0'))
                    width = self._parse_mil_value(record.get('WIDTH', '0')) * MIL_TO_MM
                    layer = self._parse_int(record.get('LAYER', '1'))

                    if radius > 0:
                        arc = AltiumArc(
                            cx_mm=cx,
                            cy_mm=cy,
                            radius_mm=radius,
                            start_angle=start_angle,
                            end_angle=end_angle,
                            width_mm=width,
                            layer=layer,
                        )
                        data.arcs.append(arc)

        except Exception as e:
            data.warnings.append(f"Failed to parse arcs: {e}")

    def _parse_rules(self, ole: olefile.OleFileIO, data: AltiumBoardData) -> None:
        """Parse design rules from Rules6 stream."""
        try:
            if ole.exists(['Rules6', 'Data']):
                rules_data = ole.openstream(['Rules6', 'Data']).read()
                records = self._parse_pipe_delimited(rules_data)

                for record in records:
                    rule_kind = record.get('RULEKIND', '')
                    rule_name = record.get('NAME', '')

                    if rule_kind and rule_name:
                        data.design_rules[rule_name] = {
                            'kind': rule_kind,
                            'enabled': record.get('ENABLED', 'TRUE') == 'TRUE',
                            'priority': self._parse_int(record.get('PRIORITY', '1')),
                            **{k: v for k, v in record.items()
                               if k not in ['RULEKIND', 'NAME', 'ENABLED', 'PRIORITY']}
                        }

        except Exception as e:
            data.warnings.append(f"Failed to parse rules: {e}")

    def _parse_differential_pairs(self, ole: olefile.OleFileIO, data: AltiumBoardData) -> None:
        """Parse differential pairs from DifferentialPairs6 stream."""
        try:
            if ole.exists(['DifferentialPairs6', 'Data']):
                dp_data = ole.openstream(['DifferentialPairs6', 'Data']).read()
                records = self._parse_pipe_delimited(dp_data)

                for record in records:
                    name = record.get('NAME', '')
                    if name:
                        data.differential_pairs.append({
                            'name': name,
                            'positive_net': record.get('POSITIVENETNAME', ''),
                            'negative_net': record.get('NEGATIVENETNAME', ''),
                        })

        except Exception as e:
            data.warnings.append(f"Failed to parse differential pairs: {e}")

    def _estimate_footprint_size(self, comp: AltiumComponent) -> float:
        """Estimate component footprint size based on component type and designator.

        Uses component designator prefix and package/footprint info to estimate
        the physical size for bounding box calculations.

        Args:
            comp: AltiumComponent to estimate size for

        Returns:
            Estimated footprint diagonal size in mm
        """
        # Default size for unknown components
        default_size = 5.0  # mm

        # Reference designator patterns and typical sizes (in mm)
        # These are rough estimates based on common package sizes
        ref_des_sizes = {
            'C': 2.0,    # Capacitors (0402-1206)
            'R': 2.0,    # Resistors (0402-1206)
            'L': 3.0,    # Inductors
            'D': 3.0,    # Diodes
            'Q': 4.0,    # Transistors
            'U': 10.0,   # ICs (varies widely, use medium estimate)
            'J': 8.0,    # Connectors
            'P': 8.0,    # Connectors (alt)
            'SW': 6.0,   # Switches
            'F': 3.0,    # Fuses
            'FB': 2.0,   # Ferrite beads
            'Y': 5.0,    # Crystals
            'X': 5.0,    # Crystals (alt)
            'T': 8.0,    # Transformers
            'BT': 15.0,  # Batteries
            'LED': 3.0,  # LEDs
            'TP': 1.5,   # Test points
            'M': 10.0,   # Motors/modules
        }

        # Extract reference designator prefix  # type: ignore[attr-defined]
        ref_des = comp.designator.upper() if comp.designator else ''  # type: ignore[attr-defined]
        ref_prefix = ''.join(c for c in ref_des if c.isalpha())

        # Try to match prefix with known sizes
        estimated_size = default_size
        for prefix, size in ref_des_sizes.items():
            if ref_prefix.startswith(prefix):
                estimated_size = size
                break

        # Check package/footprint name for additional hints  # type: ignore[attr-defined]
        footprint = (comp.footprint or comp.package_name or '').upper()  # type: ignore[attr-defined]

        # Large package indicators
        if any(x in footprint for x in ['BGA', 'QFN', 'QFP', 'TQFP', 'LQFP']):
            # BGA/QFP packages can be large
            if 'BGA' in footprint:
                estimated_size = max(estimated_size, 15.0)
            else:
                estimated_size = max(estimated_size, 10.0)

        # Small SMD packages
        if any(x in footprint for x in ['0201', '0402', '0603']):
            estimated_size = min(estimated_size, 2.0)
        elif '0805' in footprint or '1206' in footprint:
            estimated_size = min(estimated_size, 3.5)

        # SOT packages
        if 'SOT' in footprint:
            if 'SOT23' in footprint:
                estimated_size = 3.0
            elif 'SOT223' in footprint:
                estimated_size = 7.0
            else:
                estimated_size = 4.0

        # DIP packages
        if 'DIP' in footprint:
            estimated_size = 12.0

        # SOIC packages
        if 'SOIC' in footprint or 'SOP' in footprint:
            estimated_size = 8.0

        # Connector packages tend to be larger
        if 'CONN' in footprint or 'HDR' in footprint:
            estimated_size = 10.0

        return estimated_size

    def _parse_mil_value(self, value: str) -> float:
        """Parse a value in mils (e.g., '100mil' or '100')."""
        if not value:
            return 0.0
        value = value.replace('mil', '').strip()
        try:
            return float(value)
        except ValueError:
            return 0.0

    def _parse_float(self, value: str) -> float:
        """Parse a float value, handling scientific notation."""
        if not value:
            return 0.0
        try:
            return float(value)
        except ValueError:
            return 0.0

    def _parse_int(self, value: str) -> int:
        """Parse an integer value."""
        if not value:
            return 0
        try:
            return int(value)
        except ValueError:
            return 0


class AltiumSchematicParser:
    """Parser for Altium .SchDoc files.

    Extracts:
    - Components with reference, value, part number
    - Nets and connectivity
    - Power symbols
    - Sheet properties

    Usage:
        parser = AltiumSchematicParser()
        data = parser.parse("sheet.SchDoc")
        print(f"Found {len(data.components)} components")
    """

    # Altium schematic record types
    RECORD_TYPES = {
        1: "COMPONENT",
        2: "PIN",
        3: "IEEE_SYMBOL",
        4: "LABEL",
        5: "BEZIER",
        6: "POLYLINE",
        7: "POLYGON",
        8: "ELLIPSE",
        9: "PIECHART",
        10: "ROUND_RECTANGLE",
        11: "ELLIPTICAL_ARC",
        12: "ARC",
        13: "LINE",
        14: "RECTANGLE",
        15: "SHEET_SYMBOL",
        16: "SHEET_ENTRY",
        17: "POWER_PORT",
        18: "PORT",
        25: "NET_LABEL",
        26: "BUS",
        27: "WIRE",
        28: "TEXT_FRAME",
        29: "JUNCTION",
        30: "IMAGE",
        31: "HEADER",
        32: "SHEET_NAME",
        33: "FILE_NAME",
        34: "DESIGNATOR",
        37: "BUS_ENTRY",
        39: "TEMPLATE",
        41: "PARAMETER",
        43: "WARNING_SIGN",
        44: "IMPLEMENTATION_LIST",
        45: "IMPLEMENTATION",
        46: "RECORD_46",
        47: "RECORD_47",
        48: "RECORD_48",
    }

    def __init__(self):
        if not HAS_OLEFILE:
            raise ImportError("olefile library required for Altium parsing. Install with: pip install olefile")

    def parse(self, file_path: str) -> AltiumSchematicData:
        """Parse Altium SchDoc file.

        Args:
            file_path: Path to .SchDoc file

        Returns:
            AltiumSchematicData with components and nets
        """  # type: ignore[assignment]
        file_path = Path(file_path)  # type: ignore[assignment]
  # type: ignore[attr-defined]
        if not file_path.exists():  # type: ignore[attr-defined]
            raise FileNotFoundError(f"SchDoc file not found: {file_path}")

        data = AltiumSchematicData(source_file=str(file_path))

        try:
            ole = olefile.OleFileIO(str(file_path))

            # Main schematic data is in FileHeader stream
            if ole.exists(['FileHeader']):
                header_data = ole.openstream(['FileHeader']).read()
                self._parse_fileheader(header_data, data)

            ole.close()

            logger.info(f"Parsed SchDoc: {len(data.components)} components, "
                       f"{len(data.nets)} nets")

            return data

        except Exception as e:
            logger.error(f"Failed to parse SchDoc: {e}")
            raise ValueError(f"SchDoc parse error: {str(e)}")

    def _parse_fileheader(self, raw_data: bytes, data: AltiumSchematicData) -> None:
        """Parse FileHeader stream containing schematic records.

        Altium schematic records use OwnerIndex to reference parent records.
        The OwnerIndex value points to (record_index - 1) of the parent.
        """
        pos = 0
        record_index = 0

        # First pass: collect all records with their indices
        components_by_idx: Dict[int, AltiumComponent] = {}
        designators: List[Tuple[int, str]] = []  # (owner_idx, text)
        parameters: List[Tuple[int, str, str]] = []  # (owner_idx, name, value)

        while pos < len(raw_data):
            # Record format: <length 4 bytes><data>
            if pos + 4 > len(raw_data):
                break

            record_len = struct.unpack('<I', raw_data[pos:pos+4])[0]
            pos += 4

            if record_len == 0 or pos + record_len > len(raw_data):
                break

            record_data = raw_data[pos:pos+record_len]
            pos += record_len

            # Parse pipe-delimited fields
            try:
                text = record_data.decode('utf-8', errors='ignore')
                fields = self._parse_record_fields(text)

                record_type = self._parse_int(fields.get('RECORD', '0'))

                if record_type == 1:  # COMPONENT
                    # Store component by record index
                    loc_x = self._parse_coord(fields.get('LOCATION.X', '0'))
                    loc_y = self._parse_coord(fields.get('LOCATION.Y', '0'))

                    component = AltiumComponent(
                        reference='',  # Will be filled from DESIGNATOR record
                        unique_id=fields.get('UNIQUEID', ''),
                        library_ref=fields.get('LIBREFERENCE', ''),
                        description=fields.get('COMPONENTDESCRIPTION', ''),
                        x_mm=loc_x * 0.0254,  # Convert mils to mm
                        y_mm=loc_y * 0.0254,
                    )
                    components_by_idx[record_index] = component

                elif record_type == 34:  # DESIGNATOR
                    owner_idx = self._parse_int(fields.get('OWNERINDEX', '-1'))
                    designator_text = fields.get('TEXT', fields.get('Text', '')).strip('"')
                    if owner_idx >= 0 and designator_text:
                        designators.append((owner_idx, designator_text))

                elif record_type == 41:  # PARAMETER
                    owner_idx = self._parse_int(fields.get('OWNERINDEX', '-1'))
                    param_name = fields.get('NAME', fields.get('Name', '')).upper()
                    param_value = fields.get('TEXT', fields.get('Text', '')).strip('"')
                    if owner_idx >= 0 and param_name:
                        parameters.append((owner_idx, param_name, param_value))

                elif record_type == 17:  # POWER_PORT
                    power_name = fields.get('TEXT', fields.get('Text', '')).strip('"')
                    if power_name:
                        data.power_symbols.append({
                            'name': power_name,
                            'style': fields.get('STYLE', ''),
                            'is_ground': power_name.upper() in ['GND', 'VSS', 'EARTH', 'GROUND'],
                        })
                        # Add as net
                        if not any(n.name == power_name for n in data.nets):
                            data.nets.append(AltiumNet(name=power_name))

                elif record_type == 25:  # NET_LABEL
                    net_name = fields.get('TEXT', fields.get('Text', '')).strip('"')
                    if net_name and not any(n.name == net_name for n in data.nets):
                        data.nets.append(AltiumNet(name=net_name))

                elif record_type == 31:  # HEADER (sheet properties)
                    data.title = fields.get('SHEETNAME', fields.get('SheetName', ''))

            except Exception as e:
                data.warnings.append(f"Failed to parse record {record_index}: {e}")

            record_index += 1

        # Second pass: link designators and parameters to components
        # OwnerIndex points to (record_index - 1), so we use owner_idx + 1
        for owner_idx, designator_text in designators:
            comp = components_by_idx.get(owner_idx + 1)
            if comp:
                comp.reference = designator_text

        for owner_idx, param_name, param_value in parameters:
            comp = components_by_idx.get(owner_idx + 1)
            if comp:
                if param_name == 'VALUE':
                    comp.value = param_value
                elif param_name in ['PARTNUMBER', 'MPN', 'MANUFACTURER_PART_NUMBER']:
                    comp.part_number = param_value
                elif param_name in ['MANUFACTURER', 'MFR']:
                    comp.manufacturer = param_value
                elif param_name == 'DESCRIPTION' and not comp.description:
                    comp.description = param_value

        # Add components with valid designators to result
        for comp in components_by_idx.values():
            if comp.reference:  # Only add components with designators
                data.components.append(comp)

    def _parse_coord(self, value: str) -> float:
        """Parse coordinate value (may be in mils or internal units)."""
        try:
            return float(value)
        except ValueError:
            return 0.0

    def _parse_int(self, value: str) -> int:
        """Parse integer value."""
        if not value:
            return 0
        try:
            return int(value)
        except ValueError:
            return 0

    def _parse_record_fields(self, text: str) -> Dict[str, str]:
        """Parse pipe-delimited fields from record text.

        Returns a case-insensitive dictionary for field lookups.
        """
        fields = CaseInsensitiveDict()
        for part in text.split('|'):
            if '=' in part:
                key, value = part.split('=', 1)
                fields[key.strip()] = value.strip()
        return fields


class CaseInsensitiveDict(dict):
    """Dictionary with case-insensitive key lookup."""

    def __getitem__(self, key):
        return super().__getitem__(key.upper())

    def __setitem__(self, key, value) -> None:
        super().__setitem__(key.upper(), value)

    def get(self, key: str, default: Any = None) -> Any:
        return super().get(key.upper(), default)

    def __contains__(self, key):
        return super().__contains__(key.upper())


class AltiumProjectParser:
    """Parser for Altium project files and packages.

    Handles:
    - .PrjPcb project files
    - .zip archives containing Altium files
    - Automatic extraction of schematics, PCB, and BOM

    Usage:
        parser = AltiumProjectParser()
        data = parser.parse_package("/path/to/altium_export.zip")
    """

    def __init__(self):
        if not HAS_OLEFILE:
            raise ImportError("olefile library required for Altium parsing")

        self.pcb_parser = AltiumPcbParser()
        self.schematic_parser = AltiumSchematicParser()

    def parse_directory(self, dir_path: str) -> Dict[str, Any]:
        """Parse all Altium files in a directory.

        Args:
            dir_path: Path to directory containing Altium files

        Returns:
            Dict with 'pcb', 'schematics', 'bom_data' keys
        """
        dir_path_p = Path(dir_path)
        result: dict[str, Any] = {
            'pcb': None,
            'schematics': [],
            'bom_data': None,
            'project_name': None,
        }

        if not dir_path_p.exists():
            raise FileNotFoundError(f"Directory not found: {dir_path_p}")

        # Find project file
        prjpcb_files = list(dir_path_p.glob("*.PrjPcb"))
        if prjpcb_files:
            result['project_name'] = prjpcb_files[0].stem

        # Parse PcbDoc
        pcbdoc_files = list(dir_path_p.glob("*.PcbDoc"))
        if pcbdoc_files:
            try:
                result['pcb'] = self.pcb_parser.parse(str(pcbdoc_files[0]))
            except Exception as e:
                logger.warning(f"Failed to parse PcbDoc: {e}")

        # Parse SchDoc files
        schdoc_files = list(dir_path_p.glob("*.SchDoc"))
        for schdoc in schdoc_files:
            try:
                sch_data = self.schematic_parser.parse(str(schdoc))
                result['schematics'].append(sch_data)
            except Exception as e:
                logger.warning(f"Failed to parse SchDoc {schdoc.name}: {e}")

        # Extract BOM from PCB components
        if result['pcb']:
            result['bom_data'] = self._extract_bom_from_pcb(result['pcb'])  # type: ignore[arg-type]

        return result

    def _extract_bom_from_pcb(self, pcb_data: AltiumBoardData) -> List[Dict[str, Any]]:  # type: ignore[arg-type]
        """Extract BOM data from parsed PCB."""
        bom = []

        for comp in pcb_data.components:
            bom.append({
                'reference': comp.reference,
                'value': comp.value,
                'footprint': comp.footprint,
                'description': comp.description,
                'part_number': comp.part_number,
                'manufacturer': comp.manufacturer,
            })

        return bom


def get_format_benefits() -> Dict[str, Dict[str, Any]]:
    """Get benefits and limitations of each file format for AI review.

    Returns dict with format name -> {benefits: [], limitations: [], recommended_for: []}
    """
    return {
        'Altium PcbDoc': {
            'benefits': [
                'Complete PCB design data including all geometry',
                'Full net connectivity with electrical info',
                'Design rules embedded in file',
                'Differential pair definitions',
                '3D component models included',
                'Layer stackup information',
                'Rich component metadata (MPN, manufacturer)',
            ],
            'limitations': [
                'Binary OLE format requires specialized parsing',
                'Track data is compressed binary (harder to parse)',
                'Large file sizes due to 3D models',
                'Closed format with limited documentation',
            ],
            'recommended_for': [
                'Complete design review',
                'DFM analysis',
                'Signal integrity analysis with full geometry',
                'Design rule verification',
            ],
        },
        'Altium SchDoc': {
            'benefits': [
                'Complete schematic hierarchy',
                'Component parameters and part numbers',
                'Net labels and connectivity',
                'Power/ground symbol identification',
                'Design intent information',
            ],
            'limitations': [
                'Binary OLE format',
                'Less useful for physical PCB analysis',
                'No layer or routing information',
            ],
            'recommended_for': [
                'BOM extraction',
                'Component selection review',
                'Schematic-layout cross-check',
            ],
        },
        'ODB++': {
            'benefits': [
                'Industry standard interchange format',
                'Text-based, well-documented',
                'Complete manufacturing data',
                'Layer-by-layer geometry',
                'Netlist with connectivity',
                'Component placement',
            ],
            'limitations': [
                'No design rules included',
                'No schematic data',
                'Separate from design intent',
            ],
            'recommended_for': [
                'Manufacturing review',
                'DFM analysis',
                'Layer-by-layer verification',
            ],
        },
        'Gerber': {
            'benefits': [
                'Universal format - all EDA tools export',
                'Simple, well-documented format',
                'Individual layer files for targeted analysis',
                'Gerber X2 includes net names',
            ],
            'limitations': [
                'No connectivity info (except X2)',
                'Separate files per layer',
                'No component data (except centroid)',
                'No 3D or stackup info',
            ],
            'recommended_for': [
                'Quick visual check',
                'Manufacturing output verification',
                'Legacy design import',
            ],
        },
    }

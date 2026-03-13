"""Enhanced Gerber file parser for PCB layout data extraction.

Supports full RS-274X specification including:
- Standard apertures (C, R, O, P)
- Aperture macros with primitives and variables
- Arc interpolation (G02/G03) with single/multi quadrant modes
- Step-and-repeat (SR) for array replication
- Region polygons (G36/G37)
- Gerber X2 attributes (%TF, %TA, %TO, %TD)
"""
from __future__ import annotations

import logging
import math
import re
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


class ApertureType(Enum):
    """Gerber aperture types"""
    CIRCLE = "C"
    RECTANGLE = "R"
    OBROUND = "O"
    POLYGON = "P"
    MACRO = "M"


class MacroPrimitiveType(Enum):
    """Aperture macro primitive types"""
    COMMENT = 0
    CIRCLE = 1
    VECTOR_LINE = 20
    CENTER_LINE = 21
    OUTLINE = 4
    POLYGON = 5
    MOIRE = 6
    THERMAL = 7


@dataclass
class MacroPrimitive:
    """A primitive within an aperture macro"""
    primitive_type: MacroPrimitiveType
    exposure: int  # 0=off, 1=on
    parameters: List[float]  # Evaluated parameters


@dataclass
class ApertureMacro:
    """Aperture macro definition with primitives and variables"""
    name: str
    primitives: List[str] = field(default_factory=list)  # Raw primitive definitions

    def evaluate(self, params: List[float]) -> List[MacroPrimitive]:
        """
        Evaluate the macro with given parameters ($1, $2, etc.)

        Args:
            params: Parameter values to substitute for $1, $2, etc.

        Returns:
            List of evaluated MacroPrimitive objects
        """
        result = []

        for primitive_def in self.primitives:
            # Substitute variables ($1, $2, etc.)
            evaluated = primitive_def
            for i, param in enumerate(params, 1):
                evaluated = evaluated.replace(f'${i}', str(param))

            # Parse the primitive
            try:
                parts = [p.strip() for p in evaluated.split(',')]
                prim_type = int(parts[0])

                # Skip comments
                if prim_type == 0:
                    continue

                # Evaluate remaining parameters (may contain expressions)
                prim_params = []
                for p in parts[1:]:
                    prim_params.append(self._evaluate_expression(p))

                exposure = 1  # Default on
                if prim_type in [1, 4, 5, 20, 21]:  # Primitives with exposure
                    if prim_params:
                        exposure = int(prim_params[0])
                        prim_params = prim_params[1:]

                result.append(MacroPrimitive(
                    primitive_type=MacroPrimitiveType(prim_type) if prim_type in [0, 1, 4, 5, 6, 7, 20, 21] else MacroPrimitiveType.CIRCLE,
                    exposure=exposure,
                    parameters=prim_params
                ))
            except (ValueError, KeyError) as e:
                # Log macro primitive parse error
                logger.debug(f"Skipped malformed macro primitive: {e}")
                continue

        return result

    def _evaluate_expression(self, expr: str) -> float:
        """Evaluate a simple arithmetic expression"""
        expr = expr.strip()

        # Handle simple number
        try:
            return float(expr)
        except ValueError:
            pass

        # Handle expressions with x (multiply), +, -, /
        # Replace x with * for eval
        expr = expr.replace('x', '*').replace('X', '*')

        try:
            # Use a safe eval with only math operations
            allowed: dict[str, Any] = {'__builtins__': {}}
            return float(eval(expr, allowed, {}))
        except Exception as e:
            logger.debug(f"Failed to evaluate expression '{expr}': {e}")
            return 0.0


@dataclass
class Aperture:
    """Gerber aperture definition"""
    code: int
    aperture_type: ApertureType
    params: List[float]  # Diameter, width, height, etc.
    macro_name: Optional[str] = None  # For macro-based apertures
    hole_diameter: Optional[float] = None  # Optional hole in aperture

    @property
    def width_mm(self) -> float:
        if self.params:
            return self.params[0]
        return 0

    @property
    def height_mm(self) -> float:
        if len(self.params) > 1:
            return self.params[1]
        return self.width_mm

    def get_bounding_box(self) -> Tuple[float, float]:
        """Get bounding box dimensions (width, height) for this aperture"""
        if self.aperture_type == ApertureType.CIRCLE:
            diameter = self.params[0] if self.params else 0
            return (diameter, diameter)
        elif self.aperture_type == ApertureType.RECTANGLE:
            w = self.params[0] if self.params else 0
            h = self.params[1] if len(self.params) > 1 else w
            return (w, h)
        elif self.aperture_type == ApertureType.OBROUND:
            w = self.params[0] if self.params else 0
            h = self.params[1] if len(self.params) > 1 else w
            return (w, h)
        elif self.aperture_type == ApertureType.POLYGON:
            # Polygon: outer_diameter, vertices, rotation
            diameter = self.params[0] if self.params else 0
            return (diameter, diameter)
        return (0, 0)


@dataclass
class StepRepeat:
    """Step-and-repeat block for array replication"""
    x_repeats: int
    y_repeats: int
    x_step: float  # Step distance in X (mm)
    y_step: float  # Step distance in Y (mm)
    features: List[Any] = field(default_factory=list)  # Features to replicate


@dataclass
class GerberAttributes:
    """Gerber X2 file and aperture attributes"""
    # File attributes (%TF)
    file_function: Optional[str] = None  # Copper, SolderMask, etc.
    file_polarity: Optional[str] = None  # Positive, Negative
    part: Optional[str] = None  # Single, Array
    generation_software: Optional[str] = None
    creation_date: Optional[str] = None
    project_id: Optional[str] = None

    # Object attributes (%TO) - per feature
    net_name: Optional[str] = None
    pin_number: Optional[str] = None
    component_ref: Optional[str] = None

    # Custom attributes
    custom: Dict[str, str] = field(default_factory=dict)


@dataclass
class GerberTrace:
    """Trace extracted from Gerber"""
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    width_mm: float
    aperture_code: int

    @property
    def length_mm(self) -> float:
        return math.sqrt((self.end_x - self.start_x)**2 + (self.end_y - self.start_y)**2)


@dataclass
class GerberPad:
    """Pad/flash extracted from Gerber"""
    x: float
    y: float
    aperture_code: int
    width_mm: float
    height_mm: float
    shape: ApertureType


@dataclass
class GerberArc:
    """Arc extracted from Gerber"""
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    center_x: float
    center_y: float
    width_mm: float
    clockwise: bool


@dataclass
class GerberData:
    """Complete Gerber parsed data"""
    source_file: str
    format_spec: Optional[str] = None  # RS-274X, RS-274D

    # Coordinate format
    integer_digits: int = 2
    decimal_digits: int = 5
    units: str = "mm"  # mm or inch
    leading_zeros: str = "omit"  # omit, keep
    trailing_zeros: str = "omit"  # omit, keep
    absolute_coords: bool = True  # True=absolute, False=incremental

    # Apertures and macros
    apertures: Dict[int, Aperture] = field(default_factory=dict)
    macros: Dict[str, ApertureMacro] = field(default_factory=dict)

    # Features
    traces: List[GerberTrace] = field(default_factory=list)
    pads: List[GerberPad] = field(default_factory=list)
    arcs: List[GerberArc] = field(default_factory=list)
    regions: List[List[Tuple[float, float]]] = field(default_factory=list)  # Polygon regions

    # Step-and-repeat blocks
    step_repeats: List[StepRepeat] = field(default_factory=list)

    # Gerber X2 attributes
    attributes: GerberAttributes = field(default_factory=GerberAttributes)

    # Bounding box
    min_x: float = float('inf')
    max_x: float = float('-inf')
    min_y: float = float('inf')
    max_y: float = float('-inf')

    # Layer info (inferred from filename or attributes)
    layer_type: Optional[str] = None  # copper, mask, silk, paste
    layer_side: Optional[str] = None  # top, bottom, inner
    layer_number: Optional[int] = None  # For inner layers

    # Statistics
    trace_count: int = 0
    pad_count: int = 0
    arc_count: int = 0
    region_count: int = 0
    total_trace_length_mm: float = 0
    total_arc_length_mm: float = 0

    # Parsing metadata
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def width_mm(self) -> float:
        if self.min_x != float('inf') and self.max_x != float('-inf'):
            return self.max_x - self.min_x
        return 0

    @property
    def height_mm(self) -> float:
        if self.min_y != float('inf') and self.max_y != float('-inf'):
            return self.max_y - self.min_y
        return 0

    @property
    def area_mm2(self) -> float:
        return self.width_mm * self.height_mm

    def get_all_features_count(self) -> int:
        """Get total number of geometric features"""
        return self.trace_count + self.pad_count + self.arc_count + self.region_count


class GerberParser:
    """
    Enhanced Gerber RS-274X parser.

    Extracts:
    - Traces with width and coordinates
    - Pads with shape and size
    - Arcs
    - Copper pour regions
    - Layer type inference from filename

    Usage:
        parser = GerberParser()
        data = parser.parse("copper_top.gbr")
        print(f"Found {len(data.traces)} traces")
    """

    # Layer type patterns for filename inference
    LAYER_PATTERNS = {
        'copper_top': [r'\.gtl$', r'top.*copper', r'copper.*top', r'f\.cu', r'top\.cu'],
        'copper_bottom': [r'\.gbl$', r'bottom.*copper', r'copper.*bottom', r'b\.cu', r'bot\.cu'],
        'copper_inner': [r'\.g[0-9]+$', r'inner', r'in[0-9]+\.cu', r'\.gp[0-9]+'],
        'solder_mask_top': [r'\.gts$', r'mask.*top', r'top.*mask', r'f\.mask'],
        'solder_mask_bottom': [r'\.gbs$', r'mask.*bot', r'bot.*mask', r'b\.mask'],
        'silkscreen_top': [r'\.gto$', r'silk.*top', r'top.*silk', r'f\.silks'],
        'silkscreen_bottom': [r'\.gbo$', r'silk.*bot', r'bot.*silk', r'b\.silks'],
        'paste_top': [r'\.gtp$', r'paste.*top', r'top.*paste', r'f\.paste'],
        'paste_bottom': [r'\.gbp$', r'paste.*bot', r'bot.*paste', r'b\.paste'],
        'drill': [r'\.drl$', r'\.xln$', r'drill', r'\.exc$'],
        'outline': [r'\.gko$', r'\.gm1$', r'outline', r'edge', r'profile'],
    }

    def __init__(self):
        self.current_aperture: Optional[int] = None
        self.current_x: float = 0
        self.current_y: float = 0
        self.interpolation_mode: str = "linear"  # linear, cw_arc, ccw_arc
        self.quadrant_mode: str = "multi"  # single (G74) or multi (G75)
        self.region_mode: bool = False
        self.region_points: List[Tuple[float, float]] = []

        # Step-and-repeat state
        self.sr_active: bool = False
        self.sr_x_repeats: int = 1
        self.sr_y_repeats: int = 1
        self.sr_x_step: float = 0
        self.sr_y_step: float = 0
        self.sr_features: List[Any] = []

        # Current object attributes (reset with %TD)
        self.current_net: Optional[str] = None
        self.current_component: Optional[str] = None
        self.current_pin: Optional[str] = None

        # Parsing in extended block
        self.in_extended_block: bool = False
        self.extended_buffer: str = ""

    def parse(self, file_path: str) -> GerberData:
        """
        Parse a Gerber file.

        Args:
            file_path: Path to Gerber file

        Returns:
            GerberData with all extracted features
        """  # type: ignore[assignment]
        file_path = Path(file_path)  # type: ignore[assignment]
  # type: ignore[attr-defined]
        if not file_path.exists():  # type: ignore[attr-defined]
            raise FileNotFoundError(f"Gerber file not found: {file_path}")

        data = GerberData(source_file=str(file_path))

        # Infer layer type from filename  # type: ignore[attr-defined]
        self._infer_layer_type(file_path.name, data)  # type: ignore[attr-defined]

        # Read and parse content
        try:
            with open(file_path, encoding='utf-8', errors='ignore') as f:
                content = f.read()

            self._parse_content(content, data)
        except Exception as e:
            data.warnings.append(f"Error parsing Gerber content: {str(e)}")

        # Calculate statistics
        self._calculate_statistics(data)

        return data

    def _infer_layer_type(self, filename: str, data: GerberData) -> None:
        """Infer layer type from filename patterns"""
        filename_lower = filename.lower()

        for layer_type, patterns in self.LAYER_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, filename_lower):
                    parts = layer_type.split('_')
                    data.layer_type = parts[0] if len(parts) > 0 else None

                    if 'top' in layer_type:
                        data.layer_side = 'top'
                    elif 'bottom' in layer_type or 'bot' in layer_type:
                        data.layer_side = 'bottom'
                    elif 'inner' in layer_type:
                        data.layer_side = 'inner'

                    return

    def _parse_content(self, content: str, data: GerberData) -> None:
        """Parse Gerber content"""
        # Reset state
        self.current_aperture = None
        self.current_x = 0
        self.current_y = 0
        self.region_mode = False
        self.region_points = []
        self.sr_active = False
        self.sr_features = []
        self.in_extended_block = False
        self.extended_buffer = ""

        # Detect format
        if '%FS' in content:
            data.format_spec = "RS-274X"
        else:
            data.format_spec = "RS-274D"

        # Pre-process: handle extended commands that span multiple lines
        # Extended commands start with % and end with %
        processed_content = self._preprocess_extended_blocks(content)

        # Parse line by line
        lines = processed_content.replace('\r\n', '\n').replace('\r', '\n').split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            try:
                if line.startswith('%'):
                    # Extended command
                    self._parse_extended_command(line, data)
                else:
                    # Standard command - may contain multiple commands separated by *
                    self._parse_standard_commands(line, data)
            except Exception as e:
                data.warnings.append(f"Error parsing Gerber command '{line[:50]}...': {str(e)}")

    def _preprocess_extended_blocks(self, content: str) -> str:
        """
        Preprocess content to handle extended blocks that span multiple lines.
        Extended blocks start with % and end with %.
        """
        result = []
        in_block = False
        block_buffer = ""

        for char in content:
            if char == '%':
                if in_block:
                    # End of extended block
                    block_buffer += char
                    result.append(block_buffer)
                    result.append('\n')
                    block_buffer = ""
                    in_block = False
                else:
                    # Start of extended block
                    in_block = True
                    block_buffer = char
            elif in_block:
                # Inside extended block - skip newlines
                if char not in '\r\n':
                    block_buffer += char
            else:
                result.append(char)

        return ''.join(result)

    def _parse_standard_commands(self, line: str, data: GerberData) -> None:
        """Parse a line that may contain multiple standard commands separated by *"""
        # Split on * but keep commands intact
        commands = [cmd.strip() for cmd in line.split('*') if cmd.strip()]

        for cmd in commands:
            self._parse_standard_command(cmd, data)

    def _parse_extended_command(self, line: str, data: GerberData) -> None:
        """Parse extended Gerber command (starts with %)"""
        if not line.startswith('%'):
            return

        # Remove % markers
        line = line.strip('%').strip('*')

        # Format specification: FS<LATZ><XnnYnn>
        if line.startswith('FS'):
            self._parse_format_spec(line, data)

        # Units: MO<MM|IN>
        elif line.startswith('MO'):
            if 'MM' in line:
                data.units = 'mm'
            else:
                data.units = 'inch'

        # Aperture macro definition: AM<name>*<primitives>
        elif line.startswith('AM'):
            self._parse_aperture_macro(line, data)

        # Aperture definition: ADD<nn><type>,<params>
        elif line.startswith('AD'):
            self._parse_aperture_definition(line, data)

        # Step-and-repeat: SR[X<repeats>Y<repeats>I<step>J<step>]
        elif line.startswith('SR'):
            self._parse_step_repeat(line, data)

        # File attribute: TF.<attribute>,<value>
        elif line.startswith('TF'):
            self._parse_file_attribute(line, data)

        # Aperture attribute: TA.<attribute>,<value>
        elif line.startswith('TA'):
            self._parse_aperture_attribute(line, data)

        # Object attribute: TO.<attribute>,<value>
        elif line.startswith('TO'):
            self._parse_object_attribute(line, data)

        # Delete attribute: TD[<attribute>]
        elif line.startswith('TD'):
            self._delete_attribute(line, data)

        # Load polarity: LP<D|C>
        elif line.startswith('LP'):
            # D=Dark (positive), C=Clear (negative)
            pass  # Track if needed

        # Load mirroring: LM<N|XY|X|Y>
        elif line.startswith('LM'):
            pass  # Track if needed

        # Load rotation: LR<angle>
        elif line.startswith('LR'):
            pass  # Track if needed

        # Load scaling: LS<factor>
        elif line.startswith('LS'):
            pass  # Track if needed

    def _parse_format_spec(self, line: str, data: GerberData) -> None:
        """Parse format specification command"""
        # Format: FS<L|T><A|I>X<int><dec>Y<int><dec>
        # L=leading zeros omit, T=trailing zeros omit
        # A=absolute, I=incremental

        if 'L' in line[:4]:
            data.leading_zeros = 'omit'
        elif 'T' in line[:4]:
            data.trailing_zeros = 'omit'

        if 'A' in line[:4]:
            data.absolute_coords = True
        elif 'I' in line[:4]:
            data.absolute_coords = False

        match = re.search(r'X(\d)(\d)Y(\d)(\d)', line)
        if match:
            data.integer_digits = int(match.group(1))
            data.decimal_digits = int(match.group(2))

    def _parse_aperture_macro(self, line: str, data: GerberData) -> None:
        """Parse aperture macro definition"""
        # Format: AM<name>*<primitive>*<primitive>*...
        parts = line[2:].split('*')
        if not parts:
            return

        name = parts[0].strip()
        primitives = [p.strip() for p in parts[1:] if p.strip()]

        data.macros[name] = ApertureMacro(name=name, primitives=primitives)

    def _parse_step_repeat(self, line: str, data: GerberData) -> None:
        """Parse step-and-repeat command"""
        # Format: SR[X<nx>Y<ny>I<dx>J<dy>]
        # Empty SR ends the block

        if line == 'SR' or line == 'SR*':
            # End step-and-repeat block
            if self.sr_active and self.sr_features:
                sr = StepRepeat(
                    x_repeats=self.sr_x_repeats,
                    y_repeats=self.sr_y_repeats,
                    x_step=self.sr_x_step,
                    y_step=self.sr_y_step,
                    features=self.sr_features.copy()
                )
                data.step_repeats.append(sr)

                # Apply step-and-repeat: replicate features
                self._apply_step_repeat(sr, data)

            self.sr_active = False
            self.sr_features = []
            return

        # Parse parameters
        x_match = re.search(r'X(\d+)', line)
        y_match = re.search(r'Y(\d+)', line)
        i_match = re.search(r'I([+-]?\d*\.?\d+)', line)
        j_match = re.search(r'J([+-]?\d*\.?\d+)', line)

        self.sr_x_repeats = int(x_match.group(1)) if x_match else 1
        self.sr_y_repeats = int(y_match.group(1)) if y_match else 1

        # Step distances - convert based on units
        scale = 25.4 if data.units == 'inch' else 1.0
        self.sr_x_step = float(i_match.group(1)) * scale if i_match else 0
        self.sr_y_step = float(j_match.group(1)) * scale if j_match else 0

        self.sr_active = True
        self.sr_features = []

    def _apply_step_repeat(self, sr: StepRepeat, data: GerberData) -> None:
        """Apply step-and-repeat by replicating features"""
        # Skip if only 1x1 (no replication needed)
        if sr.x_repeats <= 1 and sr.y_repeats <= 1:
            return

        original_traces = len(data.traces)
        original_pads = len(data.pads)
        original_arcs = len(data.arcs)

        # Replicate (skip 0,0 which is the original)
        for xi in range(sr.x_repeats):
            for yi in range(sr.y_repeats):
                if xi == 0 and yi == 0:
                    continue  # Skip original

                dx = xi * sr.x_step
                dy = yi * sr.y_step

                # Replicate traces
                for i in range(original_traces - len(sr.features), original_traces):
                    if i >= 0 and i < len(data.traces):
                        t = data.traces[i]
                        data.traces.append(GerberTrace(
                            start_x=t.start_x + dx,
                            start_y=t.start_y + dy,
                            end_x=t.end_x + dx,
                            end_y=t.end_y + dy,
                            width_mm=t.width_mm,
                            aperture_code=t.aperture_code
                        ))

                # Replicate pads
                for i in range(original_pads - len(sr.features), original_pads):
                    if i >= 0 and i < len(data.pads):
                        p = data.pads[i]
                        data.pads.append(GerberPad(
                            x=p.x + dx,
                            y=p.y + dy,
                            aperture_code=p.aperture_code,
                            width_mm=p.width_mm,
                            height_mm=p.height_mm,
                            shape=p.shape
                        ))

    def _parse_file_attribute(self, line: str, data: GerberData) -> None:
        """Parse Gerber X2 file attribute"""
        # Format: TF.<attribute>,<value>[,<value>...]
        # or TF<attribute>,<value> (without dot)
        content = line[2:]  # Remove "TF"
        parts = content.split(',')
        if not parts:
            return

        attr_name = parts[0].strip()
        # Normalize: remove leading dot if present for comparison
        attr_name_normalized = attr_name.lstrip('.')

        attr_values = [p.strip() for p in parts[1:]]
        attr_value = ','.join(attr_values) if attr_values else ''

        if attr_name_normalized == 'FileFunction':
            data.attributes.file_function = attr_value
            # Parse layer info from FileFunction
            self._parse_file_function(attr_value, data)
        elif attr_name_normalized == 'FilePolarity':
            data.attributes.file_polarity = attr_value
        elif attr_name_normalized == 'Part':
            data.attributes.part = attr_value
        elif attr_name_normalized == 'GenerationSoftware':
            data.attributes.generation_software = attr_value
        elif attr_name_normalized == 'CreationDate':
            data.attributes.creation_date = attr_value
        elif attr_name_normalized == 'ProjectId':
            data.attributes.project_id = attr_value
        else:
            data.attributes.custom[attr_name] = attr_value

    def _parse_file_function(self, value: str, data: GerberData) -> None:
        """Parse .FileFunction attribute to determine layer type"""
        parts = value.split(',')
        if not parts:
            return

        function = parts[0].lower()

        if function == 'copper':
            data.layer_type = 'copper'
            if len(parts) > 1:
                layer_info = parts[1].lower()
                if 'top' in layer_info or layer_info == 'l1':
                    data.layer_side = 'top'
                elif 'bot' in layer_info:
                    data.layer_side = 'bottom'
                else:
                    data.layer_side = 'inner'
                    # Try to extract layer number
                    match = re.search(r'l(\d+)', layer_info)
                    if match:
                        data.layer_number = int(match.group(1))
        elif function == 'soldermask':
            data.layer_type = 'mask'
            if len(parts) > 1 and 'top' in parts[1].lower():
                data.layer_side = 'top'
            else:
                data.layer_side = 'bottom'
        elif function == 'legend' or function == 'silkscreen':
            data.layer_type = 'silk'
            if len(parts) > 1 and 'top' in parts[1].lower():
                data.layer_side = 'top'
            else:
                data.layer_side = 'bottom'
        elif function == 'paste' or function == 'solderpaste':
            data.layer_type = 'paste'
            if len(parts) > 1 and 'top' in parts[1].lower():
                data.layer_side = 'top'
            else:
                data.layer_side = 'bottom'
        elif function == 'profile' or function == 'outline':
            data.layer_type = 'outline'

    def _parse_aperture_attribute(self, line: str, data: GerberData) -> None:
        """Parse Gerber X2 aperture attribute"""
        # Format: TA.<attribute>,<value>
        # These apply to subsequently defined apertures
        pass  # Store if needed for aperture metadata

    def _parse_object_attribute(self, line: str, data: GerberData) -> None:
        """Parse Gerber X2 object attribute"""
        # Format: TO.<attribute>,<value>
        parts = line[3:].split(',')
        if not parts:
            return

        attr_name = parts[0].strip()
        attr_value = ','.join(p.strip() for p in parts[1:]) if len(parts) > 1 else ''

        if attr_name == '.N':
            self.current_net = attr_value
        elif attr_name == '.P':
            # Pin format: component,pin[,function]
            pin_parts = attr_value.split(',')
            if pin_parts:
                self.current_component = pin_parts[0]
            if len(pin_parts) > 1:
                self.current_pin = pin_parts[1]
        elif attr_name == '.C':
            self.current_component = attr_value

    def _delete_attribute(self, line: str, data: GerberData) -> None:
        """Handle attribute deletion"""
        # Format: TD[<attribute>] - empty means delete all object attributes
        attr = line[2:].strip() if len(line) > 2 else ''

        if not attr or attr == '.N':
            self.current_net = None
        if not attr or attr == '.P':
            self.current_pin = None
        if not attr or attr == '.C':
            self.current_component = None

    def _parse_aperture_definition(self, line: str, data: GerberData) -> None:
        """Parse aperture definition"""
        # Format: ADD<code><type>,<params>
        # Or for macros: ADD<code><macro_name>,<params>

        # First try standard aperture types
        match = re.match(r'ADD?(\d+)([CROP]),?(.*)$', line)
        if match:
            code = int(match.group(1))
            type_char = match.group(2)
            params_str = match.group(3)

            # Parse type
            aperture_type = {
                'C': ApertureType.CIRCLE,
                'R': ApertureType.RECTANGLE,
                'O': ApertureType.OBROUND,
                'P': ApertureType.POLYGON,
            }.get(type_char, ApertureType.CIRCLE)

            # Parse parameters
            params = []
            hole_diameter = None
            if params_str:
                for p in params_str.split('X'):
                    try:
                        params.append(float(p))
                    except ValueError:
                        pass

            # Last parameter might be hole diameter for C, R, O
            if aperture_type in [ApertureType.CIRCLE, ApertureType.RECTANGLE, ApertureType.OBROUND]:
                if aperture_type == ApertureType.CIRCLE and len(params) > 1:
                    hole_diameter = params[-1]
                    params = params[:-1]
                elif aperture_type in [ApertureType.RECTANGLE, ApertureType.OBROUND] and len(params) > 2:
                    hole_diameter = params[-1]
                    params = params[:-1]

            # Convert to mm if needed
            scale = 25.4 if data.units == 'inch' else 1.0
            params = [p * scale for p in params]
            if hole_diameter:
                hole_diameter *= scale

            data.apertures[code] = Aperture(
                code=code,
                aperture_type=aperture_type,
                params=params,
                hole_diameter=hole_diameter,
            )
            return

        # Try macro-based aperture
        match = re.match(r'ADD?(\d+)([A-Za-z_][A-Za-z0-9_]*),?(.*)$', line)
        if match:
            code = int(match.group(1))
            macro_name = match.group(2)
            params_str = match.group(3)

            # Parse parameters for macro
            params = []
            if params_str:
                for p in params_str.split('X'):
                    try:
                        params.append(float(p))
                    except ValueError:
                        pass

            # Convert to mm if needed
            scale = 25.4 if data.units == 'inch' else 1.0
            params = [p * scale for p in params]

            # Check if macro exists
            if macro_name in data.macros:
                data.apertures[code] = Aperture(
                    code=code,
                    aperture_type=ApertureType.MACRO,
                    params=params,
                    macro_name=macro_name,
                )
            else:
                data.warnings.append(f"Aperture D{code} references undefined macro '{macro_name}'")

    def _parse_standard_command(self, line: str, data: GerberData) -> None:
        """Parse standard Gerber command"""
        # Aperture selection: D<nn>
        if re.match(r'D\d+\*?$', line):
            match = re.match(r'D(\d+)', line)
            if match:
                self.current_aperture = int(match.group(1))
            return

        # Interpolation mode
        if 'G01' in line or line.startswith('G1'):
            self.interpolation_mode = 'linear'
        elif 'G02' in line or line.startswith('G2'):
            self.interpolation_mode = 'cw_arc'
        elif 'G03' in line or line.startswith('G3'):
            self.interpolation_mode = 'ccw_arc'

        # Quadrant mode (for arc interpolation)
        if 'G74' in line:
            self.quadrant_mode = 'single'  # Single quadrant mode
        elif 'G75' in line:
            self.quadrant_mode = 'multi'  # Multi quadrant mode (default)

        # Region mode
        if 'G36' in line:
            self.region_mode = True
            self.region_points = []
        elif 'G37' in line:
            if self.region_points:
                data.regions.append(self.region_points.copy())
            self.region_mode = False
            self.region_points = []

        # Comment: G04
        if line.startswith('G04') or line.startswith('G4'):
            return  # Skip comments

        # Coordinate command
        if 'X' in line or 'Y' in line or 'I' in line or 'J' in line:
            self._parse_coordinate_command(line, data)

    def _parse_coordinate_command(self, line: str, data: GerberData) -> None:
        """Parse coordinate command (move, draw, flash, arc)"""
        # Extract coordinates
        x_match = re.search(r'X([+-]?\d+)', line)
        y_match = re.search(r'Y([+-]?\d+)', line)
        i_match = re.search(r'I([+-]?\d+)', line)
        j_match = re.search(r'J([+-]?\d+)', line)

        new_x = self.current_x
        new_y = self.current_y

        scale = 10 ** (-data.decimal_digits)
        if data.units == 'inch':
            scale *= 25.4  # Convert to mm

        if x_match:
            coord_val = int(x_match.group(1))
            if data.absolute_coords:
                new_x = coord_val * scale
            else:
                new_x = self.current_x + coord_val * scale

        if y_match:
            coord_val = int(y_match.group(1))
            if data.absolute_coords:
                new_y = coord_val * scale
            else:
                new_y = self.current_y + coord_val * scale

        # Arc center offsets (always relative to current position)
        arc_i = int(i_match.group(1)) * scale if i_match else 0
        arc_j = int(j_match.group(1)) * scale if j_match else 0

        # Determine operation
        is_draw = 'D01' in line or 'D1' in line
        is_move = 'D02' in line or 'D2' in line
        is_flash = 'D03' in line or 'D3' in line

        # Check for implicit D01 if no D code specified
        if not is_draw and not is_move and not is_flash:
            if not any(f'D0{i}' in line or f'D{i}' in line for i in range(1, 10)):
                # Implicit draw if coordinates changed
                if self.current_x != new_x or self.current_y != new_y:
                    is_draw = True

        if is_draw:
            # Draw operation - check interpolation mode
            if self.interpolation_mode in ['cw_arc', 'ccw_arc'] and (i_match or j_match):
                # Arc interpolation
                self._add_arc(
                    self.current_x, self.current_y,
                    new_x, new_y,
                    arc_i, arc_j,
                    self.interpolation_mode == 'cw_arc',
                    data
                )
            else:
                # Linear interpolation
                if self.region_mode:
                    self.region_points.append((new_x, new_y))
                else:
                    self._add_trace(self.current_x, self.current_y, new_x, new_y, data)

        elif is_flash:
            # Flash (pad)
            self._add_pad(new_x, new_y, data)

        # Update bounding box
        data.min_x = min(data.min_x, new_x)
        data.max_x = max(data.max_x, new_x)
        data.min_y = min(data.min_y, new_y)
        data.max_y = max(data.max_y, new_y)

        # Update current position
        self.current_x = new_x
        self.current_y = new_y

    def _add_trace(self, x1: float, y1: float, x2: float, y2: float, data: GerberData) -> None:
        """Add a trace to the data"""
        if self.current_aperture is None:
            return

        aperture = data.apertures.get(self.current_aperture)
        width = aperture.width_mm if aperture else 0.1

        trace = GerberTrace(
            start_x=x1,
            start_y=y1,
            end_x=x2,
            end_y=y2,
            width_mm=width,
            aperture_code=self.current_aperture,
        )
        data.traces.append(trace)

        # Track for step-and-repeat
        if self.sr_active:
            self.sr_features.append(('trace', trace))

    def _add_arc(
        self,
        start_x: float, start_y: float,
        end_x: float, end_y: float,
        i_offset: float, j_offset: float,
        clockwise: bool,
        data: GerberData
    ) -> None:
        """
        Add an arc to the data.

        In multi-quadrant mode (G75, default):
            - Center = (start_x + i_offset, start_y + j_offset)
            - Arc can span any angle

        In single-quadrant mode (G74):
            - Center must be found by trying different quadrant combinations
            - Arc limited to 90 degrees
        """
        if self.current_aperture is None:
            return

        aperture = data.apertures.get(self.current_aperture)
        width = aperture.width_mm if aperture else 0.1

        # Calculate arc center
        if self.quadrant_mode == 'multi':
            # Multi-quadrant: I and J are signed offsets from start
            center_x = start_x + i_offset
            center_y = start_y + j_offset
        else:
            # Single-quadrant: Find valid center by trying combinations
            center_x, center_y = self._find_single_quadrant_center(
                start_x, start_y, end_x, end_y,
                abs(i_offset), abs(j_offset), clockwise
            )

        arc = GerberArc(
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
            center_x=center_x,
            center_y=center_y,
            width_mm=width,
            clockwise=clockwise,
        )
        data.arcs.append(arc)

        # Also tessellate arc into region points if in region mode
        if self.region_mode:
            arc_points = self._tessellate_arc(arc)
            self.region_points.extend(arc_points)

        # Track for step-and-repeat
        if self.sr_active:
            self.sr_features.append(('arc', arc))

        # Update bounding box to include arc extent
        self._update_arc_bounding_box(arc, data)

    def _find_single_quadrant_center(
        self,
        start_x: float, start_y: float,
        end_x: float, end_y: float,
        abs_i: float, abs_j: float,
        clockwise: bool
    ) -> Tuple[float, float]:
        """
        Find arc center in single-quadrant mode by trying sign combinations.
        Returns the center that produces a valid arc.
        """
        # Try all combinations of signs for I and J
        for i_sign in [1, -1]:
            for j_sign in [1, -1]:
                cx = start_x + i_sign * abs_i
                cy = start_y + j_sign * abs_j

                # Check if this center produces matching radii
                r_start = math.sqrt((start_x - cx)**2 + (start_y - cy)**2)
                r_end = math.sqrt((end_x - cx)**2 + (end_y - cy)**2)

                # Allow small tolerance for floating point
                if abs(r_start - r_end) < 0.001 * max(r_start, r_end, 1):
                    # Check if arc is <= 90 degrees (single quadrant)
                    angle_start = math.atan2(start_y - cy, start_x - cx)
                    angle_end = math.atan2(end_y - cy, end_x - cx)

                    if clockwise:
                        sweep = angle_start - angle_end
                    else:
                        sweep = angle_end - angle_start

                    # Normalize to [0, 2*pi]
                    while sweep < 0:
                        sweep += 2 * math.pi
                    while sweep > 2 * math.pi:
                        sweep -= 2 * math.pi

                    # Single quadrant: sweep should be <= 90 degrees
                    if sweep <= math.pi / 2 + 0.01:  # Small tolerance
                        return (cx, cy)

        # Fallback: use positive offsets
        return (start_x + abs_i, start_y + abs_j)

    def _tessellate_arc(self, arc: GerberArc, segments: int = 32) -> List[Tuple[float, float]]:
        """
        Tessellate arc into line segments for region polygons.

        Args:
            arc: The arc to tessellate
            segments: Maximum number of segments for a full circle

        Returns:
            List of (x, y) points along the arc
        """
        points = []

        # Calculate angles
        start_angle = math.atan2(arc.start_y - arc.center_y, arc.start_x - arc.center_x)
        end_angle = math.atan2(arc.end_y - arc.center_y, arc.end_x - arc.center_x)

        # Calculate radius
        radius = math.sqrt((arc.start_x - arc.center_x)**2 + (arc.start_y - arc.center_y)**2)

        if radius < 0.0001:
            return [(arc.end_x, arc.end_y)]

        # Calculate sweep angle
        if arc.clockwise:
            sweep = start_angle - end_angle
            if sweep <= 0:
                sweep += 2 * math.pi
        else:
            sweep = end_angle - start_angle
            if sweep <= 0:
                sweep += 2 * math.pi

        # Number of segments proportional to sweep
        num_segments = max(2, int(segments * sweep / (2 * math.pi)))

        # Generate points
        for i in range(1, num_segments + 1):
            t = i / num_segments
            if arc.clockwise:
                angle = start_angle - t * sweep
            else:
                angle = start_angle + t * sweep

            x = arc.center_x + radius * math.cos(angle)
            y = arc.center_y + radius * math.sin(angle)
            points.append((x, y))

        return points

    def _update_arc_bounding_box(self, arc: GerberArc, data: GerberData) -> None:
        """Update bounding box to include arc extent"""
        # Include start and end points
        data.min_x = min(data.min_x, arc.start_x, arc.end_x)
        data.max_x = max(data.max_x, arc.start_x, arc.end_x)
        data.min_y = min(data.min_y, arc.start_y, arc.end_y)
        data.max_y = max(data.max_y, arc.start_y, arc.end_y)

        # Check if arc crosses axis extremes
        radius = math.sqrt((arc.start_x - arc.center_x)**2 + (arc.start_y - arc.center_y)**2)
        start_angle = math.atan2(arc.start_y - arc.center_y, arc.start_x - arc.center_x)
        end_angle = math.atan2(arc.end_y - arc.center_y, arc.end_x - arc.center_x)

        # Check cardinal directions (0, 90, 180, 270 degrees)
        for cardinal in [0, math.pi/2, math.pi, 3*math.pi/2]:
            if self._angle_in_arc(cardinal, start_angle, end_angle, arc.clockwise):
                px = arc.center_x + radius * math.cos(cardinal)
                py = arc.center_y + radius * math.sin(cardinal)
                data.min_x = min(data.min_x, px)
                data.max_x = max(data.max_x, px)
                data.min_y = min(data.min_y, py)
                data.max_y = max(data.max_y, py)

    def _angle_in_arc(self, angle: float, start: float, end: float, clockwise: bool) -> bool:
        """Check if an angle falls within the arc sweep"""
        # Normalize angles to [0, 2*pi]
        def normalize(a):
            while a < 0:
                a += 2 * math.pi
            while a >= 2 * math.pi:
                a -= 2 * math.pi
            return a

        angle = normalize(angle)
        start = normalize(start)
        end = normalize(end)

        if clockwise:
            if start >= end:
                return angle <= start and angle >= end
            else:
                return angle <= start or angle >= end
        else:
            if end >= start:
                return angle >= start and angle <= end
            else:
                return angle >= start or angle <= end

    def _add_pad(self, x: float, y: float, data: GerberData) -> None:
        """Add a pad/flash to the data"""
        if self.current_aperture is None:
            return

        aperture = data.apertures.get(self.current_aperture)
        if aperture:
            pad = GerberPad(
                x=x,
                y=y,
                aperture_code=self.current_aperture,
                width_mm=aperture.width_mm,
                height_mm=aperture.height_mm,
                shape=aperture.aperture_type,
            )
            data.pads.append(pad)

            # Track for step-and-repeat
            if self.sr_active:
                self.sr_features.append(('pad', pad))

    def _calculate_statistics(self, data: GerberData) -> None:
        """Calculate summary statistics"""
        data.trace_count = len(data.traces)
        data.pad_count = len(data.pads)
        data.arc_count = len(data.arcs)
        data.region_count = len(data.regions)
        data.total_trace_length_mm = sum(t.length_mm for t in data.traces)

        # Calculate arc lengths
        data.total_arc_length_mm = 0
        for arc in data.arcs:
            radius = math.sqrt((arc.start_x - arc.center_x)**2 + (arc.start_y - arc.center_y)**2)
            start_angle = math.atan2(arc.start_y - arc.center_y, arc.start_x - arc.center_x)
            end_angle = math.atan2(arc.end_y - arc.center_y, arc.end_x - arc.center_x)

            if arc.clockwise:
                sweep = start_angle - end_angle
                if sweep <= 0:
                    sweep += 2 * math.pi
            else:
                sweep = end_angle - start_angle
                if sweep <= 0:
                    sweep += 2 * math.pi

            data.total_arc_length_mm += radius * sweep

    def parse_from_bytes(self, content: bytes, filename: str = "layer.gbr") -> GerberData:
        """
        Parse Gerber from bytes.

        Args:
            content: Raw bytes of Gerber file
            filename: Original filename for layer type inference

        Returns:
            GerberData with all extracted features
        """
        data = GerberData(source_file=filename)
        self._infer_layer_type(filename, data)

        try:
            text_content = content.decode('utf-8')
        except UnicodeDecodeError:
            text_content = content.decode('latin-1')

        self._parse_content(text_content, data)
        self._calculate_statistics(data)

        return data

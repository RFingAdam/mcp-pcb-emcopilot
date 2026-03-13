"""Data models for ODB++ parsed data"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class LayerType(Enum):
    """ODB++ layer types"""
    SIGNAL = "signal"
    PLANE = "plane"
    MIXED = "mixed"
    SOLDER_MASK = "solder_mask"
    SILK_SCREEN = "silk_screen"
    SOLDER_PASTE = "solder_paste"
    DRILL = "drill"
    DOCUMENT = "document"
    COMPONENT = "component"
    DIELECTRIC = "dielectric"


class Polarity(Enum):
    """Layer polarity"""
    POSITIVE = "positive"
    NEGATIVE = "negative"


class ViaType(Enum):
    """Via types"""
    THROUGH = "through"
    BLIND = "blind"
    BURIED = "buried"
    MICROVIA = "microvia"
    VIA_IN_PAD = "via_in_pad"


class PadShape(Enum):
    """Pad shapes"""
    ROUND = "round"
    SQUARE = "square"
    RECTANGLE = "rectangle"
    OBLONG = "oblong"
    OCTAGON = "octagon"
    DONUT = "donut"
    THERMAL = "thermal"
    CUSTOM = "custom"


@dataclass
class ODBLayer:
    """Layer definition from ODB++ matrix"""
    name: str
    row: int
    layer_type: LayerType
    polarity: Polarity = Polarity.POSITIVE
    context: str = "board"  # board, misc, etc.

    # Physical properties
    thickness_mm: Optional[float] = None
    copper_weight_oz: Optional[float] = None

    # Dielectric properties (for dielectric layers)
    dielectric_constant: Optional[float] = None
    loss_tangent: Optional[float] = None
    material: Optional[str] = None

    # Metadata
    start_name: Optional[str] = None
    end_name: Optional[str] = None
    old_name: Optional[str] = None


@dataclass
class ODBPad:
    """Pad definition"""
    name: str
    shape: PadShape
    width_mm: float
    height_mm: float

    # Additional geometry
    corner_radius_mm: Optional[float] = None
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    rotation_deg: float = 0.0

    # Thermal relief
    thermal_spoke_count: Optional[int] = None
    thermal_spoke_width_mm: Optional[float] = None
    thermal_gap_mm: Optional[float] = None


@dataclass
class ODBComponent:
    """Component placement from ODB++"""
    ref_des: str
    part_name: str
    package: str

    # Placement
    x_mm: float
    y_mm: float
    rotation_deg: float
    mirror: bool = False
    layer: str = "top"  # top or bottom

    # Dimensions
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None

    # Properties
    properties: Dict[str, Any] = field(default_factory=dict)
    pins: List[ODBPin] = field(default_factory=list)


@dataclass
class ODBPin:
    """Component pin definition"""
    pin_number: str
    pin_name: Optional[str] = None
    x_offset_mm: float = 0.0
    y_offset_mm: float = 0.0

    # Pad reference
    pad_name: Optional[str] = None
    pad_shape: Optional[PadShape] = None
    pad_width_mm: Optional[float] = None
    pad_height_mm: Optional[float] = None

    # Connectivity
    net_name: Optional[str] = None


@dataclass
class ODBNet:
    """Net/signal definition from ODB++"""
    name: str
    net_number: int

    # Connectivity
    pins: List[str] = field(default_factory=list)  # component.pin format
    subnet_count: int = 0

    # Properties
    net_class: Optional[str] = None
    impedance_target_ohm: Optional[float] = None
    is_differential: bool = False
    differential_pair: Optional[str] = None

    # Routing info (populated after feature parsing)
    routed_length_mm: Optional[float] = None
    via_count: int = 0
    layer_count: int = 0

    # Properties
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ODBVia:
    """Via definition from ODB++"""
    x_mm: float
    y_mm: float
    drill_diameter_mm: float

    # Pad sizes
    pad_top_mm: Optional[float] = None
    pad_bottom_mm: Optional[float] = None
    pad_inner_mm: Optional[float] = None

    # Layer span
    start_layer: str = "top"
    end_layer: str = "bottom"
    via_type: ViaType = ViaType.THROUGH

    # Net association
    net_name: Optional[str] = None
    net_number: Optional[int] = None

    # Properties
    is_filled: bool = False
    is_capped: bool = False
    is_tented: bool = False
    plating_thickness_um: Optional[float] = None


@dataclass
class ODBTrace:
    """Trace/track from ODB++ features"""
    layer: str
    width_mm: float

    # Geometry - list of (x, y) coordinates in mm
    points: List[tuple] = field(default_factory=list)

    # Net association
    net_name: Optional[str] = None
    net_number: Optional[int] = None

    # Computed
    length_mm: Optional[float] = None

    # Properties
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ODBCopperPour:
    """Copper pour/plane from ODB++ features"""
    layer: str
    net_name: Optional[str] = None
    net_number: Optional[int] = None

    # Geometry - boundary polygon
    boundary: List[tuple] = field(default_factory=list)  # [(x, y), ...]

    # Properties
    pour_type: str = "solid"  # solid, hatched
    clearance_mm: Optional[float] = None

    # Hatch properties
    hatch_width_mm: Optional[float] = None
    hatch_gap_mm: Optional[float] = None
    hatch_angle_deg: Optional[float] = None

    # Thermal relief
    thermal_enabled: bool = True
    thermal_spoke_count: int = 4
    thermal_spoke_width_mm: Optional[float] = None
    thermal_gap_mm: Optional[float] = None

    # Computed
    area_mm2: Optional[float] = None


@dataclass
class ODBDrill:
    """Drill hit from ODB++"""
    x_mm: float
    y_mm: float
    diameter_mm: float

    # Drill type
    drill_type: str = "plated"  # plated, non_plated, via

    # Layer span
    start_layer: str = "top"
    end_layer: str = "bottom"

    # Associated via or pad
    via_id: Optional[int] = None
    component_ref: Optional[str] = None
    pin_number: Optional[str] = None


@dataclass
class ODBBoardOutline:
    """Board outline/profile from ODB++"""
    # Boundary polygon
    outline: List[tuple] = field(default_factory=list)  # [(x, y), ...]

    # Cutouts/holes
    cutouts: List[List[tuple]] = field(default_factory=list)

    # Computed dimensions
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None
    area_mm2: Optional[float] = None

    # Origin
    origin_x_mm: float = 0.0
    origin_y_mm: float = 0.0


@dataclass
class ODBDesignRule:
    """Design rule constraint extracted from ODB++ attributes"""
    rule_name: str
    rule_type: str  # spacing, width, drill, annular_ring, other
    value_mm: float
    layer_scope: Optional[str] = None  # None = global, or layer name


@dataclass
class ODBPadStack:
    """Pad stack definition from ODB++ symbols"""
    pad_id: str
    layers: Dict[str, ODBPad] = field(default_factory=dict)  # layer_name -> pad shape
    drill_size_mm: Optional[float] = None
    plating: str = "pth"  # pth, npth


@dataclass
class ODBData:
    """Complete ODB++ parsed data"""
    # Source info
    source_file: str
    job_name: Optional[str] = None

    # Layer stackup
    layers: List[ODBLayer] = field(default_factory=list)
    layer_count: int = 0

    # Board outline
    outline: Optional[ODBBoardOutline] = None

    # Components
    components: List[ODBComponent] = field(default_factory=list)
    component_count: int = 0

    # Nets
    nets: List[ODBNet] = field(default_factory=list)
    net_count: int = 0

    # Vias
    vias: List[ODBVia] = field(default_factory=list)
    via_count: int = 0

    # Traces (per layer)
    traces: Dict[str, List[ODBTrace]] = field(default_factory=dict)

    # Copper pours (per layer)
    copper_pours: Dict[str, List[ODBCopperPour]] = field(default_factory=dict)

    # Drills
    drills: List[ODBDrill] = field(default_factory=list)

    # Pad definitions
    pad_templates: Dict[str, ODBPad] = field(default_factory=dict)

    # Pad stacks
    pad_stacks: Dict[str, ODBPadStack] = field(default_factory=dict)

    # Design rules
    design_rules: List[ODBDesignRule] = field(default_factory=list)

    # Manufacturing notes
    manufacturing_notes: List[str] = field(default_factory=list)

    # Stackup properties
    total_thickness_mm: Optional[float] = None
    default_dielectric_constant: float = 4.3  # FR4
    default_loss_tangent: float = 0.02

    # Parsing status
    parse_warnings: List[str] = field(default_factory=list)
    parse_errors: List[str] = field(default_factory=list)
    is_complete: bool = False

    def get_copper_layers(self) -> List[ODBLayer]:
        """Get only copper (signal/plane) layers"""
        return [l for l in self.layers if l.layer_type in (LayerType.SIGNAL, LayerType.PLANE, LayerType.MIXED)]

    def get_layer_by_name(self, name: str) -> Optional[ODBLayer]:
        """Find layer by name"""
        for layer in self.layers:
            if layer.name.lower() == name.lower():
                return layer
        return None

    def get_net_by_name(self, name: str) -> Optional[ODBNet]:
        """Find net by name"""
        for net in self.nets:
            if net.name.lower() == name.lower():
                return net
        return None

    def get_component_by_ref(self, ref: str) -> Optional[ODBComponent]:
        """Find component by reference designator"""
        for comp in self.components:
            if comp.ref_des.upper() == ref.upper():
                return comp
        return None

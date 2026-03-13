"""Unified in-memory PCB design data representation.

Replaces the Agentarium PostgreSQL models with plain dataclasses
that hold parsed design data from any format (KiCad, ODB++, Gerber, Altium, IPC-2581).
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PCBLayer:
    """Layer in the PCB stackup."""
    name: str
    number: int
    layer_type: str  # signal, plane, dielectric, solder_mask, mixed
    thickness_mm: float = 0.0
    material: Optional[str] = None
    dielectric_constant: float = 4.3
    loss_tangent: float = 0.02
    copper_weight_oz: Optional[float] = None


@dataclass
class PCBComponent:
    """Component placed on the PCB."""
    reference: str
    value: Optional[str] = None
    footprint: Optional[str] = None
    package: Optional[str] = None
    part_number: Optional[str] = None
    manufacturer: Optional[str] = None
    layer: str = "F.Cu"
    x_mm: float = 0.0
    y_mm: float = 0.0
    rotation: float = 0.0
    dnp: bool = False
    properties: dict = field(default_factory=dict)
    pads: list = field(default_factory=list)


@dataclass
class PCBNet:
    """Electrical net."""
    name: str
    index: int = 0
    net_class: Optional[str] = None
    is_differential: bool = False
    differential_pair: Optional[str] = None
    pin_count: int = 0
    routed_length_mm: float = 0.0
    via_count: int = 0
    impedance_target_ohm: Optional[float] = None
    max_frequency_hz: Optional[float] = None
    properties: dict = field(default_factory=dict)


@dataclass
class PCBTrace:
    """Trace segment on the PCB."""
    layer: str
    width_mm: float
    x1_mm: float = 0.0
    y1_mm: float = 0.0
    x2_mm: float = 0.0
    y2_mm: float = 0.0
    net_index: int = 0
    net_name: Optional[str] = None
    length_mm: Optional[float] = None

    def calc_length(self) -> float:
        import math
        dx = self.x2_mm - self.x1_mm
        dy = self.y2_mm - self.y1_mm
        return math.sqrt(dx * dx + dy * dy)


@dataclass
class PCBVia:
    """Via connecting layers."""
    x_mm: float
    y_mm: float
    drill_mm: float
    pad_diameter_mm: float = 0.0
    via_type: str = "through"
    start_layer: str = "F.Cu"
    end_layer: str = "B.Cu"
    net_index: int = 0
    net_name: Optional[str] = None


@dataclass
class PCBZone:
    """Copper zone/pour."""
    layer: str
    net_name: Optional[str] = None
    net_index: int = 0
    zone_type: str = "fill"
    outline: list = field(default_factory=list)
    area_mm2: float = 0.0


@dataclass
class PCBDesignData:
    """Complete PCB design data — the unified in-memory representation.

    This replaces the Agentarium PostgreSQL database.
    Populated by any parser (KiCad, ODB++, Gerber, Altium, IPC-2581).
    """
    source_file: str
    source_format: str = "unknown"

    # Board info
    board_width_mm: float = 0.0
    board_height_mm: float = 0.0
    board_thickness_mm: float = 1.6
    board_outline: list = field(default_factory=list)
    title: Optional[str] = None
    revision: Optional[str] = None

    # Stackup
    layers: list[PCBLayer] = field(default_factory=list)
    layer_count: int = 2

    # Design elements
    components: list[PCBComponent] = field(default_factory=list)
    nets: list[PCBNet] = field(default_factory=list)
    traces: list[PCBTrace] = field(default_factory=list)
    vias: list[PCBVia] = field(default_factory=list)
    zones: list[PCBZone] = field(default_factory=list)

    # Design rules
    min_trace_width_mm: float = 0.2
    min_clearance_mm: float = 0.2
    min_via_drill_mm: float = 0.3

    # Net classes
    net_classes: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Statistics (computed)
    total_trace_length_mm: float = 0.0

    # Parsing info
    warnings: list[str] = field(default_factory=list)

    # Deep extraction data (populated by ODB++ and other parsers)
    drill_table: list[dict] = field(default_factory=list)  # [{size_mm, count, plating, aspect_ratio}]
    board_outline_detail: dict = field(default_factory=dict)  # {width_mm, height_mm, area_mm2, vertices, cutouts}
    design_rules: list[dict] = field(default_factory=list)  # [{name, type, value_mm, scope}]
    copper_pours: list[dict] = field(default_factory=list)  # [{layer, net_name, area_mm2, clearance_mm, ...}]
    manufacturing_notes: list[str] = field(default_factory=list)

    # BOM data (optional, from bom_parser)
    bom_items: list[dict] = field(default_factory=list)

    # Schematic data (optional, from schematic_parser)
    schematic_components: list[dict] = field(default_factory=list)
    schematic_nets: list[dict] = field(default_factory=list)

    # Schematic PDF data (optional, from pdf_schematic_parser)
    schematic_pages: list[dict] = field(default_factory=list)
    schematic_pdf_path: Optional[str] = None

    # Review context (set by orchestrator)
    review_context: dict = field(default_factory=dict)

    # Review results (populated by orchestrator)
    review_results: dict = field(default_factory=dict)

    # 3D / STEP data (optional, from step_parser)
    step_components: list[dict] = field(default_factory=list)  # [{reference, x, y, z, width, depth, height}]
    board_3d: dict = field(default_factory=dict)  # {width, depth, thickness, bounding_box}

    @property
    def component_count(self) -> int:
        return len(self.components)

    @property
    def net_count(self) -> int:
        return len(self.nets)

    @property
    def via_count(self) -> int:
        return len(self.vias)

    def get_copper_layers(self) -> list[PCBLayer]:
        return [l for l in self.layers if l.layer_type in ("signal", "plane", "mixed")]

    def get_net_by_name(self, name: str) -> Optional[PCBNet]:
        for net in self.nets:
            if net.name.lower() == name.lower():
                return net
        return None

    def get_component_by_ref(self, ref: str) -> Optional[PCBComponent]:
        for comp in self.components:
            if comp.reference.upper() == ref.upper():
                return comp
        return None

    def get_traces_on_net(self, net_index: int) -> list[PCBTrace]:
        return [t for t in self.traces if t.net_index == net_index]

    def get_vias_on_net(self, net_index: int) -> list[PCBVia]:
        return [v for v in self.vias if v.net_index == net_index]

    def to_summary(self) -> dict:
        return {
            "source_file": self.source_file,
            "format": self.source_format,
            "board_size_mm": f"{self.board_width_mm:.1f} x {self.board_height_mm:.1f}",
            "thickness_mm": self.board_thickness_mm,
            "layer_count": self.layer_count,
            "components": self.component_count,
            "nets": self.net_count,
            "traces": len(self.traces),
            "vias": self.via_count,
            "zones": len(self.zones),
            "total_trace_length_mm": round(self.total_trace_length_mm, 1),
            "title": self.title,
            "revision": self.revision,
        }

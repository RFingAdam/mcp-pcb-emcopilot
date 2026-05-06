"""IPC-2581 file parser for PCB design data.

IPC-2581 is an XML-based industry standard format for PCB manufacturing data.
Also known as DPMX (Digital Product Model Exchange).

Supports:
- IPC-2581 Rev A, B, C
- Complete layer stackup
- Component placement
- Net connectivity
- Design rules
- BOM data
- Assembly information

Reference: IPC-2581 Standard (www.ipc.org)
"""

from __future__ import annotations

import gzip
import logging
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Unit conversion factors to mm
UNIT_CONVERSIONS = {
    "MM": 1.0,
    "MILLIMETER": 1.0,
    "MIL": 0.0254,
    "INCH": 25.4,
    "MICRON": 0.001,
    "UM": 0.001,
}


@dataclass
class IPC2581Component:
    """Component from IPC-2581 design."""
    reference: str
    package_ref: str
    part_number: Optional[str] = None
    manufacturer: Optional[str] = None
    description: Optional[str] = None
    x_mm: float = 0.0
    y_mm: float = 0.0
    rotation: float = 0.0
    layer: str = "TOP"
    mount_type: str = "SMD"  # SMD, THRU, OTHER


@dataclass
class IPC2581Net:
    """Net from IPC-2581 design."""
    name: str
    net_class: Optional[str] = None
    pins: list[dict] = field(default_factory=list)
    routed_length_mm: float = 0.0  # Total routed length of traces on this net


@dataclass
class IPC2581Trace:
    """Trace segment from IPC-2581 design."""
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float
    width_mm: float
    layer: str
    net_name: Optional[str] = None

    @property
    def length_mm(self) -> float:
        """Calculate trace segment length in mm."""
        import math
        dx = self.x2_mm - self.x1_mm
        dy = self.y2_mm - self.y1_mm
        return math.sqrt(dx * dx + dy * dy)


@dataclass
class IPC2581Via:
    """Via from IPC-2581 design."""
    x_mm: float
    y_mm: float
    drill_mm: float
    pad_diameter_mm: float
    start_layer: str
    end_layer: str
    net_name: Optional[str] = None
    via_type: str = "through"  # through, blind, buried, microvia

    def classify_via_type(self, layer_names: list[str]) -> str:
        """Classify via type based on layer span.

        Args:
            layer_names: Ordered list of copper layer names (top to bottom)

        Returns:
            Via type: 'through', 'blind', 'buried', or 'microvia'
        """
        if len(layer_names) <= 2:
            return "through"

        # Normalize layer names for comparison
        start_upper = self.start_layer.upper()
        end_upper = self.end_layer.upper()
        top_layer = layer_names[0].upper() if layer_names else "TOP"
        bottom_layer = layer_names[-1].upper() if layer_names else "BOTTOM"

        # Check for common naming patterns
        is_top = start_upper in ("TOP", "L1", "LAYER1", top_layer) or "TOP" in start_upper
        is_bottom = end_upper in ("BOTTOM", "BOT", f"L{len(layer_names)}", bottom_layer) or "BOTTOM" in end_upper or "BOT" in end_upper

        # Try to find layer indices
        try:
            start_idx = next((i for i, l in enumerate(layer_names) if l.upper() == start_upper), 0)
            end_idx = next((i for i, l in enumerate(layer_names) if l.upper() == end_upper), len(layer_names) - 1)
            layer_span = abs(end_idx - start_idx) + 1
        except (StopIteration, AttributeError):
            layer_span = len(layer_names)

        if is_top and is_bottom:
            return "through"
        elif is_top or is_bottom:
            if layer_span <= 2:
                return "microvia"
            return "blind"
        else:
            if layer_span <= 2:
                return "microvia"
            return "buried"


@dataclass
class IPC2581Pad:
    """Pad from IPC-2581 design."""
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    shape: str  # CIRCLE, RECTANGLE, OBLONG, etc.
    layer: str
    component_ref: Optional[str] = None
    pin_number: Optional[str] = None
    net_name: Optional[str] = None


@dataclass
class IPC2581Layer:
    """Layer definition from IPC-2581."""
    name: str
    layer_type: str  # SIGNAL, PLANE, DIELECTRIC, SOLDER_MASK, etc.
    side: str  # TOP, BOTTOM, INTERNAL
    sequence: int = 0
    thickness_mm: float = 0.0
    copper_weight_oz: float = 1.0
    dielectric_constant: float = 4.2
    material: Optional[str] = None


@dataclass
class IPC2581StackupLayer:
    """Physical stackup layer."""
    name: str
    layer_type: str
    thickness_mm: float
    material: Optional[str] = None
    dielectric_constant: float = 4.2
    copper_weight_oz: float = 0.0
    sequence: int = 0


@dataclass
class IPC2581DesignRule:
    """Design rule from IPC-2581."""
    name: str
    rule_type: str
    value: float
    unit: str = "MM"


@dataclass
class IPC2581BOMItem:
    """BOM item from IPC-2581."""
    part_number: str
    manufacturer: Optional[str] = None
    description: Optional[str] = None
    quantity: int = 1
    references: list[str] = field(default_factory=list)
    package: Optional[str] = None


@dataclass
class IPC2581Data:
    """Complete parsed IPC-2581 data."""
    source_file: str
    version: str = "unknown"

    # Board info
    board_name: Optional[str] = None
    width_mm: float = 0.0
    height_mm: float = 0.0
    layer_count: int = 2

    # Layer definitions
    layers: list[IPC2581Layer] = field(default_factory=list)
    stackup: list[IPC2581StackupLayer] = field(default_factory=list)

    # Design elements
    components: list[IPC2581Component] = field(default_factory=list)
    nets: list[IPC2581Net] = field(default_factory=list)
    traces: list[IPC2581Trace] = field(default_factory=list)
    vias: list[IPC2581Via] = field(default_factory=list)
    pads: list[IPC2581Pad] = field(default_factory=list)

    # Design rules
    design_rules: list[IPC2581DesignRule] = field(default_factory=list)

    # BOM
    bom_items: list[IPC2581BOMItem] = field(default_factory=list)

    # Trace statistics
    total_trace_length_mm: float = 0.0
    via_count: int = 0

    # Metadata
    warnings: list[str] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)


class IPC2581Parser:
    """Parser for IPC-2581 (DPMX) files.

    IPC-2581 is an XML-based format containing complete PCB design data.
    Files may be:
    - .xml (plain XML)
    - .cvg (IPC-2581 specific extension)
    - .zip (compressed package)
    - .gz (gzipped XML)

    Usage:
        parser = IPC2581Parser()
        data = parser.parse("design.cvg")
        print(f"Found {len(data.components)} components")
    """

    # XML namespaces used in IPC-2581
    NAMESPACES = {
        "": "http://webstds.ipc.org/2581",
        "ipc": "http://webstds.ipc.org/2581",
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    }

    def __init__(self):
        self.unit_factor = 1.0  # Default to mm
        self._packages: dict[str, dict] = {}
        self._pad_stacks: dict[str, dict] = {}
        self._net_map: dict[str, IPC2581Net] = {}

    def parse(self, file_path: str) -> IPC2581Data:
        """Parse an IPC-2581 file.

        Args:
            file_path: Path to IPC-2581 file (.xml, .cvg, .zip, or .gz)

        Returns:
            IPC2581Data with all extracted information
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"IPC-2581 file not found: {path}")

        data = IPC2581Data(source_file=str(path))

        try:
            xml_content = self._load_file(path)

            # Parse XML
            root = ET.fromstring(xml_content)

            # Detect namespace
            self._detect_namespace(root)

            # Parse sections - each section wrapped to capture partial failures
            try:
                self._parse_header(root, data)
            except Exception as e:
                data.warnings.append(f"Error parsing header: {str(e)}")

            try:
                self._parse_stackup(root, data)
            except Exception as e:
                data.warnings.append(f"Error parsing stackup: {str(e)}")

            try:
                self._parse_packages(root)
            except Exception as e:
                data.warnings.append(f"Error parsing packages: {str(e)}")

            try:
                self._parse_pad_stacks(root)
            except Exception as e:
                data.warnings.append(f"Error parsing pad stacks: {str(e)}")

            try:
                self._parse_nets(root, data)
            except Exception as e:
                data.warnings.append(f"Error parsing nets: {str(e)}")

            try:
                self._parse_components(root, data)
            except Exception as e:
                data.warnings.append(f"Error parsing components: {str(e)}")

            try:
                self._parse_layer_features(root, data)
            except Exception as e:
                data.warnings.append(f"Error parsing layer features: {str(e)}")

            try:
                self._parse_design_rules(root, data)
            except Exception as e:
                data.warnings.append(f"Error parsing design rules: {str(e)}")

            try:
                self._parse_bom(root, data)
            except Exception as e:
                data.warnings.append(f"Error parsing BOM: {str(e)}")

            # Calculate board dimensions if not set
            self._calculate_dimensions(data)

            # Calculate trace length statistics
            self._calculate_trace_statistics(data)

            logger.info(
                f"Parsed IPC-2581: {len(data.components)} components, "
                f"{len(data.nets)} nets, {len(data.traces)} traces, "
                f"{data.layer_count} layers, "
                f"total trace length: {data.total_trace_length_mm:.1f}mm"
            )

            return data

        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")
            raise ValueError(f"Invalid IPC-2581 XML: {str(e)}") from e
        except Exception as e:
            logger.error(f"Failed to parse IPC-2581: {e}")
            raise ValueError(f"IPC-2581 parse error: {str(e)}") from e

    def _load_file(self, file_path: Path) -> bytes:
        """Load file content, handling compression."""
        suffix = file_path.suffix.lower()

        if suffix == ".gz":
            with gzip.open(file_path, "rb") as f:
                return f.read()

        elif suffix == ".zip":
            with zipfile.ZipFile(file_path, "r") as zf:
                # Find XML file in archive
                xml_files = [n for n in zf.namelist()
                            if n.lower().endswith((".xml", ".cvg"))]
                if not xml_files:
                    raise ValueError("No XML file found in ZIP archive")
                return zf.read(xml_files[0])

        else:
            # Plain XML or .cvg
            with open(file_path, "rb") as f:
                return f.read()

    def _detect_namespace(self, root: ET.Element) -> None:
        """Detect and configure XML namespace."""
        tag = root.tag
        if "{" in tag:
            ns = tag[1:tag.index("}")]
            self.NAMESPACES[""] = ns
            self.NAMESPACES["ipc"] = ns

    def _find(self, element: ET.Element, path: str) -> Optional[ET.Element]:
        """Find element with namespace handling."""
        # Try with namespace
        for prefix, uri in self.NAMESPACES.items():
            if prefix:
                ns_path = "/".join(f"{{{uri}}}{p}" for p in path.split("/"))
            else:
                # Empty prefix: try bare path without namespace
                result = element.find(path)
                if result is not None:
                    return result
                continue
            result = element.find(ns_path)
            if result is not None:
                return result

        # Try without namespace
        return element.find(path)

    def _findall(self, element: ET.Element, path: str) -> list[ET.Element]:
        """Find all elements with namespace handling."""
        results = []

        # Try with namespace
        for prefix, uri in self.NAMESPACES.items():
            if not prefix:
                # Empty prefix: try bare path without namespace
                results.extend(element.findall(path))
                continue
            ns_path = "/".join(f"{{{uri}}}{p}" for p in path.split("/"))
            results.extend(element.findall(ns_path))

        # Try without namespace (fallback)
        if not results:
            results.extend(element.findall(path))

        return results

    def _parse_header(self, root: ET.Element, data: IPC2581Data) -> None:
        """Parse header information."""
        # Get version from root attributes
        data.version = root.get("revision", root.get("version", "unknown"))

        # Parse content section for board info
        content = self._find(root, "Content")
        if content is not None:
            # Get step (board) information
            for step in self._findall(content, "Step"):
                data.board_name = step.get("name")

                # Get board outline from profile
                profile = self._find(step, "Profile")
                if profile is not None:
                    self._parse_profile(profile, data)

        # Parse Ecad section
        ecad = self._find(root, "Ecad")
        if ecad is not None:
            data.properties["ecad_name"] = ecad.get("name", "")

        # Parse units
        for units in self._findall(root, ".//Units"):
            unit_type = units.get("unitType", "").upper()
            if unit_type in UNIT_CONVERSIONS:
                self.unit_factor = UNIT_CONVERSIONS[unit_type]
                data.properties["units"] = unit_type

    def _parse_profile(self, profile: ET.Element, data: IPC2581Data) -> None:
        """Parse board profile/outline."""
        min_x, min_y = float("inf"), float("inf")
        max_x, max_y = float("-inf"), float("-inf")

        # Parse polygon points
        for polygon in self._findall(profile, ".//Polygon"):
            for point in self._findall(polygon, "PolyBegin") + self._findall(polygon, "PolyStepSegment"):
                x = self._parse_float(point.get("x", "0")) * self.unit_factor
                y = self._parse_float(point.get("y", "0")) * self.unit_factor
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

        # Parse line segments
        for line in self._findall(profile, ".//Line"):
            for attr in ["startX", "startY", "endX", "endY"]:
                val = self._parse_float(line.get(attr, "0")) * self.unit_factor
                if "X" in attr:
                    min_x = min(min_x, val)
                    max_x = max(max_x, val)
                else:
                    min_y = min(min_y, val)
                    max_y = max(max_y, val)

        if min_x != float("inf"):
            data.width_mm = max_x - min_x
            data.height_mm = max_y - min_y

    def _parse_stackup(self, root: ET.Element, data: IPC2581Data) -> None:
        """Parse layer stackup."""
        stackup_group = self._find(root, ".//StackupGroup")
        if stackup_group is None:
            stackup_group = self._find(root, ".//Stackup")

        if stackup_group is None:
            return

        sequence = 0
        copper_layers = 0

        for layer_elem in self._findall(stackup_group, ".//StackupLayer"):
            name = layer_elem.get("layerOrGroupRef", layer_elem.get("name", f"Layer{sequence}"))
            layer_type = layer_elem.get("layerFunctionType", "SIGNAL").upper()
            thickness = self._parse_float(layer_elem.get("thickness", "0")) * self.unit_factor

            # Determine layer side
            if sequence == 0:
                side = "TOP"
            elif layer_type in ("SIGNAL", "PLANE"):
                side = "INTERNAL"
            else:
                side = "INTERNAL"

            # Parse material properties
            material = layer_elem.get("material")
            dk = self._parse_float(layer_elem.get("dielectricConstant", "4.2"))
            copper_weight = self._parse_float(layer_elem.get("copperWeight", "1.0"))

            layer = IPC2581Layer(
                name=name,
                layer_type=layer_type,
                side=side,
                sequence=sequence,
                thickness_mm=thickness,
                copper_weight_oz=copper_weight,
                dielectric_constant=dk,
                material=material,
            )
            data.layers.append(layer)

            stackup_layer = IPC2581StackupLayer(
                name=name,
                layer_type=layer_type,
                thickness_mm=thickness,
                material=material,
                dielectric_constant=dk,
                copper_weight_oz=copper_weight,
                sequence=sequence,
            )
            data.stackup.append(stackup_layer)

            if layer_type in ("SIGNAL", "PLANE", "POWER", "GROUND"):
                copper_layers += 1

            sequence += 1

        # Update layer count
        if copper_layers > 0:
            data.layer_count = copper_layers
        else:
            data.layer_count = max(2, len([l for l in data.layers
                                          if l.layer_type in ("SIGNAL", "PLANE")]))

    def _parse_packages(self, root: ET.Element) -> None:
        """Parse package definitions (footprints)."""
        for package in self._findall(root, ".//Package"):
            pkg_name = package.get("name", "")
            if not pkg_name:
                continue

            pkg_data: dict[str, Any] = {
                "name": pkg_name,
                "pads": [],
                "outline": None,
            }

            # Parse pads
            for pad in self._findall(package, ".//Pad"):
                pad_data = {
                    "number": pad.get("number", pad.get("pinNumber", "")),
                    "x": self._parse_float(pad.get("x", "0")) * self.unit_factor,
                    "y": self._parse_float(pad.get("y", "0")) * self.unit_factor,
                    "pad_stack_ref": pad.get("padstackDefRef", ""),
                }
                pkg_data["pads"].append(pad_data)

            self._packages[pkg_name] = pkg_data

    def _parse_pad_stacks(self, root: ET.Element) -> None:
        """Parse pad stack definitions."""
        for pad_stack in self._findall(root, ".//PadStackDef"):
            ps_name = pad_stack.get("name", "")
            if not ps_name:
                continue

            ps_data: dict[str, Any] = {
                "name": ps_name,
                "hole_diameter": 0.0,
                "pads": {},
            }

            # Parse hole
            hole = self._find(pad_stack, "Hole")
            if hole is not None:
                ps_data["hole_diameter"] = self._parse_float(
                    hole.get("diameter", "0")
                ) * self.unit_factor

            # Parse pad shapes per layer
            for pad_def in self._findall(pad_stack, ".//PadDef"):
                layer = pad_def.get("layerRef", "")
                shape = self._find(pad_def, ".//Shape")
                if shape is not None:
                    ps_data["pads"][layer] = self._parse_shape(shape)

            self._pad_stacks[ps_name] = ps_data

    def _parse_shape(self, shape: ET.Element) -> dict:
        """Parse a shape element."""
        result = {"type": "UNKNOWN", "width": 0.0, "height": 0.0}

        # Check for circle
        circle = self._find(shape, "Circle")
        if circle is not None:
            diameter = self._parse_float(circle.get("diameter", "0")) * self.unit_factor
            result = {"type": "CIRCLE", "width": diameter, "height": diameter}
            return result

        # Check for rectangle
        rect = self._find(shape, "RectCenter")
        if rect is not None:
            width = self._parse_float(rect.get("width", "0")) * self.unit_factor
            height = self._parse_float(rect.get("height", "0")) * self.unit_factor
            result = {"type": "RECTANGLE", "width": width, "height": height}
            return result

        # Check for oval/oblong
        oval = self._find(shape, "Oval")
        if oval is not None:
            width = self._parse_float(oval.get("width", "0")) * self.unit_factor
            height = self._parse_float(oval.get("height", "0")) * self.unit_factor
            result = {"type": "OBLONG", "width": width, "height": height}
            return result

        return result

    def _parse_nets(self, root: ET.Element, data: IPC2581Data) -> None:
        """Parse net definitions."""
        for net in self._findall(root, ".//Net"):
            net_name = net.get("name", "")
            if not net_name:
                continue

            net_obj = IPC2581Net(
                name=net_name,
                net_class=net.get("netClass"),
            )

            # Parse pin references
            for pin_ref in self._findall(net, ".//PinRef"):
                net_obj.pins.append({
                    "component": pin_ref.get("componentRef", ""),
                    "pin": pin_ref.get("pin", ""),
                })

            data.nets.append(net_obj)
            self._net_map[net_name] = net_obj

    def _parse_components(self, root: ET.Element, data: IPC2581Data) -> None:
        """Parse component placements."""
        for component in self._findall(root, ".//Component"):
            ref = component.get("refDes", component.get("name", ""))
            if not ref:
                continue

            package_ref = component.get("packageRef", component.get("part", ""))

            # Get location
            location = self._find(component, "Location")
            x, y, rotation = 0.0, 0.0, 0.0
            if location is not None:
                x = self._parse_float(location.get("x", "0")) * self.unit_factor
                y = self._parse_float(location.get("y", "0")) * self.unit_factor
                rotation = self._parse_float(location.get("rotation", "0"))

            # Determine layer
            layer = component.get("layerRef", component.get("side", "TOP"))
            if layer.upper() in ("BOTTOM", "BOT", "B"):
                layer = "BOTTOM"
            else:
                layer = "TOP"

            # Get mount type
            mount_type = component.get("mountType", "SMD")

            # Get part info from BOM data if available
            part_number = component.get("partNumber")
            manufacturer = component.get("manufacturer")
            description = component.get("description")

            comp = IPC2581Component(
                reference=ref,
                package_ref=package_ref,
                part_number=part_number,
                manufacturer=manufacturer,
                description=description,
                x_mm=x,
                y_mm=y,
                rotation=rotation,
                layer=layer,
                mount_type=mount_type,
            )
            data.components.append(comp)

    def _parse_layer_features(self, root: ET.Element, data: IPC2581Data) -> None:
        """Parse layer features (traces, vias, pads)."""
        for layer_feature in self._findall(root, ".//LayerFeature"):
            layer_name = layer_feature.get("layerRef", "")

            # Parse traces (lines)
            for line in self._findall(layer_feature, ".//Line"):
                x1 = self._parse_float(line.get("startX", "0")) * self.unit_factor
                y1 = self._parse_float(line.get("startY", "0")) * self.unit_factor
                x2 = self._parse_float(line.get("endX", "0")) * self.unit_factor
                y2 = self._parse_float(line.get("endY", "0")) * self.unit_factor
                width = self._parse_float(line.get("width", "0")) * self.unit_factor
                net_name = line.get("net")

                if width > 0:
                    trace = IPC2581Trace(
                        x1_mm=x1,
                        y1_mm=y1,
                        x2_mm=x2,
                        y2_mm=y2,
                        width_mm=width,
                        layer=layer_name,
                        net_name=net_name,
                    )
                    data.traces.append(trace)

            # Parse polylines (multi-segment traces)
            for polyline in self._findall(layer_feature, ".//Polyline"):
                width = self._parse_float(polyline.get("width", "0")) * self.unit_factor
                net_name = polyline.get("net")
                points = []

                for point in self._findall(polyline, ".//PolyBegin") + \
                           self._findall(polyline, ".//PolyStepSegment"):
                    x = self._parse_float(point.get("x", "0")) * self.unit_factor
                    y = self._parse_float(point.get("y", "0")) * self.unit_factor
                    points.append((x, y))

                # Convert to trace segments
                for i in range(len(points) - 1):
                    trace = IPC2581Trace(
                        x1_mm=points[i][0],
                        y1_mm=points[i][1],
                        x2_mm=points[i + 1][0],
                        y2_mm=points[i + 1][1],
                        width_mm=width,
                        layer=layer_name,
                        net_name=net_name,
                    )
                    data.traces.append(trace)

        # Parse vias
        for via in self._findall(root, ".//Via"):
            x = self._parse_float(via.get("x", "0")) * self.unit_factor
            y = self._parse_float(via.get("y", "0")) * self.unit_factor
            pad_stack_ref = via.get("padstackDefRef", "")
            net_name = via.get("net")

            # Get via dimensions from pad stack
            drill = 0.3  # Default
            pad_dia = 0.6  # Default
            if pad_stack_ref in self._pad_stacks:
                ps = self._pad_stacks[pad_stack_ref]
                drill = ps.get("hole_diameter", 0.3)
                # Get pad size from first layer
                for layer_pads in ps.get("pads", {}).values():
                    pad_dia = layer_pads.get("width", 0.6)
                    break

            via_obj = IPC2581Via(
                x_mm=x,
                y_mm=y,
                drill_mm=drill,
                pad_diameter_mm=pad_dia,
                start_layer="TOP",
                end_layer="BOTTOM",
                net_name=net_name,
            )
            data.vias.append(via_obj)

    def _parse_design_rules(self, root: ET.Element, data: IPC2581Data) -> None:
        """Parse design rules."""
        for rule in self._findall(root, ".//Rule"):
            name = rule.get("name", "")
            rule_type = rule.get("type", rule.get("ruleType", ""))
            value = self._parse_float(rule.get("value", "0"))
            unit = rule.get("unit", "MM")

            if name:
                data.design_rules.append(IPC2581DesignRule(
                    name=name,
                    rule_type=rule_type,
                    value=value * UNIT_CONVERSIONS.get(unit.upper(), 1.0),
                    unit="MM",
                ))

        # Also parse from DRC section
        for drc in self._findall(root, ".//DesignRuleCheck"):
            for constraint in self._findall(drc, ".//Constraint"):
                name = constraint.get("name", "")
                value = self._parse_float(constraint.get("value", "0"))

                if name:
                    data.design_rules.append(IPC2581DesignRule(
                        name=name,
                        rule_type="CONSTRAINT",
                        value=value * self.unit_factor,
                        unit="MM",
                    ))

    def _parse_bom(self, root: ET.Element, data: IPC2581Data) -> None:
        """Parse BOM information."""
        # Group components by part number
        bom_map: dict[str, IPC2581BOMItem] = {}

        for comp in data.components:
            if not comp.part_number:
                continue

            key = f"{comp.manufacturer or 'UNKNOWN'}|{comp.part_number}"

            if key not in bom_map:
                bom_map[key] = IPC2581BOMItem(
                    part_number=comp.part_number,
                    manufacturer=comp.manufacturer,
                    description=comp.description,
                    quantity=0,
                    references=[],
                    package=comp.package_ref,
                )

            bom_map[key].quantity += 1
            bom_map[key].references.append(comp.reference)

        # Also parse explicit BOM section if present
        for bom_item in self._findall(root, ".//BomItem"):
            pn = bom_item.get("partNumber", "")
            if not pn:
                continue

            key = f"{bom_item.get('manufacturer', 'UNKNOWN')}|{pn}"

            if key not in bom_map:
                bom_map[key] = IPC2581BOMItem(
                    part_number=pn,
                    manufacturer=bom_item.get("manufacturer"),
                    description=bom_item.get("description"),
                    quantity=int(bom_item.get("quantity", "1")),
                    references=[],
                )

        data.bom_items = list(bom_map.values())

    def _calculate_dimensions(self, data: IPC2581Data) -> None:
        """Calculate board dimensions from geometry if not already set."""
        if data.width_mm > 0 and data.height_mm > 0:
            return

        min_x, min_y = float("inf"), float("inf")
        max_x, max_y = float("-inf"), float("-inf")

        # From traces
        for trace in data.traces:
            for x in [trace.x1_mm, trace.x2_mm]:
                min_x = min(min_x, x)
                max_x = max(max_x, x)
            for y in [trace.y1_mm, trace.y2_mm]:
                min_y = min(min_y, y)
                max_y = max(max_y, y)

        # From components
        for comp in data.components:
            min_x = min(min_x, comp.x_mm)
            max_x = max(max_x, comp.x_mm)
            min_y = min(min_y, comp.y_mm)
            max_y = max(max_y, comp.y_mm)

        # From vias
        for via in data.vias:
            min_x = min(min_x, via.x_mm)
            max_x = max(max_x, via.x_mm)
            min_y = min(min_y, via.y_mm)
            max_y = max(max_y, via.y_mm)

        if min_x != float("inf"):
            # Add margin for component footprints
            data.width_mm = (max_x - min_x) + 10.0
            data.height_mm = (max_y - min_y) + 10.0

    def _calculate_trace_statistics(self, data: IPC2581Data) -> None:
        """Calculate trace length statistics and per-net routed lengths.

        Aggregates total trace length and calculates length per net
        for high-speed analysis.
        """

        # Build net name to net mapping
        net_name_to_net = {net.name: net for net in data.nets}

        # Calculate total trace length and per-net lengths
        net_trace_lengths: dict[str, float] = {}

        for trace in data.traces:
            length = trace.length_mm

            # Add to total
            data.total_trace_length_mm += length

            # Add to per-net length
            if trace.net_name:
                net_trace_lengths[trace.net_name] = (
                    net_trace_lengths.get(trace.net_name, 0) + length
                )

        # Update net objects with routed lengths
        for net_name, length in net_trace_lengths.items():
            if net_name in net_name_to_net:
                net_name_to_net[net_name].routed_length_mm = length

        # Set via count and classify via types
        data.via_count = len(data.vias)

        # Get ordered copper layer names for via classification
        copper_layer_names = [
            layer.name for layer in data.layers
            if layer.layer_type.upper() in ("SIGNAL", "COPPER", "CONDUCTOR")
        ]
        if not copper_layer_names:
            copper_layer_names = ["TOP", "BOTTOM"]  # Default fallback

        # Classify via types based on layer span
        via_type_counts = {"through": 0, "blind": 0, "buried": 0, "microvia": 0}
        for via in data.vias:
            via.via_type = via.classify_via_type(copper_layer_names)
            via_type_counts[via.via_type] = via_type_counts.get(via.via_type, 0) + 1

        logger.debug(f"Trace statistics: total={data.total_trace_length_mm:.1f}mm, "
                    f"nets with routes={len(net_trace_lengths)}, vias={data.via_count}")
        if any(v > 0 for k, v in via_type_counts.items() if k != "through"):
            logger.debug(f"Via types: {via_type_counts}")

    def _parse_float(self, value: str) -> float:
        """Parse float value safely."""
        if not value:
            return 0.0
        try:
            return float(value)
        except ValueError:
            return 0.0


def parse_ipc2581(file_path: str) -> IPC2581Data:
    """Convenience function to parse an IPC-2581 file.

    Args:
        file_path: Path to IPC-2581 file

    Returns:
        IPC2581Data with parsed design data
    """
    parser = IPC2581Parser()
    return parser.parse(file_path)

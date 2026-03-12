"""ODB++ archive parser for complete PCB data extraction"""
import tarfile
import gzip
import os
import re
import math
from pathlib import Path
from typing import Optional, List, Dict, Tuple, BinaryIO
import tempfile
import shutil

from .odb_models import (
    ODBData,
    ODBLayer,
    ODBComponent,
    ODBPin,
    ODBNet,
    ODBVia,
    ODBTrace,
    ODBCopperPour,
    ODBDrill,
    ODBBoardOutline,
    ODBPad,
    LayerType,
    Polarity,
    ViaType,
    PadShape,
)


class ODBParser:
    """
    Complete ODB++ archive parser.

    Supports extraction of:
    - Layer stackup from matrix/matrix
    - Component placement from steps/*/layers/comp_+_*/components
    - Netlist from steps/*/netlists/cadnet/netlist
    - Vias and drills from drill layers
    - Traces and copper pours from layer features
    - Board outline from steps/*/profile

    Usage:
        parser = ODBParser()
        data = parser.parse("design.tgz")
        print(f"Found {len(data.components)} components")
    """

    # Unit conversion constants
    MIL_TO_MM = 0.0254
    INCH_TO_MM = 25.4
    UM_TO_MM = 0.001

    # Layer type mapping
    LAYER_TYPE_MAP = {
        "signal": LayerType.SIGNAL,
        "power_ground": LayerType.PLANE,
        "mixed": LayerType.MIXED,
        "solder_mask": LayerType.SOLDER_MASK,
        "silk_screen": LayerType.SILK_SCREEN,
        "solder_paste": LayerType.SOLDER_PASTE,
        "drill": LayerType.DRILL,
        "document": LayerType.DOCUMENT,
        "component": LayerType.COMPONENT,
        "dielectric": LayerType.DIELECTRIC,
    }

    def __init__(self, work_dir: Optional[str] = None):
        """
        Initialize parser.

        Args:
            work_dir: Directory for extracting archives. Uses temp dir if not specified.
        """
        self.work_dir = Path(work_dir) if work_dir else None
        self._temp_dir: Optional[Path] = None
        self._units = "mil"  # Default units

    def parse(self, archive_path: str) -> ODBData:
        """
        Parse an ODB++ archive file.

        Args:
            archive_path: Path to .tgz or .zip ODB++ archive

        Returns:
            ODBData with all extracted information
        """
        archive_path = Path(archive_path)

        if not archive_path.exists():
            raise FileNotFoundError(f"Archive not found: {archive_path}")

        # Create extraction directory
        extract_dir = self._get_extract_dir(archive_path)

        try:
            # Extract archive
            self._extract_archive(archive_path, extract_dir)

            # Find ODB++ root (may be nested)
            odb_root = self._find_odb_root(extract_dir)

            if not odb_root:
                raise ValueError("Could not find ODB++ structure in archive")

            # Parse all components
            data = ODBData(source_file=str(archive_path))

            # Parse matrix (layer stackup)
            self._parse_matrix(odb_root, data)

            # Parse symbols (pad definitions/dcodes)
            self._parse_symbols(odb_root, data)

            # Get the step name (usually "pcb")
            step_name = self._get_primary_step(odb_root)

            if step_name:
                step_path = odb_root / "steps" / step_name

                # Parse board profile/outline
                self._parse_profile(step_path, data)

                # Parse netlist
                self._parse_netlist(step_path, data)

                # Parse components
                self._parse_components(step_path, data)

                # Parse layer features (traces, pours, vias)
                self._parse_layer_features(step_path, data)

                # Parse drills
                self._parse_drills(step_path, data)

            # Calculate summary statistics
            self._calculate_statistics(data)

            data.is_complete = True

        finally:
            # Cleanup temp directory
            if self._temp_dir and self._temp_dir.exists():
                shutil.rmtree(self._temp_dir)
                self._temp_dir = None

        return data

    def _get_extract_dir(self, archive_path: Path) -> Path:
        """Get or create extraction directory"""
        if self.work_dir:
            extract_dir = self.work_dir / archive_path.stem
            extract_dir.mkdir(parents=True, exist_ok=True)
            return extract_dir
        else:
            self._temp_dir = Path(tempfile.mkdtemp(prefix="odb_"))
            return self._temp_dir

    def _extract_archive(self, archive_path: Path, extract_dir: Path):
        """Extract ODB++ archive (tgz or zip)"""
        archive_str = str(archive_path).lower()

        if archive_str.endswith(('.tgz', '.tar.gz')):
            with tarfile.open(archive_path, 'r:gz') as tar:
                tar.extractall(extract_dir)
        elif archive_str.endswith('.tar'):
            with tarfile.open(archive_path, 'r') as tar:
                tar.extractall(extract_dir)
        elif archive_str.endswith('.zip'):
            import zipfile
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        else:
            raise ValueError(f"Unsupported archive format: {archive_path.suffix}")

    def _find_odb_root(self, extract_dir: Path) -> Optional[Path]:
        """Find the ODB++ root directory (contains matrix folder)"""
        # Check if extract_dir itself is the root
        if (extract_dir / "matrix").exists():
            return extract_dir

        # Check subdirectories
        for item in extract_dir.iterdir():
            if item.is_dir():
                if (item / "matrix").exists():
                    return item
                # Check one level deeper
                for subitem in item.iterdir():
                    if subitem.is_dir() and (subitem / "matrix").exists():
                        return subitem

        return None

    def _get_primary_step(self, odb_root: Path) -> Optional[str]:
        """Get the primary step name (usually 'pcb')"""
        steps_dir = odb_root / "steps"
        if not steps_dir.exists():
            return None

        # Look for common step names
        for name in ["pcb", "panel", "board", "design"]:
            if (steps_dir / name).exists():
                return name

        # Return first step if none of the common names exist
        for item in steps_dir.iterdir():
            if item.is_dir():
                return item.name

        return None

    def _parse_matrix(self, odb_root: Path, data: ODBData):
        """Parse the matrix file for layer stackup"""
        matrix_file = odb_root / "matrix" / "matrix"

        if not matrix_file.exists():
            data.parse_warnings.append("Matrix file not found")
            return

        try:
            content = self._read_file(matrix_file)
            current_layer: Optional[Dict] = None

            for line in content.split('\n'):
                line = line.strip()

                if line.startswith('LAYER'):
                    # Save previous layer
                    if current_layer:
                        data.layers.append(self._create_layer(current_layer))

                    current_layer = {}

                elif line.startswith('END_LAYER') or line == '':
                    if current_layer:
                        data.layers.append(self._create_layer(current_layer))
                        current_layer = None
                
                elif line.startswith('UNITS') or (current_layer is None and 'UNITS' in line):
                     # Global units often at top of matrix or step
                     parts = line.split('=') if '=' in line else line.split()
                     if len(parts) >= 2:
                         unit_val = parts[1].strip().lower()
                         if 'mm' in unit_val:
                             self._units = 'mm'
                         elif 'inch' in unit_val:
                             self._units = 'inch'
                         elif 'mil' in unit_val:
                             self._units = 'mil'

                elif current_layer is not None and '=' in line:
                    # Parse key=value pairs
                    key, _, value = line.partition('=')
                    current_layer[key.strip().lower()] = value.strip()

            # Handle last layer
            if current_layer:
                data.layers.append(self._create_layer(current_layer))

            data.layer_count = len([l for l in data.layers if l.layer_type in
                                    (LayerType.SIGNAL, LayerType.PLANE, LayerType.MIXED)])

        except Exception as e:
            data.parse_errors.append(f"Error parsing matrix: {str(e)}")

    def _create_layer(self, layer_dict: Dict) -> ODBLayer:
        """Create ODBLayer from parsed dictionary"""
        name = layer_dict.get('name', 'unknown')
        row = int(layer_dict.get('row', 0))

        # Determine layer type
        type_str = layer_dict.get('type', 'signal').lower()
        layer_type = self.LAYER_TYPE_MAP.get(type_str, LayerType.SIGNAL)

        # Determine polarity
        polarity_str = layer_dict.get('polarity', 'positive').lower()
        polarity = Polarity.NEGATIVE if polarity_str == 'negative' else Polarity.POSITIVE

        # Parse physical properties
        thickness = None
        # Try common thickness keys used in ODB++ matrix or attributes
        for key in ['val', 'thickness', 'thick', 'height', 'top_height', 'diel_height']:
            if key in layer_dict:
                try:
                    # Strip non-numeric units if present (e.g. '5mil')
                    val_str = ''.join(c for c in layer_dict[key] if c.isdigit() or c == '.' or c == '-')
                    if not val_str: continue
                    val = float(val_str)
                    
                    # Convert to mm
                    if self._units == 'mil':
                        thickness = val * self.MIL_TO_MM
                    elif self._units == 'inch':
                        thickness = val * self.INCH_TO_MM
                    else:
                        thickness = val # Already mm or unknown
                    break
                except ValueError:
                    continue

        # Parse dielectric properties
        dk = None
        df = None
        
        # Dielectric constant keys
        for key in ['diel_const', 'epsilon', 'er', 'dielectric_constant']:
            if key in layer_dict:
                try:
                    dk = float(layer_dict[key])
                    break
                except ValueError: pass

        # Loss tangent keys
        for key in ['loss_tangent', 'tg_d', 'loss_fact']:
             if key in layer_dict:
                try:
                    df = float(layer_dict[key])
                    break
                except ValueError: pass
        
        # If material name is present
        material = layer_dict.get('material', layer_dict.get('mat_name'))

        return ODBLayer(
            name=name,
            row=row,
            layer_type=layer_type,
            polarity=polarity,
            context=layer_dict.get('context', 'board'),
            start_name=layer_dict.get('start_name'),
            end_name=layer_dict.get('end_name'),
            thickness_mm=thickness,
            dielectric_constant=dk,
            loss_tangent=df,
            material=material
        )

    def _parse_symbols(self, odb_root: Path, data: ODBData):
        """Parse symbols directory to get pad/aperture definitions.

        ODB++ symbols define pad shapes and sizes that are referenced by dcodes
        in the features files. This method extracts actual pad dimensions.
        """
        symbols_dir = odb_root / "symbols"

        if not symbols_dir.exists():
            # Try alternative locations
            for alt_name in ["fonts", "symbols"]:
                alt_dir = odb_root / alt_name
                if alt_dir.exists() and alt_dir.is_dir():
                    symbols_dir = alt_dir
                    break
            else:
                data.parse_warnings.append("No symbols directory found - using estimated pad sizes")
                return

        try:
            # Parse each symbol file
            for symbol_file in symbols_dir.iterdir():
                if not symbol_file.is_file():
                    continue

                symbol_name = symbol_file.stem
                content = self._read_file(symbol_file)

                # Parse symbol definition
                pad_info = self._parse_symbol_file(symbol_name, content)
                if pad_info:
                    data.pad_templates[symbol_name] = pad_info

        except Exception as e:
            data.parse_warnings.append(f"Error parsing symbols: {str(e)}")

    def _parse_symbol_file(self, symbol_name: str, content: str) -> Optional[ODBPad]:
        """Parse a single symbol file to extract pad geometry.

        ODB++ symbol files contain feature records that define the pad shape.
        Common patterns:
        - Round pads: r<diameter> or round<diameter>
        - Square pads: s<size> or square<size>
        - Rectangle pads: rect<width>x<height>
        - Oblong pads: oval<width>x<height>
        """
        # Try to parse from symbol name first (common convention)
        pad = self._parse_symbol_name(symbol_name)
        if pad:
            return pad

        # Parse from symbol file content
        width = None
        height = None
        shape = PadShape.ROUND

        for line in content.split('\n'):
            line = line.strip()

            # Look for surface definition with dimensions
            # S P <polarity> - Surface with polarity
            # OB x y - Outline boundary point
            if line.startswith('OB '):
                parts = line.split()
                if len(parts) >= 3:
                    x = abs(self._convert_coord(parts[1]))
                    y = abs(self._convert_coord(parts[2]))
                    if x > 0:
                        width = max(width or 0, x * 2)
                    if y > 0:
                        height = max(height or 0, y * 2)

            # Circle record: CR x y r
            elif line.startswith('CR '):
                parts = line.split()
                if len(parts) >= 4:
                    r = self._convert_coord(parts[3])
                    if r > 0:
                        width = r * 2
                        height = r * 2
                        shape = PadShape.ROUND

            # Round pad: P x y ... with round symbol
            elif line.startswith('#') and 'round' in line.lower():
                shape = PadShape.ROUND

            # Rectangle indicator
            elif line.startswith('#') and ('rect' in line.lower() or 'square' in line.lower()):
                shape = PadShape.RECTANGLE if 'rect' in line.lower() else PadShape.SQUARE

        # If we found dimensions, create pad
        if width and width > 0:
            return ODBPad(
                name=symbol_name,
                shape=shape,
                width_mm=width,
                height_mm=height if height else width,
            )

        return None

    def _parse_symbol_name(self, name: str) -> Optional[ODBPad]:
        """Parse pad dimensions from symbol name convention.

        Common ODB++ symbol naming conventions:
        - r100 = round 100 mil diameter
        - s50 = square 50 mil
        - rect60x100 = rectangle 60x100 mil
        - oval80x120 = oval 80x120 mil
        - via30 = via 30 mil diameter
        """
        name_lower = name.lower()

        # Round pad: r<diameter> or round<diameter>
        round_match = re.match(r'^r(?:ound)?(\d+(?:\.\d+)?)', name_lower)
        if round_match:
            size = float(round_match.group(1))
            # Convert from mil to mm (typical ODB++ convention)
            size_mm = size * self.MIL_TO_MM
            return ODBPad(
                name=name,
                shape=PadShape.ROUND,
                width_mm=size_mm,
                height_mm=size_mm,
            )

        # Square pad: s<size> or square<size>
        square_match = re.match(r'^s(?:quare)?(\d+(?:\.\d+)?)', name_lower)
        if square_match:
            size = float(square_match.group(1))
            size_mm = size * self.MIL_TO_MM
            return ODBPad(
                name=name,
                shape=PadShape.SQUARE,
                width_mm=size_mm,
                height_mm=size_mm,
            )

        # Rectangle pad: rect<w>x<h>
        rect_match = re.match(r'^rect(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)', name_lower)
        if rect_match:
            width = float(rect_match.group(1)) * self.MIL_TO_MM
            height = float(rect_match.group(2)) * self.MIL_TO_MM
            return ODBPad(
                name=name,
                shape=PadShape.RECTANGLE,
                width_mm=width,
                height_mm=height,
            )

        # Oval/oblong pad: oval<w>x<h>
        oval_match = re.match(r'^o(?:val)?(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)', name_lower)
        if oval_match:
            width = float(oval_match.group(1)) * self.MIL_TO_MM
            height = float(oval_match.group(2)) * self.MIL_TO_MM
            return ODBPad(
                name=name,
                shape=PadShape.OBLONG,
                width_mm=width,
                height_mm=height,
            )

        # Via pad: via<diameter>
        via_match = re.match(r'^via(\d+(?:\.\d+)?)', name_lower)
        if via_match:
            size = float(via_match.group(1)) * self.MIL_TO_MM
            return ODBPad(
                name=name,
                shape=PadShape.ROUND,
                width_mm=size,
                height_mm=size,
            )

        # Donut pad: donut<outer>x<inner>
        donut_match = re.match(r'^donut(\d+(?:\.\d+)?)(?:x(\d+(?:\.\d+)?))?', name_lower)
        if donut_match:
            outer = float(donut_match.group(1)) * self.MIL_TO_MM
            return ODBPad(
                name=name,
                shape=PadShape.DONUT,
                width_mm=outer,
                height_mm=outer,
            )

        return None

    def _parse_profile(self, step_path: Path, data: ODBData):
        """Parse board profile/outline"""
        profile_file = step_path / "profile"

        if not profile_file.exists():
            return

        try:
            content = self._read_file(profile_file)
            outline_points = []

            for line in content.split('\n'):
                line = line.strip()

                # Parse OB (outline boundary) records
                if line.startswith('OB'):
                    # Format: OB x y [arc params]
                    parts = line.split()
                    if len(parts) >= 3:
                        x = self._convert_coord(parts[1])
                        y = self._convert_coord(parts[2])
                        outline_points.append((x, y))

                # Parse OS (outline start)
                elif line.startswith('OS'):
                    parts = line.split()
                    if len(parts) >= 3:
                        x = self._convert_coord(parts[1])
                        y = self._convert_coord(parts[2])
                        outline_points.append((x, y))

            if outline_points:
                # Calculate bounding box
                xs = [p[0] for p in outline_points]
                ys = [p[1] for p in outline_points]

                data.outline = ODBBoardOutline(
                    outline=outline_points,
                    width_mm=max(xs) - min(xs),
                    height_mm=max(ys) - min(ys),
                    origin_x_mm=min(xs),
                    origin_y_mm=min(ys),
                )

        except Exception as e:
            data.parse_warnings.append(f"Error parsing profile: {str(e)}")

    def _parse_netlist(self, step_path: Path, data: ODBData):
        """Parse netlist from cadnet or other netlist formats"""
        netlist_dir = step_path / "netlists"

        if not netlist_dir.exists():
            return

        # Try cadnet first (most common)
        cadnet_file = netlist_dir / "cadnet" / "netlist"
        if not cadnet_file.exists():
            # Try other netlist formats
            for subdir in netlist_dir.iterdir():
                if subdir.is_dir():
                    netlist_file = subdir / "netlist"
                    if netlist_file.exists():
                        cadnet_file = netlist_file
                        break

        if not cadnet_file.exists():
            return

        try:
            content = self._read_file(cadnet_file)
            current_net: Optional[Dict] = None

            for line in content.split('\n'):
                line = line.strip()

                if line.startswith('$'):
                    # Net header: $net_number net_name
                    if current_net:
                        data.nets.append(self._create_net(current_net))

                    parts = line[1:].split(None, 1)
                    net_num = int(parts[0]) if parts else 0
                    net_name = parts[1] if len(parts) > 1 else f"NET_{net_num}"

                    current_net = {
                        'number': net_num,
                        'name': net_name,
                        'pins': []
                    }

                elif current_net and line:
                    # Pin reference: component.pin
                    if '.' in line or '-' in line:
                        current_net['pins'].append(line)

            # Handle last net
            if current_net:
                data.nets.append(self._create_net(current_net))

            data.net_count = len(data.nets)

        except Exception as e:
            data.parse_warnings.append(f"Error parsing netlist: {str(e)}")

    def _create_net(self, net_dict: Dict) -> ODBNet:
        """Create ODBNet from parsed dictionary"""
        return ODBNet(
            name=net_dict.get('name', 'unknown'),
            net_number=net_dict.get('number', 0),
            pins=net_dict.get('pins', []),
        )

    def _parse_components(self, step_path: Path, data: ODBData):
        """Parse component placement from component layers"""
        layers_dir = step_path / "layers"

        if not layers_dir.exists():
            return

        # Parse top components
        for layer_name in ["comp_+_top", "comp+top", "component_top"]:
            comp_dir = layers_dir / layer_name
            if comp_dir.exists():
                self._parse_component_layer(comp_dir, data, "top")
                break

        # Parse bottom components
        for layer_name in ["comp_+_bot", "comp+bot", "component_bot", "comp_+_bottom"]:
            comp_dir = layers_dir / layer_name
            if comp_dir.exists():
                self._parse_component_layer(comp_dir, data, "bottom")
                break

        data.component_count = len(data.components)

    def _parse_component_layer(self, comp_dir: Path, data: ODBData, layer: str):
        """Parse components from a component layer directory"""
        components_file = comp_dir / "components"

        if not components_file.exists():
            return

        try:
            content = self._read_file(components_file)
            current_comp: Optional[Dict] = None

            for line in content.split('\n'):
                line = line.strip()

                if line.startswith('CMP'):
                    # Save previous component
                    if current_comp:
                        data.components.append(self._create_component(current_comp, layer))

                    current_comp = {'pins': []}

                elif line.startswith('PRP'):
                    # Property: PRP key value
                    if current_comp:
                        parts = line[3:].strip().split(None, 1)
                        if len(parts) >= 2:
                            key = parts[0].lower()
                            value = parts[1].strip("'\"")
                            current_comp[key] = value

                elif line.startswith('TOP'):
                    # Placement: TOP x y rotation mirror
                    if current_comp:
                        parts = line.split()
                        if len(parts) >= 4:
                            current_comp['x'] = self._convert_coord(parts[1])
                            current_comp['y'] = self._convert_coord(parts[2])
                            current_comp['rotation'] = float(parts[3])
                            current_comp['mirror'] = len(parts) > 4 and parts[4].upper() == 'M'

                elif line.startswith('PIN'):
                    # Pin definition
                    if current_comp:
                        pin_data = self._parse_pin_line(line)
                        if pin_data:
                            current_comp['pins'].append(pin_data)

            # Handle last component
            if current_comp:
                data.components.append(self._create_component(current_comp, layer))

        except Exception as e:
            data.parse_warnings.append(f"Error parsing component layer {layer}: {str(e)}")

    def _parse_pin_line(self, line: str) -> Optional[Dict]:
        """Parse a PIN line from component file"""
        # Format varies, but typically: PIN name x y type [other params]
        parts = line.split()
        if len(parts) < 4:
            return None

        return {
            'name': parts[1],
            'x': self._convert_coord(parts[2]) if len(parts) > 2 else 0,
            'y': self._convert_coord(parts[3]) if len(parts) > 3 else 0,
        }

    def _create_component(self, comp_dict: Dict, layer: str) -> ODBComponent:
        """Create ODBComponent from parsed dictionary"""
        pins = []
        for pin_data in comp_dict.get('pins', []):
            pins.append(ODBPin(
                pin_number=pin_data.get('name', ''),
                x_offset_mm=pin_data.get('x', 0),
                y_offset_mm=pin_data.get('y', 0),
            ))

        return ODBComponent(
            ref_des=comp_dict.get('comp_name', comp_dict.get('refdes', 'unknown')),
            part_name=comp_dict.get('part_name', comp_dict.get('part', '')),
            package=comp_dict.get('package', comp_dict.get('pkg', '')),
            x_mm=comp_dict.get('x', 0),
            y_mm=comp_dict.get('y', 0),
            rotation_deg=comp_dict.get('rotation', 0),
            mirror=comp_dict.get('mirror', False),
            layer=layer,
            pins=pins,
        )

    def _parse_layer_features(self, step_path: Path, data: ODBData):
        """Parse features from signal/plane layers"""
        layers_dir = step_path / "layers"

        if not layers_dir.exists():
            return

        for layer_info in data.layers:
            if layer_info.layer_type not in (LayerType.SIGNAL, LayerType.PLANE, LayerType.MIXED):
                continue

            layer_dir = layers_dir / layer_info.name
            if not layer_dir.exists():
                # Try without case sensitivity
                for d in layers_dir.iterdir():
                    if d.name.lower() == layer_info.name.lower():
                        layer_dir = d
                        break

            if layer_dir.exists():
                self._parse_features_file(layer_dir, layer_info.name, data)

    def _parse_features_file(self, layer_dir: Path, layer_name: str, data: ODBData):
        """Parse the features file for a layer"""
        features_file = layer_dir / "features"

        if not features_file.exists():
            # May be compressed
            features_gz = layer_dir / "features.gz"
            if features_gz.exists():
                try:
                    with gzip.open(features_gz, 'rt', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                except Exception as e:
                    data.parse_warnings.append(
                        f"Failed to read compressed features for layer {layer_name}: {e}"
                    )
                    return
            else:
                return
        else:
            content = self._read_file(features_file)

        traces = []
        pours = []
        current_points = []
        current_width = 0.1  # Default width in mm

        for line in content.split('\n'):
            line = line.strip()

            # Line/trace: L x1 y1 x2 y2
            if line.startswith('L '):
                parts = line.split()
                if len(parts) >= 5:
                    x1 = self._convert_coord(parts[1])
                    y1 = self._convert_coord(parts[2])
                    x2 = self._convert_coord(parts[3])
                    y2 = self._convert_coord(parts[4])

                    length = math.sqrt((x2-x1)**2 + (y2-y1)**2)

                    traces.append(ODBTrace(
                        layer=layer_name,
                        width_mm=current_width,
                        points=[(x1, y1), (x2, y2)],
                        length_mm=length,
                    ))

            # Arc: A x1 y1 x2 y2 xc yc cw/ccw
            elif line.startswith('A '):
                # Simplified - treat as line between endpoints
                parts = line.split()
                if len(parts) >= 5:
                    x1 = self._convert_coord(parts[1])
                    y1 = self._convert_coord(parts[2])
                    x2 = self._convert_coord(parts[3])
                    y2 = self._convert_coord(parts[4])

                    traces.append(ODBTrace(
                        layer=layer_name,
                        width_mm=current_width,
                        points=[(x1, y1), (x2, y2)],
                    ))

            # Pad: P x y dcode rotation mirror
            elif line.startswith('P '):
                # Pad - could be via pad
                parts = line.split()
                if len(parts) >= 3:
                    x = self._convert_coord(parts[1])
                    y = self._convert_coord(parts[2])
                    # Store as potential via location
                    # Full via detection would require cross-referencing with drill data

            # Surface (copper pour) start: S P <polarity>
            elif line.startswith('S ') and 'P' in line:
                current_points = []

            # Surface boundary: OB x y
            elif line.startswith('OB '):
                parts = line.split()
                if len(parts) >= 3:
                    x = self._convert_coord(parts[1])
                    y = self._convert_coord(parts[2])
                    current_points.append((x, y))

            # Surface end: SE
            elif line.startswith('SE') and current_points:
                pours.append(ODBCopperPour(
                    layer=layer_name,
                    boundary=current_points.copy(),
                ))
                current_points = []

        # Store parsed data
        if traces:
            data.traces[layer_name] = traces
        if pours:
            data.copper_pours[layer_name] = pours

    def _parse_drills(self, step_path: Path, data: ODBData):
        """Parse drill hits from drill layers"""
        layers_dir = step_path / "layers"

        if not layers_dir.exists():
            return

        # Find drill layers
        for layer_info in data.layers:
            if layer_info.layer_type != LayerType.DRILL:
                continue

            layer_dir = layers_dir / layer_info.name
            if layer_dir.exists():
                self._parse_drill_features(layer_dir, layer_info, data)

        # Also check for common drill layer names
        for drill_name in ["drill", "drl", "pth", "npth"]:
            drill_dir = layers_dir / drill_name
            if drill_dir.exists():
                self._parse_drill_features(drill_dir, None, data)

    def _parse_drill_features(self, layer_dir: Path, layer_info: Optional[ODBLayer], data: ODBData):
        """Parse drill hits from a drill layer.

        Extracts actual pad sizes from symbol definitions (dcodes) instead of
        using hardcoded estimates. Falls back to industry-standard annular ring
        calculations if symbol data is unavailable.
        """
        features_file = layer_dir / "features"

        if not features_file.exists():
            return

        try:
            content = self._read_file(features_file)
            current_tool_size = 0.3  # Default drill size mm
            current_dcode = None
            tool_sizes: Dict[str, float] = {}

            # First pass: parse tool definitions (T records)
            for line in content.split('\n'):
                line = line.strip()

                # Tool definition: T<dcode> <size> [type]
                if line.startswith('T') and not line.startswith('TOP'):
                    match = re.match(r'T(\d+)\s+(\d+(?:\.\d+)?)', line)
                    if match:
                        dcode = match.group(1)
                        size = self._convert_coord(match.group(2))
                        tool_sizes[dcode] = size

            # Second pass: parse drill hits
            for line in content.split('\n'):
                line = line.strip()

                # Pad (drill hit): P x y dcode [rotation] [mirror]
                if line.startswith('P '):
                    parts = line.split()
                    if len(parts) >= 3:
                        x = self._convert_coord(parts[1])
                        y = self._convert_coord(parts[2])

                        # Extract dcode if present (4th field or parse from symbol ref)
                        dcode = None
                        if len(parts) >= 4:
                            dcode_str = parts[3]
                            # Remove any non-numeric prefix
                            dcode_match = re.search(r'(\d+)', dcode_str)
                            if dcode_match:
                                dcode = dcode_match.group(1)

                        # Get drill size from tool definition or current
                        drill_size = tool_sizes.get(dcode, current_tool_size) if dcode else current_tool_size

                        # Get pad size from symbol templates
                        pad_size = self._get_via_pad_size(dcode, drill_size, data)

                        data.drills.append(ODBDrill(
                            x_mm=x,
                            y_mm=y,
                            diameter_mm=drill_size,
                        ))

                        # Create via from drill if this is a plated hole
                        data.vias.append(ODBVia(
                            x_mm=x,
                            y_mm=y,
                            drill_diameter_mm=drill_size,
                            pad_top_mm=pad_size,
                            pad_bottom_mm=pad_size,
                            pad_inner_mm=pad_size,  # Assume same for inner layers
                        ))

        except Exception as e:
            data.parse_warnings.append(f"Error parsing drill layer: {str(e)}")

    def _get_via_pad_size(self, dcode: Optional[str], drill_size: float, data: ODBData) -> float:
        """Get via pad size from symbol definition or calculate based on drill size.

        Lookup priority:
        1. Symbol definition from parsed pad_templates (actual design data)
        2. Industry-standard annular ring calculation

        Args:
            dcode: Symbol/dcode reference from drill feature
            drill_size: Drill diameter in mm
            data: Parsed ODB data containing pad templates

        Returns:
            Pad diameter in mm
        """
        # Try to find actual pad size from symbols
        if dcode and data.pad_templates:
            # Try exact dcode match
            for symbol_name, pad in data.pad_templates.items():
                if dcode in symbol_name or symbol_name.endswith(dcode):
                    return max(pad.width_mm, pad.height_mm)

            # Try via-specific symbols
            for symbol_name, pad in data.pad_templates.items():
                if 'via' in symbol_name.lower():
                    return max(pad.width_mm, pad.height_mm)

        # Calculate using industry-standard annular ring
        # IPC-2221 Class 2 minimum annular ring: 0.15mm (6 mil) per side
        # For vias, typical annular ring is 0.1-0.15mm per side
        min_annular_ring = 0.10  # mm per side (conservative for modern fab)

        # Standard via pad sizes based on drill size:
        # - Drill 0.2mm: Pad 0.45mm (typical)
        # - Drill 0.3mm: Pad 0.55mm (typical)
        # - Drill 0.4mm: Pad 0.65mm (typical)
        # Formula: pad = drill + 2 * annular_ring
        calculated_pad = drill_size + (2 * min_annular_ring)

        # Minimum pad size for manufacturability
        min_pad_size = 0.4  # mm

        return max(calculated_pad, min_pad_size)

    def _calculate_statistics(self, data: ODBData):
        """Calculate summary statistics for parsed data"""
        # Count vias
        data.via_count = len(data.vias)

        # Calculate total trace lengths per net
        net_trace_lengths: Dict[str, float] = {}
        for layer_name, traces in data.traces.items():
            for trace in traces:
                if trace.net_name:
                    net_trace_lengths[trace.net_name] = (
                        net_trace_lengths.get(trace.net_name, 0) +
                        (trace.length_mm or 0)
                    )

        # Update nets with routed lengths
        for net in data.nets:
            net.routed_length_mm = net_trace_lengths.get(net.name, 0)

        # Calculate board area if outline exists
        if data.outline and data.outline.outline:
            data.outline.area_mm2 = self._calculate_polygon_area(data.outline.outline)

        # Estimate total stackup thickness
        total_thickness = 0
        for layer in data.layers:
            if layer.thickness_mm:
                total_thickness += layer.thickness_mm
        if total_thickness > 0:
            data.total_thickness_mm = total_thickness

    def _calculate_polygon_area(self, points: List[Tuple[float, float]]) -> float:
        """Calculate area of polygon using shoelace formula"""
        if len(points) < 3:
            return 0

        n = len(points)
        area = 0
        for i in range(n):
            j = (i + 1) % n
            area += points[i][0] * points[j][1]
            area -= points[j][0] * points[i][1]

        return abs(area) / 2

    def _read_file(self, file_path: Path) -> str:
        """Read file content, handling both plain and compressed files"""
        if str(file_path).endswith('.gz'):
            with gzip.open(file_path, 'rt', encoding='utf-8', errors='ignore') as f:
                return f.read()
        else:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
            except UnicodeDecodeError:
                with open(file_path, 'r', encoding='latin-1') as f:
                    return f.read()

    def _convert_coord(self, value: str) -> float:
        """Convert coordinate string to mm"""
        try:
            num = float(value)
            # ODB++ typically uses mils
            return num * self.MIL_TO_MM
        except ValueError:
            return 0.0

    def parse_from_bytes(self, data: bytes, filename: str = "design.tgz") -> ODBData:
        """
        Parse ODB++ from bytes (e.g., from uploaded file).

        Args:
            data: Raw bytes of the archive
            filename: Original filename for format detection

        Returns:
            ODBData with all extracted information
        """
        # Create temp file
        temp_path = Path(tempfile.mktemp(suffix=Path(filename).suffix))

        try:
            with open(temp_path, 'wb') as f:
                f.write(data)

            return self.parse(str(temp_path))

        finally:
            if temp_path.exists():
                temp_path.unlink()

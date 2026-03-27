"""ODB++ archive parser for complete PCB data extraction"""
from __future__ import annotations

import gzip
import math
import os
import re
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Tuple

from .odb_models import (
    LayerType,
    ODBBoardOutline,
    ODBComponent,
    ODBCopperPour,
    ODBData,
    ODBDesignRule,
    ODBDrill,
    ODBLayer,
    ODBNet,
    ODBPad,
    ODBPadStack,
    ODBPin,
    ODBTrace,
    ODBVia,
    PadShape,
    Polarity,
    ViaType,
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
        archive_path_p = Path(archive_path)

        if not archive_path_p.exists():
            raise FileNotFoundError(f"Archive not found: {archive_path_p}")

        # Create extraction directory
        extract_dir = self._get_extract_dir(archive_path_p)

        try:
            # Extract archive
            self._extract_archive(archive_path_p, extract_dir)

            # Find ODB++ root (may be nested)
            odb_root = self._find_odb_root(extract_dir)

            if not odb_root:
                raise ValueError("Could not find ODB++ structure in archive")

            # Parse all components
            data = ODBData(source_file=str(archive_path))

            # Parse matrix (layer stackup)
            self._parse_matrix(odb_root, data)

            # Classify layer types using name heuristics (Fix 1.5)
            self._classify_layer_types(data)

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

                # Build net_num -> name lookup for feature parsing (Fix 1.1)
                net_num_to_name: Dict[int, str] = {
                    n.net_number: n.name for n in data.nets
                }

                # Parse layer stackup from attrlists (Fix 1.4)
                self._parse_layer_stackup_attrlists(step_path, data)

                # Parse EDA data for net-feature mapping (Fix 1.6)
                self._parse_eda_data(step_path, data)

                # Parse components
                self._parse_components(step_path, data)

                # Parse layer features (traces, pours, vias) with net mapping
                self._parse_layer_features(step_path, data, net_num_to_name)

                # Parse drills with net mapping and layer spans
                self._parse_drills(step_path, data, net_num_to_name)

                # Parse layer-level attributes (design rules per layer)
                self._parse_layer_attributes(step_path, data)

            # Parse design-level attributes and design rules from misc/attrlist
            self._parse_misc_attributes(odb_root, data)

            # Parse manufacturing notes from misc/info
            self._parse_misc_info(odb_root, data)

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

    @staticmethod
    def _validate_tar_members(
        tar: tarfile.TarFile, extract_dir: Path
    ) -> list[tarfile.TarInfo]:
        """Return tar members whose paths resolve within *extract_dir*.

        Raises ``ValueError`` on any path-traversal attempt (Zip-Slip).
        """
        safe: list[tarfile.TarInfo] = []
        resolved = extract_dir.resolve()
        for member in tar.getmembers():
            target = (resolved / member.name).resolve()
            if not str(target).startswith(str(resolved) + os.sep) and target != resolved:
                raise ValueError(
                    f"Blocked path-traversal in tar member: {member.name}"
                )
            safe.append(member)
        return safe

    @staticmethod
    def _validate_zip_members(
        zip_ref: zipfile.ZipFile, extract_dir: Path
    ) -> list[str]:
        """Return zip member names whose paths resolve within *extract_dir*.

        Raises ``ValueError`` on any path-traversal attempt (Zip-Slip).
        """
        safe: list[str] = []
        resolved = extract_dir.resolve()
        for name in zip_ref.namelist():
            target = (resolved / name).resolve()
            if not str(target).startswith(str(resolved) + os.sep) and target != resolved:
                raise ValueError(
                    f"Blocked path-traversal in zip member: {name}"
                )
            safe.append(name)
        return safe

    def _extract_archive(self, archive_path: Path, extract_dir: Path) -> None:
        """Extract ODB++ archive (tgz or zip) with path-traversal protection."""
        archive_str = str(archive_path).lower()

        if archive_str.endswith(('.tgz', '.tar.gz')):
            with tarfile.open(archive_path, 'r:gz') as tar:
                safe_members = self._validate_tar_members(tar, extract_dir)
                tar.extractall(extract_dir, members=safe_members)
        elif archive_str.endswith('.tar'):
            with tarfile.open(archive_path, 'r') as tar:
                safe_members = self._validate_tar_members(tar, extract_dir)
                tar.extractall(extract_dir, members=safe_members)
        elif archive_str.endswith('.zip'):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                self._validate_zip_members(zip_ref, extract_dir)
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

    def _parse_matrix(self, odb_root: Path, data: ODBData) -> None:
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

                elif line == '':
                    continue
                elif line.startswith('END_LAYER'):
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

    def _classify_layer_types(self, data: ODBData) -> None:
        """Reclassify copper layer types based on naming conventions.

        ODB++ exports all copper layers as TYPE=SIGNAL, even ground/power planes.
        This heuristic reclassifies based on layer name patterns and polarity.
        """
        for layer in data.layers:
            if layer.layer_type not in (LayerType.SIGNAL, LayerType.MIXED):
                continue
            name_upper = layer.name.upper()
            # Ground plane detection
            if any(kw in name_upper for kw in ['_GND', 'GROUND', '_VSS', '_DGND', '_AGND']):
                layer.layer_type = LayerType.PLANE
            # Power plane detection
            elif any(kw in name_upper for kw in ['_PWR', 'POWER', '_VCC', '_VDD']):
                layer.layer_type = LayerType.PLANE
            # Negative polarity layers are typically planes
            elif layer.polarity == Polarity.NEGATIVE:
                layer.layer_type = LayerType.PLANE

    def _parse_layer_stackup_attrlists(self, step_path: Path, data: ODBData) -> None:
        """Parse per-layer attrlist files for stackup properties (Fix 1.4).

        ODB++ stores layer physical properties in attrlist files:
        - .layer_dielectric: layer thickness (in file units)
        - .dielectric_constant: relative permittivity (Er)
        - .loss_tangent: dissipation factor (Df)
        - .copper_weight: copper weight in oz
        """
        layers_dir = step_path / "layers"
        if not layers_dir.exists():
            return

        # Build case-insensitive directory lookup
        dir_map: Dict[str, Path] = {}
        for d in layers_dir.iterdir():
            if d.is_dir():
                dir_map[d.name.lower()] = d

        for layer_info in data.layers:
            layer_dir = dir_map.get(layer_info.name.lower())
            if not layer_dir:
                continue

            attrlist_file = layer_dir / "attrlist"
            if not attrlist_file.exists():
                continue

            try:
                content = self._read_file(attrlist_file)
                # Detect units for this file
                file_units = self._units
                for line in content.split('\n')[:5]:
                    if line.strip().startswith('UNITS='):
                        unit_val = line.split('=', 1)[1].strip().lower()
                        if 'mm' in unit_val:
                            file_units = 'mm'
                        elif 'inch' in unit_val:
                            file_units = 'inch'
                        elif 'mil' in unit_val:
                            file_units = 'mil'

                for line in content.split('\n'):
                    line = line.strip()
                    if not line.startswith('.') or '=' not in line:
                        continue

                    key, _, value = line.partition('=')
                    attr_name = key.strip().lstrip('.').lower()
                    value_str = value.strip().strip("'\"")

                    try:
                        num_str = re.sub(r'[a-zA-Z]+$', '', value_str).strip()
                        if not num_str:
                            continue
                        num_val = float(num_str)
                    except ValueError:
                        continue

                    # Layer thickness
                    if attr_name == 'layer_dielectric' and num_val > 0:
                        if file_units == 'inch':
                            layer_info.thickness_mm = num_val * self.INCH_TO_MM
                        elif file_units == 'mil':
                            layer_info.thickness_mm = num_val * self.MIL_TO_MM
                        else:
                            layer_info.thickness_mm = num_val

                    # Dielectric constant
                    elif attr_name == 'dielectric_constant' and num_val > 1.0:
                        layer_info.dielectric_constant = num_val

                    # Loss tangent
                    elif attr_name == 'loss_tangent' and num_val >= 0:
                        layer_info.loss_tangent = num_val

                    # Copper weight
                    elif attr_name == 'copper_weight' and num_val > 0:
                        layer_info.copper_weight_oz = num_val

                    # Material name
                    elif attr_name == 'dielectric_name':
                        layer_info.material = value_str

            except Exception as e:
                data.parse_warnings.append(
                    f"Error parsing stackup attrlist for {layer_info.name}: {e}"
                )

    def _parse_eda_data(self, step_path: Path, data: ODBData) -> None:
        """Parse EDA data file for net-feature mapping and pin connectivity.

        Altium (and some other EDA tools) export ODB++ with net_num=0 on all
        feature records. The authoritative net-to-feature mapping is in the
        EDA data file via FID (Feature ID) records:

        - LYR <layer1> <layer2> ...: Layer index mapping
        - NET <net_name>: Current net scope
        - SNT TRC: SubNet Trace
        - SNT VIA: SubNet Via
        - SNT TOP B <comp> <pin>: SubNet component pin
        - FID C <layer_idx> <feature_idx>: Copper feature mapping
        - FID H <layer_idx> <feature_idx>: Drill/hole feature mapping
        """
        eda_file = step_path / "eda" / "data"
        if not eda_file.exists():
            return

        try:
            content = self._read_file(eda_file)
            lines = content.split('\n')

            # Parse LYR line for layer index → layer name mapping
            eda_layer_map: Dict[int, str] = {}
            for line in lines:
                if line.startswith('LYR '):
                    layer_names = line[4:].split()
                    for i, name in enumerate(layer_names):
                        eda_layer_map[i] = name.lower()
                    break

            # Build feature-to-net mapping: (layer_name, feature_idx) → net_name
            # Also collect pin counts and via FIDs
            current_net_name: Optional[str] = None
            pin_count_per_net: Dict[str, int] = {}
            subnet_type: Optional[str] = None  # 'TRC', 'VIA', 'TOP', 'BOT'

            # Store mappings
            self._eda_trace_map: Dict[str, Dict[int, str]] = {}  # layer_name → {feature_idx → net_name}
            self._eda_via_map: Dict[str, Dict[int, str]] = {}  # layer_name → {feature_idx → net_name}

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                if line.startswith('NET '):
                    current_net_name = line[4:].strip()
                    if current_net_name not in pin_count_per_net:
                        pin_count_per_net[current_net_name] = 0
                    subnet_type = None

                elif line.startswith('SNT '):
                    parts = line.split()
                    if len(parts) >= 2:
                        subnet_type = parts[1]  # TRC, VIA, TOP, BOT, PLN
                    if subnet_type in ('TOP', 'BOT') and current_net_name:
                        pin_count_per_net[current_net_name] = (
                            pin_count_per_net.get(current_net_name, 0) + 1
                        )

                elif line.startswith('FID ') and current_net_name:
                    parts = line.split()
                    if len(parts) >= 4:
                        fid_type = parts[1]  # C=copper, H=drill/hole
                        try:
                            layer_idx = int(parts[2])
                            feature_idx = int(parts[3])
                        except (ValueError, IndexError):
                            continue

                        layer_name = eda_layer_map.get(layer_idx, f"layer_{layer_idx}")

                        if fid_type == 'C':
                            if layer_name not in self._eda_trace_map:
                                self._eda_trace_map[layer_name] = {}
                            self._eda_trace_map[layer_name][feature_idx] = current_net_name
                        elif fid_type == 'H':
                            if layer_name not in self._eda_via_map:
                                self._eda_via_map[layer_name] = {}
                            self._eda_via_map[layer_name][feature_idx] = current_net_name

            # Update net objects with pin counts
            for net in data.nets:
                count = pin_count_per_net.get(net.name, 0)
                if count > 0 and len(net.pins) < count:
                    net.pins = [f"pin_{i}" for i in range(count)]

        except Exception as e:
            data.parse_warnings.append(f"Error parsing EDA data: {e}")
            self._eda_trace_map = {}
            self._eda_via_map = {}

    def _parse_symbols(self, odb_root: Path, data: ODBData) -> None:
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

    def _parse_profile(self, step_path: Path, data: ODBData) -> None:
        """Parse board profile/outline"""
        profile_file = step_path / "profile"

        if not profile_file.exists():
            return

        try:
            content = self._read_file(profile_file)
            self._detect_file_units(content)
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

    def _parse_netlist(self, step_path: Path, data: ODBData) -> None:
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

    def _parse_components(self, step_path: Path, data: ODBData) -> None:
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

    def _parse_component_layer(self, comp_dir: Path, data: ODBData, layer: str) -> None:
        """Parse components from a component layer directory"""
        components_file = comp_dir / "components"

        if not components_file.exists():
            return

        try:
            content = self._read_file(components_file)
            self._detect_file_units(content)
            current_comp: Dict[str, Any] | None = None

            for line in content.split('\n'):
                line = line.strip()

                if line.startswith('CMP'):
                    # Save previous component
                    if current_comp:
                        data.components.append(self._create_component(current_comp, layer))

                    # Parse CMP line: CMP <pkg_ref> <x> <y> <rotation> <mirror> <refdes> <part_name> ;attrs
                    current_comp = {'pins': []}
                    # Strip trailing attributes after ';'
                    cmp_line = line.split(';')[0].strip()
                    cmp_parts = cmp_line.split()
                    # CMP <pkg_ref> <x> <y> <rotation> <mirror> [refdes] [part_name]
                    if len(cmp_parts) >= 6:
                        current_comp['x'] = self._convert_coord(cmp_parts[2])
                        current_comp['y'] = self._convert_coord(cmp_parts[3])
                        current_comp['rotation'] = float(cmp_parts[4])
                        current_comp['mirror'] = cmp_parts[5].upper() == 'M'
                    if len(cmp_parts) >= 7:
                        current_comp['comp_name'] = cmp_parts[6]
                    if len(cmp_parts) >= 8:
                        current_comp['part_name'] = cmp_parts[7]

                elif line.startswith('PRP'):
                    # Property: PRP key value
                    if current_comp:
                        parts = line[3:].strip().split(None, 1)
                        if len(parts) >= 2:
                            key = parts[0].lower()
                            value = parts[1].strip("'\"")
                            current_comp[key] = value

                elif line.startswith('TOP'):
                    # Pin placement: TOP <pin_num> <x> <y> <rotation> <mirror> <net_num> <subnet_num> <toeprint_num>
                    if current_comp:
                        parts = line.split()
                        if len(parts) >= 5:
                            pin_data = {
                                'name': parts[1],
                                'x': self._convert_coord(parts[2]),
                                'y': self._convert_coord(parts[3]),
                            }
                            current_comp['pins'].append(pin_data)

                elif line.startswith('PIN'):
                    # Pin definition
                    if current_comp:
                        pin_data = self._parse_pin_line(line)  # type: ignore[assignment]
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

    def _parse_layer_features(
        self, step_path: Path, data: ODBData,
        net_num_to_name: Optional[Dict[int, str]] = None,
    ) -> None:
        """Parse features from signal/plane layers"""
        layers_dir = step_path / "layers"

        if not layers_dir.exists():
            return

        # Build case-insensitive dir lookup once
        dir_map: Dict[str, Path] = {}
        for d in layers_dir.iterdir():
            if d.is_dir():
                dir_map[d.name.lower()] = d

        for layer_info in data.layers:
            if layer_info.layer_type not in (LayerType.SIGNAL, LayerType.PLANE, LayerType.MIXED):
                continue

            layer_dir = dir_map.get(layer_info.name.lower())
            if layer_dir:
                self._parse_features_file(
                    layer_dir, layer_info.name, data, net_num_to_name
                )

    def _parse_features_file(
        self, layer_dir: Path, layer_name: str, data: ODBData,
        net_num_to_name: Optional[Dict[int, str]] = None,
    ) -> None:
        """Parse the features file for a layer.

        Extracts traces with net assignments (Fix 1.1), proper widths from
        symbol definitions (Fix 1.3), and copper pours with net assignments.
        """
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

        self._detect_file_units(content)

        # First pass: build symbol index → width map from $ definitions (Fix 1.3)
        symbol_widths: Dict[str, float] = {}
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('$'):
                sym_match = re.match(r'\$(\d+)\s+(\S+)', line)
                if sym_match:
                    sym_idx = sym_match.group(1)
                    sym_name = sym_match.group(2)
                    pad = self._parse_symbol_name(sym_name)
                    if pad:
                        # For round symbols (rN), width = diameter
                        # For rect symbols, width = larger dimension
                        symbol_widths[sym_idx] = pad.width_mm

        net_map = net_num_to_name or {}
        default_width = 0.1  # mm fallback
        traces: list[ODBTrace] = []
        pours: list[ODBCopperPour] = []
        current_points: list[tuple[float, float]] = []
        current_pour_net_num: Optional[int] = None

        # Get EDA-based net mapping for this layer (authoritative for Altium exports)
        eda_layer_map = getattr(self, '_eda_trace_map', {}).get(layer_name.lower(), {})

        # Track feature index for EDA cross-reference
        feature_idx = 0

        for line in content.split('\n'):
            line = line.strip()

            # Line/trace: L x1 y1 x2 y2 sym_num P net_num [;attrs]
            if line.startswith('L '):
                # Strip attribute suffix
                feat_part = line.split(';')[0]
                parts = feat_part.split()
                if len(parts) >= 5:
                    x1 = self._convert_coord(parts[1])
                    y1 = self._convert_coord(parts[2])
                    x2 = self._convert_coord(parts[3])
                    y2 = self._convert_coord(parts[4])

                    # Get trace width from symbol reference (Fix 1.3)
                    width = default_width
                    if len(parts) >= 6:
                        sym_idx = parts[5]
                        width = symbol_widths.get(sym_idx, default_width)

                    # Get net number (Fix 1.1)
                    # Format: L x1 y1 x2 y2 sym_num P net_num
                    # The net_num is typically the last numeric field
                    net_name: Optional[str] = None
                    net_num: Optional[int] = None
                    if len(parts) >= 8:
                        try:
                            net_num = int(parts[7])
                            net_name = net_map.get(net_num)
                        except ValueError:
                            pass
                    elif len(parts) >= 7:
                        # Some formats: L x1 y1 x2 y2 sym P (no net_num = net 0)
                        try:
                            candidate = int(parts[6])
                            # If it's a number and not just 'P'/'N', treat as net
                            net_num = candidate
                            net_name = net_map.get(net_num)
                        except ValueError:
                            pass

                    # EDA-based net lookup (authoritative for Altium exports)
                    if (not net_name or net_name == '$NONE$') and eda_layer_map:
                        eda_net = eda_layer_map.get(feature_idx)
                        if eda_net and eda_net != '$NONE$':
                            net_name = eda_net

                    length = math.sqrt((x2-x1)**2 + (y2-y1)**2)

                    traces.append(ODBTrace(
                        layer=layer_name,
                        width_mm=width,
                        points=[(x1, y1), (x2, y2)],
                        length_mm=length,
                        net_name=net_name,
                        net_number=net_num,
                    ))
                    feature_idx += 1

            # Arc: A x1 y1 x2 y2 [xc yc] sym_num P net_num
            elif line.startswith('A '):
                feat_part = line.split(';')[0]
                parts = feat_part.split()
                if len(parts) >= 5:
                    x1 = self._convert_coord(parts[1])
                    y1 = self._convert_coord(parts[2])
                    x2 = self._convert_coord(parts[3])
                    y2 = self._convert_coord(parts[4])

                    # Get width from symbol
                    width = default_width
                    # Arc has more fields (xc, yc, cw/ccw) so sym is further
                    for i in range(5, min(len(parts), 10)):
                        if parts[i] in symbol_widths:
                            width = symbol_widths[parts[i]]
                            break

                    # Try to get net from last numeric field
                    net_name_a: Optional[str] = None
                    net_num_a: Optional[int] = None
                    for i in range(len(parts) - 1, 4, -1):
                        try:
                            net_num_a = int(parts[i])
                            net_name_a = net_map.get(net_num_a)
                            break
                        except ValueError:
                            continue

                    # EDA-based net lookup for arcs
                    if (not net_name_a or net_name_a == '$NONE$') and eda_layer_map:
                        eda_net = eda_layer_map.get(feature_idx)
                        if eda_net and eda_net != '$NONE$':
                            net_name_a = eda_net

                    traces.append(ODBTrace(
                        layer=layer_name,
                        width_mm=width,
                        points=[(x1, y1), (x2, y2)],
                        net_name=net_name_a,
                        net_number=net_num_a,
                    ))
                    feature_idx += 1

            # Pad record — also a feature, increment index
            elif line.startswith('P '):
                feature_idx += 1

            # Surface (copper pour) start: S P net_num
            elif line.startswith('S ') and 'P' in line:
                current_points = []
                # Extract net number from surface record
                feat_part = line.split(';')[0]
                sparts = feat_part.split()
                current_pour_net_num = None
                # Last numeric field is typically net number
                for i in range(len(sparts) - 1, 0, -1):
                    try:
                        current_pour_net_num = int(sparts[i])
                        break
                    except ValueError:
                        continue

            # Surface boundary: OB x y
            elif line.startswith('OB '):
                parts = line.split()
                if len(parts) >= 3:
                    x = self._convert_coord(parts[1])
                    y = self._convert_coord(parts[2])
                    current_points.append((x, y))

            # Surface end: SE
            elif line.startswith('SE') and current_points:
                pour_net_name = net_map.get(current_pour_net_num) if current_pour_net_num is not None else None
                pours.append(ODBCopperPour(
                    layer=layer_name,
                    boundary=current_points.copy(),
                    net_name=pour_net_name,
                    net_number=current_pour_net_num,
                ))
                current_points = []

        # Store parsed data
        if traces:
            data.traces[layer_name] = traces
        if pours:
            data.copper_pours[layer_name] = pours

    def _parse_drills(
        self, step_path: Path, data: ODBData,
        net_num_to_name: Optional[Dict[int, str]] = None,
    ) -> None:
        """Parse drill hits from drill layers"""
        layers_dir = step_path / "layers"

        if not layers_dir.exists():
            return

        # Build case-insensitive directory lookup
        dir_map: Dict[str, Path] = {}
        for d in layers_dir.iterdir():
            if d.is_dir():
                dir_map[d.name.lower()] = d

        # Build ordered copper layer list for via type classification (Fix 1.7)
        copper_layers = [
            l.name.lower() for l in data.layers
            if l.layer_type in (LayerType.SIGNAL, LayerType.PLANE, LayerType.MIXED)
        ]

        # Find drill layers (case-insensitive)
        for layer_info in data.layers:
            if layer_info.layer_type != LayerType.DRILL:
                continue

            layer_dir = dir_map.get(layer_info.name.lower())
            if layer_dir and layer_dir.exists():
                self._parse_drill_features(
                    layer_dir, layer_info, data, net_num_to_name, copper_layers
                )

        # Also check for common drill layer names
        for drill_name in ["drill", "drl", "pth", "npth"]:
            drill_dir = layers_dir / drill_name
            if drill_dir.exists():
                self._parse_drill_features(
                    drill_dir, None, data, net_num_to_name, copper_layers
                )

    def _parse_drill_features(
        self, layer_dir: Path, layer_info: Optional[ODBLayer],
        data: ODBData,
        net_num_to_name: Optional[Dict[int, str]] = None,
        copper_layers: Optional[List[str]] = None,
    ) -> None:
        """Parse drill hits from a drill layer.

        Extracts actual pad sizes from symbol definitions (dcodes),
        net assignments from feature records (Fix 1.2), and via layer
        spans from drill layer definitions (Fix 1.7).
        """
        features_file = layer_dir / "features"

        if not features_file.exists():
            return

        try:
            content = self._read_file(features_file)
            self._detect_file_units(content)
            symbol_sizes: Dict[str, float] = {}  # symbol_index -> drill_size_mm

            # First pass: parse symbol definitions ($<index> <name>) and tool defs
            for line in content.split('\n'):
                line = line.strip()

                # Symbol definition: $<index> <symbol_name> (e.g. "$0 r6")
                if line.startswith('$'):
                    sym_match = re.match(r'\$(\d+)\s+(\S+)', line)
                    if sym_match:
                        sym_idx = sym_match.group(1)
                        sym_name = sym_match.group(2)
                        pad = self._parse_symbol_name(sym_name)
                        if pad:
                            symbol_sizes[sym_idx] = max(pad.width_mm, pad.height_mm)

                # Tool definition: T<dcode> <size> [type]
                elif line.startswith('T') and not line.startswith('TOP'):
                    match = re.match(r'T(\d+)\s+(\d+(?:\.\d+)?)', line)
                    if match:
                        dcode = match.group(1)
                        size = float(match.group(2)) * self.MIL_TO_MM
                        symbol_sizes[dcode] = size

            default_drill = 0.3  # mm fallback
            net_map = net_num_to_name or {}

            # EDA-based via mapping for this drill layer
            drill_layer_name = layer_info.name.lower() if layer_info else ""
            eda_via_map_layer = getattr(self, '_eda_via_map', {}).get(drill_layer_name, {})
            drill_feature_idx = 0

            # Determine layer span from drill layer info (Fix 1.7)
            start_layer = "top"
            end_layer = "bottom"
            via_type = ViaType.THROUGH

            if layer_info:
                if layer_info.start_name:
                    start_layer = layer_info.start_name
                if layer_info.end_name:
                    end_layer = layer_info.end_name

                # Classify via type from layer span
                if copper_layers and start_layer != "top" and end_layer != "bottom":
                    sl = start_layer.lower()
                    el = end_layer.lower()
                    is_start_outer = (
                        sl in ("top",) or
                        (copper_layers and sl == copper_layers[0])
                    )
                    is_end_outer = (
                        el in ("bottom",) or
                        (copper_layers and el == copper_layers[-1])
                    )
                    if is_start_outer or is_end_outer:
                        via_type = ViaType.BLIND
                    else:
                        via_type = ViaType.BURIED
                elif start_layer != "top" or end_layer != "bottom":
                    # Has non-default layer names → likely blind
                    via_type = ViaType.BLIND

                # Detect plating from layer name
                drill_plating = "plated"
                if layer_info.name and "non" in layer_info.name.lower():
                    drill_plating = "non_plated"

            # Second pass: parse drill hits with net mapping (Fix 1.2)
            for line in content.split('\n'):
                line = line.strip()

                # Pad (drill hit): P x y sym_idx P net_num [mirror] [;attrs]
                if line.startswith('P '):
                    feat_part = line.split(';')[0]
                    parts = feat_part.split()
                    if len(parts) >= 3:
                        x = self._convert_coord(parts[1])
                        y = self._convert_coord(parts[2])

                        # Symbol index
                        sym_idx = parts[3] if len(parts) >= 4 else None
                        drill_size = symbol_sizes.get(sym_idx, default_drill) if sym_idx else default_drill

                        # Net number (Fix 1.2) — find last numeric field after polarity
                        net_name: Optional[str] = None
                        net_num: Optional[int] = None
                        # Format: P x y sym P net_num mirror
                        # or:     P x y sym P net_num
                        for i in range(min(len(parts) - 1, 7), 3, -1):
                            try:
                                net_num = int(parts[i])
                                net_name = net_map.get(net_num)
                                break
                            except ValueError:
                                continue

                        # EDA-based net lookup for drill hits
                        if (not net_name or net_name == '$NONE$') and eda_via_map_layer:
                            eda_net = eda_via_map_layer.get(drill_feature_idx)
                            if eda_net and eda_net != '$NONE$':
                                net_name = eda_net

                        drill_feature_idx += 1
                        pad_size = self._get_via_pad_size(sym_idx, drill_size, data)

                        data.drills.append(ODBDrill(
                            x_mm=x,
                            y_mm=y,
                            diameter_mm=drill_size,
                            drill_type=drill_plating if layer_info else "plated",
                            start_layer=start_layer,
                            end_layer=end_layer,
                        ))

                        data.vias.append(ODBVia(
                            x_mm=x,
                            y_mm=y,
                            drill_diameter_mm=drill_size,
                            pad_top_mm=pad_size,
                            pad_bottom_mm=pad_size,
                            pad_inner_mm=pad_size,
                            start_layer=start_layer,
                            end_layer=end_layer,
                            via_type=via_type,
                            net_name=net_name,
                            net_number=net_num,
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

    def _parse_layer_attributes(self, step_path: Path, data: ODBData) -> None:
        """Parse attrlist files from each layer directory for per-layer design rules.

        ODB++ layers can have an attrlist file containing attributes like:
        .min_line_width, .min_spacing, .min_annular_ring, etc.
        """
        layers_dir = step_path / "layers"
        if not layers_dir.exists():
            return

        for layer_info in data.layers:
            if layer_info.layer_type not in (LayerType.SIGNAL, LayerType.PLANE, LayerType.MIXED):
                continue

            layer_dir = layers_dir / layer_info.name
            if not layer_dir.exists():
                # Try case-insensitive match
                for d in layers_dir.iterdir():
                    if d.name.lower() == layer_info.name.lower():
                        layer_dir = d
                        break

            if not layer_dir.exists():
                continue

            attrlist_file = layer_dir / "attrlist"
            if not attrlist_file.exists():
                continue

            try:
                content = self._read_file(attrlist_file)
                self._extract_design_rules_from_attrlist(
                    content, data, layer_scope=layer_info.name
                )
            except Exception as e:
                data.parse_warnings.append(
                    f"Error parsing attrlist for layer {layer_info.name}: {e}"
                )

    def _parse_misc_attributes(self, odb_root: Path, data: ODBData) -> None:
        """Parse design-level attributes from misc/attrlist.

        This file contains global design rules and fabrication parameters:
        .min_line_width = 0.1
        .min_spacing = 0.1
        .min_drill = 0.2
        .min_annular_ring = 0.075
        """
        attrlist_file = odb_root / "misc" / "attrlist"
        if not attrlist_file.exists():
            return

        try:
            content = self._read_file(attrlist_file)
            self._extract_design_rules_from_attrlist(content, data, layer_scope=None)
        except Exception as e:
            data.parse_warnings.append(f"Error parsing misc/attrlist: {e}")

    def _extract_design_rules_from_attrlist(
        self, content: str, data: ODBData, layer_scope: Optional[str]
    ) -> None:
        """Extract design rule constraints from an attrlist file.

        ODB++ attrlist format:
        - Lines starting with . define attributes: .attr_name = value
        - Lines starting with @ define attribute assignments: @0 .attr_name
        - Comment lines start with #
        """
        # Mapping from ODB++ attribute names to rule types
        rule_type_map = {
            "min_line_width": "width",
            "min_line_wid": "width",
            "min_trace_width": "width",
            "min_spacing": "spacing",
            "min_space": "spacing",
            "min_clearance": "spacing",
            "min_drill": "drill",
            "min_drill_size": "drill",
            "min_annular_ring": "annular_ring",
            "min_ann_ring": "annular_ring",
            "min_smd_to_hole": "spacing",
            "min_pad_to_pad": "spacing",
            "min_pad_to_trace": "spacing",
            "max_copper_sliver": "width",
            "min_via_hole": "drill",
            "min_hole_to_hole": "spacing",
            "min_hole_to_copper": "spacing",
        }

        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Parse .attribute = value lines
            if line.startswith('.') and '=' in line:
                key, _, value = line.partition('=')
                attr_name = key.strip().lstrip('.')
                value_str = value.strip().strip("'\"")

                # Try to parse numeric value
                try:
                    # Strip units suffix if present
                    num_str = re.sub(r'[a-zA-Z]+$', '', value_str).strip()
                    if not num_str:
                        continue
                    num_val = float(num_str)

                    # Convert to mm based on current units
                    if self._units == 'mil':
                        val_mm = num_val * self.MIL_TO_MM
                    elif self._units == 'inch':
                        val_mm = num_val * self.INCH_TO_MM
                    else:
                        val_mm = num_val  # Already mm

                    # Determine rule type
                    attr_lower = attr_name.lower()
                    rule_type = rule_type_map.get(attr_lower, "other")

                    # Only add recognized design rule attributes
                    if attr_lower in rule_type_map:
                        # Check for duplicate (same rule_name + layer_scope)
                        is_dup = any(
                            r.rule_name == attr_name and r.layer_scope == layer_scope
                            for r in data.design_rules
                        )
                        if not is_dup:
                            data.design_rules.append(ODBDesignRule(
                                rule_name=attr_name,
                                rule_type=rule_type,
                                value_mm=round(val_mm, 4),
                                layer_scope=layer_scope,
                            ))
                except ValueError:
                    continue

    def _parse_misc_info(self, odb_root: Path, data: ODBData) -> None:
        """Parse manufacturing notes and general info from misc/info.

        The misc/info file contains free-form text with design metadata,
        fab notes, material specs, revision history, etc.
        """
        info_file = odb_root / "misc" / "info"
        if not info_file.exists():
            return

        try:
            content = self._read_file(info_file)
            for line in content.split('\n'):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                # Capture non-empty lines as manufacturing notes
                # Filter out pure formatting/separator lines
                if len(line) > 2 and not all(c in '-=_*' for c in line):
                    data.manufacturing_notes.append(line)

            # Also try to extract job_name from info
            for note in data.manufacturing_notes:
                note_lower = note.lower()
                if 'job_name' in note_lower or 'design_name' in note_lower:
                    parts = note.split('=', 1)
                    if len(parts) == 2:
                        data.job_name = parts[1].strip().strip("'\"")
                        break
        except Exception as e:
            data.parse_warnings.append(f"Error parsing misc/info: {e}")

    def _build_drill_table(self, data: ODBData) -> list:
        """Build a drill table summarizing drill sizes, counts, plating, and aspect ratios.

        Returns a list of dicts: [{size_mm, count, plating, aspect_ratio}]
        sorted by drill size ascending.
        """
        # Group drills by diameter
        drill_groups: Dict[float, Dict] = {}

        for drill in data.drills:
            size = round(drill.diameter_mm, 3)
            if size not in drill_groups:
                drill_groups[size] = {
                    "size_mm": size,
                    "count": 0,
                    "plating": drill.drill_type,
                }
            drill_groups[size]["count"] += 1
            # If any drill of this size is non-plated, note it
            if drill.drill_type == "non_plated":
                drill_groups[size]["plating"] = "non_plated"

        # Also include vias that may not have explicit drill records
        for via in data.vias:
            size = round(via.drill_diameter_mm, 3)
            if size not in drill_groups:
                drill_groups[size] = {
                    "size_mm": size,
                    "count": 0,
                    "plating": "plated",
                }
                drill_groups[size]["count"] += 1

        # Calculate aspect ratios (drill depth / drill diameter)
        board_thickness = data.total_thickness_mm or 1.6  # Default FR4
        for group in drill_groups.values():
            if group["size_mm"] > 0:
                group["aspect_ratio"] = round(board_thickness / group["size_mm"], 2)
            else:
                group["aspect_ratio"] = 0.0

        return sorted(drill_groups.values(), key=lambda d: d["size_mm"])

    def _build_copper_pour_summary(self, data: ODBData) -> list:
        """Build a summary of copper pours with net assignments and areas.

        Returns a list of dicts: [{layer, net_name, area_mm2, clearance_mm,
        thermal_relief, pour_type}]
        """
        summary = []
        for layer_name, pours in data.copper_pours.items():
            for pour in pours:
                area = pour.area_mm2
                if area is None and pour.boundary:
                    area = self._calculate_polygon_area(pour.boundary)
                    pour.area_mm2 = area

                summary.append({
                    "layer": layer_name,
                    "net_name": pour.net_name or "unassigned",
                    "net_index": pour.net_number,
                    "area_mm2": round(area, 2) if area else 0.0,
                    "clearance_mm": pour.clearance_mm,
                    "thermal_relief": pour.thermal_enabled,
                    "pour_type": pour.pour_type,
                })
        return summary

    def _calculate_statistics(self, data: ODBData) -> None:
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
        total_thickness: float = 0
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
        area: float = 0
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
                with open(file_path, encoding='utf-8', errors='ignore') as f:
                    return f.read()
            except UnicodeDecodeError:
                with open(file_path, encoding='latin-1') as f:
                    return f.read()

    def _detect_file_units(self, content: str) -> None:
        """Detect UNITS= header in a file and update self._units."""
        for line in content.split('\n')[:10]:
            line = line.strip()
            if line.startswith('UNITS=') or line.startswith('UNITS ='):
                unit_val = line.split('=', 1)[1].strip().lower()
                if 'mm' in unit_val:
                    self._units = 'mm'
                elif 'inch' in unit_val:
                    self._units = 'inch'
                elif 'mil' in unit_val:
                    self._units = 'mil'
                return

    def _convert_coord(self, value: str) -> float:
        """Convert coordinate string to mm based on current units."""
        try:
            num = float(value)
            if self._units == 'inch':
                return num * self.INCH_TO_MM
            elif self._units == 'mm':
                return num
            else:  # mil (default)
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
            if temp_path.exists():  # type: ignore[attr-defined]
                temp_path.unlink()

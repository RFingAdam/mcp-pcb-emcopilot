"""PCB file format parsers with auto-detection.

Supports: KiCad (.kicad_pcb), ODB++ (.tgz/.tar.gz), Gerber (.gbr/.ger),
Altium (.PcbDoc), Allegro (.brd, ASCII export), IPC-2581 (.xml/.cvg),
BOM (.csv/.xlsx), Schematic (.kicad_sch), STEP (.step/.stp), Schematic PDF (.pdf)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from ..errors import ParseError
from ..models.pcb_data import (
    PCBComponent,
    PCBDesignData,
    PCBLayer,
    PCBNet,
    PCBTrace,
    PCBVia,
    PCBZone,
)
from .pdf_schematic_parser import PDFSchematicResult

logger = logging.getLogger(__name__)

# Maximum file size: 500 MB
_MAX_FILE_SIZE = 500 * 1024 * 1024


def detect_format(file_path: str) -> str:
    """Auto-detect PCB file format from extension and content."""
    path = Path(file_path)
    ext = path.suffix.lower()
    name = path.name.lower()

    if ext == ".kicad_pcb":
        return "kicad"
    elif ext in (".tgz",) or name.endswith(".tar.gz") or ext == ".zip":
        return "odb"
    elif ext in (".gbr", ".ger", ".gtl", ".gbl", ".gts", ".gbs", ".gto", ".gbo", ".gtp", ".gbp"):
        return "gerber"
    elif ext in (".pcbdoc",):
        return "altium"
    elif ext == ".brd":
        return "allegro"
    elif ext in (".exp",):
        # Allegro extraction file — verify content if possible
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                header = f.read(2000)
                if "$HEADER" in header or "$NETS" in header or "$COMPONENTS" in header:
                    return "allegro"
                if "ALLEGRO" in header.upper() or "ORCAD" in header.upper():
                    return "allegro"
        except OSError as e:
            logger.debug("format-sniff read failed for %s: %s", file_path, e)
        return "allegro"
    elif ext in (".xml", ".cvg"):
        # Could be IPC-2581 or other XML — check content
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                header = f.read(1000)
                if "IPC-2581" in header or "Stackup" in header:
                    return "ipc2581"
        except OSError as e:
            logger.debug("format-sniff read failed for %s: %s", file_path, e)
        return "ipc2581"
    elif ext in (".step", ".stp"):
        return "step"
    elif ext in (".csv", ".xlsx", ".xls"):
        return "bom"
    elif ext == ".kicad_sch":
        return "schematic"
    elif ext == ".pdf":
        return "schematic_pdf"
    elif ext == ".txt":
        # Content-based detection for Allegro ASCII exports
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                header = f.read(2000)
                if "$HEADER" in header or "$NETS" in header or "$COMPONENTS" in header:
                    return "allegro"
                if "ALLEGRO" in header.upper() or "ORCAD" in header.upper():
                    return "allegro"
        except OSError as e:
            logger.debug("format-sniff read failed for %s: %s", file_path, e)
        return "unknown"
    else:
        return "unknown"


def _validate_file(file_path: str) -> Path:
    """Validate file exists, is non-empty, and is within size limits.

    Returns the resolved Path on success, raises ParseError on failure.
    """
    path = Path(file_path)
    if not path.exists():
        raise ParseError("FILE_NOT_FOUND", f"File not found: {file_path}", {"file": file_path})

    file_size = path.stat().st_size
    if file_size == 0:
        raise ParseError("EMPTY_FILE", f"File is empty: {file_path}", {"file": file_path})
    if file_size > _MAX_FILE_SIZE:
        raise ParseError(
            "FILE_TOO_LARGE",
            f"File exceeds 500MB limit: {file_size / 1024 / 1024:.0f}MB",
            {"file": file_path, "size_bytes": file_size},
        )
    return path


def parse_pcb_file(file_path: str, format_hint: Optional[str] = None) -> PCBDesignData:
    """Parse any supported PCB file into unified PCBDesignData.

    Args:
        file_path: Path to the PCB design file
        format_hint: Optional format override ("kicad", "odb", "gerber", "altium", "ipc2581")

    Returns:
        PCBDesignData with all extracted design data

    Raises:
        ParseError: If the file cannot be found, is empty, too large, or fails to parse.
    """
    _validate_file(file_path)

    file_format = format_hint or detect_format(file_path)
    logger.info(f"Parsing {file_path} as {file_format}")

    if file_format == "kicad":
        return _parse_format("kicad", file_path, _parse_kicad)
    elif file_format == "odb":
        return _parse_format("odb", file_path, _parse_odb)
    elif file_format == "gerber":
        return _parse_format("gerber", file_path, _parse_gerber)
    elif file_format == "altium":
        return _parse_format("altium", file_path, _parse_altium)
    elif file_format == "allegro":
        return _parse_format("allegro", file_path, _parse_allegro)
    elif file_format == "ipc2581":
        return _parse_format("ipc2581", file_path, _parse_ipc2581)
    elif file_format == "step":
        return _parse_format("step", file_path, _parse_step)
    else:
        raise ParseError(
            "UNSUPPORTED_FORMAT",
            f"Unsupported format: {file_format} for {file_path}",
            {"file": file_path, "format": file_format},
        )


def _parse_format(fmt: str, file_path: str, parser_fn) -> PCBDesignData:
    """Wrap a format-specific parser with error handling."""
    try:
        result: PCBDesignData = parser_fn(file_path)
        return result
    except ParseError:
        raise  # Re-raise our own errors as-is
    except Exception as e:
        raise ParseError(
            "PARSE_FAILED",
            f"Failed to parse {fmt} file: {e}",
            {"file": file_path, "format": fmt},
        ) from e


def _parse_kicad(file_path: str) -> PCBDesignData:
    """Parse KiCad .kicad_pcb into PCBDesignData."""
    from .kicad_pcb_parser import KiCadPcbParser

    parser = KiCadPcbParser()
    board = parser.parse_file(file_path)

    data = PCBDesignData(
        source_file=file_path,
        source_format="kicad",
        board_width_mm=board.width_mm,
        board_height_mm=board.height_mm,
        board_thickness_mm=board.thickness_mm,
        board_outline=board.board_outline,
        layer_count=board.layer_count,
        total_trace_length_mm=board.total_trace_length_mm,
        title=board.title,
        revision=board.revision,
        net_classes=board.net_classes,
        warnings=board.warnings,
    )

    # Convert layers
    for kl in board.layers:
        data.layers.append(PCBLayer(
            name=kl.name, number=kl.number, layer_type=kl.layer_type,
        ))

    # Add stackup layers if present
    for sl in board.stackup:
        data.layers.append(PCBLayer(
            name=sl.name or sl.layer_type, number=len(data.layers),
            layer_type=sl.layer_type, thickness_mm=sl.thickness_mm,
            material=sl.material, dielectric_constant=sl.dielectric_constant,
            loss_tangent=sl.loss_tangent,
        ))

    # Convert design rules
    if board.design_rules:
        data.min_trace_width_mm = board.design_rules.min_trace_width_mm
        data.min_clearance_mm = board.design_rules.min_clearance_mm
        data.min_via_drill_mm = board.design_rules.min_via_drill_mm

    # Convert components
    for kc in board.components:
        data.components.append(PCBComponent(
            reference=kc.reference, value=kc.value, footprint=kc.footprint,
            package=kc.footprint, layer=kc.layer, x_mm=kc.x_mm, y_mm=kc.y_mm,
            rotation=kc.rotation, dnp=kc.dnp,
        ))

    # Build net index map
    net_map = {}
    for kn in board.nets:
        net_map[kn.index] = kn.name
        data.nets.append(PCBNet(
            name=kn.name, index=kn.index, net_class=kn.net_class,
            routed_length_mm=kn.routed_length_mm,
        ))

    # Convert traces
    for kt in board.traces:
        data.traces.append(PCBTrace(
            layer=kt.layer, width_mm=kt.width_mm,
            x1_mm=kt.x1_mm, y1_mm=kt.y1_mm, x2_mm=kt.x2_mm, y2_mm=kt.y2_mm,
            net_index=kt.net_index, net_name=net_map.get(kt.net_index),
            length_mm=kt.length_mm,
        ))

    # Convert vias
    for kv in board.vias:
        data.vias.append(PCBVia(
            x_mm=kv.x_mm, y_mm=kv.y_mm, drill_mm=kv.drill_mm,
            pad_diameter_mm=kv.size_mm, via_type=kv.via_type,
            start_layer=kv.layers[0] if kv.layers else "F.Cu",
            end_layer=kv.layers[1] if len(kv.layers) > 1 else "B.Cu",
            net_index=kv.net_index, net_name=net_map.get(kv.net_index),
        ))

    # Convert zones
    for kz in board.zones:
        data.zones.append(PCBZone(
            layer=kz.layer, net_name=kz.net_name, net_index=kz.net_index,
            zone_type=kz.zone_type, outline=kz.outline,
        ))

    return data


def _parse_odb(file_path: str) -> PCBDesignData:
    """Parse ODB++ archive into PCBDesignData."""
    from .odb_parser import ODBParser

    parser = ODBParser()
    odb = parser.parse(file_path)

    data = PCBDesignData(
        source_file=file_path,
        source_format="odb++",
        layer_count=odb.layer_count,
        board_thickness_mm=odb.total_thickness_mm or 1.6,
        warnings=odb.parse_warnings + odb.parse_errors,
    )

    if odb.outline:
        data.board_width_mm = odb.outline.width_mm or 0
        data.board_height_mm = odb.outline.height_mm or 0
        data.board_outline = odb.outline.outline

    # Convert layers
    for ol in odb.layers:
        data.layers.append(PCBLayer(
            name=ol.name, number=ol.row, layer_type=ol.layer_type.value,
            thickness_mm=ol.thickness_mm or 0,
            dielectric_constant=ol.dielectric_constant or 4.3,
            loss_tangent=ol.loss_tangent or 0.02,
            copper_weight_oz=ol.copper_weight_oz,
        ))

    # Convert components
    for oc in odb.components:
        data.components.append(PCBComponent(
            reference=oc.ref_des, value=oc.part_name, footprint=oc.package,
            package=oc.package, layer="F.Cu" if oc.layer == "top" else "B.Cu",
            x_mm=oc.x_mm, y_mm=oc.y_mm, rotation=oc.rotation_deg,
            properties=oc.properties,
        ))

    # Convert nets (Fix 1.6: propagate pin count)
    for on in odb.nets:
        data.nets.append(PCBNet(
            name=on.name, index=on.net_number, net_class=on.net_class,
            is_differential=on.is_differential,
            differential_pair=on.differential_pair,
            routed_length_mm=on.routed_length_mm or 0,
            via_count=on.via_count,
            impedance_target_ohm=on.impedance_target_ohm,
            pin_count=len(on.pins),
        ))

    # Convert vias
    for ov in odb.vias:
        data.vias.append(PCBVia(
            x_mm=ov.x_mm, y_mm=ov.y_mm, drill_mm=ov.drill_diameter_mm,
            pad_diameter_mm=ov.pad_top_mm or 0,
            via_type=ov.via_type.value if hasattr(ov.via_type, 'value') else str(ov.via_type),
            start_layer=ov.start_layer, end_layer=ov.end_layer,
            net_name=ov.net_name,
        ))

    # Convert traces (Fix 1.8: compute segment length, propagate net)
    import math as _math
    for layer_name, traces in odb.traces.items():
        for ot in traces:
            pts = ot.points
            if len(pts) >= 2:
                for i in range(len(pts) - 1):
                    seg_len = _math.sqrt(
                        (pts[i + 1][0] - pts[i][0]) ** 2 +
                        (pts[i + 1][1] - pts[i][1]) ** 2
                    )
                    data.traces.append(PCBTrace(
                        layer=layer_name, width_mm=ot.width_mm,
                        x1_mm=pts[i][0], y1_mm=pts[i][1],
                        x2_mm=pts[i + 1][0], y2_mm=pts[i + 1][1],
                        net_name=ot.net_name,
                        net_index=ot.net_number or 0,
                        length_mm=seg_len,
                    ))

    # Convert zones
    for layer_name, pours in odb.copper_pours.items():
        for cp in pours:
            data.zones.append(PCBZone(
                layer=layer_name, net_name=cp.net_name,
                zone_type=cp.pour_type, outline=cp.boundary,
                area_mm2=cp.area_mm2 or 0,
            ))

    # Populate deep extraction fields
    # Drill table
    data.drill_table = parser._build_drill_table(odb)

    # Board outline detail
    if odb.outline:
        data.board_outline_detail = {
            "width_mm": round(odb.outline.width_mm or 0, 3),
            "height_mm": round(odb.outline.height_mm or 0, 3),
            "area_mm2": round(odb.outline.area_mm2 or 0, 2),
            "vertices": odb.outline.outline,
            "cutouts": odb.outline.cutouts,
            "origin_x_mm": round(odb.outline.origin_x_mm, 3),
            "origin_y_mm": round(odb.outline.origin_y_mm, 3),
        }

    # Design rules
    data.design_rules = [
        {
            "name": r.rule_name,
            "type": r.rule_type,
            "value_mm": r.value_mm,
            "scope": r.layer_scope,
        }
        for r in odb.design_rules
    ]

    # Apply extracted design rules to PCBDesignData min_* fields
    for rule in odb.design_rules:
        if rule.layer_scope is not None:
            continue  # Only apply global rules to top-level fields
        if rule.rule_type == "width":
            data.min_trace_width_mm = rule.value_mm
        elif rule.rule_type == "spacing":
            data.min_clearance_mm = rule.value_mm
        elif rule.rule_type == "drill":
            data.min_via_drill_mm = rule.value_mm

    # Copper pours summary
    data.copper_pours = parser._build_copper_pour_summary(odb)

    # Manufacturing notes
    data.manufacturing_notes = list(odb.manufacturing_notes)

    return data


def _parse_gerber(file_path: str) -> PCBDesignData:
    """Parse Gerber file(s) into PCBDesignData."""
    from .gerber_parser import GerberParser

    parser = GerberParser()
    gerber = parser.parse(file_path)

    data = PCBDesignData(
        source_file=file_path,
        source_format="gerber",
    )

    if hasattr(gerber, 'warnings'):
        data.warnings = gerber.warnings or []

    # Gerber provides layer-level data; extract what's available
    if hasattr(gerber, 'traces'):
        for gt in getattr(gerber, 'traces', []):
            data.traces.append(PCBTrace(
                layer=getattr(gt, 'layer', 'unknown'),
                width_mm=getattr(gt, 'width_mm', 0),
                x1_mm=getattr(gt, 'x1_mm', 0),
                y1_mm=getattr(gt, 'y1_mm', 0),
                x2_mm=getattr(gt, 'x2_mm', 0),
                y2_mm=getattr(gt, 'y2_mm', 0),
            ))

    return data


def _parse_altium(file_path: str) -> PCBDesignData:
    """Parse Altium .PcbDoc into PCBDesignData."""
    try:
        from .altium_parser import AltiumPcbParser
    except ImportError as e:
        raise ImportError(
            "Altium parser requires 'olefile' package: pip install olefile"
        ) from e

    parser = AltiumPcbParser()
    board = parser.parse(file_path)

    data = PCBDesignData(
        source_file=file_path,
        source_format="altium",
        board_width_mm=getattr(board, 'width_mm', 0),
        board_height_mm=getattr(board, 'height_mm', 0),
        layer_count=getattr(board, 'layer_count', 2),
        warnings=getattr(board, 'warnings', []),
    )

    for ac in getattr(board, 'components', []):
        data.components.append(PCBComponent(
            reference=getattr(ac, 'reference', '?'),
            value=getattr(ac, 'value', None),
            footprint=getattr(ac, 'footprint', None),
            layer=getattr(ac, 'layer', 'F.Cu'),
            x_mm=getattr(ac, 'x_mm', 0),
            y_mm=getattr(ac, 'y_mm', 0),
        ))

    for an in getattr(board, 'nets', []):
        data.nets.append(PCBNet(
            name=getattr(an, 'name', ''),
            index=getattr(an, 'index', 0),
        ))

    for at in getattr(board, 'traces', []):
        data.traces.append(PCBTrace(
            layer=getattr(at, 'layer', ''),
            width_mm=getattr(at, 'width_mm', 0),
            x1_mm=getattr(at, 'x1_mm', 0),
            y1_mm=getattr(at, 'y1_mm', 0),
            x2_mm=getattr(at, 'x2_mm', 0),
            y2_mm=getattr(at, 'y2_mm', 0),
        ))

    for av in getattr(board, 'vias', []):
        data.vias.append(PCBVia(
            x_mm=getattr(av, 'x_mm', 0),
            y_mm=getattr(av, 'y_mm', 0),
            drill_mm=getattr(av, 'drill_mm', 0.3),
            pad_diameter_mm=getattr(av, 'pad_diameter_mm', 0.6),
        ))

    return data


def _parse_allegro(file_path: str) -> PCBDesignData:
    """Parse Allegro ASCII export into PCBDesignData."""
    from .allegro_parser import AllegroParser

    parser = AllegroParser()
    board = parser.parse_file(file_path)

    data = PCBDesignData(
        source_file=file_path,
        source_format="allegro",
        board_width_mm=board.width_mm,
        board_height_mm=board.height_mm,
        board_outline=board.board_outline,
        layer_count=board.layer_count,
        title=board.title,
        warnings=board.warnings,
    )

    # Convert stackup layers
    for sl in board.stackup:
        data.layers.append(PCBLayer(
            name=sl.name, number=len(data.layers),
            layer_type=sl.layer_type, thickness_mm=sl.thickness_mm,
            material=sl.material, dielectric_constant=sl.dielectric_constant,
            loss_tangent=sl.loss_tangent,
            copper_weight_oz=sl.copper_weight_oz,
        ))

    # Convert components
    for ac in board.components:
        layer = "F.Cu" if ac.side.upper() == "TOP" else "B.Cu"
        data.components.append(PCBComponent(
            reference=ac.reference,
            value=ac.value,
            footprint=ac.footprint,
            package=ac.footprint,
            part_number=ac.part_number,
            layer=layer,
            x_mm=ac.x_mm,
            y_mm=ac.y_mm,
            rotation=ac.rotation,
        ))

    # Convert nets
    net_name_to_index = {}
    for an in board.nets:
        net_name_to_index[an.name] = an.index
        data.nets.append(PCBNet(
            name=an.name,
            index=an.index,
            pin_count=len(an.pins),
        ))

    # Convert traces
    total_trace_length = 0.0
    for at in board.traces:
        net_idx = net_name_to_index.get(at.net_name, 0) if at.net_name else 0
        trace = PCBTrace(
            layer=at.layer,
            width_mm=at.width_mm,
            x1_mm=at.x1_mm,
            y1_mm=at.y1_mm,
            x2_mm=at.x2_mm,
            y2_mm=at.y2_mm,
            net_name=at.net_name,
            net_index=net_idx,
            length_mm=at.length_mm,
        )
        data.traces.append(trace)
        total_trace_length += at.length_mm

    data.total_trace_length_mm = total_trace_length

    # Convert vias
    for av in board.vias:
        net_idx = net_name_to_index.get(av.net_name, 0) if av.net_name else 0
        data.vias.append(PCBVia(
            x_mm=av.x_mm,
            y_mm=av.y_mm,
            drill_mm=av.drill_mm,
            pad_diameter_mm=av.pad_diameter_mm,
            start_layer=av.start_layer,
            end_layer=av.end_layer,
            net_name=av.net_name,
            net_index=net_idx,
        ))

    # Convert design rules
    if board.design_rules:
        data.min_trace_width_mm = board.design_rules.min_trace_width_mm
        data.min_clearance_mm = board.design_rules.min_clearance_mm
        data.min_via_drill_mm = board.design_rules.min_via_drill_mm

    return data


def _parse_ipc2581(file_path: str) -> PCBDesignData:
    """Parse IPC-2581 XML into PCBDesignData."""
    from .ipc2581_parser import IPC2581Parser

    parser = IPC2581Parser()
    ipc = parser.parse(file_path)

    data = PCBDesignData(
        source_file=file_path,
        source_format="ipc2581",
        layer_count=getattr(ipc, 'layer_count', 2),
        warnings=getattr(ipc, 'warnings', []),
    )

    for ic in getattr(ipc, 'components', []):
        data.components.append(PCBComponent(
            reference=getattr(ic, 'reference', '?'),
            value=getattr(ic, 'value', None),
            footprint=getattr(ic, 'footprint', None),
            x_mm=getattr(ic, 'x_mm', 0),
            y_mm=getattr(ic, 'y_mm', 0),
        ))

    for inet in getattr(ipc, 'nets', []):
        data.nets.append(PCBNet(
            name=getattr(inet, 'name', ''),
            index=getattr(inet, 'index', 0),
        ))

    for it in getattr(ipc, 'traces', []):
        data.traces.append(PCBTrace(
            layer=getattr(it, 'layer', ''),
            width_mm=getattr(it, 'width_mm', 0),
            x1_mm=getattr(it, 'x1_mm', 0),
            y1_mm=getattr(it, 'y1_mm', 0),
            x2_mm=getattr(it, 'x2_mm', 0),
            y2_mm=getattr(it, 'y2_mm', 0),
        ))

    for iv in getattr(ipc, 'vias', []):
        data.vias.append(PCBVia(
            x_mm=getattr(iv, 'x_mm', 0),
            y_mm=getattr(iv, 'y_mm', 0),
            drill_mm=getattr(iv, 'drill_mm', 0.3),
        ))

    return data


def _parse_step(file_path: str) -> PCBDesignData:
    """Parse STEP (.step/.stp) file into PCBDesignData with 3D data."""
    from .step_parser import STEPParser

    parser = STEPParser()
    result = parser.parse_file(file_path)

    board_3d = result.get("board_3d", {})
    step_components = result.get("step_components", [])

    data = PCBDesignData(
        source_file=file_path,
        source_format="step",
        board_width_mm=board_3d.get("width", 0),
        board_height_mm=board_3d.get("depth", 0),
        board_thickness_mm=board_3d.get("thickness", 1.6),
        warnings=result.get("warnings", []),
        step_components=step_components,
        board_3d=board_3d,
    )

    # Populate standard components from STEP component data
    for sc in step_components:
        data.components.append(PCBComponent(
            reference=sc.get("reference", "?"),
            value=sc.get("description", None),
            x_mm=sc.get("x", 0),
            y_mm=sc.get("y", 0),
        ))

    return data


def parse_schematic_pdf(file_path: str) -> PDFSchematicResult:
    """Parse a PDF schematic file and return extraction results.

    Args:
        file_path: Path to the PDF schematic file.

    Returns:
        PDFSchematicResult with pages, components, and nets.
    """
    from .pdf_schematic_parser import PDFSchematicParser

    parser = PDFSchematicParser()
    return parser.parse(file_path)

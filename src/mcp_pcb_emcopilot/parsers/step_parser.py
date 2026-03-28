"""Lightweight STEP (ISO 10303-21) file parser for PCB 3D model review.

Extracts board outline, component bounding boxes, heights, and reference
designators from STEP files exported by EDA tools (KiCad, Altium, Fusion360).

This is a text-only parser — NO heavy 3D dependencies (cadquery, OCP, trimesh).
STEP files are ASCII text with a well-defined entity structure.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Optional


class STEPEntity:
    """A parsed STEP entity (e.g., #123 = PRODUCT('R1', ...))."""

    __slots__ = ("id", "type_name", "raw_params", "params")

    def __init__(self, entity_id: int, type_name: str, raw_params: str):
        self.id = entity_id
        self.type_name = type_name.upper()
        self.raw_params = raw_params
        self.params: list = []


class STEPParser:
    """Parse STEP files to extract 3D geometry for PCB mechanical review.

    Handles typical EDA-exported STEP files. Best-effort parsing — does not
    attempt to implement a full ISO 10303 reader.
    """

    # Reference designator pattern (e.g., R1, C23, U5, J1, IC3, FB2)
    _REFDES_RE = re.compile(
        r'^([A-Z]{1,4})(\d+)$'
    )
    # Common EDA reference designator prefixes
    _REFDES_PREFIXES = {
        'R', 'C', 'L', 'D', 'U', 'J', 'P', 'Q', 'T', 'Y',
        'FB', 'IC', 'SW', 'TP', 'F', 'X', 'BT', 'LED', 'RN',
        'CN', 'K', 'FL', 'MP', 'H', 'FID',
    }

    def __init__(self):
        self.entities: dict[int, STEPEntity] = {}
        self._cartesian_points: dict[int, tuple[float, float, float]] = {}
        self._products: list[dict] = []
        self._shapes: dict[int, list[int]] = {}  # shape_rep_id -> list of item ids
        self._warnings: list[str] = []

    def parse_file(self, file_path: str) -> dict:
        """Parse a STEP file and return extracted 3D data.

        Returns dict with:
            - board_3d: {width, depth, thickness, bounding_box}
            - step_components: [{reference, x, y, z, width, depth, height}]
            - warnings: [str]
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"STEP file not found: {file_path}")

        with open(path, encoding="utf-8", errors="ignore") as f:
            content = f.read()

        return self.parse_content(content)

    def parse_content(self, content: str) -> dict:
        """Parse STEP content string and return extracted 3D data."""
        self.entities.clear()
        self._cartesian_points.clear()
        self._products.clear()
        self._shapes.clear()
        self._warnings.clear()

        # Parse all entities
        self._parse_entities(content)

        # Extract cartesian points first (needed for everything else)
        self._extract_cartesian_points()

        # Extract products (components)
        self._extract_products()

        # Extract shape representations
        self._extract_shape_representations()

        # Build component list with positions and bounding boxes
        components = self._build_components()

        # Determine board outline and dimensions
        board_3d = self._extract_board_dimensions(components)

        return {
            "board_3d": board_3d,
            "step_components": components,
            "warnings": self._warnings,
        }

    def _parse_entities(self, content: str) -> None:
        """Parse STEP entities from content.

        STEP entities look like:
            #123 = PRODUCT('name', 'desc', '', (#456));
            #789 = CARTESIAN_POINT('', (1.0, 2.0, 3.0));

        Entities can span multiple lines.
        """
        # Find the DATA section
        data_start = content.find("DATA;")
        if data_start == -1:
            self._warnings.append("No DATA section found in STEP file")
            return

        data_end = content.find("ENDSEC;", data_start)
        if data_end == -1:
            data_end = len(content)

        data_section = content[data_start + 5:data_end]

        # Normalize whitespace — collapse multi-line entities into single lines
        # But preserve string contents
        data_section = self._normalize_whitespace(data_section)

        # Parse individual entities
        # Pattern: #id = TYPE_NAME(params);
        entity_re = re.compile(
            r'#(\d+)\s*=\s*([A-Z_][A-Z0-9_]*)\s*\((.+?)\)\s*;',
            re.DOTALL,
        )

        for match in entity_re.finditer(data_section):
            eid = int(match.group(1))
            etype = match.group(2).strip().upper()
            raw_params = match.group(3).strip()
            entity = STEPEntity(eid, etype, raw_params)
            self.entities[eid] = entity

    def _normalize_whitespace(self, text: str) -> str:
        """Collapse whitespace outside of quoted strings."""
        result = []
        in_string = False
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == "'":
                in_string = not in_string
                result.append(ch)
            elif in_string:
                result.append(ch)
            elif ch in ('\n', '\r', '\t'):
                result.append(' ')
            else:
                result.append(ch)
            i += 1
        return ''.join(result)

    def _parse_param_list(self, raw: str) -> list:
        """Parse a STEP parameter list into Python values.

        Handles: strings 'foo', numbers, references #123, tuples (a,b,c),
        lists (#1,#2), special tokens ($, *, .ENUM.).
        """
        params = []
        i = 0
        raw = raw.strip()

        while i < len(raw):
            ch = raw[i]

            if ch == ',':
                i += 1
                continue
            elif ch == ' ':
                i += 1
                continue
            elif ch == "'":
                # String literal (ISO 10303-21: '' is escape for literal ')
                j = i + 1
                chars: list[str] = []
                while j < len(raw):
                    if raw[j] == "'":
                        if j + 1 < len(raw) and raw[j + 1] == "'":
                            chars.append("'")
                            j += 2
                        else:
                            break
                    else:
                        chars.append(raw[j])
                        j += 1
                params.append(''.join(chars))
                i = j + 1 if j < len(raw) else j
            elif ch == '#':
                # Entity reference
                j = i + 1
                while j < len(raw) and raw[j].isdigit():
                    j += 1
                params.append(int(raw[i + 1:j]))  # type: ignore[arg-type]
                i = j
            elif ch == '(':
                # Tuple/list — find matching close paren
                depth = 1
                j = i + 1
                while j < len(raw) and depth > 0:
                    if raw[j] == '(':
                        depth += 1
                    elif raw[j] == ')':
                        depth -= 1
                    j += 1
                inner = raw[i + 1:j - 1]
                params.append(self._parse_param_list(inner))  # type: ignore[arg-type]
                i = j
            elif ch == '$':
                params.append(None)  # type: ignore[arg-type]
                i += 1
            elif ch == '*':
                params.append('*')
                i += 1
            elif ch == '.':
                # Enumeration like .ENUM_VALUE.
                try:
                    end = raw.index('.', i + 1)
                except ValueError:
                    # Unterminated enum token — take rest of string
                    end = len(raw)
                params.append(raw[i + 1:end])
                i = end + 1 if end < len(raw) else end
            elif ch in '-0123456789':
                # Number
                j = i + 1
                while j < len(raw) and raw[j] in '0123456789.eE+-':
                    j += 1
                try:
                    val = float(raw[i:j])
                    if val == int(val) and 'e' not in raw[i:j].lower() and '.' not in raw[i:j]:
                        val = int(val)
                    params.append(val)  # type: ignore[arg-type]
                except ValueError:
                    params.append(raw[i:j])
                i = j
            else:
                # Skip unknown characters
                i += 1

        return params

    def _extract_cartesian_points(self) -> None:
        """Extract all CARTESIAN_POINT entities to a dict of id -> (x, y, z)."""
        for eid, entity in self.entities.items():
            if entity.type_name == "CARTESIAN_POINT":
                params = self._parse_param_list(entity.raw_params)
                # CARTESIAN_POINT('label', (x, y, z))
                if len(params) >= 2 and isinstance(params[1], list):
                    coords = params[1]
                    if len(coords) >= 3:
                        try:
                            self._cartesian_points[eid] = (
                                float(coords[0]),
                                float(coords[1]),
                                float(coords[2]),
                            )
                        except (ValueError, TypeError):
                            pass
                    elif len(coords) == 2:
                        try:
                            self._cartesian_points[eid] = (
                                float(coords[0]),
                                float(coords[1]),
                                0.0,
                            )
                        except (ValueError, TypeError):
                            pass

    def _extract_products(self) -> None:
        """Extract PRODUCT entities — these represent components in EDA exports."""
        for eid, entity in self.entities.items():
            if entity.type_name == "PRODUCT":
                params = self._parse_param_list(entity.raw_params)
                # PRODUCT('id/refdes', 'description', '', (context_refs))
                if len(params) >= 2:
                    product_id = str(params[0]) if params[0] else ""
                    description = str(params[1]) if params[1] else ""
                    self._products.append({
                        "entity_id": eid,
                        "name": product_id,
                        "description": description,
                    })

    def _extract_shape_representations(self) -> None:
        """Extract SHAPE_REPRESENTATION and related entities for geometry."""
        for eid, entity in self.entities.items():
            if entity.type_name in (
                "SHAPE_REPRESENTATION",
                "ADVANCED_BREP_SHAPE_REPRESENTATION",
                "MANIFOLD_SURFACE_SHAPE_REPRESENTATION",
                "GEOMETRICALLY_BOUNDED_SURFACE_SHAPE_REPRESENTATION",
                "GEOMETRICALLY_BOUNDED_WIREFRAME_SHAPE_REPRESENTATION",
            ):
                params = self._parse_param_list(entity.raw_params)
                # SHAPE_REPRESENTATION('name', (items...), context_ref)
                if len(params) >= 2 and isinstance(params[1], list):
                    item_refs = [
                        r for r in params[1] if isinstance(r, int)
                    ]
                    self._shapes[eid] = item_refs

    def _resolve_product_placement(self, product_entity_id: int) -> Optional[tuple[float, float, float]]:
        """Try to find the placement position for a product via its definition chain.

        Chain: PRODUCT -> PRODUCT_DEFINITION -> PRODUCT_DEFINITION_SHAPE ->
               SHAPE_DEFINITION_REPRESENTATION -> representation ->
               (ITEM_DEFINED_TRANSFORMATION or) AXIS2_PLACEMENT_3D
        """
        # Find PRODUCT_DEFINITION_FORMATION referencing this product
        pdf_ids = []
        for eid, entity in self.entities.items():
            if entity.type_name == "PRODUCT_DEFINITION_FORMATION" or \
               entity.type_name == "PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE":
                params = self._parse_param_list(entity.raw_params)
                for p in params:
                    if isinstance(p, int) and p == product_entity_id:
                        pdf_ids.append(eid)
                        break

        # Find PRODUCT_DEFINITION referencing the formation
        pd_ids = []
        for pdf_id in pdf_ids:
            for eid, entity in self.entities.items():
                if entity.type_name == "PRODUCT_DEFINITION":
                    params = self._parse_param_list(entity.raw_params)
                    for p in params:
                        if isinstance(p, int) and p == pdf_id:
                            pd_ids.append(eid)
                            break

        # Find NEXT_ASSEMBLY_USAGE_OCCURRENCE referencing the product definition
        # This gives us the placement in the assembly
        nauo_ids = []
        for pd_id in pd_ids:
            for eid, entity in self.entities.items():
                if entity.type_name == "NEXT_ASSEMBLY_USAGE_OCCURRENCE":
                    params = self._parse_param_list(entity.raw_params)
                    for p in params:
                        if isinstance(p, int) and p == pd_id:
                            nauo_ids.append(eid)
                            break

        # Find CONTEXT_DEPENDENT_SHAPE_REPRESENTATION -> REPRESENTATION_RELATIONSHIP
        # -> AXIS2_PLACEMENT_3D for the transformation
        for nauo_id in nauo_ids:
            for eid, entity in self.entities.items():
                if entity.type_name in (
                    "CONTEXT_DEPENDENT_SHAPE_REPRESENTATION",
                ):
                    params = self._parse_param_list(entity.raw_params)
                    for p in params:
                        if isinstance(p, int):
                            rep_rel = self.entities.get(p)
                            if rep_rel and "REPRESENTATION_RELATIONSHIP" in rep_rel.type_name:
                                pos = self._extract_transform_from_rep_rel(p)
                                if pos:
                                    return pos

        # Fallback: look for ITEM_DEFINED_TRANSFORMATION or
        # REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION
        for eid, entity in self.entities.items():
            if "REPRESENTATION_RELATIONSHIP" in entity.type_name and \
               "TRANSFORMATION" in entity.type_name:
                params = self._parse_param_list(entity.raw_params)
                pos = self._extract_transform_from_params(params)
                if pos:
                    # Check if this relates to our product
                    for p in params:
                        if isinstance(p, int):
                            linked = self._is_linked_to_product(p, product_entity_id)
                            if linked:
                                return pos

        return None

    def _extract_transform_from_rep_rel(self, rep_rel_id: int) -> Optional[tuple[float, float, float]]:
        """Extract translation from a REPRESENTATION_RELATIONSHIP entity."""
        entity = self.entities.get(rep_rel_id)
        if not entity:
            return None
        params = self._parse_param_list(entity.raw_params)
        return self._extract_transform_from_params(params)

    def _extract_transform_from_params(self, params: list) -> Optional[tuple[float, float, float]]:
        """Try to extract position from params containing AXIS2_PLACEMENT_3D refs."""
        for p in params:
            if isinstance(p, int):
                ref_entity = self.entities.get(p)
                if ref_entity:
                    if ref_entity.type_name == "AXIS2_PLACEMENT_3D":
                        return self._get_axis2_position(p)
                    elif ref_entity.type_name == "ITEM_DEFINED_TRANSFORMATION":
                        # ITEM_DEFINED_TRANSFORMATION('', '', #axis1, #axis2)
                        inner_params = self._parse_param_list(ref_entity.raw_params)
                        for ip in inner_params:
                            if isinstance(ip, int):
                                inner_entity = self.entities.get(ip)
                                if inner_entity and inner_entity.type_name == "AXIS2_PLACEMENT_3D":
                                    pos = self._get_axis2_position(ip)
                                    if pos and (pos[0] != 0 or pos[1] != 0 or pos[2] != 0):
                                        return pos
        return None

    def _is_linked_to_product(self, entity_id: int, product_id: int, depth: int = 0) -> bool:
        """Check if an entity chain leads to a specific product. Limited depth."""
        if depth > 8:
            return False
        entity = self.entities.get(entity_id)
        if not entity:
            return False
        if entity_id == product_id:
            return True
        params = self._parse_param_list(entity.raw_params)
        for p in params:
            if isinstance(p, int):
                if p == product_id:
                    return True
                if self._is_linked_to_product(p, product_id, depth + 1):
                    return True
        return False

    def _get_axis2_position(self, entity_id: int) -> Optional[tuple[float, float, float]]:
        """Get the origin position from an AXIS2_PLACEMENT_3D entity.

        AXIS2_PLACEMENT_3D('label', #point, #dir1, #dir2)
        """
        entity = self.entities.get(entity_id)
        if not entity or entity.type_name != "AXIS2_PLACEMENT_3D":
            return None

        params = self._parse_param_list(entity.raw_params)
        # Look for cartesian point reference
        for p in params:
            if isinstance(p, int) and p in self._cartesian_points:
                return self._cartesian_points[p]

        return None

    def _is_refdes(self, name: str) -> bool:
        """Check if a name looks like a reference designator."""
        if not name:
            return False
        name_upper = name.upper().strip()
        if self._REFDES_RE.match(name_upper):
            # Extract letter prefix
            m = re.match(r'^([A-Z]+)', name_upper)
            if m and m.group(1) in self._REFDES_PREFIXES:
                return True
        return False

    def _build_components(self) -> list[dict]:
        """Build component list from extracted products and their placements."""
        components = []

        for product in self._products:
            name = product["name"]
            desc = product["description"]
            eid = product["entity_id"]

            # Determine reference designator
            reference = ""
            if self._is_refdes(name):
                reference = name.upper()
            elif self._is_refdes(desc):
                reference = desc.upper()
            else:
                # Not a component (might be the board itself or assembly)
                continue

            # Try to get placement position
            pos = self._resolve_product_placement(eid)
            x, y, z = pos if pos else (0.0, 0.0, 0.0)

            # Try to get bounding box from shape representation
            bbox = self._get_product_bounding_box(eid)

            comp = {
                "reference": reference,
                "description": desc if desc != reference else "",
                "x": round(x, 3),
                "y": round(y, 3),
                "z": round(z, 3),
                "width": round(bbox.get("width", 0), 3) if bbox else 0.0,
                "depth": round(bbox.get("depth", 0), 3) if bbox else 0.0,
                "height": round(bbox.get("height", 0), 3) if bbox else 0.0,
            }
            components.append(comp)

        return components

    def _get_product_bounding_box(self, product_entity_id: int) -> Optional[dict]:
        """Compute bounding box for a product from its shape geometry.

        Traces through: PRODUCT -> PRODUCT_DEFINITION_FORMATION ->
        PRODUCT_DEFINITION -> PRODUCT_DEFINITION_SHAPE ->
        SHAPE_DEFINITION_REPRESENTATION -> SHAPE_REPRESENTATION -> items ->
        collect all CARTESIAN_POINTs
        """
        # Collect all cartesian point refs reachable from this product's shapes
        points = self._collect_points_for_product(product_entity_id)
        if not points:
            return None

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        zs = [p[2] for p in points]

        return {
            "width": max(xs) - min(xs),
            "depth": max(ys) - min(ys),
            "height": max(zs) - min(zs),
            "min_x": min(xs),
            "min_y": min(ys),
            "min_z": min(zs),
            "max_x": max(xs),
            "max_y": max(ys),
            "max_z": max(zs),
        }

    def _collect_points_for_product(self, product_entity_id: int) -> list[tuple[float, float, float]]:
        """Collect all cartesian points associated with a product's shape."""
        points: list[Any] = []

        # Find shape representation IDs linked to this product
        shape_rep_ids = self._find_shape_reps_for_product(product_entity_id)

        for sr_id in shape_rep_ids:
            if sr_id in self._shapes:
                for item_id in self._shapes[sr_id]:
                    self._collect_points_recursive(item_id, points, depth=0)

        return points

    def _find_shape_reps_for_product(self, product_entity_id: int) -> list[int]:
        """Find SHAPE_REPRESENTATION IDs linked to a product."""
        result = []

        # Product -> Product_Definition_Formation
        pdf_ids = []
        for eid, entity in self.entities.items():
            if entity.type_name in ("PRODUCT_DEFINITION_FORMATION",
                                    "PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE"):
                params = self._parse_param_list(entity.raw_params)
                for p in params:
                    if isinstance(p, int) and p == product_entity_id:
                        pdf_ids.append(eid)

        # PDF -> Product_Definition
        pd_ids = []
        for pdf_id in pdf_ids:
            for eid, entity in self.entities.items():
                if entity.type_name == "PRODUCT_DEFINITION":
                    params = self._parse_param_list(entity.raw_params)
                    for p in params:
                        if isinstance(p, int) and p == pdf_id:
                            pd_ids.append(eid)

        # PD -> Product_Definition_Shape
        pds_ids = []
        for pd_id in pd_ids:
            for eid, entity in self.entities.items():
                if entity.type_name == "PRODUCT_DEFINITION_SHAPE":
                    params = self._parse_param_list(entity.raw_params)
                    for p in params:
                        if isinstance(p, int) and p == pd_id:
                            pds_ids.append(eid)

        # PDS -> Shape_Definition_Representation
        for pds_id in pds_ids:
            for eid, entity in self.entities.items():
                if entity.type_name == "SHAPE_DEFINITION_REPRESENTATION":
                    params = self._parse_param_list(entity.raw_params)
                    for p in params:
                        if isinstance(p, int) and p == pds_id:
                            # The other ref in params should be the shape rep
                            for p2 in params:
                                if isinstance(p2, int) and p2 in self._shapes:
                                    result.append(p2)

        return result

    def _collect_points_recursive(self, entity_id: int, points: list, depth: int = 0) -> None:
        """Recursively collect cartesian points from a shape item tree."""
        if depth > 12:
            return  # Prevent infinite recursion
        if entity_id in self._cartesian_points:
            points.append(self._cartesian_points[entity_id])
            return

        entity = self.entities.get(entity_id)
        if not entity:
            return

        params = self._parse_param_list(entity.raw_params)
        for p in params:
            if isinstance(p, int):
                self._collect_points_recursive(p, points, depth + 1)
            elif isinstance(p, list):
                for item in p:
                    if isinstance(item, int):
                        self._collect_points_recursive(item, points, depth + 1)

    def _extract_board_dimensions(self, components: list[dict]) -> dict:
        """Extract board outline dimensions.

        Strategy:
        1. Look for CLOSED_SHELL or MANIFOLD_SOLID_BREP with the largest
           footprint (area in XY) and smallest Z extent — that's likely the board.
        2. Fall back to computing bounding box from all non-component geometry.
        3. Fall back to bounding box from all cartesian points.
        """
        board_3d = {
            "width": 0.0,
            "depth": 0.0,
            "thickness": 0.0,
            "bounding_box": {
                "min_x": 0.0, "min_y": 0.0, "min_z": 0.0,
                "max_x": 0.0, "max_y": 0.0, "max_z": 0.0,
            },
        }

        # Strategy 1: Find board body from CLOSED_SHELL / MANIFOLD_SOLID_BREP
        board_body = self._find_board_body()
        if board_body:
            board_3d["width"] = round(board_body["width"], 3)
            board_3d["depth"] = round(board_body["depth"], 3)
            board_3d["thickness"] = round(board_body["height"], 3)
            board_3d["bounding_box"] = {
                "min_x": round(board_body["min_x"], 3),
                "min_y": round(board_body["min_y"], 3),
                "min_z": round(board_body["min_z"], 3),
                "max_x": round(board_body["max_x"], 3),
                "max_y": round(board_body["max_y"], 3),
                "max_z": round(board_body["max_z"], 3),
            }
            return board_3d

        # Strategy 2: Use all cartesian points as fallback
        if self._cartesian_points:
            all_pts = list(self._cartesian_points.values())
            xs = [p[0] for p in all_pts]
            ys = [p[1] for p in all_pts]
            zs = [p[2] for p in all_pts]

            board_3d["width"] = round(max(xs) - min(xs), 3)
            board_3d["depth"] = round(max(ys) - min(ys), 3)
            board_3d["thickness"] = round(max(zs) - min(zs), 3)
            board_3d["bounding_box"] = {
                "min_x": round(min(xs), 3),
                "min_y": round(min(ys), 3),
                "min_z": round(min(zs), 3),
                "max_x": round(max(xs), 3),
                "max_y": round(max(ys), 3),
                "max_z": round(max(zs), 3),
            }
            self._warnings.append(
                "Board dimensions estimated from overall bounding box (no board body found)"
            )
        else:
            self._warnings.append("No geometry found in STEP file")

        return board_3d

    def _find_board_body(self) -> Optional[dict]:
        """Find the board body — the CLOSED_SHELL or MANIFOLD_SOLID_BREP
        with the largest XY footprint and typical PCB thickness (0.4-3.2mm).

        The board body is typically the entity with the largest area in XY
        and a Z extent consistent with a PCB (0.4-3.2mm typical).
        """
        candidates = []

        for eid, entity in self.entities.items():
            if entity.type_name in ("CLOSED_SHELL", "MANIFOLD_SOLID_BREP"):
                points: list[Any] = []
                self._collect_points_recursive(eid, points, depth=0)
                if len(points) < 4:
                    continue

                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                zs = [p[2] for p in points]

                width = max(xs) - min(xs)
                depth = max(ys) - min(ys)
                height = max(zs) - min(zs)
                area_xy = width * depth

                if width > 0 and depth > 0 and height > 0:
                    candidates.append({
                        "entity_id": eid,
                        "width": width,
                        "depth": depth,
                        "height": height,
                        "area_xy": area_xy,
                        "min_x": min(xs),
                        "min_y": min(ys),
                        "min_z": min(zs),
                        "max_x": max(xs),
                        "max_y": max(ys),
                        "max_z": max(zs),
                    })

        if not candidates:
            return None

        # Prefer candidates with PCB-like thickness (0.4-3.2mm) and large XY area
        pcb_candidates = [
            c for c in candidates
            if 0.3 <= c["height"] <= 4.0 and c["area_xy"] > 100  # >10mm x 10mm
        ]

        if pcb_candidates:
            # Largest XY area with PCB-like thickness
            return max(pcb_candidates, key=lambda c: c["area_xy"])

        # Fallback: largest XY area overall
        return max(candidates, key=lambda c: c["area_xy"])


def compute_3d_clearances(board_3d: dict, step_components: list[dict]) -> dict:
    """Compute clearances between components and between components and board edges.

    Args:
        board_3d: Board 3D dimensions from STEP parser
        step_components: Component list from STEP parser

    Returns:
        Dict with component_clearances, edge_clearances, and issues.
    """
    component_clearances = []
    edge_clearances = []
    issues = []

    bbox = board_3d.get("bounding_box", {})
    board_min_x = bbox.get("min_x", 0)
    board_min_y = bbox.get("min_y", 0)
    board_max_x = bbox.get("max_x", board_3d.get("width", 0))
    board_max_y = bbox.get("max_y", board_3d.get("depth", 0))

    # Component-to-component clearances
    for i, c1 in enumerate(step_components):
        for j, c2 in enumerate(step_components):
            if j <= i:
                continue

            # Calculate center-to-center distance
            dx = c1["x"] - c2["x"]
            dy = c1["y"] - c2["y"]
            dist = math.sqrt(dx * dx + dy * dy)

            # Approximate edge-to-edge gap
            half_extent_1 = max(c1.get("width", 0), c1.get("depth", 0)) / 2
            half_extent_2 = max(c2.get("width", 0), c2.get("depth", 0)) / 2
            gap = dist - half_extent_1 - half_extent_2

            clearance = {
                "component_1": c1["reference"],
                "component_2": c2["reference"],
                "center_distance_mm": round(dist, 3),
                "estimated_gap_mm": round(max(gap, 0), 3),
            }
            component_clearances.append(clearance)

            if gap < 0.5 and gap >= 0:
                issues.append(
                    f"Tight clearance ({gap:.2f}mm) between {c1['reference']} and {c2['reference']}"
                )
            elif gap < 0:
                issues.append(
                    f"Possible overlap between {c1['reference']} and {c2['reference']} "
                    f"(gap={gap:.2f}mm)"
                )

    # Component-to-board-edge clearances
    if board_3d.get("width", 0) > 0 and board_3d.get("depth", 0) > 0:
        for comp in step_components:
            half_w = comp.get("width", 0) / 2
            half_d = comp.get("depth", 0) / 2

            left = comp["x"] - half_w - board_min_x
            right = board_max_x - (comp["x"] + half_w)
            bottom = comp["y"] - half_d - board_min_y
            top = board_max_y - (comp["y"] + half_d)

            min_edge = min(left, right, bottom, top)
            closest_edge = "left" if min_edge == left else \
                           "right" if min_edge == right else \
                           "bottom" if min_edge == bottom else "top"

            edge_cl = {
                "component": comp["reference"],
                "left_mm": round(left, 3),
                "right_mm": round(right, 3),
                "bottom_mm": round(bottom, 3),
                "top_mm": round(top, 3),
                "minimum_mm": round(min_edge, 3),
                "closest_edge": closest_edge,
            }
            edge_clearances.append(edge_cl)

            if min_edge < 1.0:
                issues.append(
                    f"{comp['reference']} is {min_edge:.2f}mm from {closest_edge} board edge"
                )

    return {
        "component_clearances": component_clearances,
        "edge_clearances": edge_clearances,
        "issues": issues,
        "component_count": len(step_components),
    }


def check_enclosure_fit(
    board_3d: dict,
    step_components: list[dict],
    enclosure_width_mm: float,
    enclosure_depth_mm: float,
    enclosure_height_mm: float,
    clearance_mm: float = 1.0,
) -> dict:
    """Check if board + components fit within an enclosure.

    Args:
        board_3d: Board 3D dimensions
        step_components: Component list
        enclosure_width_mm: Internal width of enclosure
        enclosure_depth_mm: Internal depth of enclosure
        enclosure_height_mm: Internal height of enclosure
        clearance_mm: Required clearance on all sides

    Returns:
        Dict with fit result, margins, and issues.
    """
    issues = []

    # Board dimensions
    board_w = board_3d.get("width", 0)
    board_d = board_3d.get("depth", 0)
    board_t = board_3d.get("thickness", 1.6)

    # Compute assembly height (board + tallest component above + below)
    max_height_above = 0.0
    max_height_below = 0.0
    tallest_above_ref = ""
    tallest_below_ref = ""

    board_bbox = board_3d.get("bounding_box", {})
    board_top_z = board_bbox.get("max_z", board_t)
    board_bot_z = board_bbox.get("min_z", 0)

    for comp in step_components:
        comp_z = comp.get("z", 0)
        comp_h = comp.get("height", 0)

        # Component above board
        if comp_z >= board_bot_z:
            protrusion = (comp_z + comp_h) - board_top_z
            if protrusion > max_height_above:
                max_height_above = protrusion
                tallest_above_ref = comp["reference"]

        # Component below board
        if comp_z < board_bot_z:
            protrusion = board_bot_z - comp_z
            if protrusion > max_height_below:
                max_height_below = protrusion
                tallest_below_ref = comp["reference"]

    total_height = board_t + max_height_above + max_height_below

    # Available space (minus clearance on each side)
    avail_w = enclosure_width_mm - 2 * clearance_mm
    avail_d = enclosure_depth_mm - 2 * clearance_mm
    avail_h = enclosure_height_mm - 2 * clearance_mm

    margin_w = avail_w - board_w
    margin_d = avail_d - board_d
    margin_h = avail_h - total_height

    fits = margin_w >= 0 and margin_d >= 0 and margin_h >= 0

    if margin_w < 0:
        issues.append(
            f"Board too wide: {board_w:.1f}mm vs {avail_w:.1f}mm available "
            f"(exceeds by {-margin_w:.1f}mm)"
        )
    if margin_d < 0:
        issues.append(
            f"Board too deep: {board_d:.1f}mm vs {avail_d:.1f}mm available "
            f"(exceeds by {-margin_d:.1f}mm)"
        )
    if margin_h < 0:
        issues.append(
            f"Assembly too tall: {total_height:.1f}mm vs {avail_h:.1f}mm available "
            f"(exceeds by {-margin_h:.1f}mm)"
        )

    return {
        "fits": fits,
        "board_width_mm": round(board_w, 3),
        "board_depth_mm": round(board_d, 3),
        "board_thickness_mm": round(board_t, 3),
        "assembly_height_mm": round(total_height, 3),
        "max_component_height_above_mm": round(max_height_above, 3),
        "max_component_height_below_mm": round(max_height_below, 3),
        "tallest_component_above": tallest_above_ref,
        "tallest_component_below": tallest_below_ref,
        "enclosure": {
            "width_mm": enclosure_width_mm,
            "depth_mm": enclosure_depth_mm,
            "height_mm": enclosure_height_mm,
            "clearance_mm": clearance_mm,
        },
        "margins": {
            "width_mm": round(margin_w, 3),
            "depth_mm": round(margin_d, 3),
            "height_mm": round(margin_h, 3),
        },
        "issues": issues,
    }

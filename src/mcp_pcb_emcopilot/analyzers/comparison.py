"""Design revision comparison — diff two PCBDesignData instances."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import math


@dataclass
class ComponentChange:
    ref_des: str
    change_type: str  # "added", "removed", "moved", "rotated", "value_changed", "package_changed"
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    detail: str = ""


@dataclass
class NetChange:
    net_name: str
    change_type: str  # "added", "removed", "trace_count_changed"
    detail: str = ""


@dataclass
class DesignComparison:
    design_a_file: str
    design_b_file: str

    board_size_changed: bool = False
    old_dimensions: tuple[float, float] = (0.0, 0.0)
    new_dimensions: tuple[float, float] = (0.0, 0.0)
    layer_count_changed: bool = False
    old_layer_count: int = 0
    new_layer_count: int = 0

    component_changes: list[ComponentChange] = field(default_factory=list)
    components_added: int = 0
    components_removed: int = 0
    components_moved: int = 0

    net_changes: list[NetChange] = field(default_factory=list)
    nets_added: int = 0
    nets_removed: int = 0

    total_changes: int = 0
    summary: str = ""


class DesignComparator:
    """Compare two PCB design revisions."""

    MOVE_THRESHOLD_MM = 0.5  # Position change > 0.5mm counts as "moved"
    ROTATION_THRESHOLD_DEG = 1.0  # Rotation change > 1 degree counts as "rotated"

    def compare(self, design_a, design_b) -> DesignComparison:
        """Compare two PCBDesignData instances.

        design_a is the "before" (old) design.
        design_b is the "after" (new) design.
        """
        result = DesignComparison(
            design_a_file=getattr(design_a, 'source_file', 'unknown'),
            design_b_file=getattr(design_b, 'source_file', 'unknown'),
        )

        self._compare_board(design_a, design_b, result)
        self._compare_components(design_a, design_b, result)
        self._compare_nets(design_a, design_b, result)

        result.total_changes = (
            result.components_added + result.components_removed + result.components_moved
            + result.nets_added + result.nets_removed
            + (1 if result.board_size_changed else 0)
            + (1 if result.layer_count_changed else 0)
        )

        self._generate_summary(result)
        return result

    def _compare_board(self, a, b, result):
        old_w = getattr(a, 'board_width_mm', 0) or 0
        old_h = getattr(a, 'board_height_mm', 0) or 0
        new_w = getattr(b, 'board_width_mm', 0) or 0
        new_h = getattr(b, 'board_height_mm', 0) or 0

        result.old_dimensions = (old_w, old_h)
        result.new_dimensions = (new_w, new_h)
        result.board_size_changed = (
            abs(old_w - new_w) > 0.01 or abs(old_h - new_h) > 0.01
        )

        old_layers = getattr(a, 'layer_count', 0) or 0
        new_layers = getattr(b, 'layer_count', 0) or 0
        result.old_layer_count = old_layers
        result.new_layer_count = new_layers
        result.layer_count_changed = old_layers != new_layers

    def _compare_components(self, a, b, result):
        # Build lookup by ref_des
        a_comps = {}
        for c in getattr(a, 'components', []):
            ref = getattr(c, 'ref_des', None) or getattr(c, 'reference', None) or ''
            if ref:
                a_comps[ref] = c

        b_comps = {}
        for c in getattr(b, 'components', []):
            ref = getattr(c, 'ref_des', None) or getattr(c, 'reference', None) or ''
            if ref:
                b_comps[ref] = c

        a_refs = set(a_comps.keys())
        b_refs = set(b_comps.keys())

        # Added components
        for ref in sorted(b_refs - a_refs):
            result.component_changes.append(ComponentChange(
                ref_des=ref, change_type="added",
                new_value=getattr(b_comps[ref], 'value', '') or getattr(b_comps[ref], 'package', ''),
                detail=f"New component {ref}",
            ))
            result.components_added += 1

        # Removed components
        for ref in sorted(a_refs - b_refs):
            result.component_changes.append(ComponentChange(
                ref_des=ref, change_type="removed",
                old_value=getattr(a_comps[ref], 'value', '') or getattr(a_comps[ref], 'package', ''),
                detail=f"Removed component {ref}",
            ))
            result.components_removed += 1

        # Modified components
        for ref in sorted(a_refs & b_refs):
            ac = a_comps[ref]
            bc = b_comps[ref]

            # Check position change
            ax = getattr(ac, 'x_mm', 0) or getattr(ac, 'x', 0) or 0
            ay = getattr(ac, 'y_mm', 0) or getattr(ac, 'y', 0) or 0
            bx = getattr(bc, 'x_mm', 0) or getattr(bc, 'x', 0) or 0
            by = getattr(bc, 'y_mm', 0) or getattr(bc, 'y', 0) or 0

            dist = math.sqrt((bx - ax)**2 + (by - ay)**2)
            if dist > self.MOVE_THRESHOLD_MM:
                result.component_changes.append(ComponentChange(
                    ref_des=ref, change_type="moved",
                    old_value=f"({ax:.2f}, {ay:.2f})",
                    new_value=f"({bx:.2f}, {by:.2f})",
                    detail=f"Moved {dist:.2f}mm",
                ))
                result.components_moved += 1
                continue

            # Check rotation
            ar = getattr(ac, 'rotation', 0) or 0
            br = getattr(bc, 'rotation', 0) or 0
            if abs(br - ar) > self.ROTATION_THRESHOLD_DEG:
                result.component_changes.append(ComponentChange(
                    ref_des=ref, change_type="rotated",
                    old_value=f"{ar:.1f}\u00b0",
                    new_value=f"{br:.1f}\u00b0",
                    detail=f"Rotated from {ar:.1f}\u00b0 to {br:.1f}\u00b0",
                ))
                result.components_moved += 1
                continue

            # Check value change
            av = getattr(ac, 'value', '') or ''
            bv = getattr(bc, 'value', '') or ''
            if av != bv and (av or bv):
                result.component_changes.append(ComponentChange(
                    ref_des=ref, change_type="value_changed",
                    old_value=av, new_value=bv,
                    detail=f"Value changed from '{av}' to '{bv}'",
                ))

    def _compare_nets(self, a, b, result):
        a_nets = set()
        for n in getattr(a, 'nets', []):
            name = getattr(n, 'name', '') or getattr(n, 'net_name', '') or ''
            if name:
                a_nets.add(name)

        b_nets = set()
        for n in getattr(b, 'nets', []):
            name = getattr(n, 'name', '') or getattr(n, 'net_name', '') or ''
            if name:
                b_nets.add(name)

        for name in sorted(b_nets - a_nets):
            result.net_changes.append(NetChange(
                net_name=name, change_type="added",
                detail=f"New net {name}",
            ))
            result.nets_added += 1

        for name in sorted(a_nets - b_nets):
            result.net_changes.append(NetChange(
                net_name=name, change_type="removed",
                detail=f"Removed net {name}",
            ))
            result.nets_removed += 1

    def _generate_summary(self, result):
        parts = []
        if result.board_size_changed:
            parts.append(f"Board resized from {result.old_dimensions[0]:.1f}x{result.old_dimensions[1]:.1f}mm to {result.new_dimensions[0]:.1f}x{result.new_dimensions[1]:.1f}mm")
        if result.layer_count_changed:
            parts.append(f"Layer count changed from {result.old_layer_count} to {result.new_layer_count}")
        if result.components_added:
            parts.append(f"{result.components_added} component(s) added")
        if result.components_removed:
            parts.append(f"{result.components_removed} component(s) removed")
        if result.components_moved:
            parts.append(f"{result.components_moved} component(s) moved/rotated")
        if result.nets_added:
            parts.append(f"{result.nets_added} net(s) added")
        if result.nets_removed:
            parts.append(f"{result.nets_removed} net(s) removed")

        if not parts:
            result.summary = "No significant changes detected between designs."
        else:
            result.summary = "; ".join(parts) + f". Total: {result.total_changes} change(s)."

    def to_dict(self, comparison: DesignComparison) -> dict:
        """Convert comparison to dict for tool output."""
        return {
            "design_a": comparison.design_a_file,
            "design_b": comparison.design_b_file,
            "board_changes": {
                "size_changed": comparison.board_size_changed,
                "old_dimensions_mm": list(comparison.old_dimensions),
                "new_dimensions_mm": list(comparison.new_dimensions),
                "layer_count_changed": comparison.layer_count_changed,
                "old_layer_count": comparison.old_layer_count,
                "new_layer_count": comparison.new_layer_count,
            },
            "component_changes": {
                "added": comparison.components_added,
                "removed": comparison.components_removed,
                "moved": comparison.components_moved,
                "details": [
                    {"ref_des": c.ref_des, "type": c.change_type,
                     "old": c.old_value, "new": c.new_value, "detail": c.detail}
                    for c in comparison.component_changes
                ],
            },
            "net_changes": {
                "added": comparison.nets_added,
                "removed": comparison.nets_removed,
                "details": [
                    {"net": n.net_name, "type": n.change_type, "detail": n.detail}
                    for n in comparison.net_changes
                ],
            },
            "total_changes": comparison.total_changes,
            "summary": comparison.summary,
        }

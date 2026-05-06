"""Design revision comparator — diff between Rev A and Rev B."""
from __future__ import annotations

import math
from typing import Any, Dict


class RevisionComparator:
    """Compare two PCBDesignData objects and report differences."""

    def compare(self, design_a: Any, design_b: Any) -> Dict[str, Any]:
        """Compare two designs and return structured diff."""
        diff: Dict[str, Any] = {
            "components": self._compare_components(design_a, design_b),
            "nets": self._compare_nets(design_a, design_b),
            "stackup": self._compare_stackup(design_a, design_b),
            "traces": self._compare_traces(design_a, design_b),
            "vias": self._compare_vias(design_a, design_b),
            "board": self._compare_board(design_a, design_b),
        }
        # Summary
        added = diff["components"]["added_count"] + diff["nets"]["added_count"]
        removed = diff["components"]["removed_count"] + diff["nets"]["removed_count"]
        changed = diff["components"]["moved_count"] + diff["components"]["value_changed_count"]
        diff["summary"] = {
            "total_additions": added,
            "total_removals": removed,
            "total_changes": changed,
            "is_significant": added + removed + changed > 5,
        }
        return diff

    def _compare_components(self, a: Any, b: Any) -> Dict:
        a_map = {c.reference: c for c in a.components}
        b_map = {c.reference: c for c in b.components}
        added = [ref for ref in b_map if ref not in a_map]
        removed = [ref for ref in a_map if ref not in b_map]
        moved = []
        value_changed = []
        for ref in set(a_map) & set(b_map):
            ca, cb = a_map[ref], b_map[ref]
            dist = math.sqrt((ca.x_mm - cb.x_mm)**2 + (ca.y_mm - cb.y_mm)**2)
            if dist > 1.0:
                moved.append({"ref": ref, "distance_mm": round(dist, 2),
                              "from": (round(ca.x_mm, 1), round(ca.y_mm, 1)),
                              "to": (round(cb.x_mm, 1), round(cb.y_mm, 1))})
            va = (ca.value or "").strip().upper()
            vb = (cb.value or "").strip().upper()
            if va != vb and va and vb:
                value_changed.append({"ref": ref, "from": ca.value, "to": cb.value})
        return {
            "added": added[:20], "added_count": len(added),
            "removed": removed[:20], "removed_count": len(removed),
            "moved": moved[:20], "moved_count": len(moved),
            "value_changed": value_changed[:20], "value_changed_count": len(value_changed),
        }

    def _compare_nets(self, a: Any, b: Any) -> Dict:
        a_names = {n.name for n in a.nets}
        b_names = {n.name for n in b.nets}
        return {
            "added": sorted(b_names - a_names)[:20],
            "added_count": len(b_names - a_names),
            "removed": sorted(a_names - b_names)[:20],
            "removed_count": len(a_names - b_names),
            "common_count": len(a_names & b_names),
        }

    def _compare_stackup(self, a: Any, b: Any) -> Dict:
        a_layers = [(l.name, l.layer_type, l.thickness_mm) for l in a.layers if l.layer_type in ('signal', 'plane', 'dielectric')]
        b_layers = [(l.name, l.layer_type, l.thickness_mm) for l in b.layers if l.layer_type in ('signal', 'plane', 'dielectric')]
        return {
            "a_layer_count": len(a_layers),
            "b_layer_count": len(b_layers),
            "layer_count_changed": len(a_layers) != len(b_layers),
            "a_layers": [(n, t) for n, t, _ in a_layers],
            "b_layers": [(n, t) for n, t, _ in b_layers],
        }

    def _compare_traces(self, a: Any, b: Any) -> Dict:
        return {
            "a_count": len(a.traces), "b_count": len(b.traces),
            "delta": len(b.traces) - len(a.traces),
        }

    def _compare_vias(self, a: Any, b: Any) -> Dict:
        return {
            "a_count": len(a.vias), "b_count": len(b.vias),
            "delta": len(b.vias) - len(a.vias),
        }

    def _compare_board(self, a: Any, b: Any) -> Dict:
        return {
            "a_size": f"{a.board_width_mm:.1f}x{a.board_height_mm:.1f}" if a.board_width_mm else "?",
            "b_size": f"{b.board_width_mm:.1f}x{b.board_height_mm:.1f}" if b.board_width_mm else "?",
            "size_changed": abs((a.board_width_mm or 0) - (b.board_width_mm or 0)) > 0.5 or
                           abs((a.board_height_mm or 0) - (b.board_height_mm or 0)) > 0.5,
        }

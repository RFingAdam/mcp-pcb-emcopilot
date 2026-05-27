"""Shared geometric pin → net resolver.

Both KiCad and Altium schematic parsers face the same problem: a pin
sits at a coordinate, a wire runs through it, and a net label
anchored at a wire endpoint names the net. Neither tool exports an
explicit netlist in the schematic file itself, so we infer
connectivity from geometry.

This module is the algorithm in one place so both parsers can call
it without drifting.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

DEFAULT_SNAP_MM = 0.51


def resolve_pins_by_geometry(
    components: Iterable[Any],
    wires: list[dict[str, Any]],
    labels: list[dict[str, Any]],
    junctions: list[dict[str, Any]],
    nets: Optional[dict[str, Any]] = None,
    snap_mm: float = DEFAULT_SNAP_MM,
) -> None:
    """Tag each component pin with the net of the nearest label.

    Args:
        components: iterable of objects with a ``pins`` list of dicts
            (``ParsedComponent`` or ``AltiumComponent``). Each pin dict
            should expose ``x_abs`` / ``y_abs`` (absolute coords in mm);
            if absent, the component's own coordinate is used.
        wires: list of ``{x1, y1, x2, y2}`` dicts in mm. Currently
            unused in the snap-to-label heuristic but reserved so the
            signature is stable as we add wire-walk net merging later.
        labels: list of ``{name, x, y}`` dicts in mm.
        junctions: list of ``{x, y}`` dicts in mm. Currently unused —
            reserved for future cross-wire merging.
        nets: optional mapping of ``{net_name -> net_object}`` where
            ``net_object.pins`` is a list to append discovered pin
            connections to. Pass ``None`` to skip the back-reference.
        snap_mm: maximum distance from a pin to a label anchor for
            the pin to be considered connected to that label's net.

    Side effects:
        - Each pin dict gets ``pin['net'] = label_name`` when within
          tolerance.
        - When ``nets`` is provided, the matching net object gets a
          ``{'component': ref, 'pin_number': n}`` entry appended to
          its ``pins`` list.
    """
    if not wires or not labels:
        # Mark these as deliberately observed — the snap-to-label
        # heuristic needs both to work, and the caller should not
        # assume any pins were resolved if either is empty.
        _ = wires, junctions
        return

    snap_sq = snap_mm ** 2

    # Pre-compute label name → anchor coordinate. If multiple labels
    # share a name (common for power nets like GND), the first wins;
    # downstream geometry won't care because they share the same name.
    label_anchors: dict[str, tuple[float, float]] = {}
    for label in labels:
        label_anchors.setdefault(label["name"], (label["x"], label["y"]))

    for comp in components:
        pins = getattr(comp, "pins", None)
        if not pins:
            continue
        ref = getattr(comp, "reference", "")
        comp_x = getattr(comp, "x_coord", None)
        if comp_x is None:
            comp_x = getattr(comp, "x_mm", 0.0)
        comp_y = getattr(comp, "y_coord", None)
        if comp_y is None:
            comp_y = getattr(comp, "y_mm", 0.0)

        for pin in pins:
            # Skip pins that already have an explicit NetIdentifier
            # — the caller resolved them ahead of the geometric pass.
            if pin.get("net"):
                continue

            px = float(pin.get("x_abs", comp_x))
            py = float(pin.get("y_abs", comp_y))
            best_net: Optional[str] = None
            best_d2 = snap_sq

            for name, (lx, ly) in label_anchors.items():
                d2 = (px - lx) ** 2 + (py - ly) ** 2
                if d2 <= best_d2:
                    best_d2 = d2
                    best_net = name

            if best_net is not None:
                pin["net"] = best_net
                if nets is not None:
                    net = nets.get(best_net)
                    if net is not None and hasattr(net, "pins"):
                        net.pins.append({
                            "component": ref,
                            "pin_number": pin.get("pin_number", ""),
                        })

    # Junctions reserved for future cross-wire net merging.
    _ = junctions

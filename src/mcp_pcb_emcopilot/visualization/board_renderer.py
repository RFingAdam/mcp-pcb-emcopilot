"""SVG board renderer for PCB design visualization.

Generates SVG from PCBDesignData — board outline, component placement,
net/trace highlighting, via positions, copper zones, and layer views.

Pure Python, no external dependencies (SVG is XML text).
"""

from __future__ import annotations

from typing import Optional
from xml.sax.saxutils import escape

from ..models.pcb_data import PCBDesignData

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

# Component type heuristic colour map (prefix -> fill colour)
_COMP_COLOURS = {
    "U": "#4A90D9",      # ICs — blue
    "IC": "#4A90D9",
    "J": "#E88D3F",      # connectors — orange
    "P": "#E88D3F",
    "CON": "#E88D3F",
    "R": "#5CB85C",      # passives — green
    "C": "#5CB85C",
    "L": "#5CB85C",
    "D": "#D94A7A",      # diodes/LEDs — pink
    "LED": "#D94A7A",
    "Q": "#9B59B6",      # transistors — purple
    "T": "#9B59B6",
    "F": "#F5A623",      # fuses — amber
    "SW": "#8E8E93",     # switches — grey
    "TP": "#AAAAAA",     # test points — light grey
    "Y": "#C0392B",      # crystals — red
    "X": "#C0392B",
}

_DEFAULT_COMP_COLOUR = "#888888"

_BOARD_FILL = "#1A1A2E"
_BOARD_STROKE = "#E0E0E0"
_TRACE_COLOUR = "#FFD700"
_VIA_COLOUR = "#FF6B6B"
_VIA_DRILL_COLOUR = "#1A1A2E"
_ZONE_COLOUR = "rgba(255,215,0,0.15)"
_HIGHLIGHT_COLOUR = "#FF4136"
_GRID_COLOUR = "#333355"
_TEXT_COLOUR = "#E0E0E0"
_DIM_COLOUR = "#888888"

# Layer colours for copper layers
_LAYER_COLOURS = {
    "F.Cu": "#FF4444",
    "B.Cu": "#4444FF",
    "In1.Cu": "#44FF44",
    "In2.Cu": "#FFFF44",
    "In3.Cu": "#FF44FF",
    "In4.Cu": "#44FFFF",
}


def _comp_colour(reference: str) -> str:
    """Return fill colour based on component reference prefix."""
    ref_upper = reference.upper()
    for prefix, colour in _COMP_COLOURS.items():
        if ref_upper.startswith(prefix):
            return colour
    return _DEFAULT_COMP_COLOUR


def _esc(text: str) -> str:
    return escape(str(text))


# ---------------------------------------------------------------------------
# BoardRenderer
# ---------------------------------------------------------------------------

class BoardRenderer:
    """Render a PCBDesignData into SVG strings."""

    def __init__(self, design: PCBDesignData, width_px: int = 800):
        self.design = design
        self.width_px = width_px

        # Board extent
        bw = design.board_width_mm or 100.0
        bh = design.board_height_mm or 100.0
        self.board_w = max(bw, 1.0)
        self.board_h = max(bh, 1.0)

        # Margin around the board (mm)
        self.margin = max(self.board_w, self.board_h) * 0.12

        # Scale: pixels per mm
        total_w = self.board_w + 2 * self.margin
        self.scale = self.width_px / total_w
        self.height_px = int((self.board_h + 2 * self.margin) * self.scale)

    # ----- coordinate helpers -----

    def _x(self, mm: float) -> float:
        """Convert board mm X to SVG px."""
        return (mm + self.margin) * self.scale

    def _y(self, mm: float) -> float:
        """Convert board mm Y to SVG px (Y flipped: 0 at top)."""
        return (self.board_h - mm + self.margin) * self.scale

    def _sx(self, mm: float) -> float:
        """Scale a distance (no offset)."""
        return mm * self.scale

    # ----- SVG scaffolding -----

    def _svg_header(self, title: str = "PCB Board View") -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{self.width_px}" height="{self.height_px}" '
            f'viewBox="0 0 {self.width_px} {self.height_px}" '
            f'style="background:{_BOARD_FILL}">\n'
            f'<title>{_esc(title)}</title>\n'
            f'<defs>\n'
            f'  <style>\n'
            f'    text {{ font-family: monospace; fill: {_TEXT_COLOUR}; }}\n'
            f'    .dim {{ font-size: 10px; fill: {_DIM_COLOUR}; }}\n'
            f'    .refdes {{ font-size: 8px; fill: white; text-anchor: middle; dominant-baseline: central; }}\n'
            f'    .title-text {{ font-size: 14px; font-weight: bold; fill: {_TEXT_COLOUR}; }}\n'
            f'    .scale-text {{ font-size: 9px; fill: {_DIM_COLOUR}; }}\n'
            f'  </style>\n'
            f'</defs>\n'
        )

    @staticmethod
    def _svg_footer() -> str:
        return '</svg>\n'

    # ----- drawing primitives -----

    def _draw_board_outline(self) -> str:
        """Draw the board outline rectangle (or polygon if vertices exist)."""
        lines: list[str] = []
        outline = self.design.board_outline
        bod = self.design.board_outline_detail

        vertices = (bod.get("vertices") if bod else None) or outline
        if vertices and len(vertices) >= 3:
            pts = " ".join(
                f"{self._x(v[0]):.1f},{self._y(v[1]):.1f}"
                for v in vertices
                if isinstance(v, (list, tuple)) and len(v) >= 2
            )
            if pts:
                lines.append(
                    f'<polygon points="{pts}" '
                    f'fill="none" stroke="{_BOARD_STROKE}" stroke-width="2"/>\n'
                )
                return "".join(lines)

        # Fallback: rectangle from board_width/height
        x0, y0 = self._x(0), self._y(self.board_h)
        w, h = self._sx(self.board_w), self._sx(self.board_h)
        lines.append(
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="none" stroke="{_BOARD_STROKE}" stroke-width="2" rx="2"/>\n'
        )
        return "".join(lines)

    def _draw_dimensions(self) -> str:
        """Draw board width/height dimension labels."""
        lines: list[str] = []
        # Width label (below board)
        cx = self._x(self.board_w / 2)
        by = self._y(0) + 18
        lines.append(
            f'<text x="{cx:.1f}" y="{by:.1f}" class="dim" text-anchor="middle">'
            f'{self.board_w:.1f} mm</text>\n'
        )
        # Height label (left of board)
        lx = self._x(0) - 8
        cy = self._y(self.board_h / 2)
        lines.append(
            f'<text x="{lx:.1f}" y="{cy:.1f}" class="dim" text-anchor="end" '
            f'transform="rotate(-90,{lx:.1f},{cy:.1f})">'
            f'{self.board_h:.1f} mm</text>\n'
        )
        return "".join(lines)

    def _draw_title_block(self, title: str | None = None) -> str:
        """Draw title and scale bar in the bottom-right."""
        lines: list[str] = []
        label = title or self.design.title or self.design.source_file or "PCB"
        tx = self.width_px - 10
        ty = self.height_px - 8
        lines.append(
            f'<text x="{tx:.0f}" y="{ty:.0f}" class="title-text" '
            f'text-anchor="end">{_esc(label)}</text>\n'
        )

        # Scale bar: 10 mm reference
        bar_mm = 10.0
        if bar_mm > self.board_w * 0.4:
            bar_mm = round(self.board_w * 0.25, 1) or 1.0
        bar_px = self._sx(bar_mm)
        bx = self.width_px - 10 - bar_px
        by = self.height_px - 24
        lines.append(
            f'<line x1="{bx:.1f}" y1="{by:.1f}" '
            f'x2="{bx + bar_px:.1f}" y2="{by:.1f}" '
            f'stroke="{_DIM_COLOUR}" stroke-width="2"/>\n'
            f'<line x1="{bx:.1f}" y1="{by - 3:.1f}" '
            f'x2="{bx:.1f}" y2="{by + 3:.1f}" '
            f'stroke="{_DIM_COLOUR}" stroke-width="1"/>\n'
            f'<line x1="{bx + bar_px:.1f}" y1="{by - 3:.1f}" '
            f'x2="{bx + bar_px:.1f}" y2="{by + 3:.1f}" '
            f'stroke="{_DIM_COLOUR}" stroke-width="1"/>\n'
            f'<text x="{bx + bar_px / 2:.1f}" y="{by - 5:.1f}" '
            f'class="scale-text" text-anchor="middle">{bar_mm:.0f} mm</text>\n'
        )
        return "".join(lines)

    def _draw_components(
        self,
        highlight_refs: Optional[set[str]] = None,
        layer_filter: Optional[str] = None,
    ) -> str:
        """Draw component rectangles with ref-des labels."""
        lines: list[str] = []
        for comp in self.design.components:
            if layer_filter and comp.layer != layer_filter:
                continue

            # Estimate component size from package/footprint
            w_mm, h_mm = _estimate_package_size(comp.package or comp.footprint or "")
            cx = self._x(comp.x_mm)
            cy = self._y(comp.y_mm)
            pw = self._sx(w_mm)
            ph = self._sx(h_mm)

            colour = _comp_colour(comp.reference)
            opacity = "1.0"
            stroke = "none"
            if highlight_refs is not None:
                if comp.reference in highlight_refs:
                    stroke = _HIGHLIGHT_COLOUR
                    opacity = "1.0"
                else:
                    opacity = "0.25"

            rot = comp.rotation or 0
            transform = f' transform="rotate({-rot:.1f},{cx:.1f},{cy:.1f})"' if rot else ""

            lines.append(
                f'<rect x="{cx - pw / 2:.1f}" y="{cy - ph / 2:.1f}" '
                f'width="{pw:.1f}" height="{ph:.1f}" '
                f'fill="{colour}" fill-opacity="{opacity}" '
                f'stroke="{stroke}" stroke-width="1.5" rx="1"'
                f'{transform}/>\n'
            )
            # Ref-des label
            font_sz = max(6, min(10, pw * 0.6))
            lines.append(
                f'<text x="{cx:.1f}" y="{cy:.1f}" '
                f'class="refdes" font-size="{font_sz:.0f}px" '
                f'opacity="{opacity}"'
                f'{transform}>{_esc(comp.reference)}</text>\n'
            )
        return "".join(lines)

    def _draw_traces(
        self,
        net_names: Optional[set[str]] = None,
        layer_filter: Optional[str] = None,
        colour: str = _TRACE_COLOUR,
    ) -> str:
        """Draw trace segments."""
        lines: list[str] = []
        for tr in self.design.traces:
            if layer_filter and tr.layer != layer_filter:
                continue
            if net_names is not None and tr.net_name not in net_names:
                continue

            lw = max(1.0, self._sx(tr.width_mm))
            c = colour
            if net_names is None and tr.layer in _LAYER_COLOURS:
                c = _LAYER_COLOURS[tr.layer]

            x1, y1 = self._x(tr.x1_mm), self._y(tr.y1_mm)
            x2, y2 = self._x(tr.x2_mm), self._y(tr.y2_mm)
            lines.append(
                f'<line x1="{x1:.1f}" y1="{y1:.1f}" '
                f'x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="{c}" stroke-width="{lw:.1f}" '
                f'stroke-linecap="round" opacity="0.85"/>\n'
            )
        return "".join(lines)

    def _draw_vias(
        self,
        net_names: Optional[set[str]] = None,
        colour: str = _VIA_COLOUR,
    ) -> str:
        """Draw via positions as circles."""
        lines: list[str] = []
        for via in self.design.vias:
            if net_names is not None and via.net_name not in net_names:
                continue
            cx = self._x(via.x_mm)
            cy = self._y(via.y_mm)
            r_pad = max(2.0, self._sx(via.pad_diameter_mm / 2)) if via.pad_diameter_mm else max(2.0, self._sx(via.drill_mm * 0.8))
            r_drill = max(1.0, self._sx(via.drill_mm / 2))
            lines.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r_pad:.1f}" '
                f'fill="{colour}" opacity="0.8"/>\n'
            )
            lines.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r_drill:.1f}" '
                f'fill="{_VIA_DRILL_COLOUR}"/>\n'
            )
        return "".join(lines)

    def _draw_zones(
        self,
        net_names: Optional[set[str]] = None,
        layer_filter: Optional[str] = None,
    ) -> str:
        """Draw copper zone outlines."""
        lines: list[str] = []
        for zone in self.design.zones:
            if layer_filter and zone.layer != layer_filter:
                continue
            if net_names is not None and zone.net_name not in net_names:
                continue
            if not zone.outline:
                continue

            pts = " ".join(
                f"{self._x(p[0]):.1f},{self._y(p[1]):.1f}"
                for p in zone.outline
                if isinstance(p, (list, tuple)) and len(p) >= 2
            )
            if pts:
                fill = _ZONE_COLOUR
                lines.append(
                    f'<polygon points="{pts}" fill="{fill}" '
                    f'stroke="#FFD700" stroke-width="0.5" stroke-dasharray="3,3" '
                    f'opacity="0.35"/>\n'
                )
        return "".join(lines)

    def _draw_copper_pours(
        self,
        layer_filter: Optional[str] = None,
    ) -> str:
        """Draw copper pour areas from board_outline_detail / copper_pours."""
        lines: list[str] = []
        for pour in self.design.copper_pours:
            if layer_filter and pour.get("layer") != layer_filter:
                continue
            outline = pour.get("outline", [])
            if not outline:
                continue
            pts = " ".join(
                f"{self._x(p[0]):.1f},{self._y(p[1]):.1f}"
                for p in outline
                if isinstance(p, (list, tuple)) and len(p) >= 2
            )
            if pts:
                lines.append(
                    f'<polygon points="{pts}" fill="#FFD700" '
                    f'fill-opacity="0.1" stroke="#FFD700" '
                    f'stroke-width="0.5" stroke-dasharray="4,2"/>\n'
                )
        return "".join(lines)

    # ----- public render methods -----

    def render_board(
        self,
        layers: Optional[list[str]] = None,
        highlight_nets: Optional[list[str]] = None,
        highlight_components: Optional[list[str]] = None,
    ) -> str:
        """Full board view with optional layer/net/component highlighting.

        Returns SVG string.
        """
        hl_nets = set(highlight_nets) if highlight_nets else None
        hl_comps = set(highlight_components) if highlight_components else None
        layer_filter = layers[0] if layers and len(layers) == 1 else None

        parts: list[str] = [self._svg_header("Board View")]

        # Board outline
        parts.append(self._draw_board_outline())

        # Zones / copper pours
        parts.append(self._draw_zones(net_names=hl_nets, layer_filter=layer_filter))
        parts.append(self._draw_copper_pours(layer_filter=layer_filter))

        # Traces
        if hl_nets:
            # Draw non-highlighted traces dimmed, then highlighted on top
            parts.append(
                f'<g opacity="0.15">{self._draw_traces(layer_filter=layer_filter)}</g>\n'
            )
            parts.append(
                self._draw_traces(net_names=hl_nets, layer_filter=layer_filter, colour=_HIGHLIGHT_COLOUR)
            )
        else:
            parts.append(self._draw_traces(layer_filter=layer_filter))

        # Vias
        parts.append(self._draw_vias(net_names=hl_nets))

        # Components
        parts.append(self._draw_components(highlight_refs=hl_comps, layer_filter=layer_filter))

        # Dimensions + title
        parts.append(self._draw_dimensions())
        parts.append(self._draw_title_block())

        parts.append(self._svg_footer())
        return "".join(parts)

    def render_net(self, net_name: str) -> str:
        """Render a single net highlighted on the board.

        Shows all board features dimmed, with the target net in highlight colour.
        Returns SVG string.
        """
        net = self.design.get_net_by_name(net_name)
        if not net:
            raise ValueError(f"Net '{net_name}' not found in design")

        net_names = {net.name}

        parts: list[str] = [self._svg_header(f"Net: {net_name}")]

        parts.append(self._draw_board_outline())

        # Dimmed background
        parts.append('<g opacity="0.12">\n')
        parts.append(self._draw_traces())
        parts.append(self._draw_vias())
        parts.append(self._draw_components())
        parts.append('</g>\n')

        # Highlighted net
        parts.append(self._draw_traces(net_names=net_names, colour=_HIGHLIGHT_COLOUR))
        parts.append(self._draw_vias(net_names=net_names, colour=_HIGHLIGHT_COLOUR))

        # Draw pads for the net's components (find components connected to net)
        connected_vias = [v for v in self.design.vias if v.net_name == net.name]
        connected_traces = [t for t in self.design.traces if t.net_name == net.name]

        # Label the net
        # Find a representative point for the label
        label_x, label_y = self._x(self.board_w / 2), self._y(self.board_h / 2)
        if connected_traces:
            t0 = connected_traces[0]
            label_x = self._x((t0.x1_mm + t0.x2_mm) / 2)
            label_y = self._y((t0.y1_mm + t0.y2_mm) / 2) - 12
        elif connected_vias:
            label_x = self._x(connected_vias[0].x_mm)
            label_y = self._y(connected_vias[0].y_mm) - 12

        parts.append(
            f'<text x="{label_x:.1f}" y="{label_y:.1f}" '
            f'fill="{_HIGHLIGHT_COLOUR}" font-size="11px" font-family="monospace" '
            f'text-anchor="middle" font-weight="bold">{_esc(net_name)}</text>\n'
        )

        # Stats
        total_len = sum((t.length_mm or t.calc_length()) for t in connected_traces)
        info = (
            f"Traces: {len(connected_traces)}  "
            f"Vias: {len(connected_vias)}  "
            f"Length: {total_len:.1f} mm"
        )
        parts.append(
            f'<text x="{self.width_px - 10:.0f}" y="16" '
            f'fill="{_DIM_COLOUR}" font-size="10px" font-family="monospace" '
            f'text-anchor="end">{_esc(info)}</text>\n'
        )

        parts.append(self._draw_dimensions())
        parts.append(self._draw_title_block(f"Net: {net_name}"))
        parts.append(self._svg_footer())
        return "".join(parts)

    def render_layer(self, layer_name: str) -> str:
        """Render features on a specific copper layer.

        Returns SVG string.
        """
        parts: list[str] = [self._svg_header(f"Layer: {layer_name}")]
        parts.append(self._draw_board_outline())
        parts.append(self._draw_zones(layer_filter=layer_name))
        parts.append(self._draw_copper_pours(layer_filter=layer_name))

        colour = _LAYER_COLOURS.get(layer_name, _TRACE_COLOUR)
        parts.append(self._draw_traces(layer_filter=layer_name, colour=colour))
        parts.append(self._draw_vias())
        parts.append(self._draw_components(layer_filter=layer_name))
        parts.append(self._draw_dimensions())
        parts.append(self._draw_title_block(f"Layer: {layer_name}"))
        parts.append(self._svg_footer())
        return "".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _estimate_package_size(footprint: str) -> tuple[float, float]:
    """Rough size estimate from footprint/package name. Returns (w_mm, h_mm)."""
    fp = (footprint or "").upper()

    # Common SMD sizes
    if "0201" in fp:
        return (0.6, 0.3)
    if "0402" in fp:
        return (1.0, 0.5)
    if "0603" in fp:
        return (1.6, 0.8)
    if "0805" in fp:
        return (2.0, 1.25)
    if "1206" in fp:
        return (3.2, 1.6)
    if "1210" in fp:
        return (3.2, 2.5)
    if "2512" in fp:
        return (6.3, 3.2)

    # QFP / LQFP
    if "QFP" in fp:
        if "48" in fp:
            return (7.0, 7.0)
        if "100" in fp or "144" in fp:
            return (14.0, 14.0)
        return (10.0, 10.0)

    # BGA
    if "BGA" in fp:
        return (12.0, 12.0)

    # QFN / DFN
    if "QFN" in fp or "DFN" in fp:
        return (5.0, 5.0)

    # SOP / SOIC / SSOP / TSSOP
    if "TSSOP" in fp or "SSOP" in fp:
        return (5.0, 3.0)
    if "SOIC" in fp or "SOP" in fp:
        return (5.0, 4.0)

    # SOT
    if "SOT-23" in fp or "SOT23" in fp:
        return (2.9, 1.3)
    if "SOT" in fp:
        return (3.0, 1.5)

    # Through-hole DIP
    if "DIP" in fp:
        return (8.0, 20.0)

    # Connectors
    if "CONN" in fp or "HDR" in fp or "PIN" in fp:
        return (8.0, 3.0)

    # Default
    return (3.0, 2.0)

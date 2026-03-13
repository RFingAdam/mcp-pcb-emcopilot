"""SVG annotation overlay generator.

Creates annotation overlays (arrows, text callouts, highlight regions,
warning markers) that can be used standalone or combined with a board render.

Pure Python, no external dependencies.
"""

from __future__ import annotations

import math
from typing import Any, Optional
from xml.sax.saxutils import escape

from ..models.pcb_data import PCBDesignData

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_COLOUR = "#FF4136"
_ARROW_COLOUR = "#FF4136"
_TEXT_COLOUR = "#FFFFFF"
_HIGHLIGHT_FILL = "rgba(255,65,54,0.2)"
_WARNING_COLOUR = "#FFD700"
_ERROR_COLOUR = "#FF4136"
_INFO_COLOUR = "#0074D9"

_BG = "none"   # overlay is transparent by default


def _esc(text: str) -> str:
    return escape(str(text))


# ---------------------------------------------------------------------------
# Annotator
# ---------------------------------------------------------------------------

class Annotator:
    """Generate SVG annotation overlays for PCB boards.

    Can render standalone or compose with a BoardRenderer SVG.
    """

    def __init__(self, design: PCBDesignData, width_px: int = 800):
        self.design = design
        self.width_px = width_px

        bw = design.board_width_mm or 100.0
        bh = design.board_height_mm or 100.0
        self.board_w = max(bw, 1.0)
        self.board_h = max(bh, 1.0)

        self.margin = max(self.board_w, self.board_h) * 0.12
        total_w = self.board_w + 2 * self.margin
        self.scale = self.width_px / total_w
        self.height_px = int((self.board_h + 2 * self.margin) * self.scale)

    def _x(self, mm: float) -> float:
        return (mm + self.margin) * self.scale

    def _y(self, mm: float) -> float:
        return (self.board_h - mm + self.margin) * self.scale

    def _sx(self, mm: float) -> float:
        return mm * self.scale

    # ----- annotation primitives -----

    def _render_arrow(self, ann: dict) -> str:
        """Arrow pointing at (x, y) from a direction, with optional text."""
        x_mm = ann["x"]
        y_mm = ann["y"]
        colour = ann.get("color", ann.get("colour", _ARROW_COLOUR))
        text = ann.get("text", "")
        length = ann.get("length", 8.0)  # arrow length in mm

        tx = self._x(x_mm)
        ty = self._y(y_mm)

        # Arrow points toward the target from above-right
        angle = ann.get("angle", -45)
        rad = math.radians(angle)
        arrow_len = self._sx(length)
        sx = tx + arrow_len * math.cos(rad)
        sy = ty + arrow_len * math.sin(rad)

        # Arrowhead
        head_len = 8
        head_angle = 0.4  # ~23 degrees
        ha1 = rad + math.pi - head_angle
        ha2 = rad + math.pi + head_angle
        hx1 = tx + head_len * math.cos(ha1)
        hy1 = ty + head_len * math.sin(ha1)
        hx2 = tx + head_len * math.cos(ha2)
        hy2 = ty + head_len * math.sin(ha2)

        parts = [
            f'<line x1="{sx:.1f}" y1="{sy:.1f}" '
            f'x2="{tx:.1f}" y2="{ty:.1f}" '
            f'stroke="{colour}" stroke-width="2"/>\n',
            f'<polygon points="{tx:.1f},{ty:.1f} {hx1:.1f},{hy1:.1f} {hx2:.1f},{hy2:.1f}" '
            f'fill="{colour}"/>\n',
        ]

        if text:
            # Place label at the tail of the arrow
            text_x = sx + 4 * math.cos(rad)
            text_y = sy + 4 * math.sin(rad)
            anchor = "start" if math.cos(rad) >= 0 else "end"
            parts.append(
                f'<text x="{text_x:.1f}" y="{text_y:.1f}" '
                f'fill="{colour}" font-size="11px" font-family="monospace" '
                f'text-anchor="{anchor}" font-weight="bold">{_esc(text)}</text>\n'
            )

        return "".join(parts)

    def _render_text(self, ann: dict) -> str:
        """Text callout with optional leader line."""
        x_mm = ann["x"]
        y_mm = ann["y"]
        text = ann.get("text", "")
        colour = ann.get("color", ann.get("colour", _TEXT_COLOUR))
        font_size = ann.get("font_size", 11)

        tx = self._x(x_mm)
        ty = self._y(y_mm)

        parts: list[str] = []

        # Background pill for readability
        text_w = len(text) * font_size * 0.62
        text_h = font_size + 6
        parts.append(
            f'<rect x="{tx - 4:.1f}" y="{ty - text_h + 2:.1f}" '
            f'width="{text_w + 8:.1f}" height="{text_h:.1f}" '
            f'rx="3" fill="#000" fill-opacity="0.7"/>\n'
        )
        parts.append(
            f'<text x="{tx:.1f}" y="{ty:.1f}" fill="{colour}" '
            f'font-size="{font_size}px" font-family="monospace">'
            f'{_esc(text)}</text>\n'
        )

        # Optional leader line to a target
        target_x = ann.get("target_x")
        target_y = ann.get("target_y")
        if target_x is not None and target_y is not None:
            ttx = self._x(target_x)
            tty = self._y(target_y)
            parts.append(
                f'<line x1="{tx:.1f}" y1="{ty:.1f}" '
                f'x2="{ttx:.1f}" y2="{tty:.1f}" '
                f'stroke="{colour}" stroke-width="1" '
                f'stroke-dasharray="3,2" opacity="0.7"/>\n'
                f'<circle cx="{ttx:.1f}" cy="{tty:.1f}" r="3" '
                f'fill="{colour}" opacity="0.7"/>\n'
            )

        return "".join(parts)

    def _render_highlight(self, ann: dict) -> str:
        """Highlight region — rectangle or circle."""
        x_mm = ann["x"]
        y_mm = ann["y"]
        colour = ann.get("color", ann.get("colour", _DEFAULT_COLOUR))
        shape = ann.get("shape", "rect")
        w_mm = ann.get("width", 5.0)
        h_mm = ann.get("height", 5.0)
        r_mm = ann.get("radius", 3.0)

        if shape == "circle":
            cx = self._x(x_mm)
            cy = self._y(y_mm)
            r = self._sx(r_mm)
            return (
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
                f'fill="{colour}" fill-opacity="0.2" '
                f'stroke="{colour}" stroke-width="2" stroke-dasharray="4,2"/>\n'
            )
        else:
            rx = self._x(x_mm - w_mm / 2)
            ry = self._y(y_mm + h_mm / 2)
            w = self._sx(w_mm)
            h = self._sx(h_mm)
            return (
                f'<rect x="{rx:.1f}" y="{ry:.1f}" '
                f'width="{w:.1f}" height="{h:.1f}" '
                f'fill="{colour}" fill-opacity="0.15" '
                f'stroke="{colour}" stroke-width="2" stroke-dasharray="4,2" rx="2"/>\n'
            )

    def _render_warning(self, ann: dict) -> str:
        """Warning/error marker (triangle with !)."""
        x_mm = ann["x"]
        y_mm = ann["y"]
        text = ann.get("text", "")
        severity = ann.get("severity", "warning")
        colour = _WARNING_COLOUR if severity == "warning" else _ERROR_COLOUR

        cx = self._x(x_mm)
        cy = self._y(y_mm)

        # Triangle
        s = 10  # half-size in px
        pts = (
            f"{cx:.1f},{cy - s:.1f} "
            f"{cx - s * 0.87:.1f},{cy + s * 0.5:.1f} "
            f"{cx + s * 0.87:.1f},{cy + s * 0.5:.1f}"
        )
        parts = [
            f'<polygon points="{pts}" fill="{colour}" '
            f'stroke="#000" stroke-width="1"/>\n',
            f'<text x="{cx:.1f}" y="{cy + 2:.1f}" '
            f'fill="#000" font-size="13px" font-weight="bold" '
            f'font-family="sans-serif" text-anchor="middle" '
            f'dominant-baseline="central">!</text>\n',
        ]

        if text:
            parts.append(
                f'<text x="{cx + s + 4:.1f}" y="{cy + 3:.1f}" '
                f'fill="{colour}" font-size="10px" font-family="monospace" '
                f'font-weight="bold">{_esc(text)}</text>\n'
            )

        return "".join(parts)

    # ----- public API -----

    def render_annotations(self, annotations: list[dict]) -> str:
        """Render a list of annotations as an SVG overlay.

        Each annotation is a dict with at least ``type``, ``x``, ``y``.
        Supported types: ``arrow``, ``text``, ``highlight``, ``warning``.

        Returns SVG string (transparent background, same coordinate space
        as BoardRenderer).
        """
        parts: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{self.width_px}" height="{self.height_px}" '
            f'viewBox="0 0 {self.width_px} {self.height_px}">\n'
            f'<title>Annotations</title>\n'
        ]

        for ann in annotations:
            ann_type = ann.get("type", "")
            if ann_type == "arrow":
                parts.append(self._render_arrow(ann))
            elif ann_type == "text":
                parts.append(self._render_text(ann))
            elif ann_type == "highlight":
                parts.append(self._render_highlight(ann))
            elif ann_type == "warning":
                parts.append(self._render_warning(ann))
            # Unknown types are silently skipped

        parts.append('</svg>\n')
        return "".join(parts)

    def render_annotated_board(
        self,
        annotations: list[dict],
        layers: Optional[list[str]] = None,
        highlight_nets: Optional[list[str]] = None,
        highlight_components: Optional[list[str]] = None,
    ) -> str:
        """Render a board view with annotations composited on top.

        Convenience method that generates the board SVG and embeds
        the annotation overlay inside the same SVG document.

        Returns single SVG string.
        """
        from .board_renderer import BoardRenderer

        renderer = BoardRenderer(self.design, self.width_px)
        board_svg = renderer.render_board(
            layers=layers,
            highlight_nets=highlight_nets,
            highlight_components=highlight_components,
        )

        # Strip trailing </svg> from board, append annotations, re-close
        board_svg = board_svg.rstrip()
        if board_svg.endswith("</svg>"):
            board_svg = board_svg[:-len("</svg>")]

        # Render annotation group (without outer <svg> wrapper)
        ann_group = ['<g id="annotations">\n']
        for ann in annotations:
            ann_type = ann.get("type", "")
            if ann_type == "arrow":
                ann_group.append(self._render_arrow(ann))
            elif ann_type == "text":
                ann_group.append(self._render_text(ann))
            elif ann_type == "highlight":
                ann_group.append(self._render_highlight(ann))
            elif ann_type == "warning":
                ann_group.append(self._render_warning(ann))
        ann_group.append('</g>\n')

        return board_svg + "\n" + "".join(ann_group) + "</svg>\n"

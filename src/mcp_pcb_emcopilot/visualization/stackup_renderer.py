"""SVG stackup cross-section renderer.

Generates a side-view cross-section of the PCB layer stackup showing
copper layers, dielectrics, solder mask, with thickness dimensions
and signal/ground/power designations.

Pure Python, no external dependencies.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from ..models.pcb_data import PCBDesignData, PCBLayer

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

_COLOURS = {
    "signal": "#D4A017",      # copper — gold
    "plane": "#CC8400",       # copper plane — darker gold
    "mixed": "#DAA520",       # mixed — goldenrod
    "dielectric": "#2E7D32",  # prepreg / core — green
    "solder_mask": "#1B5E20", # solder mask — dark green
    "silk": "#FAFAFA",        # silkscreen — white
}

_BG = "#F5F5F0"
_LABEL_COLOUR = "#333333"
_DIM_COLOUR = "#777777"
_BORDER_COLOUR = "#999999"

_DESIGNATION_BADGE = {
    "signal": ("#E8D44D", "#333"),
    "plane": ("#90CAF9", "#333"),
    "mixed": ("#CE93D8", "#333"),
    "dielectric": ("#A5D6A7", "#333"),
    "solder_mask": ("#66BB6A", "#FFF"),
}


def _esc(text: str) -> str:
    return escape(str(text))


def _layer_colour(layer_type: str) -> str:
    return _COLOURS.get(layer_type, _COLOURS["dielectric"])


# ---------------------------------------------------------------------------
# StackupRenderer
# ---------------------------------------------------------------------------

class StackupRenderer:
    """Render a PCB stackup cross-section as SVG."""

    def __init__(self, design: PCBDesignData, width_px: int = 700):
        self.design = design
        self.width_px = width_px

    def render(self) -> str:
        """Render stackup cross-section.  Returns SVG string."""
        layers = self.design.layers
        if not layers:
            layers = self._synthesize_layers()

        # Layout parameters
        left_margin = 160    # space for labels
        right_margin = 120   # space for dims
        badge_margin = 90    # space for type badge
        bar_width = self.width_px - left_margin - right_margin - badge_margin
        top_margin = 50
        bottom_margin = 40

        # Minimum visual height per layer so thin layers remain visible
        min_layer_h = 14
        # Scale thickness so total fits nicely
        total_thickness = sum(l.thickness_mm for l in layers) or 1.0
        target_h = max(300, 40 * len(layers))
        px_per_mm = target_h / total_thickness

        # Compute row heights (enforce minimum)
        row_heights: list[float] = []
        for ly in layers:
            h = max(min_layer_h, ly.thickness_mm * px_per_mm)
            row_heights.append(h)

        total_h = sum(row_heights)
        svg_h = int(total_h + top_margin + bottom_margin)

        parts: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{self.width_px}" height="{svg_h}" '
            f'viewBox="0 0 {self.width_px} {svg_h}" '
            f'style="background:{_BG}">\n'
            f'<title>PCB Stackup Cross-Section</title>\n'
            f'<defs><style>\n'
            f'  text {{ font-family: "Segoe UI", Arial, sans-serif; }}\n'
            f'  .layer-label {{ font-size: 12px; fill: {_LABEL_COLOUR}; font-weight: 600; }}\n'
            f'  .dim {{ font-size: 10px; fill: {_DIM_COLOUR}; }}\n'
            f'  .title {{ font-size: 15px; fill: {_LABEL_COLOUR}; font-weight: bold; }}\n'
            f'  .badge {{ font-size: 9px; font-weight: 600; }}\n'
            f'  .material {{ font-size: 9px; fill: {_DIM_COLOUR}; }}\n'
            f'</style></defs>\n'
        ]

        # Title
        parts.append(
            f'<text x="{self.width_px / 2:.0f}" y="28" class="title" '
            f'text-anchor="middle">Layer Stackup '
            f'({self.design.layer_count}L, '
            f'{self.design.board_thickness_mm:.2f} mm)</text>\n'
        )

        y = top_margin
        for i, ly in enumerate(layers):
            h = row_heights[i]
            fill = _layer_colour(ly.layer_type)
            bx = left_margin

            # Layer band
            parts.append(
                f'<rect x="{bx}" y="{y:.1f}" width="{bar_width}" height="{h:.1f}" '
                f'fill="{fill}" stroke="{_BORDER_COLOUR}" stroke-width="0.5"/>\n'
            )

            # Hatching for copper layers
            if ly.layer_type in ("signal", "plane", "mixed"):
                parts.append(self._copper_hatching(bx, y, bar_width, h))

            # Label (left)
            label_y = y + h / 2 + 4
            parts.append(
                f'<text x="{bx - 8:.0f}" y="{label_y:.1f}" '
                f'class="layer-label" text-anchor="end">{_esc(ly.name)}</text>\n'
            )

            # Material (below label, smaller)
            if ly.material:
                parts.append(
                    f'<text x="{bx - 8:.0f}" y="{label_y + 12:.1f}" '
                    f'class="material" text-anchor="end">{_esc(ly.material)}</text>\n'
                )

            # Dielectric constant (inside bar, for dielectric layers)
            if ly.layer_type in ("dielectric",) and ly.dielectric_constant:
                parts.append(
                    f'<text x="{bx + bar_width / 2:.0f}" y="{label_y:.1f}" '
                    f'font-size="9px" fill="white" text-anchor="middle" '
                    f'opacity="0.8">Er={ly.dielectric_constant:.1f}</text>\n'
                )

            # Copper weight (inside bar)
            if ly.copper_weight_oz and ly.layer_type in ("signal", "plane", "mixed"):
                parts.append(
                    f'<text x="{bx + bar_width / 2:.0f}" y="{label_y:.1f}" '
                    f'font-size="9px" fill="#333" text-anchor="middle" '
                    f'opacity="0.9">{ly.copper_weight_oz:.0f} oz</text>\n'
                )

            # Thickness dimension (right side)
            dim_x = bx + bar_width + 10
            if ly.thickness_mm > 0:
                parts.append(
                    f'<text x="{dim_x:.0f}" y="{label_y:.1f}" '
                    f'class="dim">{ly.thickness_mm:.3f} mm</text>\n'
                )
                # Dimension lines
                parts.append(
                    f'<line x1="{dim_x + 60:.0f}" y1="{y:.1f}" '
                    f'x2="{dim_x + 60:.0f}" y2="{y + h:.1f}" '
                    f'stroke="{_DIM_COLOUR}" stroke-width="0.5"/>\n'
                    f'<line x1="{dim_x + 56:.0f}" y1="{y:.1f}" '
                    f'x2="{dim_x + 64:.0f}" y2="{y:.1f}" '
                    f'stroke="{_DIM_COLOUR}" stroke-width="0.5"/>\n'
                    f'<line x1="{dim_x + 56:.0f}" y1="{y + h:.1f}" '
                    f'x2="{dim_x + 64:.0f}" y2="{y + h:.1f}" '
                    f'stroke="{_DIM_COLOUR}" stroke-width="0.5"/>\n'
                )

            # Type badge (far right)
            badge_x = bx + bar_width + right_margin + 5
            bg, fg = _DESIGNATION_BADGE.get(ly.layer_type, ("#DDD", "#333"))
            badge_label = ly.layer_type.upper()
            parts.append(
                f'<rect x="{badge_x:.0f}" y="{y + h / 2 - 8:.1f}" '
                f'width="70" height="16" rx="3" fill="{bg}"/>\n'
                f'<text x="{badge_x + 35:.0f}" y="{y + h / 2 + 4:.1f}" '
                f'class="badge" fill="{fg}" text-anchor="middle">{badge_label}</text>\n'
            )

            y += h  # type: ignore[assignment]

        # Total thickness annotation
        parts.append(
            f'<text x="{self.width_px / 2:.0f}" y="{svg_h - 12:.0f}" '
            f'class="dim" text-anchor="middle">'
            f'Total board thickness: {self.design.board_thickness_mm:.2f} mm</text>\n'
        )

        parts.append('</svg>\n')
        return "".join(parts)

    # ----- helpers -----

    @staticmethod
    def _copper_hatching(x: float, y: float, w: float, h: float) -> str:
        """Add diagonal hatching lines to indicate copper."""
        lines: list[str] = [
            f'<clipPath id="clip_{x:.0f}_{y:.0f}">'
            f'<rect x="{x}" y="{y:.1f}" width="{w}" height="{h:.1f}"/>'
            f'</clipPath>\n'
            f'<g clip-path="url(#clip_{x:.0f}_{y:.0f})" '
            f'stroke="#00000020" stroke-width="0.5">\n'
        ]
        step = 6
        total = w + h
        pos = 0.0
        while pos < total:
            x1 = x + pos
            y1 = y
            x2 = x + pos - h
            y2 = y + h
            lines.append(
                f'<line x1="{x1:.1f}" y1="{y1:.1f}" '
                f'x2="{x2:.1f}" y2="{y2:.1f}"/>\n'
            )
            pos += step
        lines.append('</g>\n')
        return "".join(lines)

    def _synthesize_layers(self) -> list[PCBLayer]:
        """Create a basic stackup when no layer data exists."""
        lc = max(self.design.layer_count, 2)
        thickness = self.design.board_thickness_mm or 1.6
        copper_t = 0.035
        # Distribute dielectric evenly between copper layers
        n_diel = lc - 1 if lc > 1 else 1
        diel_t = (thickness - lc * copper_t) / n_diel
        if diel_t < 0.05:
            diel_t = 0.2

        result: list[PCBLayer] = []
        num = 0

        # Top solder mask
        result.append(PCBLayer(name="Top Solder Mask", number=num, layer_type="solder_mask", thickness_mm=0.025))
        num += 1

        for i in range(lc):
            layer_name = "F.Cu" if i == 0 else ("B.Cu" if i == lc - 1 else f"In{i}.Cu")
            layer_type = "signal" if (i == 0 or i == lc - 1) else "plane"
            result.append(PCBLayer(name=layer_name, number=num, layer_type=layer_type, thickness_mm=copper_t, copper_weight_oz=1.0))
            num += 1

            if i < lc - 1:
                diel_name = "Core" if i == lc // 2 - 1 else f"Prepreg{i + 1}"
                result.append(PCBLayer(name=diel_name, number=num, layer_type="dielectric", thickness_mm=round(diel_t, 3), dielectric_constant=4.3, material="FR-4"))
                num += 1

        # Bottom solder mask
        result.append(PCBLayer(name="Bottom Solder Mask", number=num, layer_type="solder_mask", thickness_mm=0.025))

        return result

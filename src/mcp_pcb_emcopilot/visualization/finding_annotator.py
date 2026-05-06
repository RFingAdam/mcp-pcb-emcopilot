"""
Finding Annotator — renders SVG board view with review findings overlaid.

Draws the board outline, all traces as thin gray lines, then overlays
flagged traces in colour by severity with marker circles at finding
locations. Includes a legend.

Pure Python, no external dependencies (SVG is XML text).
"""
from __future__ import annotations

from typing import Any, List
from xml.sax.saxutils import escape

from ..models.pcb_data import PCBDesignData

# ---------------------------------------------------------------------------
# Colours by severity
# ---------------------------------------------------------------------------

_SEVERITY_COLOURS = {
    "critical": "#ff0000",
    "high": "#ff0000",
    "warning": "#ff8c00",
    "medium": "#ff8c00",
    "info": "#4169e1",
    "low": "#4169e1",
}

_BG_COLOUR = "#1a1a2e"
_BOARD_FILL = "#222240"
_BOARD_STROKE = "#e0e0e0"
_TRACE_COLOUR = "#555555"
_TEXT_COLOUR = "#e0e0e0"
_COMPONENT_FILL = "#333355"
_COMPONENT_STROKE = "#666688"

_MARKER_RADIUS_MM = 1.5  # marker circle radius in board-mm


def _esc(text: str) -> str:
    return escape(str(text))


class FindingAnnotator:
    """Render an SVG board view annotated with design review findings.

    Usage::

        annotator = FindingAnnotator()
        svg_str = annotator.annotate_board_svg(design, review_result)
    """

    def annotate_board_svg(
        self,
        design: PCBDesignData,
        review_result: Any,
        width_px: int = 900,
    ) -> str:
        """Generate annotated SVG from a design and its review result.

        Parameters
        ----------
        design : PCBDesignData
            Parsed PCB design.
        review_result : object
            A ReviewResult (or similar) with ``domain_results`` containing
            findings that have ``severity``, ``location_x_mm``, ``location_y_mm``,
            and optionally ``signal_name``, ``location_layer``.
        width_px : int
            Desired SVG width in pixels.

        Returns
        -------
        str
            Complete SVG document as a string, viewable in any browser.
        """
        # Board dimensions
        bw = max(getattr(design, "board_width_mm", 0) or 100.0, 1.0)
        bh = max(getattr(design, "board_height_mm", 0) or 100.0, 1.0)

        margin_mm = max(bw, bh) * 0.12
        total_w_mm = bw + 2 * margin_mm
        total_h_mm = bh + 2 * margin_mm
        scale = width_px / total_w_mm
        height_px = int(total_h_mm * scale)

        # Coordinate helpers (flip Y for PCB convention)
        def sx(mm: float) -> float:
            return (mm + margin_mm) * scale

        def sy(mm: float) -> float:
            return (bh - mm + margin_mm) * scale

        def sd(mm: float) -> float:
            return mm * scale

        # Collect findings from review result
        findings = self._collect_findings(review_result)

        # Build set of flagged net names
        flagged_nets = self._flagged_net_names(findings)

        # Build set of flagged component refs
        flagged_components = self._flagged_component_refs(findings)

        parts: list[str] = []

        # SVG header
        parts.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width_px}" height="{height_px}" '
            f'viewBox="0 0 {width_px} {height_px}" '
            f'style="background:{_BG_COLOUR}">\n'
            f'<title>PCB Design Review Findings</title>\n'
            f'<defs><style>\n'
            f'  text {{ font-family: monospace; fill: {_TEXT_COLOUR}; }}\n'
            f'  .legend-text {{ font-size: 11px; }}\n'
            f'  .marker-label {{ font-size: 8px; fill: white; text-anchor: middle; }}\n'
            f'</style></defs>\n'
        )

        # Board outline
        parts.append(
            f'<rect x="{sx(0):.1f}" y="{sy(bh):.1f}" '
            f'width="{sd(bw):.1f}" height="{sd(bh):.1f}" '
            f'fill="{_BOARD_FILL}" stroke="{_BOARD_STROKE}" stroke-width="1.5" '
            f'rx="2"/>\n'
        )

        # Background traces (all traces as thin grey lines)
        parts.append('<!-- Background traces -->\n')
        for trace in getattr(design, "traces", []):
            x1 = sx(trace.x1_mm)
            y1 = sy(trace.y1_mm)
            x2 = sx(trace.x2_mm)
            y2 = sy(trace.y2_mm)
            parts.append(
                f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="{_TRACE_COLOUR}" stroke-width="0.5" stroke-linecap="round"/>\n'
            )

        # Components with findings get highlighted outlines
        parts.append('<!-- Components -->\n')
        for comp in getattr(design, "components", []):
            ref = getattr(comp, "reference", "")
            cx = getattr(comp, "x_mm", 0)
            cy = getattr(comp, "y_mm", 0)
            # Estimate component bounding box from footprint or default
            comp_w = 2.0
            comp_h = 1.5
            fp = getattr(comp, "footprint", "") or ""
            if "QFP" in fp.upper() or "BGA" in fp.upper():
                comp_w = comp_h = 5.0
            elif "SOT" in fp.upper():
                comp_w, comp_h = 2.0, 1.2

            is_flagged = ref in flagged_components
            stroke = _SEVERITY_COLOURS.get("warning", _COMPONENT_STROKE) if is_flagged else _COMPONENT_STROKE
            stroke_w = "2" if is_flagged else "0.5"
            fill = _COMPONENT_FILL

            parts.append(
                f'<rect x="{sx(cx) - sd(comp_w / 2):.1f}" '
                f'y="{sy(cy) - sd(comp_h / 2):.1f}" '
                f'width="{sd(comp_w):.1f}" height="{sd(comp_h):.1f}" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_w}" '
                f'rx="1" opacity="0.7"/>\n'
            )

        # Overlay flagged traces in colour
        parts.append('<!-- Flagged traces -->\n')
        for trace in getattr(design, "traces", []):
            net_name = getattr(trace, "net_name", None)
            if net_name and net_name in flagged_nets:
                severity = flagged_nets[net_name]
                colour = _SEVERITY_COLOURS.get(severity, _TRACE_COLOUR)
                x1 = sx(trace.x1_mm)
                y1 = sy(trace.y1_mm)
                x2 = sx(trace.x2_mm)
                y2 = sy(trace.y2_mm)
                w = max(sd(getattr(trace, "width_mm", 0.15)), 1.5)
                parts.append(
                    f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                    f'stroke="{colour}" stroke-width="{w:.1f}" stroke-linecap="round" '
                    f'opacity="0.8"/>\n'
                )

        # Finding markers (circles at finding locations)
        parts.append('<!-- Finding markers -->\n')
        marker_r = sd(_MARKER_RADIUS_MM)
        for idx, f in enumerate(findings):
            loc_x = f.get("location_x_mm")
            loc_y = f.get("location_y_mm")
            if loc_x is None or loc_y is None:
                continue
            severity = f.get("severity", "info")
            colour = _SEVERITY_COLOURS.get(severity, _SEVERITY_COLOURS["info"])
            cx = sx(loc_x)
            cy = sy(loc_y)
            parts.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{marker_r:.1f}" '
                f'fill="none" stroke="{colour}" stroke-width="2" opacity="0.9"/>\n'
            )
            # Small index label inside the marker
            parts.append(
                f'<text x="{cx:.1f}" y="{cy + 3:.1f}" class="marker-label">{idx + 1}</text>\n'
            )

        # Legend
        parts.append(self._render_legend(width_px, height_px, findings))

        # Footer
        parts.append('</svg>\n')
        return "".join(parts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_findings(review_result: Any) -> List[dict]:
        """Extract findings from a ReviewResult or similar structure."""
        findings: List[dict] = []
        domain_results = getattr(review_result, "domain_results", [])
        for dr in domain_results:
            for f in getattr(dr, "findings", []):
                entry: dict = {}
                if hasattr(f, "to_dict"):
                    entry = f.to_dict()
                else:
                    for attr in ("severity", "title", "description", "signal_name",
                                 "location_x_mm", "location_y_mm", "location_layer",
                                 "domain"):
                        val = getattr(f, attr, None)
                        if val is not None:
                            entry[attr] = val
                if entry.get("severity") not in ("accepted",):
                    findings.append(entry)
        return findings

    @staticmethod
    def _flagged_net_names(findings: List[dict]) -> dict[str, str]:
        """Map net names to worst severity from findings."""
        severity_rank = {"critical": 0, "high": 0, "warning": 1, "medium": 1, "info": 2, "low": 2}
        net_sev: dict[str, str] = {}
        for f in findings:
            net = f.get("signal_name")
            if not net:
                continue
            sev = f.get("severity", "info")
            existing = net_sev.get(net)
            if existing is None or severity_rank.get(sev, 9) < severity_rank.get(existing, 9):
                net_sev[net] = sev
        return net_sev

    @staticmethod
    def _flagged_component_refs(findings: List[dict]) -> set[str]:
        """Extract component references mentioned in findings."""
        refs: set[str] = set()
        for f in findings:
            desc = f.get("description", "")
            title = f.get("title", "")
            # Look for component references like U1, C10, R3 in text
            for token in (title + " " + desc).split():
                token = token.strip("(),.:;'\"")
                if len(token) >= 2 and token[0].isalpha() and any(c.isdigit() for c in token[1:]):
                    refs.add(token)
        return refs

    @staticmethod
    def _render_legend(width_px: int, height_px: int, findings: List[dict]) -> str:
        """Render severity legend in top-right corner."""
        legend_items = [
            ("Critical", _SEVERITY_COLOURS["critical"]),
            ("Warning", _SEVERITY_COLOURS["warning"]),
            ("Info", _SEVERITY_COLOURS["info"]),
        ]
        x_start = width_px - 120
        y_start = 15
        parts: list[str] = []
        parts.append(
            f'<rect x="{x_start - 10}" y="{y_start - 10}" '
            f'width="120" height="{len(legend_items) * 20 + 15}" '
            f'fill="rgba(0,0,0,0.6)" rx="4"/>\n'
        )
        for i, (label, colour) in enumerate(legend_items):
            y = y_start + i * 20
            parts.append(
                f'<circle cx="{x_start + 5}" cy="{y + 5}" r="5" '
                f'fill="{colour}" opacity="0.9"/>\n'
            )
            parts.append(
                f'<text x="{x_start + 18}" y="{y + 9}" class="legend-text">'
                f'{_esc(label)}</text>\n'
            )
        # Finding count
        count = len(findings)
        parts.append(
            f'<text x="{x_start}" y="{y_start + len(legend_items) * 20 + 2}" '
            f'class="legend-text" fill="#aaa">{count} finding{"s" if count != 1 else ""}</text>\n'
        )
        return "".join(parts)

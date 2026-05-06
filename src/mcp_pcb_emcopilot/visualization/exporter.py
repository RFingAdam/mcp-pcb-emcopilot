"""SVG-to-PNG exporter for PCB visualization renders.

Converts SVG output from BoardRenderer, StackupRenderer, Annotator,
and net renders into rasterized PNG files suitable for embedding in
DOCX/PDF reports.

Optional dependency: cairosvg (pip install cairosvg).
Falls back to writing raw SVG if cairosvg is not available.
"""

from __future__ import annotations

import os
import tempfile
from typing import Optional


def svg_to_png(
    svg_content: str,
    output_path: Optional[str] = None,
    width: int = 1600,
    background_color: Optional[str] = None,
) -> str:
    """Convert SVG string to PNG file.

    Args:
        svg_content: SVG markup string.
        output_path: Destination PNG path.  If None a temp file is created.
        width: Output image width in pixels (height scales proportionally).
        background_color: Optional CSS background colour (e.g. '#FFFFFF').

    Returns:
        Absolute path to the written PNG file.

    Raises:
        ImportError: If cairosvg is not installed.
    """
    try:
        import cairosvg
    except ImportError as e:
        raise ImportError(
            "cairosvg is required for PNG export. "
            "Install with: pip install cairosvg"
        ) from e

    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".png", prefix="pcb_render_")
        os.close(fd)

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    cairosvg.svg2png(
        bytestring=svg_content.encode("utf-8"),
        write_to=output_path,
        output_width=width,
        background_color=background_color,
    )

    return os.path.abspath(output_path)


def svg_to_file(
    svg_content: str,
    output_path: Optional[str] = None,
) -> str:
    """Write SVG string to a file.

    Args:
        svg_content: SVG markup string.
        output_path: Destination SVG path.  If None a temp file is created.

    Returns:
        Absolute path to the written SVG file.
    """
    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".svg", prefix="pcb_render_")
        os.close(fd)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg_content)

    return os.path.abspath(output_path)


def batch_export(
    renders: dict[str, str],
    output_dir: str,
    fmt: str = "png",
    width: int = 1600,
) -> dict[str, str]:
    """Export multiple named SVG renders to files.

    Args:
        renders: Mapping of label -> SVG content string.
        output_dir: Directory for output files.
        fmt: Output format — 'png' or 'svg'.
        width: PNG width in pixels (ignored for SVG).

    Returns:
        Mapping of label -> absolute output path.
    """
    os.makedirs(output_dir, exist_ok=True)
    results = {}

    for label, svg in renders.items():
        safe_label = "".join(c if c.isalnum() or c in "_-" else "_" for c in label)
        out_path = os.path.join(output_dir, f"{safe_label}.{fmt}")

        if fmt == "png":
            results[label] = svg_to_png(svg, out_path, width=width)
        else:
            results[label] = svg_to_file(svg, out_path)

    return results

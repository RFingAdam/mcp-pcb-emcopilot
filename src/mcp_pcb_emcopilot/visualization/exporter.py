"""SVG-to-PNG exporter for PCB visualization renders.

Converts SVG output from BoardRenderer, StackupRenderer, Annotator,
and net renders into rasterized PNG files suitable for embedding in
DOCX/PDF reports.

Optional dependency: cairosvg (pip install cairosvg), which additionally needs
the native Cairo library present at import time.

PNG export raises :class:`MissingDependencyError` when cairosvg is unusable —
it does *not* silently fall back to writing SVG bytes, because a file named
``.png`` containing SVG is worse than an explicit failure. Callers that want a
fallback should test :func:`png_export_available` and use :func:`svg_to_file`.
"""

from __future__ import annotations

import os
import tempfile
from typing import Optional

from ..errors import MissingDependencyError

# cairosvg is installable but unusable without native Cairo (the common case on
# Windows), where ``import cairosvg`` raises OSError from cairocffi's dlopen
# rather than ImportError.
_CAIRO_IMPORT_ERRORS = (ImportError, OSError)


def png_export_available() -> bool:
    """Return True if PNG rasterisation can actually run.

    Checks that cairosvg *imports*, not merely that it is installed — the two
    differ whenever the native Cairo library is missing. Lets callers and tests
    branch without provoking an exception.
    """
    try:
        import cairosvg  # noqa: F401
    except _CAIRO_IMPORT_ERRORS:
        return False
    return True


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
        MissingDependencyError: If cairosvg is not installed, or is installed
            but cannot load the native Cairo library.
    """
    try:
        import cairosvg
    except _CAIRO_IMPORT_ERRORS as exc:
        raise MissingDependencyError(
            "MISSING_DEPENDENCY",
            "cairosvg is required for PNG export but is not usable: "
            f"{type(exc).__name__}: {exc}. Install with 'pip install cairosvg'; "
            "on Windows the native Cairo library is also required (an OSError "
            "here means cairosvg is installed but Cairo itself is missing). "
            "SVG output via svg_to_file() needs no extra dependency.",
            {"dependency": "cairosvg", "underlying_error": type(exc).__name__},
        ) from exc

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

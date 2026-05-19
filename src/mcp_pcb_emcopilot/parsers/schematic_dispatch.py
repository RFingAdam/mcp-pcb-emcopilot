"""Schematic format auto-dispatch.

One entry point — :func:`detect_format` — that maps a file path to the
appropriate parser based on extension plus magic-byte inspection for
the cases where extension alone isn't sufficient (PDFs vs Altium .SchDoc
which is OLE2 — different first bytes).

The downstream :func:`parse_schematic_auto` calls the correct concrete
parser and returns a uniform ``{components, nets, source_format}``
dict the MCP tool can spread onto a session.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Literal

SchematicFormat = Literal["kicad", "altium", "pdf", "netlist", "unknown"]

# Magic bytes for format-by-content disambiguation when extension is missing
# or wrong. We only need the first ~8 bytes to disambiguate.
_PDF_MAGIC = b"%PDF-"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # Altium .SchDoc compound docs
_KICAD_MAGIC = b"(kicad_sch"


def _read_head(path: Path, n: int = 16) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(n)
    except OSError:
        return b""


def detect_format(file_path: str) -> SchematicFormat:
    """Best-effort schematic format detection.

    Extension wins when it's one of the well-known schematic extensions.
    For ambiguous extensions (``.sch`` could be OrCAD or EAGLE; ``.bin``
    could be anything) we sniff magic bytes.
    """
    p = Path(file_path)
    ext = p.suffix.lower()
    if ext == ".kicad_sch":
        return "kicad"
    if ext in {".schdoc", ".schlib"}:
        return "altium"
    if ext == ".pdf":
        return "pdf"
    if ext == ".net":
        return "netlist"

    head = _read_head(p, 16)
    if head.startswith(_PDF_MAGIC):
        return "pdf"
    if head.startswith(_OLE_MAGIC):
        return "altium"
    if head.startswith(_KICAD_MAGIC):
        return "kicad"
    return "unknown"


def _is_image_only_pdf(file_path: str) -> bool:
    """Detect PDFs with no extractable text layer.

    The PDF schematic parser is text-only; image-only PDFs (typically
    photocopies/scans) yield zero components and zero nets, which is
    worse than refusing outright. We catch this case here so the MCP
    tool can return a clear remediation message.
    """
    try:
        import pdfplumber  # type: ignore[import-not-found]
    except ImportError:
        return False  # can't tell — be permissive
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages[:2]:  # first two pages are enough
                if page.extract_text() and page.extract_text().strip():
                    return False
        return True
    except Exception:
        return False


def parse_schematic_auto(file_path: str) -> dict[str, Any]:
    """Parse a schematic with format auto-detection.

    Returns a uniform dict::

        {
          "source_format": "kicad" | "altium" | "pdf" | "netlist",
          "components": [{...}, ...],  # always dicts
          "nets": [{...}, ...],
          "title": Optional[str],
          "warnings": list[str],
          "raw": <parser-specific result>,
        }

    Raises ``ValueError`` for unknown formats or image-only PDFs.
    """
    fmt = detect_format(file_path)
    if fmt == "unknown":
        raise ValueError(
            f"Could not detect a schematic format for {file_path!r}. "
            f"Supported: .kicad_sch, .SchDoc/.SchLib, .pdf, .net."
        )
    if fmt == "pdf" and _is_image_only_pdf(file_path):
        raise ValueError(
            f"PDF {file_path!r} appears to be image-only (no extractable text). "
            f"Re-export the schematic with a text layer enabled, or convert via OCR first."
        )

    if fmt == "pdf":
        from .pdf_schematic_parser import PDFSchematicParser
        parser = PDFSchematicParser()
        result = parser.parse(file_path)
        return {
            "source_format": "pdf",
            "components": list(result.components),
            "nets": list(result.nets),
            "title": getattr(result, "title", None),
            "warnings": list(getattr(result, "warnings", []) or []),
            "raw": result,
            "pages": [
                {
                    "page_number": pg.page_number,
                    "components": pg.components,
                    "nets": pg.nets,
                    "width_pts": pg.width_pts,
                    "height_pts": pg.height_pts,
                }
                for pg in getattr(result, "pages", []) or []
            ],
            "file_path": file_path,
        }

    if fmt == "netlist":
        # Phase 4c — proper ORCAD PSTXNET / Pads ASCII parser. Falls back
        # to the original regex stub only if the proper parser produces
        # zero output (very malformed file).
        try:
            from .netlist_parser import parse_netlist
            parsed = parse_netlist(file_path)
            comp_dicts = [_dataclass_to_dict(c) for c in parsed.components]
            net_dicts = [_dataclass_to_dict(n) for n in parsed.nets]
            if comp_dicts or net_dicts:
                return {
                    "source_format": "netlist",
                    "components": comp_dicts,
                    "nets": net_dicts,
                    "title": None,
                    "warnings": list(parsed.warnings or []),
                    "raw": parsed,
                    "file_path": file_path,
                }
        except Exception as e:  # pragma: no cover — fall through to stub
            stub_warning = f"netlist_parser raised {e!s}; falling back to regex stub"
        else:
            stub_warning = "netlist_parser found nothing; falling back to regex stub"
        components, nets = _parse_simple_netlist(file_path)
        return {
            "source_format": "netlist",
            "components": components,
            "nets": nets,
            "title": None,
            "warnings": [stub_warning],
            "raw": None,
            "file_path": file_path,
        }

    # KiCad and Altium share the SchematicParserFactory path.
    from .schematic_parser import SchematicParserFactory
    parsed = SchematicParserFactory.parse(file_path)
    return {
        "source_format": fmt,
        "components": [_dataclass_to_dict(c) for c in (parsed.components or [])],
        "nets": [_dataclass_to_dict(n) for n in (parsed.nets or [])],
        "title": parsed.title,
        "warnings": list(parsed.warnings or []),
        "raw": parsed,
        "file_path": file_path,
    }


def _dataclass_to_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return dict(obj)
    # ``is_dataclass(obj)`` returns True for the class itself too, but
    # ``asdict`` only accepts instances. Narrow before calling.
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    # Last resort — try to read attributes off whatever this is.
    return {k: getattr(obj, k) for k in dir(obj) if not k.startswith("_") and not callable(getattr(obj, k, None))}


def _parse_simple_netlist(file_path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Trivial netlist reader: pulls REFDES + NET tokens line by line.

    Just enough so downstream analyzers see *something* rather than failing
    hard. A proper ORCAD/Pads parser is a separate effort.
    """
    import re

    refdes_re = re.compile(r"^\s*([RCLUDQXJK][A-Za-z]?\d+)\b", re.MULTILINE)
    net_re = re.compile(r"NET_NAME\s*[:=]\s*['\"]?([\w\+\-\.]+)['\"]?", re.IGNORECASE)
    components: list[dict[str, Any]] = []
    nets: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    seen_nets: set[str] = set()
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return components, nets
    for m in refdes_re.finditer(text):
        ref = m.group(1).upper()
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        components.append({"reference": ref, "value": None, "page": 1})
    for m in net_re.finditer(text):
        name = m.group(1)
        if name in seen_nets:
            continue
        seen_nets.add(name)
        nets.append({
            "name": name,
            "is_power": name.upper().startswith(("VCC", "VDD", "V3", "V5", "VBAT", "VBUS")),
            "is_ground": name.upper().startswith(("GND", "VSS", "AGND", "DGND")),
        })
    return components, nets

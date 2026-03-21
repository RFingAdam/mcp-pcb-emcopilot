"""PDF schematic parser for extracting component references and net names.

Extracts text-layer data from schematic PDFs exported by Altium, OrCAD, KiCad,
and other EDA tools.  Uses PyMuPDF (fitz) when available; falls back to basic
page-count and image-path extraction when it is not installed.

Usage::

    parser = PDFSchematicParser()
    result = parser.parse("schematic.pdf")
    print(result.components)   # [{"reference": "R1", "value": "10k", ...}, ...]
    print(result.nets)         # [{"name": "VCC", "page": 1}, ...]
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reference-designator regex
# ---------------------------------------------------------------------------
# Matches standard EDA reference designators:
#   R1, R10, C100, U3, J1, L2, D5, Q1, FB1, FL1, TP1, SW1, RN1, etc.
# Also captures an optional value suffix after whitespace or equals:
#   R1 10k, R1=10k, C10 100nF
_REFDES_PATTERN = re.compile(
    r"""
    \b                                     # word boundary
    (?P<ref>
        (?:R|C|L|U|J|D|Q|FB|FL|TP|SW|RN|  # common prefixes
           CR|BT|F|K|M|P|RT|T|VR|X|Y|     # extended prefixes
           IC|LED|TVS|RV|MOV|NTC|PTC)      # more component types
        \d+                                 # numeric part
        [A-Z]?                              # optional letter suffix (e.g. R1A)
    )
    (?:                                     # optional value capture
        \s*[=:\s]\s*                        # separator: = or : or whitespace
        (?P<value>
            [\d.]+\s*[pnuUmMkKGT]?         # number with SI prefix
            [FfHhVvAaRr\u03A9]?             # unit (F, H, V, A, R, ohm)
        )
    )?
    \b
    """,
    re.VERBOSE,
)

# Net / label patterns found in schematic PDF text
# Matches common net-label formats: NET_NAME, VCC, GND, +3V3, SDA, SCL, etc.
_NET_LABEL_PATTERN = re.compile(
    r"""
    (?:^|(?<=\s)|(?<=[\(,;:]))             # start of string, whitespace, or delimiter
    (?P<net>
        (?:\+\d+V\d*)                       # power rails: +3V3, +5V, +1V8
        |
        (?:VCC|VDD|VSS|GND|VBUS|VBAT)      # standard power/gnd
        (?:[A-Z0-9_]*)                      # with optional suffix: VCC3V3, VBUS_USB
        |
        (?:[A-Z][A-Z0-9_]{1,30})           # uppercase net names like SDA, CLK_100M
    )
    \b
    """,
    re.VERBOSE,
)

# Words that look like net names but are usually just schematic boilerplate
_NET_BLACKLIST = frozenset({
    "REV", "DATE", "PAGE", "SHEET", "TITLE", "DRAWN", "APPROVED",
    "CHECKED", "SCALE", "SIZE", "FILE", "PROJECT", "COMPANY",
    "COPYRIGHT", "NOTES", "DESCRIPTION", "OF", "BY", "REF",
    "VALUE", "FOOTPRINT", "DATASHEET", "COMPONENT", "SYMBOL",
    "NAME", "NUMBER", "QTY", "QUANTITY", "PART", "DESIGNATOR",
    "REVISION", "AUTHOR", "ENGINEER", "DOCUMENT", "SCH", "PDF",
    "NOT", "FOR", "THE", "AND", "THIS", "WITH", "FROM", "ARE",
})


@dataclass
class PDFSchematicPage:
    """Data extracted from one page of a schematic PDF."""
    page_number: int
    text: str = ""
    components: list[dict] = field(default_factory=list)
    nets: list[dict] = field(default_factory=list)
    image_path: Optional[str] = None
    width_pts: float = 0.0
    height_pts: float = 0.0


@dataclass
class PDFSchematicResult:
    """Complete result of parsing a schematic PDF."""
    file_path: str
    page_count: int = 0
    pages: list[PDFSchematicPage] = field(default_factory=list)
    components: list[dict] = field(default_factory=list)
    nets: list[dict] = field(default_factory=list)
    has_text_layer: bool = False
    pymupdf_available: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_summary(self) -> dict:
        return {
            "file_path": self.file_path,
            "page_count": self.page_count,
            "component_count": len(self.components),
            "net_count": len(self.nets),
            "has_text_layer": self.has_text_layer,
            "pymupdf_available": self.pymupdf_available,
            "unique_ref_prefixes": self._ref_prefix_summary(),
            "warnings": self.warnings[:10],
        }

    def _ref_prefix_summary(self) -> dict[str, int]:
        prefixes: dict[str, int] = {}
        for comp in self.components:
            ref = comp.get("reference", "")
            prefix = re.match(r"([A-Z]+)", ref)
            if prefix:
                p = prefix.group(1)
                prefixes[p] = prefixes.get(p, 0) + 1
        return prefixes


class PDFSchematicParser:
    """Parse PDF schematics to extract component references and net labels.

    Requires ``PyMuPDF`` (``pip install pymupdf``) for full text extraction.
    Without it, only page count and page-image paths are available.
    """

    def __init__(self):
        self._fitz = None

    def _load_fitz(self) -> bool:
        """Try to import PyMuPDF (fitz). Return True if available."""
        if self._fitz is not None:
            return True
        try:
            import fitz  # type: ignore[import-untyped]
            self._fitz = fitz
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, file_path: str) -> PDFSchematicResult:
        """Parse a PDF schematic file.

        Args:
            file_path: Path to the PDF file.

        Returns:
            PDFSchematicResult with pages, components, and nets.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file is not a valid PDF.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {file_path}")
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Not a PDF file: {file_path}")

        result = PDFSchematicResult(file_path=str(path.resolve()))

        if self._load_fitz():
            result.pymupdf_available = True
            try:
                self._parse_with_fitz(result)
            except Exception as e:
                result.warnings.append(f"PyMuPDF failed to parse: {e}")
                result.page_count = 0
        else:
            result.pymupdf_available = False
            self._parse_fallback(result)
            result.warnings.append(
                "PyMuPDF not installed. Only page count available. "
                "Install with: pip install pymupdf"
            )

        return result

    # ------------------------------------------------------------------
    # PyMuPDF-based extraction
    # ------------------------------------------------------------------

    def _parse_with_fitz(self, result: PDFSchematicResult) -> None:
        """Extract text and images using PyMuPDF."""
        fitz = self._fitz
        doc = fitz.open(result.file_path)  # type: ignore[union-attr]
        result.page_count = len(doc)

        all_components: dict[str, dict] = {}  # keyed by reference
        all_nets: dict[str, dict] = {}  # keyed by net name

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text") or ""
            rect = page.rect

            page_data = PDFSchematicPage(
                page_number=page_num + 1,
                text=text,
                width_pts=rect.width,
                height_pts=rect.height,
            )

            if text.strip():
                result.has_text_layer = True
                page_comps = self._extract_components(text, page_num + 1)
                page_nets = self._extract_nets(text, page_num + 1)
                page_data.components = page_comps
                page_data.nets = page_nets

                # Merge into global lists (dedup by reference / net name)
                for comp in page_comps:
                    ref = comp["reference"]
                    if ref not in all_components:
                        all_components[ref] = comp
                    else:
                        # Track additional pages
                        existing_pages = all_components[ref].get("pages", [all_components[ref].get("page", 1)])
                        if page_num + 1 not in existing_pages:
                            existing_pages.append(page_num + 1)
                        all_components[ref]["pages"] = existing_pages

                for net in page_nets:
                    name = net["name"]
                    if name not in all_nets:
                        all_nets[name] = net
                    else:
                        existing_pages = all_nets[name].get("pages", [all_nets[name].get("page", 1)])
                        if page_num + 1 not in existing_pages:
                            existing_pages.append(page_num + 1)
                        all_nets[name]["pages"] = existing_pages

            result.pages.append(page_data)

        doc.close()

        result.components = list(all_components.values())
        result.nets = list(all_nets.values())

        if not result.has_text_layer:
            result.warnings.append(
                "PDF has no extractable text layer. "
                "The schematic may be a rasterized/scanned image. "
                "Use pcb_get_schematic_page to get page images for visual inspection."
            )

    # ------------------------------------------------------------------
    # Fallback (no PyMuPDF)
    # ------------------------------------------------------------------

    def _parse_fallback(self, result: PDFSchematicResult) -> None:
        """Minimal parse without PyMuPDF -- just get page count from header."""
        try:
            with open(result.file_path, "rb") as f:
                header = f.read(1024)
                # Verify PDF signature
                if not header.startswith(b"%PDF"):
                    raise ValueError(f"Not a valid PDF file: {result.file_path}")

                # Read trailer to find page count (heuristic)
                f.seek(0, 2)
                file_size = f.tell()
                # Read last 2KB for xref/trailer
                read_size = min(file_size, 2048)
                f.seek(file_size - read_size)
                trailer = f.read(read_size).decode("latin-1", errors="ignore")

                # Try to find /Count N in the trailer (catalog page count)
                count_match = re.search(r"/Count\s+(\d+)", trailer)
                if count_match:
                    result.page_count = int(count_match.group(1))
                else:
                    # Fallback: count /Type /Page occurrences in the whole file
                    f.seek(0)
                    content = f.read().decode("latin-1", errors="ignore")
                    result.page_count = len(re.findall(r"/Type\s*/Page[^s]", content))

        except ValueError:
            raise
        except Exception as e:
            result.warnings.append(f"Could not read PDF header: {e}")
            result.page_count = 0

    # ------------------------------------------------------------------
    # Render a page to image (requires fitz)
    # ------------------------------------------------------------------

    def render_page_image(
        self, file_path: str, page_number: int, output_dir: str, dpi: int = 150
    ) -> Optional[str]:
        """Render a PDF page to a PNG image.

        Args:
            file_path: Path to the PDF.
            page_number: 1-based page number.
            output_dir: Directory for the output image.
            dpi: Resolution (default 150).

        Returns:
            Path to the rendered PNG, or None if fitz is not available.
        """
        if not self._load_fitz():
            return None

        fitz = self._fitz
        doc = fitz.open(file_path)  # type: ignore[union-attr]
        try:
            if page_number < 1 or page_number > len(doc):
                raise ValueError(
                    f"Page {page_number} out of range (1-{len(doc)})"
                )

            page = doc[page_number - 1]
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)  # type: ignore[union-attr]
            pix = page.get_pixmap(matrix=mat)

            os.makedirs(output_dir, exist_ok=True)
            stem = Path(file_path).stem
            out_path = os.path.join(output_dir, f"{stem}_page{page_number}.png")
            pix.save(out_path)

            return out_path
        finally:
            doc.close()

    # ------------------------------------------------------------------
    # Text-analysis helpers
    # ------------------------------------------------------------------

    def _extract_components(self, text: str, page: int) -> list[dict]:
        """Extract component references from page text."""
        components: list[dict] = []
        seen: set[str] = set()

        for m in _REFDES_PATTERN.finditer(text):
            ref = m.group("ref")
            if ref in seen:
                continue
            seen.add(ref)

            value = (m.group("value") or "").strip() or None
            components.append({
                "reference": ref,
                "value": value,
                "page": page,
            })

        return components

    def _extract_nets(self, text: str, page: int) -> list[dict]:
        """Extract net/label names from page text."""
        nets: list[dict] = []
        seen: set[str] = set()

        for m in _NET_LABEL_PATTERN.finditer(text):
            name = m.group("net")
            if name in seen or name in _NET_BLACKLIST:
                continue
            # Skip if it matches a refdes (already captured as component)
            if _REFDES_PATTERN.match(name):
                continue
            # Skip very short names that are likely noise
            if len(name) < 3:
                continue
            seen.add(name)

            is_power = bool(re.match(r"^(?:VCC|VDD|VBUS|VBAT|\+\d)", name))
            is_ground = bool(re.match(r"^(?:GND|VSS|AGND|DGND|PGND)", name))

            nets.append({
                "name": name,
                "page": page,
                "is_power": is_power,
                "is_ground": is_ground,
            })

        return nets

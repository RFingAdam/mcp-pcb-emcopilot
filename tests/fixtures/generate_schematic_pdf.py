"""Generate a tiny synthetic PDF that the PDF schematic parser can mine
for refdes + net names. Run once to produce ``sample_schematic.pdf``.

Pure-stdlib; no PyMuPDF or reportlab dependency — we hand-write a minimal
valid PDF document with a single page containing a text stream that names
a few components and nets. The PDF schematic parser uses pdfplumber
internally which reads the same text layer.
"""

from __future__ import annotations

from pathlib import Path


# Minimal PDF 1.4 with a single uncompressed text stream. The byte offsets
# are computed and patched in at write time so we don't have to keep the
# xref table hand-aligned. Layout-only — no fonts beyond Helvetica.
def build_pdf(text_lines: list[str]) -> bytes:
    # Construct the page content stream — one line per call to Tj.
    content_lines: list[bytes] = [b"BT\n/F1 12 Tf\n50 750 Td\n"]
    for line in text_lines:
        content_lines.append(f"({line}) Tj\n0 -16 Td\n".encode("latin-1"))
    content_lines.append(b"ET\n")
    content_stream = b"".join(content_lines)

    objects: list[bytes] = []

    def add_obj(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog_id = add_obj(b"<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add_obj(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    page_id = add_obj(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
    )
    content_id = add_obj(
        f"<< /Length {len(content_stream)} >>\nstream\n".encode("latin-1")
        + content_stream
        + b"\nendstream"
    )
    font_id = add_obj(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    assert catalog_id == 1 and pages_id == 2 and page_id == 3
    assert content_id == 4 and font_id == 5

    # Assemble file + xref.
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("latin-1"))
        out.extend(obj)
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets:
        out.extend(f"{off:010d} 00000 n \n".encode("latin-1"))
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode("latin-1")
    )
    out.extend(f"startxref\n{xref_pos}\n%%EOF\n".encode("latin-1"))
    return bytes(out)


SCHEMATIC_TEXT = [
    "Sample Synthetic Schematic - Page 1",
    "Components",
    "R1 10k",
    "R2 4.7k",
    "C1 10uF/16V",
    "C2 100nF/50V",
    "U1 STM32F407VGT6",
    "D1 PESD5V0",
    "J1 USB-Type-C",
    "Net Labels",
    "VCC_3V3",
    "GND",
    "USB_DP",
    "USB_DM",
    "VBUS",
]


def main() -> None:
    out_path = Path(__file__).parent / "sample_schematic.pdf"
    out_path.write_bytes(build_pdf(SCHEMATIC_TEXT))
    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

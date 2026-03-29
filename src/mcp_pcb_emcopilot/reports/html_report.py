"""Interactive HTML report generator for PCB design reviews.

Generates a single self-contained HTML file with embedded CSS/JS that provides:
- Collapsible finding sections with severity color coding
- Embedded SVG board renders (inline, zoomable)
- Executive summary with score dashboard
- Finding filtering by severity
- Text search across findings
- Print-friendly styles

Provides both a function-based API (``generate_html_report``) that works with
:class:`PCBDesignData`, and a standalone class-based API
(:class:`HTMLReportGenerator`) that accepts lightweight dataclasses and does
not require a parsed PCB design.
"""
from __future__ import annotations

import base64
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from ..models.pcb_data import PCBDesignData

# ---------------------------------------------------------------------------
# Standalone dataclasses (class-based API)
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    """A single design-review finding."""

    severity: str  # "critical", "warning", "info", "pass"
    title: str
    description: str
    recommendation: str = ""
    location: str = ""  # e.g. "U1 pin 3" or "NET: CLK"
    domain: str = ""


@dataclass
class DomainResult:
    """Aggregated results for one analysis domain."""

    name: str
    score: float  # 0-100
    findings: list[Finding] = field(default_factory=list)


@dataclass
class HTMLReportData:
    """Input data for the standalone HTML report generator."""

    title: str
    design_file: str
    review_date: str
    domains: list[DomainResult] = field(default_factory=list)
    summary: dict = field(default_factory=dict)  # overall scores, pass/fail counts
    images: dict[str, str] = field(default_factory=dict)  # name -> SVG content or base64 PNG


class HTMLReportGenerator:
    """Self-contained interactive HTML report generator.

    Example::

        data = HTMLReportData(
            title="My Board Review",
            design_file="board.kicad_pcb",
            review_date="2025-05-01",
            domains=[...],
        )
        gen = HTMLReportGenerator()
        html_str = gen.generate(data)
        path = gen.save(data, "/tmp/report.html")
    """

    def generate(self, data: HTMLReportData) -> str:
        """Return a complete self-contained HTML string."""
        return _generate_html_from_data(data)

    def save(self, data: HTMLReportData, output_path: str) -> str:
        """Write report to *output_path* and return the absolute path."""
        html = self.generate(data)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(html)
        return os.path.abspath(output_path)


# ---------------------------------------------------------------------------
# CSS themes
# ---------------------------------------------------------------------------

_LIGHT_THEME_CSS = """
:root {
    --bg-primary: #ffffff;
    --bg-secondary: #f8f9fa;
    --bg-card: #ffffff;
    --text-primary: #1a1a2e;
    --text-secondary: #555555;
    --text-muted: #888888;
    --border-color: #dee2e6;
    --header-bg: #1F4E79;
    --header-text: #ffffff;
    --shadow: 0 2px 8px rgba(0,0,0,0.08);
    --shadow-hover: 0 4px 16px rgba(0,0,0,0.12);
    --badge-critical-bg: #dc3545;
    --badge-critical-text: #ffffff;
    --badge-high-bg: #fd7e14;
    --badge-high-text: #ffffff;
    --badge-warning-bg: #ffc107;
    --badge-warning-text: #212529;
    --badge-pass-bg: #28a745;
    --badge-pass-text: #ffffff;
    --badge-info-bg: #17a2b8;
    --badge-info-text: #ffffff;
    --finding-critical-bg: #fff5f5;
    --finding-critical-border: #dc3545;
    --finding-high-bg: #fff8f0;
    --finding-high-border: #fd7e14;
    --finding-warning-bg: #fffef0;
    --finding-warning-border: #ffc107;
    --finding-pass-bg: #f0fff4;
    --finding-pass-border: #28a745;
    --finding-info-bg: #f0f8ff;
    --finding-info-border: #17a2b8;
    --filter-active-bg: #1F4E79;
    --filter-active-text: #ffffff;
    --filter-inactive-bg: #e9ecef;
    --filter-inactive-text: #495057;
}
"""

_DARK_THEME_CSS = """
:root {
    --bg-primary: #0f172a;
    --bg-secondary: #1e293b;
    --bg-card: #1e293b;
    --text-primary: #e2e8f0;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --border-color: #334155;
    --header-bg: #0f172a;
    --header-text: #e2e8f0;
    --shadow: 0 2px 8px rgba(0,0,0,0.3);
    --shadow-hover: 0 4px 16px rgba(0,0,0,0.5);
    --badge-critical-bg: #ef4444;
    --badge-critical-text: #ffffff;
    --badge-high-bg: #f97316;
    --badge-high-text: #ffffff;
    --badge-warning-bg: #eab308;
    --badge-warning-text: #1e293b;
    --badge-pass-bg: #22c55e;
    --badge-pass-text: #ffffff;
    --badge-info-bg: #06b6d4;
    --badge-info-text: #ffffff;
    --finding-critical-bg: #1c1017;
    --finding-critical-border: #ef4444;
    --finding-high-bg: #1c1510;
    --finding-high-border: #f97316;
    --finding-warning-bg: #1c1a10;
    --finding-warning-border: #eab308;
    --finding-pass-bg: #101c14;
    --finding-pass-border: #22c55e;
    --finding-info-bg: #101a1c;
    --finding-info-border: #06b6d4;
    --filter-active-bg: #3b82f6;
    --filter-active-text: #ffffff;
    --filter-inactive-bg: #334155;
    --filter-inactive-text: #94a3b8;
}
"""

_COMMON_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.6;
}
.container { max-width: 1100px; margin: 0 auto; padding: 0 24px; }
header {
    background: var(--header-bg);
    color: var(--header-text);
    padding: 32px 0 24px;
    margin-bottom: 32px;
    border-bottom: 3px solid var(--badge-info-bg);
}
header h1 { font-size: 28px; font-weight: 700; margin-bottom: 4px; }
header .subtitle { font-size: 14px; opacity: 0.8; }
header .meta { font-size: 12px; opacity: 0.6; margin-top: 8px; }

/* Executive summary */
.summary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 16px;
    margin: 24px 0;
}
.summary-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 16px;
    text-align: center;
    box-shadow: var(--shadow);
}
.summary-card .value { font-size: 32px; font-weight: 700; }
.summary-card .label { font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }

/* Overall status */
.status-pass { color: var(--badge-pass-bg); }
.status-warning { color: var(--badge-warning-bg); }
.status-fail { color: var(--badge-critical-bg); }

/* Filter bar */
.filter-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 24px 0;
    padding: 16px;
    background: var(--bg-secondary);
    border-radius: 8px;
    align-items: center;
}
.filter-bar label { font-size: 13px; font-weight: 600; margin-right: 8px; color: var(--text-secondary); }
.filter-btn {
    padding: 6px 14px;
    border: none;
    border-radius: 16px;
    cursor: pointer;
    font-size: 12px;
    font-weight: 600;
    transition: all 0.2s;
    background: var(--filter-inactive-bg);
    color: var(--filter-inactive-text);
}
.filter-btn.active {
    background: var(--filter-active-bg);
    color: var(--filter-active-text);
}
.filter-btn:hover { opacity: 0.85; }
.filter-count {
    margin-left: 16px;
    font-size: 12px;
    color: var(--text-muted);
}

/* Severity badges */
.badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.badge-CRITICAL { background: var(--badge-critical-bg); color: var(--badge-critical-text); }
.badge-HIGH { background: var(--badge-high-bg); color: var(--badge-high-text); }
.badge-WARNING { background: var(--badge-warning-bg); color: var(--badge-warning-text); }
.badge-PASS { background: var(--badge-pass-bg); color: var(--badge-pass-text); }
.badge-INFO { background: var(--badge-info-bg); color: var(--badge-info-text); }

/* Collapsible sections */
.section {
    margin: 24px 0;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    overflow: hidden;
    box-shadow: var(--shadow);
}
.section-header {
    padding: 16px 20px;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
    user-select: none;
    transition: background 0.2s;
}
.section-header:hover { opacity: 0.9; }
.section-header h2 { font-size: 18px; font-weight: 600; }
.section-header .toggle { font-size: 18px; transition: transform 0.3s; }
.section-header.collapsed .toggle { transform: rotate(-90deg); }
.section-body { padding: 20px; }
.section-body.collapsed { display: none; }

/* Board info table */
.info-table { width: 100%; border-collapse: collapse; margin: 16px 0; }
.info-table th, .info-table td {
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid var(--border-color);
    font-size: 13px;
}
.info-table th { font-weight: 600; color: var(--text-secondary); width: 200px; }
.info-table tr:last-child th, .info-table tr:last-child td { border-bottom: none; }

/* Finding cards */
.finding {
    margin: 12px 0;
    padding: 14px 18px;
    border-left: 4px solid var(--border-color);
    border-radius: 4px;
    transition: box-shadow 0.2s;
}
.finding:hover { box-shadow: var(--shadow-hover); }
.finding-CRITICAL { background: var(--finding-critical-bg); border-left-color: var(--finding-critical-border); }
.finding-HIGH { background: var(--finding-high-bg); border-left-color: var(--finding-high-border); }
.finding-WARNING { background: var(--finding-warning-bg); border-left-color: var(--finding-warning-border); }
.finding-PASS { background: var(--finding-pass-bg); border-left-color: var(--finding-pass-border); }
.finding-INFO { background: var(--finding-info-bg); border-left-color: var(--finding-info-border); }
.finding-title { font-weight: 600; font-size: 14px; margin-bottom: 6px; }
.finding-detail { font-size: 13px; color: var(--text-secondary); margin-bottom: 6px; }
.finding-recommendation {
    font-size: 12px;
    color: var(--text-muted);
    padding-top: 6px;
    border-top: 1px dashed var(--border-color);
}
.finding-recommendation strong { color: var(--text-secondary); }

/* Images */
.render-container {
    text-align: center;
    margin: 16px 0;
    padding: 16px;
    background: var(--bg-secondary);
    border-radius: 8px;
    overflow: hidden;
}
.render-container img {
    max-width: 100%;
    height: auto;
    border-radius: 4px;
    cursor: zoom-in;
    transition: transform 0.3s;
}
.render-container img.zoomed {
    transform: scale(1.5);
    cursor: zoom-out;
}
.render-caption {
    font-size: 12px;
    color: var(--text-muted);
    margin-top: 8px;
    font-style: italic;
}

/* Footer */
footer {
    text-align: center;
    padding: 32px 0;
    color: var(--text-muted);
    font-size: 12px;
    border-top: 1px solid var(--border-color);
    margin-top: 48px;
}

/* Print styles */
@media print {
    body { background: white; color: black; }
    header { background: white; color: black; border-bottom: 2px solid #333; page-break-after: always; }
    .filter-bar { display: none; }
    .section { break-inside: avoid; box-shadow: none; border: 1px solid #ccc; }
    .section-body.collapsed { display: block !important; }
    .section-header .toggle { display: none; }
    .finding { break-inside: avoid; }
    .render-container img { max-width: 90%; }
    footer { page-break-before: always; }
}
"""

_JS = """
document.addEventListener('DOMContentLoaded', function() {
    // Collapsible sections
    document.querySelectorAll('.section-header').forEach(function(header) {
        header.addEventListener('click', function() {
            var body = this.nextElementSibling;
            if (body && body.classList.contains('section-body')) {
                body.classList.toggle('collapsed');
                this.classList.toggle('collapsed');
            }
        });
    });

    // Image zoom
    document.querySelectorAll('.render-container img').forEach(function(img) {
        img.addEventListener('click', function() {
            this.classList.toggle('zoomed');
        });
    });

    // Severity filter buttons
    var filterBtns = document.querySelectorAll('.filter-btn');
    var activeFilters = new Set(['CRITICAL', 'HIGH', 'WARNING', 'PASS', 'INFO']);

    function updateVisibility() {
        var findings = document.querySelectorAll('.finding');
        var visible = 0;
        findings.forEach(function(f) {
            var sev = f.getAttribute('data-severity');
            if (activeFilters.has(sev)) {
                f.style.display = '';
                visible++;
            } else {
                f.style.display = 'none';
            }
        });
        var countEl = document.getElementById('filter-count');
        if (countEl) {
            countEl.textContent = visible + ' of ' + findings.length + ' findings shown';
        }
    }

    filterBtns.forEach(function(btn) {
        btn.addEventListener('click', function() {
            var sev = this.getAttribute('data-severity');
            if (sev === 'ALL') {
                if (activeFilters.size === 5) {
                    activeFilters.clear();
                    filterBtns.forEach(function(b) { b.classList.remove('active'); });
                } else {
                    activeFilters = new Set(['CRITICAL', 'HIGH', 'WARNING', 'PASS', 'INFO']);
                    filterBtns.forEach(function(b) { b.classList.add('active'); });
                }
            } else {
                if (activeFilters.has(sev)) {
                    activeFilters.delete(sev);
                    this.classList.remove('active');
                } else {
                    activeFilters.add(sev);
                    this.classList.add('active');
                }
            }
            updateVisibility();
        });
    });

    updateVisibility();
});
"""


# ---------------------------------------------------------------------------
# HTML building helpers
# ---------------------------------------------------------------------------

def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _sanitize_svg(svg: str) -> str:
    """Strip dangerous elements and attributes from inline SVG content.

    Removes ``<script>`` blocks, ``on*`` event-handler attributes, and
    ``javascript:`` URIs to prevent SVG-based XSS when embedding
    user-supplied images in the report.
    """
    # Remove <script>...</script> (including nested / multiline)
    cleaned = re.sub(r"<script[\s>].*?</script>", "", svg, flags=re.DOTALL | re.IGNORECASE)
    # Remove standalone <script .../> self-closing tags
    cleaned = re.sub(r"<script\b[^>]*/\s*>", "", cleaned, flags=re.IGNORECASE)
    # Remove on* event-handler attributes (onclick, onload, onerror, etc.)
    cleaned = re.sub(r"""\s+on\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]*)""", "", cleaned, flags=re.IGNORECASE)
    # Remove javascript: URIs in href/xlink:href/src attributes
    cleaned = re.sub(
        r"""(href|xlink:href|src)\s*=\s*["']?\s*javascript:""",
        r"\1=\"\"",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


def _severity_class(severity: str) -> str:
    """Normalize severity to CSS class name."""
    s = severity.upper().strip()
    if s in ("CRITICAL", "HIGH", "WARNING", "PASS", "INFO"):
        return s
    if s in ("ERROR", "FAIL"):
        return "CRITICAL"
    if s in ("MEDIUM", "MODERATE"):
        return "WARNING"
    if s in ("LOW", "OK"):
        return "PASS"
    return "INFO"


def _build_badge(severity: str) -> str:
    """Build an HTML severity badge."""
    cls = _severity_class(severity)
    return f'<span class="badge badge-{cls}">{_escape_html(cls)}</span>'


def _build_finding_card(finding: dict[str, Any]) -> str:
    """Build HTML for a single finding card."""
    sev = _severity_class(finding.get("severity", "INFO"))
    title = _escape_html(str(finding.get("title", finding.get("description", "Finding"))))
    detail = _escape_html(str(finding.get("detail", finding.get("description", ""))))
    rec = _escape_html(str(finding.get("recommendation", "")))

    parts = [
        f'<div class="finding finding-{sev}" data-severity="{sev}">',
        f'  <div class="finding-title">{_build_badge(sev)} {title}</div>',
    ]
    if detail:
        parts.append(f'  <div class="finding-detail">{detail}</div>')
    if rec:
        parts.append(f'  <div class="finding-recommendation"><strong>Recommendation:</strong> {rec}</div>')
    parts.append("</div>")
    return "\n".join(parts)


def _build_section(title: str, body_html: str, collapsed: bool = False, title_is_html: bool = False) -> str:
    """Build a collapsible section."""
    hdr_cls = " collapsed" if collapsed else ""
    body_cls = " collapsed" if collapsed else ""
    display_title = title if title_is_html else _escape_html(title)
    return f"""
<div class="section">
  <div class="section-header{hdr_cls}">
    <h2>{display_title}</h2>
    <span class="toggle">&#9660;</span>
  </div>
  <div class="section-body{body_cls}">
    {body_html}
  </div>
</div>
"""


def _build_info_table(rows: list[tuple[str, str]]) -> str:
    """Build an info table from key-value pairs."""
    parts = ['<table class="info-table">']
    for label, value in rows:
        parts.append(
            f"<tr><th>{_escape_html(label)}</th>"
            f"<td>{_escape_html(str(value))}</td></tr>"
        )
    parts.append("</table>")
    return "\n".join(parts)


def _embed_image(path: str, caption: str = "") -> str:
    """Embed an image as base64 data URI."""
    if not path or not os.path.exists(path):
        return ""

    ext = os.path.splitext(path)[1].lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".svg": "image/svg+xml",
        ".gif": "image/gif",
    }
    mime = mime_map.get(ext, "image/png")

    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")

    cap_html = ""
    if caption:
        cap_html = f'<div class="render-caption">{_escape_html(caption)}</div>'

    return f"""
<div class="render-container">
  <img src="data:{mime};base64,{data}" alt="{_escape_html(caption)}" />
  {cap_html}
</div>
"""


# ---------------------------------------------------------------------------
# Standalone class-based report generation
# ---------------------------------------------------------------------------

def _generate_html_from_data(data: HTMLReportData) -> str:
    """Build a self-contained HTML string from *HTMLReportData*.

    This is the class-based API counterpart to :func:`generate_html_report`.
    It does not require a :class:`PCBDesignData` instance.
    """
    theme_css = _DARK_THEME_CSS  # class-based API defaults to dark theme

    # Count findings by severity
    severity_counts: dict[str, int] = {
        "CRITICAL": 0, "HIGH": 0, "WARNING": 0, "PASS": 0, "INFO": 0,
    }
    total_findings = 0
    for domain in data.domains:
        for finding in domain.findings:
            sev = _severity_class(finding.severity)
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
            total_findings += 1

    # Build domain sections
    sections_html: list[str] = []
    for domain in data.domains:
        cards: list[str] = []
        for finding in domain.findings:
            sev = _severity_class(finding.severity)
            cards.append(_build_finding_card({
                "severity": sev,
                "title": finding.title,
                "description": finding.description,
                "recommendation": finding.recommendation,
                "location": finding.location,
            }))
        score_pct = domain.score
        score_cls = (
            "status-pass" if score_pct >= 80
            else "status-warning" if score_pct >= 60
            else "status-fail"
        )
        header_extra = f' <span class="{score_cls}" style="font-size:14px;">({score_pct:.0f}%)</span>'
        body = "\n".join(cards) if cards else "<p>No findings.</p>"
        sections_html.append(_build_section(f"{_escape_html(domain.name)}{header_extra}", body, title_is_html=True))

    # Embed images (inline SVG or base64)
    if data.images:
        img_parts: list[str] = []
        for label, content in data.images.items():
            if content.strip().startswith("<svg") or content.strip().startswith("<?xml"):
                # Encode SVG as base64 data URI to prevent script execution
                svg_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
                img_parts.append(
                    f'<div class="render-container">'
                    f'<img src="data:image/svg+xml;base64,{svg_b64}" alt="{_escape_html(label)}"/>'
                    f'<div class="render-caption">{_escape_html(label)}</div></div>'
                )
            else:
                img_parts.append(
                    f'<div class="render-container">'
                    f'<img src="data:image/png;base64,{content}" alt="{_escape_html(label)}"/>'
                    f'<div class="render-caption">{_escape_html(label)}</div></div>'
                )
        if img_parts:
            sections_html.append(
                _build_section("Board Images", "\n".join(img_parts), collapsed=True)
            )

    # Overall status
    overall_status = data.summary.get("overall_status", "N/A") if data.summary else "N/A"
    status_cls = "status-pass"
    if any(k in str(overall_status).upper() for k in ("CRITICAL", "FAIL")):
        status_cls = "status-fail"
    elif "WARNING" in str(overall_status).upper():
        status_cls = "status-warning"

    summary_cards = f"""
<div class="summary-grid">
  <div class="summary-card">
    <div class="value {status_cls}">{_escape_html(str(overall_status))}</div>
    <div class="label">Overall Status</div>
  </div>
  <div class="summary-card">
    <div class="value">{total_findings}</div>
    <div class="label">Total Findings</div>
  </div>
  <div class="summary-card">
    <div class="value" style="color: var(--badge-critical-bg);">{severity_counts.get('CRITICAL', 0)}</div>
    <div class="label">Critical</div>
  </div>
  <div class="summary-card">
    <div class="value" style="color: var(--badge-warning-bg);">{severity_counts.get('WARNING', 0)}</div>
    <div class="label">Warning</div>
  </div>
  <div class="summary-card">
    <div class="value" style="color: var(--badge-pass-bg);">{severity_counts.get('PASS', 0)}</div>
    <div class="label">Pass</div>
  </div>
</div>
"""

    filter_bar = f"""
<div class="filter-bar">
  <label>Filter by severity:</label>
  <button class="filter-btn active" data-severity="ALL">All</button>
  <button class="filter-btn active" data-severity="CRITICAL">Critical ({severity_counts.get('CRITICAL', 0)})</button>
  <button class="filter-btn active" data-severity="HIGH">High ({severity_counts.get('HIGH', 0)})</button>
  <button class="filter-btn active" data-severity="WARNING">Warning ({severity_counts.get('WARNING', 0)})</button>
  <button class="filter-btn active" data-severity="PASS">Pass ({severity_counts.get('PASS', 0)})</button>
  <button class="filter-btn active" data-severity="INFO">Info ({severity_counts.get('INFO', 0)})</button>
  <span class="filter-count" id="filter-count">{total_findings} of {total_findings} findings shown</span>
</div>
"""

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_escape_html(data.title)}</title>
<style>
{theme_css}
{_COMMON_CSS}
</style>
</head>
<body>
<header>
  <div class="container">
    <h1>{_escape_html(data.title)}</h1>
    <div class="subtitle">Comprehensive EMC, Signal Integrity &amp; DFM Analysis</div>
    <div class="meta">Design: {_escape_html(data.design_file)} | Date: {_escape_html(data.review_date)} | Generated: {now}</div>
  </div>
</header>

<main class="container">
  <h2>Executive Summary</h2>
  {summary_cards}
  {filter_bar}
  {"".join(sections_html)}
</main>

<footer>
  <div class="container">
    <p>Generated by MCP PCB EMCopilot</p>
    <p>{_escape_html(data.title)} | {now}</p>
  </div>
</footer>

<script>
{_JS}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Main report generation (function-based API)
# ---------------------------------------------------------------------------

def generate_html_report(
    design: PCBDesignData,
    session_id: str,
    output_path: str | None = None,
    title: str = "PCB Design Review Report",
    theme: str = "light",
    include_images: bool = True,
    image_dir: str | None = None,
) -> str:
    """Generate interactive HTML report.

    Args:
        design: PCBDesignData with review_results populated.
        session_id: Session identifier.
        output_path: Destination .html path. Defaults to temp file.
        title: Report title.
        theme: Color theme - "light" or "dark".
        include_images: Whether to embed images from image_dir.
        image_dir: Directory containing pre-rendered PNG/SVG images.

    Returns:
        Absolute path to the generated HTML file.
    """
    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".html", prefix="pcb_review_")
        os.close(fd)

    # Resolve images
    images: dict[str, str] = {}
    if include_images and image_dir and os.path.isdir(image_dir):
        for fname in os.listdir(image_dir):
            if fname.lower().endswith((".png", ".jpg", ".jpeg", ".svg")):
                label = os.path.splitext(fname)[0]
                images[label] = os.path.join(image_dir, fname)

    theme_css = _DARK_THEME_CSS if theme == "dark" else _LIGHT_THEME_CSS

    # Extract review results
    results = design.review_results or {}
    summary = results.get("executive_summary", {})
    domain_results = results.get("domain_results", [])

    # Count findings by severity
    severity_counts: dict[str, int] = {
        "CRITICAL": 0, "HIGH": 0, "WARNING": 0, "PASS": 0, "INFO": 0,
    }
    total_findings = 0
    for dr in domain_results:
        for finding in dr.get("findings", []):
            sev = _severity_class(finding.get("severity", "INFO"))
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
            total_findings += 1

    # Build HTML sections
    sections_html: list[str] = []

    # --- Board overview section ---
    board_w = design.board_width_mm or 0
    board_h = design.board_height_mm or 0
    layers = len(design.layers) if design.layers else 0

    overview_html = _build_info_table([
        ("Board Size", f"{board_w:.1f} x {board_h:.1f} mm ({board_w * board_h:.0f} mm2)"),
        ("Layer Count", str(layers)),
        ("Components", str(len(design.components))),
        ("Nets", str(len(design.nets))),
        ("Traces", str(len(design.traces))),
        ("Vias", str(len(design.vias))),
        ("Copper Zones", str(len(design.zones))),
    ])

    # Add board image if available
    for key in ("board_annotated", "board_full"):
        if key in images:
            overview_html += _embed_image(images[key], "Board layout render")
            break

    sections_html.append(_build_section("Board Overview", overview_html))

    # --- Stackup section ---
    if design.layers:
        stackup_html = ""
        if "stackup" in images:
            stackup_html += _embed_image(images["stackup"], "Layer stackup cross-section")

        layer_rows = []
        for ly in design.layers:
            lname = ly.get("name", "") if isinstance(ly, dict) else getattr(ly, "name", "")
            ltype = ly.get("type", "") if isinstance(ly, dict) else getattr(ly, "type", "")
            layer_rows.append((lname, ltype))
        if layer_rows:
            stackup_html += _build_info_table(layer_rows)

        sections_html.append(_build_section("Layer Stackup", stackup_html, collapsed=True))

    # --- Domain analysis sections ---
    for dr in domain_results:
        domain = dr.get("domain", "Unknown")
        status = dr.get("status", "")
        findings = dr.get("findings", [])

        body_parts = []
        if status:
            body_parts.append(f'<p><strong>Status:</strong> {_build_badge(status)} {_escape_html(status)}</p>')

        for finding in findings:
            body_parts.append(_build_finding_card(finding))

        # Add relevant image
        domain_lower = domain.lower().replace(" ", "_")
        for img_key in (f"nets_{domain_lower}", domain_lower, f"board_{domain_lower}"):
            if img_key in images:
                body_parts.append(_embed_image(images[img_key], f"{domain} analysis render"))
                break

        if not body_parts:
            body_parts.append('<p style="color: var(--text-muted);">No findings for this domain.</p>')

        sections_html.append(
            _build_section(f"{domain} Analysis", "\n".join(body_parts), collapsed=True)
        )

    # --- Drill table section ---
    if design.vias:
        drill_counts: dict[float, int] = {}
        for v in design.vias:
            d = v.get("drill_mm", 0) if isinstance(v, dict) else getattr(v, "drill_mm", 0)
            if d > 0:
                d_rounded = round(d, 3)
                drill_counts[d_rounded] = drill_counts.get(d_rounded, 0) + 1
        if drill_counts:
            drill_rows = [(f"{sz:.3f} mm", str(cnt)) for sz, cnt in sorted(drill_counts.items())]
            drill_rows.append(("Total", str(sum(drill_counts.values()))))
            drill_html = _build_info_table(drill_rows)
            sections_html.append(_build_section("Drill Table", drill_html, collapsed=True))

    # --- Net render images section ---
    net_imgs = {k: v for k, v in images.items() if k.startswith("net_")}
    if net_imgs:
        img_parts = []
        for label, path in sorted(net_imgs.items()):
            net_name = label.replace("net_", "").replace("_", " ").upper()
            img_parts.append(_embed_image(path, f"Net: {net_name}"))
        sections_html.append(
            _build_section("Net Highlight Renders", "\n".join(img_parts), collapsed=True)
        )

    # --- Build executive summary ---
    overall_status = summary.get("overall_status", "N/A")
    status_cls = "status-pass"
    if "CRITICAL" in overall_status.upper() or "FAIL" in overall_status.upper():
        status_cls = "status-fail"
    elif "WARNING" in overall_status.upper():
        status_cls = "status-warning"

    # --- VP Executive Dashboard ---
    crit_count = severity_counts.get('CRITICAL', 0)
    high_count = severity_counts.get('HIGH', 0)
    warn_count = severity_counts.get('WARNING', 0)
    pass_count = severity_counts.get('PASS', 0)
    info_count = severity_counts.get('INFO', 0)

    # SVG donut gauge for overall status
    gauge_color = "#dc3545" if "FAIL" in overall_status.upper() else "#ffc107" if "WARN" in overall_status.upper() else "#28a745"
    gauge_pct = max(5, min(95, 100 - (crit_count * 5 + high_count * 3 + warn_count)))  # Rough health score
    gauge_offset = 283 - (283 * gauge_pct / 100)

    # Domain risk breakdown
    domain_bars = ""
    for dr in domain_results:
        d_name = dr.get("domain", "?")
        d_findings = dr.get("findings", [])
        d_crits = sum(1 for f in d_findings if f.get("severity") in ("critical",))
        d_warns = sum(1 for f in d_findings if f.get("severity") in ("warning", "high"))
        d_info = sum(1 for f in d_findings if f.get("severity") in ("info",))
        d_total = len(d_findings)
        if d_total == 0:
            continue
        bar_color = "#dc3545" if d_crits > 0 else "#ffc107" if d_warns > 0 else "#28a745"
        bar_width = min(100, max(5, d_total * 2))
        domain_bars += (
            f'<div class="domain-bar" style="margin: 4px 0;">'
            f'<span style="display:inline-block;width:220px;font-size:13px;color:var(--text);">{_escape_html(d_name)}</span>'
            f'<span style="display:inline-block;width:{bar_width}%;max-width:50%;height:18px;'
            f'background:{bar_color};border-radius:3px;vertical-align:middle;"></span>'
            f'<span style="font-size:12px;margin-left:8px;color:var(--muted);">'
            f'{d_crits}C {d_warns}W {d_info}I</span></div>\n'
        )

    # Top 5 critical findings
    top_crits = []
    for dr in domain_results:
        for f in dr.get("findings", []):
            if f.get("severity") == "critical":
                loc = f.get("location", {})
                loc_str = f" at ({loc['x_mm']:.0f},{loc['y_mm']:.0f})mm" if loc.get("x_mm") else ""
                top_crits.append(f"{dr.get('domain','')}: {f.get('description','')[:100]}{loc_str}")
    top_crits_html = ""
    if top_crits:
        items = "".join(f"<li>{_escape_html(c)}</li>" for c in top_crits[:5])
        top_crits_html = f'<div style="margin-top:12px;"><strong>Top Critical Findings:</strong><ol style="margin:6px 0;padding-left:20px;font-size:13px;">{items}</ol></div>'

    summary_cards = f"""
<div style="display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start;margin-bottom:20px;">
  <!-- Overall gauge -->
  <div style="text-align:center;min-width:160px;">
    <svg width="140" height="140" viewBox="0 0 100 100">
      <circle cx="50" cy="50" r="45" fill="none" stroke="#e9ecef" stroke-width="10"/>
      <circle cx="50" cy="50" r="45" fill="none" stroke="{gauge_color}" stroke-width="10"
        stroke-dasharray="283" stroke-dashoffset="{gauge_offset:.0f}"
        transform="rotate(-90 50 50)" stroke-linecap="round"/>
      <text x="50" y="45" text-anchor="middle" font-size="16" font-weight="bold" fill="{gauge_color}">{gauge_pct}%</text>
      <text x="50" y="60" text-anchor="middle" font-size="9" fill="var(--muted)">health score</text>
    </svg>
    <div style="font-size:18px;font-weight:bold;color:{gauge_color};margin-top:4px;">{_escape_html(overall_status)}</div>
  </div>

  <!-- Severity breakdown -->
  <div style="min-width:200px;">
    <div style="font-size:14px;font-weight:600;margin-bottom:8px;">Findings ({total_findings})</div>
    <div style="display:flex;gap:12px;flex-wrap:wrap;">
      <div style="text-align:center;padding:8px 14px;background:#dc354520;border-radius:8px;border-left:4px solid #dc3545;">
        <div style="font-size:24px;font-weight:bold;color:#dc3545;">{crit_count}</div>
        <div style="font-size:11px;color:var(--muted);">Critical</div>
      </div>
      <div style="text-align:center;padding:8px 14px;background:#ffc10720;border-radius:8px;border-left:4px solid #ffc107;">
        <div style="font-size:24px;font-weight:bold;color:#e6a800;">{warn_count + high_count}</div>
        <div style="font-size:11px;color:var(--muted);">Warning</div>
      </div>
      <div style="text-align:center;padding:8px 14px;background:#28a74520;border-radius:8px;border-left:4px solid #28a745;">
        <div style="font-size:24px;font-weight:bold;color:#28a745;">{pass_count}</div>
        <div style="font-size:11px;color:var(--muted);">Pass</div>
      </div>
      <div style="text-align:center;padding:8px 14px;background:#17a2b820;border-radius:8px;border-left:4px solid #17a2b8;">
        <div style="font-size:24px;font-weight:bold;color:#17a2b8;">{info_count}</div>
        <div style="font-size:11px;color:var(--muted);">Info</div>
      </div>
    </div>
    {top_crits_html}
  </div>
</div>

<!-- Domain risk heatmap -->
<div style="margin:16px 0;padding:12px;background:var(--card-bg);border-radius:8px;border:1px solid var(--border);">
  <div style="font-size:14px;font-weight:600;margin-bottom:8px;">Domain Analysis ({len(domain_results)} domains)</div>
  {domain_bars}
</div>
"""

    # Filter bar
    filter_bar = f"""
<div class="filter-bar">
  <label>Filter by severity:</label>
  <button class="filter-btn active" data-severity="ALL">All</button>
  <button class="filter-btn active" data-severity="CRITICAL">Critical ({severity_counts.get('CRITICAL', 0)})</button>
  <button class="filter-btn active" data-severity="HIGH">High ({severity_counts.get('HIGH', 0)})</button>
  <button class="filter-btn active" data-severity="WARNING">Warning ({severity_counts.get('WARNING', 0)})</button>
  <button class="filter-btn active" data-severity="PASS">Pass ({severity_counts.get('PASS', 0)})</button>
  <button class="filter-btn active" data-severity="INFO">Info ({severity_counts.get('INFO', 0)})</button>
  <span class="filter-count" id="filter-count">{total_findings} of {total_findings} findings shown</span>
</div>
"""

    # --- Assemble full HTML document ---
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_escape_html(title)}</title>
<style>
{theme_css}
{_COMMON_CSS}
</style>
</head>
<body>
<header>
  <div class="container">
    <h1>{_escape_html(title)}</h1>
    <div class="subtitle">Comprehensive EMC, Signal Integrity &amp; DFM Analysis</div>
    <div class="meta">Session: {_escape_html(session_id)} | Generated: {now} | MCP PCB EMCopilot</div>
  </div>
</header>

<main class="container">
  <h2>Executive Summary</h2>
  {summary_cards}
  {filter_bar}
  {"".join(sections_html)}
</main>

<footer>
  <div class="container">
    <p>Generated by MCP PCB EMCopilot</p>
    <p>{_escape_html(title)} | {now}</p>
  </div>
</footer>

<script>
{_JS}
</script>
</body>
</html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return os.path.abspath(output_path)

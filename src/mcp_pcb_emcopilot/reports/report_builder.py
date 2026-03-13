"""ReportBuilder — session harvesting and document assembly.

Collects analysis results from review_results and analysis_cache,
constructs TrackedFinding objects with traceability, builds fixed-order
report sections (skipping empty ones), and outputs DOCX + HTML.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any, Optional

from ..models.pcb_data import PCBDesignData
from .section_registry import REPORT_SECTIONS, SectionDef
from .tracked_finding import TrackedFinding

# ---------------------------------------------------------------------------
# Domain key → finding-ID prefix mapping
# ---------------------------------------------------------------------------

_DOMAIN_PREFIXES: dict[str, str] = {
    "emc": "EMC",
    "signal_integrity": "SI",
    "high_speed": "HS",
    "power_integrity": "PI",
    "return_path": "RP",
    "thermal": "TH",
    "dfm": "DFM",
    "esd": "ESD",
    "impedance": "IMP",
    "grounding": "GND",
    "shielding": "SHD",
    "antenna": "ANT",
    "immunity": "IMM",
    "emi_filtering": "FLT",
    "automotive_emc": "AUT",
    "stackup": "STK",
    "stackup_optimization": "STO",
    "net_classification": "NET",
    "schematic_overview": "SCH",
    "cross_reference": "XRF",
    "design_rules": "DRU",
    "drill_table": "DRL",
    "test_plan": "TST",
}


def _prefix_for(domain: str) -> str:
    """Return the finding-ID prefix for *domain*, falling back to first 3 chars."""
    return _DOMAIN_PREFIXES.get(domain, domain[:3].upper() or "GEN")


# ---------------------------------------------------------------------------
# Section key → domain mapping (for matching harvested data to sections)
# ---------------------------------------------------------------------------

_SECTION_DOMAIN_MAP: dict[str, list[str]] = {
    "stackup": ["pcb_get_stackup"],
    "schematic_overview": ["pcb_parse_schematic_pdf"],
    "cross_reference": ["pcb_cross_reference_schematic"],
    "net_classification": ["pcb_classify_nets", "pcb_detect_interfaces"],
    "impedance": [
        "pcb_calc_microstrip_impedance", "pcb_calc_stripline_impedance",
        "pcb_calc_differential_impedance", "pcb_calc_cpw_impedance",
    ],
    "signal_integrity": [
        "pcb_calc_eye_diagram", "pcb_calc_ibis_eye",
        "pcb_analyze_mode_conversion", "pcb_analyze_crosstalk",
        "pcb_analyze_differential_pair", "pcb_analyze_length_matching",
    ],
    "high_speed": [
        "pcb_analyze_ddr", "pcb_analyze_usb", "pcb_analyze_pcie",
        "pcb_analyze_ethernet", "pcb_validate_ddr_topology",
        "pcb_validate_pcie_lanes", "pcb_analyze_ddr_timing_budget",
        "pcb_calc_pcie_link_budget",
    ],
    "emc": [
        "pcb_analyze_clock_emi", "pcb_analyze_emi_risk",
        "pcb_analyze_smps_emi", "pcb_analyze_conducted_emissions",
        "pcb_analyze_near_field", "pcb_predict_emissions",
        "pcb_get_emi_hotspots",
    ],
    "emi_filtering": ["pcb_design_emi_filter"],
    "automotive_emc": ["pcb_analyze_automotive_emc"],
    "esd": ["pcb_analyze_esd"],
    "immunity": ["pcb_analyze_immunity_margin"],
    "power_integrity": [
        "pcb_analyze_pdn", "pcb_analyze_vrm", "pcb_analyze_decoupling",
        "pcb_calc_plane_resonance", "pcb_calc_pdn_impedance",
    ],
    "return_path": [
        "pcb_visualize_return_path", "pcb_find_split_crossings",
        "pcb_trace_return_path", "pcb_analyze_return_paths",
        "pcb_analyze_return_current", "pcb_analyze_return_current_density",
    ],
    "antenna": [
        "pcb_analyze_trace_antenna", "pcb_analyze_slot_antenna",
        "pcb_analyze_common_mode", "pcb_analyze_cable_coupling",
    ],
    "thermal": [
        "pcb_analyze_thermal", "pcb_analyze_thermal_via",
        "pcb_analyze_copper_spreading",
    ],
    "dfm": [
        "pcb_analyze_solder_paste", "pcb_analyze_placement",
        "pcb_analyze_assembly",
    ],
    "stackup_optimization": ["pcb_optimize_stackup"],
    "shielding": ["pcb_analyze_shielding"],
    "grounding": ["pcb_analyze_grounding", "pcb_analyze_ground_stitch"],
    "test_plan": ["pcb_generate_test_plan"],
    "design_rules": ["pcb_get_design_rules"],
    "drill_table": ["pcb_get_drill_table", "pcb_analyze_via"],
}


# ---------------------------------------------------------------------------
# Glossary terms
# ---------------------------------------------------------------------------

_GLOSSARY: list[tuple[str, str]] = [
    ("EMC", "Electromagnetic Compatibility"),
    ("EMI", "Electromagnetic Interference"),
    ("ESD", "Electrostatic Discharge"),
    ("SI", "Signal Integrity"),
    ("PI", "Power Integrity"),
    ("PDN", "Power Distribution Network"),
    ("DDR", "Double Data Rate (memory interface)"),
    ("PCIe", "Peripheral Component Interconnect Express"),
    ("USB", "Universal Serial Bus"),
    ("DFM", "Design for Manufacturing"),
    ("DRC", "Design Rule Check"),
    ("BGA", "Ball Grid Array"),
    ("VRM", "Voltage Regulator Module"),
    ("SMPS", "Switched-Mode Power Supply"),
    ("CISPR", "Comite International Special des Perturbations Radioelectriques"),
    ("FCC", "Federal Communications Commission"),
    ("IEC", "International Electrotechnical Commission"),
    ("dBuV/m", "Decibels referenced to one microvolt per metre"),
    ("Zo", "Characteristic impedance"),
    ("Dk", "Dielectric constant (relative permittivity)"),
    ("Df", "Dissipation factor (loss tangent)"),
]


# ---------------------------------------------------------------------------
# ReportBuilder
# ---------------------------------------------------------------------------

class ReportBuilder:
    """Build a comprehensive PCB design review report.

    Harvests analysis results from the session (review_results + analysis_cache),
    constructs TrackedFinding objects, builds fixed-order report sections
    (skipping empty ones), and outputs DOCX and/or HTML.
    """

    def __init__(
        self,
        design: PCBDesignData,
        title: Optional[str] = None,
        confidentiality: str = "CONFIDENTIAL",
        output_dir: str = "/tmp/pcb_reports",
        auto_render: bool = True,
    ) -> None:
        self.design = design
        self.title = title or f"Design Review — {design.title or design.source_file}"
        self.confidentiality = confidentiality
        self.output_dir = output_dir
        self.auto_render = auto_render

        os.makedirs(self.output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, format: str = "both") -> dict:
        """Generate the report and return metadata.

        Args:
            format: ``"docx"``, ``"html"``, or ``"both"``.

        Returns:
            Dict with keys: docx_path, html_path, file_size_kb,
            sections_generated, sections_skipped, findings_count,
            plots_generated, renders_generated, overall_verdict.
        """
        results = self._harvest_session()
        all_findings = self._collect_findings(results)
        verdict = self._determine_verdict(all_findings)
        counts = self._count_findings(all_findings)

        out: dict[str, Any] = {
            "docx_path": None,
            "html_path": None,
            "file_size_kb": 0,
            "sections_generated": 0,
            "sections_skipped": 0,
            "findings_count": counts,
            "plots_generated": 0,
            "renders_generated": 0,
            "overall_verdict": verdict,
        }

        if format in ("docx", "both"):
            docx_path, sg, ss = self._build_docx(results, all_findings, verdict)
            out["docx_path"] = docx_path
            out["sections_generated"] = sg
            out["sections_skipped"] = ss
            out["file_size_kb"] = round(os.path.getsize(docx_path) / 1024, 1)

        if format in ("html", "both"):
            html_path = self._build_html(results, all_findings, verdict)
            out["html_path"] = html_path
            if out["docx_path"] is None:
                # Only HTML — report HTML size
                out["file_size_kb"] = round(os.path.getsize(html_path) / 1024, 1)
                # Count sections for HTML-only mode
                out["sections_generated"] = self._count_html_sections(results)

        return out

    # ------------------------------------------------------------------
    # Session harvesting
    # ------------------------------------------------------------------

    def _harvest_session(self) -> dict[str, Any]:
        """Collect review_results['domains'] + analysis_cache into one dict."""
        harvested: dict[str, Any] = {}

        # 1. review_results["domains"]
        rr = self.design.review_results or {}
        domains = rr.get("domains", {})
        for domain_key, domain_data in domains.items():
            harvested[domain_key] = domain_data

        # 2. analysis_cache (keyed by tool name)
        for tool_name, tool_data in (self.design.analysis_cache or {}).items():
            harvested[tool_name] = tool_data

        return harvested

    # ------------------------------------------------------------------
    # Finding construction
    # ------------------------------------------------------------------

    def _collect_findings(self, results: dict) -> list[TrackedFinding]:
        """Convert raw finding dicts to TrackedFinding objects."""
        findings: list[TrackedFinding] = []
        domain_counters: dict[str, int] = {}

        # Walk review_results domains
        rr = self.design.review_results or {}
        domains = rr.get("domains", {})
        for domain_key, domain_data in domains.items():
            prefix = _prefix_for(domain_key)
            for raw in domain_data.get("findings", []):
                count = domain_counters.get(prefix, 0) + 1
                domain_counters[prefix] = count
                finding_id = f"{prefix}-{count:03d}"

                findings.append(TrackedFinding(
                    finding_id=finding_id,
                    severity=raw.get("severity", "INFO"),
                    domain=domain_key,
                    title=raw.get("title", "Untitled finding"),
                    what_it_means=raw.get("detail", ""),
                    how_calculated=raw.get("how_calculated", "Automated analysis"),
                    physical_mechanism=raw.get("physical_mechanism", ""),
                    measured_value=str(raw.get("measured_value", "")),
                    limit_value=str(raw.get("limit_value", "")),
                    margin=str(raw.get("margin", "")),
                    recommendation=raw.get("recommendation", ""),
                    reference_standard=raw.get("reference_standard", ""),
                    nets=raw.get("nets", []),
                    layers=raw.get("layers", []),
                    components=raw.get("components", []),
                    coordinates_mm=raw.get("coordinates_mm", []),
                ))

        # Walk analysis_cache entries
        for tool_name, tool_data in (self.design.analysis_cache or {}).items():
            if not isinstance(tool_data, dict):
                continue
            for raw in tool_data.get("findings", []):
                domain_key = tool_name.replace("pcb_analyze_", "").replace("pcb_", "")
                prefix = _prefix_for(domain_key)
                count = domain_counters.get(prefix, 0) + 1
                domain_counters[prefix] = count
                finding_id = f"{prefix}-{count:03d}"

                findings.append(TrackedFinding(
                    finding_id=finding_id,
                    severity=raw.get("severity", "INFO"),
                    domain=domain_key,
                    title=raw.get("title", "Untitled finding"),
                    what_it_means=raw.get("detail", ""),
                    how_calculated=raw.get("how_calculated", "Automated analysis"),
                    physical_mechanism=raw.get("physical_mechanism", ""),
                    measured_value=str(raw.get("measured_value", "")),
                    limit_value=str(raw.get("limit_value", "")),
                    margin=str(raw.get("margin", "")),
                    recommendation=raw.get("recommendation", ""),
                    reference_standard=raw.get("reference_standard", ""),
                    nets=raw.get("nets", []),
                    layers=raw.get("layers", []),
                    components=raw.get("components", []),
                    coordinates_mm=raw.get("coordinates_mm", []),
                ))

        return findings

    # ------------------------------------------------------------------
    # Verdict logic
    # ------------------------------------------------------------------

    def _determine_verdict(self, findings: list[TrackedFinding]) -> str:
        """Determine overall report verdict from severity distribution."""
        severities = {f.severity for f in findings}
        if "CRITICAL" in severities:
            return "CRITICAL \u2014 Remediation Required Before Prototype"
        if "HIGH" in severities:
            return "CONDITIONAL \u2014 Proceed with Caution, Address HIGH Items"
        if "WARNING" in severities:
            return "PASS WITH WARNINGS \u2014 Review Recommended Items"
        return "PASS \u2014 Ready for Prototype"

    # ------------------------------------------------------------------
    # Counts
    # ------------------------------------------------------------------

    def _count_findings(self, findings: list[TrackedFinding]) -> dict[str, int]:
        """Return finding counts by severity."""
        counts = {"critical": 0, "high": 0, "warning": 0, "info": 0, "pass": 0}
        for f in findings:
            key = f.severity.lower()
            if key in counts:
                counts[key] += 1
        return counts

    # ------------------------------------------------------------------
    # DOCX generation
    # ------------------------------------------------------------------

    def _build_docx(
        self,
        results: dict,
        all_findings: list[TrackedFinding],
        verdict: str,
    ) -> tuple[str, int, int]:
        """Assemble DOCX report. Returns (path, sections_generated, sections_skipped)."""
        from .docx_report import _check_docx, add_finding_box, add_image_with_caption, add_styled_table
        _check_docx()
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Inches, Pt, RGBColor

        doc = Document()

        # Page setup
        section = doc.sections[0]
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.9)
        section.right_margin = Inches(0.9)

        style = doc.styles["Normal"]
        style.font.name = "Calibri"
        style.font.size = Pt(10)

        # ---- Cover page ----
        self._build_cover_page(doc, verdict)

        # ---- TOC placeholder ----
        doc.add_heading("Table of Contents", level=1)
        p = doc.add_paragraph(
            "[Table of contents — update field in Word after opening]"
        )
        p.runs[0].font.size = Pt(9)
        p.runs[0].font.italic = True
        p.runs[0].font.color.rgb = RGBColor(0x99, 0x99, 0x99)
        doc.add_page_break()

        # ---- Iterate report sections ----
        sections_generated = 0
        sections_skipped = 0

        for sect in REPORT_SECTIONS:
            if sect.required:
                # Always build required sections
                self._build_section(doc, sect, results, all_findings, verdict)
                sections_generated += 1
            else:
                # Only build if we have matching data
                if self._has_data_for_section(sect, results):
                    self._build_section(doc, sect, results, all_findings, verdict)
                    sections_generated += 1
                else:
                    sections_skipped += 1

        # ---- Footer ----
        doc.add_paragraph()
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run("\u2014 End of Report \u2014")
        run.font.size = Pt(10)
        run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
        run.italic = True

        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run("Generated by MCP PCB EMCopilot")
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

        # Save
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = self.title.replace(" ", "_").replace("/", "_")[:40]
        filename = f"{safe_title}_{timestamp}.docx"
        output_path = os.path.join(self.output_dir, filename)
        doc.save(output_path)

        return os.path.abspath(output_path), sections_generated, sections_skipped

    # ------------------------------------------------------------------
    # HTML generation
    # ------------------------------------------------------------------

    def _build_html(
        self,
        results: dict,
        all_findings: list[TrackedFinding],
        verdict: str,
    ) -> str:
        """Wrap existing generate_html_report() and return path."""
        from .html_report import generate_html_report

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = self.title.replace(" ", "_").replace("/", "_")[:40]
        filename = f"{safe_title}_{timestamp}.html"
        output_path = os.path.join(self.output_dir, filename)

        session_id = f"report_{timestamp}"
        return generate_html_report(
            design=self.design,
            session_id=session_id,
            output_path=output_path,
            title=self.title,
            theme="light",
        )

    # ------------------------------------------------------------------
    # Section count helper for HTML-only mode
    # ------------------------------------------------------------------

    def _count_html_sections(self, results: dict) -> int:
        """Count how many sections would be generated."""
        count = 0
        for sect in REPORT_SECTIONS:
            if sect.required or self._has_data_for_section(sect, results):
                count += 1
        return count

    # ------------------------------------------------------------------
    # Cover page
    # ------------------------------------------------------------------

    def _build_cover_page(self, doc: Any, verdict: str) -> None:
        """Add a professional cover page."""
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Inches, Pt, RGBColor

        for _ in range(5):
            doc.add_paragraph()

        # Title
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(self.title)
        run.font.size = Pt(28)
        run.bold = True
        run.font.color.rgb = RGBColor(0x1F, 0x4E, 0x79)

        # Subtitle
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run("Comprehensive EMC, Signal Integrity & DFM Analysis")
        run.font.size = Pt(14)
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

        doc.add_paragraph()

        # Confidentiality
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(self.confidentiality)
        run.font.size = Pt(12)
        run.bold = True
        if self.confidentiality == "CONFIDENTIAL":
            run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
        else:
            run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

        for _ in range(3):
            doc.add_paragraph()

        # Cover info table
        board_w = self.design.board_width_mm or 0
        board_h = self.design.board_height_mm or 0
        layer_count = len(self.design.layers) if self.design.layers else 0
        now_str = datetime.now().strftime("%Y-%m-%d")

        cover_data = [
            ("Date", now_str),
            ("Board", self.design.title or self.design.source_file),
            ("Board Size", f"{board_w:.1f} \u00d7 {board_h:.1f} mm"),
            ("Layers", str(layer_count)),
            ("Components", str(len(self.design.components))),
            ("Nets", str(len(self.design.nets))),
            ("Verdict", verdict),
            ("Tool", "MCP PCB EMCopilot"),
        ]

        table = doc.add_table(rows=len(cover_data), cols=2)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, (label, value) in enumerate(cover_data):
            row = table.rows[i]
            row.cells[0].text = ""
            row.cells[1].text = ""
            p0 = row.cells[0].paragraphs[0]
            run = p0.add_run(label)
            run.bold = True
            run.font.size = Pt(10)
            p0.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p1 = row.cells[1].paragraphs[0]
            run = p1.add_run(value)
            run.font.size = Pt(10)
            row.cells[0].width = Inches(2.0)
            row.cells[1].width = Inches(4.5)

        doc.add_page_break()

    # ------------------------------------------------------------------
    # Data availability check
    # ------------------------------------------------------------------

    def _has_data_for_section(self, sect: SectionDef, results: dict) -> bool:
        """Check whether we have data relevant to this section."""
        # Check review_results domains
        key = sect.key
        if key in results:
            return True

        # Check analysis_cache tool names mapped to this section
        tool_names = _SECTION_DOMAIN_MAP.get(key, [])
        for tool in tool_names:
            if tool in results:
                return True

        # Special cases: check design data
        if key == "stackup" and self.design.layers:
            return True
        if key == "drill_table" and (self.design.vias or self.design.drill_table):
            return True
        if key == "design_rules" and self.design.design_rules:
            return True

        return False

    # ------------------------------------------------------------------
    # Generic section dispatcher
    # ------------------------------------------------------------------

    def _build_section(
        self,
        doc: Any,
        sect: SectionDef,
        results: dict,
        all_findings: list[TrackedFinding],
        verdict: str,
    ) -> None:
        """Dispatch to the correct section builder."""
        builders = {
            "executive_summary": self._build_executive_summary,
            "board_overview": self._build_board_overview,
            "action_items": self._build_action_items,
            "tool_coverage": self._build_tool_coverage,
            "glossary": self._build_glossary,
            "references": self._build_references,
            "appendices": self._build_appendices,
        }

        builder = builders.get(sect.key)
        if builder:
            builder(doc, sect, results, all_findings, verdict)
        else:
            self._build_domain_section(doc, sect, results, all_findings)

    # ------------------------------------------------------------------
    # Required section builders
    # ------------------------------------------------------------------

    def _build_executive_summary(
        self, doc: Any, sect: SectionDef, results: dict,
        all_findings: list[TrackedFinding], verdict: str,
    ) -> None:
        from docx.shared import Pt, RGBColor

        from .docx_report import add_finding_box, add_styled_table

        doc.add_heading(f"{sect.number}. {sect.title}", level=1)

        # Verdict
        p = doc.add_paragraph()
        run = p.add_run(f"Overall Verdict: {verdict}")
        run.bold = True
        run.font.size = Pt(12)
        if "CRITICAL" in verdict:
            run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
        elif "CONDITIONAL" in verdict:
            run.font.color.rgb = RGBColor(0xE6, 0x5C, 0x00)
        elif "WARNINGS" in verdict:
            run.font.color.rgb = RGBColor(0x7F, 0x60, 0x00)
        else:
            run.font.color.rgb = RGBColor(0x1B, 0x5E, 0x20)

        counts = self._count_findings(all_findings)
        summary_rows = [
            ("Total Findings", str(sum(counts.values()))),
            ("Critical", str(counts["critical"])),
            ("High", str(counts["high"])),
            ("Warning", str(counts["warning"])),
            ("Info", str(counts["info"])),
            ("Pass", str(counts["pass"])),
            ("Domains Analyzed", str(len(results))),
        ]
        add_styled_table(doc, ["Metric", "Value"], summary_rows, col_widths=[3.0, 3.5])

        # Top critical/high findings
        critical_high = [f for f in all_findings if f.severity in ("CRITICAL", "HIGH")]
        if critical_high:
            doc.add_paragraph()
            p = doc.add_paragraph()
            run = p.add_run("Key Findings Requiring Attention:")
            run.bold = True
            run.font.size = Pt(10)
            for tf in critical_high[:5]:
                add_finding_box(doc, tf.severity, f"[{tf.finding_id}] {tf.title}",
                                tf.what_it_means, tf.recommendation)

        doc.add_page_break()

    def _build_board_overview(
        self, doc: Any, sect: SectionDef, results: dict,
        all_findings: list[TrackedFinding], verdict: str,
    ) -> None:
        from .docx_report import add_styled_table

        doc.add_heading(f"{sect.number}. {sect.title}", level=1)

        board_w = self.design.board_width_mm or 0
        board_h = self.design.board_height_mm or 0
        layer_count = len(self.design.layers) if self.design.layers else 0

        overview_rows = [
            ("Source File", self.design.source_file),
            ("Format", self.design.source_format),
            ("Board Size", f"{board_w:.1f} \u00d7 {board_h:.1f} mm ({board_w * board_h:.0f} mm\u00b2)"),
            ("Thickness", f"{self.design.board_thickness_mm:.2f} mm"),
            ("Layer Count", str(layer_count)),
            ("Components", str(len(self.design.components))),
            ("Nets", str(len(self.design.nets))),
            ("Traces", str(len(self.design.traces))),
            ("Vias", str(len(self.design.vias))),
            ("Zones", str(len(self.design.zones))),
        ]
        add_styled_table(doc, ["Parameter", "Value"], overview_rows, col_widths=[2.5, 4.0])

        # Layer summary
        if self.design.layers:
            doc.add_paragraph()
            doc.add_heading("Layer Stackup Summary", level=2)
            layer_rows = []
            for ly in self.design.layers:
                layer_rows.append((
                    str(ly.number),
                    ly.name,
                    ly.layer_type,
                    f"{ly.thickness_mm:.3f}" if ly.thickness_mm else "\u2014",
                    ly.material or "\u2014",
                ))
            add_styled_table(
                doc,
                ["#", "Name", "Type", "Thickness (mm)", "Material"],
                layer_rows,
                col_widths=[0.5, 1.5, 1.2, 1.5, 1.8],
            )

        doc.add_page_break()

    def _build_action_items(
        self, doc: Any, sect: SectionDef, results: dict,
        all_findings: list[TrackedFinding], verdict: str,
    ) -> None:
        from .docx_report import add_styled_table

        doc.add_heading(f"{sect.number}. {sect.title}", level=1)
        doc.add_paragraph(
            "The following items are prioritised by severity. "
            "Critical and High findings should be addressed before prototype fabrication."
        )

        # Sort: CRITICAL first, then HIGH, WARNING, INFO, PASS
        severity_order = {"CRITICAL": 0, "HIGH": 1, "WARNING": 2, "INFO": 3, "PASS": 4}
        actionable = sorted(all_findings, key=lambda f: severity_order.get(f.severity, 5))

        if actionable:
            rows = []
            for tf in actionable:
                rows.append((
                    tf.finding_id,
                    tf.severity,
                    tf.title,
                    tf.recommendation or "\u2014",
                ))
            add_styled_table(
                doc,
                ["ID", "Severity", "Finding", "Recommendation"],
                rows,
                col_widths=[1.0, 1.0, 2.5, 2.5],
            )
        else:
            doc.add_paragraph("No findings to report. The design appears clean.")

        doc.add_page_break()

    def _build_tool_coverage(
        self, doc: Any, sect: SectionDef, results: dict,
        all_findings: list[TrackedFinding], verdict: str,
    ) -> None:
        from .docx_report import add_styled_table

        doc.add_heading(f"{sect.number}. {sect.title}", level=1)
        doc.add_paragraph(
            "This section documents which analysis tools were invoked during the review "
            "and their coverage status."
        )

        rows = []
        for s in REPORT_SECTIONS:
            if s.source_tools:
                ran_tools = []
                for t in s.source_tools:
                    if t in (self.design.analysis_cache or {}):
                        ran_tools.append(t)
                status = "Ran" if ran_tools else "Not run"
                tool_list = ", ".join(s.source_tools[:3])
                if len(s.source_tools) > 3:
                    tool_list += f" (+{len(s.source_tools) - 3} more)"
                rows.append((s.title, tool_list, status))

        if rows:
            add_styled_table(
                doc,
                ["Section", "Tools", "Status"],
                rows,
                col_widths=[2.0, 3.0, 1.0],
            )
        else:
            doc.add_paragraph("No tool-specific sections defined.")

        doc.add_page_break()

    def _build_glossary(
        self, doc: Any, sect: SectionDef, results: dict,
        all_findings: list[TrackedFinding], verdict: str,
    ) -> None:
        from .docx_report import add_styled_table

        doc.add_heading(f"{sect.number}. {sect.title}", level=1)
        add_styled_table(
            doc,
            ["Abbreviation", "Definition"],
            _GLOSSARY,
            col_widths=[1.5, 5.0],
        )

    def _build_references(
        self, doc: Any, sect: SectionDef, results: dict,
        all_findings: list[TrackedFinding], verdict: str,
    ) -> None:
        from docx.shared import Pt

        doc.add_heading(f"{sect.number}. {sect.title}", level=1)

        references = [
            "IPC-2221B \u2014 Generic Standard on Printed Board Design",
            "IPC-2152 \u2014 Standard for Determining Current-Carrying Capacity in Printed Board Design",
            "CISPR 32 \u2014 Electromagnetic Compatibility of Multimedia Equipment \u2014 Emission Requirements",
            "CISPR 25 \u2014 Vehicles, Boats and Internal Combustion Engines \u2014 Radio Disturbance Characteristics",
            "FCC Part 15 \u2014 Radio Frequency Devices",
            "IEC 61000-4-2 \u2014 Electrostatic Discharge Immunity Test",
            "IEC 61000-4-3 \u2014 Radiated, Radio-Frequency, Electromagnetic Field Immunity Test",
            "JEDEC JESD79-4 \u2014 DDR4 SDRAM Standard",
            "PCI Express Base Specification \u2014 Revision 5.0/6.0",
            "USB 3.2/4.0 Specification",
            "Henry Ott, Electromagnetic Compatibility Engineering, Wiley, 2009",
            "Eric Bogatin, Signal and Power Integrity \u2014 Simplified, Prentice Hall, 2010",
        ]
        for ref in references:
            p = doc.add_paragraph(ref, style="List Bullet")
            for run in p.runs:
                run.font.size = Pt(9)

    def _build_appendices(
        self, doc: Any, sect: SectionDef, results: dict,
        all_findings: list[TrackedFinding], verdict: str,
    ) -> None:
        from docx.shared import Pt, RGBColor

        doc.add_heading(f"{sect.number}. {sect.title}", level=1)

        # Appendix A: Finding detail
        doc.add_heading("A. Complete Finding Catalogue", level=2)
        if all_findings:
            from .docx_report import add_finding_box
            for tf in all_findings:
                detail = tf.what_it_means
                if tf.measured_value:
                    detail += f"\nMeasured: {tf.measured_value}"
                if tf.limit_value:
                    detail += f" | Limit: {tf.limit_value}"
                if tf.margin:
                    detail += f" | Margin: {tf.margin}"
                add_finding_box(
                    doc, tf.severity,
                    f"[{tf.finding_id}] {tf.title}",
                    detail,
                    tf.recommendation,
                )
        else:
            p = doc.add_paragraph("No findings recorded.")
            p.runs[0].font.size = Pt(9)
            p.runs[0].font.color.rgb = RGBColor(0x99, 0x99, 0x99)

        # Appendix B: Report metadata
        doc.add_heading("B. Report Metadata", level=2)
        p = doc.add_paragraph(
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Tool: MCP PCB EMCopilot\n"
            f"Confidentiality: {self.confidentiality}"
        )
        for run in p.runs:
            run.font.size = Pt(9)

    # ------------------------------------------------------------------
    # Domain section builder (generic)
    # ------------------------------------------------------------------

    def _build_domain_section(
        self,
        doc: Any,
        sect: SectionDef,
        results: dict,
        all_findings: list[TrackedFinding],
    ) -> None:
        """Build a domain-specific section with data tables and findings."""
        from docx.shared import Pt

        from .docx_report import add_finding_box, add_styled_table

        doc.add_heading(f"{sect.number}. {sect.title}", level=1)

        # Gather domain data
        domain_data = results.get(sect.key, {})
        if isinstance(domain_data, dict):
            status = domain_data.get("status", "")
            score = domain_data.get("score")
            if status:
                p = doc.add_paragraph()
                run = p.add_run(f"Status: {status}")
                run.bold = True
                run.font.size = Pt(10)
                if score is not None:
                    run = p.add_run(f"  (Score: {score}/100)")
                    run.font.size = Pt(10)

        # Gather tool data for this section
        tool_names = _SECTION_DOMAIN_MAP.get(sect.key, [])
        tool_results = {}
        for tool in tool_names:
            if tool in results:
                tool_results[tool] = results[tool]

        # Emit tool result summaries as tables
        for tool_name, tdata in tool_results.items():
            if not isinstance(tdata, dict):
                continue
            doc.add_heading(tool_name.replace("pcb_", "").replace("_", " ").title(), level=2)

            # Extract top-level scalar key/value pairs for a summary table
            summary_rows = []
            for k, v in tdata.items():
                if k == "findings":
                    continue
                if isinstance(v, (str, int, float, bool)):
                    summary_rows.append((k.replace("_", " ").title(), str(v)))
            if summary_rows:
                add_styled_table(doc, ["Parameter", "Value"], summary_rows,
                                 col_widths=[3.0, 3.5])

        # Emit findings for this domain
        domain_findings = [
            f for f in all_findings
            if f.domain == sect.key or f.domain in [
                t.replace("pcb_analyze_", "").replace("pcb_", "")
                for t in tool_names
            ]
        ]
        if domain_findings:
            doc.add_paragraph()
            doc.add_heading("Findings", level=2)
            for tf in domain_findings:
                add_finding_box(
                    doc, tf.severity,
                    f"[{tf.finding_id}] {tf.title}",
                    tf.what_it_means,
                    tf.recommendation,
                )

        doc.add_page_break()

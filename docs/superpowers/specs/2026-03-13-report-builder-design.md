# Generalized PCB Design Review Report Builder — Design Spec

**Goal:** Replace the one-off `generate_docx_report.py` script with a reusable, project-agnostic MCP tool that generates professional DOCX and HTML design review reports from any PCB design session.

**Architecture:** A `ReportBuilder` class harvests analysis results from the current session, constructs traceable findings via a `TrackedFinding` dataclass, builds 30 fixed-order sections (skipping empty ones), auto-generates simulation plots and board renders for findings missing visuals, and outputs DOCX + HTML using existing report helpers. One new MCP tool exposes this to the user.

**Tech Stack:** Python, python-docx (existing dep), existing `docx_report.py` / `html_report.py` / `simulation_plots.py` helpers.

---

## 1. Problem Statement

The current report generation is a hardcoded script (`generate_docx_report.py`) specific to the Trimble Porpoise design. It has several shortcomings:

- **Not reusable** — every new project requires rewriting the script
- **Not traceable** — findings say "a 31 mm trace" without specifying which net, layer, or components
- **Not explanatory** — reports show numbers without explaining what they mean, how they were calculated, or the physical mechanism
- **Not integrated** — exists outside the MCP server as a standalone script
- **Not automated** — requires manual assembly of analysis results

## 2. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Data source | Session-based (primary) + optional orchestration | AI naturally runs analyses during review; harvest those results |
| Output formats | DOCX + HTML | DOCX for formal delivery, HTML for quick preview; PDF via Word export |
| Report structure | Fixed sections, skip empty | Consistent structure across reports; readers know where to find things |
| Generation | Server-side file output | Self-contained, returns file path, works everywhere |
| Images | Auto-render + reuse session cache | Reuse existing renders (fast), auto-fill gaps (complete) |
| Approach | ReportBuilder module | Single class, reuses existing helpers, pragmatic |

## 2.1 Session Result Accumulation

Individual MCP tool calls (e.g., `pcb_analyze_crosstalk`) return results directly to the AI client but do **not** currently store them back into the session. Only `pcb_run_design_review` (the orchestrator) populates `design.review_results`.

To support session-based harvesting, the implementation must add an `analysis_cache: dict[str, Any]` field to `PCBDesignData`. Each analysis tool handler in `server.py` will append its result to `design.analysis_cache[tool_name]` before returning it. This is a small change per handler (one line: `data.analysis_cache[name] = result`).

The `ReportBuilder._harvest_session()` method will:
1. Check `design.review_results` first (from orchestrator)
2. Fall back to `design.analysis_cache` (from individual tool calls)
3. Merge both sources, with orchestrator results taking precedence

When `run_analysis=true`, the tool calls `run_design_review()` which overwrites `design.review_results`. Any existing `analysis_cache` entries are preserved as supplemental data.

## 2.2 Overall Verdict Logic

The overall verdict is determined by the highest-severity finding:

| Condition | Verdict |
|-----------|---------|
| Any CRITICAL finding | `"CRITICAL — Remediation Required Before Prototype"` |
| Any HIGH finding (no CRITICAL) | `"CONDITIONAL — Proceed with Caution, Address HIGH Items"` |
| Any WARNING finding (no HIGH/CRITICAL) | `"PASS WITH WARNINGS — Review Recommended Items"` |
| Only INFO/PASS findings | `"PASS — Ready for Prototype"` |

## 3. Finding Traceability Model

Every finding is built from a `TrackedFinding` dataclass that enforces traceability:

```python
@dataclass
class TrackedFinding:
    # Identity
    finding_id: str              # "EMC-001", "SI-003", etc.
    severity: str                # CRITICAL / HIGH / WARNING / INFO / PASS
    domain: str                  # "emc", "signal_integrity", "power", etc.
    title: str                   # Short title for finding box

    # Traceability
    nets: list[str]              # ["WiFi_2.4GHz", "CLK_100M"]
    layers: list[str]            # ["L1", "L2"]
    components: list[str]        # ["U12 (WiFi SoC)", "J8 (antenna connector)"]
    coordinates_mm: list[tuple]  # [(x1,y1), (x2,y2)] board coordinates
    trace_length_mm: float | None

    # Explanation
    what_it_means: str           # Plain-English explanation of the metric
    how_calculated: str          # Brief methodology description
    physical_mechanism: str      # Why this matters physically

    # Data
    measured_value: str          # "31.2 mm trace, 0.032 coupling coefficient"
    limit_value: str             # "λ/4 = 31.25 mm at 2.4 GHz"
    margin: str                  # "-0.05 mm (resonant match)"

    # Action
    recommendation: str          # Specific fix with component values
    reference_standard: str      # "IEC 61000-4-2 Level 4"

    # Visuals
    plot_path: str | None        # Simulation plot PNG
    render_path: str | None      # Board/net render PNG
```

### Example — Trace Antenna Finding

```
finding_id: "ANT-001"
severity: "WARNING"
title: "Trace resonant at 2.4 GHz WiFi band"
nets: ["WiFi_2.4GHz"]
layers: ["L1"]
components: ["U12 (WiFi SoC, pin RF_OUT)", "J8 (antenna connector, pin 1)"]
trace_length_mm: 31.2
what_it_means: "This trace is electrically a quarter-wave antenna at 2.4 GHz,
    meaning it efficiently radiates and receives energy at WiFi frequencies."
how_calculated: "Quarter-wave resonance: f = c / (4 × L × √εr_eff).
    For L=31.2mm, εr_eff=3.02: f = 2.42 GHz."
physical_mechanism: "A trace whose length matches λ/4 acts as a monopole
    antenna. It couples radiated energy into the WiFi receive path,
    degrading sensitivity, and radiates clock/digital noise outward."
measured_value: "31.2 mm routed length on L1 microstrip"
limit_value: "λ/4 at 2.4 GHz = 31.25 mm (εr_eff=3.02)"
margin: "-0.05 mm (exact resonant match)"
recommendation: "Route on inner layer L3 with continuous L2 GND reference,
    or add ground stitching vias at ≤3 mm spacing on both sides."
reference_standard: "FCC Part 15.109, CISPR 32"
```

## 4. Report Sections (Fixed Order)

| # | Section | Source Analyzers | Skippable |
|---|---------|-----------------|-----------|
| 1 | Executive Summary | All (aggregated) | No |
| 2 | Board Overview & Layout | `pcb_parse_layout`, `pcb_get_board_outline` | No |
| 3 | Layer Stackup | `pcb_get_stackup` | Yes |
| 4 | Schematic Overview | `pcb_parse_schematic_pdf` | Yes |
| 5 | Component Cross-Reference | `pcb_cross_reference_schematic` | Yes |
| 6 | Net Classification | `pcb_classify_nets`, `pcb_detect_interfaces` | Yes |
| 7 | Impedance Analysis | `pcb_calc_microstrip_impedance`, `pcb_calc_stripline_impedance`, `pcb_calc_differential_impedance`, `pcb_calc_cpw_impedance` | Yes |
| 8 | Signal Integrity | `pcb_calc_eye_diagram`, `pcb_calc_ibis_eye`, `pcb_analyze_mode_conversion`, `pcb_analyze_crosstalk`, `pcb_analyze_differential_pair`, `pcb_analyze_length_matching` | Yes |
| 9 | High-Speed Interfaces | `pcb_analyze_ddr`, `pcb_analyze_usb`, `pcb_analyze_pcie`, `pcb_analyze_ethernet`, `pcb_validate_ddr_topology`, `pcb_validate_pcie_lanes`, `pcb_analyze_ddr_timing_budget`, `pcb_calc_pcie_link_budget` | Yes |
| 10 | EMC / EMI | `pcb_analyze_clock_emi`, `pcb_analyze_emi_risk`, `pcb_analyze_smps_emi`, `pcb_analyze_conducted_emissions`, `pcb_analyze_near_field`, `pcb_predict_emissions`, `pcb_get_emi_hotspots` | Yes |
| 11 | EMI Filtering | `pcb_design_emi_filter` | Yes |
| 12 | Automotive EMC | `pcb_analyze_automotive_emc` | Yes |
| 13 | ESD Assessment | `pcb_analyze_esd` | Yes |
| 14 | Immunity Margin | `pcb_analyze_immunity_margin` | Yes |
| 15 | Power Integrity | `pcb_analyze_pdn`, `pcb_analyze_vrm`, `pcb_analyze_decoupling`, `pcb_calc_plane_resonance`, `pcb_calc_pdn_impedance` | Yes |
| 16 | Return Path Analysis | `pcb_visualize_return_path`, `pcb_find_split_crossings`, `pcb_trace_return_path`, `pcb_analyze_return_paths`, `pcb_analyze_return_current`, `pcb_analyze_return_current_density` | Yes |
| 17 | Antenna / Unintentional Radiation | `pcb_analyze_trace_antenna`, `pcb_analyze_slot_antenna`, `pcb_analyze_common_mode`, `pcb_analyze_cable_coupling` | Yes |
| 18 | Thermal | `pcb_analyze_thermal`, `pcb_analyze_thermal_via`, `pcb_analyze_copper_spreading` | Yes |
| 19 | DFM | `pcb_analyze_solder_paste`, `pcb_analyze_placement`, `pcb_analyze_assembly` | Yes |
| 20 | Stackup Optimization | `pcb_optimize_stackup` | Yes |
| 21 | Shielding | `pcb_analyze_shielding` | Yes |
| 22 | Grounding | `pcb_analyze_grounding`, `pcb_analyze_ground_stitch` | Yes |
| 23 | Pre-Compliance Test Plan | `pcb_generate_test_plan` | Yes |
| 24 | Design Rules | `pcb_get_design_rules` | Yes |
| 25 | Drill Table & Vias | `pcb_get_drill_table`, `pcb_analyze_via` | Yes |
| 26 | Priority Action Items | All (aggregated) | No |
| 27 | Tool Coverage | Session metadata | No |
| 28 | Glossary | Static + dynamic | No |
| 29 | References | Static + dynamic | No |
| 30 | Appendices | All | No |

## 5. Section Builder Pattern

Each section builder follows a consistent pattern. Note: `docx_report.py` helper functions (`_add_styled_table`, `_add_image_with_caption`, `_add_finding_box`) will be made public (remove underscore prefix) as part of this work, since they are now consumed by `report_builder.py` in addition to the internal `generate_docx_report()` function.

Pattern:

```python
def _build_section_name(self, doc, results):
    """Section N: Title."""
    # 1. Guard — skip if no data
    data = self._get_domain_results("domain_key", results)
    if not data:
        return

    # 2. Section header + explanatory intro
    doc.add_heading("N. Section Title", level=1)
    doc.add_paragraph("What this analysis category evaluates...")

    # 3. Data tables with measurements
    add_styled_table(doc, headers, rows)

    # 4. Findings with full traceability
    finding = TrackedFinding(...)
    self._render_finding(doc, finding)

    # 5. Simulation plot (cached or generated)
    plot = self._ensure_plot("plot_type", data)
    add_image_with_caption(doc, plot, "caption")

    # 6. Net render (cached or generated)
    render = self._ensure_net_render(finding.nets[0])
    add_image_with_caption(doc, render, "net routing detail")
```

## 6. MCP Tool Interface

```python
{
    "name": "pcb_generate_design_review_report",
    "description": "Generate a professional PCB design review report (DOCX and/or HTML) "
                   "from all analysis results in the current session.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Session containing analysis results"
            },
            "format": {
                "type": "string",
                "enum": ["docx", "html", "both"],
                "default": "both"
            },
            "output_dir": {
                "type": "string",
                "description": "Directory for output files. Defaults to /tmp/pcb_reports/"
            },
            "title": {
                "type": "string",
                "description": "Report title (e.g., 'Product X Rev B PCB Design Review')"
            },
            "confidentiality": {
                "type": "string",
                "default": "CONFIDENTIAL"
            },
            "run_analysis": {
                "type": "boolean",
                "default": false,
                "description": "If true, runs full design review analysis first"
            },
            "auto_render": {
                "type": "boolean",
                "default": true,
                "description": "Auto-generate board/net renders for findings missing visuals"
            }
        },
        "required": ["session_id"]
    }
}
```

**Returns:**

```python
{
    "docx_path": "/tmp/pcb_reports/Design_Review_2026-03-13.docx",
    "html_path": "/tmp/pcb_reports/Design_Review_2026-03-13.html",
    "file_size_kb": 10240,
    "sections_generated": 22,
    "sections_skipped": 8,
    "findings_count": {"critical": 3, "high": 5, "warning": 8, "info": 4, "pass": 12},
    "plots_generated": 14,
    "renders_generated": 6,
    "overall_verdict": "CRITICAL — Remediation Required Before Prototype"
}
```

## 7. File Structure

```
src/mcp_pcb_emcopilot/
  reports/
    __init__.py              # existing — add ReportBuilder export
    report_builder.py        # NEW — ReportBuilder class (~800 lines)
    tracked_finding.py        # NEW — TrackedFinding dataclass (~60 lines)
    section_registry.py      # NEW — section ordering & metadata (~100 lines)
    docx_report.py           # existing — reuse helpers as-is
    html_report.py           # existing — reuse as-is
    simulation_plots.py      # existing — reuse as-is
    test_plan.py             # existing — reuse as-is
  server.py                  # existing — add 1 new tool handler

tests/
  test_report_builder.py     # NEW
  test_tracked_finding.py     # NEW
  test_section_registry.py   # NEW
```

**No new dependencies.** Uses existing `python-docx` and existing helper modules.

## 8. Testing Strategy

**test_tracked_finding.py (~10 tests):**
- Finding with full traceability fields serializes correctly
- Finding with missing optional fields still works
- Severity validation (only CRITICAL/HIGH/WARNING/INFO/PASS)
- finding_id format validation ("EMC-001" pattern)

**test_section_registry.py (~8 tests):**
- All 30 sections present and in order
- Required sections flagged correctly
- Section lookup by key works
- No duplicate section numbers

**test_report_builder.py (~20 tests):**
- Empty session produces valid report with only required sections
- Session with one domain produces that section + exec summary
- Findings sorted by severity in action items
- DOCX output file is valid (opens without error)
- HTML output file is valid
- `run_analysis=true` triggers orchestrator
- `auto_render=true` generates missing renders
- Plot caching works (doesn't regenerate existing plots)
- All section builder methods handle missing data gracefully
- Executive summary aggregates findings correctly

Real DOCX/HTML files generated to `/tmp/`, validated well-formed. Synthetic analyzer output dicts as test fixtures.

## 9. Key Design Principles

1. **Every finding must be traceable** — net name, layer, component ref des, coordinates. No anonymous "a trace" or "a slot."
2. **Every finding must be explanatory** — `what_it_means`, `how_calculated`, `physical_mechanism` fields are not optional in spirit. The report should teach the reader.
3. **Reuse existing infrastructure** — `docx_report.py` helpers, `SimulationPlotter`, `html_report.py` are already well-factored. Don't rewrite them.
4. **Session-first** — the primary path is harvesting results the AI already generated during the review conversation.
5. **Graceful degradation** — missing data means skip the section, not crash the report.
6. **Professional output** — color-coded severity badges, alternating row stripes, sequential figure numbering, headers/footers, TOC field codes. The output should look like it came from a $50k/year EDA tool, not a script.

<p align="center">
  <img src="assets/logo.svg" alt="MCP PCB EMCopilot" width="480">
</p>

<p align="center">
  <strong>AI-powered PCB design review, EMC analysis, and signal integrity via MCP</strong>
</p>

<p align="center">
  <a href="#installation">Installation</a> •
  <a href="#features">Features</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#tool-reference">93 Tools</a> •
  <a href="#supported-formats">Formats</a> •
  <a href="#reports">Reports</a>
</p>

<p align="center">
  <img alt="Tools" src="https://img.shields.io/badge/MCP_Tools-93-22d3ee?style=flat-square">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10+-3776ab?style=flat-square">
  <img alt="License" src="https://img.shields.io/badge/License-Apache_2.0-green?style=flat-square">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-Compatible-a855f7?style=flat-square">
</p>

---

## Overview

MCP PCB EMCopilot is a Model Context Protocol server that provides **93 tools** for AI-assisted PCB design review. It analyzes designs for EMC compliance, signal integrity, power integrity, thermal management, and manufacturing readiness — catching critical issues before prototype fabrication.

### What it does

- **Parses** PCB layouts from KiCad, ODB++, Gerber, IPC-2581, Altium, and STEP files
- **Analyzes** designs across 8 engineering domains with physics-based calculations
- **Predicts** EMC compliance against FCC, CISPR, and IEC standards
- **Generates** professional DOCX reports with embedded board renders and annotated findings
- **Visualizes** board layouts, net routing, stackups, and EMI hotspots as SVG/PNG

## Features

### Parsers & Data Extraction (15 tools)
| Tool | Description |
|------|-------------|
| `pcb_parse_layout` | Parse KiCad, ODB++, Gerber, IPC-2581, Altium files |
| `pcb_parse_schematic_pdf` | Extract schematic pages from PDF |
| `pcb_parse_step` | Parse 3D STEP models |
| `pcb_get_components` | List all components with positions |
| `pcb_get_nets` | Get net list with filtering |
| `pcb_get_traces` | Extract trace routing data |
| `pcb_get_vias` | Get via locations and dimensions |
| `pcb_get_board_outline` | Board dimensions and shape |
| `pcb_get_stackup` | Layer stackup information |
| `pcb_get_copper_pours` | Copper fill/zone data |
| `pcb_get_drill_table` | Drill sizes and counts |
| `pcb_get_design_rules` | Design rule constraints |
| `pcb_get_manufacturing_notes` | DFM notes and constraints |
| `pcb_list_sessions` | Manage parser sessions |
| `pcb_close_session` | Close parser session |

### Impedance Calculators (7 tools)
| Tool | Description |
|------|-------------|
| `pcb_calc_microstrip_impedance` | Surface trace impedance (IPC-2141) |
| `pcb_calc_stripline_impedance` | Buried trace impedance |
| `pcb_calc_differential_impedance` | Differential pair impedance |
| `pcb_calc_cpw_impedance` | Coplanar waveguide impedance |
| `pcb_calc_trace_width` | Current capacity (IPC-2221) |
| `pcb_calc_via_stitching` | Via stitching spacing calculator |
| `pcb_calc_pdn_impedance` | PDN target impedance profiling |

### Signal Integrity (14 tools)
| Tool | Description |
|------|-------------|
| `pcb_analyze_timing` | Setup/hold margin analysis |
| `pcb_analyze_crosstalk` | NEXT/FEXT estimation |
| `pcb_analyze_via` | Via impedance discontinuity |
| `pcb_analyze_differential_pair` | Diff pair quality |
| `pcb_analyze_length_matching` | Length match verification |
| `pcb_analyze_mode_conversion` | Differential mode conversion |
| `pcb_analyze_return_paths` | Return current path analysis |
| `pcb_analyze_return_current` | Return current density profile |
| `pcb_analyze_return_current_density` | Current density mapping |
| `pcb_calc_insertion_loss` | Channel insertion loss |
| `pcb_calc_return_loss` | Impedance match quality |
| `pcb_calc_skin_effect` | Skin effect resistance |
| `pcb_calc_dielectric_loss` | Dielectric loss tangent |
| `pcb_calc_eye_diagram` | Eye diagram estimation |

### EMC / EMI Analysis (14 tools)
| Tool | Description |
|------|-------------|
| `pcb_analyze_current_loop` | Loop radiation estimation |
| `pcb_analyze_clock_emi` | Clock harmonic analysis |
| `pcb_analyze_smps_emi` | Switching converter EMI |
| `pcb_analyze_emi_risk` | Board-level EMI risk scoring |
| `pcb_analyze_shielding` | Shield effectiveness |
| `pcb_analyze_grounding` | Grounding quality assessment |
| `pcb_analyze_ground_stitch` | Via stitching adequacy |
| `pcb_analyze_common_mode` | Common-mode noise |
| `pcb_analyze_cable_coupling` | Cable-to-cable coupling |
| `pcb_analyze_slot_antenna` | Ground slot radiation |
| `pcb_analyze_trace_antenna` | Trace as antenna risk |
| `pcb_estimate_bandwidth` | Bandwidth from rise time |
| `pcb_predict_emissions` | Radiated emission prediction |
| `pcb_predict_compliance` | FCC/CISPR compliance prediction |

### Power Integrity (5 tools)
| Tool | Description |
|------|-------------|
| `pcb_analyze_pdn` | PDN impedance analysis |
| `pcb_analyze_decoupling` | Decap effectiveness |
| `pcb_analyze_vrm` | VRM output assessment |
| `pcb_analyze_copper_spreading` | Copper spreading thermal |
| `pcb_calc_plane_resonance` | Plane pair resonance |

### High-Speed Digital (8 tools)
| Tool | Description |
|------|-------------|
| `pcb_analyze_ddr` | DDR memory interface |
| `pcb_analyze_ddr_timing_budget` | DDR timing margins |
| `pcb_validate_ddr_topology` | DDR routing topology |
| `pcb_analyze_usb` | USB 2.0/3.x analysis |
| `pcb_analyze_ethernet` | Ethernet PHY interface |
| `pcb_analyze_pcie` | PCIe lane analysis |
| `pcb_validate_pcie_lanes` | PCIe routing validation |
| `pcb_calc_pcie_link_budget` | PCIe link budget |

### Thermal (2 tools)
| Tool | Description |
|------|-------------|
| `pcb_analyze_thermal` | Component thermal analysis |
| `pcb_analyze_thermal_via` | Thermal via effectiveness |

### DFM / Manufacturing (4 tools)
| Tool | Description |
|------|-------------|
| `pcb_analyze_placement` | Component placement review |
| `pcb_analyze_assembly` | Assembly feasibility |
| `pcb_analyze_solder_paste` | Solder paste analysis |
| `pcb_analyze_tolerance` | Manufacturing tolerances |

### ESD Protection (1 tool)
| Tool | Description |
|------|-------------|
| `pcb_analyze_esd` | ESD protection assessment |

### Classification & Detection (4 tools)
| Tool | Description |
|------|-------------|
| `pcb_classify_design` | Design type classification |
| `pcb_classify_nets` | Net type classification |
| `pcb_detect_interfaces` | Interface auto-detection |
| `pcb_cross_reference_schematic` | Schematic-layout cross-check |

### Visualization (5 tools)
| Tool | Description |
|------|-------------|
| `pcb_render_board` | Full board SVG render |
| `pcb_render_net` | Individual net highlight |
| `pcb_render_stackup` | Stackup cross-section |
| `pcb_annotate_board` | Annotated board with findings |
| `pcb_get_emi_hotspots` | EMI hotspot identification |

### Export & Reporting (7 tools)
| Tool | Description |
|------|-------------|
| `pcb_export_render_png` | SVG to PNG conversion |
| `pcb_export_all_renders` | Batch export renders |
| `pcb_generate_report` | Generate markdown report |
| `pcb_generate_docx_report` | Generate DOCX with images |
| `pcb_get_schematic_page` | Extract schematic page |
| `pcb_set_review_context` | Set review context |
| `pcb_run_design_review` | Orchestrated full review |

### 3D & Enclosure (3 tools)
| Tool | Description |
|------|-------------|
| `pcb_get_3d_clearances` | 3D clearance analysis |
| `pcb_check_enclosure_fit` | Enclosure fit check |
| `pcb_find_split_crossings` | Split plane crossing detection |

### Utility (4 tools)
| Tool | Description |
|------|-------------|
| `pcb_get_stackup_templates` | Standard stackup templates |
| `pcb_get_material_properties` | Dielectric material data |
| `pcb_trace_return_path` | Return current path tracing |
| `pcb_optimize_ground_stitching` | Stitch via optimization |

## Tool Reference

### Impedance Formulas

The impedance calculators use industry-standard IPC-2141 formulas:

| Trace Type | Typical Applications | Formula Basis |
|------------|---------------------|---------------|
| Microstrip | Top/bottom layer signals | Hammerstad & Jensen |
| Stripline | Inner layer signals | Cohn |
| Differential | USB, HDMI, LVDS, DDR | Coupled line theory |
| CPW/GCPW | RF, mmWave | Conformal mapping |

### Supported Standards

- **IPC-2221** — Generic PCB design standard (current capacity)
- **IPC-2141** — Controlled impedance design
- **FCC Part 15** — Radiated and conducted emission limits
- **CISPR 22/32** — Information technology equipment emissions
- **IEC 61000-4** — ESD, surge, and immunity testing
- **JEDEC** — DDR timing and topology constraints
- **PCIe CEM** — Lane routing and loss budget specifications

### Material Database

Built-in properties for:
- FR4 (standard and high-Tg)
- Rogers RO4003C, RO4350B
- Isola I-Speed, I-Tera
- Panasonic Megtron 6
- Polyimide (flex circuits)

## Supported Formats

| Format | Extension | Parse | Notes |
|--------|-----------|-------|-------|
| KiCad | `.kicad_pcb` | Yes | Full support |
| ODB++ | `.zip`, `.tgz` | Yes | Full support |
| Gerber | `.gbr`, `.ger` | Yes | RS-274X |
| IPC-2581 | `.xml` | Yes | Standard XML |
| Altium | `.PcbDoc` | Yes | Via export |
| STEP | `.step`, `.stp` | Yes | 3D model |
| PDF Schematic | `.pdf` | Yes | Page extraction |

## Installation

### Quick Install
```bash
git clone https://github.com/RFingAdam/mcp-pcb-emcopilot.git
cd mcp-pcb-emcopilot
uv pip install -e .
```

### Optional Dependencies
```bash
pip install cairosvg    # PNG export
pip install python-docx # DOCX reports
pip install pymupdf     # Enhanced PDF schematic parsing
```

### Add to MCP Client

**Claude Code:**
```bash
claude mcp add pcb-emcopilot -- uv run --directory /path/to/mcp-pcb-emcopilot mcp-pcb-emcopilot
```

**Codex CLI:**
```bash
codex mcp add pcb-emcopilot -- uv run --directory /path/to/mcp-pcb-emcopilot mcp-pcb-emcopilot
```

**Config JSON:**
```json
{
  "command": "uv",
  "args": ["run", "--directory", "/path/to/mcp-pcb-emcopilot", "mcp-pcb-emcopilot"]
}
```

## Quick Start

### Run a full design review
```
Parse my PCB layout from design.kicad_pcb, then run a comprehensive design review
and generate a DOCX report with all findings.
```

### Check USB impedance
```
Calculate differential impedance for USB 2.0 traces: 0.15mm width, 0.2mm spacing,
0.1mm dielectric height, FR4 (Er=4.3)
```

### Predict EMC compliance
```
I have a 100MHz clock with 0.5ns rise time on a 25mm trace. Will it pass FCC Class B?
```

### Analyze DDR4 timing
```
Check DDR4-3200 timing budget with 40mm data trace, 35mm strobe, 200ps driver skew
```

### Estimate PCIe link budget
```
Calculate PCIe Gen4 link budget: 150mm trace on Megtron 6, two connectors,
four via transitions
```

## Reports

MCP PCB EMCopilot generates comprehensive DOCX design review reports with:

- Executive summary with domain score dashboard
- Go/No-Go recommendation with gating criteria
- Embedded board renders, net highlights, and annotated findings
- Per-domain analysis (EMC, SI, PI, Thermal, DFM, ESD, RF)
- Priority action items with severity classification
- Appendices with component summary and tool coverage

## Companion MCP Servers

| Server | Purpose |
|--------|---------|
| [mcp-emc-regulations](https://github.com/RFingAdam/mcp-emc-regulations) | FCC/CISPR/IEC emission limits |
| [mcp-nec2-antenna](https://github.com/RFingAdam/mcp-nec2-antenna) | Antenna simulation (NEC2) |
| [mcp-openems](https://github.com/RFingAdam/mcp-openems) | Full-wave EM simulation |
| [mcp-drawio-engineering](https://github.com/RFingAdam/mcp-drawio-engineering) | Engineering diagrams |

## Common Design Targets

| Interface | Single-Ended | Differential |
|-----------|------------------|------------------|
| General purpose | 50 | — |
| USB 2.0 | — | 90 |
| USB 3.x | — | 85 |
| HDMI | — | 100 |
| DDR4/LPDDR4 | 40 | 80 |
| PCIe | — | 85 |
| Ethernet | — | 100 |

## License

Apache-2.0

## Author

Adam Engelbrecht — [@RFingAdam](https://github.com/RFingAdam)

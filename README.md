<div align="center">

<img src="assets/logo-banner.svg" alt="mcp-pcb-emcopilot — PCB EMC + signal-integrity analysis (return paths, decoupling, DDR/PCIe/USB)" width="100%"/>

<br/>

[![License](https://img.shields.io/badge/License-Apache--2.0-1E40AF.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB.svg)](https://www.python.org/downloads/)
[![MCP Tools](https://img.shields.io/badge/MCP_Tools-93-22D3EE.svg)](#tools)
[![MCP](https://img.shields.io/badge/MCP-server-A78BFA.svg)](https://modelcontextprotocol.io)
[![eng-mcp-suite](https://img.shields.io/badge/eng--mcp--suite-member-22D3EE.svg)](https://github.com/RFingAdam/eng-mcp-suite)

**AI-powered PCB design review — EMC, signal integrity, power integrity, thermal, and DFM in one MCP server.**
**Catch return-path breaks, decoupling gaps, and DDR/PCIe topology errors before fabrication, from your terminal or AI agent.**

[Quick start](#quick-start) ·
[Tools](#tools) ·
[Workflows](#workflows) ·
[Documentation](#documentation)

</div>

---

## What is mcp-pcb-emcopilot?

mcp-pcb-emcopilot is a Model Context Protocol server that provides
**93 tools** for AI-assisted PCB design review. It parses layouts from
KiCad / ODB++ / Gerber / IPC-2581 / Altium / STEP, runs physics-based
analyzers across eight engineering domains, and emits annotated DOCX
reports with embedded board renders and per-finding severity.

Drive it from any MCP client. The orchestrator (`pcb_run_design_review`)
walks parsers → classifiers → analyzers → reports in one call; each
underlying step is also a standalone tool an agent can call directly
when you want to debug one net or revalidate one DDR byte-lane.

**What mcp-pcb-emcopilot does well:**

- 🤖 **AI-native via MCP.** First-class [Model Context Protocol](https://modelcontextprotocol.io)
  server with 93 tools across parsing, calculation, analysis, and
  reporting. Any Claude / LLM agent can drive a full design review.
- 🧱 **Multi-format layout parsing.** KiCad `.kicad_pcb`, ODB++, Gerber
  RS-274X, IPC-2581, Altium `.PcbDoc`, 3D STEP — same downstream
  analyzers regardless of source.
- 📐 **IPC-grounded impedance.** Microstrip / stripline / differential /
  CPWG via IPC-2141 (Hammerstad-Jensen, Cohn, coupled-line). Plus
  IPC-2221 trace-width / current capacity.
- 🛰️ **EMC + SI in one pass.** Return-path analysis, decoupling
  effectiveness, current-loop radiation, FCC / CISPR / IEC compliance
  prediction, DDR / PCIe / USB topology validation.
- 📑 **Audit-grade reports.** DOCX + HTML with embedded board renders,
  net highlights, annotated findings, executive summary, and Go/No-Go
  recommendation.
- 🔒 **Apache-2.0.**

---

## Quick start

### Install

```bash
git clone https://github.com/RFingAdam/mcp-pcb-emcopilot.git
cd mcp-pcb-emcopilot
uv pip install -e .
```

Optional extras (PNG export, DOCX reports, enhanced PDF parsing):

```bash
pip install cairosvg python-docx pymupdf
```

### Wire it into your MCP client

**Claude Code:**
```bash
claude mcp add pcb-emcopilot -- uv run --directory /path/to/mcp-pcb-emcopilot mcp-pcb-emcopilot
```

**Codex CLI:**
```bash
codex mcp add pcb-emcopilot -- uv run --directory /path/to/mcp-pcb-emcopilot mcp-pcb-emcopilot
```

**Raw config (Claude Desktop):**

```json
{
  "mcpServers": {
    "pcb-emcopilot": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-pcb-emcopilot", "mcp-pcb-emcopilot"]
    }
  }
}
```

Then ask your assistant:

> *"Parse design.kicad_pcb, run a comprehensive design review, and generate a DOCX report with annotated findings."*

The agent walks `pcb_parse_layout` → `pcb_classify_design` →
`pcb_run_design_review` → `pcb_generate_docx_report` and hands you a
fabrication-grade document.

---

## Tools

93 tools across 14 categories. Full table is below — full reference
with arguments in [`docs/tools.md`](docs/tools.md).

### Parsers & data extraction (15)
| Tool | Description |
|------|-------------|
| `pcb_parse_layout` | Parse KiCad, ODB++, Gerber, IPC-2581, Altium |
| `pcb_parse_schematic_pdf` | Extract schematic pages from PDF |
| `pcb_parse_step` | Parse 3D STEP models |
| `pcb_get_components` / `_nets` / `_traces` / `_vias` / `_board_outline` / `_stackup` / `_copper_pours` / `_drill_table` / `_design_rules` / `_manufacturing_notes` | Layout query tools |
| `pcb_list_sessions` / `pcb_close_session` | Session management |

### Impedance calculators (7)
`pcb_calc_microstrip_impedance`, `pcb_calc_stripline_impedance`,
`pcb_calc_differential_impedance`, `pcb_calc_cpw_impedance`,
`pcb_calc_trace_width`, `pcb_calc_via_stitching`,
`pcb_calc_pdn_impedance`.

### Signal integrity (14)
`pcb_analyze_timing`, `pcb_analyze_crosstalk`, `pcb_analyze_via`,
`pcb_analyze_differential_pair`, `pcb_analyze_length_matching`,
`pcb_analyze_mode_conversion`, `pcb_analyze_return_paths`,
`pcb_analyze_return_current`, `pcb_analyze_return_current_density`,
`pcb_calc_insertion_loss`, `pcb_calc_return_loss`,
`pcb_calc_skin_effect`, `pcb_calc_dielectric_loss`,
`pcb_calc_eye_diagram`.

### EMC / EMI analysis (14)
`pcb_analyze_current_loop`, `pcb_analyze_clock_emi`,
`pcb_analyze_smps_emi`, `pcb_analyze_emi_risk`,
`pcb_analyze_shielding`, `pcb_analyze_grounding`,
`pcb_analyze_ground_stitch`, `pcb_analyze_common_mode`,
`pcb_analyze_cable_coupling`, `pcb_analyze_slot_antenna`,
`pcb_analyze_trace_antenna`, `pcb_estimate_bandwidth`,
`pcb_predict_emissions`, `pcb_predict_compliance`.

### Power integrity (5)
`pcb_analyze_pdn`, `pcb_analyze_decoupling`, `pcb_analyze_vrm`,
`pcb_analyze_copper_spreading`, `pcb_calc_plane_resonance`.

### High-speed digital (8)
`pcb_analyze_ddr`, `pcb_analyze_ddr_timing_budget`,
`pcb_validate_ddr_topology`, `pcb_analyze_usb`,
`pcb_analyze_ethernet`, `pcb_analyze_pcie`,
`pcb_validate_pcie_lanes`, `pcb_calc_pcie_link_budget`.

### Thermal (2), DFM / manufacturing (4), ESD (1)
`pcb_analyze_thermal`, `pcb_analyze_thermal_via`,
`pcb_analyze_placement`, `pcb_analyze_assembly`,
`pcb_analyze_solder_paste`, `pcb_analyze_tolerance`,
`pcb_analyze_esd`.

### Classification & detection (4)
`pcb_classify_design`, `pcb_classify_nets`, `pcb_detect_interfaces`,
`pcb_cross_reference_schematic`.

### Visualization (5)
`pcb_render_board`, `pcb_render_net`, `pcb_render_stackup`,
`pcb_annotate_board`, `pcb_get_emi_hotspots`.

### Export & reporting (7)
`pcb_export_render_png`, `pcb_export_all_renders`,
`pcb_generate_report`, `pcb_generate_docx_report`,
`pcb_get_schematic_page`, `pcb_set_review_context`,
`pcb_run_design_review` (orchestrated full review).

### 3D & enclosure (3), utility (4)
`pcb_get_3d_clearances`, `pcb_check_enclosure_fit`,
`pcb_find_split_crossings`, `pcb_get_stackup_templates`,
`pcb_get_material_properties`, `pcb_trace_return_path`,
`pcb_optimize_ground_stitching`.

Full per-tool argument reference in [`docs/tools.md`](docs/tools.md).

---

## What it solves

| Domain | Standards         | Headline tools                                           |
| ------ | ----------------- | -------------------------------------------------------- |
| Impedance | IPC-2141, IPC-2221 | microstrip / stripline / differential / CPW calculators |
| EMC    | FCC Part 15, CISPR 22/32 | `pcb_predict_emissions`, `pcb_predict_compliance`  |
| Immunity | IEC 61000-4    | `pcb_analyze_esd`                                        |
| Digital | JEDEC, PCIe CEM  | `pcb_validate_ddr_topology`, `pcb_validate_pcie_lanes`   |

### Material database

Built-in dielectric properties: FR4 (standard + high-Tg), Rogers
RO4003C / RO4350B, Isola I-Speed / I-Tera, Panasonic Megtron 6,
polyimide (flex). Query via `pcb_get_material_properties`.

### Supported formats

| Format            | Extension       | Notes              |
| ----------------- | --------------- | ------------------ |
| KiCad             | `.kicad_pcb`    | Full support       |
| ODB++             | `.zip`, `.tgz`  | Full support       |
| Gerber RS-274X    | `.gbr`, `.ger`  |                    |
| IPC-2581          | `.xml`          | Standard XML       |
| Altium            | `.PcbDoc`       | Via export         |
| STEP              | `.step`, `.stp` | 3D model           |
| PDF schematic     | `.pdf`          | Page extraction    |

---

## Workflows

mcp-pcb-emcopilot fits in the following [eng-mcp-suite](https://github.com/RFingAdam/eng-mcp-suite)
workflow bundles:

- **`pcb-review`** — full layout intake, EMC + SI + PI + thermal +
  DFM analysis, audit-grade DOCX report.
- **`coexistence-review`** — multi-radio band selection
  (mcp-ltspice-qucs / mcp-emc-regulations) followed by layout-level
  shielding + return-path check (this server).

See the [suite manifest](https://github.com/RFingAdam/eng-mcp-suite/blob/main/manifest.yaml)
for the full list of sibling MCPs and bundle definitions.

---

## Documentation

- 📘 **[Quick Start](docs/index.md)** — install through first call.
- 🛠️ **[Tool reference](docs/tools.md)** — every MCP tool, every argument.
- 📐 **[Usage examples](docs/usage.md)** — practical end-to-end walkthroughs.
- 🏗️ **[Architecture](docs/architecture.md)** — how this MCP fits in eng-mcp-suite.

---

## Common design targets

| Interface       | Single-ended Z₀ | Differential Z_diff |
| --------------- | --------------- | ------------------- |
| General purpose | 50 Ω            | —                   |
| USB 2.0         | —               | 90 Ω                |
| USB 3.x         | —               | 85 Ω                |
| HDMI            | —               | 100 Ω               |
| DDR4 / LPDDR4   | 40 Ω            | 80 Ω                |
| PCIe            | —               | 85 Ω                |
| Ethernet        | —               | 100 Ω               |

---

## Part of eng-mcp-suite

<sub>This MCP server is part of</sub>

[![eng-mcp-suite](https://img.shields.io/badge/eng--mcp--suite-engineering%20MCP%20catalog-22D3EE?style=for-the-badge)](https://github.com/RFingAdam/eng-mcp-suite)

<sub>An open umbrella for engineering MCP servers across RF, EMC, PCB,
signal integrity, EM simulation, and lab test. Same brand, same docs
structure, designed to compose. See the
[full catalog](https://github.com/RFingAdam/eng-mcp-suite#whats-included)
or jump to a sibling:</sub>

| Domain                      | Sibling MCPs                                                                 |
| --------------------------- | ---------------------------------------------------------------------------- |
| **RF / Transmission lines** | [lineforge](https://github.com/RFingAdam/lineforge)                          |
| **Antennas**                | [mcp-nec2-antenna](https://github.com/RFingAdam/mcp-nec2-antenna)            |
| **Circuit + filter sim**    | [mcp-ltspice-qucs](https://github.com/RFingAdam/mcp-ltspice-qucs)            |
| **EMC regulatory**          | [mcp-emc-regulations](https://github.com/RFingAdam/mcp-emc-regulations)      |
| **EM simulation (3D)**      | [mcp-openems](https://github.com/RFingAdam/mcp-openems)                      |
| **Diagrams**                | [drawio-engineering-mcp](https://github.com/RFingAdam/drawio-engineering-mcp) |
| **Lab gear**                | [copper-mountain-vna-mcp](https://github.com/RFingAdam/copper-mountain-vna-mcp) |

---

## Contributing

Contributions are welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for
the contributor guide.

```bash
uv pip install -e ".[dev]"
uv run pytest -q
```

---

## License

[Apache-2.0](LICENSE).

## Acknowledgments

- **The KiCad project**, **ODB++**, **IPC** — the open layout standards
  this server parses.
- **IPC-2141A** — controlled-impedance reference behind the trace
  calculators.
- **The MCP working group** — for the [Model Context Protocol](https://modelcontextprotocol.io) specification.

<div align="center">

<sub>Part of <a href="https://github.com/RFingAdam/eng-mcp-suite">eng-mcp-suite</a> — built for PCB designers, EMC labs, and AI agents.</sub>

</div>

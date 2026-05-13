# Tools

This page documents the MCP tool surface (93 tools, grouped). Tools are
registered under the `pcb-emcopilot` namespace when the server is loaded
by an MCP client. For exhaustive argument detail, the canonical source
is the tool registration in
[`src/mcp_pcb_emcopilot/server.py`](https://github.com/RFingAdam/mcp-pcb-emcopilot/blob/main/src/mcp_pcb_emcopilot/server.py).

## Categories

| Category                          | Tools | Doc anchor                       |
| --------------------------------- | ----: | -------------------------------- |
| Parsers & data extraction         | 15    | [#parsers](#parsers)             |
| Impedance calculators             | 7     | [#impedance](#impedance)         |
| Signal integrity                  | 14    | [#signal-integrity](#signal-integrity) |
| EMC / EMI analysis                | 14    | [#emc--emi](#emc--emi)           |
| Power integrity                   | 5     | [#power-integrity](#power-integrity) |
| High-speed digital                | 8     | [#high-speed-digital](#high-speed-digital) |
| Thermal                           | 2     | [#thermal](#thermal)             |
| DFM / manufacturing               | 4     | [#dfm--manufacturing](#dfm--manufacturing) |
| ESD                               | 1     | [#esd](#esd)                     |
| Classification & detection        | 4     | [#classification](#classification) |
| Visualization                     | 5     | [#visualization](#visualization) |
| Export & reporting                | 7     | [#export--reporting](#export--reporting) |
| 3D & enclosure                    | 3     | [#3d--enclosure](#3d--enclosure) |
| Utility                           | 4     | [#utility](#utility)             |

---

## Parsers

| Tool                            | Purpose                                              |
| ------------------------------- | ---------------------------------------------------- |
| `pcb_parse_layout`              | Parse KiCad, ODB++, Gerber, IPC-2581, Altium files   |
| `pcb_parse_schematic_pdf`       | Extract schematic pages from PDF                     |
| `pcb_parse_step`                | Parse 3D STEP models                                 |
| `pcb_get_components`            | List all components with positions                   |
| `pcb_get_nets`                  | Get net list with filtering                          |
| `pcb_get_traces`                | Extract trace routing data                           |
| `pcb_get_vias`                  | Get via locations and dimensions                     |
| `pcb_get_board_outline`         | Board dimensions and shape                           |
| `pcb_get_stackup`               | Layer stackup information                            |
| `pcb_get_copper_pours`          | Copper fill/zone data                                |
| `pcb_get_drill_table`           | Drill sizes and counts                               |
| `pcb_get_design_rules`          | Design rule constraints                              |
| `pcb_get_manufacturing_notes`   | DFM notes and constraints                            |
| `pcb_list_sessions`             | Manage parser sessions                               |
| `pcb_close_session`             | Close parser session                                 |

## Impedance

| Tool                              | Reference / Formula              |
| --------------------------------- | -------------------------------- |
| `pcb_calc_microstrip_impedance`   | IPC-2141 / Hammerstad-Jensen     |
| `pcb_calc_stripline_impedance`    | IPC-2141 / Cohn                  |
| `pcb_calc_differential_impedance` | Coupled-line theory              |
| `pcb_calc_cpw_impedance`          | Conformal mapping                |
| `pcb_calc_trace_width`            | IPC-2221 current capacity        |
| `pcb_calc_via_stitching`          | Stitching spacing calculator     |
| `pcb_calc_pdn_impedance`          | PDN target impedance profile     |

## Signal integrity

`pcb_analyze_timing`, `pcb_analyze_crosstalk`, `pcb_analyze_via`,
`pcb_analyze_differential_pair`, `pcb_analyze_length_matching`,
`pcb_analyze_mode_conversion`, `pcb_analyze_return_paths`,
`pcb_analyze_return_current`, `pcb_analyze_return_current_density`,
`pcb_calc_insertion_loss`, `pcb_calc_return_loss`,
`pcb_calc_skin_effect`, `pcb_calc_dielectric_loss`,
`pcb_calc_eye_diagram`.

## EMC / EMI

`pcb_analyze_current_loop`, `pcb_analyze_clock_emi`,
`pcb_analyze_smps_emi`, `pcb_analyze_emi_risk`,
`pcb_analyze_shielding`, `pcb_analyze_grounding`,
`pcb_analyze_ground_stitch`, `pcb_analyze_common_mode`,
`pcb_analyze_cable_coupling`, `pcb_analyze_slot_antenna`,
`pcb_analyze_trace_antenna`, `pcb_estimate_bandwidth`,
`pcb_predict_emissions`, `pcb_predict_compliance`.

## Power integrity

`pcb_analyze_pdn`, `pcb_analyze_decoupling`, `pcb_analyze_vrm`,
`pcb_analyze_copper_spreading`, `pcb_calc_plane_resonance`.

## High-speed digital

`pcb_analyze_ddr`, `pcb_analyze_ddr_timing_budget`,
`pcb_validate_ddr_topology`, `pcb_analyze_usb`,
`pcb_analyze_ethernet`, `pcb_analyze_pcie`,
`pcb_validate_pcie_lanes`, `pcb_calc_pcie_link_budget`.

## Thermal

`pcb_analyze_thermal`, `pcb_analyze_thermal_via`.

## DFM / manufacturing

`pcb_analyze_placement`, `pcb_analyze_assembly`,
`pcb_analyze_solder_paste`, `pcb_analyze_tolerance`.

## ESD

`pcb_analyze_esd` — ESD protection assessment (TVS placement, clamping
voltage, IEC 61000-4-2 levels).

## Classification

`pcb_classify_design`, `pcb_classify_nets`, `pcb_detect_interfaces`,
`pcb_cross_reference_schematic`.

## Visualization

`pcb_render_board`, `pcb_render_net`, `pcb_render_stackup`,
`pcb_annotate_board`, `pcb_get_emi_hotspots`.

## Export & reporting

| Tool                       | Purpose                                              |
| -------------------------- | ---------------------------------------------------- |
| `pcb_export_render_png`    | SVG → PNG conversion                                 |
| `pcb_export_all_renders`   | Batch export all renders                             |
| `pcb_generate_report`      | Markdown report                                      |
| `pcb_generate_docx_report` | DOCX with embedded board renders                     |
| `pcb_get_schematic_page`   | Extract a schematic page                             |
| `pcb_set_review_context`   | Set review context (target standards, customer, etc.) |
| `pcb_run_design_review`    | **Orchestrated full review** (parsers → analyzers → report) |

## 3D & enclosure

`pcb_get_3d_clearances`, `pcb_check_enclosure_fit`,
`pcb_find_split_crossings`.

## Utility

`pcb_get_stackup_templates`, `pcb_get_material_properties`,
`pcb_trace_return_path`, `pcb_optimize_ground_stitching`.

---

## Supported standards

- **IPC-2221** — Generic PCB design (current capacity)
- **IPC-2141** — Controlled impedance
- **FCC Part 15** — Radiated + conducted emission limits
- **CISPR 22 / 32** — Information-technology / multimedia equipment emissions
- **IEC 61000-4** — ESD, surge, immunity
- **JEDEC** — DDR timing + topology
- **PCIe CEM** — Lane routing + loss budget

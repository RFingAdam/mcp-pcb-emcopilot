# Changelog

All notable changes to **mcp-pcb-emcopilot** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] — 2026-05-27

### Added
- **Phase 2** — Claude-driven meticulous-review workflow.
- **Phase 3 / 3a** — cross-MCP intent queue + four orchestration tools
  (`pcb_request_simulation`, `pcb_request_limit_lookup`,
  `pcb_request_antenna_check`, `pcb_request_filter_design`).
- **Phase 3b** — limits provider with sibling-MCP bridges into
  `mcp-emc-regulations`, `mcp-openems`, `mcp-nec2-antenna`, and
  `mcp-ltspice-qucs`.
- **Phase 4** — multi-market intake (FCC Part 15 / CISPR / automotive
  CISPR-25 / medical IEC-60601), standards-coverage report, and a
  pre-flight gate that refuses analysis when required market context
  is missing.
- **Phase 4b** — schematic-aware analyzers and 3-way schematic /
  layout / BOM cross-reference, plus the
  `pcb_three_way_cross_reference` tool.
- **Phase 4c** — KiCad `sexpdata` parser for `.kicad_sch` and
  `.kicad_pcb`, netlist extractor, and `pcb_analyze_signal_flow`
  tool. CI pinned for reproducibility.
- **web-ui scaffold** — React + Vite + Tailwind frontend salvaged
  from the earlier Agentarium `pcb_em_copilot` module (2026-04-21).
  Ships under `web-ui/` with its own README documenting the
  remaining Flask-backend retargeting work. Not built or served by
  the Python package yet — included as the integration starting
  point for the next iteration.

### Changed
- **CI** — bumped GitHub Actions to Node 24 (`checkout@v5`,
  `setup-python@v6`).
- **Type checking** — mypy typecheck is now a required CI step;
  `continue-on-error` moved from job- to step-level so individual
  step failures still surface.

### Fixed
- Cleared all pre-existing mypy errors across the source tree.
- Stripped the `src.` prefix from `importlib.import_module()` string
  args and from `test_integration_odb` imports so tests resolve
  against the installed package, not the working tree.

## [0.3.0] — 2026-05-13

### Changed
- **License: Apache-2.0 → AGPL-3.0-or-later.** Aligns with the
  eng-mcp-suite toolkit-wide AGPL move. The AGPL closes the
  "wrap as a paid SaaS without contributing back" gap by extending
  copyleft to network use. Existing Apache-2.0 forks remain valid
  under their original terms; future commits and the v0.3.0 release
  are AGPL-3.0-or-later. See the
  [LICENSE_SUMMARY](https://github.com/RFingAdam/eng-mcp-suite/blob/main/LICENSE_SUMMARY.md)
  in eng-mcp-suite for the toolkit-wide rationale.

## [0.2.0] — 2026-05-13

### Added
- Tiers 2–3 design-review features: BOM cross-reference, revision diff,
  AI-driven recommendations, reference-design lookup, ECO generation.
- Executive dashboard with SVG gauges and domain-risk bars.
- PCB-to-OpenEMS bridge — RF simulation extractor + coupled-line models.
- Crosstalk analyzer, finding annotator, false-positive suppression.
- 65 integration tests + EDA net-mapping validation.
- BOM-driven current profiling and battery-life analysis.
- Interactive review context — MCP asks the user for missing info.
- Differential-pair impedance calculation from real trace spacing.
- Per-IC decoupling adequacy checker.
- Impedance validation using real stackup data.
- Brand assets aligned with eng-mcp-suite design system (logo, banner, docs).

### Fixed
- PDN per-rail consolidation; coordinate-specific findings.
- RF filter detection recognizes TDK/Qualcomm part numbers and BF* refs.
- DFM analyzer method name; MCP `pcb_answer_review_questions` accepts JSON
  string for MCP transport compatibility.
- Copper vs dielectric thickness accounting; SDIO cross-chip false positive.
- 27 correctness / formula / robustness / security fixes across analyzers.

## [0.1.0]

Initial release of the MCP server with PCB layout parsing, IPC-2141
impedance solvers, EMC + SI analyzers, and DOCX report generation across
eight engineering domains.

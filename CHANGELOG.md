# Changelog

All notable changes to **mcp-pcb-emcopilot** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

# Standards Coverage Matrix

Programmatic source of truth: `src/mcp_pcb_emcopilot/standards/coverage.py::STANDARD_TO_ANALYZERS`.

The matrix maps every supported regulatory standard to the analyzers required to claim compliance, the source of authoritative limit values, and the current coverage level. `pcb_get_standards_coverage` reads from the same dict so the runtime view always matches this document.

## Coverage levels

| Level | Meaning |
|---|---|
| `full` | All required analyzers implemented; limits available locally or via emc-regulations. |
| `partial` | Most analyzers present but some heuristic/missing; verify manually. |
| `stub` | Standard recognised but no analyzer covers it yet; surface as human-review. |
| `unimplemented` | Standard is out-of-scope today; reported for transparency. |

## Limit sources

| Source | Meaning |
|---|---|
| `local_fallback` | Hard-coded tables in `analyzers/emc/limits_provider.py` are authoritative. |
| `emc-regulations` | Authoritative source is the `mcp__emc-regulations__*` sibling MCP; analyzers consult `limits_provider` which transparently uses the live cache when populated. |

## Automotive

| Standard | Required analyzers | Limit source | Coverage |
|---|---|---|---|
| CISPR_25 | automotive_emc, return_paths, smps_emi, clock_emi | local_fallback | full |
| ISO_11452_2 | immunity_margin, cable_coupling | local_fallback | full |
| ISO_11452_4 | immunity_margin, cable_coupling | local_fallback | full |
| ISO_11452_5 | immunity_margin | local_fallback | partial |
| ISO_7637_2 | (none — transient model deferred) | emc-regulations | stub |
| ISO_7637_3 | (none) | emc-regulations | stub |
| ISO_16750_2 | immunity_margin | local_fallback | partial |

## Commercial

| Standard | Required analyzers | Limit source | Coverage |
|---|---|---|---|
| FCC_PART_15_B | conducted_emissions, near_field, emi_risk, clock_emi | local_fallback | full |
| FCC_PART_15_A | conducted_emissions, near_field, emi_risk | local_fallback | full |
| CISPR_32 | conducted_emissions, near_field, clock_emi | local_fallback | full |
| EN_55032 | conducted_emissions, near_field, clock_emi | local_fallback | full |
| IEC_61000_4_2 | esd, immunity_margin | local_fallback | full |
| IEC_61000_4_3 | immunity_margin, cable_coupling | local_fallback | full |
| IEC_61000_4_4 | immunity_margin | local_fallback | partial |
| IEC_61000_4_5 | immunity_margin | local_fallback | partial |
| IEC_61000_4_6 | immunity_margin, cable_coupling | local_fallback | partial |
| IEC_61000_4_8 | immunity_margin | local_fallback | partial |
| IEC_61000_4_11 | (none) | emc-regulations | stub |

## Medical

| Standard | Required analyzers | Limit source | Coverage |
|---|---|---|---|
| IEC_60601_1_2_ED_4_1 | esd, immunity_margin, cable_coupling | local_fallback | full |
| IEC_60601_1_2_ED_4_0 | esd, immunity_margin, cable_coupling | local_fallback | full |
| IEC_60601_1_2 (alias 4.1) | esd, immunity_margin, cable_coupling | local_fallback | full |

## Wireless / RF

| Standard | Required analyzers | Limit source | Coverage |
|---|---|---|---|
| FCC_47_CFR_15C | trace_antenna, slot_antenna, common_mode, return_loss | emc-regulations | partial |
| FCC_PART_15_C (alias) | trace_antenna, slot_antenna, common_mode, return_loss | emc-regulations | partial |
| ETSI_EN_300_328 | trace_antenna, return_loss | emc-regulations | partial |
| ETSI_EN_301_893 | trace_antenna, return_loss | emc-regulations | partial |
| ETSI_EN_303_413 | trace_antenna | emc-regulations | partial |
| ISED_RSS-247 | trace_antenna, return_loss | emc-regulations | partial |
| EN_301_489 | immunity_margin, cable_coupling | emc-regulations | partial |

## Industrial

| Standard | Required analyzers | Limit source | Coverage |
|---|---|---|---|
| EN_61326 | conducted_emissions, immunity_margin, esd | local_fallback | full |
| IEC_61000_6_2 | immunity_margin, esd | local_fallback | full |
| IEC_61000_6_4 | conducted_emissions, near_field | local_fallback | full |

## Out-of-scope (reported but not implemented)

| Standard | Required analyzers | Limit source | Coverage |
|---|---|---|---|
| MIL_STD_461G | — | emc-regulations | unimplemented |

## How callers use this

- `pcb_get_standards_coverage(session_id)` returns one `StandardCoverage` per active standard, surfacing which required analyzers ran and which are missing.
- The preflight gate (`standards/preflight.py::validate_review_complete`) refuses to advance to report generation when any `stub` or `unimplemented` standard is in the active set — unless `force_run=True`, which stamps the report **PRELIMINARY**.
- A coverage entry with non-empty `missing_analyzers` does not by itself block report generation; the analyzers ran for that interface may not have been triggered (e.g., no USB nets in the design). Use the coverage summary alongside the orchestrator's `domain_results` to judge.

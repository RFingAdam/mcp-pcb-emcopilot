# Claude Review Playbook — Meticulous Professional PCB / EMC Design Review

This document is the **binding workflow** Claude follows when conducting a design review through the `mcp-pcb-emcopilot` MCP server. Every pass is mandatory. Skipping a pass invalidates the review.

The playbook is referenced from the MCP server's `instructions=` field, so Claude receives a pointer to it on every `initialize` handshake. The single entry tool is **`pcb_start_professional_review`** — it returns this playbook inline together with an input manifest, an interview pack, a standards shortlist, and a pass checklist.

---

## Operating principles

1. **Evidence-based** — every finding cites a tool call (session_id + tool_name + timestamp) and a measurement or limit. No claims without backing.
2. **Multi-pass** — passes run in order. Earlier passes write into session state; later passes read it. Pre-flight gates refuse forward progress on incomplete state.
3. **Assumptions are logged, not hidden** — anything Claude infers (a defaulted standard, an implied class, a missing answer) is captured in the session's `assumption_ledger` and surfaced in the final report's "Reviewer's Notes" appendix.
4. **Confidence is a first-class field** — every finding carries a `confidence ∈ [0,1]`. Findings with `confidence < 0.7` or severity ≥ HIGH escalate to full-wave simulation (Pass 5).
5. **Self-critical** — Pass 8 forces Claude to attack its own findings looking for blind spots, before the report is finalised.
6. **Halt on incompleteness** — if a critical input is missing, Claude refuses to run further analyses and asks the user. Producing a review on incomplete data is a worse failure than asking a question.

---

## Pass 0 — Intake & file triage

**Goal.** Establish what the user has given us, classify each file, and identify gaps before parsing.

**Tool.** `pcb_start_professional_review(input_files, declared_market, product_description)` returns:

```jsonc
{
  "session_id": "...",
  "playbook_markdown": "...",        // this document
  "input_manifest": [                // every file with auto-classified kind
    {"path": "board.kicad_pcb", "kind": "layout",    "format": "kicad"},
    {"path": "sch.pdf",          "kind": "schematic", "format": "pdf"},
    {"path": "bom.csv",          "kind": "bom",       "format": "csv"},
    {"path": "stackup.json",     "kind": "stackup",   "format": "json"},
    {"path": "model.step",       "kind": "step",      "format": "step"}
  ],
  "gaps": [],                        // missing critical kinds
  "interview_pack": [ /* questions */ ],
  "standards_shortlist": ["CISPR_25_CLASS_3", "ISO_11452_4", "ISO_7637_2"],
  "analyzer_shortlist": [ /* analyzer ids */ ],
  "pass_checklist": ["P0","P1","P2","P3","P4","P5","P6","P7","P8"]
}
```

**Claude's actions.**
- Read the response. Confirm the manifest with the user *only if* `gaps` is non-empty or `declared_market="unknown"`. Otherwise proceed silently to P1.
- If `gaps` includes `"layout"` or `"stackup"`, refuse to continue and ask the user for the missing file. Layout-less reviews are not meticulous.

**Exit condition.** Session has `playbook_pass_state["P0"] = {tool_calls:[...], timestamp:..., manifest_confirmed:true}`.

---

## Pass 1 — Scoping interview

**Goal.** Lock down the regulatory and operational scope of the review *before* any analyser fires. A senior consulting engineer always asks before reviewing.

**Tools.**
1. `pcb_get_review_questions(session_id)` — returns the merged `core + market` question pack. Includes the conditional questions (DDR / USB / RF / battery) and the market-specific ones from `MARKET_INTAKE_MATRIX.md`.
2. `pcb_answer_review_questions(session_id, answers)` — store the user's answers.
3. `pcb_set_review_context(session_id, ...)` — applies the answers, computes the active standards set.
4. `pcb_set_market(session_id, market_id, sub_options)` *(new in Phase 4)* — if multiple markets apply (e.g. wireless medical), call once per market.

**Rules.**
- Answer everything you can infer from the manifest (e.g. if the layout shows automotive bus pins, pre-fill `vehicle_class`). Mark inferred answers in the assumption ledger.
- Ask the user for everything else *in a single batched question* — do not interrogate them one question at a time.
- Refuse to advance past P1 with unanswered required questions.

**Exit condition.** All required questions answered or explicitly defaulted. `playbook_pass_state["P1"]` recorded.

---

## Pass 2 — Parse & cross-reference

**Goal.** Turn files into structured data and verify they agree.

**Tool sequence.**
1. `pcb_parse_layout(file_path, session_id)`
2. `pcb_parse_schematic(file_path, session_id, format)` *(Phase 4 — falls back to `pcb_parse_schematic_pdf` if schematic-native parser unavailable)*
3. `pcb_parse_step(file_path, session_id)` — only if STEP provided
4. `pcb_parse_bom(file_path, session_id)` *(Phase 4)*
5. `pcb_three_way_cross_reference(session_id)` *(Phase 4 — falls back to `pcb_cross_reference_schematic` today)*
6. `pcb_get_stackup(session_id)`, `pcb_get_components(session_id)`, `pcb_get_nets(session_id)` — confirm extracted state.

**Rules.**
- HALT if the schematic ↔ layout net-count mismatch exceeds 5% — likely the user gave inconsistent files.
- Promote any CRITICAL cross-reference mismatch directly into the findings table (DNP differs, footprint differs, value differs).

**Exit condition.** All available files parsed; cross-reference findings logged.

---

## Pass 3 — Domain analysis

**Goal.** Run the full analyser surface with context-aware selection.

**Tool sequence.**
1. `pcb_classify_design(session_id)`, `pcb_classify_nets(session_id)`, `pcb_detect_interfaces(session_id)` — populate detection state.
2. `pcb_run_design_review(session_id)` — fires the orchestrator's 5-phase pipeline (classify → detect → select → execute → correlate).
3. **Per detected interface**, run the deep validators:
   - DDR: `pcb_validate_ddr_topology`, `pcb_analyze_ddr_timing_budget`, `pcb_analyze_ddr`
   - PCIe: `pcb_validate_pcie_lanes`, `pcb_calc_pcie_link_budget`, `pcb_analyze_pcie`
   - USB: `pcb_analyze_usb`
   - Ethernet: `pcb_analyze_ethernet`
   - RF/intentional radiator: `pcb_analyze_trace_antenna`, `pcb_analyze_slot_antenna`
4. **For every market in the standards shortlist**, run the EMC analysers it depends on:
   - Automotive → `pcb_analyze_automotive_emc`, `pcb_analyze_return_paths`, `pcb_analyze_smps_emi`, `pcb_analyze_clock_emi`
   - Commercial → `pcb_analyze_conducted_emissions`, `pcb_analyze_near_field`, `pcb_analyze_emi_risk`
   - Medical → `pcb_analyze_esd`, `pcb_analyze_immunity_margin`, `pcb_analyze_cable_coupling`
   - Wireless → `pcb_analyze_trace_antenna`, `pcb_analyze_common_mode`, `pcb_calc_return_loss`
5. Read `pcb_get_emi_hotspots(session_id)` to surface high-risk regions for the report.

**Rules.**
- A failure to run an analyser (exception) is itself a finding — confidence drops to 0.3 and the missing area is flagged for human review.

**Exit condition.** `playbook_pass_state["P3"]` records every analyser called and its finding count.

---

## Pass 4 — Standards verification

**Goal.** Compare predictions to the limits for *every* selected standard, using live data when available.

**Tool sequence per standard.**
1. Live limit lookup (Phase 3 — new):
   - `mcp__emc-regulations__cispr25_limit(class_n, freq_mhz, detector)` *(automotive)*
   - `mcp__emc-regulations__fcc_part15_limit(class, freq_mhz, detector)` *(commercial / wireless)*
   - `mcp__emc-regulations__iso11452_levels(test_method, level)` *(automotive immunity)*
   - `mcp__emc-regulations__iec61000_test_levels(part, level)` *(IEC 61000-4-x immunity)*
   - `mcp__emc-regulations__medical_immunity_levels(class)` *(IEC 60601-1-2)*
   - `mcp__emc-regulations__fcc_part_lookup(part_number)` *(intentional radiator)*
   - `mcp__emc-regulations__protocol_limits(protocol, band)` *(wireless protocols)*
2. Predictions:
   - `pcb_predict_emissions(session_id, standard)` — radiated emissions vs limit line
   - `pcb_predict_compliance(session_id, standard_set)` — go/no-go per standard
   - `pcb_analyze_conducted_emissions(session_id)` — vs LISN-based limits

**Rules.**
- Log compliance margin in dB for every standard. A negative margin is automatically severity ≥ HIGH.
- If `mcp__emc-regulations__*` is unavailable, fall back to the local `analyzers/emc/limits_provider.py` cache and stamp the finding `source="analytical-fallback"`.

**Exit condition.** Every standard in `standards_shortlist` has a margin recorded. `playbook_pass_state["P4"]` updated.

---

## Pass 5 — Simulation escalation

**Goal.** Verify analytical findings that matter with full-wave EM (openEMS) or NEC2 antenna simulation. Cheap analytical heuristics are insufficient for a meticulous review when severity is high or confidence is low.

**Trigger predicate (per finding).**

```
escalate = (severity in {CRITICAL, HIGH} OR confidence < 0.7)
           AND domain in {signal_integrity, emc, antenna, power_integrity_resonance}
```

**Tool sequence.**
1. `pcb_extract_simulation_candidates(session_id)` — orchestrator's candidate list.
2. `pcb_suggest_next_actions(session_id, domains=["si","emc","antenna","pi"])` *(Phase 3 — new)* — returns a prioritised list of `ExternalAction` objects (openEMS / NEC2 / live regs).
3. For each action with `mcp_server="openems"`:
   - Call the matching `mcp__openems__*` tool (`openems_create_microstrip`, `_stripline`, `_via`, `_coupled_lines`, `_patch`, `_dipole`, `_horn`, `_helix`, `_monopole`) with the supplied params.
   - Run `mcp__openems__openems_generate_script` → user executes the simulation (or it runs in CI for synthetic boards).
   - Feed result back via `pcb_attach_external_result(session_id, action_id, result)` — orchestrator re-correlates the finding (`verified=True`, severity may shift up or down within tolerance).
4. For each action with `mcp_server="nec2-antenna"` (triggered when an intentional radiator ≥ 30 MHz is detected):
   - `mcp__nec2-antenna__nec2_create_<type>` then `mcp__nec2-antenna__nec2_simulate`.
   - Attach result; finding gains `simulated_vswr`, `simulated_gain_dbi`, `pattern_null_directions`.
5. `pcb_validate_with_openems(session_id, finding_id)` — closes the loop, sets `verified=True/False` based on tolerance (`SIM_TOLERANCE_PCT=5%`).

**Rules.**
- A simulation `pass` → `verified=True, confidence=0.95, source="openems"`.
- A simulation `warning` → `confidence=0.6`, severity unchanged.
- A simulation `fail` → severity escalates to CRITICAL, a new finding "analytical model invalidated by full-wave" is appended, `source="openems"`.
- Sibling-MCP unavailability is not a blocker: the finding keeps `verified=False, source="analytical"` and the gap is logged for human review.

**Exit condition.** Every triggered finding has either `verified=True` or an explicit `skipped_reason`. `playbook_pass_state["P5"]` updated.

---

## Pass 6 — Cross-domain correlation

**Goal.** Find compound failure modes that single-domain analysers miss.

**Correlations to check.**
- **Thermal × SI** — elevated junction temp shrinks timing margin. Re-check DDR/PCIe eyes if any `thermal` finding ≥ MEDIUM.
- **PDN × EMI** — PDN anti-resonance near a clock harmonic? Re-rate clock_emi findings.
- **EMC × Routing** — return-path break + high di/dt source nearby → escalate to CRITICAL.
- **Mechanical × ESD** — STEP shows accessible mechanical surfaces within 10 mm of a sensitive net without ESD protection → flag.
- **DFM × Grounding** — via pitch < 250 µm near power-return → thermal-relief adequacy.
- **Protection circuit × Interface** *(Phase 4)* — external-facing pin (USB/Ethernet PHY/antenna port) without TVS in schematic.

**Tool sequence.**
- `pcb_analyze_emi_risk(session_id)`, `pcb_analyze_immunity_margin(session_id)` — re-run with full findings as context.
- `pcb_compare_simulation(session_id)` — closes analytical-vs-simulated loop.

**Exit condition.** Risk matrix populated. `playbook_pass_state["P6"]` updated.

---

## Pass 7 — Reporting

**Goal.** Produce the audit-grade deliverable.

**Tool sequence.**
1. Renders:
   - `pcb_render_board(session_id)`, `pcb_export_all_renders(session_id)`
   - `pcb_annotate_board(session_id, findings)` — overlays severity markers at coordinates.
   - `pcb_render_stackup(session_id)`, `pcb_render_net(session_id, net_name)` for high-risk nets.
2. Diagrams *(Phase 3 — drawio_bridge emits the intents)*:
   - `mcp__drawio-engineering__create_pcb_stackup` — always.
   - `mcp__drawio-engineering__create_rf_block_diagram` — if RF detected.
   - `mcp__drawio-engineering__create_emc_test_setup` — one per market.
   - `mcp__drawio-engineering__markup_schematic` — if schematic parsed.
   - Each result attached via `pcb_attach_external_result`; report builder embeds them.
3. `pcb_generate_test_plan(session_id)` — recommended test set per market.
4. `pcb_generate_design_review_report(session_id, formats=["html","docx"])` — refuses to run unless P0–P6 logged; emits PRELIMINARY-stamped output if `force=True`.

**Output sections** (existing template, augmented):
- Executive summary with go/no-go
- Domain score dashboard (EMC / SI / PI / Thermal / DFM)
- Per-domain findings table, severity-sorted
- Embedded board renders with annotated hotspots
- Stackup cross-section + drawio diagrams
- Standards margin table (every standard, measured vs limit, dB margin)
- Simulation appendix (every openEMS / NEC2 run)
- Test plan
- Component / drill / manufacturing notes
- **Reviewer's Notes** appendix (from Pass 8)

**Exit condition.** Report files exist on disk. `playbook_pass_state["P7"]` updated.

---

## Pass 8 — Self-critique

**Goal.** Attack the review for blind spots before delivering.

**Use** `docs/SELF_CRITIQUE_CHECKLIST.md`. At minimum:

1. **Coverage** — every detected interface has its deep validator entry in `P3`? Every standard in shortlist has a limit lookup in `P4`?
2. **Confidence audit** — list every finding with `confidence < 0.8`; justify why it wasn't escalated.
3. **Assumption ledger** — every inferred answer, defaulted standard, missing input — captured.
4. **Counter-evidence** — for each HIGH/CRITICAL finding, what would falsify it? Did we check?
5. **Simulation gap** — any HIGH finding lacking openEMS / NEC2 corroboration → explain.
6. **Standards traceability** — every cited limit links to an `mcp__emc-regulations__*` action_id or `analytical-fallback` flag.
7. **Human review flags** — list items a registered PE should personally verify before signing the report.
8. **Known blind spots** — thermal transients, ESD soft-fail, long-term drift, EOL stackup tolerance, ageing capacitors, supply-chain MPN substitutions.

**Tool.** Append the critique as the "Reviewer's Notes" appendix of the existing report. Re-run `pcb_generate_design_review_report(session_id, regenerate_appendix_only=True)`.

**Exit condition.** All eight items checked. `playbook_pass_state["P8"]` updated. `pcb_finalize_review(session_id)` succeeds. Only then call `pcb_close_session(session_id)`.

---

## State logging — what every pass writes

Each pass appends to `session.playbook_pass_state[pass_id]`:

```jsonc
{
  "pass_id": "P3",
  "started_at": 1714000000.0,
  "completed_at": 1714000045.2,
  "tool_calls": [
    {"name": "pcb_run_design_review", "params": {...}, "result_summary": "..."},
    ...
  ],
  "findings_added": 12,
  "findings_modified": 0,
  "confidence_distribution": {"<0.5": 0, "0.5-0.7": 2, "0.7-0.9": 7, ">0.9": 3},
  "assumptions_logged": ["assumed CISPR-25 class 3 from auto+passenger answers"]
}
```

`pcb_generate_design_review_report` refuses unless P0–P6 entries exist (P7 is itself the report; P8 is the critique appendix). `pcb_finalize_review` refuses unless P8 exists with at least one entry in each checklist category.

---

## Failure modes

- **Missing layout file** → P0 halts. Refuse to continue.
- **Schematic ↔ layout net-count mismatch > 5%** → P2 halts. Surface the discrepancy to the user.
- **All sibling MCPs unavailable** → P4 and P5 use fallbacks; report is stamped "PRELIMINARY — external verification unavailable". Not invalid, just downgraded.
- **A required interview question unanswered** → P1 will not advance. Re-ask the user.
- **Critical finding without simulation verification when sim was available** → P8 catches it and forces re-run of P5.

---

## A worked example

User: *"Review the attached automotive accessory board for CISPR-25 Class 3 + ISO 7637-2 + ISO 11452-4. Files: dashboard.kicad_pcb, dashboard_sch.pdf, dashboard_stackup.json, dashboard_bom.csv, dashboard.step. Product: 12 V dashboard accessory, key-on/off, no engine-bay placement."*

1. **P0** — `pcb_start_professional_review` returns manifest (5 files, no gaps), market=automotive, standards_shortlist=`[CISPR_25_CLASS_3, ISO_11452_4, ISO_7637_2, ISO_16750_2]`.
2. **P1** — Interview pack adds `vehicle_class`, `bus_voltage`, `iso7637_pulses`, `oem_spec`. User answers in one batch. `pcb_set_review_context` applies.
3. **P2** — Parse all five files; 3-way cross-ref flags a footprint mismatch on R47 (HIGH).
4. **P3** — Orchestrator runs 8 analysers; `pcb_analyze_automotive_emc` flags two return-path breaks; `pcb_analyze_smps_emi` flags a 2 MHz SMPS harmonic near the AM-band limit.
5. **P4** — `mcp__emc-regulations__cispr25_limit` returns Class 3 AM-band radiated limit; predicted emission exceeds it by 4 dB (CRITICAL).
6. **P5** — `pcb_suggest_next_actions` returns 3 openEMS escalations. `mcp__openems__*` simulations confirm the AM-band exceedance (verified=True) and one return-path finding is downgraded to MEDIUM after simulation.
7. **P6** — Cross-correlation links the verified AM-band exceedance to the unstitched SMPS return path → recommendation chain.
8. **P7** — Reports generated; drawio creates stackup + RF chain + CISPR-25 test setup diagrams.
9. **P8** — Self-critique flags that the ISO 7637-2 Pulse 5b transient was not simulated (no analyser for transient response yet) → appended to "Reviewer's Notes" as a human-review flag.

Final output: DOCX + HTML report, ~18 pages, 14 findings, 3 verified by simulation, 1 human-review flag, "Go with conditions" verdict. Total agent time: ~6 min, ~28 tool calls.

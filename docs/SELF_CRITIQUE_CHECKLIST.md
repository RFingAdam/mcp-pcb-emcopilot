# Self-Critique Checklist (Pass 8)

A meticulous review ends with Claude attacking its own findings. This checklist is mandatory before `pcb_finalize_review` succeeds. Each item produces a "Reviewer's Notes" entry that is appended to the final report.

The output of Pass 8 is a JSON block, persisted in `session.playbook_pass_state["P8"]["critique"]`. It contains one section per checklist item below.

---

## 1. Coverage check

For every detected interface, is there a deep validator entry logged in Pass 3?

| Interface | Required validators |
|---|---|
| DDR | `pcb_validate_ddr_topology`, `pcb_analyze_ddr_timing_budget`, `pcb_analyze_ddr` |
| PCIe | `pcb_validate_pcie_lanes`, `pcb_calc_pcie_link_budget`, `pcb_analyze_pcie` |
| USB | `pcb_analyze_usb` |
| Ethernet | `pcb_analyze_ethernet` |
| RF/antenna | `pcb_analyze_trace_antenna`, `pcb_analyze_slot_antenna` |

For every standard in the shortlist, is there a Pass 4 limit lookup logged?

**Output.** `{"interfaces_covered": [...], "interfaces_missing_validators": [...], "standards_covered": [...], "standards_missing_lookup": [...]}`

---

## 2. Confidence audit

List every finding with `confidence < 0.8`. For each: did it escalate to Pass 5 (simulation)? If not, why?

**Acceptable reasons to skip simulation:**
- Sibling MCP unavailable at runtime → `source="analytical-fallback"` AND flagged for human review.
- Severity below HIGH AND domain not in escalation set.
- Already verified by a related sibling action.

**Unacceptable.** Skipping because "it seemed fine" or "we ran out of tool budget."

**Output.** `{"low_confidence": [{"finding_id":..., "confidence":..., "escalated":..., "reason":...}, ...]}`

---

## 3. Assumption ledger

Every inference Claude made instead of asking. Common entries:
- "Assumed CISPR-25 Class 3 from `vehicle_class=passenger` + `bus_voltage=12V`."
- "Defaulted target single-ended impedance to 50 Ω because user didn't specify."
- "Inferred ISO 11452-4 BCI level 4 from `oem_spec=Ford_EMC-CS-2009`."

**Output.** `{"assumptions": [{"assumption": "...", "source": "...", "could_be_wrong_because": "..."}]}`

---

## 4. Counter-evidence

For each CRITICAL and HIGH finding, what would *falsify* it? Did Claude check?

Example template:
- Finding: `EMC-007: SMPS harmonic at 6 MHz exceeds CISPR-25 Class 3 AM band by 4 dB`.
- Counter-evidence to check: SMPS actually disabled in this product variant? Harmonic suppressed by a downstream filter (BOM line F1)? Customer's CISPR-25 test setup uses 1 m antenna distance, not 50 cm?
- Verified: yes, F1 = 100 nH π-filter, but π-filter resonance is *above* 6 MHz → finding holds.

**Output.** `{"high_critical_findings": [{"finding_id":..., "counter_evidence_considered":..., "verdict":...}, ...]}`

---

## 5. Simulation gap

Findings flagged HIGH or CRITICAL that *should* have been simulated but weren't.

Possible causes:
- Sibling MCP unavailable → must be flagged for human review.
- Geometry too complex for openEMS auto-extraction → must produce a manual-modeling recommendation.
- Trigger predicate missed an edge case → log as a playbook bug.

**Output.** `{"sim_gaps": [{"finding_id":..., "reason":..., "human_review_required": true}]}`

---

## 6. Standards traceability

Every cited limit value must trace back to either:
- An `action_id` in `session.external_results` pointing to a `mcp__emc-regulations__*` call, OR
- A `source="analytical-fallback"` flag with the local table reference (file:line).

Limits that are pulled from neither (e.g. cited from training-data memory) are a critical traceability failure.

**Output.** `{"traceability_failures": [{"finding_id":..., "cited_limit":..., "source":...}, ...]}`

---

## 7. Human-review flags

Items that a human Professional Engineer (PE) must verify personally before signing the report. These are not Claude's failures — they are out-of-scope items that need human expertise.

**Always-included flags:**
- Schematic-derived intent (Claude reads schematics; PE reads design intent).
- Long-term reliability (FIT rates, MTBF, ageing-component derating beyond 80%).
- Functional-safety qualitative arguments (ISO 26262, IEC 61508 FMEA quality).
- ESD soft-failure (analytical-only; lab measurement needed).
- ISO 7637-2 transients (no analytical model yet — Phase 4 stub).
- Variant differences (DNP assemblies, BOM swaps, region-specific firmware).

**Conditional flags:**
- Wireless: SAR if device near body, OTA performance, regulatory submission paperwork.
- Medical: risk-analysis traceability to IEC 62304 (software) and ISO 14971 (risk).

**Output.** `{"human_review_required": ["...", "..."]}`

---

## 8. Known blind spots

Things this review **cannot** detect, called out explicitly so the user knows what's missing:

- **Thermal transients** — analyses are steady-state.
- **ESD soft-fail / latch-up** — only static voltage-margin checks.
- **Long-term drift** — capacitor ageing, electromigration, solder-joint cycling.
- **EOL stackup tolerance** — fab variation across lots not modelled.
- **Supply-chain MPN substitutions** — alternates in BOM not always equivalent.
- **EMC chamber-vs-prediction delta** — analytical predictions are approximate; chamber measurement is the source of truth.
- **Cross-talk through reference-plane gaps** — heuristic only; full 3D field solve only when escalated.
- **Connector/cable contributions** — analyses end at the board edge; cable/connector EMI is out-of-scope unless `cable_coupling` was run with cable data.

**Output.** `{"blind_spots_acknowledged": ["...", "..."]}`

---

## Final emission

After all 8 items, emit the consolidated JSON into the report's "Reviewer's Notes" appendix:

```jsonc
{
  "review_critique_version": "1.0",
  "checklist_version": "2026-05-14",
  "coverage": { ... },
  "confidence_audit": { ... },
  "assumption_ledger": { ... },
  "counter_evidence": { ... },
  "sim_gaps": { ... },
  "traceability_failures": { ... },
  "human_review_required": [ ... ],
  "blind_spots_acknowledged": [ ... ],
  "summary_one_line": "12 findings reviewed; 3 escalated to simulation; 2 human-review flags raised."
}
```

`pcb_finalize_review(session_id)` parses this JSON and:
- Fails if any of `coverage.standards_missing_lookup` is non-empty AND `require_critical_verified=True`.
- Warns if `traceability_failures` is non-empty.
- Succeeds otherwise, returning the path of the finalised report.

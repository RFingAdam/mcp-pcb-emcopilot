# Market Intake Matrix

Per-market question packs and the standards / analyzers each market activates. Used by `pcb_start_professional_review`, `pcb_get_review_questions`, and `pcb_set_market`.

A review can have **multiple** active markets (e.g. *medical + wireless* for a connected medical device). Each market contributes a question pack and a set of standards. Packs are additive; duplicate questions are deduped by `id`.

---

## Question packs (summary)

| Market | Questions | Triggers |
|---|---|---|
| `core` | 10 | Always included. DDR / USB / RF / battery / impedance / environment. |
| `automotive` | 8 | Vehicle class, bus voltage, ISO 26262 ASIL, CISPR-25 class, OEM spec, key-state scope, ISO 7637 pulses, load-dump tolerance. |
| `medical` | 6 | Device class, patient contact, MRI compatibility, IEC 60601 edition, ground-fault limit, defib-proof. |
| `wireless` | 8 | Intentional radiator, TX power, antenna gain, FCC part, modulation, duty cycle, frequency bands, module cert strategy. |
| `commercial` | 6 | Target regions, CISPR 32 class, IEC 61000-4 immunity level, IEC 61000-3-2 class, LVD scope, product environment. |
| `industrial` | 7 | Hazloc class, IP rating, vibration profile, ambient range, EN 61326 immunity, pollution degree, surge target. |

---

## Automotive pack

| ID | Question | Type | Default |
|---|---|---|---|
| `vehicle_class` | Passenger / commercial / agricultural / off-road / EV-high-voltage? | choice | passenger |
| `bus_voltage` | 12 V / 24 V / 48 V / HV-traction? | choice | 12V |
| `iso26262_asil` | ASIL level (QM / A / B / C / D)? | choice | QM |
| `cispr25_class` | CISPR-25 emissions class (1–5)? | number | 3 |
| `oem_spec` | OEM-specific spec? (Ford EMC-CS-2009, GMW3097, VW80000, PSA B21-7110, none) | choice | none |
| `key_state_scope` | Test scope: off / accessory / on / cranking? | multi | on |
| `iso7637_pulses` | Required ISO 7637-2 pulses (1, 2a, 2b, 3a, 3b, 4, 5a, 5b)? | multi | 1,2a,2b,3a,3b |
| `load_dump_tolerance` | Active clamp / TVS / both / neither for load-dump? | choice | TVS |

**Standards activated.** `CISPR_25_CLASS_<n>`, `ISO_11452_2`, `ISO_11452_4`, `ISO_11452_5`, `ISO_7637_2`, `ISO_7637_3`, `ISO_16750_2`. Add `UNECE_R10` if vehicle_class=passenger and region=EU.

**Analyzers activated.** `automotive_emc`, `smps_emi`, `clock_emi`, `return_paths`, `conducted_emissions`, `near_field`, `immunity_margin`. With `oem_spec≠none` add a stricter limit overlay (Ford / GM / VW thresholds tighter than CISPR-25 baseline).

---

## Medical pack

| ID | Question | Type | Default |
|---|---|---|---|
| `device_class` | Class I / IIa / IIb / III? | choice | IIa |
| `patient_contact` | None / applied / Type B / Type BF / Type CF? | choice | applied |
| `mri_compatibility` | None / MR-conditional / MR-safe? | choice | none |
| `iec60601_edition` | IEC 60601-1-2 edition (4.0 / 4.1)? | choice | 4.1 |
| `ground_fault_limit_uA` | Earth-leakage limit (10 / 50 / 100 / 500 µA)? | choice | 100 |
| `defib_proof` | Defibrillation-proof requirement? | bool | false |

**Standards activated.** `IEC_60601_1_2_ED_4_1`, `IEC_61000_4_2`, `IEC_61000_4_3`, `IEC_61000_4_4`, `IEC_61000_4_5`, `IEC_61000_4_6`, `IEC_61000_4_8`, `IEC_61000_4_11`. Add `IEC_60601_1_11` if home-healthcare environment. Defib-proof → extra surge-immunity overlay.

**Analyzers activated.** `esd`, `immunity_margin`, `cable_coupling`, `conducted_emissions`, `protection_circuits` (Phase 4).

---

## Wireless / RF pack

| ID | Question | Type | Default |
|---|---|---|---|
| `intentional_radiator` | Yes / no? | bool | true |
| `tx_power_dbm` | Maximum conducted TX power (dBm)? | number | 20 |
| `antenna_gain_dbi` | Antenna gain (dBi)? | number | 2 |
| `fcc_part` | 15B / 15C / 15E / 95 / 22 / 24 / 27 / 22H / 74? | choice | 15C |
| `modulation` | OFDM / DSSS / FHSS / Bluetooth / LoRa / proprietary? | choice | OFDM |
| `duty_cycle_pct` | Duty cycle (%)? | number | 100 |
| `frequency_bands_mhz` | Operating bands (multi, e.g. 2400-2483.5, 5150-5350)? | text | "" |
| `module_cert_strategy` | FCC-ID-modular / host-cert / SDOC? | choice | FCC-ID-modular |

**Standards activated.** `FCC_47_CFR_<part>`, `ETSI_EN_300_328` (2.4 GHz), `ETSI_EN_301_893` (5 GHz), `ETSI_EN_303_413` (GNSS), `ISED_RSS-247`. `EN_301_489-x` immunity overlays per radio class.

**Analyzers activated.** `trace_antenna`, `slot_antenna`, `common_mode`, `cable_coupling`, `return_loss`. NEC2 escalation mandatory in Pass 5 when `intentional_radiator=true` and frequency ≥ 30 MHz.

---

## Commercial pack

| ID | Question | Type | Default |
|---|---|---|---|
| `target_regions` | US / EU / JP / CN / KR (multi)? | multi | US,EU |
| `cispr32_class` | Class A (industrial) or Class B (residential)? | choice | B |
| `iec61000_4_immunity_level` | 1 / 2 / 3 / 4? | choice | 3 |
| `iec61000_3_2_class` | A / B / C / D / not-applicable? | choice | not-applicable |
| `low_voltage_directive_scope` | In scope of EU LVD? | bool | false |
| `product_environment` | Residential / light-industrial / heavy-industrial? | choice | residential |

**Standards activated.** `FCC_PART_15_B` (US), `CISPR_32_CLASS_<X>` + `EN_55032` (EU), `VCCI_<X>` (JP), `GB_9254` (CN), `KN_32` (KR). Plus `IEC_61000_4_2/3/4/5/6/8/11` immunity tests.

**Analyzers activated.** `conducted_emissions`, `near_field`, `emi_risk`, `clock_emi`, `current_loop`.

---

## Industrial pack

| ID | Question | Type | Default |
|---|---|---|---|
| `hazloc_class` | None / Class I Div 1 / Class I Div 2 / ATEX Zone 1 / ATEX Zone 2? | choice | none |
| `ip_rating` | IP00 – IP69K? | choice | IP54 |
| `vibration_profile` | IEC 60068-2-6 level? | choice | 2g |
| `ambient_temp_range_C` | Min / max (°C, comma-separated)? | text | -25,70 |
| `en61326_immunity` | Industrial / laboratory / portable? | choice | industrial |
| `pollution_degree` | 1 / 2 / 3 / 4? | choice | 2 |
| `surge_target_kV` | 0.5 / 1 / 2 / 4 kV per IEC 61000-4-5? | choice | 2 |

**Standards activated.** `EN_61326_<env>`, `IEC_61000_6_2` (industrial immunity), `IEC_61000_6_4` (industrial emissions), `IEC_61131_2` if PLC, `ATEX_2014_34_EU` if hazloc≠none.

**Analyzers activated.** `conducted_emissions`, `esd`, `immunity_margin`, `cable_coupling`, `near_field`.

---

## Multi-market combinations

A connected medical patient monitor with BLE radio activates **`medical + wireless`** packs simultaneously:

- Standards become the union: `IEC_60601_1_2_ED_4_1`, `IEC_61000_4_*`, `FCC_47_CFR_15C`, `ETSI_EN_300_328`, `EN_301_489-17`.
- Analyzers become the union: ESD + immunity + cable coupling + trace antenna + NEC2 escalation.
- Pre-flight gate refuses report generation unless **every** standard in the union has a margin recorded.

Automotive infotainment with Wi-Fi: **`automotive + wireless`**. CISPR-25 + ISO 11452 + FCC Part 15C + EN 301 489-17. Note the cellular bands trigger automotive-specific cellular intermod checks (above CISPR-25's 1 GHz baseline).

---

## Activation matrix (compact)

For the runtime mirror, see `src/mcp_pcb_emcopilot/standards/coverage.py::STANDARD_TO_ANALYZERS`.

| Standard | Pack | Required analyzers | Limit source | Coverage |
|---|---|---|---|---|
| CISPR_25_CLASS_1..5 | automotive | automotive_emc, return_paths, smps_emi, clock_emi | emc-regulations + local fallback | full |
| ISO_11452_2/4/5 | automotive | immunity_margin, cable_coupling | emc-regulations | full |
| ISO_7637_2 | automotive | (transient) — Phase 4 stub | local | stub |
| ISO_16750_2 | automotive | (env) — local heuristics | local | partial |
| FCC_PART_15_B | commercial / wireless | conducted_emissions, near_field, emi_risk | emc-regulations + local fallback | full |
| CISPR_32_CLASS_A/B | commercial | conducted_emissions, near_field, clock_emi | emc-regulations | full |
| IEC_60601_1_2_ED_4_1 | medical | esd, immunity_margin, cable_coupling | emc-regulations | full |
| IEC_61000_4_2..11 | commercial / medical / industrial | esd, immunity_margin | emc-regulations | full |
| EN_300_328 | wireless | trace_antenna, return_loss, NEC2-escalate | emc-regulations + nec2 | full |
| EN_301_893 | wireless | trace_antenna, return_loss | emc-regulations | full |
| EN_61326_industrial | industrial | conducted_emissions, immunity_margin, esd | emc-regulations | full |
| MIL_STD_461G | (military, out-of-scope today) | — | — | unimplemented |

---

## Pre-flight gate behaviour

`pcb_validate_review_complete(session_id)` (Phase 4 — new) returns:

```jsonc
{
  "ready": false,
  "missing_questions": ["vehicle_class", "iso26262_asil"],
  "missing_standard_selection": false,
  "blocking_findings": []
}
```

`pcb_run_design_review` and `pcb_generate_design_review_report` both call this and refuse to advance unless `ready=true` (overridable with `force_run=true`, which stamps the report PRELIMINARY).

"""Market-specific question packs and standards bundles.

Data-only module. Consumed by:
- ``review_playbook.build_interview_pack`` — to compose the per-session interview.
- ``review_context.get_review_questions`` — to merge the core + market packs.
- ``standards.coverage`` (Phase 4) — to map markets to required analyzers.

Adding a new market = adding a single dict entry to ``QUESTION_BANK`` plus an
entry in ``MARKET_STANDARDS`` and ``MARKET_ANALYZERS``. No new code paths.
"""

from __future__ import annotations

from typing import Any

# =============================================================================
# Per-market question packs
# =============================================================================

QUESTION_BANK: dict[str, list[dict[str, Any]]] = {
    "automotive": [
        {
            "id": "vehicle_class",
            "category": "automotive",
            "text": "Vehicle class?",
            "type": "choice",
            "choices": ["passenger", "commercial", "agricultural", "off-road", "EV-high-voltage"],
            "default": "passenger",
            "why": (
                "Vehicle class determines CISPR-25 antenna distance, "
                "ISO 11452 levels, and OEM-overlay applicability."
            ),
        },
        {
            "id": "bus_voltage",
            "category": "automotive",
            "text": "Primary bus voltage?",
            "type": "choice",
            "choices": ["12V", "24V", "48V", "HV-traction"],
            "default": "12V",
            "why": "Drives ISO 16750-2 pulse set and ISO 7637 transient amplitudes.",
        },
        {
            "id": "iso26262_asil",
            "category": "automotive",
            "text": "ISO 26262 ASIL level?",
            "type": "choice",
            "choices": ["QM", "A", "B", "C", "D"],
            "default": "QM",
            "why": "Functional-safety classification — affects diagnostic-coverage and redundancy review.",
        },
        {
            "id": "cispr25_class",
            "category": "automotive",
            "text": "CISPR-25 emissions class target (1=loosest, 5=strictest)?",
            "type": "number",
            "default": 3,
            "why": "Sets the radiated-emissions limit line used in Pass 4 standards verification.",
        },
        {
            "id": "oem_spec",
            "category": "automotive",
            "text": "OEM-specific EMC spec?",
            "type": "choice",
            "choices": ["none", "Ford_EMC-CS-2009", "GMW3097", "VW_TL_81000", "PSA_B21-7110", "other"],
            "default": "none",
            "why": "OEM specs usually impose tighter limits than CISPR-25; overlay applied automatically.",
        },
        {
            "id": "key_state_scope",
            "category": "automotive",
            "text": "Key states in test scope (multi)?",
            "type": "multi",
            "choices": ["off", "accessory", "on", "cranking"],
            "default": ["on"],
            "why": "Defines which power modes must comply — cranking includes low-voltage operation per ISO 16750.",
        },
        {
            "id": "iso7637_pulses",
            "category": "automotive",
            "text": "ISO 7637-2 pulses required (multi)?",
            "type": "multi",
            "choices": ["1", "2a", "2b", "3a", "3b", "4", "5a", "5b"],
            "default": ["1", "2a", "2b", "3a", "3b"],
            "why": "Selects the transient pulse set the design must survive.",
        },
        {
            "id": "load_dump_tolerance",
            "category": "automotive",
            "text": "Load-dump protection scheme?",
            "type": "choice",
            "choices": ["TVS", "active_clamp", "both", "neither"],
            "default": "TVS",
            "why": "Pulse 5a/5b survival depends on the input protection; reviewed against ISO 7637-2 Annex.",
        },
    ],
    "medical": [
        {
            "id": "device_class",
            "category": "medical",
            "text": "Medical device class?",
            "type": "choice",
            "choices": ["I", "IIa", "IIb", "III"],
            "default": "IIa",
            "why": "Class drives IEC 60601-1-2 immunity levels and risk-management depth.",
        },
        {
            "id": "patient_contact",
            "category": "medical",
            "text": "Patient-contact type?",
            "type": "choice",
            "choices": ["none", "applied", "type_B", "type_BF", "type_CF"],
            "default": "applied",
            "why": "Contact type determines isolation, leakage-current, and defib-proof requirements.",
        },
        {
            "id": "mri_compatibility",
            "category": "medical",
            "text": "MRI compatibility required?",
            "type": "choice",
            "choices": ["none", "MR-conditional", "MR-safe"],
            "default": "none",
            "why": "MR-conditional / MR-safe imposes magnetic-field immunity and material restrictions.",
        },
        {
            "id": "iec60601_edition",
            "category": "medical",
            "text": "IEC 60601-1-2 edition target?",
            "type": "choice",
            "choices": ["4.0", "4.1"],
            "default": "4.1",
            "why": "Ed 4.1 adds coexistence-test §8.10 and tighter ESD requirements.",
        },
        {
            "id": "ground_fault_limit_uA",
            "category": "medical",
            "text": "Earth-leakage / ground-fault current limit (µA)?",
            "type": "choice",
            "choices": ["10", "50", "100", "500"],
            "default": "100",
            "why": "Combined with patient_contact selects the IEC 60601-1 leakage class.",
        },
        {
            "id": "defib_proof",
            "category": "medical",
            "text": "Defibrillation-proof requirement?",
            "type": "bool",
            "default": False,
            "why": "Defib-proof imposes a 5 kV pulse immunity and added isolation barriers.",
        },
    ],
    "wireless": [
        {
            "id": "intentional_radiator",
            "category": "wireless",
            "text": "Is this device an intentional radiator?",
            "type": "bool",
            "default": True,
            "why": "Drives FCC Part 15C/95 applicability and mandates NEC2 escalation in Pass 5.",
        },
        {
            "id": "tx_power_dbm",
            "category": "wireless",
            "text": "Maximum conducted TX power (dBm)?",
            "type": "number",
            "default": 20,
            "why": "TX power combined with antenna gain sets EIRP and determines SAR/MPE applicability.",
        },
        {
            "id": "antenna_gain_dbi",
            "category": "wireless",
            "text": "Antenna gain (dBi)?",
            "type": "number",
            "default": 2,
            "why": "Used for EIRP calculation and harmonics limit verification.",
        },
        {
            "id": "fcc_part",
            "category": "wireless",
            "text": "FCC Part?",
            "type": "choice",
            "choices": ["15B", "15C", "15E", "95", "22", "24", "27", "22H", "74"],
            "default": "15C",
            "why": "Picks the specific FCC limit set and restricted bands.",
        },
        {
            "id": "modulation",
            "category": "wireless",
            "text": "Modulation type?",
            "type": "choice",
            "choices": ["OFDM", "DSSS", "FHSS", "Bluetooth", "LoRa", "proprietary"],
            "default": "OFDM",
            "why": "Modulation affects spectrum mask, duty-cycle averaging, and intermod analysis.",
        },
        {
            "id": "duty_cycle_pct",
            "category": "wireless",
            "text": "Duty cycle (%)?",
            "type": "number",
            "default": 100,
            "why": "Drives average-power-vs-peak limit application.",
        },
        {
            "id": "frequency_bands_mhz",
            "category": "wireless",
            "text": "Operating bands (comma-separated MHz ranges, e.g. '2400-2483.5, 5150-5350')?",
            "type": "text",
            "default": "",
            "why": "Selects per-band limits and restricted-band collision checks.",
        },
        {
            "id": "module_cert_strategy",
            "category": "wireless",
            "text": "Certification strategy?",
            "type": "choice",
            "choices": ["FCC-ID-modular", "host-cert", "SDOC"],
            "default": "FCC-ID-modular",
            "why": "Modular use of a pre-certified radio module shifts the burden of compliance verification.",
        },
    ],
    "commercial": [
        {
            "id": "target_regions",
            "category": "commercial",
            "text": "Target market regions (multi)?",
            "type": "multi",
            "choices": ["US", "EU", "JP", "CN", "KR"],
            "default": ["US", "EU"],
            "why": "Each region applies its own EMC standard family (FCC / CISPR / VCCI / GB / KN).",
        },
        {
            "id": "cispr32_class",
            "category": "commercial",
            "text": "CISPR 32 class?",
            "type": "choice",
            "choices": ["A", "B"],
            "default": "B",
            "why": "Class A (industrial) is 10 dB looser than Class B (residential).",
        },
        {
            "id": "iec61000_4_immunity_level",
            "category": "commercial",
            "text": "IEC 61000-4 immunity level target?",
            "type": "choice",
            "choices": ["1", "2", "3", "4"],
            "default": "3",
            "why": "Level 3 is typical industrial; level 2 residential; level 4 harsh environment.",
        },
        {
            "id": "iec61000_3_2_class",
            "category": "commercial",
            "text": "IEC 61000-3-2 harmonics class?",
            "type": "choice",
            "choices": ["A", "B", "C", "D", "not-applicable"],
            "default": "not-applicable",
            "why": "Applies to mains-connected equipment above 75 W input.",
        },
        {
            "id": "low_voltage_directive_scope",
            "category": "commercial",
            "text": "In scope of EU Low-Voltage Directive?",
            "type": "bool",
            "default": False,
            "why": "LVD applies to 50–1000 V AC / 75–1500 V DC equipment.",
        },
        {
            "id": "product_environment",
            "category": "commercial",
            "text": "Product environment?",
            "type": "choice",
            "choices": ["residential", "light-industrial", "heavy-industrial"],
            "default": "residential",
            "why": "Selects the immunity-test severity overlay.",
        },
    ],
    "industrial": [
        {
            "id": "hazloc_class",
            "category": "industrial",
            "text": "Hazardous-location classification?",
            "type": "choice",
            "choices": ["none", "Class_I_Div_1", "Class_I_Div_2", "ATEX_Zone_1", "ATEX_Zone_2"],
            "default": "none",
            "why": "Hazloc classes impose intrinsic-safety and material restrictions.",
        },
        {
            "id": "ip_rating",
            "category": "industrial",
            "text": "Enclosure IP rating target?",
            "type": "choice",
            "choices": ["IP00", "IP20", "IP54", "IP65", "IP67", "IP69K"],
            "default": "IP54",
            "why": "Drives sealing, gasket EMC, and shield-gap analysis.",
        },
        {
            "id": "vibration_profile",
            "category": "industrial",
            "text": "Vibration profile (IEC 60068-2-6)?",
            "type": "choice",
            "choices": ["1g", "2g", "5g", "10g"],
            "default": "2g",
            "why": "Affects solder-joint reliability and connector retention review.",
        },
        {
            "id": "ambient_temp_range_C",
            "category": "industrial",
            "text": "Ambient temperature range (°C, min,max)?",
            "type": "text",
            "default": "-25,70",
            "why": "Thermal analysis baseline and component derating.",
        },
        {
            "id": "en61326_immunity",
            "category": "industrial",
            "text": "EN 61326 environment?",
            "type": "choice",
            "choices": ["industrial", "laboratory", "portable"],
            "default": "industrial",
            "why": "Selects immunity-level overlay for IEC 61000-4-x tests.",
        },
        {
            "id": "pollution_degree",
            "category": "industrial",
            "text": "Pollution degree (IEC 60664)?",
            "type": "choice",
            "choices": ["1", "2", "3", "4"],
            "default": "2",
            "why": "Drives creepage / clearance distance requirements.",
        },
        {
            "id": "surge_target_kV",
            "category": "industrial",
            "text": "IEC 61000-4-5 surge target (kV)?",
            "type": "choice",
            "choices": ["0.5", "1", "2", "4"],
            "default": "2",
            "why": "Selects surge-protection sizing.",
        },
    ],
}


# =============================================================================
# Market → standards mapping
# =============================================================================

MARKET_STANDARDS: dict[str, list[str]] = {
    "automotive": [
        "CISPR_25",
        "ISO_11452_2",
        "ISO_11452_4",
        "ISO_11452_5",
        "ISO_7637_2",
        "ISO_7637_3",
        "ISO_16750_2",
    ],
    "medical": [
        "IEC_60601_1_2_ED_4_1",
        "IEC_61000_4_2",
        "IEC_61000_4_3",
        "IEC_61000_4_4",
        "IEC_61000_4_5",
        "IEC_61000_4_6",
        "IEC_61000_4_8",
        "IEC_61000_4_11",
    ],
    "wireless": [
        "FCC_47_CFR_15C",
        "ETSI_EN_300_328",
        "ETSI_EN_301_893",
        "ETSI_EN_303_413",
        "ISED_RSS-247",
        "EN_301_489",
    ],
    "commercial": [
        "FCC_PART_15_B",
        "CISPR_32",
        "EN_55032",
        "IEC_61000_4_2",
        "IEC_61000_4_3",
        "IEC_61000_4_4",
        "IEC_61000_4_5",
        "IEC_61000_4_6",
        "IEC_61000_4_8",
        "IEC_61000_4_11",
    ],
    "industrial": [
        "EN_61326",
        "IEC_61000_6_2",
        "IEC_61000_6_4",
        "IEC_61000_4_2",
        "IEC_61000_4_4",
        "IEC_61000_4_5",
    ],
}


# =============================================================================
# Market → analyzer ids it activates
# =============================================================================

MARKET_ANALYZERS: dict[str, list[str]] = {
    "automotive": [
        "automotive_emc",
        "smps_emi",
        "clock_emi",
        "return_paths",
        "conducted_emissions",
        "near_field",
        "immunity_margin",
    ],
    "medical": [
        "esd",
        "immunity_margin",
        "cable_coupling",
        "conducted_emissions",
        "near_field",
    ],
    "wireless": [
        "trace_antenna",
        "slot_antenna",
        "common_mode",
        "cable_coupling",
        "return_loss",
    ],
    "commercial": [
        "conducted_emissions",
        "near_field",
        "emi_risk",
        "clock_emi",
        "current_loop",
    ],
    "industrial": [
        "conducted_emissions",
        "esd",
        "immunity_margin",
        "cable_coupling",
        "near_field",
    ],
}


# =============================================================================
# Helpers
# =============================================================================

KNOWN_MARKETS: tuple[str, ...] = tuple(QUESTION_BANK.keys())


def get_pack(market: str) -> list[dict[str, Any]]:
    """Return a deep copy of the question pack for a market (empty if unknown)."""
    pack = QUESTION_BANK.get(market, [])
    return [dict(q) for q in pack]


def get_standards(market: str) -> list[str]:
    """Return the standards list for a market (empty if unknown)."""
    return list(MARKET_STANDARDS.get(market, []))


def get_analyzers(market: str) -> list[str]:
    """Return the analyzer-id list for a market (empty if unknown)."""
    return list(MARKET_ANALYZERS.get(market, []))


def merge_packs(markets: list[str]) -> list[dict[str, Any]]:
    """Merge per-market packs deduped by question id (preserves first occurrence)."""
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for m in markets:
        for q in get_pack(m):
            if q["id"] in seen:
                continue
            seen.add(q["id"])
            merged.append(q)
    return merged


def merge_standards(markets: list[str]) -> list[str]:
    """Union of standards across markets, deduped, order preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for m in markets:
        for s in get_standards(m):
            if s in seen:
                continue
            seen.add(s)
            out.append(s)
    return out


def merge_analyzers(markets: list[str]) -> list[str]:
    """Union of analyzers across markets, deduped, order preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for m in markets:
        for a in get_analyzers(m):
            if a in seen:
                continue
            seen.add(a)
            out.append(a)
    return out

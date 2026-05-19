"""Standards → required-analyzer mapping and coverage classification.

For every supported standard we record:
- ``required_analyzers`` — the analyzer ids that must run to claim compliance
  (these are the ``orchestrator._select_analyzers`` keys).
- ``limit_source`` — ``"local_fallback"`` if the in-process tables in
  ``analyzers.emc.limits_provider`` can fully resolve the standard's limit
  values, ``"emc-regulations"`` if a live sibling-MCP lookup is the
  authoritative source.
- ``coverage_level`` — ``"full"`` / ``"partial"`` / ``"stub"`` based on
  current analyzer + limit-provider state.

The mirror human-readable matrix lives at
``docs/STANDARDS_COVERAGE_MATRIX.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CoverageLevel = Literal["full", "partial", "stub", "unimplemented"]


# =============================================================================
# Standard → metadata map
# =============================================================================

STANDARD_TO_ANALYZERS: dict[str, dict[str, Any]] = {
    # Automotive
    "CISPR_25": {
        "required_analyzers": ["automotive_emc", "return_paths", "smps_emi", "clock_emi"],
        "limit_source": "local_fallback",
        "coverage_level": "full",
        "pack": "automotive",
        "notes": "CISPR 25 radiated + conducted emissions, classes 1-5.",
    },
    "ISO_11452_2": {
        "required_analyzers": ["immunity_margin", "cable_coupling"],
        "limit_source": "local_fallback",
        "coverage_level": "full",
        "pack": "automotive",
        "notes": "ISO 11452-2 field strength immunity.",
    },
    "ISO_11452_4": {
        "required_analyzers": ["immunity_margin", "cable_coupling"],
        "limit_source": "local_fallback",
        "coverage_level": "full",
        "pack": "automotive",
        "notes": "ISO 11452-4 BCI bulk current injection.",
    },
    "ISO_11452_5": {
        "required_analyzers": ["immunity_margin"],
        "limit_source": "local_fallback",
        "coverage_level": "partial",
        "pack": "automotive",
        "notes": "ISO 11452-5 stripline; analytical only.",
    },
    "ISO_7637_2": {
        "required_analyzers": [],  # no transient analyzer yet
        "limit_source": "emc-regulations",
        "coverage_level": "stub",
        "pack": "automotive",
        "notes": "ISO 7637-2 transient pulses — no analytical model yet, surface to user as human-review.",
    },
    "ISO_7637_3": {
        "required_analyzers": [],
        "limit_source": "emc-regulations",
        "coverage_level": "stub",
        "pack": "automotive",
        "notes": "ISO 7637-3 signal-line transients — stub.",
    },
    "ISO_16750_2": {
        "required_analyzers": ["immunity_margin"],
        "limit_source": "local_fallback",
        "coverage_level": "partial",
        "pack": "automotive",
        "notes": "ISO 16750-2 environmental conditions; analytical heuristics only.",
    },

    # Commercial
    "FCC_PART_15_B": {
        "required_analyzers": ["conducted_emissions", "near_field", "emi_risk", "clock_emi"],
        "limit_source": "local_fallback",
        "coverage_level": "full",
        "pack": "commercial",
    },
    "FCC_PART_15_A": {
        "required_analyzers": ["conducted_emissions", "near_field", "emi_risk"],
        "limit_source": "local_fallback",
        "coverage_level": "full",
        "pack": "commercial",
    },
    "CISPR_32": {
        "required_analyzers": ["conducted_emissions", "near_field", "clock_emi"],
        "limit_source": "local_fallback",
        "coverage_level": "full",
        "pack": "commercial",
    },
    "EN_55032": {
        "required_analyzers": ["conducted_emissions", "near_field", "clock_emi"],
        "limit_source": "local_fallback",
        "coverage_level": "full",
        "pack": "commercial",
        "notes": "EU harmonised equivalent of CISPR 32.",
    },
    "IEC_61000_4_2": {
        "required_analyzers": ["esd", "immunity_margin"],
        "limit_source": "local_fallback",
        "coverage_level": "full",
        "pack": "commercial",
    },
    "IEC_61000_4_3": {
        "required_analyzers": ["immunity_margin", "cable_coupling"],
        "limit_source": "local_fallback",
        "coverage_level": "full",
        "pack": "commercial",
    },
    "IEC_61000_4_4": {
        "required_analyzers": ["immunity_margin"],
        "limit_source": "local_fallback",
        "coverage_level": "partial",
        "pack": "commercial",
    },
    "IEC_61000_4_5": {
        "required_analyzers": ["immunity_margin"],
        "limit_source": "local_fallback",
        "coverage_level": "partial",
        "pack": "commercial",
        "notes": "Surge immunity — analytical envelope only.",
    },
    "IEC_61000_4_6": {
        "required_analyzers": ["immunity_margin", "cable_coupling"],
        "limit_source": "local_fallback",
        "coverage_level": "partial",
        "pack": "commercial",
    },
    "IEC_61000_4_8": {
        "required_analyzers": ["immunity_margin"],
        "limit_source": "local_fallback",
        "coverage_level": "partial",
        "pack": "commercial",
    },
    "IEC_61000_4_11": {
        "required_analyzers": [],
        "limit_source": "emc-regulations",
        "coverage_level": "stub",
        "pack": "commercial",
    },

    # Medical
    "IEC_60601_1_2_ED_4_1": {
        "required_analyzers": ["esd", "immunity_margin", "cable_coupling"],
        "limit_source": "local_fallback",
        "coverage_level": "full",
        "pack": "medical",
    },
    "IEC_60601_1_2_ED_4_0": {
        "required_analyzers": ["esd", "immunity_margin", "cable_coupling"],
        "limit_source": "local_fallback",
        "coverage_level": "full",
        "pack": "medical",
    },
    "IEC_60601_1_2": {
        "required_analyzers": ["esd", "immunity_margin", "cable_coupling"],
        "limit_source": "local_fallback",
        "coverage_level": "full",
        "pack": "medical",
        "notes": "Alias for the current edition (4.1).",
    },

    # Wireless / RF
    "FCC_47_CFR_15C": {
        "required_analyzers": ["trace_antenna", "slot_antenna", "common_mode", "return_loss"],
        "limit_source": "emc-regulations",
        "coverage_level": "partial",
        "pack": "wireless",
        "notes": "Intentional radiator rules — NEC2 escalation recommended.",
    },
    "FCC_PART_15_C": {
        "required_analyzers": ["trace_antenna", "slot_antenna", "common_mode", "return_loss"],
        "limit_source": "emc-regulations",
        "coverage_level": "partial",
        "pack": "wireless",
        "notes": "Alias for FCC_47_CFR_15C.",
    },
    "ETSI_EN_300_328": {
        "required_analyzers": ["trace_antenna", "return_loss"],
        "limit_source": "emc-regulations",
        "coverage_level": "partial",
        "pack": "wireless",
    },
    "ETSI_EN_301_893": {
        "required_analyzers": ["trace_antenna", "return_loss"],
        "limit_source": "emc-regulations",
        "coverage_level": "partial",
        "pack": "wireless",
    },
    "ETSI_EN_303_413": {
        "required_analyzers": ["trace_antenna"],
        "limit_source": "emc-regulations",
        "coverage_level": "partial",
        "pack": "wireless",
        "notes": "GNSS receivers.",
    },
    "ISED_RSS-247": {
        "required_analyzers": ["trace_antenna", "return_loss"],
        "limit_source": "emc-regulations",
        "coverage_level": "partial",
        "pack": "wireless",
    },
    "EN_301_489": {
        "required_analyzers": ["immunity_margin", "cable_coupling"],
        "limit_source": "emc-regulations",
        "coverage_level": "partial",
        "pack": "wireless",
        "notes": "Radio EMC immunity overlay.",
    },

    # Industrial
    "EN_61326": {
        "required_analyzers": ["conducted_emissions", "immunity_margin", "esd"],
        "limit_source": "local_fallback",
        "coverage_level": "full",
        "pack": "industrial",
    },
    "IEC_61000_6_2": {
        "required_analyzers": ["immunity_margin", "esd"],
        "limit_source": "local_fallback",
        "coverage_level": "full",
        "pack": "industrial",
    },
    "IEC_61000_6_4": {
        "required_analyzers": ["conducted_emissions", "near_field"],
        "limit_source": "local_fallback",
        "coverage_level": "full",
        "pack": "industrial",
    },

    # Military (placeholder)
    "MIL_STD_461G": {
        "required_analyzers": [],
        "limit_source": "emc-regulations",
        "coverage_level": "unimplemented",
        "pack": "military",
        "notes": "MIL-STD-461 G is out-of-scope today; reported as unimplemented for transparency.",
    },
}


# =============================================================================
# Result dataclass + helpers
# =============================================================================

@dataclass
class StandardCoverage:
    """Coverage status for one (standard, session) pair."""

    standard: str
    pack: str
    required_analyzers: list[str]
    ran_analyzers: list[str] = field(default_factory=list)
    missing_analyzers: list[str] = field(default_factory=list)
    limit_source: str = "local_fallback"
    coverage_level: str = "full"
    notes: str = ""

    @property
    def fully_covered(self) -> bool:
        return not self.missing_analyzers and self.coverage_level == "full"

    def to_dict(self) -> dict[str, Any]:
        return {
            "standard": self.standard,
            "pack": self.pack,
            "required_analyzers": list(self.required_analyzers),
            "ran_analyzers": list(self.ran_analyzers),
            "missing_analyzers": list(self.missing_analyzers),
            "limit_source": self.limit_source,
            "coverage_level": self.coverage_level,
            "fully_covered": self.fully_covered,
            "notes": self.notes,
        }


def get_coverage(
    active_standards: list[str],
    ran_analyzers: list[str] | set[str] | None = None,
) -> list[StandardCoverage]:
    """Return per-standard coverage for the supplied analyzer set."""
    ran_set = set(ran_analyzers or [])
    out: list[StandardCoverage] = []
    for std in active_standards:
        meta = STANDARD_TO_ANALYZERS.get(std)
        if meta is None:
            out.append(StandardCoverage(
                standard=std,
                pack="unknown",
                required_analyzers=[],
                limit_source="unknown",
                coverage_level="unimplemented",
                notes="Standard is not in STANDARD_TO_ANALYZERS.",
            ))
            continue
        required = list(meta["required_analyzers"])
        ran = [a for a in required if a in ran_set]
        missing = [a for a in required if a not in ran_set]
        out.append(StandardCoverage(
            standard=std,
            pack=str(meta.get("pack", "unknown")),
            required_analyzers=required,
            ran_analyzers=ran,
            missing_analyzers=missing,
            limit_source=str(meta.get("limit_source", "local_fallback")),
            coverage_level=str(meta.get("coverage_level", "full")),
            notes=str(meta.get("notes", "")),
        ))
    return out


def summarise_coverage(coverage: list[StandardCoverage]) -> dict[str, Any]:
    """Roll a coverage list into a single response dict."""
    full = sum(1 for c in coverage if c.fully_covered)
    partial = sum(1 for c in coverage if not c.fully_covered and c.coverage_level == "partial")
    stub = sum(1 for c in coverage if c.coverage_level == "stub")
    unimplemented = sum(1 for c in coverage if c.coverage_level == "unimplemented")
    return {
        "total_standards": len(coverage),
        "fully_covered": full,
        "partial": partial,
        "stub": stub,
        "unimplemented": unimplemented,
        "ready_for_report": unimplemented == 0 and stub == 0,
        "per_standard": [c.to_dict() for c in coverage],
    }

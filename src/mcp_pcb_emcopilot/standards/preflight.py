"""Preflight gate — refuses to advance past run_design_review or
generate_design_review_report when intake state is incomplete.

The gate is intentionally generous: any single critical defect causes
``ready=False``, but multiple checks may all flag at once so the caller
sees the full backlog and can correct them in one round-trip.

Callers pass ``force_run=True`` to bypass the gate; the report builder
stamps such outputs ``PRELIMINARY`` so the downgrade is visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .. import market_packs
from ..models.pcb_data import PCBDesignData
from .coverage import get_coverage, summarise_coverage


@dataclass
class ValidationGate:
    """Result of :func:`validate_review_complete`."""

    ready: bool
    missing_required_questions: list[str] = field(default_factory=list)
    missing_standard_selection: bool = False
    incomplete_standards: list[str] = field(default_factory=list)
    blocking_findings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "missing_required_questions": list(self.missing_required_questions),
            "missing_standard_selection": self.missing_standard_selection,
            "incomplete_standards": list(self.incomplete_standards),
            "blocking_findings": list(self.blocking_findings),
            "notes": list(self.notes),
        }


# Questions deemed *required* for a defensible review. These are the ones a
# senior reviewer would refuse to skip. Market-specific required-question
# lists are appended on top, keyed by market.
_CORE_REQUIRED: tuple[str, ...] = (
    "operating_environment",
    "fab_stackup_spec",
)

_MARKET_REQUIRED: dict[str, tuple[str, ...]] = {
    "automotive": ("vehicle_class", "cispr25_class", "bus_voltage"),
    "medical": ("device_class", "iec60601_edition"),
    "wireless": ("intentional_radiator", "fcc_part"),
    "commercial": ("cispr32_class", "target_regions"),
    "industrial": ("en61326_immunity", "surge_target_kV"),
}


def _required_questions_for(markets: list[str]) -> list[str]:
    required: list[str] = list(_CORE_REQUIRED)
    for m in markets:
        for q in _MARKET_REQUIRED.get(m, ()):
            if q not in required:
                required.append(q)
    return required


def validate_review_complete(
    design: PCBDesignData,
    ran_analyzers: Optional[list[str] | set[str]] = None,
) -> ValidationGate:
    """Decide whether the session is ready to generate a final report.

    The gate combines:
    - Required-question completion (core + market-specific).
    - Standard selection (at least one active standard must be in scope).
    - Standards coverage state — ``stub`` or ``unimplemented`` standards
      surface as ``incomplete_standards`` but do not block on their own;
      they become blocking only if no other standard fully covers the same
      hazard domain (judgement deferred to the caller via notes).
    """
    ctx = design.review_context or {}
    answers = ctx.get("interactive_answers", {}) or {}

    # Resolve active markets. The ``markets`` key may be absent, the wrong
    # type, or a list — coerce to a flat list[str] before further use.
    raw_markets = ctx.get("markets")
    explicit_markets: list[str] = (
        [str(m).lower() for m in raw_markets] if isinstance(raw_markets, list) else []
    )
    markets = [m for m in explicit_markets if m in market_packs.KNOWN_MARKETS]
    if not markets:
        pb = ctx.get("playbook") or {}
        declared = str(pb.get("declared_market") or "").lower()
        if declared and declared != "unknown" and declared in market_packs.KNOWN_MARKETS:
            markets = [declared]

    # Required-question completeness.
    required = _required_questions_for(markets)
    missing_questions = [q for q in required if q not in answers]

    # Standard-selection completeness.
    target_standards: list[str] = list(ctx.get("target_standards") or [])
    pb = ctx.get("playbook") or {}
    for s in pb.get("standards_shortlist") or []:
        if s not in target_standards:
            target_standards.append(s)
    missing_standard_selection = not target_standards

    # Coverage summary.
    coverage = get_coverage(target_standards, ran_analyzers=ran_analyzers)
    incomplete = [c.standard for c in coverage if c.coverage_level in ("stub", "unimplemented")]

    notes: list[str] = []
    if markets:
        notes.append(f"Active markets: {', '.join(markets)}.")
    else:
        notes.append("No active market declared — call pcb_set_market or include declared_market.")
    if incomplete:
        notes.append(
            "Standards with stub or unimplemented coverage: "
            + ", ".join(incomplete)
            + ". Surface these as human-review items in the report."
        )

    ready = (
        not missing_questions
        and not missing_standard_selection
    )

    return ValidationGate(
        ready=ready,
        missing_required_questions=missing_questions,
        missing_standard_selection=missing_standard_selection,
        incomplete_standards=incomplete,
        notes=notes,
    )


def coverage_summary(
    design: PCBDesignData,
    ran_analyzers: Optional[list[str] | set[str]] = None,
) -> dict[str, Any]:
    """Convenience: build the standards-coverage summary for a session."""
    ctx = design.review_context or {}
    standards: list[str] = list(ctx.get("target_standards") or [])
    pb = ctx.get("playbook") or {}
    for s in pb.get("standards_shortlist") or []:
        if s not in standards:
            standards.append(s)
    return summarise_coverage(get_coverage(standards, ran_analyzers=ran_analyzers))

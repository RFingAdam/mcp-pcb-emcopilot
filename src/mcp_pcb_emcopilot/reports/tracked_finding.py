"""TrackedFinding dataclass — traceable design review finding."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict


VALID_SEVERITIES = {"CRITICAL", "HIGH", "WARNING", "INFO", "PASS"}
_FINDING_ID_RE = re.compile(r"^[A-Z]+-\d{3}$")


@dataclass
class TrackedFinding:
    """A design review finding with full traceability.

    Every finding links back to specific nets, layers, components, and
    board coordinates so the report reader knows exactly what and where
    the issue is.
    """

    # Identity
    finding_id: str
    severity: str
    domain: str
    title: str

    # Explanation
    what_it_means: str
    how_calculated: str
    physical_mechanism: str

    # Data
    measured_value: str
    limit_value: str
    margin: str

    # Action
    recommendation: str
    reference_standard: str

    # Traceability (optional — not all findings map to a specific net)
    nets: list[str] = field(default_factory=list)
    layers: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    coordinates_mm: list[tuple] = field(default_factory=list)
    trace_length_mm: float | None = None

    # Visuals (populated during report generation)
    plot_path: str | None = None
    render_path: str | None = None

    def __post_init__(self):
        # Normalize and validate severity
        self.severity = self.severity.upper()
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(
                f"severity must be one of {VALID_SEVERITIES}, got '{self.severity}'"
            )
        # Validate finding_id format
        if not _FINDING_ID_RE.match(self.finding_id):
            raise ValueError(
                f"finding_id must match DOMAIN-NNN pattern (e.g., 'EMC-001'), "
                f"got '{self.finding_id}'"
            )

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return asdict(self)

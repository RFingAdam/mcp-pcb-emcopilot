"""Standards coverage + preflight gating.

Subpackage that maps regulatory standards to the analyzers required to claim
compliance, and validates that a session has enough state to produce a
defensible review.
"""

from .coverage import (
    STANDARD_TO_ANALYZERS,
    StandardCoverage,
    get_coverage,
    summarise_coverage,
)
from .preflight import ValidationGate, validate_review_complete

__all__ = [
    "STANDARD_TO_ANALYZERS",
    "StandardCoverage",
    "ValidationGate",
    "get_coverage",
    "summarise_coverage",
    "validate_review_complete",
]

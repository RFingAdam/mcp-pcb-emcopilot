"""PCB design review report generation."""

from .tracked_finding import TrackedFinding
from .section_registry import REPORT_SECTIONS, SectionDef, get_section_by_key

__all__ = [
    "TrackedFinding",
    "REPORT_SECTIONS",
    "SectionDef",
    "get_section_by_key",
]

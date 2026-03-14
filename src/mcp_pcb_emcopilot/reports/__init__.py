"""PCB design review report generation."""

from .report_builder import ReportBuilder
from .section_registry import REPORT_SECTIONS, SectionDef, get_section_by_key
from .tracked_finding import TrackedFinding

__all__ = [
    "ReportBuilder",
    "TrackedFinding",
    "REPORT_SECTIONS",
    "SectionDef",
    "get_section_by_key",
]

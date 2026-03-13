"""PCB design review report generation."""

from .tracked_finding import TrackedFinding
from .section_registry import REPORT_SECTIONS, SectionDef, get_section_by_key
from .report_builder import ReportBuilder

__all__ = [
    "ReportBuilder",
    "TrackedFinding",
    "REPORT_SECTIONS",
    "SectionDef",
    "get_section_by_key",
]

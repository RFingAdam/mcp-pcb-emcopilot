"""
Antenna and EMC Analyzers.

Provides analyzers for unintentional antenna structures
and EMC-related design issues.
"""
from .trace_antenna import TraceAntennaAnalyzer, TraceAntennaResult
from .slot_antenna import SlotAntennaAnalyzer, SlotAntennaResult
from .common_mode import CommonModeAnalyzer, CommonModeResult
from .cable_coupling import CableCouplingAnalyzer, CableCouplingResult

__all__ = [
    "TraceAntennaAnalyzer",
    "TraceAntennaResult",
    "SlotAntennaAnalyzer",
    "SlotAntennaResult",
    "CommonModeAnalyzer",
    "CommonModeResult",
    "CableCouplingAnalyzer",
    "CableCouplingResult",
]

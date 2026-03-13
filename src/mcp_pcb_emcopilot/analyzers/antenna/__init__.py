"""
Antenna and EMC Analyzers.

Provides analyzers for unintentional antenna structures
and EMC-related design issues.
"""
from __future__ import annotations

from .cable_coupling import CableCouplingAnalyzer, CableCouplingResult
from .common_mode import CommonModeAnalyzer, CommonModeResult
from .slot_antenna import SlotAntennaAnalyzer, SlotAntennaResult
from .trace_antenna import TraceAntennaAnalyzer, TraceAntennaResult

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

"""High-Speed Digital analysis modules.

Provides analysis for high-speed digital interfaces:
- DDR3/DDR4/DDR5/LPDDR routing compliance
- PCIe lane analysis and link budget
- PCIe lane skew validation
- USB 2.0/3.x routing
- Ethernet PHY routing
- Generic length matching
"""

from __future__ import annotations

from .ddr_analyzer import DDRAnalyzer, DDRIssue, DDRResult, DDRStandard
from .ddr_topology import analyze_ddr_timing_budget, validate_ddr_topology
from .ethernet_analyzer import EthernetAnalyzer, EthernetIssue, EthernetResult
from .length_matching import LengthMatcher, LengthMatchResult, MatchingGroup
from .pcie_analyzer import PCIeAnalyzer, PCIeGeneration, PCIeIssue, PCIeResult
from .pcie_link_budget import calculate_pcie_link_budget, validate_pcie_lanes
from .usb_analyzer import USBAnalyzer, USBIssue, USBResult, USBVersion

__all__ = [
    # DDR
    "DDRAnalyzer",
    "DDRResult",
    "DDRIssue",
    "DDRStandard",
    # PCIe
    "PCIeAnalyzer",
    "PCIeResult",
    "PCIeIssue",
    "PCIeGeneration",
    # DDR Topology
    "validate_ddr_topology",
    "analyze_ddr_timing_budget",
    # PCIe Link Budget
    "calculate_pcie_link_budget",
    "validate_pcie_lanes",
    # USB
    "USBAnalyzer",
    "USBResult",
    "USBIssue",
    "USBVersion",
    # Ethernet
    "EthernetAnalyzer",
    "EthernetResult",
    "EthernetIssue",
    # Length Matching
    "LengthMatcher",
    "LengthMatchResult",
    "MatchingGroup",
]

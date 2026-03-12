"""High-Speed Digital analysis modules.

Provides analysis for high-speed digital interfaces:
- DDR3/DDR4/DDR5/LPDDR routing compliance
- PCIe lane analysis
- USB 2.0/3.x routing
- Ethernet PHY routing
- Generic length matching
"""

from .ddr_analyzer import DDRAnalyzer, DDRResult, DDRIssue, DDRStandard
from .pcie_analyzer import PCIeAnalyzer, PCIeResult, PCIeIssue, PCIeGeneration
from .usb_analyzer import USBAnalyzer, USBResult, USBIssue, USBVersion
from .ethernet_analyzer import EthernetAnalyzer, EthernetResult, EthernetIssue
from .length_matching import LengthMatcher, LengthMatchResult, MatchingGroup

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

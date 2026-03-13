"""Thermal analysis modules.

Provides thermal risk analysis for PCB designs:
- Component power dissipation mapping
- Thermal via adequacy
- Hotspot detection
- Copper heat spreading
"""

from __future__ import annotations

from .copper_spreading import CopperSpreadingAnalyzer, CopperSpreadingResult
from .hotspot_detector import Hotspot, HotspotDetector, HotspotResult
from .power_dissipation import ComponentPower, PowerDissipationAnalyzer, PowerDissipationResult
from .thermal_via import ThermalViaAnalyzer, ThermalViaIssue, ThermalViaResult

__all__ = [
    # Power Dissipation
    "PowerDissipationAnalyzer",
    "PowerDissipationResult",
    "ComponentPower",
    # Thermal Vias
    "ThermalViaAnalyzer",
    "ThermalViaResult",
    "ThermalViaIssue",
    # Hotspots
    "HotspotDetector",
    "HotspotResult",
    "Hotspot",
    # Copper Spreading
    "CopperSpreadingAnalyzer",
    "CopperSpreadingResult",
]

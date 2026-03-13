"""Thermal analysis modules.

Provides thermal risk analysis for PCB designs:
- Component power dissipation mapping
- Thermal via adequacy
- Hotspot detection
- Copper heat spreading
"""

from __future__ import annotations

from .power_dissipation import PowerDissipationAnalyzer, PowerDissipationResult, ComponentPower
from .thermal_via import ThermalViaAnalyzer, ThermalViaResult, ThermalViaIssue
from .hotspot_detector import HotspotDetector, HotspotResult, Hotspot
from .copper_spreading import CopperSpreadingAnalyzer, CopperSpreadingResult

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

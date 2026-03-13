"""EMC (Electromagnetic Compatibility) analysis modules"""

from __future__ import annotations

from .current_loop import CurrentLoopAnalyzer, LoopAnalysisResult
from .shielding import ShieldingAnalyzer, ShieldingResult
from .radiated_emissions import EmissionsAnalyzer, EmissionsResult
from .grounding import GroundingAnalyzer, GroundingResult
from .esd_assessment import ESDAnalyzer, ESDResult

__all__ = [
    "CurrentLoopAnalyzer",
    "LoopAnalysisResult",
    "ShieldingAnalyzer",
    "ShieldingResult",
    "EmissionsAnalyzer",
    "EmissionsResult",
    "GroundingAnalyzer",
    "GroundingResult",
    "ESDAnalyzer",
    "ESDResult",
]

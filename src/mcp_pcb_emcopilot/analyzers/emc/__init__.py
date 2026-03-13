"""EMC (Electromagnetic Compatibility) analysis modules"""

from __future__ import annotations

from .current_loop import CurrentLoopAnalyzer, LoopAnalysisResult
from .esd_assessment import ESDAnalyzer, ESDResult
from .filter_design import FilterDesigner, FilterDesignResult
from .grounding import GroundingAnalyzer, GroundingResult
from .radiated_emissions import EmissionsAnalyzer, EmissionsResult
from .shielding import ShieldingAnalyzer, ShieldingResult

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
    "FilterDesigner",
    "FilterDesignResult",
]

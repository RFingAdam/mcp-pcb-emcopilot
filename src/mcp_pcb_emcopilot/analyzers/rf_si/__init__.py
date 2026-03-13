"""RF and Signal Integrity analysis modules"""

from __future__ import annotations

from .crosstalk_analyzer import CrosstalkAnalyzer, CrosstalkResult
from .differential_pair import DifferentialPairAnalyzer, DiffPairResult
from .eye_diagram import calculate_eye_opening
from .impedance_calculator import ImpedanceCalculator, ImpedanceResult
from .via_modeler import ViaModel, ViaModeler

__all__ = [
    "ImpedanceCalculator",
    "ImpedanceResult",
    "CrosstalkAnalyzer",
    "CrosstalkResult",
    "ViaModeler",
    "ViaModel",
    "DifferentialPairAnalyzer",
    "DiffPairResult",
    "calculate_eye_opening",
]

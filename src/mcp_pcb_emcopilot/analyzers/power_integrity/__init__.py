"""Power Integrity analysis modules.

Provides comprehensive power distribution network (PDN) analysis including:
- PDN impedance analysis
- Frequency-swept PDN impedance profiling
- Decoupling capacitor placement optimization
- VRM routing and proximity analysis
- Power plane integrity checking
"""

from __future__ import annotations

from .cavity_resonance import analyze_cavity_resonance
from .decap_placement import DecapAnalyzer, DecapRecommendation, DecapResult
from .pdn_analyzer import PDNAnalyzer, PDNImpedancePoint, PDNResult
from .pdn_impedance import calculate_pdn_impedance
from .power_plane_analyzer import PlaneIssue, PowerPlaneAnalyzer, PowerPlaneResult
from .vrm_analyzer import VRMAnalyzer, VRMIssue, VRMResult

__all__ = [
    # PDN Analysis
    "PDNAnalyzer",
    "PDNResult",
    "PDNImpedancePoint",
    # PDN Impedance Profiling
    "calculate_pdn_impedance",
    # Decoupling
    "DecapAnalyzer",
    "DecapResult",
    "DecapRecommendation",
    # VRM
    "VRMAnalyzer",
    "VRMResult",
    "VRMIssue",
    # Power Planes
    "PowerPlaneAnalyzer",
    "PowerPlaneResult",
    "PlaneIssue",
    # Cavity Resonance
    "analyze_cavity_resonance",
]

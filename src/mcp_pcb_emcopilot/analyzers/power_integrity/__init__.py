"""Power Integrity analysis modules.

Provides comprehensive power distribution network (PDN) analysis including:
- PDN impedance analysis
- Frequency-swept PDN impedance profiling
- Decoupling capacitor placement optimization
- VRM routing and proximity analysis
- Power plane integrity checking
"""

from .pdn_analyzer import PDNAnalyzer, PDNResult, PDNImpedancePoint
from .pdn_impedance import calculate_pdn_impedance
from .decap_placement import DecapAnalyzer, DecapResult, DecapRecommendation
from .vrm_analyzer import VRMAnalyzer, VRMResult, VRMIssue
from .power_plane_analyzer import PowerPlaneAnalyzer, PowerPlaneResult, PlaneIssue

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
]

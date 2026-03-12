"""Power Integrity analysis modules.

Provides comprehensive power distribution network (PDN) analysis including:
- PDN impedance analysis
- Decoupling capacitor placement optimization  
- VRM routing and proximity analysis
- Power plane integrity checking
"""

from .pdn_analyzer import PDNAnalyzer, PDNResult, PDNImpedancePoint
from .decap_placement import DecapAnalyzer, DecapResult, DecapRecommendation
from .vrm_analyzer import VRMAnalyzer, VRMResult, VRMIssue
from .power_plane_analyzer import PowerPlaneAnalyzer, PowerPlaneResult, PlaneIssue

__all__ = [
    # PDN Analysis
    "PDNAnalyzer",
    "PDNResult", 
    "PDNImpedancePoint",
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

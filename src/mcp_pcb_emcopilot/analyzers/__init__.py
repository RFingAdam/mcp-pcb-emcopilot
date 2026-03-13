"""Analysis engines for RF/SI, EMC, DFM, Power Integrity, High-Speed, Thermal, and Antenna analysis."""

from .antenna import (
    CableCouplingAnalyzer,
    CableCouplingResult,
    CommonModeAnalyzer,
    CommonModeResult,
    SlotAntennaAnalyzer,
    SlotAntennaResult,
    TraceAntennaAnalyzer,
    TraceAntennaResult,
)
from .dfm import (
    AssemblyAnalyzer,
    AssemblyResult,
    PlacementAnalyzer,
    PlacementResult,
    SolderPasteAnalyzer,
    SolderPasteResult,
    ThermalReliefAnalyzer,
    ThermalReliefResult,
    ToleranceAnalyzer,
    ToleranceResult,
)
from .emc import (
    CurrentLoopAnalyzer,
    EmissionsAnalyzer,
    EmissionsResult,
    ESDAnalyzer,
    ESDResult,
    GroundingAnalyzer,
    GroundingResult,
    LoopAnalysisResult,
    ShieldingAnalyzer,
    ShieldingResult,
)
from .high_speed import (
    DDRAnalyzer,
    DDRResult,
    EthernetAnalyzer,
    EthernetResult,
    LengthMatcher,
    LengthMatchResult,
    PCIeAnalyzer,
    PCIeResult,
    USBAnalyzer,
    USBResult,
)
from .power_integrity import (
    DecapAnalyzer,
    DecapResult,
    PDNAnalyzer,
    PDNResult,
    PowerPlaneAnalyzer,
    PowerPlaneResult,
    VRMAnalyzer,
    VRMResult,
)
from .rf_si import (
    CrosstalkAnalyzer,
    CrosstalkResult,
    DifferentialPairAnalyzer,
    DiffPairResult,
    ImpedanceCalculator,
    ImpedanceResult,
    ViaModel,
    ViaModeler,
)
from .thermal import (
    CopperSpreadingAnalyzer,
    CopperSpreadingResult,
    HotspotDetector,
    HotspotResult,
    PowerDissipationAnalyzer,
    PowerDissipationResult,
    ThermalViaAnalyzer,
    ThermalViaResult,
)

__all__ = [
    # RF/SI
    "ImpedanceCalculator", "ImpedanceResult",
    "CrosstalkAnalyzer", "CrosstalkResult",
    "ViaModeler", "ViaModel",
    "DifferentialPairAnalyzer", "DiffPairResult",
    # EMC
    "CurrentLoopAnalyzer", "LoopAnalysisResult",
    "ShieldingAnalyzer", "ShieldingResult",
    "EmissionsAnalyzer", "EmissionsResult",
    "GroundingAnalyzer", "GroundingResult",
    "ESDAnalyzer", "ESDResult",
    # DFM
    "SolderPasteAnalyzer", "SolderPasteResult",
    "ThermalReliefAnalyzer", "ThermalReliefResult",
    "PlacementAnalyzer", "PlacementResult",
    "AssemblyAnalyzer", "AssemblyResult",
    "ToleranceAnalyzer", "ToleranceResult",
    # Power Integrity
    "PDNAnalyzer", "PDNResult",
    "DecapAnalyzer", "DecapResult",
    "VRMAnalyzer", "VRMResult",
    "PowerPlaneAnalyzer", "PowerPlaneResult",
    # High-Speed
    "DDRAnalyzer", "DDRResult",
    "PCIeAnalyzer", "PCIeResult",
    "USBAnalyzer", "USBResult",
    "EthernetAnalyzer", "EthernetResult",
    "LengthMatcher", "LengthMatchResult",
    # Thermal
    "PowerDissipationAnalyzer", "PowerDissipationResult",
    "ThermalViaAnalyzer", "ThermalViaResult",
    "HotspotDetector", "HotspotResult",
    "CopperSpreadingAnalyzer", "CopperSpreadingResult",
    # Antenna
    "TraceAntennaAnalyzer", "TraceAntennaResult",
    "SlotAntennaAnalyzer", "SlotAntennaResult",
    "CommonModeAnalyzer", "CommonModeResult",
    "CableCouplingAnalyzer", "CableCouplingResult",
]

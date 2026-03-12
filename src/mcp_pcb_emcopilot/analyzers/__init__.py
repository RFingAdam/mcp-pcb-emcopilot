"""Analysis engines for RF/SI, EMC, DFM, Power Integrity, High-Speed, Thermal, and Antenna analysis."""

from .rf_si import (
    ImpedanceCalculator,
    ImpedanceResult,
    CrosstalkAnalyzer,
    CrosstalkResult,
    ViaModeler,
    ViaModel,
    DifferentialPairAnalyzer,
    DiffPairResult,
)

from .emc import (
    CurrentLoopAnalyzer,
    LoopAnalysisResult,
    ShieldingAnalyzer,
    ShieldingResult,
    EmissionsAnalyzer,
    EmissionsResult,
    GroundingAnalyzer,
    GroundingResult,
    ESDAnalyzer,
    ESDResult,
)

from .dfm import (
    SolderPasteAnalyzer,
    SolderPasteResult,
    ThermalReliefAnalyzer,
    ThermalReliefResult,
    PlacementAnalyzer,
    PlacementResult,
    AssemblyAnalyzer,
    AssemblyResult,
    ToleranceAnalyzer,
    ToleranceResult,
)

from .power_integrity import (
    PDNAnalyzer,
    PDNResult,
    DecapAnalyzer,
    DecapResult,
    VRMAnalyzer,
    VRMResult,
    PowerPlaneAnalyzer,
    PowerPlaneResult,
)

from .high_speed import (
    DDRAnalyzer,
    DDRResult,
    PCIeAnalyzer,
    PCIeResult,
    USBAnalyzer,
    USBResult,
    EthernetAnalyzer,
    EthernetResult,
    LengthMatcher,
    LengthMatchResult,
)

from .thermal import (
    PowerDissipationAnalyzer,
    PowerDissipationResult,
    ThermalViaAnalyzer,
    ThermalViaResult,
    HotspotDetector,
    HotspotResult,
    CopperSpreadingAnalyzer,
    CopperSpreadingResult,
)

from .antenna import (
    TraceAntennaAnalyzer,
    TraceAntennaResult,
    SlotAntennaAnalyzer,
    SlotAntennaResult,
    CommonModeAnalyzer,
    CommonModeResult,
    CableCouplingAnalyzer,
    CableCouplingResult,
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

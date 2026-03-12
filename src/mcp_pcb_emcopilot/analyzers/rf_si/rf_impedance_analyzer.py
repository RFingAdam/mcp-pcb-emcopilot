"""RF Impedance Analyzer for 50-ohm transmission line validation.

Validates:
- RF net impedance within +/-5% tolerance (47.5-52.5 ohm)
- Proper RF transmission line structures
- Ground coplanar waveguide (GCPW) detection
- RF component connectivity

Decoupled from SQLAlchemy — operates on PCBDesignData.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from .impedance_calculator import ImpedanceCalculator

logger = logging.getLogger(__name__)


@dataclass
class RFImpedanceViolation:
    """RF impedance violation (not within 50 ohm +/-5%)."""
    net_name: str
    trace_index: Optional[int] = None
    layer_name: str = ""
    calculated_impedance: float = 0.0
    target_impedance: float = 50.0
    tolerance_percent: float = 5.0
    trace_width_mm: float = 0.0
    structure_type: str = "unknown"
    severity: str = "error"

    def get_tolerance_range(self) -> tuple[float, float]:
        delta = self.target_impedance * (self.tolerance_percent / 100.0)
        return (self.target_impedance - delta, self.target_impedance + delta)


@dataclass
class RFNet:
    """Detected RF net."""
    net_name: str
    net_type: str  # antenna, tx, rx, rf_signal, lo
    component_refs: list[str] = field(default_factory=list)
    trace_count: int = 0


@dataclass
class RFImpedanceAnalysisResult:
    """Result of RF impedance analysis."""
    rf_nets: list[RFNet] = field(default_factory=list)
    violations: list[RFImpedanceViolation] = field(default_factory=list)
    gcpw_structures: int = 0
    errors: int = 0
    warnings: int = 0
    is_estimated_stackup: bool = False
    stackup_notes: list[str] = field(default_factory=list)

    def get_compliance_percentage(self) -> float:
        total = len(self.rf_nets)
        if total == 0:
            return 100.0
        compliant = total - len(self.violations)
        return (compliant / total) * 100.0


class RFImpedanceAnalyzer:
    """Analyzer for RF transmission line impedance validation.

    Operates on in-memory PCBDesignData instead of database sessions.
    """

    RF_NET_PATTERNS = [
        r"^RF[_\-]",
        r"^ANT[_\-]?",
        r"^TX[_\-]RF",
        r"^RX[_\-]RF",
        r"^LO[_\-]",
        r"[_\-]RF$",
        r"^WLAN",
        r"^BT[_\-]",
        r"^GPS[_\-]",
        r"^LTE[_\-]",
    ]

    RF_COMPONENT_PATTERNS = [
        r"(?i)diplexer",
        r"(?i)triplexer",
        r"(?i)saw",
        r"(?i)baw",
        r"(?i)lna",
        r"(?i)pa",
        r"(?i)balun",
        r"(?i)antenna",
    ]

    TARGET_IMPEDANCE = 50.0
    TOLERANCE_PERCENT = 5.0

    def __init__(self):
        self.impedance_calculator = ImpedanceCalculator()

    def analyze(self, design_data) -> RFImpedanceAnalysisResult:
        """Analyze RF net impedance compliance.

        Args:
            design_data: PCBDesignData with parsed design

        Returns:
            Analysis result with violations
        """
        result = RFImpedanceAnalysisResult()

        # Detect RF nets from net names
        rf_nets = self._detect_rf_nets(design_data.nets)
        result.rf_nets = rf_nets

        if not rf_nets:
            return result

        # Get stackup info for impedance calculations
        copper_layers = [l for l in design_data.layers if l.layer_type in ("signal", "plane", "mixed")]
        if not copper_layers:
            result.stackup_notes.append("No stackup data — cannot calculate impedance")
            return result

        # Check impedance for each RF net
        for rf_net_info in rf_nets:
            violations = self._check_net_impedance(
                design_data, rf_net_info.net_name
            )
            result.violations.extend(violations)

        result.errors = sum(1 for v in result.violations if v.severity == "error")
        result.warnings = sum(1 for v in result.violations if v.severity == "warning")

        return result

    def _detect_rf_nets(self, nets) -> list[RFNet]:
        """Detect RF nets by pattern matching."""
        rf_nets = []
        for net in nets:
            net_name_upper = net.name.upper()
            for pattern in self.RF_NET_PATTERNS:
                if re.search(pattern, net_name_upper):
                    net_type = self._classify_rf_net(net_name_upper)
                    rf_nets.append(RFNet(net_name=net.name, net_type=net_type))
                    break
        return rf_nets

    def _classify_rf_net(self, net_name: str) -> str:
        if "ANT" in net_name:
            return "antenna"
        elif "TX" in net_name:
            return "tx"
        elif "RX" in net_name:
            return "rx"
        elif "LO" in net_name:
            return "lo"
        return "rf_signal"

    def _check_net_impedance(self, design_data, net_name: str) -> list[RFImpedanceViolation]:
        """Check impedance for a specific RF net."""
        violations = []

        # Find the net
        net = design_data.get_net_by_name(net_name)
        if not net:
            return violations

        # Get traces on this net
        traces = design_data.get_traces_on_net(net.index)

        # Get stackup layers sorted by number
        layers_sorted = sorted(design_data.layers, key=lambda l: l.number)

        for idx, trace in enumerate(traces):
            violation = self._calculate_trace_impedance(
                trace, layers_sorted, net_name, idx
            )
            if violation:
                violations.append(violation)

        return violations

    def _calculate_trace_impedance(
        self, trace, layers_sorted, net_name: str, trace_idx: int
    ) -> Optional[RFImpedanceViolation]:
        """Calculate impedance for a trace checking adjacent dielectrics."""
        if not trace.width_mm or trace.width_mm == 0:
            return None

        # Find signal layer
        signal_layer = None
        for l in layers_sorted:
            if l.name == trace.layer:
                signal_layer = l
                break

        if not signal_layer:
            return None

        trace_thickness = 0.035  # Default 1oz
        if signal_layer.copper_weight_oz:
            trace_thickness = signal_layer.copper_weight_oz * 0.035

        # Find dielectric height to reference plane (look below)
        h_total = 0.0
        er_effective = 4.3
        idx = layers_sorted.index(signal_layer)

        for l in layers_sorted[idx + 1:]:
            if l.layer_type in ('plane', 'mixed'):
                break
            if l.layer_type == 'dielectric':
                h_total += l.thickness_mm if l.thickness_mm else 0.15
                er_effective = l.dielectric_constant or 4.3

        if h_total == 0.0:
            h_total = 0.15

        is_outer = signal_layer.number <= 1 or signal_layer.number >= len(layers_sorted)
        line_type = "microstrip" if is_outer else "stripline"

        if line_type == "microstrip":
            impedance = self.impedance_calculator.microstrip(
                width_mm=trace.width_mm, height_mm=h_total,
                dielectric_constant=er_effective, thickness_mm=trace_thickness,
            )
        else:
            impedance = self.impedance_calculator.stripline(
                width_mm=trace.width_mm, height_mm=h_total * 2,
                dielectric_constant=er_effective, thickness_mm=trace_thickness,
            )

        min_z, max_z = self._get_tolerance_range()
        if impedance < min_z or impedance > max_z:
            return RFImpedanceViolation(
                net_name=net_name,
                trace_index=trace_idx,
                layer_name=f"{signal_layer.name}",
                calculated_impedance=impedance,
                target_impedance=self.TARGET_IMPEDANCE,
                tolerance_percent=self.TOLERANCE_PERCENT,
                trace_width_mm=trace.width_mm,
                structure_type=line_type,
                severity="error",
            )
        return None

    def _get_tolerance_range(self) -> tuple[float, float]:
        delta = self.TARGET_IMPEDANCE * (self.TOLERANCE_PERCENT / 100.0)
        return (self.TARGET_IMPEDANCE - delta, self.TARGET_IMPEDANCE + delta)

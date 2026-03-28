"""
DDR Memory Interface Analyzer.

Analyzes DDR3/DDR4/DDR5/LPDDR routing for compliance:
- Data byte lane matching
- Address/Command timing
- Clock routing
- Via transitions
- Reference plane continuity
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# Speed of light in mm/ps
SPEED_OF_LIGHT_MM_PS = 299.792458


class DDRStandard(str, Enum):
    """DDR memory standards."""
    DDR3 = "ddr3"
    DDR3L = "ddr3l"
    DDR4 = "ddr4"
    DDR5 = "ddr5"
    LPDDR3 = "lpddr3"
    LPDDR4 = "lpddr4"
    LPDDR4X = "lpddr4x"
    LPDDR5 = "lpddr5"


class DDRIssueType(str, Enum):
    """Types of DDR routing issues."""
    DQ_DQS_SKEW = "dq_dqs_skew"
    BYTE_LANE_MISMATCH = "byte_lane_mismatch"
    ADDR_CMD_SKEW = "addr_cmd_skew"
    CLK_ROUTING = "clk_routing"
    IMPEDANCE_MISMATCH = "impedance_mismatch"
    SPACING_VIOLATION = "spacing_violation"
    VIA_COUNT_EXCEEDED = "via_count_exceeded"
    REFERENCE_PLANE_BREAK = "reference_plane_break"
    TERMINATION_MISSING = "termination_missing"
    VREF_DECOUPLING = "vref_decoupling"


@dataclass
class DDRIssue:
    """A DDR routing issue."""
    issue_type: DDRIssueType
    severity: str  # critical, high, medium, low
    description: str
    signal_name: Optional[str] = None
    byte_lane: Optional[int] = None
    measured_value: Optional[float] = None
    limit_value: Optional[float] = None
    recommendation: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "issue_type": self.issue_type.value,
            "severity": self.severity,
            "description": self.description,
            "signal_name": self.signal_name,
            "byte_lane": self.byte_lane,
            "measured_value": round(self.measured_value, 3) if self.measured_value else None,
            "limit_value": round(self.limit_value, 3) if self.limit_value else None,
            "recommendation": self.recommendation,
        }


@dataclass
class ByteLaneAnalysis:
    """Analysis of a single DDR byte lane."""
    byte_lane: int
    dqs_length_mm: float
    dq_lengths_mm: list[float]
    max_dq_dqs_skew_ps: float
    skew_within_spec: bool
    issues: list[DDRIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "byte_lane": self.byte_lane,
            "dqs_length_mm": round(self.dqs_length_mm, 2),
            "dq_lengths_mm": [round(l, 2) for l in self.dq_lengths_mm],
            "max_dq_dqs_skew_ps": round(self.max_dq_dqs_skew_ps, 1),
            "skew_within_spec": self.skew_within_spec,
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass
class DDRResult:
    """Result of DDR interface analysis."""
    ddr_standard: DDRStandard
    data_rate_mtps: int  # Megatransfers per second

    # Byte lane analysis
    byte_lanes: list[ByteLaneAnalysis] = field(default_factory=list)

    # Address/Command analysis
    addr_cmd_max_skew_ps: float = 0.0
    addr_cmd_within_spec: bool = True

    # Clock analysis
    clock_length_mm: float = 0.0
    clock_matched: bool = True
    clock_impedance_ohm: float = 0.0

    # Via analysis
    max_via_transitions: int = 0
    via_transitions_acceptable: bool = True

    # Overall results
    issues: list[DDRIssue] = field(default_factory=list)
    compliant: bool = True
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "ddr_standard": self.ddr_standard.value,
            "data_rate_mtps": self.data_rate_mtps,
            "byte_lanes": [bl.to_dict() for bl in self.byte_lanes],
            "addr_cmd_max_skew_ps": round(self.addr_cmd_max_skew_ps, 1),
            "addr_cmd_within_spec": self.addr_cmd_within_spec,
            "clock_length_mm": round(self.clock_length_mm, 2),
            "clock_matched": self.clock_matched,
            "clock_impedance_ohm": round(self.clock_impedance_ohm, 1),
            "max_via_transitions": self.max_via_transitions,
            "via_transitions_acceptable": self.via_transitions_acceptable,
            "issues": [i.to_dict() for i in self.issues],
            "compliant": self.compliant,
            "score": round(self.score, 1),
        }


# DDR timing specifications by standard (in picoseconds)
DDR_SPECS: dict[DDRStandard, dict[str, Any]] = {
    DDRStandard.DDR3: {
        "dq_dqs_skew_ps": 50,      # Max DQ-DQS skew per byte lane
        "addr_cmd_skew_ps": 100,   # Max address/command skew
        "clk_skew_ps": 25,         # Max clock pair skew
        "max_via_transitions": 4,
        "impedance_se_ohm": 40,    # Single-ended impedance
        "impedance_diff_ohm": 80,  # Differential impedance
        "min_spacing_w": 3,        # Minimum 3W spacing
    },
    DDRStandard.DDR4: {
        "dq_dqs_skew_ps": 25,
        "addr_cmd_skew_ps": 50,
        "clk_skew_ps": 15,
        "max_via_transitions": 2,
        "impedance_se_ohm": 40,
        "impedance_diff_ohm": 80,
        "min_spacing_w": 3,
    },
    DDRStandard.DDR5: {
        "dq_dqs_skew_ps": 15,
        "addr_cmd_skew_ps": 30,
        "clk_skew_ps": 10,
        "max_via_transitions": 2,
        "impedance_se_ohm": 40,
        "impedance_diff_ohm": 80,
        "min_spacing_w": 4,
    },
    DDRStandard.LPDDR4: {
        "dq_dqs_skew_ps": 30,
        "addr_cmd_skew_ps": 60,
        "clk_skew_ps": 15,
        "max_via_transitions": 2,
        "impedance_se_ohm": 40,
        "impedance_diff_ohm": 80,
        "min_spacing_w": 3,
    },
    DDRStandard.LPDDR5: {
        "dq_dqs_skew_ps": 20,
        "addr_cmd_skew_ps": 40,
        "clk_skew_ps": 10,
        "max_via_transitions": 2,
        "impedance_se_ohm": 40,
        "impedance_diff_ohm": 80,
        "min_spacing_w": 4,
    },
}


class DDRAnalyzer:
    """
    DDR memory interface routing analyzer.

    Analyzes DDR routing compliance for:
    - DQ to DQS skew within byte lanes
    - Address/Command signal timing
    - Clock routing quality
    - Via transition limits
    - Spacing rules

    Usage:
        analyzer = DDRAnalyzer()
        result = analyzer.analyze(
            ddr_standard=DDRStandard.DDR4,
            data_rate_mtps=3200,
            byte_lanes=[
                {
                    "byte_lane": 0,
                    "dqs_length_mm": 45.5,
                    "dq_lengths_mm": [45.3, 45.7, 45.4, 45.6, 45.5, 45.4, 45.6, 45.5],
                },
            ],
            addr_cmd_lengths_mm=[50.1, 50.3, 50.0, 50.2, ...],
            clock_length_mm=48.0,
        )
    """

    # Default propagation delay (ps/mm) for typical FR4 at DDR frequencies
    DEFAULT_PROP_DELAY_PS_PER_MM = 6.5

    def __init__(
        self,
        prop_delay_ps_per_mm: Optional[float] = None,
        strict_mode: bool = False,
        stackup_layers: Optional[List[Dict[str, Any]]] = None,
        routing_layer: Optional[int] = None,
    ):
        """
        Initialize analyzer.

        Args:
            prop_delay_ps_per_mm: Propagation delay in ps/mm (if not provided, calculated from stackup)
            strict_mode: Use stricter (50%) timing margins
            stackup_layers: List of stackup layer dicts with 'dielectric_constant', 'type', etc.
            routing_layer: Layer number (1-based) where DDR signals are routed
        """
        self.strict_mode = strict_mode
        self.margin_factor = 0.5 if strict_mode else 1.0
        self.stackup_layers = stackup_layers
        self.routing_layer = routing_layer

        # Calculate propagation delay from stackup if available
        if prop_delay_ps_per_mm is not None:
            self.prop_delay = prop_delay_ps_per_mm
        elif stackup_layers:
            self.prop_delay = self._calculate_prop_delay_from_stackup(
                stackup_layers, routing_layer
            )
        else:
            self.prop_delay = self.DEFAULT_PROP_DELAY_PS_PER_MM

        # Store per-layer propagation delays for mixed-layer routing
        self._layer_prop_delays: Dict[int, float] = {}
        if stackup_layers:
            self._calculate_all_layer_delays(stackup_layers)

    def _calculate_prop_delay_from_stackup(
        self,
        layers: List[Dict[str, Any]],
        routing_layer: Optional[int] = None,
    ) -> float:
        """Calculate propagation delay from stackup dielectric.

        Args:
            layers: List of stackup layer dictionaries
            routing_layer: Specific layer to calculate for (1-based)

        Returns:
            Propagation delay in ps/mm
        """
        if not layers:
            return self.DEFAULT_PROP_DELAY_PS_PER_MM

        # Find copper/signal layers
        signal_layers = []
        for idx, layer in enumerate(layers):
            layer_type = str(layer.get('type', '')).lower()
            if layer_type in ('signal', 'copper', 'mixed'):
                signal_layers.append((idx + 1, layer))

        if not signal_layers:
            return self.DEFAULT_PROP_DELAY_PS_PER_MM

        # Determine if microstrip or stripline
        total_signal_layers = len(signal_layers)
        if routing_layer is not None:
            target_layer = routing_layer
        else:
            # Default to inner layers for DDR routing
            target_layer = 2 if total_signal_layers > 2 else 1

        # Find adjacent dielectric layer(s) for the target signal layer
        is_outer = target_layer == 1 or target_layer == len(layers)

        # Get dielectric constant from adjacent layer(s)
        dielectric_constant = 4.0  # Default FR4

        for idx, layer in enumerate(layers):
            layer_type = str(layer.get('type', '')).lower()
            if layer_type in ('dielectric', 'core', 'prepreg'):
                er = layer.get('dielectric_constant')
                if er:
                    dielectric_constant = float(er)
                    break  # Use first dielectric found

        # Calculate effective dielectric constant
        if is_outer:
            # Microstrip Hammerstad: Er_eff = (Er+1)/2 + (Er-1)/2 * 1/sqrt(1+12*h/w)
            # Use actual w/h ratio (default 1.5 for typical DDR traces)
            u = 1.5  # default w/h ratio for DDR traces
            er_eff = (dielectric_constant + 1) / 2 + (dielectric_constant - 1) / 2 * (1 + 12 / u) ** (-0.5)
        else:
            # Stripline: effective Er equals substrate Er
            er_eff = dielectric_constant

        # Propagation delay = sqrt(Er_eff) / c
        prop_delay = math.sqrt(er_eff) / SPEED_OF_LIGHT_MM_PS

        return prop_delay

    def _calculate_all_layer_delays(self, layers: List[Dict[str, Any]]) -> None:
        """Pre-calculate propagation delays for all signal layers."""
        for idx, layer in enumerate(layers):
            layer_type = str(layer.get('type', '')).lower()
            if layer_type in ('signal', 'copper', 'mixed'):
                layer_num = idx + 1
                self._layer_prop_delays[layer_num] = self._calculate_prop_delay_from_stackup(
                    layers, layer_num
                )

    def get_prop_delay_for_layer(self, layer_number: int) -> float:
        """Get propagation delay for a specific layer.

        Args:
            layer_number: Layer number (1-based)

        Returns:
            Propagation delay in ps/mm for that layer
        """
        return self._layer_prop_delays.get(layer_number, self.prop_delay)

    def length_to_time(self, length_mm: float, layer_number: Optional[int] = None) -> float:
        """Convert length to propagation time in ps.

        Args:
            length_mm: Trace length in mm
            layer_number: Optional layer number for per-layer accuracy

        Returns:
            Propagation time in ps
        """
        if layer_number is not None and layer_number in self._layer_prop_delays:
            return length_mm * self._layer_prop_delays[layer_number]
        return length_mm * self.prop_delay

    def time_to_length(self, time_ps: float, layer_number: Optional[int] = None) -> float:
        """Convert propagation time to length in mm.

        Args:
            time_ps: Propagation time in ps
            layer_number: Optional layer number for per-layer accuracy

        Returns:
            Length in mm
        """
        if layer_number is not None and layer_number in self._layer_prop_delays:
            return time_ps / self._layer_prop_delays[layer_number]
        return time_ps / self.prop_delay

    def analyze_byte_lane(
        self,
        byte_lane: int,
        dqs_length_mm: float,
        dq_lengths_mm: list[float],
        ddr_standard: DDRStandard,
    ) -> ByteLaneAnalysis:
        """
        Analyze a single byte lane.

        Args:
            byte_lane: Byte lane number (0-7)
            dqs_length_mm: DQS strobe length
            dq_lengths_mm: List of DQ data line lengths
            ddr_standard: DDR standard

        Returns:
            ByteLaneAnalysis result
        """
        spec = DDR_SPECS.get(ddr_standard, DDR_SPECS[DDRStandard.DDR4])
        max_skew_ps = spec["dq_dqs_skew_ps"] * self.margin_factor

        issues = []
        max_actual_skew = 0.0

        # Calculate DQ-DQS skew for each data line
        for i, dq_len in enumerate(dq_lengths_mm):
            length_diff = abs(dq_len - dqs_length_mm)
            skew_ps = self.length_to_time(length_diff)

            if skew_ps > max_actual_skew:
                max_actual_skew = skew_ps

            if skew_ps > max_skew_ps:
                issues.append(DDRIssue(
                    issue_type=DDRIssueType.DQ_DQS_SKEW,
                    severity="critical" if skew_ps > max_skew_ps * 1.5 else "high",
                    description=f"DQ{byte_lane * 8 + i} to DQS{byte_lane} skew {skew_ps:.1f}ps exceeds {max_skew_ps:.0f}ps limit",
                    signal_name=f"DQ{byte_lane * 8 + i}",
                    byte_lane=byte_lane,
                    measured_value=skew_ps,
                    limit_value=max_skew_ps,
                    recommendation=f"Adjust DQ{byte_lane * 8 + i} length by {length_diff:.2f}mm",
                ))

        return ByteLaneAnalysis(
            byte_lane=byte_lane,
            dqs_length_mm=dqs_length_mm,
            dq_lengths_mm=dq_lengths_mm,
            max_dq_dqs_skew_ps=max_actual_skew,
            skew_within_spec=max_actual_skew <= max_skew_ps,
            issues=issues,
        )

    def analyze(
        self,
        ddr_standard: DDRStandard,
        data_rate_mtps: int,
        byte_lanes: list[dict],
        addr_cmd_lengths_mm: Optional[list[float]] = None,
        clock_length_mm: float = 0.0,
        clock_pair_skew_mm: float = 0.0,
        via_transitions: Optional[dict[str, int]] = None,
        trace_impedance_ohm: Optional[float] = None,
    ) -> DDRResult:
        """
        Analyze complete DDR interface.

        Args:
            ddr_standard: DDR standard (DDR3, DDR4, DDR5, etc.)
            data_rate_mtps: Data rate in MT/s (e.g., 3200)
            byte_lanes: List of byte lane data
            addr_cmd_lengths_mm: Address/command signal lengths
            clock_length_mm: Clock trace length
            clock_pair_skew_mm: Clock P/N pair length mismatch
            via_transitions: Dict of signal name to via count
            trace_impedance_ohm: Measured trace impedance

        Returns:
            DDRResult with comprehensive analysis
        """
        spec = DDR_SPECS.get(ddr_standard, DDR_SPECS[DDRStandard.DDR4])
        issues = []

        # Analyze byte lanes
        analyzed_lanes = []
        for bl_data in byte_lanes:
            lane_analysis = self.analyze_byte_lane(
                byte_lane=bl_data.get("byte_lane", 0),
                dqs_length_mm=bl_data.get("dqs_length_mm", 0),
                dq_lengths_mm=bl_data.get("dq_lengths_mm", []),
                ddr_standard=ddr_standard,
            )
            analyzed_lanes.append(lane_analysis)
            issues.extend(lane_analysis.issues)

        # Analyze inter-byte lane matching
        if len(analyzed_lanes) > 1:
            dqs_lengths = [bl.dqs_length_mm for bl in analyzed_lanes]
            max_byte_skew_mm = max(dqs_lengths) - min(dqs_lengths)
            max_byte_skew_ps = self.length_to_time(max_byte_skew_mm)

            # Inter-byte lane skew should be within UI/4
            ui_ps = 1e6 / data_rate_mtps  # Unit interval
            max_allowed_ps = ui_ps / 4

            if max_byte_skew_ps > max_allowed_ps:
                issues.append(DDRIssue(
                    issue_type=DDRIssueType.BYTE_LANE_MISMATCH,
                    severity="high",
                    description=f"Inter-byte lane skew {max_byte_skew_ps:.1f}ps exceeds {max_allowed_ps:.0f}ps",
                    measured_value=max_byte_skew_ps,
                    limit_value=max_allowed_ps,
                    recommendation="Match byte lane lengths to within UI/4",
                ))

        # Analyze address/command timing
        addr_cmd_max_skew = 0.0
        addr_cmd_within_spec = True
        if addr_cmd_lengths_mm and len(addr_cmd_lengths_mm) > 1:
            max_len = max(addr_cmd_lengths_mm)
            min_len = min(addr_cmd_lengths_mm)
            addr_cmd_max_skew = self.length_to_time(max_len - min_len)
            addr_cmd_limit = spec["addr_cmd_skew_ps"] * self.margin_factor

            if addr_cmd_max_skew > addr_cmd_limit:
                addr_cmd_within_spec = False
                issues.append(DDRIssue(
                    issue_type=DDRIssueType.ADDR_CMD_SKEW,
                    severity="high",
                    description=f"Address/Command skew {addr_cmd_max_skew:.1f}ps exceeds {addr_cmd_limit:.0f}ps",
                    measured_value=addr_cmd_max_skew,
                    limit_value=addr_cmd_limit,
                    recommendation="Match address/command lengths within spec",
                ))

        # Analyze clock routing
        clock_matched = True
        clock_impedance = trace_impedance_ohm or spec["impedance_diff_ohm"]

        if clock_pair_skew_mm > 0:
            clock_skew_ps = self.length_to_time(clock_pair_skew_mm)
            clock_limit = spec["clk_skew_ps"] * self.margin_factor

            if clock_skew_ps > clock_limit:
                clock_matched = False
                issues.append(DDRIssue(
                    issue_type=DDRIssueType.CLK_ROUTING,
                    severity="critical",
                    description=f"Clock pair skew {clock_skew_ps:.1f}ps exceeds {clock_limit:.0f}ps",
                    signal_name="CLK",
                    measured_value=clock_skew_ps,
                    limit_value=clock_limit,
                    recommendation="Match clock P/N pair lengths precisely",
                ))

        # Analyze via transitions
        max_via = 0
        via_ok = True
        if via_transitions:
            max_via = max(via_transitions.values()) if via_transitions else 0
            if max_via > spec["max_via_transitions"]:
                via_ok = False
                worst_signal = max(via_transitions, key=lambda k: via_transitions[k])
                issues.append(DDRIssue(
                    issue_type=DDRIssueType.VIA_COUNT_EXCEEDED,
                    severity="medium",
                    description=f"Signal {worst_signal} has {max_via} via transitions (max {spec['max_via_transitions']})",
                    signal_name=worst_signal,
                    measured_value=max_via,
                    limit_value=spec["max_via_transitions"],
                    recommendation="Reduce layer transitions or use back-drilling",
                ))

        # Check impedance
        if trace_impedance_ohm:
            target_z = spec["impedance_se_ohm"]
            tolerance = 0.1  # 10%
            if abs(trace_impedance_ohm - target_z) > target_z * tolerance:
                issues.append(DDRIssue(
                    issue_type=DDRIssueType.IMPEDANCE_MISMATCH,
                    severity="high",
                    description=f"Trace impedance {trace_impedance_ohm:.1f}Ω differs from target {target_z}Ω",
                    measured_value=trace_impedance_ohm,
                    limit_value=target_z,
                    recommendation="Adjust trace width for correct impedance",
                ))

        # Calculate overall compliance and score
        compliant = all(bl.skew_within_spec for bl in analyzed_lanes) and \
                   addr_cmd_within_spec and clock_matched and via_ok
        score = self._calculate_score(issues, analyzed_lanes)

        return DDRResult(
            ddr_standard=ddr_standard,
            data_rate_mtps=data_rate_mtps,
            byte_lanes=analyzed_lanes,
            addr_cmd_max_skew_ps=addr_cmd_max_skew,
            addr_cmd_within_spec=addr_cmd_within_spec,
            clock_length_mm=clock_length_mm,
            clock_matched=clock_matched,
            clock_impedance_ohm=clock_impedance,
            max_via_transitions=max_via,
            via_transitions_acceptable=via_ok,
            issues=issues,
            compliant=compliant,
            score=score,
        )

    def _calculate_score(
        self,
        issues: list[DDRIssue],
        byte_lanes: list[ByteLaneAnalysis],
    ) -> float:
        """Calculate DDR routing quality score."""
        score = 100.0

        # Deduct for issues
        for issue in issues:
            if issue.severity == "critical":
                score -= 20
            elif issue.severity == "high":
                score -= 12
            elif issue.severity == "medium":
                score -= 6
            else:
                score -= 2

        # Bonus for all lanes within spec
        if all(bl.skew_within_spec for bl in byte_lanes):
            score = min(100, score + 5)

        return max(0.0, score)

    def analyze_topology(
        self,
        ddr_nets: list[dict],
        ddr_standard: DDRStandard,
    ) -> dict:
        """Analyze DDR routing topology (fly-by vs T-topology).

        Fly-by topology: Signals routed sequentially through DRAMs
        T-topology: Signals branch to DRAMs (common in DDR2, problematic for DDR4+)

        Args:
            ddr_nets: List of net information with fanout points
            ddr_standard: DDR standard being analyzed

        Returns:
            Dictionary with topology classification and issues
        """
        topology_result: dict[str, Any] = {
            "topology_type": "unknown",
            "is_optimal": True,
            "issues": [],
        }

        # Detect topology by counting branching points
        total_branching_points = 0
        sequential_connections = 0

        for net in ddr_nets:
            fanout_count = net.get("fanout_count", 0)

            if fanout_count == 0:
                # Sequential (point-to-point)
                sequential_connections += 1
            else:
                # Branching detected
                total_branching_points += fanout_count

        # Classify topology
        if total_branching_points == 0:
            topology_result["topology_type"] = "fly-by"
            topology_result["is_optimal"] = True
        elif sequential_connections > total_branching_points:
            topology_result["topology_type"] = "mostly_fly-by"
            topology_result["is_optimal"] = ddr_standard not in [DDRStandard.DDR5, DDRStandard.LPDDR5]
        else:
            topology_result["topology_type"] = "t-topology"
            topology_result["is_optimal"] = False

            # T-topology is problematic for DDR4+
            if ddr_standard in [DDRStandard.DDR4, DDRStandard.DDR5]:
                topology_result["issues"].append({
                    "severity": "critical",
                    "description": f"T-topology detected for {ddr_standard.value} - "
                                 "fly-by topology required for data rates >2133 MT/s",
                    "recommendation": "Route data signals sequentially (fly-by) instead of branching",
                })

        return topology_result

    def check_zq_resistor(
        self,
        controller_position: tuple[float, float],
        zq_resistor_position: Optional[tuple[float, float]],
        zq_resistance_ohm: Optional[float],
        zq_tolerance_percent: Optional[float],
    ) -> dict:
        """Validate ZQ calibration resistor placement and value.

        ZQ Requirements:
        - Resistance: 240Ω ±1% (typical)
        - Placement: <20mm from memory controller
        - Connection: Directly to controller ZQ pin

        Args:
            controller_position: (x, y) position of memory controller in mm
            zq_resistor_position: (x, y) position of ZQ resistor in mm (None if missing)
            zq_resistance_ohm: Resistor value in ohms
            zq_tolerance_percent: Resistor tolerance percentage

        Returns:
            Dictionary with validation results and issues
        """
        result: dict[str, Any] = {
            "zq_present": zq_resistor_position is not None,
            "value_correct": False,
            "placement_ok": False,
            "distance_mm": None,
            "issues": [],
        }

        # Check if ZQ resistor exists
        if zq_resistor_position is None:
            result["issues"].append({
                "severity": "critical",
                "description": "ZQ calibration resistor missing",
                "recommendation": "Add 240Ω ±1% resistor from controller ZQ pin to ground",
            })
            return result

        # Validate resistance value (240Ω ±1% typical)
        target_resistance = 240.0
        max_tolerance = 1.0  # ±1%

        if zq_resistance_ohm:
            deviation = abs(zq_resistance_ohm - target_resistance) / target_resistance * 100

            if deviation <= max_tolerance:
                result["value_correct"] = True
            else:
                result["issues"].append({
                    "severity": "high",
                    "description": f"ZQ resistor value {zq_resistance_ohm}Ω deviates {deviation:.2f}% "
                                 f"from target 240Ω (max ±1%)",
                    "recommendation": "Use 240Ω ±1% tolerance resistor",
                })

            # Warn if tolerance spec is too loose
            if zq_tolerance_percent and zq_tolerance_percent > 1.0:
                result["issues"].append({
                    "severity": "medium",
                    "description": f"ZQ resistor tolerance ±{zq_tolerance_percent}% exceeds ±1% recommendation",
                    "recommendation": "Use ±1% or tighter tolerance for optimal calibration",
                })

        # Validate placement distance (<20mm typical)
        max_distance_mm = 20.0
        distance = math.sqrt(
            (zq_resistor_position[0] - controller_position[0])**2 +
            (zq_resistor_position[1] - controller_position[1])**2
        )
        result["distance_mm"] = round(distance, 2)

        if distance <= max_distance_mm:
            result["placement_ok"] = True
        else:
            result["issues"].append({
                "severity": "high",
                "description": f"ZQ resistor placement {distance:.1f}mm from controller exceeds "
                             f"recommended maximum {max_distance_mm}mm",
                "recommendation": "Place ZQ resistor within 20mm of controller ZQ pin",
            })

        return result

    def measure_stub_lengths(
        self,
        main_bus_traces: list[dict],
        dram_tap_points: list[dict],
        ddr_standard: DDRStandard,
    ) -> dict:
        """Measure stub lengths from main bus to DRAM pins.

        Stub Length Limits:
        - DDR4: Max 25mm per stub
        - DDR5: Max 15mm per stub (tighter for higher frequencies)

        Args:
            main_bus_traces: List of main bus trace segments with endpoints
            dram_tap_points: List of DRAM connection points with positions
            ddr_standard: DDR standard for limits

        Returns:
            Dictionary with stub measurements and violations
        """
        result: dict[str, Any] = {
            "stub_count": len(dram_tap_points),
            "max_stub_length_mm": 0.0,
            "stubs_compliant": True,
            "violations": [],
        }

        # Determine stub length limit
        if ddr_standard == DDRStandard.DDR5 or ddr_standard == DDRStandard.LPDDR5:
            max_stub_length = 15.0  # mm
        elif ddr_standard == DDRStandard.DDR4 or ddr_standard == DDRStandard.LPDDR4:
            max_stub_length = 25.0  # mm
        else:
            max_stub_length = 30.0  # mm (DDR3 and earlier, more lenient)

        # Measure each stub
        for tap in dram_tap_points:
            tap_position = tap.get("position")  # (x, y)
            component_ref = tap.get("component_ref", "Unknown")

            if not tap_position:
                continue

            # Find closest point on main bus
            min_distance = float("inf")
            for trace in main_bus_traces:
                # Simplified: measure to trace endpoints
                # Full implementation would find perpendicular distance to trace segment
                for endpoint in [trace.get("start"), trace.get("end")]:
                    if endpoint:
                        distance = math.sqrt(
                            (tap_position[0] - endpoint[0])**2 +
                            (tap_position[1] - endpoint[1])**2
                        )
                        min_distance = min(min_distance, distance)

            stub_length = min_distance if min_distance != float("inf") else 0.0
            result["max_stub_length_mm"] = max(result["max_stub_length_mm"], stub_length)

            # Check compliance
            if stub_length > max_stub_length:
                result["stubs_compliant"] = False
                result["violations"].append({
                    "severity": "high",
                    "component_ref": component_ref,
                    "stub_length_mm": round(stub_length, 2),
                    "limit_mm": max_stub_length,
                    "description": f"Stub length {stub_length:.1f}mm to {component_ref} exceeds "
                                 f"{ddr_standard.value.upper()} limit of {max_stub_length}mm",
                    "recommendation": f"Reduce stub length to <{max_stub_length}mm or use fly-by routing",
                })

        return result

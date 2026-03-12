"""
PCIe Interface Analyzer.

Analyzes PCIe lane routing for compliance:
- TX/RX differential pair matching
- Lane-to-lane skew
- REFCLK routing
- Via transitions
- Impedance control
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PCIeGeneration(str, Enum):
    """PCIe generation versions."""
    GEN1 = "gen1"  # 2.5 GT/s
    GEN2 = "gen2"  # 5 GT/s
    GEN3 = "gen3"  # 8 GT/s
    GEN4 = "gen4"  # 16 GT/s
    GEN5 = "gen5"  # 32 GT/s
    GEN6 = "gen6"  # 64 GT/s


class PCIeIssueType(str, Enum):
    """Types of PCIe routing issues."""
    PAIR_SKEW = "pair_skew"
    LANE_TO_LANE_SKEW = "lane_to_lane_skew"
    IMPEDANCE_MISMATCH = "impedance_mismatch"
    LENGTH_EXCEEDED = "length_exceeded"
    VIA_TRANSITIONS = "via_transitions"
    REFCLK_ROUTING = "refclk_routing"
    SPACING_VIOLATION = "spacing_violation"
    COUPLING_INSUFFICIENT = "coupling_insufficient"
    AC_CAP_MISSING = "ac_cap_missing"


@dataclass
class PCIeIssue:
    """A PCIe routing issue."""
    issue_type: PCIeIssueType
    severity: str
    description: str
    lane: Optional[int] = None
    signal_name: Optional[str] = None
    measured_value: Optional[float] = None
    limit_value: Optional[float] = None
    recommendation: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "issue_type": self.issue_type.value,
            "severity": self.severity,
            "description": self.description,
            "lane": self.lane,
            "signal_name": self.signal_name,
            "measured_value": round(self.measured_value, 3) if self.measured_value else None,
            "limit_value": round(self.limit_value, 3) if self.limit_value else None,
            "recommendation": self.recommendation,
        }


@dataclass
class PCIeLaneAnalysis:
    """Analysis of a single PCIe lane."""
    lane_number: int
    tx_p_length_mm: float
    tx_n_length_mm: float
    rx_p_length_mm: float
    rx_n_length_mm: float
    tx_pair_skew_ps: float
    rx_pair_skew_ps: float
    tx_length_mm: float  # Average TX length
    rx_length_mm: float  # Average RX length
    via_count: int
    issues: list[PCIeIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "lane_number": self.lane_number,
            "tx_p_length_mm": round(self.tx_p_length_mm, 2),
            "tx_n_length_mm": round(self.tx_n_length_mm, 2),
            "rx_p_length_mm": round(self.rx_p_length_mm, 2),
            "rx_n_length_mm": round(self.rx_n_length_mm, 2),
            "tx_pair_skew_ps": round(self.tx_pair_skew_ps, 1),
            "rx_pair_skew_ps": round(self.rx_pair_skew_ps, 1),
            "tx_length_mm": round(self.tx_length_mm, 2),
            "rx_length_mm": round(self.rx_length_mm, 2),
            "via_count": self.via_count,
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass
class PCIeResult:
    """Result of PCIe interface analysis."""
    generation: PCIeGeneration
    lane_count: int  # x1, x4, x8, x16

    # Lane analysis
    lanes: list[PCIeLaneAnalysis] = field(default_factory=list)

    # Lane-to-lane matching
    max_lane_to_lane_skew_ps: float = 0.0
    lane_matching_ok: bool = True

    # REFCLK analysis
    refclk_length_mm: float = 0.0
    refclk_pair_skew_ps: float = 0.0
    refclk_ok: bool = True

    # Overall metrics
    max_trace_length_mm: float = 0.0
    differential_impedance_ohm: float = 85.0

    # Issues
    issues: list[PCIeIssue] = field(default_factory=list)
    compliant: bool = True
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "generation": self.generation.value,
            "lane_count": self.lane_count,
            "lanes": [lane.to_dict() for lane in self.lanes],
            "max_lane_to_lane_skew_ps": round(self.max_lane_to_lane_skew_ps, 1),
            "lane_matching_ok": self.lane_matching_ok,
            "refclk_length_mm": round(self.refclk_length_mm, 2),
            "refclk_pair_skew_ps": round(self.refclk_pair_skew_ps, 1),
            "refclk_ok": self.refclk_ok,
            "max_trace_length_mm": round(self.max_trace_length_mm, 2),
            "differential_impedance_ohm": round(self.differential_impedance_ohm, 1),
            "issues": [i.to_dict() for i in self.issues],
            "compliant": self.compliant,
            "score": round(self.score, 1),
        }


# PCIe specifications by generation
PCIE_SPECS = {
    PCIeGeneration.GEN1: {
        "data_rate_gts": 2.5,
        "pair_skew_ps": 12,
        "lane_to_lane_skew_ps": 2000,  # 2ns for Gen1/2
        "max_length_mm": 500,
        "diff_impedance_ohm": 85,
        "tolerance_percent": 15,
        "max_via_transitions": 4,
        "refclk_pair_skew_ps": 5,
    },
    PCIeGeneration.GEN2: {
        "data_rate_gts": 5.0,
        "pair_skew_ps": 6,
        "lane_to_lane_skew_ps": 2000,
        "max_length_mm": 400,
        "diff_impedance_ohm": 85,
        "tolerance_percent": 15,
        "max_via_transitions": 4,
        "refclk_pair_skew_ps": 5,
    },
    PCIeGeneration.GEN3: {
        "data_rate_gts": 8.0,
        "pair_skew_ps": 3.5,
        "lane_to_lane_skew_ps": 1500,
        "max_length_mm": 350,
        "diff_impedance_ohm": 85,
        "tolerance_percent": 10,
        "max_via_transitions": 3,
        "refclk_pair_skew_ps": 3,
    },
    PCIeGeneration.GEN4: {
        "data_rate_gts": 16.0,
        "pair_skew_ps": 2,
        "lane_to_lane_skew_ps": 1000,
        "max_length_mm": 300,
        "diff_impedance_ohm": 85,
        "tolerance_percent": 10,
        "max_via_transitions": 2,
        "refclk_pair_skew_ps": 2,
    },
    PCIeGeneration.GEN5: {
        "data_rate_gts": 32.0,
        "pair_skew_ps": 1,
        "lane_to_lane_skew_ps": 500,
        "max_length_mm": 250,
        "diff_impedance_ohm": 85,
        "tolerance_percent": 8,
        "max_via_transitions": 2,
        "refclk_pair_skew_ps": 1,
    },
    PCIeGeneration.GEN6: {
        "data_rate_gts": 64.0,
        "pair_skew_ps": 0.5,
        "lane_to_lane_skew_ps": 250,
        "max_length_mm": 200,
        "diff_impedance_ohm": 85,
        "tolerance_percent": 5,
        "max_via_transitions": 2,
        "refclk_pair_skew_ps": 0.5,
    },
}


class PCIeAnalyzer:
    """
    PCIe interface routing analyzer.

    Analyzes PCIe lane routing for compliance with generation-specific requirements.

    Usage:
        analyzer = PCIeAnalyzer()
        result = analyzer.analyze(
            generation=PCIeGeneration.GEN4,
            lanes=[
                {
                    "lane": 0,
                    "tx_p_length_mm": 80.5,
                    "tx_n_length_mm": 80.6,
                    "rx_p_length_mm": 82.3,
                    "rx_n_length_mm": 82.4,
                    "via_count": 2,
                },
            ],
            refclk_length_mm=75.0,
            refclk_pair_skew_mm=0.1,
        )
    """

    PROP_DELAY_PS_PER_MM = 6.5

    def __init__(
        self,
        prop_delay_ps_per_mm: float = 6.5,
        strict_mode: bool = False,
    ):
        """
        Initialize analyzer.

        Args:
            prop_delay_ps_per_mm: Propagation delay
            strict_mode: Use 50% of spec limits
        """
        self.prop_delay = prop_delay_ps_per_mm
        self.margin = 0.5 if strict_mode else 1.0

    def length_to_time(self, length_mm: float) -> float:
        """Convert length to time in ps."""
        return length_mm * self.prop_delay

    def analyze_lane(
        self,
        lane_number: int,
        tx_p_length: float,
        tx_n_length: float,
        rx_p_length: float,
        rx_n_length: float,
        via_count: int,
        generation: PCIeGeneration,
    ) -> PCIeLaneAnalysis:
        """Analyze a single PCIe lane."""
        spec = PCIE_SPECS[generation]
        issues = []

        # Calculate pair skews
        tx_skew_mm = abs(tx_p_length - tx_n_length)
        rx_skew_mm = abs(rx_p_length - rx_n_length)
        tx_skew_ps = self.length_to_time(tx_skew_mm)
        rx_skew_ps = self.length_to_time(rx_skew_mm)

        # Check TX pair skew
        max_skew = spec["pair_skew_ps"] * self.margin
        if tx_skew_ps > max_skew:
            issues.append(PCIeIssue(
                issue_type=PCIeIssueType.PAIR_SKEW,
                severity="critical",
                description=f"Lane {lane_number} TX pair skew {tx_skew_ps:.1f}ps exceeds {max_skew:.1f}ps",
                lane=lane_number,
                signal_name=f"TX{lane_number}",
                measured_value=tx_skew_ps,
                limit_value=max_skew,
                recommendation="Match TX differential pair lengths",
            ))

        # Check RX pair skew
        if rx_skew_ps > max_skew:
            issues.append(PCIeIssue(
                issue_type=PCIeIssueType.PAIR_SKEW,
                severity="critical",
                description=f"Lane {lane_number} RX pair skew {rx_skew_ps:.1f}ps exceeds {max_skew:.1f}ps",
                lane=lane_number,
                signal_name=f"RX{lane_number}",
                measured_value=rx_skew_ps,
                limit_value=max_skew,
                recommendation="Match RX differential pair lengths",
            ))

        # Check via transitions
        if via_count > spec["max_via_transitions"]:
            issues.append(PCIeIssue(
                issue_type=PCIeIssueType.VIA_TRANSITIONS,
                severity="medium",
                description=f"Lane {lane_number} has {via_count} via transitions (max {spec['max_via_transitions']})",
                lane=lane_number,
                measured_value=via_count,
                limit_value=spec["max_via_transitions"],
                recommendation="Reduce layer transitions or use back-drilling",
            ))

        # Check max length
        max_len = max(tx_p_length, tx_n_length, rx_p_length, rx_n_length)
        if max_len > spec["max_length_mm"]:
            issues.append(PCIeIssue(
                issue_type=PCIeIssueType.LENGTH_EXCEEDED,
                severity="high",
                description=f"Lane {lane_number} length {max_len:.1f}mm exceeds {spec['max_length_mm']}mm",
                lane=lane_number,
                measured_value=max_len,
                limit_value=spec["max_length_mm"],
                recommendation="Shorten trace length or use signal conditioning",
            ))

        return PCIeLaneAnalysis(
            lane_number=lane_number,
            tx_p_length_mm=tx_p_length,
            tx_n_length_mm=tx_n_length,
            rx_p_length_mm=rx_p_length,
            rx_n_length_mm=rx_n_length,
            tx_pair_skew_ps=tx_skew_ps,
            rx_pair_skew_ps=rx_skew_ps,
            tx_length_mm=(tx_p_length + tx_n_length) / 2,
            rx_length_mm=(rx_p_length + rx_n_length) / 2,
            via_count=via_count,
            issues=issues,
        )

    def analyze(
        self,
        generation: PCIeGeneration,
        lanes: list[dict],
        refclk_length_mm: float = 0.0,
        refclk_pair_skew_mm: float = 0.0,
        differential_impedance_ohm: Optional[float] = None,
    ) -> PCIeResult:
        """
        Analyze complete PCIe interface.

        Args:
            generation: PCIe generation
            lanes: List of lane data dicts
            refclk_length_mm: REFCLK trace length
            refclk_pair_skew_mm: REFCLK pair skew
            differential_impedance_ohm: Measured impedance

        Returns:
            PCIeResult with full analysis
        """
        spec = PCIE_SPECS[generation]
        issues = []

        # Analyze each lane
        analyzed_lanes = []
        for lane_data in lanes:
            lane = self.analyze_lane(
                lane_number=lane_data.get("lane", 0),
                tx_p_length=lane_data.get("tx_p_length_mm", 0),
                tx_n_length=lane_data.get("tx_n_length_mm", 0),
                rx_p_length=lane_data.get("rx_p_length_mm", 0),
                rx_n_length=lane_data.get("rx_n_length_mm", 0),
                via_count=lane_data.get("via_count", 0),
                generation=generation,
            )
            analyzed_lanes.append(lane)
            issues.extend(lane.issues)

        # Calculate lane-to-lane skew
        lane_matching_ok = True
        max_l2l_skew = 0.0
        if len(analyzed_lanes) > 1:
            tx_lengths = [lane.tx_length_mm for lane in analyzed_lanes]
            rx_lengths = [lane.rx_length_mm for lane in analyzed_lanes]

            tx_skew_mm = max(tx_lengths) - min(tx_lengths)
            rx_skew_mm = max(rx_lengths) - min(rx_lengths)
            max_l2l_skew = self.length_to_time(max(tx_skew_mm, rx_skew_mm))

            if max_l2l_skew > spec["lane_to_lane_skew_ps"] * self.margin:
                lane_matching_ok = False
                issues.append(PCIeIssue(
                    issue_type=PCIeIssueType.LANE_TO_LANE_SKEW,
                    severity="high",
                    description=f"Lane-to-lane skew {max_l2l_skew:.0f}ps exceeds {spec['lane_to_lane_skew_ps']}ps",
                    measured_value=max_l2l_skew,
                    limit_value=spec["lane_to_lane_skew_ps"],
                    recommendation="Match all lane lengths within specification",
                ))

        # Analyze REFCLK
        refclk_ok = True
        refclk_skew_ps = self.length_to_time(refclk_pair_skew_mm)
        if refclk_skew_ps > spec["refclk_pair_skew_ps"] * self.margin:
            refclk_ok = False
            issues.append(PCIeIssue(
                issue_type=PCIeIssueType.REFCLK_ROUTING,
                severity="critical",
                description=f"REFCLK pair skew {refclk_skew_ps:.2f}ps exceeds {spec['refclk_pair_skew_ps']}ps",
                signal_name="REFCLK",
                measured_value=refclk_skew_ps,
                limit_value=spec["refclk_pair_skew_ps"],
                recommendation="Match REFCLK differential pair precisely",
            ))

        # Check impedance
        z_diff = differential_impedance_ohm or spec["diff_impedance_ohm"]
        target_z = spec["diff_impedance_ohm"]
        tolerance = spec["tolerance_percent"] / 100

        if differential_impedance_ohm:
            if abs(z_diff - target_z) > target_z * tolerance:
                issues.append(PCIeIssue(
                    issue_type=PCIeIssueType.IMPEDANCE_MISMATCH,
                    severity="high",
                    description=f"Impedance {z_diff:.1f}Ω outside {target_z}Ω ±{spec['tolerance_percent']}%",
                    measured_value=z_diff,
                    limit_value=target_z,
                    recommendation="Adjust trace geometry for correct impedance",
                ))

        # Calculate max length across all lanes
        max_length = 0.0
        for lane in analyzed_lanes:
            max_length = max(max_length, lane.tx_length_mm, lane.rx_length_mm)

        # Determine compliance
        compliant = lane_matching_ok and refclk_ok and \
                   all(len(lane.issues) == 0 for lane in analyzed_lanes)

        score = self._calculate_score(issues, analyzed_lanes)

        return PCIeResult(
            generation=generation,
            lane_count=len(lanes),
            lanes=analyzed_lanes,
            max_lane_to_lane_skew_ps=max_l2l_skew,
            lane_matching_ok=lane_matching_ok,
            refclk_length_mm=refclk_length_mm,
            refclk_pair_skew_ps=refclk_skew_ps,
            refclk_ok=refclk_ok,
            max_trace_length_mm=max_length,
            differential_impedance_ohm=z_diff,
            issues=issues,
            compliant=compliant,
            score=score,
        )

    def _calculate_score(
        self,
        issues: list[PCIeIssue],
        lanes: list[PCIeLaneAnalysis],
    ) -> float:
        """Calculate PCIe routing score."""
        score = 100.0

        for issue in issues:
            if issue.severity == "critical":
                score -= 20
            elif issue.severity == "high":
                score -= 12
            elif issue.severity == "medium":
                score -= 6
            else:
                score -= 2

        # Bonus for clean lanes
        clean_lanes = sum(1 for lane in lanes if not lane.issues)
        if clean_lanes == len(lanes):
            score = min(100, score + 5)

        return max(0.0, score)

"""
USB Interface Analyzer.

Analyzes USB 2.0/3.x/4 routing for compliance:
- Differential pair matching
- Impedance control
- Via transitions
- Length constraints
- ESD protection placement
- Connector placement
- Stub detection
- Common-mode impedance (USB 3.x/4)
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any

# Speed of light in mm/ps
SPEED_OF_LIGHT_MM_PS = 299.792458


class USBVersion(str, Enum):
    """USB versions."""
    USB2_LS = "usb2_ls"    # USB 2.0 Low Speed (1.5 Mbps)
    USB2_FS = "usb2_fs"    # USB 2.0 Full Speed (12 Mbps)
    USB2_HS = "usb2_hs"    # USB 2.0 High Speed (480 Mbps)
    USB3_GEN1 = "usb3_gen1"  # USB 3.0/3.1 Gen1 (5 Gbps)
    USB3_GEN2 = "usb3_gen2"  # USB 3.1 Gen2 (10 Gbps)
    USB3_GEN2X2 = "usb3_gen2x2"  # USB 3.2 Gen2x2 (20 Gbps)
    USB4_GEN2 = "usb4_gen2"  # USB4 Gen2 (20 Gbps)
    USB4_GEN3 = "usb4_gen3"  # USB4 Gen3 (40 Gbps)


class USBIssueType(str, Enum):
    """Types of USB routing issues."""
    PAIR_SKEW = "pair_skew"
    IMPEDANCE_MISMATCH = "impedance_mismatch"
    COMMON_MODE_IMPEDANCE = "common_mode_impedance"
    LENGTH_EXCEEDED = "length_exceeded"
    VIA_TRANSITIONS = "via_transitions"
    SPACING_VIOLATION = "spacing_violation"
    ESD_PROTECTION = "esd_protection"
    ESD_PLACEMENT = "esd_placement"
    TERMINATION = "termination"
    CONNECTOR_PLACEMENT = "connector_placement"
    STUB_DETECTED = "stub_detected"
    PHY_DISTANCE = "phy_distance"


@dataclass
class USBIssue:
    """A USB routing issue."""
    issue_type: USBIssueType
    severity: str
    description: str
    signal_name: Optional[str] = None
    measured_value: Optional[float] = None
    limit_value: Optional[float] = None
    recommendation: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "issue_type": self.issue_type.value,
            "severity": self.severity,
            "description": self.description,
            "signal_name": self.signal_name,
            "measured_value": round(self.measured_value, 3) if self.measured_value else None,
            "limit_value": round(self.limit_value, 3) if self.limit_value else None,
            "recommendation": self.recommendation,
        }


@dataclass
class USBPairAnalysis:
    """Analysis of a USB differential pair."""
    pair_name: str  # D+/D-, SSTX, SSRX, etc.
    p_length_mm: float
    n_length_mm: float
    pair_skew_ps: float
    skew_within_spec: bool
    via_count: int
    issues: list[USBIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pair_name": self.pair_name,
            "p_length_mm": round(self.p_length_mm, 2),
            "n_length_mm": round(self.n_length_mm, 2),
            "pair_skew_ps": round(self.pair_skew_ps, 1),
            "skew_within_spec": self.skew_within_spec,
            "via_count": self.via_count,
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass
class USBResult:
    """Result of USB interface analysis."""
    usb_version: USBVersion

    # Pair analysis
    pairs: list[USBPairAnalysis] = field(default_factory=list)

    # USB 2.0 specific
    usb2_length_mm: float = 0.0
    usb2_impedance_ohm: float = 90.0

    # USB 3.x specific
    sstx_length_mm: float = 0.0
    ssrx_length_mm: float = 0.0
    ss_impedance_ohm: float = 85.0

    # ESD analysis
    has_esd_protection: bool = True

    # Issues
    issues: list[USBIssue] = field(default_factory=list)
    compliant: bool = True
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "usb_version": self.usb_version.value,
            "pairs": [p.to_dict() for p in self.pairs],
            "usb2_length_mm": round(self.usb2_length_mm, 2),
            "usb2_impedance_ohm": round(self.usb2_impedance_ohm, 1),
            "sstx_length_mm": round(self.sstx_length_mm, 2),
            "ssrx_length_mm": round(self.ssrx_length_mm, 2),
            "ss_impedance_ohm": round(self.ss_impedance_ohm, 1),
            "has_esd_protection": self.has_esd_protection,
            "issues": [i.to_dict() for i in self.issues],
            "compliant": self.compliant,
            "score": round(self.score, 1),
        }


# USB specifications by version
USB_SPECS = {
    USBVersion.USB2_LS: {
        "data_rate_gbps": 0.0015,
        "pair_skew_ps": 500,
        "max_length_mm": 3000,  # Up to 3m for LS
        "diff_impedance_ohm": 90,
        "tolerance_percent": 15,
        "max_via_transitions": 6,
        "common_mode_impedance_ohm": None,  # Not required for USB2
        "max_esd_distance_mm": 25.0,  # ESD within 25mm of connector
        "max_phy_distance_mm": None,  # No limit for LS
    },
    USBVersion.USB2_FS: {
        "data_rate_gbps": 0.012,
        "pair_skew_ps": 200,
        "max_length_mm": 3000,
        "diff_impedance_ohm": 90,
        "tolerance_percent": 15,
        "max_via_transitions": 6,
        "common_mode_impedance_ohm": None,
        "max_esd_distance_mm": 25.0,
        "max_phy_distance_mm": None,
    },
    USBVersion.USB2_HS: {
        "data_rate_gbps": 0.48,
        "pair_skew_ps": 100,
        "max_length_mm": 150,  # ~6 inches max recommended
        "diff_impedance_ohm": 90,
        "tolerance_percent": 10,
        "max_via_transitions": 4,
        "common_mode_impedance_ohm": None,
        "max_esd_distance_mm": 15.0,  # Tighter for HS
        "max_phy_distance_mm": 100.0,  # ~4 inches from PHY to connector
    },
    USBVersion.USB3_GEN1: {
        "data_rate_gbps": 5.0,
        "pair_skew_ps": 10,
        "max_length_mm": 200,
        "diff_impedance_ohm": 85,
        "tolerance_percent": 10,
        "max_via_transitions": 2,
        "common_mode_impedance_ohm": 30,  # Zcm target for USB3+
        "common_mode_tolerance_percent": 15,
        "max_esd_distance_mm": 10.0,
        "max_phy_distance_mm": 150.0,
        "max_stub_length_mm": 1.0,  # Max stub length
    },
    USBVersion.USB3_GEN2: {
        "data_rate_gbps": 10.0,
        "pair_skew_ps": 5,
        "max_length_mm": 150,
        "diff_impedance_ohm": 85,
        "tolerance_percent": 10,
        "max_via_transitions": 2,
        "common_mode_impedance_ohm": 30,
        "common_mode_tolerance_percent": 15,
        "max_esd_distance_mm": 10.0,
        "max_phy_distance_mm": 100.0,
        "max_stub_length_mm": 0.5,  # Tighter for Gen2
    },
    USBVersion.USB3_GEN2X2: {
        "data_rate_gbps": 20.0,
        "pair_skew_ps": 3,
        "max_length_mm": 100,
        "diff_impedance_ohm": 85,
        "tolerance_percent": 8,
        "max_via_transitions": 2,
        "common_mode_impedance_ohm": 30,
        "common_mode_tolerance_percent": 12,
        "max_esd_distance_mm": 10.0,
        "max_phy_distance_mm": 75.0,
        "max_stub_length_mm": 0.3,
    },
    USBVersion.USB4_GEN2: {
        "data_rate_gbps": 20.0,
        "pair_skew_ps": 3,
        "max_length_mm": 100,
        "diff_impedance_ohm": 85,
        "tolerance_percent": 8,
        "max_via_transitions": 2,
        "common_mode_impedance_ohm": 25,  # Stricter for USB4
        "common_mode_tolerance_percent": 10,
        "max_esd_distance_mm": 8.0,
        "max_phy_distance_mm": 75.0,
        "max_stub_length_mm": 0.3,
    },
    USBVersion.USB4_GEN3: {
        "data_rate_gbps": 40.0,
        "pair_skew_ps": 2,
        "max_length_mm": 100,
        "diff_impedance_ohm": 85,
        "tolerance_percent": 8,
        "max_via_transitions": 2,
        "common_mode_impedance_ohm": 25,
        "common_mode_tolerance_percent": 10,
        "max_esd_distance_mm": 8.0,
        "max_phy_distance_mm": 50.0,
        "max_stub_length_mm": 0.2,  # Very tight for 40Gbps
    },
}


class USBAnalyzer:
    """
    USB interface routing analyzer.

    Analyzes USB 2.0/3.x/4 routing for compliance.

    Usage:
        analyzer = USBAnalyzer()
        result = analyzer.analyze(
            usb_version=USBVersion.USB3_GEN2,
            usb2_pair={"p_length_mm": 45.0, "n_length_mm": 45.1, "via_count": 2},
            sstx_pair={"p_length_mm": 50.0, "n_length_mm": 50.05, "via_count": 2},
            ssrx_pair={"p_length_mm": 52.0, "n_length_mm": 52.1, "via_count": 2},
            has_esd_protection=True,
        )
    """

    PROP_DELAY_PS_PER_MM = 6.5

    def __init__(
        self,
        prop_delay_ps_per_mm: float = 6.5,
    ):
        self.prop_delay = prop_delay_ps_per_mm

    def length_to_time(self, length_mm: float) -> float:
        """Convert length to time in ps."""
        return length_mm * self.prop_delay

    def analyze_pair(
        self,
        pair_name: str,
        p_length_mm: float,
        n_length_mm: float,
        via_count: int,
        usb_version: USBVersion,
    ) -> USBPairAnalysis:
        """Analyze a USB differential pair."""
        # Get appropriate spec
        spec = USB_SPECS.get(usb_version, USB_SPECS[USBVersion.USB3_GEN1])
        issues = []

        # Calculate skew
        skew_mm = abs(p_length_mm - n_length_mm)
        skew_ps = self.length_to_time(skew_mm)
        max_skew = spec["pair_skew_ps"]

        if skew_ps > max_skew:
            issues.append(USBIssue(
                issue_type=USBIssueType.PAIR_SKEW,
                severity="critical" if skew_ps > max_skew * 2 else "high",
                description=f"{pair_name} pair skew {skew_ps:.1f}ps exceeds {max_skew}ps",
                signal_name=pair_name,
                measured_value=skew_ps,
                limit_value=max_skew,
                recommendation=f"Match {pair_name} P/N lengths to within spec",
            ))

        # Check length
        avg_length = (p_length_mm + n_length_mm) / 2
        if avg_length > spec["max_length_mm"]:
            issues.append(USBIssue(
                issue_type=USBIssueType.LENGTH_EXCEEDED,
                severity="high",
                description=f"{pair_name} length {avg_length:.1f}mm exceeds {spec['max_length_mm']}mm",
                signal_name=pair_name,
                measured_value=avg_length,
                limit_value=spec["max_length_mm"],
                recommendation="Shorten USB routing or add redriver/retimer",
            ))

        # Check vias
        if via_count > spec["max_via_transitions"]:
            issues.append(USBIssue(
                issue_type=USBIssueType.VIA_TRANSITIONS,
                severity="medium",
                description=f"{pair_name} has {via_count} vias (max {spec['max_via_transitions']})",
                signal_name=pair_name,
                measured_value=via_count,
                limit_value=spec["max_via_transitions"],
                recommendation="Minimize layer transitions",
            ))

        return USBPairAnalysis(
            pair_name=pair_name,
            p_length_mm=p_length_mm,
            n_length_mm=n_length_mm,
            pair_skew_ps=skew_ps,
            skew_within_spec=skew_ps <= max_skew,
            via_count=via_count,
            issues=issues,
        )

    def analyze(
        self,
        usb_version: USBVersion,
        usb2_pair: Optional[dict] = None,
        sstx_pair: Optional[dict] = None,
        ssrx_pair: Optional[dict] = None,
        usb2_impedance_ohm: Optional[float] = None,
        ss_impedance_ohm: Optional[float] = None,
        common_mode_impedance_ohm: Optional[float] = None,
        has_esd_protection: bool = True,
        esd_distance_mm: Optional[float] = None,
        phy_to_connector_mm: Optional[float] = None,
        stub_lengths_mm: Optional[List[float]] = None,
    ) -> USBResult:
        """
        Analyze USB interface routing.

        Args:
            usb_version: USB version
            usb2_pair: D+/D- pair data {p_length_mm, n_length_mm, via_count}
            sstx_pair: SuperSpeed TX pair data
            ssrx_pair: SuperSpeed RX pair data
            usb2_impedance_ohm: Measured USB 2.0 impedance
            ss_impedance_ohm: Measured SuperSpeed impedance
            common_mode_impedance_ohm: Common-mode impedance (for USB3+)
            has_esd_protection: Whether ESD protection is present
            esd_distance_mm: Distance from ESD device to connector
            phy_to_connector_mm: Distance from USB PHY to connector
            stub_lengths_mm: List of stub lengths detected on USB traces

        Returns:
            USBResult with analysis
        """
        pairs = []
        issues = []
        spec = USB_SPECS.get(usb_version, USB_SPECS[USBVersion.USB3_GEN1])

        # Analyze USB 2.0 pair
        usb2_length = 0.0
        if usb2_pair:
            pair = self.analyze_pair(
                "D+/D-",
                usb2_pair.get("p_length_mm", 0),
                usb2_pair.get("n_length_mm", 0),
                usb2_pair.get("via_count", 0),
                USBVersion.USB2_HS,  # Use USB2 specs
            )
            pairs.append(pair)
            issues.extend(pair.issues)
            usb2_length = (usb2_pair.get("p_length_mm", 0) + usb2_pair.get("n_length_mm", 0)) / 2

        # Analyze SuperSpeed pairs
        sstx_length = 0.0
        ssrx_length = 0.0

        if sstx_pair:
            pair = self.analyze_pair(
                "SSTX",
                sstx_pair.get("p_length_mm", 0),
                sstx_pair.get("n_length_mm", 0),
                sstx_pair.get("via_count", 0),
                usb_version,
            )
            pairs.append(pair)
            issues.extend(pair.issues)
            sstx_length = (sstx_pair.get("p_length_mm", 0) + sstx_pair.get("n_length_mm", 0)) / 2

        if ssrx_pair:
            pair = self.analyze_pair(
                "SSRX",
                ssrx_pair.get("p_length_mm", 0),
                ssrx_pair.get("n_length_mm", 0),
                ssrx_pair.get("via_count", 0),
                usb_version,
            )
            pairs.append(pair)
            issues.extend(pair.issues)
            ssrx_length = (ssrx_pair.get("p_length_mm", 0) + ssrx_pair.get("n_length_mm", 0)) / 2

        # Check impedances
        z_usb2 = usb2_impedance_ohm or 90.0
        z_ss = ss_impedance_ohm or 85.0

        if usb2_impedance_ohm:
            target = 90.0
            if abs(usb2_impedance_ohm - target) > target * 0.10:
                issues.append(USBIssue(
                    issue_type=USBIssueType.IMPEDANCE_MISMATCH,
                    severity="high",
                    description=f"USB 2.0 impedance {usb2_impedance_ohm:.1f}Ω outside 90Ω ±10%",
                    measured_value=usb2_impedance_ohm,
                    limit_value=target,
                    recommendation="Adjust USB 2.0 trace geometry",
                ))

        if ss_impedance_ohm and usb_version not in [USBVersion.USB2_HS, USBVersion.USB2_FS, USBVersion.USB2_LS]:
            target = spec["diff_impedance_ohm"]
            tolerance = spec["tolerance_percent"] / 100
            if abs(ss_impedance_ohm - target) > target * tolerance:
                issues.append(USBIssue(
                    issue_type=USBIssueType.IMPEDANCE_MISMATCH,
                    severity="high",
                    description=f"SuperSpeed impedance {ss_impedance_ohm:.1f}Ω outside {target}Ω ±{spec['tolerance_percent']}%",
                    measured_value=ss_impedance_ohm,
                    limit_value=target,
                    recommendation="Adjust SuperSpeed trace geometry",
                ))

        # Check common-mode impedance (USB3+ requirement)
        zcm_target = spec.get("common_mode_impedance_ohm")
        if common_mode_impedance_ohm and zcm_target:
            zcm_tolerance = spec.get("common_mode_tolerance_percent", 15) / 100
            if abs(common_mode_impedance_ohm - zcm_target) > zcm_target * zcm_tolerance:
                issues.append(USBIssue(
                    issue_type=USBIssueType.COMMON_MODE_IMPEDANCE,
                    severity="high",
                    description=f"Common-mode impedance {common_mode_impedance_ohm:.1f}Ω outside {zcm_target}Ω ±{int(zcm_tolerance*100)}%",
                    measured_value=common_mode_impedance_ohm,
                    limit_value=zcm_target,
                    recommendation="Adjust trace geometry for proper Zcm - check pair spacing and symmetry",
                ))

        # Check ESD placement (distance from connector)
        max_esd_distance = spec.get("max_esd_distance_mm")
        if esd_distance_mm is not None and max_esd_distance is not None:
            if esd_distance_mm > max_esd_distance:
                issues.append(USBIssue(
                    issue_type=USBIssueType.ESD_PLACEMENT,
                    severity="medium",
                    description=f"ESD device {esd_distance_mm:.1f}mm from connector (max {max_esd_distance}mm)",
                    measured_value=esd_distance_mm,
                    limit_value=max_esd_distance,
                    recommendation="Move ESD protection closer to USB connector",
                ))

        # Check PHY to connector distance
        max_phy_distance = spec.get("max_phy_distance_mm")
        if phy_to_connector_mm is not None and max_phy_distance is not None:
            if phy_to_connector_mm > max_phy_distance:
                issues.append(USBIssue(
                    issue_type=USBIssueType.PHY_DISTANCE,
                    severity="high" if phy_to_connector_mm > max_phy_distance * 1.3 else "medium",
                    description=f"PHY to connector {phy_to_connector_mm:.1f}mm exceeds {max_phy_distance}mm recommendation",
                    measured_value=phy_to_connector_mm,
                    limit_value=max_phy_distance,
                    recommendation="Reduce PHY-to-connector distance or add redriver/retimer",
                ))

        # Check for stubs on USB traces
        max_stub = spec.get("max_stub_length_mm")
        if stub_lengths_mm and max_stub is not None:
            for i, stub_len in enumerate(stub_lengths_mm):
                if stub_len > max_stub:
                    issues.append(USBIssue(
                        issue_type=USBIssueType.STUB_DETECTED,
                        severity="critical" if stub_len > max_stub * 2 else "high",
                        description=f"Stub #{i+1} length {stub_len:.2f}mm exceeds {max_stub}mm at {spec['data_rate_gbps']:.1f}Gbps",
                        measured_value=stub_len,
                        limit_value=max_stub,
                        recommendation="Remove or back-drill vias, use blind vias, or eliminate T-branches",
                    ))

        # Check ESD protection
        if not has_esd_protection:
            issues.append(USBIssue(
                issue_type=USBIssueType.ESD_PROTECTION,
                severity="high",
                description="USB interface lacks ESD protection",
                recommendation="Add TVS diodes near USB connector",
            ))

        # Determine compliance
        compliant = all(p.skew_within_spec for p in pairs) and has_esd_protection
        score = self._calculate_score(issues, pairs)

        return USBResult(
            usb_version=usb_version,
            pairs=pairs,
            usb2_length_mm=usb2_length,
            usb2_impedance_ohm=z_usb2,
            sstx_length_mm=sstx_length,
            ssrx_length_mm=ssrx_length,
            ss_impedance_ohm=z_ss,
            has_esd_protection=has_esd_protection,
            issues=issues,
            compliant=compliant,
            score=score,
        )

    def _calculate_score(
        self,
        issues: list[USBIssue],
        pairs: list[USBPairAnalysis],
    ) -> float:
        """Calculate USB routing score."""
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

        if all(p.skew_within_spec for p in pairs):
            score = min(100, score + 5)

        return max(0.0, score)

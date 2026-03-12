"""
Cable Coupling Analyzer.

Analyzes potential EMI coupling between PCB traces
and attached cables.
"""
from dataclasses import dataclass, field
from enum import Enum


class CableCouplingType(Enum):
    """Types of cable coupling."""
    COMMON_MODE_TO_CABLE = "common_mode_to_cable"
    NEAR_CONNECTOR_RADIATION = "near_connector_radiation"
    SHIELD_GROUNDING = "shield_grounding"
    FILTER_EFFECTIVENESS = "filter_effectiveness"


class CouplingRisk(Enum):
    """Cable coupling risk levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class CableCouplingIssue:
    """A cable coupling issue."""
    issue_id: str
    coupling_type: CableCouplingType
    connector_ref: str
    cable_type: str

    detail: str
    affected_signals: list[str]

    # Risk factors
    has_filtering: bool
    has_proper_grounding: bool
    high_speed_interface: bool

    risk: CouplingRisk
    recommendation: str

    def to_dict(self) -> dict:
        return {
            "issue_id": self.issue_id,
            "coupling_type": self.coupling_type.value,
            "connector_ref": self.connector_ref,
            "cable_type": self.cable_type,
            "detail": self.detail,
            "affected_signals": self.affected_signals[:5],
            "has_filtering": self.has_filtering,
            "has_proper_grounding": self.has_proper_grounding,
            "high_speed_interface": self.high_speed_interface,
            "risk": self.risk.value,
            "recommendation": self.recommendation,
        }


@dataclass
class ConnectorAnalysis:
    """Cable coupling analysis for a connector."""
    connector_ref: str
    connector_type: str
    cable_type: str

    # Routing analysis
    trace_to_connector_length_mm: float
    high_speed_signals: list[str]
    slow_signals: list[str]

    # Protection analysis
    has_esd_protection: bool
    has_common_mode_choke: bool
    has_ferrite: bool
    shield_grounding_points: int

    issues: list[CableCouplingIssue]
    overall_risk: CouplingRisk

    def to_dict(self) -> dict:
        return {
            "connector_ref": self.connector_ref,
            "connector_type": self.connector_type,
            "cable_type": self.cable_type,
            "trace_to_connector_length_mm": round(self.trace_to_connector_length_mm, 1),
            "high_speed_signals": self.high_speed_signals[:5],
            "slow_signals": self.slow_signals[:5],
            "has_esd_protection": self.has_esd_protection,
            "has_common_mode_choke": self.has_common_mode_choke,
            "has_ferrite": self.has_ferrite,
            "shield_grounding_points": self.shield_grounding_points,
            "issues": [i.to_dict() for i in self.issues],
            "overall_risk": self.overall_risk.value,
        }


@dataclass
class CableCouplingResult:
    """Result of cable coupling analysis."""
    connectors_analyzed: list[ConnectorAnalysis] = field(default_factory=list)
    total_issues: int = 0
    high_risk_connectors: list[str] = field(default_factory=list)
    missing_cm_chokes: int = 0
    missing_esd: int = 0
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "connectors_analyzed": [c.to_dict() for c in self.connectors_analyzed],
            "total_issues": self.total_issues,
            "high_risk_connectors": self.high_risk_connectors,
            "missing_cm_chokes": self.missing_cm_chokes,
            "missing_esd": self.missing_esd,
            "score": round(self.score, 1),
        }


# Cable types and their EMI characteristics
CABLE_EMI_PROFILE = {
    "usb": {
        "typical_length_m": 2.0,
        "shielded": True,
        "antenna_efficiency_at_100mhz": 0.3,
        "requires_cm_choke": True,
        "requires_esd": True,
    },
    "hdmi": {
        "typical_length_m": 1.5,
        "shielded": True,
        "antenna_efficiency_at_100mhz": 0.25,
        "requires_cm_choke": True,
        "requires_esd": True,
    },
    "ethernet": {
        "typical_length_m": 5.0,
        "shielded": False,  # Cat5e/6 usually unshielded
        "antenna_efficiency_at_100mhz": 0.5,
        "requires_cm_choke": True,  # Magnetics with CM rejection
        "requires_esd": True,
    },
    "power": {
        "typical_length_m": 2.0,
        "shielded": False,
        "antenna_efficiency_at_100mhz": 0.6,
        "requires_cm_choke": True,
        "requires_esd": False,
    },
    "ribbon": {
        "typical_length_m": 0.3,
        "shielded": False,
        "antenna_efficiency_at_100mhz": 0.7,
        "requires_cm_choke": False,
        "requires_esd": False,
    },
    "coax": {
        "typical_length_m": 1.0,
        "shielded": True,
        "antenna_efficiency_at_100mhz": 0.1,
        "requires_cm_choke": False,
        "requires_esd": True,
    },
}


class CableCouplingAnalyzer:
    """
    Cable coupling EMI analyzer.

    Cables attached to PCBs are efficient antennas.
    Common mode currents on cables radiate and receive
    electromagnetic energy.

    Key factors:
    - Cable length vs wavelength
    - Common mode impedance
    - Grounding and filtering at connector

    The analyzer checks:
    1. Common mode filtering (chokes, ferrites)
    2. Shield grounding strategy
    3. High-speed signal routing to connectors
    4. ESD protection presence

    Usage:
        analyzer = CableCouplingAnalyzer()
        result = analyzer.analyze(
            connectors=[
                {
                    "ref": "J1",
                    "type": "USB-C",
                    "cable_type": "usb",
                    "signals": ["USB_TX_P", "USB_TX_N", "USB_RX_P", "USB_RX_N"],
                    "high_speed_signals": ["USB_TX_P", "USB_TX_N"],
                    "trace_length_mm": 25,
                    "has_cm_choke": True,
                    "has_esd": True,
                    "shield_grounds": 4,
                },
            ],
        )
    """

    def __init__(
        self,
        require_cm_choke_for_hs: bool = True,
        min_shield_grounds: int = 2,
    ):
        """
        Initialize analyzer.

        Args:
            require_cm_choke_for_hs: Require CM choke for high-speed interfaces
            min_shield_grounds: Minimum shield grounding points
        """
        self.require_cm = require_cm_choke_for_hs
        self.min_grounds = min_shield_grounds

    def analyze_connector(self, connector: dict) -> ConnectorAnalysis:
        """
        Analyze cable coupling for a connector.

        Args:
            connector: Connector specification

        Returns:
            ConnectorAnalysis with issues
        """
        ref = connector.get("ref", "J?")
        conn_type = connector.get("type", "unknown")
        cable_type = connector.get("cable_type", "ribbon").lower()
        signals = connector.get("signals", [])
        hs_signals = connector.get("high_speed_signals", [])
        trace_len = connector.get("trace_length_mm", 0)
        has_cm = connector.get("has_cm_choke", False)
        has_esd = connector.get("has_esd", False)
        has_ferrite = connector.get("has_ferrite", False)
        shield_grounds = connector.get("shield_grounds", 0)

        slow_signals = [s for s in signals if s not in hs_signals]
        cable_profile = CABLE_EMI_PROFILE.get(cable_type, CABLE_EMI_PROFILE["ribbon"])

        issues = []
        is_high_speed = len(hs_signals) > 0

        # Check CM choke requirement
        if cable_profile.get("requires_cm_choke", False) and not has_cm:
            if is_high_speed or cable_type in ["ethernet", "power"]:
                risk = CouplingRisk.HIGH if is_high_speed else CouplingRisk.MEDIUM
                issues.append(CableCouplingIssue(
                    issue_id=f"{ref}_cm_choke",
                    coupling_type=CableCouplingType.COMMON_MODE_TO_CABLE,
                    connector_ref=ref,
                    cable_type=cable_type,
                    detail="No common mode choke on cable interface",
                    affected_signals=signals[:3],
                    has_filtering=has_ferrite,
                    has_proper_grounding=shield_grounds >= self.min_grounds,
                    high_speed_interface=is_high_speed,
                    risk=risk,
                    recommendation=f"Add common mode choke on {conn_type} interface",
                ))

        # Check ESD protection
        if cable_profile.get("requires_esd", False) and not has_esd:
            issues.append(CableCouplingIssue(
                issue_id=f"{ref}_esd",
                coupling_type=CableCouplingType.FILTER_EFFECTIVENESS,
                connector_ref=ref,
                cable_type=cable_type,
                detail="No ESD protection on connector",
                affected_signals=signals[:3],
                has_filtering=has_cm or has_ferrite,
                has_proper_grounding=shield_grounds >= self.min_grounds,
                high_speed_interface=is_high_speed,
                risk=CouplingRisk.MEDIUM,
                recommendation=f"Add ESD protection TVS diodes on {conn_type}",
            ))

        # Check shield grounding
        if cable_profile.get("shielded", False):
            if shield_grounds < self.min_grounds:
                issues.append(CableCouplingIssue(
                    issue_id=f"{ref}_shield",
                    coupling_type=CableCouplingType.SHIELD_GROUNDING,
                    connector_ref=ref,
                    cable_type=cable_type,
                    detail=f"Only {shield_grounds} shield ground points (min: {self.min_grounds})",
                    affected_signals=[],
                    has_filtering=has_cm or has_ferrite,
                    has_proper_grounding=False,
                    high_speed_interface=is_high_speed,
                    risk=CouplingRisk.HIGH if is_high_speed else CouplingRisk.MEDIUM,
                    recommendation=f"Add shield ground connections (need {self.min_grounds - shield_grounds} more)",
                ))

        # Check high-speed routing near connector
        if is_high_speed and trace_len > 50:
            issues.append(CableCouplingIssue(
                issue_id=f"{ref}_routing",
                coupling_type=CableCouplingType.NEAR_CONNECTOR_RADIATION,
                connector_ref=ref,
                cable_type=cable_type,
                detail=f"Long trace runs ({trace_len:.0f}mm) near connector",
                affected_signals=hs_signals[:3],
                has_filtering=has_cm or has_ferrite,
                has_proper_grounding=shield_grounds >= self.min_grounds,
                high_speed_interface=True,
                risk=CouplingRisk.MEDIUM,
                recommendation="Minimize trace length near connector edge",
            ))

        # Determine overall risk
        if any(i.risk == CouplingRisk.CRITICAL for i in issues):
            overall = CouplingRisk.CRITICAL
        elif any(i.risk == CouplingRisk.HIGH for i in issues):
            overall = CouplingRisk.HIGH
        elif any(i.risk == CouplingRisk.MEDIUM for i in issues):
            overall = CouplingRisk.MEDIUM
        else:
            overall = CouplingRisk.LOW

        return ConnectorAnalysis(
            connector_ref=ref,
            connector_type=conn_type,
            cable_type=cable_type,
            trace_to_connector_length_mm=trace_len,
            high_speed_signals=hs_signals,
            slow_signals=slow_signals,
            has_esd_protection=has_esd,
            has_common_mode_choke=has_cm,
            has_ferrite=has_ferrite,
            shield_grounding_points=shield_grounds,
            issues=issues,
            overall_risk=overall,
        )

    def analyze(self, connectors: list[dict]) -> CableCouplingResult:
        """
        Analyze all connectors for cable coupling issues.

        Args:
            connectors: List of connector specifications

        Returns:
            CableCouplingResult with analysis
        """
        analyses = []
        total_issues = 0
        high_risk = []
        missing_cm = 0
        missing_esd = 0

        for conn in connectors:
            analysis = self.analyze_connector(conn)
            analyses.append(analysis)
            total_issues += len(analysis.issues)

            if analysis.overall_risk in [CouplingRisk.CRITICAL, CouplingRisk.HIGH]:
                high_risk.append(analysis.connector_ref)

            if not analysis.has_common_mode_choke and analysis.high_speed_signals:
                missing_cm += 1
            if not analysis.has_esd_protection:
                missing_esd += 1

        score = self._calculate_score(analyses)

        return CableCouplingResult(
            connectors_analyzed=analyses,
            total_issues=total_issues,
            high_risk_connectors=high_risk,
            missing_cm_chokes=missing_cm,
            missing_esd=missing_esd,
            score=score,
        )

    def _calculate_score(self, analyses: list[ConnectorAnalysis]) -> float:
        """Calculate cable coupling score."""
        score = 100.0

        for a in analyses:
            for issue in a.issues:
                if issue.risk == CouplingRisk.CRITICAL:
                    score -= 15
                elif issue.risk == CouplingRisk.HIGH:
                    score -= 10
                elif issue.risk == CouplingRisk.MEDIUM:
                    score -= 5
                else:
                    score -= 2

        return max(0.0, score)

"""
Common Mode Analyzer.

Analyzes differential pairs for common mode conversion
issues that lead to EMI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CommonModeIssueType(Enum):
    """Types of common mode issues."""
    LENGTH_MISMATCH = "length_mismatch"
    IMPEDANCE_IMBALANCE = "impedance_imbalance"
    ASYMMETRIC_VIA = "asymmetric_via"
    REFERENCE_DISCONTINUITY = "reference_discontinuity"
    STUB = "stub"
    ASYMMETRIC_COUPLING = "asymmetric_coupling"


@dataclass
class CommonModeIssue:
    """A common mode conversion issue."""
    issue_id: str
    issue_type: CommonModeIssueType
    pair_name: str
    location: Optional[str]

    # Issue details
    detail: str
    measured_value: float
    limit_value: float
    unit: str

    # Estimated CM conversion
    estimated_cm_db: float  # Estimated common mode level in dB

    severity: str
    recommendation: str

    def to_dict(self) -> dict:
        return {
            "issue_id": self.issue_id,
            "issue_type": self.issue_type.value,
            "pair_name": self.pair_name,
            "location": self.location,
            "detail": self.detail,
            "measured_value": round(self.measured_value, 3),
            "limit_value": round(self.limit_value, 3),
            "unit": self.unit,
            "estimated_cm_db": round(self.estimated_cm_db, 1),
            "severity": self.severity,
            "recommendation": self.recommendation,
        }


@dataclass
class DiffPairAnalysis:
    """Common mode analysis for a differential pair."""
    pair_name: str
    positive_net: str
    negative_net: str

    # Length analysis
    length_p_mm: float
    length_n_mm: float
    length_mismatch_mm: float
    length_mismatch_percent: float

    # Via analysis
    via_count_p: int
    via_count_n: int
    via_mismatch: int

    # Issues found
    issues: list[CommonModeIssue]

    # Estimated total CM
    total_cm_estimate_db: float

    def to_dict(self) -> dict:
        return {
            "pair_name": self.pair_name,
            "positive_net": self.positive_net,
            "negative_net": self.negative_net,
            "length_p_mm": round(self.length_p_mm, 2),
            "length_n_mm": round(self.length_n_mm, 2),
            "length_mismatch_mm": round(self.length_mismatch_mm, 3),
            "length_mismatch_percent": round(self.length_mismatch_percent, 2),
            "via_count_p": self.via_count_p,
            "via_count_n": self.via_count_n,
            "via_mismatch": self.via_mismatch,
            "issues": [i.to_dict() for i in self.issues],
            "total_cm_estimate_db": round(self.total_cm_estimate_db, 1),
        }


@dataclass
class CommonModeResult:
    """Result of common mode analysis."""
    pairs_analyzed: list[DiffPairAnalysis] = field(default_factory=list)
    total_issues: int = 0
    critical_pairs: list[str] = field(default_factory=list)
    worst_cm_estimate_db: float = -60.0
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "pairs_analyzed": [p.to_dict() for p in self.pairs_analyzed],
            "total_issues": self.total_issues,
            "critical_pairs": self.critical_pairs,
            "worst_cm_estimate_db": round(self.worst_cm_estimate_db, 1),
            "score": round(self.score, 1),
        }


class CommonModeAnalyzer:
    """
    Common mode analyzer for differential pairs.

    Common mode (CM) signals are a major source of EMI.
    CM is generated when the two signals of a differential
    pair become unbalanced due to:

    - Length mismatch (skew)
    - Impedance imbalance
    - Asymmetric via transitions
    - Reference plane discontinuities
    - Stubs or T-junctions

    The CM voltage can be estimated from:
    V_cm ≈ (V_diff/2) * (ΔZ/Z0) for impedance imbalance
    V_cm ≈ V_diff * sin(π * Δt * f) for timing skew

    Usage:
        analyzer = CommonModeAnalyzer(
            max_length_mismatch_mm=0.25,
            max_length_mismatch_percent=0.5,
        )
        result = analyzer.analyze(
            pairs=[
                {
                    "name": "USB_SS_TX",
                    "p_net": "USB_TX_P",
                    "n_net": "USB_TX_N",
                    "p_length_mm": 45.5,
                    "n_length_mm": 45.3,
                    "p_vias": 2,
                    "n_vias": 2,
                    "signal_freq_mhz": 5000,  # 5GHz
                    "reference_breaks": [],
                },
            ],
        )
    """

    def __init__(
        self,
        max_length_mismatch_mm: float = 0.25,
        max_length_mismatch_percent: float = 0.5,
        max_via_mismatch: int = 0,
    ):
        """
        Initialize analyzer.

        Args:
            max_length_mismatch_mm: Maximum absolute length mismatch
            max_length_mismatch_percent: Maximum length mismatch percentage
            max_via_mismatch: Maximum via count difference
        """
        self.max_mm = max_length_mismatch_mm
        self.max_pct = max_length_mismatch_percent
        self.max_via = max_via_mismatch

    def estimate_cm_from_skew(
        self,
        skew_mm: float,
        signal_freq_mhz: float,
        er: float = 4.3,
    ) -> float:
        """
        Estimate common mode level from length skew.

        CM conversion from skew: ~20*log10(π * Δt * f)

        Args:
            skew_mm: Length mismatch in mm
            signal_freq_mhz: Signal frequency
            er: Dielectric constant

        Returns:
            Estimated CM level in dB (relative to differential)
        """
        import math

        # Propagation delay ~6.5ps/mm for FR4
        delay_per_mm_ps = 6.5 * math.sqrt(er / 4.3)
        skew_ps = skew_mm * delay_per_mm_ps

        freq_hz = signal_freq_mhz * 1e6
        skew_s = skew_ps * 1e-12

        # Phase difference
        phase = math.pi * skew_s * freq_hz

        if phase > 0:
            cm_ratio = math.sin(phase)
            if cm_ratio > 0:
                return 20 * math.log10(cm_ratio)

        return -60.0  # Very low CM

    def estimate_cm_from_impedance(
        self,
        z_mismatch_percent: float,
    ) -> float:
        """
        Estimate CM from impedance imbalance.

        CM ≈ (ΔZ / 2*Z0) in ratio

        Args:
            z_mismatch_percent: Impedance mismatch percentage

        Returns:
            CM level in dB
        """
        import math

        ratio = z_mismatch_percent / 200  # ΔZ / 2*Z0
        if ratio > 0:
            return 20 * math.log10(ratio)
        return -60.0

    def analyze_pair(self, pair: dict) -> DiffPairAnalysis:
        """
        Analyze a single differential pair.

        Args:
            pair: Pair specification

        Returns:
            DiffPairAnalysis with issues
        """
        name = pair.get("name", "unknown")
        p_net = pair.get("p_net", "P")
        n_net = pair.get("n_net", "N")
        p_len = pair.get("p_length_mm", 0)
        n_len = pair.get("n_length_mm", 0)
        p_vias = pair.get("p_vias", 0)
        n_vias = pair.get("n_vias", 0)
        freq = pair.get("signal_freq_mhz", 100)
        ref_breaks = pair.get("reference_breaks", [])
        z_mismatch = pair.get("impedance_mismatch_percent", 0)

        issues = []
        total_cm = -60.0  # Start with very low CM

        # Length mismatch
        avg_len = (p_len + n_len) / 2 if (p_len + n_len) > 0 else 1
        mismatch_mm = abs(p_len - n_len)
        mismatch_pct = (mismatch_mm / avg_len) * 100 if avg_len > 0 else 0

        if mismatch_mm > self.max_mm or mismatch_pct > self.max_pct:
            cm_db = self.estimate_cm_from_skew(mismatch_mm, freq)
            total_cm = max(total_cm, cm_db)

            severity = "critical" if cm_db > -20 else "high" if cm_db > -30 else "medium"
            issues.append(CommonModeIssue(
                issue_id=f"{name}_length",
                issue_type=CommonModeIssueType.LENGTH_MISMATCH,
                pair_name=name,
                location=None,
                detail=f"P={p_len:.2f}mm, N={n_len:.2f}mm",
                measured_value=mismatch_mm,
                limit_value=self.max_mm,
                unit="mm",
                estimated_cm_db=cm_db,
                severity=severity,
                recommendation=f"Reduce length mismatch to <{self.max_mm}mm",
            ))

        # Via mismatch
        via_diff = abs(p_vias - n_vias)
        if via_diff > self.max_via:
            # Each extra via adds ~5dB CM
            cm_db = min(-20 + via_diff * 5, -10)
            total_cm = max(total_cm, cm_db)

            issues.append(CommonModeIssue(
                issue_id=f"{name}_via",
                issue_type=CommonModeIssueType.ASYMMETRIC_VIA,
                pair_name=name,
                location=None,
                detail=f"P has {p_vias} vias, N has {n_vias} vias",
                measured_value=float(via_diff),
                limit_value=float(self.max_via),
                unit="vias",
                estimated_cm_db=cm_db,
                severity="high" if via_diff > 1 else "medium",
                recommendation="Ensure equal number of vias on P and N",
            ))

        # Reference discontinuities
        for ref_break in ref_breaks:
            # Reference break causes significant CM
            cm_db = -15  # Typically -10 to -20 dB CM
            total_cm = max(total_cm, cm_db)

            issues.append(CommonModeIssue(
                issue_id=f"{name}_ref_{ref_break.get('id', 'x')}",
                issue_type=CommonModeIssueType.REFERENCE_DISCONTINUITY,
                pair_name=name,
                location=ref_break.get("location"),
                detail=ref_break.get("description", "Reference plane break"),
                measured_value=1.0,
                limit_value=0.0,
                unit="break",
                estimated_cm_db=cm_db,
                severity="critical",
                recommendation="Route pair to avoid reference plane breaks",
            ))

        # Impedance imbalance
        if z_mismatch > 0:
            cm_db = self.estimate_cm_from_impedance(z_mismatch)
            total_cm = max(total_cm, cm_db)

            if cm_db > -30:
                issues.append(CommonModeIssue(
                    issue_id=f"{name}_z",
                    issue_type=CommonModeIssueType.IMPEDANCE_IMBALANCE,
                    pair_name=name,
                    location=None,
                    detail=f"{z_mismatch:.1f}% impedance imbalance",
                    measured_value=z_mismatch,
                    limit_value=5.0,  # 5% typical limit
                    unit="%",
                    estimated_cm_db=cm_db,
                    severity="high" if cm_db > -20 else "medium",
                    recommendation="Balance trace widths and spacing",
                ))

        return DiffPairAnalysis(
            pair_name=name,
            positive_net=p_net,
            negative_net=n_net,
            length_p_mm=p_len,
            length_n_mm=n_len,
            length_mismatch_mm=mismatch_mm,
            length_mismatch_percent=mismatch_pct,
            via_count_p=p_vias,
            via_count_n=n_vias,
            via_mismatch=via_diff,
            issues=issues,
            total_cm_estimate_db=total_cm,
        )

    def analyze(self, pairs: list[dict]) -> CommonModeResult:
        """
        Analyze all differential pairs.

        Args:
            pairs: List of pair specifications

        Returns:
            CommonModeResult with analysis
        """
        analyses = []
        total_issues = 0
        critical = []
        worst_cm = -60.0

        for pair in pairs:
            analysis = self.analyze_pair(pair)
            analyses.append(analysis)
            total_issues += len(analysis.issues)

            if analysis.total_cm_estimate_db > worst_cm:
                worst_cm = analysis.total_cm_estimate_db

            if analysis.total_cm_estimate_db > -20:
                critical.append(analysis.pair_name)

        score = self._calculate_score(analyses)

        return CommonModeResult(
            pairs_analyzed=analyses,
            total_issues=total_issues,
            critical_pairs=critical,
            worst_cm_estimate_db=worst_cm,
            score=score,
        )

    def _calculate_score(self, analyses: list[DiffPairAnalysis]) -> float:
        """Calculate common mode score."""
        score = 100.0

        for a in analyses:
            for issue in a.issues:
                if issue.severity == "critical":
                    score -= 15
                elif issue.severity == "high":
                    score -= 8
                elif issue.severity == "medium":
                    score -= 4
                else:
                    score -= 2

        return max(0.0, score)

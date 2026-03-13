"""
Ethernet Interface Analyzer.

Analyzes Ethernet PHY routing for 10/100/1G/2.5G/5G/10G:
- MDI pair analysis
- Common mode rejection
- Return path continuity
- Termination
- Via count validation
- Ground plane stitching
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any


class EthernetSpeed(str, Enum):
    """Ethernet speed grades."""
    ETH_10M = "10m"
    ETH_100M = "100m"
    ETH_1G = "1g"
    ETH_2_5G = "2_5g"
    ETH_5G = "5g"
    ETH_10G = "10g"


class EthernetIssueType(str, Enum):
    """Types of Ethernet routing issues."""
    PAIR_SKEW = "pair_skew"
    PAIR_TO_PAIR_SKEW = "pair_to_pair_skew"
    IMPEDANCE_MISMATCH = "impedance_mismatch"
    LENGTH_EXCEEDED = "length_exceeded"
    COUPLING_INSUFFICIENT = "coupling_insufficient"
    TRANSFORMER_PLACEMENT = "transformer_placement"
    TERMINATION = "termination"
    CMC_MISSING = "cmc_missing"
    VIA_COUNT_EXCEEDED = "via_count_exceeded"
    RETURN_PATH_DISCONTINUITY = "return_path_discontinuity"
    GROUND_STITCHING = "ground_stitching"
    ISOLATION_DISTANCE = "isolation_distance"
    REFERENCE_PLANE_GAP = "reference_plane_gap"


@dataclass
class EthernetIssue:
    """An Ethernet routing issue."""
    issue_type: EthernetIssueType
    severity: str
    description: str
    pair_name: Optional[str] = None
    measured_value: Optional[float] = None
    limit_value: Optional[float] = None
    recommendation: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "issue_type": self.issue_type.value,
            "severity": self.severity,
            "description": self.description,
            "pair_name": self.pair_name,
            "measured_value": round(self.measured_value, 3) if self.measured_value else None,
            "limit_value": round(self.limit_value, 3) if self.limit_value else None,
            "recommendation": self.recommendation,
        }


@dataclass
class MDIPairAnalysis:
    """Analysis of an MDI pair."""
    pair_name: str  # MDI0, MDI1, MDI2, MDI3
    p_length_mm: float
    n_length_mm: float
    pair_skew_ps: float
    avg_length_mm: float
    skew_within_spec: bool
    issues: list[EthernetIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pair_name": self.pair_name,
            "p_length_mm": round(self.p_length_mm, 2),
            "n_length_mm": round(self.n_length_mm, 2),
            "pair_skew_ps": round(self.pair_skew_ps, 1),
            "avg_length_mm": round(self.avg_length_mm, 2),
            "skew_within_spec": self.skew_within_spec,
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass
class EthernetResult:
    """Result of Ethernet interface analysis."""
    speed: EthernetSpeed

    # MDI pair analysis
    mdi_pairs: list[MDIPairAnalysis] = field(default_factory=list)

    # Pair-to-pair matching
    max_pair_to_pair_skew_ps: float = 0.0
    pair_matching_ok: bool = True

    # Component analysis
    has_magnetics: bool = True
    magnetics_distance_mm: float = 0.0
    has_cmc: bool = False  # Common mode choke

    # Impedance
    differential_impedance_ohm: float = 100.0

    # Issues
    issues: list[EthernetIssue] = field(default_factory=list)
    compliant: bool = True
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "speed": self.speed.value,
            "mdi_pairs": [p.to_dict() for p in self.mdi_pairs],
            "max_pair_to_pair_skew_ps": round(self.max_pair_to_pair_skew_ps, 1),
            "pair_matching_ok": self.pair_matching_ok,
            "has_magnetics": self.has_magnetics,
            "magnetics_distance_mm": round(self.magnetics_distance_mm, 2),
            "has_cmc": self.has_cmc,
            "differential_impedance_ohm": round(self.differential_impedance_ohm, 1),
            "issues": [i.to_dict() for i in self.issues],
            "compliant": self.compliant,
            "score": round(self.score, 1),
        }


# Ethernet specifications by speed
ETHERNET_SPECS = {
    EthernetSpeed.ETH_10M: {
        "pair_count": 2,
        "pair_skew_ps": 2000,
        "pair_to_pair_skew_ps": 5000,
        "max_length_mm": 150,
        "diff_impedance_ohm": 100,
        "tolerance_percent": 15,
        "magnetics_distance_mm": 50,
        "max_via_count": 6,
        "min_stitch_spacing_mm": 10.0,  # Ground via stitching
        "isolation_gap_mm": 0.5,  # IEEE 802.3 isolation
    },
    EthernetSpeed.ETH_100M: {
        "pair_count": 2,
        "pair_skew_ps": 500,
        "pair_to_pair_skew_ps": 2000,
        "max_length_mm": 100,
        "diff_impedance_ohm": 100,
        "tolerance_percent": 10,
        "magnetics_distance_mm": 25,
        "max_via_count": 4,
        "min_stitch_spacing_mm": 8.0,
        "isolation_gap_mm": 0.5,
    },
    EthernetSpeed.ETH_1G: {
        "pair_count": 4,
        "pair_skew_ps": 100,
        "pair_to_pair_skew_ps": 500,
        "max_length_mm": 75,
        "diff_impedance_ohm": 100,
        "tolerance_percent": 10,
        "magnetics_distance_mm": 20,
        "max_via_count": 2,
        "min_stitch_spacing_mm": 5.0,
        "isolation_gap_mm": 0.5,
    },
    EthernetSpeed.ETH_2_5G: {
        "pair_count": 4,
        "pair_skew_ps": 50,
        "pair_to_pair_skew_ps": 200,
        "max_length_mm": 50,
        "diff_impedance_ohm": 100,
        "tolerance_percent": 10,
        "magnetics_distance_mm": 15,
        "max_via_count": 2,
        "min_stitch_spacing_mm": 3.0,
        "isolation_gap_mm": 0.5,
    },
    EthernetSpeed.ETH_5G: {
        "pair_count": 4,
        "pair_skew_ps": 30,
        "pair_to_pair_skew_ps": 150,
        "max_length_mm": 45,
        "diff_impedance_ohm": 100,
        "tolerance_percent": 10,
        "magnetics_distance_mm": 12,
        "max_via_count": 2,
        "min_stitch_spacing_mm": 2.5,
        "isolation_gap_mm": 0.5,
    },
    EthernetSpeed.ETH_10G: {
        "pair_count": 4,
        "pair_skew_ps": 20,
        "pair_to_pair_skew_ps": 100,
        "max_length_mm": 40,
        "diff_impedance_ohm": 100,
        "tolerance_percent": 8,
        "magnetics_distance_mm": 10,
        "max_via_count": 2,
        "min_stitch_spacing_mm": 2.0,
        "isolation_gap_mm": 0.5,
    },
}


class EthernetAnalyzer:
    """
    Ethernet PHY interface routing analyzer.

    Analyzes Ethernet routing for 10/100/1G/2.5G/5G/10G compliance.

    Usage:
        analyzer = EthernetAnalyzer()
        result = analyzer.analyze(
            speed=EthernetSpeed.ETH_1G,
            mdi_pairs=[
                {"name": "MDI0", "p_length_mm": 25.0, "n_length_mm": 25.1},
                {"name": "MDI1", "p_length_mm": 25.5, "n_length_mm": 25.4},
                {"name": "MDI2", "p_length_mm": 24.8, "n_length_mm": 24.9},
                {"name": "MDI3", "p_length_mm": 25.2, "n_length_mm": 25.3},
            ],
            has_magnetics=True,
            magnetics_distance_mm=15.0,
        )
    """

    PROP_DELAY_PS_PER_MM = 6.5

    def __init__(self, prop_delay_ps_per_mm: float = 6.5):
        self.prop_delay = prop_delay_ps_per_mm

    def length_to_time(self, length_mm: float) -> float:
        """Convert length to time in ps."""
        return length_mm * self.prop_delay

    def analyze_pair(
        self,
        pair_name: str,
        p_length_mm: float,
        n_length_mm: float,
        speed: EthernetSpeed,
    ) -> MDIPairAnalysis:
        """Analyze a single MDI pair."""
        spec = ETHERNET_SPECS.get(speed, ETHERNET_SPECS[EthernetSpeed.ETH_1G])
        issues = []

        skew_mm = abs(p_length_mm - n_length_mm)
        skew_ps = self.length_to_time(skew_mm)
        max_skew = spec["pair_skew_ps"]

        if skew_ps > max_skew:
            issues.append(EthernetIssue(
                issue_type=EthernetIssueType.PAIR_SKEW,
                severity="high" if skew_ps > max_skew * 1.5 else "medium",
                description=f"{pair_name} intra-pair skew {skew_ps:.1f}ps exceeds {max_skew}ps",
                pair_name=pair_name,
                measured_value=skew_ps,
                limit_value=max_skew,
                recommendation=f"Match {pair_name} P/N lengths",
            ))

        avg_length = (p_length_mm + n_length_mm) / 2
        if avg_length > spec["max_length_mm"]:
            issues.append(EthernetIssue(
                issue_type=EthernetIssueType.LENGTH_EXCEEDED,
                severity="medium",
                description=f"{pair_name} length {avg_length:.1f}mm exceeds recommended {spec['max_length_mm']}mm",
                pair_name=pair_name,
                measured_value=avg_length,
                limit_value=spec["max_length_mm"],
                recommendation="Shorten PHY to magnetics routing",
            ))

        return MDIPairAnalysis(
            pair_name=pair_name,
            p_length_mm=p_length_mm,
            n_length_mm=n_length_mm,
            pair_skew_ps=skew_ps,
            avg_length_mm=avg_length,
            skew_within_spec=skew_ps <= max_skew,
            issues=issues,
        )

    def analyze(
        self,
        speed: EthernetSpeed,
        mdi_pairs: list[dict],
        has_magnetics: bool = True,
        magnetics_distance_mm: float = 0.0,
        has_cmc: bool = False,
        differential_impedance_ohm: Optional[float] = None,
        via_counts: Optional[Dict[str, int]] = None,
        has_return_path_continuity: Optional[bool] = None,
        reference_plane_gaps: Optional[List[float]] = None,
        ground_stitch_spacing_mm: Optional[float] = None,
        isolation_gap_mm: Optional[float] = None,
    ) -> EthernetResult:
        """
        Analyze Ethernet interface routing.

        Args:
            speed: Ethernet speed grade
            mdi_pairs: List of MDI pair data
            has_magnetics: Whether magnetics transformer is present
            magnetics_distance_mm: Distance from PHY to magnetics
            has_cmc: Whether common mode choke is present
            differential_impedance_ohm: Measured differential impedance
            via_counts: Dict of pair name to via count (e.g., {"MDI0": 2, "MDI1": 3})
            has_return_path_continuity: Whether return path is continuous
            reference_plane_gaps: List of gap widths under MDI traces (mm)
            ground_stitch_spacing_mm: Spacing between ground stitching vias
            isolation_gap_mm: Gap between MDI and chassis ground (IEEE 802.3)

        Returns:
            EthernetResult with analysis
        """
        spec = ETHERNET_SPECS.get(speed, ETHERNET_SPECS[EthernetSpeed.ETH_1G])
        issues = []
        analyzed_pairs = []

        # Analyze each MDI pair
        for pair_data in mdi_pairs:
            pair = self.analyze_pair(
                pair_name=pair_data.get("name", "MDI?"),
                p_length_mm=pair_data.get("p_length_mm", 0),
                n_length_mm=pair_data.get("n_length_mm", 0),
                speed=speed,
            )
            analyzed_pairs.append(pair)
            issues.extend(pair.issues)

            # Check via count for this pair
            pair_name = pair_data.get("name", "MDI?")
            if via_counts and pair_name in via_counts:
                pair_vias = via_counts[pair_name]
                max_vias = spec.get("max_via_count", 4)
                if pair_vias > max_vias:
                    issues.append(EthernetIssue(
                        issue_type=EthernetIssueType.VIA_COUNT_EXCEEDED,
                        severity="medium" if pair_vias <= max_vias + 2 else "high",
                        description=f"{pair_name} has {pair_vias} vias (max {max_vias} for {speed.value})",
                        pair_name=pair_name,
                        measured_value=pair_vias,
                        limit_value=max_vias,
                        recommendation="Minimize via transitions on MDI pairs",
                    ))

        # Check pair-to-pair matching
        pair_matching_ok = True
        max_p2p_skew = 0.0
        if len(analyzed_pairs) > 1:
            lengths = [p.avg_length_mm for p in analyzed_pairs]
            max_diff = max(lengths) - min(lengths)
            max_p2p_skew = self.length_to_time(max_diff)

            if max_p2p_skew > spec["pair_to_pair_skew_ps"]:
                pair_matching_ok = False
                issues.append(EthernetIssue(
                    issue_type=EthernetIssueType.PAIR_TO_PAIR_SKEW,
                    severity="high",
                    description=f"Pair-to-pair skew {max_p2p_skew:.0f}ps exceeds {spec['pair_to_pair_skew_ps']}ps",
                    measured_value=max_p2p_skew,
                    limit_value=spec["pair_to_pair_skew_ps"],
                    recommendation="Match all MDI pair lengths",
                ))

        # Check magnetics
        if not has_magnetics:
            issues.append(EthernetIssue(
                issue_type=EthernetIssueType.TRANSFORMER_PLACEMENT,
                severity="critical",
                description="Ethernet magnetics transformer not detected",
                recommendation="Add isolation transformer per IEEE 802.3",
            ))
        elif magnetics_distance_mm > spec["magnetics_distance_mm"]:
            issues.append(EthernetIssue(
                issue_type=EthernetIssueType.TRANSFORMER_PLACEMENT,
                severity="medium",
                description=f"PHY to magnetics distance {magnetics_distance_mm:.1f}mm exceeds {spec['magnetics_distance_mm']}mm",
                measured_value=magnetics_distance_mm,
                limit_value=spec["magnetics_distance_mm"],
                recommendation="Place magnetics closer to PHY",
            ))

        # Check return path continuity
        if has_return_path_continuity is not None and not has_return_path_continuity:
            issues.append(EthernetIssue(
                issue_type=EthernetIssueType.RETURN_PATH_DISCONTINUITY,
                severity="high",
                description="Return path discontinuity detected on MDI traces",
                recommendation="Ensure solid ground plane under MDI routing from PHY to magnetics",
            ))

        # Check reference plane gaps under MDI traces
        if reference_plane_gaps:
            max_gap = spec.get("isolation_gap_mm", 0.5) * 2  # Allow up to 2x isolation gap
            for i, gap in enumerate(reference_plane_gaps):
                if gap > max_gap:
                    issues.append(EthernetIssue(
                        issue_type=EthernetIssueType.REFERENCE_PLANE_GAP,
                        severity="high" if gap > max_gap * 1.5 else "medium",
                        description=f"Reference plane gap {gap:.2f}mm under MDI traces (max {max_gap:.2f}mm)",
                        measured_value=gap,
                        limit_value=max_gap,
                        recommendation="Add ground stitching vias to bridge gap or reroute MDI traces",
                    ))

        # Check ground stitching near MDI traces
        min_stitch = spec.get("min_stitch_spacing_mm", 5.0)
        if ground_stitch_spacing_mm is not None:
            if ground_stitch_spacing_mm > min_stitch * 2:  # More than 2x recommended spacing
                issues.append(EthernetIssue(
                    issue_type=EthernetIssueType.GROUND_STITCHING,
                    severity="medium",
                    description=f"Ground stitching spacing {ground_stitch_spacing_mm:.1f}mm exceeds {min_stitch * 2:.1f}mm (recommended {min_stitch:.1f}mm)",
                    measured_value=ground_stitch_spacing_mm,
                    limit_value=min_stitch * 2,
                    recommendation="Add ground vias at regular intervals near MDI traces",
                ))

        # Check IEEE 802.3 isolation gap (MDI to chassis)
        isolation_requirement = spec.get("isolation_gap_mm", 0.5)
        if isolation_gap_mm is not None:
            if isolation_gap_mm < isolation_requirement:
                issues.append(EthernetIssue(
                    issue_type=EthernetIssueType.ISOLATION_DISTANCE,
                    severity="high",
                    description=f"MDI to chassis isolation {isolation_gap_mm:.2f}mm below {isolation_requirement:.2f}mm IEEE 802.3 requirement",
                    measured_value=isolation_gap_mm,
                    limit_value=isolation_requirement,
                    recommendation="Increase clearance between MDI signals and chassis ground",
                ))

        # Check impedance
        z_diff = differential_impedance_ohm or 100.0
        if differential_impedance_ohm:
            target = spec["diff_impedance_ohm"]
            tolerance = spec["tolerance_percent"] / 100
            if abs(z_diff - target) > target * tolerance:
                issues.append(EthernetIssue(
                    issue_type=EthernetIssueType.IMPEDANCE_MISMATCH,
                    severity="high",
                    description=f"MDI impedance {z_diff:.1f}Ω outside {target}Ω ±{spec['tolerance_percent']}%",
                    measured_value=z_diff,
                    limit_value=target,
                    recommendation="Adjust MDI trace geometry for 100Ω differential",
                ))

        # Recommend CMC for high-speed
        if speed in [EthernetSpeed.ETH_2_5G, EthernetSpeed.ETH_10G] and not has_cmc:
            issues.append(EthernetIssue(
                issue_type=EthernetIssueType.CMC_MISSING,
                severity="low",
                description="Common mode choke recommended for 2.5G+ Ethernet",
                recommendation="Add CMC to reduce common mode noise",
            ))

        compliant = all(p.skew_within_spec for p in analyzed_pairs) and \
                   pair_matching_ok and has_magnetics
        score = self._calculate_score(issues, analyzed_pairs)

        return EthernetResult(
            speed=speed,
            mdi_pairs=analyzed_pairs,
            max_pair_to_pair_skew_ps=max_p2p_skew,
            pair_matching_ok=pair_matching_ok,
            has_magnetics=has_magnetics,
            magnetics_distance_mm=magnetics_distance_mm,
            has_cmc=has_cmc,
            differential_impedance_ohm=z_diff,
            issues=issues,
            compliant=compliant,
            score=score,
        )

    def _calculate_score(
        self,
        issues: list[EthernetIssue],
        pairs: list[MDIPairAnalysis],
    ) -> float:
        """Calculate Ethernet routing score."""
        score = 100.0

        for issue in issues:
            if issue.severity == "critical":
                score -= 25
            elif issue.severity == "high":
                score -= 12
            elif issue.severity == "medium":
                score -= 6
            else:
                score -= 2

        if all(p.skew_within_spec for p in pairs):
            score = min(100, score + 5)

        return max(0.0, score)

"""
Generic Length Matching Analyzer.

Provides length matching analysis for any signal group:
- Intra-group length matching
- Inter-group skew calculation
- Timing margin analysis
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SignalLength:
    """A signal with length information."""
    signal_name: str
    length_mm: float
    layer: Optional[str] = None
    via_count: int = 0

    def to_dict(self) -> dict:
        return {
            "signal_name": self.signal_name,
            "length_mm": round(self.length_mm, 2),
            "layer": self.layer,
            "via_count": self.via_count,
        }


@dataclass
class MatchingGroup:
    """A group of signals that should be length-matched."""
    group_name: str
    signals: list[SignalLength]
    target_length_mm: Optional[float] = None
    max_skew_ps: float = 50.0
    propagation_delay_ps_per_mm: float = 6.5

    @property
    def min_length(self) -> float:
        return min(s.length_mm for s in self.signals) if self.signals else 0

    @property
    def max_length(self) -> float:
        return max(s.length_mm for s in self.signals) if self.signals else 0

    @property
    def avg_length(self) -> float:
        return sum(s.length_mm for s in self.signals) / len(self.signals) if self.signals else 0

    @property
    def length_spread_mm(self) -> float:
        return self.max_length - self.min_length

    @property
    def skew_ps(self) -> float:
        return self.length_spread_mm * self.propagation_delay_ps_per_mm

    @property
    def within_spec(self) -> bool:
        return self.skew_ps <= self.max_skew_ps

    def to_dict(self) -> dict:
        return {
            "group_name": self.group_name,
            "signals": [s.to_dict() for s in self.signals],
            "target_length_mm": self.target_length_mm,
            "max_skew_ps": self.max_skew_ps,
            "min_length_mm": round(self.min_length, 2),
            "max_length_mm": round(self.max_length, 2),
            "avg_length_mm": round(self.avg_length, 2),
            "length_spread_mm": round(self.length_spread_mm, 2),
            "actual_skew_ps": round(self.skew_ps, 1),
            "within_spec": self.within_spec,
        }


@dataclass
class LengthMatchIssue:
    """A length matching issue."""
    severity: str
    description: str
    group_name: str
    signal_name: Optional[str] = None
    current_length_mm: Optional[float] = None
    target_length_mm: Optional[float] = None
    adjustment_mm: Optional[float] = None
    recommendation: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "description": self.description,
            "group_name": self.group_name,
            "signal_name": self.signal_name,
            "current_length_mm": round(self.current_length_mm, 2) if self.current_length_mm else None,
            "target_length_mm": round(self.target_length_mm, 2) if self.target_length_mm else None,
            "adjustment_mm": round(self.adjustment_mm, 2) if self.adjustment_mm else None,
            "recommendation": self.recommendation,
        }


@dataclass
class LengthMatchResult:
    """Result of length matching analysis."""
    groups: list[MatchingGroup] = field(default_factory=list)
    inter_group_skew_ps: float = 0.0
    issues: list[LengthMatchIssue] = field(default_factory=list)
    all_matched: bool = True
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "groups": [g.to_dict() for g in self.groups],
            "inter_group_skew_ps": round(self.inter_group_skew_ps, 1),
            "issues": [i.to_dict() for i in self.issues],
            "all_matched": self.all_matched,
            "score": round(self.score, 1),
        }


class LengthMatcher:
    """
    Generic length matching analyzer.

    Analyzes signal groups for length matching compliance.

    Usage:
        matcher = LengthMatcher()
        result = matcher.analyze(
            groups=[
                MatchingGroup(
                    group_name="DDR_DQ0",
                    max_skew_ps=25,
                    signals=[
                        SignalLength("DQ0", 45.5),
                        SignalLength("DQ1", 45.7),
                        SignalLength("DQ2", 45.3),
                    ],
                ),
            ],
            match_groups_to_each_other=True,
            inter_group_max_skew_ps=100,
        )
    """

    def __init__(
        self,
        prop_delay_ps_per_mm: float = 6.5,
    ):
        self.prop_delay = prop_delay_ps_per_mm

    def analyze_group(
        self,
        group: MatchingGroup,
    ) -> tuple[MatchingGroup, list[LengthMatchIssue]]:
        """
        Analyze a single matching group.

        Returns tuple of (updated group, list of issues).
        """
        issues = []

        # Set propagation delay for group
        group.propagation_delay_ps_per_mm = self.prop_delay

        # Determine target length
        target = group.target_length_mm or group.avg_length

        # Check each signal
        for signal in group.signals:
            length_diff = signal.length_mm - target
            skew_contribution = abs(length_diff) * self.prop_delay

            if skew_contribution > group.max_skew_ps / 2:
                # This signal is a significant contributor to skew
                issues.append(LengthMatchIssue(
                    severity="high" if skew_contribution > group.max_skew_ps else "medium",
                    description=f"{signal.signal_name} contributes {skew_contribution:.1f}ps to group skew",
                    group_name=group.group_name,
                    signal_name=signal.signal_name,
                    current_length_mm=signal.length_mm,
                    target_length_mm=target,
                    adjustment_mm=-length_diff,  # Negative means add length, positive means remove
                    recommendation=f"Adjust {signal.signal_name} by {-length_diff:+.2f}mm",
                ))

        # Check overall group compliance
        if not group.within_spec:
            issues.append(LengthMatchIssue(
                severity="high",
                description=f"Group {group.group_name} skew {group.skew_ps:.1f}ps exceeds {group.max_skew_ps}ps",
                group_name=group.group_name,
                recommendation=f"Reduce length spread from {group.length_spread_mm:.2f}mm",
            ))

        return group, issues

    def analyze(
        self,
        groups: list[MatchingGroup],
        match_groups_to_each_other: bool = False,
        inter_group_max_skew_ps: float = 100.0,
    ) -> LengthMatchResult:
        """
        Analyze multiple matching groups.

        Args:
            groups: List of MatchingGroup objects
            match_groups_to_each_other: Whether groups should also be matched
            inter_group_max_skew_ps: Max skew between groups

        Returns:
            LengthMatchResult with full analysis
        """
        all_issues = []
        analyzed_groups = []

        # Analyze each group
        for group in groups:
            analyzed_group, issues = self.analyze_group(group)
            analyzed_groups.append(analyzed_group)
            all_issues.extend(issues)

        # Calculate inter-group skew if requested
        inter_group_skew = 0.0
        if match_groups_to_each_other and len(analyzed_groups) > 1:
            avg_lengths = [g.avg_length for g in analyzed_groups]
            length_spread = max(avg_lengths) - min(avg_lengths)
            inter_group_skew = length_spread * self.prop_delay

            if inter_group_skew > inter_group_max_skew_ps:
                # Find which groups need adjustment
                min_avg = min(avg_lengths)
                max_avg = max(avg_lengths)
                short_group = next(g for g in analyzed_groups if g.avg_length == min_avg)
                long_group = next(g for g in analyzed_groups if g.avg_length == max_avg)

                all_issues.append(LengthMatchIssue(
                    severity="high",
                    description=f"Inter-group skew {inter_group_skew:.0f}ps exceeds {inter_group_max_skew_ps}ps",
                    group_name=f"{short_group.group_name} vs {long_group.group_name}",
                    recommendation=f"Match {short_group.group_name} and {long_group.group_name} average lengths",
                ))

        # Determine overall compliance
        all_matched = all(g.within_spec for g in analyzed_groups)
        if match_groups_to_each_other:
            all_matched = all_matched and inter_group_skew <= inter_group_max_skew_ps

        score = self._calculate_score(all_issues, analyzed_groups)

        return LengthMatchResult(
            groups=analyzed_groups,
            inter_group_skew_ps=inter_group_skew,
            issues=all_issues,
            all_matched=all_matched,
            score=score,
        )

    def create_matching_report(
        self,
        result: LengthMatchResult,
    ) -> str:
        """
        Create a human-readable matching report.

        Args:
            result: LengthMatchResult to report on

        Returns:
            Formatted string report
        """
        lines = ["=" * 60, "Length Matching Report", "=" * 60, ""]

        for group in result.groups:
            status = "✓ PASS" if group.within_spec else "✗ FAIL"
            lines.append(f"Group: {group.group_name} [{status}]")
            lines.append(f"  Signals: {len(group.signals)}")
            lines.append(f"  Length range: {group.min_length:.2f} - {group.max_length:.2f} mm")
            lines.append(f"  Spread: {group.length_spread_mm:.2f} mm ({group.skew_ps:.1f} ps)")
            lines.append(f"  Limit: {group.max_skew_ps:.0f} ps")
            lines.append("")

            # List signals that need adjustment
            target = group.target_length_mm or group.avg_length
            for signal in sorted(group.signals, key=lambda s: abs(s.length_mm - target), reverse=True):
                diff = signal.length_mm - target
                if abs(diff) > 0.01:  # Only show significant differences
                    lines.append(f"    {signal.signal_name}: {signal.length_mm:.2f} mm ({diff:+.2f} mm)")

            lines.append("")

        if result.inter_group_skew_ps > 0:
            lines.append(f"Inter-group skew: {result.inter_group_skew_ps:.1f} ps")
            lines.append("")

        lines.append(f"Overall: {'PASS' if result.all_matched else 'FAIL'}")
        lines.append(f"Score: {result.score:.0f}/100")

        return "\n".join(lines)

    def _calculate_score(
        self,
        issues: list[LengthMatchIssue],
        groups: list[MatchingGroup],
    ) -> float:
        """Calculate length matching score."""
        score = 100.0

        # Deduct for issues
        for issue in issues:
            if issue.severity == "critical":
                score -= 20
            elif issue.severity == "high":
                score -= 10
            elif issue.severity == "medium":
                score -= 5
            else:
                score -= 2

        # Bonus for all groups matched
        if all(g.within_spec for g in groups):
            score = min(100, score + 10)

        return max(0.0, score)

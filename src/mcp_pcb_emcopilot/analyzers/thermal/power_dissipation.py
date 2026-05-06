"""
Power Dissipation Analyzer.

Maps power dissipation across the PCB and identifies
components with high thermal loads.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ComponentPower:
    """Power dissipation data for a component."""
    component_ref: str
    component_type: str  # IC, regulator, resistor, etc.
    package: str
    position: tuple[float, float]
    power_dissipation_w: float
    thermal_resistance_jc: float  # °C/W junction to case
    thermal_resistance_ja: Optional[float] = None  # °C/W junction to ambient
    has_heatsink: bool = False
    has_thermal_vias: bool = False
    estimated_temp_rise_c: float = 0.0

    def to_dict(self) -> dict:
        return {
            "component_ref": self.component_ref,
            "component_type": self.component_type,
            "package": self.package,
            "position": self.position,
            "power_dissipation_w": round(self.power_dissipation_w, 3),
            "thermal_resistance_jc": round(self.thermal_resistance_jc, 1),
            "thermal_resistance_ja": round(self.thermal_resistance_ja, 1) if self.thermal_resistance_ja else None,
            "has_heatsink": self.has_heatsink,
            "has_thermal_vias": self.has_thermal_vias,
            "estimated_temp_rise_c": round(self.estimated_temp_rise_c, 1),
        }


@dataclass
class PowerDissipationIssue:
    """A power dissipation issue."""
    severity: str
    description: str
    component_ref: str
    power_w: float
    temp_rise_c: float
    recommendation: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "description": self.description,
            "component_ref": self.component_ref,
            "power_w": round(self.power_w, 3),
            "temp_rise_c": round(self.temp_rise_c, 1),
            "recommendation": self.recommendation,
        }


@dataclass
class PowerDissipationResult:
    """Result of power dissipation analysis."""
    total_power_w: float = 0.0
    components: list[ComponentPower] = field(default_factory=list)

    # High power components (>0.5W)
    high_power_components: list[str] = field(default_factory=list)

    # Thermal map data
    power_density_map: Optional[list[list[float]]] = None
    peak_power_density_w_per_cm2: float = 0.0
    peak_location: tuple[float, float] = (0.0, 0.0)

    # Issues
    issues: list[PowerDissipationIssue] = field(default_factory=list)
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "total_power_w": round(self.total_power_w, 2),
            "components": [c.to_dict() for c in self.components],
            "high_power_components": self.high_power_components,
            "peak_power_density_w_per_cm2": round(self.peak_power_density_w_per_cm2, 2),
            "peak_location": self.peak_location,
            "issues": [i.to_dict() for i in self.issues],
            "score": round(self.score, 1),
        }


# Typical thermal resistance values (°C/W) for common packages
PACKAGE_THERMAL_RESISTANCE: dict[str, dict[str, float]] = {
    # Small packages
    "0201": {"jc": 200, "ja": 400},
    "0402": {"jc": 150, "ja": 300},
    "0603": {"jc": 100, "ja": 200},
    "0805": {"jc": 80, "ja": 150},
    "1206": {"jc": 60, "ja": 120},
    # Larger resistors
    "2010": {"jc": 40, "ja": 80},
    "2512": {"jc": 30, "ja": 60},
    # SOT packages
    "SOT23": {"jc": 100, "ja": 200},
    "SOT223": {"jc": 40, "ja": 80},
    "SOT89": {"jc": 50, "ja": 100},
    # QFN/QFP
    "QFN16": {"jc": 15, "ja": 50},
    "QFN24": {"jc": 12, "ja": 45},
    "QFN32": {"jc": 10, "ja": 40},
    "QFN48": {"jc": 8, "ja": 35},
    "QFP44": {"jc": 15, "ja": 60},
    "QFP64": {"jc": 12, "ja": 50},
    "QFP100": {"jc": 10, "ja": 45},
    # BGA
    "BGA64": {"jc": 8, "ja": 35},
    "BGA100": {"jc": 6, "ja": 30},
    "BGA256": {"jc": 4, "ja": 25},
    "BGA484": {"jc": 3, "ja": 20},
    "BGA676": {"jc": 2, "ja": 18},
    # Power packages
    "TO220": {"jc": 2, "ja": 50},
    "TO263": {"jc": 3, "ja": 40},
    "DPAK": {"jc": 3, "ja": 50},
    "D2PAK": {"jc": 1.5, "ja": 30},
}


class PowerDissipationAnalyzer:
    """
    Analyzes power dissipation across PCB components.

    Estimates temperature rise and identifies potential
    thermal issues.

    Usage:
        analyzer = PowerDissipationAnalyzer()
        result = analyzer.analyze(
            components=[
                {
                    "ref": "U1",
                    "type": "processor",
                    "package": "BGA256",
                    "position": (50, 40),
                    "power_w": 5.0,
                },
                {
                    "ref": "U2",
                    "type": "regulator",
                    "package": "SOT223",
                    "position": (30, 30),
                    "power_w": 0.8,
                },
            ],
            ambient_temp_c=25.0,
            max_junction_temp_c=85.0,
        )
    """

    def __init__(
        self,
        high_power_threshold_w: float = 0.5,
        critical_temp_rise_c: float = 50.0,
        warning_temp_rise_c: float = 30.0,
    ):
        """
        Initialize analyzer.

        Args:
            high_power_threshold_w: Threshold for high-power component
            critical_temp_rise_c: Critical temperature rise threshold
            warning_temp_rise_c: Warning temperature rise threshold
        """
        self.high_power_threshold = high_power_threshold_w
        self.critical_temp = critical_temp_rise_c
        self.warning_temp = warning_temp_rise_c

    def get_thermal_resistance(
        self,
        package: str,
    ) -> tuple[float, float]:
        """
        Get thermal resistance values for a package.

        Returns (θjc, θja) in °C/W.
        """
        # Normalize package name
        pkg = package.upper().replace("-", "").replace("_", "")

        # Try exact match
        if pkg in PACKAGE_THERMAL_RESISTANCE:
            data = PACKAGE_THERMAL_RESISTANCE[pkg]
            return data["jc"], data["ja"]

        # Try partial match
        for key in PACKAGE_THERMAL_RESISTANCE:
            if key in pkg or pkg in key:
                data = PACKAGE_THERMAL_RESISTANCE[key]
                return data["jc"], data["ja"]

        # Default values
        return 20.0, 60.0

    def estimate_temp_rise(
        self,
        power_w: float,
        theta_ja: float,
        has_heatsink: bool = False,
        heatsink_theta: float = 10.0,
    ) -> float:
        """
        Estimate junction temperature rise.

        Args:
            power_w: Power dissipation in Watts
            theta_ja: Junction-to-ambient thermal resistance
            has_heatsink: Whether a heatsink is attached
            heatsink_theta: Heatsink thermal resistance

        Returns:
            Temperature rise in °C
        """
        if has_heatsink:
            # Heatsink reduces effective thermal resistance
            effective_theta = theta_ja * heatsink_theta / (theta_ja + heatsink_theta)
        else:
            effective_theta = theta_ja

        return power_w * effective_theta

    def analyze(
        self,
        components: list[dict],
        ambient_temp_c: float = 25.0,
        max_junction_temp_c: float = 85.0,
        board_area_cm2: Optional[float] = None,
    ) -> PowerDissipationResult:
        """
        Analyze power dissipation.

        Args:
            components: List of component data
            ambient_temp_c: Ambient temperature
            max_junction_temp_c: Maximum allowed junction temperature
            board_area_cm2: Board area for density calculation

        Returns:
            PowerDissipationResult with analysis
        """
        analyzed: list[ComponentPower] = []
        issues = []
        total_power = 0.0
        high_power = []

        for comp in components:
            ref = comp.get("ref", "?")
            power = comp.get("power_w", 0.0)
            package = comp.get("package", "QFN32")
            position = comp.get("position", (0, 0))
            has_heatsink = comp.get("has_heatsink", False)
            has_thermal_vias = comp.get("has_thermal_vias", False)

            # Get thermal resistance
            theta_jc, theta_ja = self.get_thermal_resistance(package)

            # Adjust for thermal vias (reduces θja by ~20-40%)
            if has_thermal_vias:
                theta_ja *= 0.7

            # Estimate temperature rise
            temp_rise = self.estimate_temp_rise(power, theta_ja, has_heatsink)

            component = ComponentPower(
                component_ref=ref,
                component_type=comp.get("type", "unknown"),
                package=package,
                position=position,
                power_dissipation_w=power,
                thermal_resistance_jc=theta_jc,
                thermal_resistance_ja=theta_ja,
                has_heatsink=has_heatsink,
                has_thermal_vias=has_thermal_vias,
                estimated_temp_rise_c=temp_rise,
            )
            analyzed.append(component)
            total_power += power

            # Check for high power
            if power >= self.high_power_threshold:
                high_power.append(ref)

            # Check for thermal issues
            max_allowed_rise = max_junction_temp_c - ambient_temp_c
            if temp_rise > max_allowed_rise:
                issues.append(PowerDissipationIssue(
                    severity="critical",
                    description=f"{ref} may exceed Tj_max ({ambient_temp_c + temp_rise:.0f}°C > {max_junction_temp_c}°C)",
                    component_ref=ref,
                    power_w=power,
                    temp_rise_c=temp_rise,
                    recommendation="Add heatsink, thermal vias, or improve airflow",
                ))
            elif temp_rise > self.critical_temp:
                issues.append(PowerDissipationIssue(
                    severity="high",
                    description=f"{ref} has high temperature rise ({temp_rise:.0f}°C)",
                    component_ref=ref,
                    power_w=power,
                    temp_rise_c=temp_rise,
                    recommendation="Consider thermal vias or improved copper spreading",
                ))
            elif temp_rise > self.warning_temp:
                issues.append(PowerDissipationIssue(
                    severity="medium",
                    description=f"{ref} has moderate temperature rise ({temp_rise:.0f}°C)",
                    component_ref=ref,
                    power_w=power,
                    temp_rise_c=temp_rise,
                    recommendation="Monitor thermal performance",
                ))

        # Calculate power density
        peak_density = 0.0
        peak_loc = (0.0, 0.0)
        if board_area_cm2 and board_area_cm2 > 0:
            # Simple estimate: highest power component density
            for cp in analyzed:
                # Assume component area based on package (rough estimate)
                comp_area_cm2 = 0.5  # Default
                density = cp.power_dissipation_w / comp_area_cm2
                if density > peak_density:
                    peak_density = density
                    peak_loc = cp.position

        score = self._calculate_score(issues, total_power, analyzed)

        return PowerDissipationResult(
            total_power_w=total_power,
            components=analyzed,
            high_power_components=high_power,
            peak_power_density_w_per_cm2=peak_density,
            peak_location=peak_loc,
            issues=issues,
            score=score,
        )

    def _calculate_score(
        self,
        issues: list[PowerDissipationIssue],
        total_power: float,
        components: list[ComponentPower],
    ) -> float:
        """Calculate thermal score."""
        score = 100.0

        for issue in issues:
            if issue.severity == "critical":
                score -= 25
            elif issue.severity == "high":
                score -= 15
            elif issue.severity == "medium":
                score -= 8
            else:
                score -= 3

        # Bonus for thermal vias on high-power components
        high_power_with_vias = sum(
            1 for c in components
            if c.power_dissipation_w >= self.high_power_threshold and c.has_thermal_vias
        )
        score = min(100, score + high_power_with_vias * 3)

        return max(0.0, score)

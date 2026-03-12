"""
VRM (Voltage Regulator Module) Analyzer.

Analyzes VRM placement and routing for power integrity:
- VRM to load proximity
- Output capacitor placement
- Feedback loop routing
- Current carrying capability
- Thermal considerations
"""
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class VRMIssueType(str, Enum):
    """Types of VRM issues."""
    VRM_TOO_FAR = "vrm_too_far"
    OUTPUT_CAP_PLACEMENT = "output_cap_placement"
    FEEDBACK_ROUTING = "feedback_routing"
    TRACE_WIDTH_INSUFFICIENT = "trace_width_insufficient"
    THERMAL_PAD_MISSING = "thermal_pad_missing"
    INPUT_CAP_MISSING = "input_cap_missing"
    INDUCTOR_PLACEMENT = "inductor_placement"
    GROUND_RETURN = "ground_return"


@dataclass
class VRMIssue:
    """A VRM-related issue."""
    issue_type: VRMIssueType
    severity: str
    description: str
    component_ref: Optional[str] = None
    recommendation: Optional[str] = None
    location: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "issue_type": self.issue_type.value,
            "severity": self.severity,
            "description": self.description,
            "component_ref": self.component_ref,
            "recommendation": self.recommendation,
            "location": self.location,
        }


@dataclass
class VRMComponent:
    """VRM component analysis."""
    component_ref: str
    component_type: str  # vrm, inductor, output_cap, input_cap, feedback_resistor
    position: tuple[float, float]
    value: Optional[str] = None
    issues: list[VRMIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "component_ref": self.component_ref,
            "component_type": self.component_type,
            "position": self.position,
            "value": self.value,
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass
class VRMResult:
    """Result of VRM analysis."""
    vrm_ref: str
    output_rail: str
    output_voltage: float
    output_current_max: float

    # Component analysis
    components: list[VRMComponent] = field(default_factory=list)

    # Routing analysis
    output_trace_width_mm: float = 0.0
    required_trace_width_mm: float = 0.0
    trace_width_adequate: bool = True

    # Loop analysis
    power_loop_area_mm2: float = 0.0
    power_loop_inductance_nh: float = 0.0
    feedback_loop_length_mm: float = 0.0

    # Thermal analysis
    has_thermal_vias: bool = False
    estimated_power_dissipation_w: float = 0.0

    # Issues and score
    issues: list[VRMIssue] = field(default_factory=list)
    score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "vrm_ref": self.vrm_ref,
            "output_rail": self.output_rail,
            "output_voltage": self.output_voltage,
            "output_current_max": self.output_current_max,
            "components": [c.to_dict() for c in self.components],
            "output_trace_width_mm": round(self.output_trace_width_mm, 3),
            "required_trace_width_mm": round(self.required_trace_width_mm, 3),
            "trace_width_adequate": self.trace_width_adequate,
            "power_loop_area_mm2": round(self.power_loop_area_mm2, 2),
            "power_loop_inductance_nh": round(self.power_loop_inductance_nh, 2),
            "feedback_loop_length_mm": round(self.feedback_loop_length_mm, 2),
            "has_thermal_vias": self.has_thermal_vias,
            "estimated_power_dissipation_w": round(self.estimated_power_dissipation_w, 3),
            "issues": [i.to_dict() for i in self.issues],
            "score": round(self.score, 1),
        }


# Current capacity for 1oz copper at various temperatures (A/mm width)
CURRENT_CAPACITY = {
    "10C_rise": 0.4,  # A per mm width for 1oz copper
    "20C_rise": 0.6,
    "30C_rise": 0.8,
}


class VRMAnalyzer:
    """
    VRM placement and routing analyzer.

    Analyzes switching regulator layout for:
    - Component placement optimization
    - Current loop minimization
    - Trace width adequacy
    - Thermal management

    Usage:
        analyzer = VRMAnalyzer()
        result = analyzer.analyze_vrm(
            vrm_ref="U5",
            vrm_position=(30.0, 40.0),
            output_rail="VCC_1V8",
            output_voltage=1.8,
            output_current=3.0,
            input_voltage=5.0,
            components=[
                {"ref": "L1", "type": "inductor", "position": (32.0, 40.0)},
                {"ref": "C10", "type": "output_cap", "position": (35.0, 40.0)},
                {"ref": "C9", "type": "input_cap", "position": (28.0, 40.0)},
            ],
            load_positions=[(50.0, 50.0), (60.0, 45.0)],
        )
    """

    def __init__(
        self,
        max_vrm_to_load_mm: float = 50.0,
        max_feedback_length_mm: float = 20.0,
        temp_rise_target: str = "20C_rise",
    ):
        """
        Initialize analyzer.

        Args:
            max_vrm_to_load_mm: Maximum acceptable VRM to load distance
            max_feedback_length_mm: Maximum feedback loop length
            temp_rise_target: Temperature rise target for trace sizing
        """
        self.max_vrm_to_load = max_vrm_to_load_mm
        self.max_feedback_length = max_feedback_length_mm
        self.current_capacity = CURRENT_CAPACITY.get(temp_rise_target, 0.6)

    def calculate_required_trace_width(
        self,
        current_a: float,
        copper_weight_oz: float = 1.0,
        temp_rise: str = "20C_rise",
    ) -> float:
        """
        Calculate required trace width for current.

        Args:
            current_a: Current in Amps
            copper_weight_oz: Copper weight (1oz = 35µm)
            temp_rise: Acceptable temperature rise

        Returns:
            Required width in mm
        """
        capacity = CURRENT_CAPACITY.get(temp_rise, 0.6) * copper_weight_oz
        return current_a / capacity

    def calculate_loop_inductance(
        self,
        loop_area_mm2: float,
        trace_width_mm: float = 0.5,
    ) -> float:
        """
        Estimate loop inductance from area.

        L ≈ µ0 * Area / width (rough approximation)

        Args:
            loop_area_mm2: Loop area in mm²
            trace_width_mm: Average trace width

        Returns:
            Inductance in nH
        """
        mu0 = 4 * math.pi * 1e-7  # H/m
        area_m2 = loop_area_mm2 * 1e-6
        width_m = trace_width_mm * 1e-3

        inductance_h = mu0 * area_m2 / width_m
        return inductance_h * 1e9  # Convert to nH

    def estimate_power_dissipation(
        self,
        input_voltage: float,
        output_voltage: float,
        output_current: float,
        efficiency: float = 0.85,
    ) -> float:
        """
        Estimate VRM power dissipation.

        Args:
            input_voltage: Input voltage
            output_voltage: Output voltage
            output_current: Output current
            efficiency: Assumed efficiency

        Returns:
            Power dissipation in Watts
        """
        output_power = output_voltage * output_current
        input_power = output_power / efficiency
        return input_power - output_power

    def analyze_vrm(
        self,
        vrm_ref: str,
        vrm_position: tuple[float, float],
        output_rail: str,
        output_voltage: float,
        output_current: float,
        input_voltage: float,
        components: list[dict],
        load_positions: Optional[list[tuple[float, float]]] = None,
        output_trace_width_mm: float = 0.5,
        has_thermal_vias: bool = False,
        feedback_resistor_position: Optional[tuple[float, float]] = None,
    ) -> VRMResult:
        """
        Analyze VRM layout.

        Args:
            vrm_ref: VRM reference designator
            vrm_position: VRM position (x, y) in mm
            output_rail: Output rail name
            output_voltage: Output voltage
            output_current: Maximum output current
            input_voltage: Input voltage
            components: List of related components
            load_positions: Positions of major loads
            output_trace_width_mm: Output trace width
            has_thermal_vias: Whether VRM has thermal vias
            feedback_resistor_position: Position of feedback resistor

        Returns:
            VRMResult with analysis
        """
        issues = []
        analyzed_components = []

        # Analyze each component
        inductor_pos = None
        output_cap_pos = None
        input_cap_pos = None

        for comp in components:
            comp_type = comp.get("type", "unknown")
            comp_ref = comp.get("ref", "?")
            comp_pos = comp.get("position", (0, 0))

            comp_issues = []

            if comp_type == "inductor":
                inductor_pos = comp_pos
                # Check inductor proximity to VRM
                dist = self._distance(vrm_position, comp_pos)
                if dist > 5.0:
                    comp_issues.append(VRMIssue(
                        issue_type=VRMIssueType.INDUCTOR_PLACEMENT,
                        severity="high",
                        description=f"Inductor {comp_ref} is {dist:.1f}mm from VRM, should be <5mm",
                        component_ref=comp_ref,
                        recommendation="Place inductor adjacent to VRM switch node",
                    ))

            elif comp_type == "output_cap":
                output_cap_pos = comp_pos
                # Check output cap proximity to load
                if load_positions:
                    min_load_dist = min(self._distance(comp_pos, lp) for lp in load_positions)
                    if min_load_dist > 20.0:
                        comp_issues.append(VRMIssue(
                            issue_type=VRMIssueType.OUTPUT_CAP_PLACEMENT,
                            severity="medium",
                            description=f"Output cap {comp_ref} is {min_load_dist:.1f}mm from nearest load",
                            component_ref=comp_ref,
                            recommendation="Add bulk capacitor closer to major loads",
                        ))

            elif comp_type == "input_cap":
                input_cap_pos = comp_pos
                # Check input cap proximity to VRM
                dist = self._distance(vrm_position, comp_pos)
                if dist > 3.0:
                    comp_issues.append(VRMIssue(
                        issue_type=VRMIssueType.INPUT_CAP_MISSING,
                        severity="high",
                        description=f"Input cap {comp_ref} is {dist:.1f}mm from VRM VIN pin",
                        component_ref=comp_ref,
                        recommendation="Move input capacitor adjacent to VRM input",
                    ))

            analyzed_components.append(VRMComponent(
                component_ref=comp_ref,
                component_type=comp_type,
                position=comp_pos,
                value=comp.get("value"),
                issues=comp_issues,
            ))
            issues.extend(comp_issues)

        # Check VRM to load distance
        if load_positions:
            avg_load_dist = sum(self._distance(vrm_position, lp) for lp in load_positions) / len(load_positions)
            if avg_load_dist > self.max_vrm_to_load:
                issues.append(VRMIssue(
                    issue_type=VRMIssueType.VRM_TOO_FAR,
                    severity="medium",
                    description=f"VRM is {avg_load_dist:.1f}mm average from loads",
                    component_ref=vrm_ref,
                    recommendation="Consider relocating VRM closer to major loads or adding remote sensing",
                ))

        # Calculate required trace width
        required_width = self.calculate_required_trace_width(output_current)
        trace_adequate = output_trace_width_mm >= required_width

        if not trace_adequate:
            issues.append(VRMIssue(
                issue_type=VRMIssueType.TRACE_WIDTH_INSUFFICIENT,
                severity="high",
                description=f"Output trace {output_trace_width_mm:.2f}mm too narrow for {output_current}A (need {required_width:.2f}mm)",
                component_ref=vrm_ref,
                recommendation=f"Increase output trace width to at least {required_width:.2f}mm or use copper pour",
            ))

        # Check thermal vias
        power_dissipation = self.estimate_power_dissipation(
            input_voltage, output_voltage, output_current
        )
        if power_dissipation > 0.5 and not has_thermal_vias:
            issues.append(VRMIssue(
                issue_type=VRMIssueType.THERMAL_PAD_MISSING,
                severity="medium",
                description=f"VRM dissipates ~{power_dissipation:.2f}W but no thermal vias detected",
                component_ref=vrm_ref,
                recommendation="Add thermal vias under exposed pad to inner ground plane",
            ))

        # Estimate power loop area and inductance
        loop_area = 0.0
        if inductor_pos and input_cap_pos:
            # Rough estimate: triangle formed by VRM, inductor, input cap
            loop_area = self._triangle_area(vrm_position, inductor_pos, input_cap_pos)

        loop_inductance = self.calculate_loop_inductance(loop_area)

        if loop_area > 50:
            issues.append(VRMIssue(
                issue_type=VRMIssueType.GROUND_RETURN,
                severity="high",
                description=f"Power loop area ~{loop_area:.1f}mm² is large (>50mm²)",
                component_ref=vrm_ref,
                recommendation="Minimize hot loop by placing input cap adjacent to VRM",
            ))

        # Analyze feedback loop
        feedback_length = 0.0
        if feedback_resistor_position:
            feedback_length = self._distance(vrm_position, feedback_resistor_position)
            if feedback_length > self.max_feedback_length:
                issues.append(VRMIssue(
                    issue_type=VRMIssueType.FEEDBACK_ROUTING,
                    severity="medium",
                    description=f"Feedback path {feedback_length:.1f}mm is long (>{self.max_feedback_length}mm)",
                    component_ref=vrm_ref,
                    recommendation="Route feedback trace away from switching node, keep short",
                ))

        # Check for missing components
        if not input_cap_pos:
            issues.append(VRMIssue(
                issue_type=VRMIssueType.INPUT_CAP_MISSING,
                severity="critical",
                description="No input capacitor identified near VRM",
                component_ref=vrm_ref,
                recommendation="Add ceramic input capacitor adjacent to VRM VIN pin",
            ))

        # Calculate score
        score = self._calculate_score(issues, trace_adequate, loop_area)

        return VRMResult(
            vrm_ref=vrm_ref,
            output_rail=output_rail,
            output_voltage=output_voltage,
            output_current_max=output_current,
            components=analyzed_components,
            output_trace_width_mm=output_trace_width_mm,
            required_trace_width_mm=required_width,
            trace_width_adequate=trace_adequate,
            power_loop_area_mm2=loop_area,
            power_loop_inductance_nh=loop_inductance,
            feedback_loop_length_mm=feedback_length,
            has_thermal_vias=has_thermal_vias,
            estimated_power_dissipation_w=power_dissipation,
            issues=issues,
            score=score,
        )

    def _distance(self, p1: tuple[float, float], p2: tuple[float, float]) -> float:
        """Calculate Euclidean distance between two points."""
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    def _triangle_area(
        self,
        p1: tuple[float, float],
        p2: tuple[float, float],
        p3: tuple[float, float],
    ) -> float:
        """Calculate area of triangle formed by three points."""
        # Shoelace formula
        return abs(
            (p1[0] * (p2[1] - p3[1]) +
             p2[0] * (p3[1] - p1[1]) +
             p3[0] * (p1[1] - p2[1])) / 2
        )

    def _calculate_score(
        self,
        issues: list[VRMIssue],
        trace_adequate: bool,
        loop_area: float,
    ) -> float:
        """Calculate VRM layout quality score."""
        score = 100.0

        # Deduct for issues
        for issue in issues:
            if issue.severity == "critical":
                score -= 25
            elif issue.severity == "high":
                score -= 15
            elif issue.severity == "medium":
                score -= 8
            else:
                score -= 3

        # Bonus for good practices
        if trace_adequate:
            score = min(100, score + 5)
        if loop_area < 25:
            score = min(100, score + 5)

        return max(0.0, score)

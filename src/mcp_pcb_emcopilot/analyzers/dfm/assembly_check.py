"""Assembly check analyzer for DFM"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ManufacturingCapability(Enum):
    """Manufacturing capability levels."""
    STANDARD = "standard"       # Standard SMT assembly
    FINE_PITCH = "fine_pitch"   # Fine-pitch capability
    HDI = "hdi"                 # HDI/advanced assembly
    ADVANCED = "advanced"       # State-of-the-art capability


@dataclass
class ManufacturingProfile:
    """Manufacturing capability profile with thresholds.

    All thresholds are data-driven based on industry standards:
    - IPC-A-610 Class 2/3 acceptance criteria
    - IPC-7525B stencil design guidelines
    - Modern assembly equipment capabilities
    """
    name: str
    capability: ManufacturingCapability

    # Minimum pitch capability (mm) - below this is high risk
    min_pitch_mm: float
    # Pitch thresholds for bridging risk: (high_risk, medium_risk, low_risk)
    bridging_pitch_thresholds: Tuple[float, float, float]

    # Tombstone-prone packages (smallest size handled reliably)
    min_reliable_package: str  # Smallest package size handled reliably
    tombstone_prone_packages: List[str]

    # Thermal relief requirements
    thermal_relief_required_below_pitch_mm: float
    thermal_relief_spoke_width_mm: float
    thermal_relief_gap_mm: float

    # BGA coplanarity limits (mm)
    bga_coplanarity_spec_mm: float

    # Stencil aperture reduction for fine pitch (percent)
    stencil_reduction_percent: float

    # Wave solder SMT limits
    wave_max_height_mm: float
    wave_max_pins: int

    # Minimum component-to-component spacing (mm)
    min_spacing_mm: float


# Pre-defined manufacturing profiles based on industry data
MANUFACTURING_PROFILES: Dict[ManufacturingCapability, ManufacturingProfile] = {
    ManufacturingCapability.STANDARD: ManufacturingProfile(
        name="Standard SMT Assembly",
        capability=ManufacturingCapability.STANDARD,
        min_pitch_mm=0.5,
        bridging_pitch_thresholds=(0.5, 0.65, 0.8),  # High, Medium, Low risk
        min_reliable_package="0402",
        tombstone_prone_packages=["01005", "0201", "0402"],
        thermal_relief_required_below_pitch_mm=0.65,
        thermal_relief_spoke_width_mm=0.25,
        thermal_relief_gap_mm=0.25,
        bga_coplanarity_spec_mm=0.15,
        stencil_reduction_percent=10,
        wave_max_height_mm=2.0,
        wave_max_pins=4,
        min_spacing_mm=0.2,
    ),
    ManufacturingCapability.FINE_PITCH: ManufacturingProfile(
        name="Fine-Pitch Assembly",
        capability=ManufacturingCapability.FINE_PITCH,
        min_pitch_mm=0.4,
        bridging_pitch_thresholds=(0.4, 0.5, 0.65),  # High, Medium, Low risk
        min_reliable_package="0201",
        tombstone_prone_packages=["01005", "0201"],
        thermal_relief_required_below_pitch_mm=0.5,
        thermal_relief_spoke_width_mm=0.2,
        thermal_relief_gap_mm=0.2,
        bga_coplanarity_spec_mm=0.10,
        stencil_reduction_percent=15,
        wave_max_height_mm=1.5,
        wave_max_pins=2,
        min_spacing_mm=0.15,
    ),
    ManufacturingCapability.HDI: ManufacturingProfile(
        name="HDI Assembly",
        capability=ManufacturingCapability.HDI,
        min_pitch_mm=0.3,
        bridging_pitch_thresholds=(0.3, 0.4, 0.5),  # High, Medium, Low risk
        min_reliable_package="0201",
        tombstone_prone_packages=["01005"],
        thermal_relief_required_below_pitch_mm=0.4,
        thermal_relief_spoke_width_mm=0.15,
        thermal_relief_gap_mm=0.15,
        bga_coplanarity_spec_mm=0.08,
        stencil_reduction_percent=20,
        wave_max_height_mm=1.0,
        wave_max_pins=2,
        min_spacing_mm=0.1,
    ),
    ManufacturingCapability.ADVANCED: ManufacturingProfile(
        name="Advanced/State-of-the-Art Assembly",
        capability=ManufacturingCapability.ADVANCED,
        min_pitch_mm=0.2,
        bridging_pitch_thresholds=(0.2, 0.3, 0.4),  # High, Medium, Low risk
        min_reliable_package="01005",
        tombstone_prone_packages=[],  # Advanced can handle all packages
        thermal_relief_required_below_pitch_mm=0.3,
        thermal_relief_spoke_width_mm=0.1,
        thermal_relief_gap_mm=0.1,
        bga_coplanarity_spec_mm=0.05,
        stencil_reduction_percent=25,
        wave_max_height_mm=0.8,
        wave_max_pins=2,
        min_spacing_mm=0.08,
    ),
}


@dataclass
class AssemblyResult:
    """Results from assembly analysis"""
    # Board summary
    board_id: str
    assembly_process: str  # reflow, wave, mixed, manual

    # Risk counts
    tombstone_risk_count: int
    bridging_risk_count: int
    shadowing_risk_count: int
    coplanarity_risk_count: int

    # Process compatibility
    reflow_compatible: bool
    wave_compatible: bool
    rework_accessible: bool

    # Assessment
    dfm_score: float  # 0-100
    risk_level: str  # low, medium, high, critical

    # Detailed risks
    risks: List[Dict[str, Any]] = field(default_factory=list)

    # Issues and recommendations
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    # Details
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AssemblyComponent:
    """Component for assembly analysis"""
    reference: str
    package: str
    x_mm: float
    y_mm: float
    rotation_deg: float
    side: str

    # Pad characteristics
    pad_width_mm: float
    pad_length_mm: float
    pin_count: int
    pitch_mm: float = 0

    # Thermal characteristics
    thermal_mass: str = "low"  # low, medium, high
    connected_to_plane: bool = False

    # Component specifics
    component_type: str = "smd"  # smd, pth, bga
    height_mm: float = 1.0


class AssemblyAnalyzer:
    """
    Assembly check analyzer for DFM.

    Analyzes:
    - Tombstoning risk for chip components
    - Solder bridging risk for fine-pitch
    - Shadowing during reflow
    - Coplanarity issues for BGAs
    - Rework accessibility

    Based on IPC-A-610 and assembly process requirements.
    Supports configurable manufacturing profiles for data-driven thresholds.
    """

    # Legacy hardcoded values (deprecated - use profiles instead)
    TOMBSTONE_PRONE = ["01005", "0201", "0402", "0603"]
    BRIDGING_RISK = {0.3: "high", 0.4: "medium", 0.5: "low"}

    def __init__(
        self,
        capability: ManufacturingCapability = ManufacturingCapability.STANDARD,
        custom_profile: Optional[ManufacturingProfile] = None,
    ):
        """Initialize analyzer with manufacturing capability.

        Args:
            capability: Manufacturing capability level to use
            custom_profile: Optional custom profile to override defaults
        """
        if custom_profile:
            self.profile = custom_profile
        else:
            self.profile = MANUFACTURING_PROFILES[capability]

    @classmethod
    def for_standard_smt(cls) -> AssemblyAnalyzer:
        """Create analyzer for standard SMT assembly."""
        return cls(capability=ManufacturingCapability.STANDARD)

    @classmethod
    def for_fine_pitch(cls) -> AssemblyAnalyzer:
        """Create analyzer for fine-pitch assembly."""
        return cls(capability=ManufacturingCapability.FINE_PITCH)

    @classmethod
    def for_hdi(cls) -> AssemblyAnalyzer:
        """Create analyzer for HDI assembly."""
        return cls(capability=ManufacturingCapability.HDI)

    @classmethod
    def for_advanced(cls) -> AssemblyAnalyzer:
        """Create analyzer for advanced/state-of-the-art assembly."""
        return cls(capability=ManufacturingCapability.ADVANCED)

    def analyze_assembly(
        self,
        components: List[AssemblyComponent],
        board_id: str = "PCB1",
        assembly_process: str = "reflow",
    ) -> AssemblyResult:
        """
        Analyze assembly risks.

        Args:
            components: List of components
            board_id: Board identifier
            assembly_process: Assembly process type

        Returns:
            AssemblyResult with complete analysis
        """
        risks = []

        # Analyze each component
        for c in components:
            component_risks = self._analyze_component(c, assembly_process)
            risks.extend(component_risks)

        # Count by risk type
        tombstone_count = sum(1 for r in risks if r["risk_type"] == "tombstone")
        bridging_count = sum(1 for r in risks if r["risk_type"] == "bridging")
        shadowing_count = sum(1 for r in risks if r["risk_type"] == "shadowing")
        coplanarity_count = sum(1 for r in risks if r["risk_type"] == "coplanarity")

        # Process compatibility
        reflow_ok = self._check_reflow_compatibility(components)
        wave_ok = self._check_wave_compatibility(components)
        rework_ok = self._check_rework_accessibility(components)

        # Calculate score
        score = self._calculate_score(
            len(components),
            tombstone_count,
            bridging_count,
            shadowing_count,
            coplanarity_count,
        )

        # Risk level
        if score >= 80:
            risk_level = "low"
        elif score >= 60:
            risk_level = "medium"
        elif score >= 40:
            risk_level = "high"
        else:
            risk_level = "critical"

        # Generate issues and recommendations
        issues = []
        recommendations = []

        if tombstone_count > 0:
            issues.append(f"{tombstone_count} component(s) at risk of tombstoning")
            recommendations.append("Balance pad sizes and thermal connections")
            recommendations.append("Consider different solder paste aperture sizes")

        if bridging_count > 0:
            issues.append(f"{bridging_count} location(s) at risk of solder bridging")
            recommendations.append("Increase pad spacing or reduce paste volume")
            recommendations.append("Consider solder mask defined pads")

        if shadowing_count > 0:
            issues.append(f"{shadowing_count} component(s) may experience shadowing")
            recommendations.append("Review component heights and spacing")
            recommendations.append("Consider reflow profile adjustment")

        if coplanarity_count > 0:
            issues.append(f"{coplanarity_count} BGA(s) with coplanarity concerns")
            recommendations.append("Verify BGA package coplanarity spec")
            recommendations.append("Consider pre-baking BGAs")

        if not wave_ok and assembly_process in ("wave", "mixed"):
            issues.append("Board not fully wave solder compatible")
            recommendations.append("Move SMD components to top side")

        if not rework_ok:
            issues.append("Some components have limited rework accessibility")
            recommendations.append("Increase spacing around critical components")

        return AssemblyResult(
            board_id=board_id,
            assembly_process=assembly_process,
            tombstone_risk_count=tombstone_count,
            bridging_risk_count=bridging_count,
            shadowing_risk_count=shadowing_count,
            coplanarity_risk_count=coplanarity_count,
            reflow_compatible=reflow_ok,
            wave_compatible=wave_ok,
            rework_accessible=rework_ok,
            dfm_score=round(score, 1),
            risk_level=risk_level,
            risks=risks,
            issues=issues,
            recommendations=recommendations,
            metrics={
                "total_components": len(components),
                "smd_count": sum(1 for c in components if c.component_type == "smd"),
                "bga_count": sum(1 for c in components if c.component_type == "bga"),
                "fine_pitch_count": sum(
                    1 for c in components
                    if c.pitch_mm <= self.profile.bridging_pitch_thresholds[2] and c.pitch_mm > 0
                ),
                "manufacturing_profile": self.profile.name,
                "manufacturing_capability": self.profile.capability.value,
                "min_pitch_capability_mm": self.profile.min_pitch_mm,
                "stencil_reduction_percent": self.profile.stencil_reduction_percent,
            },
        )

    def _analyze_component(
        self,
        component: AssemblyComponent,
        process: str,
    ) -> List[Dict]:
        """Analyze risks for a single component."""
        risks = []

        # Tombstoning risk (small passive components)
        tombstone_risk = self._assess_tombstone_risk(component)
        if tombstone_risk:
            risks.append({
                "risk_type": "tombstone",
                "component": component.reference,
                "severity": tombstone_risk,
                "detail": f"Package {component.package} prone to tombstoning",
            })

        # Bridging risk (fine pitch)
        bridging_risk = self._assess_bridging_risk(component)
        if bridging_risk:
            risks.append({
                "risk_type": "bridging",
                "component": component.reference,
                "severity": bridging_risk,
                "detail": f"Pitch {component.pitch_mm}mm may bridge",
            })

        # Shadowing risk (tall components near small ones)
        # Would need neighbor info for full analysis
        if component.height_mm > 5:
            risks.append({
                "risk_type": "shadowing",
                "component": component.reference,
                "severity": "medium",
                "detail": f"Tall component ({component.height_mm}mm) may shadow neighbors",
            })

        # Coplanarity risk (BGAs)
        if component.component_type == "bga":
            coplanarity_risk = self._assess_coplanarity_risk(component)
            if coplanarity_risk:
                risks.append({
                    "risk_type": "coplanarity",
                    "component": component.reference,
                    "severity": coplanarity_risk,
                    "detail": f"BGA with {component.pin_count} balls",
                })

        return risks

    def _assess_tombstone_risk(self, component: AssemblyComponent) -> Optional[str]:
        """Assess tombstoning risk using profile-based thresholds.

        Risk factors considered:
        - Package size vs manufacturing capability
        - Thermal connection imbalance
        - Thermal mass differential
        """
        # Use profile-based tombstone-prone packages
        tombstone_prone = self.profile.tombstone_prone_packages

        # Check if package is in the prone list for this capability
        is_prone = any(pkg in component.package.lower() for pkg in tombstone_prone)

        if not is_prone:
            # Package not considered risky for this manufacturing capability
            return None

        # Risk escalation based on thermal factors
        if component.connected_to_plane:
            # Plane connection without proper thermal relief is high risk
            # Check if component pitch requires thermal relief
            if component.pitch_mm < self.profile.thermal_relief_required_below_pitch_mm:
                return "high"
            return "high"  # Plane connection always increases risk

        if component.thermal_mass == "high":
            return "medium"

        # Check package size against profile minimum reliable
        package_sizes = ["01005", "0201", "0402", "0603", "0805", "1206"]
        min_reliable_idx = package_sizes.index(self.profile.min_reliable_package) if self.profile.min_reliable_package in package_sizes else 0

        for i, pkg in enumerate(package_sizes):
            if pkg in component.package.lower():
                if i < min_reliable_idx:
                    # Smaller than minimum reliable
                    return "high" if i < min_reliable_idx - 1 else "medium"
                break

        return "low"

    def _assess_bridging_risk(self, component: AssemblyComponent) -> Optional[str]:
        """Assess solder bridging risk using profile-based thresholds.

        Modern assembly can handle finer pitches than legacy profiles.
        Thresholds are calibrated per manufacturing capability.
        """
        if component.pitch_mm <= 0:
            return None

        high_threshold, medium_threshold, low_threshold = self.profile.bridging_pitch_thresholds

        # Check against profile thresholds
        if component.pitch_mm <= high_threshold:
            # Below minimum capability - high risk
            if component.pitch_mm < self.profile.min_pitch_mm:
                return "critical"  # Beyond capability
            return "high"
        elif component.pitch_mm <= medium_threshold:
            return "medium"
        elif component.pitch_mm <= low_threshold:
            return "low"

        # Pitch is above all risk thresholds
        return None

    def _assess_coplanarity_risk(self, component: AssemblyComponent) -> Optional[str]:
        """Assess BGA coplanarity risk using profile-based thresholds.

        Risk based on:
        - BGA size (pin count)
        - Profile coplanarity spec
        - Ball pitch
        """
        if component.component_type != "bga":
            return None

        # Profile coplanarity spec affects risk tolerance
        coplanarity_spec = self.profile.bga_coplanarity_spec_mm

        # Stricter profiles (lower spec) can tolerate larger BGAs
        # Risk thresholds scale inversely with coplanarity capability
        high_threshold = int(500 * (0.15 / coplanarity_spec))  # Scale based on 0.15mm baseline
        medium_threshold = int(200 * (0.15 / coplanarity_spec))

        if component.pin_count > high_threshold:
            return "high"
        elif component.pin_count > medium_threshold:
            return "medium"
        else:
            return "low"

    def _check_reflow_compatibility(
        self,
        components: List[AssemblyComponent],
    ) -> bool:
        """Check if board is reflow compatible."""
        # Check for components that can't handle reflow
        for c in components:
            if c.thermal_mass == "very_high":
                return False
        return True

    def _check_wave_compatibility(
        self,
        components: List[AssemblyComponent],
    ) -> bool:
        """Check if board is wave solder compatible using profile limits."""
        max_height = self.profile.wave_max_height_mm
        max_pins = self.profile.wave_max_pins

        for c in components:
            if c.side == "bottom" and c.component_type == "smd":
                # SMD on bottom side may not survive wave
                if c.height_mm > max_height or c.pin_count > max_pins:
                    return False
        return True

    def _check_rework_accessibility(
        self,
        components: List[AssemblyComponent],
    ) -> bool:
        """Check rework accessibility using profile-based thresholds."""
        bga_count = sum(1 for c in components if c.component_type == "bga")

        # Fine pitch threshold based on profile capability
        fine_pitch_threshold = self.profile.bridging_pitch_thresholds[1]  # Medium risk threshold
        fine_pitch = sum(
            1 for c in components
            if c.pitch_mm <= fine_pitch_threshold and c.pitch_mm > 0
        )

        # Scale thresholds based on capability - advanced profiles tolerate more
        capability_factor = {
            ManufacturingCapability.STANDARD: 1.0,
            ManufacturingCapability.FINE_PITCH: 1.5,
            ManufacturingCapability.HDI: 2.0,
            ManufacturingCapability.ADVANCED: 3.0,
        }.get(self.profile.capability, 1.0)

        max_bgas = int(3 * capability_factor)
        max_fine_pitch = int(10 * capability_factor)

        # Many BGAs or fine pitch = harder rework
        if bga_count > max_bgas or fine_pitch > max_fine_pitch:
            return False
        return True

    def _calculate_score(
        self,
        total: int,
        tombstone: int,
        bridging: int,
        shadowing: int,
        coplanarity: int,
    ) -> float:
        """Calculate assembly DFM score."""
        if total == 0:
            return 100

        score = 100.0

        # Weighted penalties
        score -= (tombstone / total) * 25
        score -= (bridging / total) * 30
        score -= (shadowing / total) * 15
        score -= (coplanarity / total) * 20

        return max(0, min(100, score))

    def analyze_thermal_balance(
        self,
        component: AssemblyComponent,
        pad_areas_mm2: Tuple[float, float],
        plane_connection: Tuple[bool, bool],
    ) -> Dict[str, Any]:
        """
        Analyze thermal balance for tombstone prevention.

        Args:
            component: Component to analyze
            pad_areas_mm2: (left_pad_area, right_pad_area)
            plane_connection: (left_connected, right_connected)

        Returns:
            Thermal balance analysis
        """
        left_area, right_area = pad_areas_mm2
        left_plane, right_plane = plane_connection

        # Calculate thermal imbalance
        area_ratio = min(left_area, right_area) / max(left_area, right_area)
        area_imbalance = abs(left_area - right_area)

        # Plane connection creates significant thermal imbalance
        plane_imbalance = left_plane != right_plane

        # Risk assessment
        if plane_imbalance:
            risk = "high"
            recommendation = "Add thermal relief on plane-connected pad"
        elif area_ratio < 0.8:
            risk = "medium"
            recommendation = "Balance pad areas to within 20%"
        else:
            risk = "low"
            recommendation = None

        return {
            "component": component.reference,
            "area_ratio": round(area_ratio, 3),
            "area_imbalance_mm2": round(area_imbalance, 3),
            "plane_imbalance": plane_imbalance,
            "tombstone_risk": risk,
            "recommendation": recommendation,
        }

    def analyze_smt_on_wave_side(
        self,
        components: List[AssemblyComponent],
    ) -> Dict[str, Any]:
        """
        Analyze SMT components on wave solder side.

        Args:
            components: All components

        Returns:
            Wave solder SMT analysis
        """
        bottom_smt = [
            c for c in components
            if c.side == "bottom" and c.component_type == "smd"
        ]

        wave_compatible = []
        wave_incompatible = []

        for c in bottom_smt:
            # Wave-solderable SMD guidelines
            max_height = 2.0  # mm
            max_size = "1206"  # Largest standard size

            is_compatible = (
                c.height_mm <= max_height and
                c.pin_count <= 4 and
                any(pkg in c.package.lower() for pkg in ["0402", "0603", "0805", "1206"])
            )

            if is_compatible:
                wave_compatible.append(c.reference)
            else:
                wave_incompatible.append({
                    "component": c.reference,
                    "package": c.package,
                    "reason": "Too tall or too many pins for wave" if c.height_mm > max_height or c.pin_count > 4 else "Package not wave compatible",
                })

        return {
            "total_bottom_smt": len(bottom_smt),
            "wave_compatible": len(wave_compatible),
            "wave_incompatible": len(wave_incompatible),
            "compatible_components": wave_compatible,
            "incompatible_details": wave_incompatible,
            "recommendation": "Move incompatible SMT to top side" if wave_incompatible else None,
        }


# Alias for consistent naming with other analyzers
AssemblyCheckAnalyzer = AssemblyAnalyzer

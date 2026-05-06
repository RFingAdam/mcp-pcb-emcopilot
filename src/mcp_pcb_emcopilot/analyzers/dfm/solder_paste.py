"""Solder paste stencil analyzer for DFM"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SolderPasteResult:
    """Results from solder paste analysis"""
    # Component identification
    component_ref: str
    package_type: str
    pin_count: int

    # Pad characteristics
    pad_width_mm: float
    pad_length_mm: float
    pad_area_mm2: float

    # Aperture characteristics
    aperture_width_mm: float
    aperture_length_mm: float
    aperture_area_mm2: float

    # Stencil characteristics
    stencil_thickness_mm: float

    # Key ratios
    area_ratio: float  # Aperture area / (perimeter × thickness)
    aspect_ratio: float  # Aperture width / stencil thickness
    transfer_efficiency: float  # Estimated paste transfer %

    # Assessment
    dfm_score: float  # 0-100
    risk_level: str  # low, medium, high, critical

    # Per-pad analysis (for multi-pin packages)
    pad_analysis: List[Dict[str, Any]] = field(default_factory=list)

    # Issues and recommendations
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    # Details
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PadDefinition:
    """Individual pad definition"""
    pad_id: str
    width_mm: float
    length_mm: float
    pitch_mm: float = 0.5
    shape: str = "rectangle"  # rectangle, obround, custom


@dataclass
class ComponentPads:
    """Component pad configuration"""
    reference: str
    package: str  # 0402, 0603, QFN32, BGA256, etc.
    pads: List[PadDefinition]
    is_bga: bool = False
    is_fine_pitch: bool = False


class SolderPasteAnalyzer:
    """
    Solder paste stencil analyzer for DFM.

    Analyzes:
    - Area ratio (key for paste release)
    - Aspect ratio
    - Transfer efficiency estimation
    - Fine-pitch component challenges

    Based on IPC-7525 stencil design guidelines.
    """

    # Standard stencil thicknesses (mm)
    STENCIL_THICKNESSES = {
        "standard": 0.127,     # 5 mil
        "fine_pitch": 0.100,   # 4 mil
        "ultra_fine": 0.075,   # 3 mil
        "thick": 0.150,        # 6 mil
    }

    # Package size database (typical pad dimensions in mm)
    PACKAGE_PADS = {
        "01005": {"width": 0.13, "length": 0.15, "pitch": 0.3},
        "0201": {"width": 0.18, "length": 0.24, "pitch": 0.4},
        "0402": {"width": 0.25, "length": 0.35, "pitch": 0.5},
        "0603": {"width": 0.40, "length": 0.55, "pitch": 0.8},
        "0805": {"width": 0.60, "length": 0.90, "pitch": 1.0},
        "1206": {"width": 0.90, "length": 1.35, "pitch": 1.5},
        "qfn_0.4mm": {"width": 0.20, "length": 0.60, "pitch": 0.4},
        "qfn_0.5mm": {"width": 0.25, "length": 0.80, "pitch": 0.5},
        "qfp_0.5mm": {"width": 0.25, "length": 1.50, "pitch": 0.5},
        "qfp_0.4mm": {"width": 0.20, "length": 1.20, "pitch": 0.4},
        "bga_0.4mm": {"width": 0.20, "length": 0.20, "pitch": 0.4},
        "bga_0.5mm": {"width": 0.25, "length": 0.25, "pitch": 0.5},
        "bga_0.8mm": {"width": 0.35, "length": 0.35, "pitch": 0.8},
        "bga_1.0mm": {"width": 0.45, "length": 0.45, "pitch": 1.0},
    }

    # Minimum area ratio for reliable paste release
    MIN_AREA_RATIO = {
        "standard": 0.66,      # Chemically etched
        "laser_cut": 0.60,     # Laser cut
        "electroformed": 0.55, # Electroformed (best walls)
    }

    def __init__(self, stencil_type: str = "laser_cut"):
        """
        Initialize analyzer.

        Args:
            stencil_type: Type of stencil (standard, laser_cut, electroformed)
        """
        self.stencil_type = stencil_type
        self.min_area_ratio = self.MIN_AREA_RATIO.get(stencil_type, 0.66)

    def analyze_component(
        self,
        component: ComponentPads,
        stencil_thickness_mm: Optional[float] = None,
        aperture_reduction_percent: float = 0,
    ) -> SolderPasteResult:
        """
        Analyze solder paste design for a component.

        Args:
            component: Component pad configuration
            stencil_thickness_mm: Stencil thickness (auto-selected if None)
            aperture_reduction_percent: Aperture reduction from pad size

        Returns:
            SolderPasteResult with complete analysis
        """
        if not component.pads:
            raise ValueError("Component must have at least one pad")

        # Select stencil thickness if not specified
        if stencil_thickness_mm is None:
            stencil_thickness_mm = self._select_stencil_thickness(component)

        # Analyze each pad
        pad_results: list[dict[str, Any]] = []
        worst_area_ratio = float('inf')
        worst_aspect_ratio = float('inf')

        for pad in component.pads:
            pad_area = pad.width_mm * pad.length_mm

            # Calculate aperture size with reduction
            reduction_factor = 1 - (aperture_reduction_percent / 100)
            apt_width = pad.width_mm * reduction_factor
            apt_length = pad.length_mm * reduction_factor
            apt_area = apt_width * apt_length

            # Calculate area ratio
            perimeter = 2 * (apt_width + apt_length)
            wall_area = perimeter * stencil_thickness_mm
            area_ratio = apt_area / wall_area if wall_area > 0 else 0

            # Calculate aspect ratio (width / thickness)
            aspect_ratio = min(apt_width, apt_length) / stencil_thickness_mm

            # Track worst cases
            worst_area_ratio = min(worst_area_ratio, area_ratio)
            worst_aspect_ratio = min(worst_aspect_ratio, aspect_ratio)

            pad_results.append({
                "pad_id": pad.pad_id,
                "pad_width_mm": pad.width_mm,
                "pad_length_mm": pad.length_mm,
                "aperture_width_mm": round(apt_width, 3),
                "aperture_length_mm": round(apt_length, 3),
                "area_ratio": round(area_ratio, 3),
                "aspect_ratio": round(aspect_ratio, 3),
                "pass": area_ratio >= self.min_area_ratio,
            })

        # Use first pad for summary (typically representative)
        first_pad = component.pads[0]
        first_result = pad_results[0]

        # Calculate transfer efficiency
        transfer_efficiency = self._estimate_transfer_efficiency(
            worst_area_ratio,
            worst_aspect_ratio,
        )

        # DFM score
        score = self._calculate_dfm_score(
            worst_area_ratio,
            worst_aspect_ratio,
            transfer_efficiency,
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

        # Issues and recommendations
        issues = []
        recommendations = []

        if worst_area_ratio < self.min_area_ratio:
            issues.append(f"Area ratio {worst_area_ratio:.2f} below {self.min_area_ratio:.2f} minimum")
            recommendations.append("Use thinner stencil or electroformed process")
            recommendations.append("Consider aperture modifications (home plate, etc.)")

        if worst_aspect_ratio < 1.5:
            issues.append(f"Low aspect ratio {worst_aspect_ratio:.2f}")
            recommendations.append("Use step stencil or local thickness reduction")

        if transfer_efficiency < 75:
            issues.append(f"Low paste transfer efficiency ({transfer_efficiency:.0f}%)")

        if component.is_bga and stencil_thickness_mm > 0.1:
            issues.append("BGA may need reduced stencil thickness")
            recommendations.append("Consider 0.100mm (4mil) stencil for BGA")

        # Check for fine-pitch specific issues
        if component.is_fine_pitch:
            if stencil_thickness_mm > 0.1:
                recommendations.append("Fine-pitch requires ≤0.100mm stencil")
            if aperture_reduction_percent < 10:
                recommendations.append("Consider 10-15% aperture reduction for fine-pitch")

        return SolderPasteResult(
            component_ref=component.reference,
            package_type=component.package,
            pin_count=len(component.pads),
            pad_width_mm=first_pad.width_mm,
            pad_length_mm=first_pad.length_mm,
            pad_area_mm2=round(first_pad.width_mm * first_pad.length_mm, 4),
            aperture_width_mm=first_result["aperture_width_mm"],
            aperture_length_mm=first_result["aperture_length_mm"],
            aperture_area_mm2=round(
                first_result["aperture_width_mm"] * first_result["aperture_length_mm"], 4
            ),
            stencil_thickness_mm=stencil_thickness_mm,
            area_ratio=round(worst_area_ratio, 3),
            aspect_ratio=round(worst_aspect_ratio, 3),
            transfer_efficiency=round(transfer_efficiency, 1),
            dfm_score=round(score, 1),
            risk_level=risk_level,
            pad_analysis=pad_results,
            issues=issues,
            recommendations=recommendations,
            metrics={
                "stencil_type": self.stencil_type,
                "min_area_ratio": self.min_area_ratio,
                "aperture_reduction_percent": aperture_reduction_percent,
                "is_fine_pitch": component.is_fine_pitch,
                "is_bga": component.is_bga,
            },
        )

    def _select_stencil_thickness(self, component: ComponentPads) -> float:
        """Select appropriate stencil thickness for component."""
        # Find minimum pad dimension
        min_dim = float('inf')
        for pad in component.pads:
            min_dim = min(min_dim, pad.width_mm, pad.length_mm)

        # Select based on smallest feature
        if min_dim < 0.20:
            return self.STENCIL_THICKNESSES["ultra_fine"]  # 3 mil
        elif min_dim < 0.30 or component.is_fine_pitch:
            return self.STENCIL_THICKNESSES["fine_pitch"]  # 4 mil
        else:
            return self.STENCIL_THICKNESSES["standard"]  # 5 mil

    def _estimate_transfer_efficiency(
        self,
        area_ratio: float,
        aspect_ratio: float,
    ) -> float:
        """
        Estimate paste transfer efficiency.

        Based on empirical data from stencil printing studies.
        """
        # Area ratio dominates
        base_efficiency: float
        if area_ratio >= 0.75:
            base_efficiency = 95.0
        elif area_ratio >= 0.66:
            base_efficiency = 85.0
        elif area_ratio >= 0.55:
            base_efficiency = 75.0
        elif area_ratio >= 0.45:
            base_efficiency = 60.0
        else:
            base_efficiency = 40.0

        # Aspect ratio modifier
        if aspect_ratio < 1.0:
            base_efficiency *= 0.7
        elif aspect_ratio < 1.5:
            base_efficiency *= 0.85

        return min(100, base_efficiency)

    def _calculate_dfm_score(
        self,
        area_ratio: float,
        aspect_ratio: float,
        transfer_efficiency: float,
    ) -> float:
        """Calculate overall DFM score."""
        score = 100.0

        # Area ratio (40% weight)
        if area_ratio < self.min_area_ratio:
            deficit = self.min_area_ratio - area_ratio
            score -= deficit * 60

        # Aspect ratio (30% weight)
        if aspect_ratio < 1.5:
            score -= (1.5 - aspect_ratio) * 20

        # Transfer efficiency (30% weight)
        if transfer_efficiency < 85:
            score -= (85 - transfer_efficiency) * 0.5

        return max(0, min(100, score))

    def analyze_from_package(
        self,
        package_name: str,
        reference: str = "U1",
        pin_count: int = 1,
        stencil_thickness_mm: Optional[float] = None,
    ) -> SolderPasteResult:
        """
        Analyze based on standard package name.

        Args:
            package_name: Package type (0402, QFN32, BGA256, etc.)
            reference: Component reference
            pin_count: Number of pins
            stencil_thickness_mm: Stencil thickness

        Returns:
            SolderPasteResult
        """
        # Look up package in database
        package_lower = package_name.lower()
        package_info = None

        for key, info in self.PACKAGE_PADS.items():
            if key in package_lower or package_lower in key:
                package_info = info
                break

        if package_info is None:
            # Default to 0603
            package_info = self.PACKAGE_PADS["0603"]

        # Create pad definition
        pads = [
            PadDefinition(
                pad_id=f"P{i+1}",
                width_mm=package_info["width"],
                length_mm=package_info["length"],
                pitch_mm=package_info["pitch"],
            )
            for i in range(min(pin_count, 10))  # Analyze up to 10 pads
        ]

        is_bga = "bga" in package_lower
        is_fine_pitch = package_info["pitch"] <= 0.5

        component = ComponentPads(
            reference=reference,
            package=package_name,
            pads=pads,
            is_bga=is_bga,
            is_fine_pitch=is_fine_pitch,
        )

        return self.analyze_component(component, stencil_thickness_mm)

    def recommend_stencil(
        self,
        components: List[Tuple[str, int]],  # [(package, count), ...]
    ) -> Dict[str, Any]:
        """
        Recommend stencil configuration for a board.

        Args:
            components: List of (package_name, quantity) tuples

        Returns:
            Stencil recommendations
        """
        # Analyze all component types
        analyses = []
        min_pitch = float('inf')
        has_bga = False

        for package, count in components:
            result = self.analyze_from_package(package, pin_count=4)
            analyses.append({
                "package": package,
                "count": count,
                "area_ratio": result.area_ratio,
                "risk_level": result.risk_level,
            })

            # Track constraints
            if "bga" in package.lower():
                has_bga = True
                pitch = float(package.split("_")[-1].replace("mm", "")) if "_" in package else 1.0
                min_pitch = min(min_pitch, pitch)

        # Determine stencil thickness
        if min_pitch <= 0.4:
            recommended_thickness = 0.075  # 3 mil
            thickness_note = "Ultra-fine pitch requires 3mil stencil"
        elif min_pitch <= 0.5 or has_bga:
            recommended_thickness = 0.100  # 4 mil
            thickness_note = "Fine pitch/BGA requires 4mil stencil"
        else:
            recommended_thickness = 0.127  # 5 mil
            thickness_note = "Standard 5mil stencil suitable"

        # Count risk levels
        high_risk = sum(1 for a in analyses if a["risk_level"] in ("high", "critical"))

        return {
            "recommended_thickness_mm": recommended_thickness,
            "recommended_thickness_mil": recommended_thickness / 0.0254,
            "note": thickness_note,
            "stencil_type": "electroformed" if min_pitch <= 0.4 else "laser_cut",
            "high_risk_packages": high_risk,
            "analyses": analyses,
            "suggestions": [
                "Use electroformed stencil for best paste release" if min_pitch <= 0.5 else None,
                "Consider step stencil if mixing 01005 with large passives" if min_pitch <= 0.3 else None,
                "Nano-coating recommended for fine-pitch" if min_pitch <= 0.4 else None,
            ],
        }

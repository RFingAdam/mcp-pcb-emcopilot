"""Shielding effectiveness analyzer for EMC"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import math


@dataclass
class ShieldingResult:
    """Results from shielding effectiveness analysis"""
    # Shield identification
    shield_id: str
    description: str

    # Material properties
    material: str
    thickness_mm: float
    conductivity_s_m: float  # S/m
    permeability: float  # Relative

    # Shielding effectiveness
    se_electric_db: float  # For E-field
    se_magnetic_db: float  # For H-field
    se_plane_wave_db: float  # For plane wave
    se_total_db: float  # Minimum of all

    # Frequency characteristics
    frequency_mhz: float
    skin_depth_um: float

    # Aperture effects
    aperture_leakage_db: float
    largest_aperture_mm: float
    resonance_frequency_mhz: Optional[float]

    # Assessment
    effectiveness_rating: str  # excellent, good, moderate, poor, inadequate
    emc_score: float  # 0-100

    # Issues and recommendations
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    # Detailed metrics
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ShieldConfig:
    """Shield configuration"""
    material: str = "aluminum"
    thickness_mm: float = 1.0
    length_mm: float = 100
    width_mm: float = 100
    height_mm: float = 50
    apertures: List[Dict[str, float]] = field(default_factory=list)  # List of {type, diameter/length, width}


class ShieldingAnalyzer:
    """
    Shielding effectiveness analyzer.

    Calculates shielding effectiveness for:
    - Solid metal enclosures
    - PCB shielding cans
    - Aperture/slot leakage
    - Seam leakage

    Based on IEEE 299 and classical shielding theory.
    """

    # Material properties: (conductivity S/m, relative permeability)
    MATERIALS = {
        "copper": (5.8e7, 1.0),
        "aluminum": (3.77e7, 1.0),
        "steel": (6.99e6, 200),
        "mu_metal": (1.8e6, 20000),
        "nickel": (1.43e7, 100),
        "tin": (9.17e6, 1.0),
        "zinc": (1.69e7, 1.0),
        "silver": (6.3e7, 1.0),
        "brass": (1.5e7, 1.0),
        "phosphor_bronze": (1.0e7, 1.0),
    }

    # Free space permeability
    MU0 = 4 * math.pi * 1e-7  # H/m

    # Free space impedance
    Z0 = 377  # ohms

    def __init__(self):
        pass

    def analyze_shield(
        self,
        config: ShieldConfig,
        frequency_mhz: float = 100,
        shield_id: str = "S1",
    ) -> ShieldingResult:
        """
        Analyze shielding effectiveness.

        Args:
            config: Shield configuration
            frequency_mhz: Frequency of interest
            shield_id: Identifier for this shield

        Returns:
            ShieldingResult with complete analysis
        """
        # Get material properties
        sigma, mu_r = self.MATERIALS.get(
            config.material.lower(),
            self.MATERIALS["aluminum"]
        )

        # Calculate skin depth
        skin_depth = self._calculate_skin_depth(frequency_mhz, sigma, mu_r)

        # Calculate SE for solid shield (no apertures)
        se_e, se_h, se_pw = self._calculate_solid_se(
            config.thickness_mm,
            frequency_mhz,
            sigma,
            mu_r,
        )

        # Calculate aperture leakage
        aperture_leak = 0
        largest_aperture = 0
        resonance_freq = None

        if config.apertures:
            aperture_leak, largest_aperture = self._calculate_aperture_leakage(
                config.apertures,
                frequency_mhz,
            )
            # Check for slot resonance
            resonance_freq = self._check_resonance(config.apertures)

        # Total SE (worst case)
        se_total = min(se_e, se_h, se_pw) - aperture_leak

        # Effectiveness rating
        if se_total >= 80:
            rating = "excellent"
            score = 95
        elif se_total >= 60:
            rating = "good"
            score = 80
        elif se_total >= 40:
            rating = "moderate"
            score = 65
        elif se_total >= 20:
            rating = "poor"
            score = 40
        else:
            rating = "inadequate"
            score = 20

        # Adjust score for aperture issues
        if aperture_leak > 20:
            score -= 15
        if resonance_freq and abs(resonance_freq - frequency_mhz) < 50:
            score -= 20

        # Generate issues and recommendations
        issues = []
        recommendations = []

        if se_total < 30:
            issues.append(f"Low shielding effectiveness: {se_total:.1f}dB")
            recommendations.append("Increase shield thickness or use higher conductivity material")

        if aperture_leak > 10:
            issues.append(f"Significant aperture leakage: {aperture_leak:.1f}dB")
            recommendations.append("Reduce aperture size or use waveguide beyond cutoff")

        if largest_aperture > 0:
            wavelength_mm = 300000 / frequency_mhz
            if largest_aperture > wavelength_mm / 20:
                issues.append(f"Aperture {largest_aperture:.1f}mm > λ/20 ({wavelength_mm/20:.1f}mm)")
                recommendations.append("Add honeycomb or mesh over large apertures")

        if resonance_freq:
            issues.append(f"Slot resonance near {resonance_freq:.0f}MHz")
            recommendations.append("Break up long slots with conductive bonds")

        if config.thickness_mm < 5 * skin_depth / 1000:
            issues.append(f"Shield thickness < 5 skin depths at {frequency_mhz}MHz")

        return ShieldingResult(
            shield_id=shield_id,
            description=f"{config.material} shield {config.thickness_mm}mm",
            material=config.material,
            thickness_mm=config.thickness_mm,
            conductivity_s_m=sigma,
            permeability=mu_r,
            se_electric_db=round(se_e, 1),
            se_magnetic_db=round(se_h, 1),
            se_plane_wave_db=round(se_pw, 1),
            se_total_db=round(se_total, 1),
            frequency_mhz=frequency_mhz,
            skin_depth_um=round(skin_depth, 2),
            aperture_leakage_db=round(aperture_leak, 1),
            largest_aperture_mm=round(largest_aperture, 2),
            resonance_frequency_mhz=round(resonance_freq, 1) if resonance_freq else None,
            effectiveness_rating=rating,
            emc_score=round(max(0, min(100, score)), 1),
            issues=issues,
            recommendations=recommendations,
            metrics={
                "wavelength_mm": 300000 / frequency_mhz,
                "absorption_loss_db": round(self._absorption_loss(config.thickness_mm, skin_depth), 1),
                "reflection_loss_db": round(se_pw - self._absorption_loss(config.thickness_mm, skin_depth), 1),
            },
        )

    def _calculate_skin_depth(
        self,
        frequency_mhz: float,
        conductivity: float,
        permeability: float,
    ) -> float:
        """
        Calculate skin depth in micrometers.

        δ = sqrt(2 / (ω × μ × σ))
        """
        omega = 2 * math.pi * frequency_mhz * 1e6
        mu = self.MU0 * permeability
        delta = math.sqrt(2 / (omega * mu * conductivity))
        return delta * 1e6  # Convert to um

    def _calculate_solid_se(
        self,
        thickness_mm: float,
        frequency_mhz: float,
        conductivity: float,
        permeability: float,
    ) -> tuple:
        """
        Calculate SE for solid shield (E-field, H-field, plane wave).

        SE = R + A + B (reflection + absorption + multiple reflection)
        """
        skin_depth_um = self._calculate_skin_depth(frequency_mhz, conductivity, permeability)
        skin_depth_mm = skin_depth_um / 1000
        t_over_delta = thickness_mm / skin_depth_mm

        # Absorption loss (same for all wave types)
        absorption = self._absorption_loss(thickness_mm, skin_depth_um)

        # Calculate shield impedance
        omega = 2 * math.pi * frequency_mhz * 1e6
        mu = self.MU0 * permeability
        z_shield = math.sqrt(omega * mu / conductivity) * (1 + 1j) / math.sqrt(2)
        z_s_mag = abs(z_shield)

        # Reflection loss for plane wave
        reflection_pw = 20 * math.log10(self.Z0 / (4 * z_s_mag))

        # Reflection loss for E-field (near field electric)
        # Higher because source impedance is higher
        reflection_e = reflection_pw + 10  # Approximate

        # Reflection loss for H-field (near field magnetic)
        # Lower because source impedance is lower
        reflection_h = reflection_pw - 15  # Approximate

        # Multiple reflection correction (significant only for thin shields)
        if t_over_delta < 1:
            mr_correction = 20 * math.log10(1 - math.exp(-2 * t_over_delta))
        else:
            mr_correction = 0

        se_e = absorption + reflection_e + mr_correction
        se_h = max(absorption + reflection_h + mr_correction, absorption)  # H-field limited
        se_pw = absorption + reflection_pw + mr_correction

        return se_e, se_h, se_pw

    def _absorption_loss(self, thickness_mm: float, skin_depth_um: float) -> float:
        """Calculate absorption loss in dB."""
        skin_depth_mm = skin_depth_um / 1000
        if skin_depth_mm > 0:
            return 8.686 * thickness_mm / skin_depth_mm
        return 100

    def _calculate_aperture_leakage(
        self,
        apertures: List[Dict[str, float]],
        frequency_mhz: float,
    ) -> tuple:
        """
        Calculate total aperture leakage and largest aperture.

        Returns:
            (total_leakage_db, largest_aperture_mm)
        """
        wavelength_mm = 300000 / frequency_mhz
        max_aperture = 0
        total_leakage_linear = 0

        for ap in apertures:
            ap_type = ap.get("type", "circle")
            if ap_type == "circle":
                diameter = ap.get("diameter", 1)
                max_aperture = max(max_aperture, diameter)
                # Circular aperture SE reduction
                if diameter < wavelength_mm / 2:
                    se_reduction = 20 * math.log10(wavelength_mm / (2 * diameter))
                else:
                    se_reduction = 0
            elif ap_type == "slot":
                length = ap.get("length", 10)
                width = ap.get("width", 1)
                max_aperture = max(max_aperture, length)
                # Slot aperture SE reduction (worse than circular)
                if length < wavelength_mm / 2:
                    se_reduction = 20 * math.log10(wavelength_mm / (2 * length))
                else:
                    se_reduction = 0
            else:
                se_reduction = 10  # Default

            # Number of identical apertures
            count = ap.get("count", 1)

            # Aperture coupling is additive in power
            leakage_linear = 10 ** (-se_reduction / 20) * count
            total_leakage_linear += leakage_linear ** 2

        # Convert back to dB reduction
        if total_leakage_linear > 0:
            total_leakage_db = -10 * math.log10(total_leakage_linear)
            # Leakage = reduction in SE
            leakage = max(0, 60 - total_leakage_db)  # 60dB baseline
        else:
            leakage = 0

        return leakage, max_aperture

    def _check_resonance(self, apertures: List[Dict[str, float]]) -> Optional[float]:
        """Check for slot resonance frequency."""
        for ap in apertures:
            if ap.get("type") == "slot":
                length = ap.get("length", 0)
                if length > 0:
                    # Slot resonance at λ/2 = length
                    resonance_mhz = 150000 / length  # f = c / (2L)
                    return resonance_mhz
        return None

    def recommend_shield(
        self,
        required_se_db: float,
        frequency_mhz: float,
        max_thickness_mm: float = 2.0,
        aperture_size_mm: float = 0,
    ) -> Dict[str, Any]:
        """
        Recommend shield parameters for required SE.

        Args:
            required_se_db: Required shielding effectiveness
            frequency_mhz: Operating frequency
            max_thickness_mm: Maximum allowable thickness
            aperture_size_mm: Largest unavoidable aperture

        Returns:
            Dictionary with recommended shield parameters
        """
        recommendations = []

        for material, (sigma, mu_r) in self.MATERIALS.items():
            skin_depth = self._calculate_skin_depth(frequency_mhz, sigma, mu_r)

            # Try different thicknesses
            for thickness in [0.1, 0.2, 0.5, 1.0, 1.5, 2.0]:
                if thickness > max_thickness_mm:
                    continue

                se_e, se_h, se_pw = self._calculate_solid_se(
                    thickness, frequency_mhz, sigma, mu_r
                )
                se = min(se_e, se_h, se_pw)

                # Account for aperture
                if aperture_size_mm > 0:
                    wavelength_mm = 300000 / frequency_mhz
                    if aperture_size_mm < wavelength_mm / 2:
                        aperture_se = 20 * math.log10(wavelength_mm / (2 * aperture_size_mm))
                        se = min(se, aperture_se)

                if se >= required_se_db:
                    recommendations.append({
                        "material": material,
                        "thickness_mm": thickness,
                        "achieved_se_db": round(se, 1),
                        "margin_db": round(se - required_se_db, 1),
                        "skin_depths": round(thickness * 1000 / skin_depth, 1),
                    })

        # Sort by thickness (prefer thinner)
        recommendations.sort(key=lambda x: (x["thickness_mm"], -x["achieved_se_db"]))

        if recommendations:
            return {
                "success": True,
                "best_option": recommendations[0],
                "alternatives": recommendations[1:5],
            }
        else:
            return {
                "success": False,
                "message": f"Cannot achieve {required_se_db}dB SE within {max_thickness_mm}mm thickness",
                "suggestions": [
                    "Increase allowable thickness",
                    "Reduce aperture size",
                    "Consider multi-layer shielding",
                ],
            }

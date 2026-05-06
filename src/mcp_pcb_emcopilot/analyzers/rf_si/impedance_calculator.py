"""
Transmission line impedance calculator for PCB traces.

Implements IPC-2141 and industry-standard formulas for:
- Microstrip (surface traces)
- Embedded microstrip (with solder mask)
- Stripline (buried between planes)
- Coplanar waveguide (with/without ground)
- Differential pairs
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TraceType(Enum):
    """Transmission line types"""
    MICROSTRIP = "microstrip"
    EMBEDDED_MICROSTRIP = "embedded_microstrip"
    STRIPLINE = "stripline"
    ASYMMETRIC_STRIPLINE = "asymmetric_stripline"
    COPLANAR_WAVEGUIDE = "cpw"
    COPLANAR_WAVEGUIDE_GROUND = "cpw_ground"


@dataclass
class ImpedanceResult:
    """Result of impedance calculation"""
    # Calculated values
    impedance_ohm: float
    effective_dielectric: float
    propagation_delay_ps_per_mm: float
    phase_velocity_mm_per_ns: float

    # Loss characteristics
    conductor_loss_db_per_mm: float = 0.0
    dielectric_loss_db_per_mm: float = 0.0
    total_loss_db_per_mm: float = 0.0

    # Input parameters (for reference)
    trace_type: str = ""
    width_mm: float = 0.0
    height_mm: float = 0.0
    thickness_mm: float = 0.0
    dielectric_constant: float = 0.0
    frequency_hz: float = 1e9

    # Model information
    model_used: str = ""
    model_accuracy: str = "typical"  # typical, high, approximate

    @property
    def wavelength_mm(self) -> float:
        """Calculate wavelength at the specified frequency"""
        c = 299792458000  # mm/s
        return c / (self.frequency_hz * math.sqrt(self.effective_dielectric))

    @property
    def electrical_length_deg_per_mm(self) -> float:
        """Electrical length in degrees per mm"""
        return 360 / self.wavelength_mm

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "impedance_ohm": round(self.impedance_ohm, 2),
            "effective_dielectric": round(self.effective_dielectric, 3),
            "propagation_delay_ps_per_mm": round(self.propagation_delay_ps_per_mm, 3),
            "phase_velocity_mm_per_ns": round(self.phase_velocity_mm_per_ns, 1),
            "conductor_loss_db_per_mm": round(self.conductor_loss_db_per_mm, 6),
            "dielectric_loss_db_per_mm": round(self.dielectric_loss_db_per_mm, 6),
            "total_loss_db_per_mm": round(self.total_loss_db_per_mm, 6),
            "wavelength_mm": round(self.wavelength_mm, 2),
            "trace_type": self.trace_type,
            "model_used": self.model_used,
        }


class ImpedanceCalculator:
    """
    Transmission line impedance calculator.

    Implements multiple calculation methods:
    - IPC-2141 formulas (standard)
    - Hammerstad-Jensen equations (high accuracy)
    - Wheeler approximations (fast)

    Usage:
        calc = ImpedanceCalculator()
        result = calc.microstrip(
            width_mm=0.15,
            height_mm=0.2,
            dielectric_constant=4.3
        )
        print(f"Impedance: {result.impedance_ohm:.1f} Ohm")
    """

    # Physical constants
    C0 = 299792458  # Speed of light in m/s
    MU0 = 4 * math.pi * 1e-7  # Permeability of free space
    EPS0 = 8.854187817e-12  # Permittivity of free space
    COPPER_CONDUCTIVITY = 5.8e7  # S/m

    def __init__(
        self,
        default_frequency_hz: float = 1e9,
        default_loss_tangent: float = 0.02,
        default_copper_conductivity: float = 5.8e7,
    ):
        """
        Initialize calculator.

        Args:
            default_frequency_hz: Default frequency for loss calculations
            default_loss_tangent: Default dielectric loss tangent
            default_copper_conductivity: Conductivity of copper (S/m)
        """
        self.default_frequency = default_frequency_hz
        self.default_loss_tangent = default_loss_tangent
        self.copper_conductivity = default_copper_conductivity

    def microstrip(
        self,
        width_mm: float,
        height_mm: float,
        dielectric_constant: float,
        thickness_mm: float = 0.035,
        loss_tangent: Optional[float] = None,
        frequency_hz: Optional[float] = None,
    ) -> ImpedanceResult:
        """
        Calculate microstrip impedance using IPC-2141 / Hammerstad formulas.

        Args:
            width_mm: Trace width in mm
            height_mm: Height above ground plane (dielectric thickness) in mm
            dielectric_constant: Relative permittivity of substrate
            thickness_mm: Copper thickness in mm (default 1oz = 0.035mm)
            loss_tangent: Dielectric loss tangent
            frequency_hz: Frequency for loss calculation

        Returns:
            ImpedanceResult with impedance and related parameters
        """
        freq = frequency_hz or self.default_frequency
        tan_d = loss_tangent or self.default_loss_tangent

        # Effective width accounting for thickness (Hammerstad correction)
        if width_mm / height_mm < 0.5 * math.pi:
            w_eff = width_mm + thickness_mm / math.pi * (
                1 + math.log(4 * math.pi * width_mm / thickness_mm)
            )
        else:
            w_eff = width_mm + thickness_mm / math.pi * (
                1 + math.log(2 * height_mm / thickness_mm)
            )

        w_h = w_eff / height_mm

        # Effective dielectric constant (Hammerstad-Jensen)
        if w_h <= 1:
            eps_eff = (dielectric_constant + 1) / 2 + (dielectric_constant - 1) / 2 * (
                1 / math.sqrt(1 + 12 / w_h) + 0.04 * (1 - w_h) ** 2
            )
        else:
            eps_eff = (dielectric_constant + 1) / 2 + (
                (dielectric_constant - 1) / 2 / math.sqrt(1 + 12 / w_h)
            )

        # Characteristic impedance
        if w_h <= 1:
            z0 = 60 / math.sqrt(eps_eff) * math.log(8 / w_h + w_h / 4)
        else:
            z0 = 120 * math.pi / math.sqrt(eps_eff) / (
                w_h + 1.393 + 0.667 * math.log(w_h + 1.444)
            )

        # Propagation characteristics
        vp = self.C0 / math.sqrt(eps_eff)  # Phase velocity in m/s
        delay_ps_per_mm = 1e12 / (vp * 1000)  # ps/mm

        # Loss calculations
        conductor_loss = self._calculate_conductor_loss(
            width_mm, height_mm, thickness_mm, z0, freq
        )
        dielectric_loss = self._calculate_dielectric_loss(eps_eff, tan_d, freq)

        return ImpedanceResult(
            impedance_ohm=z0,
            effective_dielectric=eps_eff,
            propagation_delay_ps_per_mm=delay_ps_per_mm,
            phase_velocity_mm_per_ns=vp / 1e6,  # mm/ns
            conductor_loss_db_per_mm=conductor_loss,
            dielectric_loss_db_per_mm=dielectric_loss,
            total_loss_db_per_mm=conductor_loss + dielectric_loss,
            trace_type="microstrip",
            width_mm=width_mm,
            height_mm=height_mm,
            thickness_mm=thickness_mm,
            dielectric_constant=dielectric_constant,
            frequency_hz=freq,
            model_used="hammerstad_jensen",
        )

    def embedded_microstrip(
        self,
        width_mm: float,
        height_mm: float,
        cover_height_mm: float,
        dielectric_constant: float,
        cover_dielectric: float = 3.3,  # Solder mask
        thickness_mm: float = 0.035,
        loss_tangent: Optional[float] = None,
        frequency_hz: Optional[float] = None,
    ) -> ImpedanceResult:
        """
        Calculate embedded microstrip (with solder mask) impedance.

        Args:
            width_mm: Trace width
            height_mm: Height to ground plane
            cover_height_mm: Solder mask thickness
            dielectric_constant: Substrate dielectric constant
            cover_dielectric: Cover layer (solder mask) dielectric constant
            thickness_mm: Copper thickness
            loss_tangent: Dielectric loss tangent
            frequency_hz: Frequency for loss calculation

        Returns:
            ImpedanceResult
        """
        # First calculate bare microstrip
        bare = self.microstrip(
            width_mm, height_mm, dielectric_constant, thickness_mm,
            loss_tangent, frequency_hz
        )

        # Adjust for solder mask cover using empirical formula
        # The solder mask increases effective Er and lowers Z0
        h_ratio = cover_height_mm / height_mm
        er_cover_effect = 1 + h_ratio * (cover_dielectric / dielectric_constant - 1) * 0.7

        # Effective dielectric with cover
        eps_eff_covered = bare.effective_dielectric * er_cover_effect

        # Impedance reduction due to cover (typically 3-8%)
        z0_reduction = 1 - 0.05 * h_ratio * (cover_dielectric / dielectric_constant)
        z0 = bare.impedance_ohm * z0_reduction

        # Recalculate propagation
        vp = self.C0 / math.sqrt(eps_eff_covered)
        delay_ps_per_mm = 1e12 / (vp * 1000)

        return ImpedanceResult(
            impedance_ohm=z0,
            effective_dielectric=eps_eff_covered,
            propagation_delay_ps_per_mm=delay_ps_per_mm,
            phase_velocity_mm_per_ns=vp / 1e6,
            conductor_loss_db_per_mm=bare.conductor_loss_db_per_mm,
            dielectric_loss_db_per_mm=bare.dielectric_loss_db_per_mm * 1.1,  # Slightly higher with mask
            total_loss_db_per_mm=bare.conductor_loss_db_per_mm + bare.dielectric_loss_db_per_mm * 1.1,
            trace_type="embedded_microstrip",
            width_mm=width_mm,
            height_mm=height_mm,
            thickness_mm=thickness_mm,
            dielectric_constant=dielectric_constant,
            frequency_hz=frequency_hz or self.default_frequency,
            model_used="embedded_hammerstad",
        )

    def stripline(
        self,
        width_mm: float,
        height_mm: float,
        dielectric_constant: float,
        thickness_mm: float = 0.035,
        loss_tangent: Optional[float] = None,
        frequency_hz: Optional[float] = None,
    ) -> ImpedanceResult:
        """
        Calculate symmetric stripline impedance.

        For a trace centered between two ground planes.

        Args:
            width_mm: Trace width
            height_mm: Distance from trace center to each ground plane
            dielectric_constant: Substrate dielectric constant
            thickness_mm: Copper thickness
            loss_tangent: Dielectric loss tangent
            frequency_hz: Frequency for loss calculation

        Returns:
            ImpedanceResult
        """
        freq = frequency_hz or self.default_frequency
        tan_d = loss_tangent or self.default_loss_tangent

        # Total height between planes
        b = 2 * height_mm

        # Effective width considering thickness
        w_eff = width_mm
        if thickness_mm > 0:
            # Correction for finite thickness
            m = 6 * height_mm / (3 * height_mm + thickness_mm)
            if width_mm / b <= 0.35:
                w_eff = width_mm - thickness_mm * (1 - math.log(4 * math.pi * width_mm / thickness_mm))
            else:
                w_eff = width_mm

        w_b = w_eff / b
        t_b = thickness_mm / b

        # Stripline impedance (Cohn formula)
        if w_b < 0.35:
            k = math.cosh(math.pi * w_eff / (2 * b))
            z0 = 30 * math.pi / math.sqrt(dielectric_constant) / k
        else:
            # Wheeler formula for wider traces
            cf = (1 - t_b) * (0.0885 * dielectric_constant + 0.3)
            z0 = 30 * math.pi / math.sqrt(dielectric_constant) * b / (w_eff + cf * b)

        # For stripline, effective Er equals material Er
        eps_eff = dielectric_constant

        # Propagation
        vp = self.C0 / math.sqrt(eps_eff)
        delay_ps_per_mm = 1e12 / (vp * 1000)

        # Loss
        conductor_loss = self._calculate_conductor_loss(
            width_mm, height_mm, thickness_mm, z0, freq
        ) * 1.2  # Slightly higher for stripline
        dielectric_loss = self._calculate_dielectric_loss(eps_eff, tan_d, freq)

        return ImpedanceResult(
            impedance_ohm=z0,
            effective_dielectric=eps_eff,
            propagation_delay_ps_per_mm=delay_ps_per_mm,
            phase_velocity_mm_per_ns=vp / 1e6,
            conductor_loss_db_per_mm=conductor_loss,
            dielectric_loss_db_per_mm=dielectric_loss,
            total_loss_db_per_mm=conductor_loss + dielectric_loss,
            trace_type="stripline",
            width_mm=width_mm,
            height_mm=height_mm,
            thickness_mm=thickness_mm,
            dielectric_constant=dielectric_constant,
            frequency_hz=freq,
            model_used="cohn_wheeler",
        )

    def coplanar_waveguide(
        self,
        width_mm: float,
        gap_mm: float,
        height_mm: float,
        dielectric_constant: float,
        with_ground: bool = True,
        thickness_mm: float = 0.035,
        loss_tangent: Optional[float] = None,
        frequency_hz: Optional[float] = None,
    ) -> ImpedanceResult:
        """
        Calculate coplanar waveguide impedance.

        Args:
            width_mm: Center conductor width
            gap_mm: Gap between center and ground conductors
            height_mm: Substrate height
            dielectric_constant: Substrate dielectric constant
            with_ground: True for CPWG (with bottom ground), False for CPW
            thickness_mm: Copper thickness
            loss_tangent: Dielectric loss tangent
            frequency_hz: Frequency for loss calculation

        Returns:
            ImpedanceResult
        """
        freq = frequency_hz or self.default_frequency
        tan_d = loss_tangent or self.default_loss_tangent

        # Calculate modulus k for CPW
        a = width_mm / 2
        b = width_mm / 2 + gap_mm
        k0 = a / b
        k0_prime = math.sqrt(1 - k0**2)

        # Elliptic integral ratio approximation
        def elliptic_ratio(k: float) -> float:
            if k < 0.707:
                k_prime = math.sqrt(1 - k**2)
                return math.pi / math.log(2 * (1 + math.sqrt(k_prime)) / (1 - math.sqrt(k_prime)))
            else:
                return math.log(2 * (1 + math.sqrt(k)) / (1 - math.sqrt(k))) / math.pi

        # Effective dielectric
        if with_ground:
            # CPWG - effect of bottom ground plane
            k1 = math.tanh(math.pi * a / (2 * height_mm)) / math.tanh(
                math.pi * b / (2 * height_mm)
            )
            k1_prime = math.sqrt(1 - k1**2)

            q = elliptic_ratio(k0) / elliptic_ratio(k1)
            eps_eff = 1 + (dielectric_constant - 1) / 2 * q
        else:
            # CPW without ground
            eps_eff = (dielectric_constant + 1) / 2

        # Characteristic impedance
        z0 = 30 * math.pi / math.sqrt(eps_eff) * elliptic_ratio(k0)

        # Propagation
        vp = self.C0 / math.sqrt(eps_eff)
        delay_ps_per_mm = 1e12 / (vp * 1000)

        # Loss
        conductor_loss = self._calculate_conductor_loss(
            width_mm, gap_mm, thickness_mm, z0, freq
        ) * 0.8  # CPW typically has lower loss
        dielectric_loss = self._calculate_dielectric_loss(eps_eff, tan_d, freq)

        return ImpedanceResult(
            impedance_ohm=z0,
            effective_dielectric=eps_eff,
            propagation_delay_ps_per_mm=delay_ps_per_mm,
            phase_velocity_mm_per_ns=vp / 1e6,
            conductor_loss_db_per_mm=conductor_loss,
            dielectric_loss_db_per_mm=dielectric_loss,
            total_loss_db_per_mm=conductor_loss + dielectric_loss,
            trace_type="cpw_ground" if with_ground else "cpw",
            width_mm=width_mm,
            height_mm=height_mm,
            thickness_mm=thickness_mm,
            dielectric_constant=dielectric_constant,
            frequency_hz=freq,
            model_used="elliptic_cpw",
        )

    def differential_microstrip(
        self,
        width_mm: float,
        spacing_mm: float,
        height_mm: float,
        dielectric_constant: float,
        thickness_mm: float = 0.035,
        loss_tangent: Optional[float] = None,
        frequency_hz: Optional[float] = None,
    ) -> dict:
        """
        Calculate differential microstrip impedance.

        Args:
            width_mm: Trace width (each trace)
            spacing_mm: Edge-to-edge spacing between traces
            height_mm: Height above ground plane
            dielectric_constant: Substrate dielectric constant
            thickness_mm: Copper thickness
            loss_tangent: Dielectric loss tangent
            frequency_hz: Frequency for loss calculation

        Returns:
            Dictionary with Zodd, Zeven, Zdiff, Zcommon
        """
        # Calculate single-ended impedance
        single = self.microstrip(
            width_mm, height_mm, dielectric_constant, thickness_mm,
            loss_tangent, frequency_hz
        )

        # Coupling coefficient (approximate)
        s_h = spacing_mm / height_mm
        coupling = 0.3 * math.exp(-s_h / 0.4) if s_h < 3 else 0.05

        # Odd and even mode impedances
        z_odd = single.impedance_ohm * (1 - coupling)
        z_even = single.impedance_ohm * (1 + coupling)

        # Differential and common mode
        z_diff = 2 * z_odd
        z_common = z_even / 2

        return {
            "z_single_ohm": single.impedance_ohm,
            "z_odd_ohm": z_odd,
            "z_even_ohm": z_even,
            "z_diff_ohm": z_diff,
            "z_common_ohm": z_common,
            "coupling_coefficient": coupling,
            "effective_dielectric": single.effective_dielectric,
            "propagation_delay_ps_per_mm": single.propagation_delay_ps_per_mm,
        }

    def differential_stripline(
        self,
        width_mm: float,
        spacing_mm: float,
        height_mm: float,
        dielectric_constant: float,
        thickness_mm: float = 0.035,
        loss_tangent: Optional[float] = None,
        frequency_hz: Optional[float] = None,
    ) -> dict:
        """
        Calculate differential stripline impedance.

        Args:
            width_mm: Trace width (each trace)
            spacing_mm: Edge-to-edge spacing
            height_mm: Distance to each ground plane
            dielectric_constant: Substrate dielectric constant
            thickness_mm: Copper thickness
            loss_tangent: Dielectric loss tangent
            frequency_hz: Frequency for loss calculation

        Returns:
            Dictionary with Zodd, Zeven, Zdiff, Zcommon
        """
        # Calculate single-ended stripline
        single = self.stripline(
            width_mm, height_mm, dielectric_constant, thickness_mm,
            loss_tangent, frequency_hz
        )

        # Coupling is stronger in stripline due to being embedded
        s_h = spacing_mm / height_mm
        coupling = 0.4 * math.exp(-s_h / 0.5) if s_h < 3 else 0.08

        # Odd and even mode
        z_odd = single.impedance_ohm * (1 - coupling)
        z_even = single.impedance_ohm * (1 + coupling)

        # Differential and common mode
        z_diff = 2 * z_odd
        z_common = z_even / 2

        return {
            "z_single_ohm": single.impedance_ohm,
            "z_odd_ohm": z_odd,
            "z_even_ohm": z_even,
            "z_diff_ohm": z_diff,
            "z_common_ohm": z_common,
            "coupling_coefficient": coupling,
            "effective_dielectric": single.effective_dielectric,
            "propagation_delay_ps_per_mm": single.propagation_delay_ps_per_mm,
        }

    def _calculate_conductor_loss(
        self,
        width_mm: float,
        height_mm: float,
        thickness_mm: float,
        z0: float,
        frequency_hz: float,
    ) -> float:
        """Calculate conductor loss in dB/mm"""
        # Skin depth
        omega = 2 * math.pi * frequency_hz
        delta = math.sqrt(2 / (omega * self.MU0 * self.copper_conductivity))

        # Surface resistance
        rs = 1 / (self.copper_conductivity * delta)

        # Approximate conductor loss (simplified formula)
        # alpha_c = Rs / (Z0 * w) for thin strips
        width_m = width_mm / 1000

        # dB/m
        alpha_c_db_m = 8.686 * rs / (z0 * width_m)

        # Convert to dB/mm
        return alpha_c_db_m / 1000

    def _calculate_dielectric_loss(
        self,
        effective_dielectric: float,
        loss_tangent: float,
        frequency_hz: float,
    ) -> float:
        """Calculate dielectric loss in dB/mm"""
        # Wavelength in free space
        lambda_0 = self.C0 / frequency_hz * 1000  # mm

        # Dielectric loss factor
        # alpha_d = (pi * sqrt(eps_eff) * tan_d) / lambda_0 [Np/mm]
        alpha_d_np = math.pi * math.sqrt(effective_dielectric) * loss_tangent / lambda_0

        # Convert Np/mm to dB/mm
        return alpha_d_np * 8.686

    def calculate(
        self,
        trace_type: TraceType,
        width_mm: float,
        height_mm: float,
        dielectric_constant: float,
        **kwargs
    ) -> ImpedanceResult:
        """
        Generic calculation method.

        Args:
            trace_type: Type of transmission line
            width_mm: Trace width
            height_mm: Height/distance to reference plane
            dielectric_constant: Substrate Er
            **kwargs: Additional parameters per trace type

        Returns:
            ImpedanceResult
        """
        if trace_type == TraceType.MICROSTRIP:
            return self.microstrip(width_mm, height_mm, dielectric_constant, **kwargs)
        elif trace_type == TraceType.EMBEDDED_MICROSTRIP:
            return self.embedded_microstrip(width_mm, height_mm, **kwargs)
        elif trace_type == TraceType.STRIPLINE:
            return self.stripline(width_mm, height_mm, dielectric_constant, **kwargs)
        elif trace_type == TraceType.COPLANAR_WAVEGUIDE:
            return self.coplanar_waveguide(
                width_mm, kwargs.get("gap_mm", 0.1), height_mm, dielectric_constant,
                with_ground=False, **kwargs
            )
        elif trace_type == TraceType.COPLANAR_WAVEGUIDE_GROUND:
            return self.coplanar_waveguide(
                width_mm, kwargs.get("gap_mm", 0.1), height_mm, dielectric_constant,
                with_ground=True, **kwargs
            )
        else:
            raise ValueError(f"Unknown trace type: {trace_type}")

    def find_width_for_impedance(
        self,
        target_impedance: float,
        height_mm: float,
        dielectric_constant: float,
        trace_type: TraceType = TraceType.MICROSTRIP,
        tolerance: float = 0.1,
        max_iterations: int = 50,
        **kwargs
    ) -> float:
        """
        Find trace width for target impedance using binary search.

        Args:
            target_impedance: Target impedance in ohms
            height_mm: Height above ground plane
            dielectric_constant: Substrate Er
            trace_type: Type of transmission line
            tolerance: Acceptable error in ohms
            max_iterations: Maximum iterations
            **kwargs: Additional parameters for calculation

        Returns:
            Width in mm that achieves target impedance
        """
        # Initial bounds
        w_min = 0.01  # 10 um
        w_max = 10.0  # 10 mm

        for _ in range(max_iterations):
            w_mid = (w_min + w_max) / 2
            result = self.calculate(trace_type, w_mid, height_mm, dielectric_constant, **kwargs)

            if abs(result.impedance_ohm - target_impedance) < tolerance:
                return w_mid

            if result.impedance_ohm > target_impedance:
                # Impedance too high, need wider trace
                w_min = w_mid
            else:
                # Impedance too low, need narrower trace
                w_max = w_mid

        # Return best estimate
        return (w_min + w_max) / 2

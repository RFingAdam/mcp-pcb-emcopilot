"""
Via electrical modeler for PCB signal integrity analysis.

Models via structures as transmission line discontinuities,
calculating impedance, inductance, capacitance, and stub effects.
"""
import math
from dataclasses import dataclass
from typing import Optional, List
from enum import Enum


class ViaType(Enum):
    """Via structure types"""
    THROUGH_HOLE = "through"
    BLIND = "blind"
    BURIED = "buried"
    MICROVIA = "microvia"
    VIA_IN_PAD = "via_in_pad"


@dataclass
class ViaConfig:
    """Configuration for via analysis.

    Attributes:
        drill_diameter_mm: Via drill diameter in mm
        pad_diameter_mm: Via pad diameter in mm
        antipad_diameter_mm: Antipad diameter in mm
        via_length_mm: Via length (stackup height) in mm
    """
    drill_diameter_mm: float
    pad_diameter_mm: float
    antipad_diameter_mm: float = 0.6
    via_length_mm: float = 1.6


@dataclass
class ViaModel:
    """Electrical model of a via"""
    # Physical parameters
    via_type: ViaType
    drill_diameter_mm: float
    pad_diameter_mm: float
    antipad_diameter_mm: float
    barrel_length_mm: float
    stub_length_mm: float

    # Electrical parameters
    inductance_nh: float
    capacitance_pf: float
    resistance_mohm: float
    impedance_ohm: float

    # Derived parameters
    resonant_frequency_ghz: float
    stub_resonance_ghz: Optional[float]

    # Quality metrics
    insertion_loss_db: float
    return_loss_db: float

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "via_type": self.via_type.value,
            "drill_diameter_mm": round(self.drill_diameter_mm, 3),
            "pad_diameter_mm": round(self.pad_diameter_mm, 3),
            "antipad_diameter_mm": round(self.antipad_diameter_mm, 3),
            "barrel_length_mm": round(self.barrel_length_mm, 3),
            "stub_length_mm": round(self.stub_length_mm, 3),
            "inductance_nh": round(self.inductance_nh, 3),
            "capacitance_pf": round(self.capacitance_pf, 4),
            "resistance_mohm": round(self.resistance_mohm, 2),
            "impedance_ohm": round(self.impedance_ohm, 1),
            "resonant_frequency_ghz": round(self.resonant_frequency_ghz, 2),
            "stub_resonance_ghz": round(self.stub_resonance_ghz, 2) if self.stub_resonance_ghz else None,
            "insertion_loss_db": round(self.insertion_loss_db, 3),
            "return_loss_db": round(self.return_loss_db, 2),
        }


@dataclass
class ViaArrayModel:
    """Model for via arrays (e.g., for ground stitching or power delivery)"""
    via_count: int
    array_inductance_nh: float
    array_capacitance_pf: float
    total_resistance_mohm: float
    effective_impedance_ohm: float
    current_capacity_a: float
    thermal_resistance_k_per_w: float


class ViaModeler:
    """
    Via electrical modeler.

    Calculates:
    - Via inductance (barrel + pad)
    - Via capacitance (pad-to-plane)
    - Characteristic impedance
    - Stub resonance
    - Insertion and return loss

    Usage:
        modeler = ViaModeler()
        model = modeler.model_via(
            drill_mm=0.3,
            pad_mm=0.6,
            antipad_mm=0.9,
            stackup_height_mm=1.6,
            dielectric_constant=4.3,
        )
        print(f"Via inductance: {model.inductance_nh:.2f} nH")
    """

    # Physical constants
    MU0 = 4 * math.pi * 1e-7  # H/m
    EPS0 = 8.854187817e-12   # F/m
    C0 = 299792458           # m/s
    COPPER_RESISTIVITY = 1.68e-8  # Ohm*m

    def __init__(
        self,
        default_plating_thickness_um: float = 25,
        default_frequency_ghz: float = 1.0,
    ):
        """
        Initialize modeler.

        Args:
            default_plating_thickness_um: Via barrel plating thickness
            default_frequency_ghz: Default frequency for calculations
        """
        self.plating_thickness = default_plating_thickness_um / 1000  # mm
        self.default_frequency = default_frequency_ghz

    def model_via(
        self,
        drill_mm: float,
        pad_mm: float,
        antipad_mm: float,
        stackup_height_mm: float,
        dielectric_constant: float,
        signal_layer_position: float = 0.0,
        via_type: ViaType = ViaType.THROUGH_HOLE,
        frequency_ghz: Optional[float] = None,
    ) -> ViaModel:
        """
        Create electrical model for a via.

        Args:
            drill_mm: Drill diameter
            pad_mm: Pad diameter
            antipad_mm: Antipad (clearance) diameter
            stackup_height_mm: Total stackup thickness
            dielectric_constant: Average dielectric constant
            signal_layer_position: Position of signal layer from top (0 = top, 1 = bottom)
            via_type: Type of via structure
            frequency_ghz: Analysis frequency

        Returns:
            ViaModel with electrical parameters
        """
        freq = (frequency_ghz or self.default_frequency) * 1e9

        # Calculate via barrel length
        if via_type == ViaType.THROUGH_HOLE:
            barrel_length = stackup_height_mm
            stub_length = stackup_height_mm * (1 - signal_layer_position)
        elif via_type == ViaType.BLIND:
            barrel_length = stackup_height_mm * signal_layer_position
            stub_length = 0
        elif via_type == ViaType.BURIED:
            barrel_length = stackup_height_mm * 0.5  # Approximate
            stub_length = 0
        elif via_type == ViaType.MICROVIA:
            barrel_length = stackup_height_mm * 0.1  # Single layer
            stub_length = 0
        else:
            barrel_length = stackup_height_mm
            stub_length = stackup_height_mm * 0.5

        # Via barrel inductance
        inductance = self._calculate_barrel_inductance(
            drill_mm, barrel_length
        )

        # Pad capacitance
        capacitance = self._calculate_pad_capacitance(
            pad_mm, antipad_mm, dielectric_constant
        )

        # DC resistance
        resistance = self._calculate_barrel_resistance(
            drill_mm, barrel_length
        )

        # Characteristic impedance
        impedance = self._calculate_via_impedance(
            drill_mm, antipad_mm, dielectric_constant
        )

        # Resonant frequency (LC resonance)
        if inductance > 0 and capacitance > 0:
            resonant_freq = 1 / (2 * math.pi * math.sqrt(
                inductance * 1e-9 * capacitance * 1e-12
            ))
            resonant_freq_ghz = resonant_freq / 1e9
        else:
            resonant_freq_ghz = 100  # Very high if no resonance

        # Stub resonance (quarter-wave)
        stub_resonance = None
        if stub_length > 0:
            vp = self.C0 / math.sqrt(dielectric_constant)
            stub_resonance = vp / (4 * stub_length * 1e-3) / 1e9  # GHz

        # Insertion and return loss at specified frequency
        insertion_loss, return_loss = self._calculate_losses(
            inductance, capacitance, impedance, freq
        )

        return ViaModel(
            via_type=via_type,
            drill_diameter_mm=drill_mm,
            pad_diameter_mm=pad_mm,
            antipad_diameter_mm=antipad_mm,
            barrel_length_mm=barrel_length,
            stub_length_mm=stub_length,
            inductance_nh=inductance,
            capacitance_pf=capacitance,
            resistance_mohm=resistance,
            impedance_ohm=impedance,
            resonant_frequency_ghz=resonant_freq_ghz,
            stub_resonance_ghz=stub_resonance,
            insertion_loss_db=insertion_loss,
            return_loss_db=return_loss,
        )

    def _calculate_barrel_inductance(
        self,
        drill_mm: float,
        length_mm: float,
    ) -> float:
        """
        Calculate via barrel inductance in nH.

        Uses simplified formula for cylindrical conductor.
        """
        # Convert to meters
        d = drill_mm / 1000
        l = length_mm / 1000

        # Inductance of a cylindrical conductor
        # L = (mu0 * l / 2pi) * [ln(4l/d) - 1]
        if d > 0 and l > 0:
            L = (self.MU0 * l / (2 * math.pi)) * (math.log(4 * l / d) - 1)
            return L * 1e9  # Convert to nH
        return 0

    def _calculate_pad_capacitance(
        self,
        pad_mm: float,
        antipad_mm: float,
        dielectric_constant: float,
    ) -> float:
        """
        Calculate pad-to-plane capacitance in pF.

        Uses parallel plate approximation with fringing.
        """
        # Convert to meters
        pad_r = pad_mm / 2000
        antipad_r = antipad_mm / 2000

        if antipad_r <= pad_r:
            return 0

        # Coaxial capacitance approximation
        # C = 2*pi*eps*eps0 / ln(antipad/pad)
        C = 2 * math.pi * dielectric_constant * self.EPS0 / math.log(antipad_r / pad_r)

        # This gives C per unit length; multiply by typical layer thickness
        C_per_layer = C * 0.2e-3  # 0.2mm typical layer

        # Convert to pF and account for multiple layers (approximate)
        return C_per_layer * 1e12 * 4  # Approximate 4 layers contributing

    def _calculate_barrel_resistance(
        self,
        drill_mm: float,
        length_mm: float,
    ) -> float:
        """
        Calculate via barrel DC resistance in mOhm.
        """
        # Plated via barrel is a hollow cylinder
        outer_r = drill_mm / 2
        inner_r = outer_r - self.plating_thickness

        if inner_r < 0:
            inner_r = 0

        # Cross-sectional area
        area_mm2 = math.pi * (outer_r**2 - inner_r**2)
        area_m2 = area_mm2 * 1e-6

        # Resistance
        length_m = length_mm / 1000
        R = self.COPPER_RESISTIVITY * length_m / area_m2

        return R * 1000  # Convert to mOhm

    def _calculate_via_impedance(
        self,
        drill_mm: float,
        antipad_mm: float,
        dielectric_constant: float,
    ) -> float:
        """
        Calculate via characteristic impedance.

        Models via as coaxial transmission line.
        """
        if antipad_mm <= drill_mm:
            return 50  # Default

        # Coaxial impedance: Z0 = (60/sqrt(er)) * ln(D/d)
        z0 = (60 / math.sqrt(dielectric_constant)) * math.log(antipad_mm / drill_mm)

        return z0

    def _calculate_losses(
        self,
        inductance_nh: float,
        capacitance_pf: float,
        impedance_ohm: float,
        frequency_hz: float,
    ) -> tuple:
        """
        Calculate insertion and return loss.

        Returns:
            (insertion_loss_db, return_loss_db)
        """
        omega = 2 * math.pi * frequency_hz
        z0 = 50  # Reference impedance

        # Via impedance at frequency
        XL = omega * inductance_nh * 1e-9
        XC = 1 / (omega * capacitance_pf * 1e-12 + 1e-15)

        # Net reactance
        X_net = XL - XC

        # Via impedance (simplified)
        Z_via = complex(0, X_net)

        # Reflection coefficient
        gamma = (Z_via) / (2 * z0 + Z_via)
        S11 = abs(gamma)

        # Transmission coefficient
        S21 = 1 - S11

        # Convert to dB
        return_loss = -20 * math.log10(S11 + 1e-10)
        insertion_loss = -20 * math.log10(S21 + 1e-10)

        return insertion_loss, return_loss

    def model_via_array(
        self,
        via_count: int,
        drill_mm: float,
        pad_mm: float,
        antipad_mm: float,
        stackup_height_mm: float,
        dielectric_constant: float,
        array_pitch_mm: float = 1.0,
    ) -> ViaArrayModel:
        """
        Model an array of vias (e.g., for ground stitching).

        Args:
            via_count: Number of vias in array
            drill_mm: Drill diameter per via
            pad_mm: Pad diameter per via
            antipad_mm: Antipad diameter per via
            stackup_height_mm: Stackup thickness
            dielectric_constant: Dielectric constant
            array_pitch_mm: Via-to-via pitch

        Returns:
            ViaArrayModel with array parameters
        """
        # Model single via
        single_via = self.model_via(
            drill_mm, pad_mm, antipad_mm,
            stackup_height_mm, dielectric_constant
        )

        # Mutual inductance reduction
        # Closely spaced vias reduce inductance
        if via_count > 1 and array_pitch_mm > 0:
            pitch_ratio = array_pitch_mm / stackup_height_mm
            mutual_factor = 1 + 0.3 / pitch_ratio  # Approximate mutual coupling
            parallel_inductance = single_via.inductance_nh / via_count / mutual_factor
        else:
            parallel_inductance = single_via.inductance_nh / via_count

        # Capacitance adds in parallel
        total_capacitance = single_via.capacitance_pf * via_count

        # Resistance in parallel
        total_resistance = single_via.resistance_mohm / via_count

        # Effective impedance
        effective_z = math.sqrt(
            parallel_inductance * 1e-9 / (total_capacitance * 1e-12 + 1e-15)
        )

        # Current capacity (based on via cross-section)
        # Assume 20 A/mm² for copper
        via_area_mm2 = math.pi * (drill_mm / 2) ** 2
        current_capacity = 20 * via_area_mm2 * via_count

        # Thermal resistance (approximate)
        thermal_res = 50 / via_count  # K/W, simplified

        return ViaArrayModel(
            via_count=via_count,
            array_inductance_nh=parallel_inductance,
            array_capacitance_pf=total_capacitance,
            total_resistance_mohm=total_resistance,
            effective_impedance_ohm=effective_z,
            current_capacity_a=current_capacity,
            thermal_resistance_k_per_w=thermal_res,
        )

    def optimize_via(
        self,
        target_impedance: float,
        stackup_height_mm: float,
        dielectric_constant: float,
        min_drill_mm: float = 0.2,
        max_drill_mm: float = 0.6,
    ) -> dict:
        """
        Optimize via dimensions for target impedance.

        Args:
            target_impedance: Target characteristic impedance
            stackup_height_mm: Stackup thickness
            dielectric_constant: Dielectric constant
            min_drill_mm: Minimum drill size
            max_drill_mm: Maximum drill size

        Returns:
            Dictionary with optimized dimensions
        """
        best_drill = min_drill_mm
        best_antipad = min_drill_mm * 2
        best_error = float('inf')

        # Search for optimal dimensions
        for drill in [min_drill_mm + i * 0.05 for i in range(int((max_drill_mm - min_drill_mm) / 0.05) + 1)]:
            for antipad_ratio in [1.5, 2.0, 2.5, 3.0]:
                antipad = drill * antipad_ratio
                pad = drill + 0.3  # Standard annular ring

                model = self.model_via(
                    drill, pad, antipad,
                    stackup_height_mm, dielectric_constant
                )

                error = abs(model.impedance_ohm - target_impedance)
                if error < best_error:
                    best_error = error
                    best_drill = drill
                    best_antipad = antipad

        return {
            "drill_mm": round(best_drill, 2),
            "pad_mm": round(best_drill + 0.3, 2),
            "antipad_mm": round(best_antipad, 2),
            "achieved_impedance_ohm": round(
                self.model_via(
                    best_drill, best_drill + 0.3, best_antipad,
                    stackup_height_mm, dielectric_constant
                ).impedance_ohm, 1
            ),
            "target_impedance_ohm": target_impedance,
        }

    def calculate_stub_effect(
        self,
        stub_length_mm: float,
        dielectric_constant: float,
        max_frequency_ghz: float = 10,
    ) -> dict:
        """
        Calculate via stub resonance effects.

        Args:
            stub_length_mm: Length of via stub
            dielectric_constant: Dielectric constant
            max_frequency_ghz: Maximum frequency of interest

        Returns:
            Dictionary with resonance information
        """
        if stub_length_mm <= 0:
            return {
                "has_resonance": False,
                "message": "No stub present",
            }

        # Phase velocity in dielectric
        vp = self.C0 / math.sqrt(dielectric_constant)

        # Quarter-wave resonances
        resonances = []
        n = 1
        while True:
            # Quarter-wave: f = (2n-1) * v / (4 * L)
            freq = (2 * n - 1) * vp / (4 * stub_length_mm * 1e-3) / 1e9
            if freq > max_frequency_ghz:
                break
            resonances.append({
                "harmonic": n,
                "frequency_ghz": round(freq, 2),
                "type": "quarter-wave null",
            })
            n += 1

        return {
            "has_resonance": len(resonances) > 0,
            "stub_length_mm": stub_length_mm,
            "resonances": resonances,
            "recommendation": self._stub_recommendation(resonances, max_frequency_ghz),
        }

    def _stub_recommendation(
        self,
        resonances: List[dict],
        max_freq_ghz: float,
    ) -> str:
        """Generate recommendation based on stub resonances"""
        if not resonances:
            return "No problematic resonances within frequency range."

        first_resonance = resonances[0]["frequency_ghz"]

        if first_resonance < max_freq_ghz * 0.5:
            return (f"Critical: First stub resonance at {first_resonance:.1f} GHz is within "
                   f"operating bandwidth. Consider back-drilling to reduce stub length.")
        elif first_resonance < max_freq_ghz:
            return (f"Warning: Stub resonance at {first_resonance:.1f} GHz may affect "
                   f"high-frequency performance. Monitor insertion loss at this frequency.")
        else:
            return "Stub resonance is above primary operating frequency."

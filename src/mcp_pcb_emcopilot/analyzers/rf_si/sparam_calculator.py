"""
Analytical S-parameter calculator for PCB traces and vias.

Uses ABCD matrix cascading with scikit-rf to calculate frequency-dependent
S-parameters from trace geometry without FDTD simulation.
"""
import math
import cmath
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, List
import re

try:
    import skrf as rf
except ImportError:
    rf = None

from .impedance_calculator import ImpedanceCalculator
from .via_modeler import ViaModeler


@dataclass
class SParameterResult:
    """Result of S-parameter calculation for a trace/net."""
    frequencies_hz: List[float]
    s11_db: List[float]
    s21_db: List[float]
    s11_phase_deg: List[float]
    s21_phase_deg: List[float]
    s12_db: List[float] = field(default_factory=list)
    s22_db: List[float] = field(default_factory=list)
    s12_phase_deg: List[float] = field(default_factory=list)
    s22_phase_deg: List[float] = field(default_factory=list)
    z0_ohm: float = 50.0
    interface_type: str = "single_trace"
    net_name: str = ""

    @property
    def frequencies_ghz(self) -> List[float]:
        return [f / 1e9 for f in self.frequencies_hz]

    @property
    def return_loss_min_db(self) -> float:
        """Minimum return loss (worst case, highest S11)."""
        return max(self.s11_db) if self.s11_db else 0

    @property
    def insertion_loss_max_db(self) -> float:
        """Maximum insertion loss (worst case, lowest S21)."""
        return min(self.s21_db) if self.s21_db else 0

    @property
    def bandwidth_3db_hz(self) -> Optional[float]:
        """Bandwidth where S21 is within 3dB of maximum."""
        if not self.s21_db or len(self.s21_db) < 2:
            return None
        max_s21 = max(self.s21_db)
        threshold = max_s21 - 3.0
        # Find frequency range where S21 > threshold
        in_band = [f for f, s in zip(self.frequencies_hz, self.s21_db) if s > threshold]
        if in_band:
            return max(in_band) - min(in_band)
        return None

    def to_dict(self) -> dict:
        return {
            "frequencies_hz": self.frequencies_hz,
            "frequencies_ghz": self.frequencies_ghz,
            "s11_db": [round(x, 3) for x in self.s11_db],
            "s21_db": [round(x, 3) for x in self.s21_db],
            "s11_phase_deg": [round(x, 1) for x in self.s11_phase_deg],
            "s21_phase_deg": [round(x, 1) for x in self.s21_phase_deg],
            "z0_ohm": self.z0_ohm,
            "interface_type": self.interface_type,
            "net_name": self.net_name,
            "return_loss_min_db": round(self.return_loss_min_db, 2),
            "insertion_loss_max_db": round(self.insertion_loss_max_db, 2),
            "bandwidth_3db_hz": self.bandwidth_3db_hz,
        }


@dataclass
class InterfaceSParamResult:
    """S-parameter results for a high-speed interface."""
    interface_type: str
    confidence: float
    nets: List[str]
    frequency_range_hz: tuple
    target_impedance_ohm: float
    results: dict  # net_name -> SParameterResult
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "interface_type": self.interface_type,
            "confidence": round(self.confidence, 2),
            "nets": self.nets,
            "frequency_range_hz": list(self.frequency_range_hz),
            "target_impedance_ohm": self.target_impedance_ohm,
            "results": {k: v.to_dict() for k, v in self.results.items()},
            "summary": self.summary,
        }


class SParameterCalculator:
    """
    Analytical S-parameter calculator using ABCD matrix cascading.

    Calculates frequency-dependent S-parameters from PCB trace geometry
    without requiring FDTD simulation (like OpenEMS).

    Uses:
    - ImpedanceCalculator for Z0, effective dielectric, and loss
    - ViaModeler for via L and C parameters
    - ABCD matrix cascading for element combination
    - scikit-rf for ABCD to S-parameter conversion

    Usage:
        calc = SParameterCalculator()
        result = calc.calculate_trace_sparam(
            width_mm=0.15,
            length_mm=50.0,
            height_mm=0.2,
            dielectric_constant=4.3,
            frequencies_hz=np.linspace(1e6, 6e9, 201),
        )
    """

    # Physical constants
    C0 = 299792458e3  # Speed of light in mm/s
    MU0 = 4 * math.pi * 1e-7

    def __init__(self, reference_impedance: float = 50.0):
        """
        Initialize calculator.

        Args:
            reference_impedance: Reference impedance for S-parameters (typically 50 ohm)
        """
        self.z0_ref = reference_impedance
        self.impedance_calc = ImpedanceCalculator()
        self.via_modeler = ViaModeler()

    def calculate_trace_sparam(
        self,
        width_mm: float,
        length_mm: float,
        height_mm: float,
        dielectric_constant: float,
        frequencies_hz: List[float],
        loss_tangent: float = 0.02,
        thickness_mm: float = 0.035,
        trace_type: str = "microstrip",
        interface_type: str = "single_trace",
        net_name: str = "",
    ) -> SParameterResult:
        """
        Calculate S-parameters for a single trace.

        Args:
            width_mm: Trace width
            length_mm: Trace length
            height_mm: Height above reference plane
            dielectric_constant: Substrate dielectric constant
            frequencies_hz: List of frequencies for calculation
            loss_tangent: Dielectric loss tangent
            thickness_mm: Copper thickness
            trace_type: "microstrip" or "stripline"
            interface_type: Interface classification
            net_name: Name of the net

        Returns:
            SParameterResult with frequency-dependent S-parameters
        """
        s11_db = []
        s21_db = []
        s11_phase = []
        s21_phase = []
        calculated_z0 = 50.0

        for freq in frequencies_hz:
            # Get impedance and loss at this frequency
            if trace_type == "stripline":
                imp_result = self.impedance_calc.stripline(
                    width_mm=width_mm,
                    height_mm=height_mm,
                    dielectric_constant=dielectric_constant,
                    thickness_mm=thickness_mm,
                    loss_tangent=loss_tangent,
                    frequency_hz=freq,
                )
            else:
                imp_result = self.impedance_calc.microstrip(
                    width_mm=width_mm,
                    height_mm=height_mm,
                    dielectric_constant=dielectric_constant,
                    thickness_mm=thickness_mm,
                    loss_tangent=loss_tangent,
                    frequency_hz=freq,
                )

            calculated_z0 = imp_result.impedance_ohm

            # Calculate ABCD matrix for this trace at this frequency
            abcd = self._trace_to_abcd(
                z0=imp_result.impedance_ohm,
                eps_eff=imp_result.effective_dielectric,
                loss_db_per_mm=imp_result.total_loss_db_per_mm,
                length_mm=length_mm,
                frequency_hz=freq,
            )

            # Convert ABCD to S-parameters
            s_matrix = self._abcd_to_s(abcd, self.z0_ref)

            # Extract S11 and S21
            s11 = s_matrix[0, 0]
            s21 = s_matrix[1, 0]

            s11_db.append(20 * math.log10(abs(s11) + 1e-15))
            s21_db.append(20 * math.log10(abs(s21) + 1e-15))
            s11_phase.append(math.degrees(cmath.phase(s11)))
            s21_phase.append(math.degrees(cmath.phase(s21)))

        return SParameterResult(
            frequencies_hz=list(frequencies_hz),
            s11_db=s11_db,
            s21_db=s21_db,
            s11_phase_deg=s11_phase,
            s21_phase_deg=s21_phase,
            s12_db=s21_db.copy(),  # Reciprocal
            s22_db=s11_db.copy(),  # Symmetric
            s12_phase_deg=s21_phase.copy(),
            s22_phase_deg=s11_phase.copy(),
            z0_ohm=calculated_z0,
            interface_type=interface_type,
            net_name=net_name,
        )

    def calculate_trace_with_vias(
        self,
        trace_segments: List[dict],
        vias: List[dict],
        stackup_height_mm: float,
        dielectric_constant: float,
        frequencies_hz: List[float],
        loss_tangent: float = 0.02,
        interface_type: str = "net",
        net_name: str = "",
    ) -> SParameterResult:
        """
        Calculate S-parameters for traces with via transitions.

        Args:
            trace_segments: List of trace dicts with width_mm, length_mm, height_mm, type
            vias: List of via dicts with drill_mm, pad_mm, antipad_mm
            stackup_height_mm: Total stackup thickness
            dielectric_constant: Substrate dielectric constant
            frequencies_hz: List of frequencies
            loss_tangent: Dielectric loss tangent
            interface_type: Interface classification
            net_name: Net name

        Returns:
            SParameterResult for the cascaded structure
        """
        s11_db = []
        s21_db = []
        s11_phase = []
        s21_phase = []

        for freq in frequencies_hz:
            # Cascade all elements
            abcd_total = np.eye(2, dtype=complex)

            # Interleave traces and vias
            for i, segment in enumerate(trace_segments):
                # Add trace segment
                if segment.get("type") == "stripline":
                    imp_result = self.impedance_calc.stripline(
                        width_mm=segment["width_mm"],
                        height_mm=segment["height_mm"],
                        dielectric_constant=dielectric_constant,
                        thickness_mm=segment.get("thickness_mm", 0.035),
                        loss_tangent=loss_tangent,
                        frequency_hz=freq,
                    )
                else:
                    imp_result = self.impedance_calc.microstrip(
                        width_mm=segment["width_mm"],
                        height_mm=segment["height_mm"],
                        dielectric_constant=dielectric_constant,
                        thickness_mm=segment.get("thickness_mm", 0.035),
                        loss_tangent=loss_tangent,
                        frequency_hz=freq,
                    )

                abcd_trace = self._trace_to_abcd(
                    z0=imp_result.impedance_ohm,
                    eps_eff=imp_result.effective_dielectric,
                    loss_db_per_mm=imp_result.total_loss_db_per_mm,
                    length_mm=segment["length_mm"],
                    frequency_hz=freq,
                )
                abcd_total = abcd_total @ abcd_trace

                # Add via after this segment (if there's one)
                if i < len(vias):
                    via = vias[i]
                    abcd_via = self._via_to_abcd(
                        drill_mm=via["drill_mm"],
                        pad_mm=via.get("pad_mm", via["drill_mm"] + 0.3),
                        antipad_mm=via.get("antipad_mm", via["drill_mm"] * 2),
                        stackup_height_mm=stackup_height_mm,
                        dielectric_constant=dielectric_constant,
                        frequency_hz=freq,
                    )
                    abcd_total = abcd_total @ abcd_via

            # Convert to S-parameters
            s_matrix = self._abcd_to_s(abcd_total, self.z0_ref)

            s11 = s_matrix[0, 0]
            s21 = s_matrix[1, 0]

            s11_db.append(20 * math.log10(abs(s11) + 1e-15))
            s21_db.append(20 * math.log10(abs(s21) + 1e-15))
            s11_phase.append(math.degrees(cmath.phase(s11)))
            s21_phase.append(math.degrees(cmath.phase(s21)))

        return SParameterResult(
            frequencies_hz=list(frequencies_hz),
            s11_db=s11_db,
            s21_db=s21_db,
            s11_phase_deg=s11_phase,
            s21_phase_deg=s21_phase,
            s12_db=s21_db.copy(),
            s22_db=s11_db.copy(),
            s12_phase_deg=s21_phase.copy(),
            s22_phase_deg=s11_phase.copy(),
            z0_ohm=self.z0_ref,
            interface_type=interface_type,
            net_name=net_name,
        )

    def _trace_to_abcd(
        self,
        z0: float,
        eps_eff: float,
        loss_db_per_mm: float,
        length_mm: float,
        frequency_hz: float,
    ) -> np.ndarray:
        """
        Calculate ABCD matrix for a transmission line segment.

        ABCD matrix for lossy transmission line:
        [A B] = [cosh(γl)      Z0*sinh(γl)]
        [C D]   [sinh(γl)/Z0   cosh(γl)   ]

        where γ = α + jβ is the propagation constant
        """
        # Attenuation constant (Np/mm from dB/mm)
        alpha = loss_db_per_mm / 8.686

        # Phase constant
        wavelength = self.C0 / (frequency_hz * math.sqrt(eps_eff))
        beta = 2 * math.pi / wavelength  # rad/mm

        # Propagation constant
        gamma = complex(alpha, beta)

        # ABCD matrix elements
        gl = gamma * length_mm
        cosh_gl = cmath.cosh(gl)
        sinh_gl = cmath.sinh(gl)

        A = cosh_gl
        B = z0 * sinh_gl
        C = sinh_gl / z0
        D = cosh_gl

        return np.array([[A, B], [C, D]], dtype=complex)

    def _via_to_abcd(
        self,
        drill_mm: float,
        pad_mm: float,
        antipad_mm: float,
        stackup_height_mm: float,
        dielectric_constant: float,
        frequency_hz: float,
    ) -> np.ndarray:
        """
        Calculate ABCD matrix for a via.

        Via model: Series inductor + shunt capacitor
        ABCD_via = ABCD_L @ ABCD_C

        ABCD_L = [1, jωL; 0, 1]  (series L)
        ABCD_C = [1, 0; jωC, 1]  (shunt C)
        """
        # Get via model
        via_model = self.via_modeler.model_via(
            drill_mm=drill_mm,
            pad_mm=pad_mm,
            antipad_mm=antipad_mm,
            stackup_height_mm=stackup_height_mm,
            dielectric_constant=dielectric_constant,
            frequency_ghz=frequency_hz / 1e9,
        )

        omega = 2 * math.pi * frequency_hz
        L = via_model.inductance_nh * 1e-9  # H
        C = via_model.capacitance_pf * 1e-12  # F

        # Series L
        abcd_L = np.array([[1, 1j * omega * L], [0, 1]], dtype=complex)

        # Shunt C
        abcd_C = np.array([[1, 0], [1j * omega * C, 1]], dtype=complex)

        # Cascade
        return abcd_L @ abcd_C

    def _abcd_to_s(self, abcd: np.ndarray, z0: float = 50.0) -> np.ndarray:
        """
        Convert ABCD matrix to S-parameter matrix.

        S11 = (A + B/Z0 - C*Z0 - D) / (A + B/Z0 + C*Z0 + D)
        S21 = 2 / (A + B/Z0 + C*Z0 + D)
        S12 = 2 / (A + B/Z0 + C*Z0 + D)  (reciprocal)
        S22 = (-A + B/Z0 - C*Z0 + D) / (A + B/Z0 + C*Z0 + D)
        """
        A, B = abcd[0, 0], abcd[0, 1]
        C, D = abcd[1, 0], abcd[1, 1]

        denom = A + B / z0 + C * z0 + D

        s11 = (A + B / z0 - C * z0 - D) / denom
        s21 = 2 / denom
        s12 = 2 / denom
        s22 = (-A + B / z0 - C * z0 + D) / denom

        return np.array([[s11, s12], [s21, s22]], dtype=complex)


class HighSpeedInterfaceDetector:
    """
    Detects high-speed interfaces from net names using pattern matching.
    """

    # Interface patterns and specifications
    INTERFACE_SPECS = {
        "ddr4": {
            "patterns": [
                r"DQ\d+", r"DQS\d*[PN]?", r"DM\d+", r"DDR.*CLK",
                r"DDR.*ADDR", r"DDR.*CMD", r"DDR.*BA\d*",
            ],
            "freq_range": (100e6, 4e9),
            "z0_target": 40,
            "description": "DDR4 Memory Interface",
        },
        "ddr5": {
            "patterns": [
                r"DDR5.*DQ", r"DDR5.*DQS", r"DDR5.*CLK",
            ],
            "freq_range": (100e6, 6e9),
            "z0_target": 40,
            "description": "DDR5 Memory Interface",
        },
        "lpddr4": {
            "patterns": [
                r"LPDDR.*DQ", r"LPDDR.*DQS", r"LPDDR.*CLK",
            ],
            "freq_range": (100e6, 4e9),
            "z0_target": 40,
            "description": "LPDDR4 Memory Interface",
        },
        "usb2": {
            "patterns": [
                r"D\+", r"D-", r"USB.*D[PM]", r"USB2.*D[PM]",
            ],
            "freq_range": (1e6, 1e9),
            "z0_target": 90,
            "description": "USB 2.0 (480 Mbps)",
        },
        "usb3": {
            "patterns": [
                r"SSTX[PN]?", r"SSRX[PN]?", r"USB3.*TX", r"USB3.*RX",
                r"SS[TR]X[+-]?",
            ],
            "freq_range": (100e6, 12e9),
            "z0_target": 85,
            "description": "USB 3.x SuperSpeed",
        },
        "pcie_gen3": {
            "patterns": [
                r"PET\d*[PN]?", r"PER\d*[PN]?", r"PCIE.*TX", r"PCIE.*RX",
                r"PCIE_TX", r"PCIE_RX",
            ],
            "freq_range": (100e6, 8e9),
            "z0_target": 85,
            "description": "PCIe Gen3 (8 GT/s)",
        },
        "pcie_gen4": {
            "patterns": [
                r"PCIE.*GEN4", r"PCIE4.*TX", r"PCIE4.*RX",
            ],
            "freq_range": (100e6, 16e9),
            "z0_target": 85,
            "description": "PCIe Gen4 (16 GT/s)",
        },
        "ethernet_1g": {
            "patterns": [
                r"MDI\d*[PN]?", r"ETH.*[TR]X", r"RGMII.*",
                r"SGMII.*", r"ETH_[TR]X",
            ],
            "freq_range": (1e6, 500e6),
            "z0_target": 100,
            "description": "Gigabit Ethernet",
        },
        "ethernet_10g": {
            "patterns": [
                r"XFI.*", r"SFP.*", r"10G.*TX", r"10G.*RX",
            ],
            "freq_range": (100e6, 12e9),
            "z0_target": 100,
            "description": "10 Gigabit Ethernet",
        },
        "hdmi": {
            "patterns": [
                r"HDMI.*D\d", r"HDMI.*CLK", r"TMDS.*",
            ],
            "freq_range": (100e6, 6e9),
            "z0_target": 100,
            "description": "HDMI/TMDS",
        },
        "displayport": {
            "patterns": [
                r"DP.*TX", r"DP.*RX", r"DPTX", r"DPRX", r"AUX[PN]",
            ],
            "freq_range": (100e6, 8e9),
            "z0_target": 100,
            "description": "DisplayPort",
        },
        "sata": {
            "patterns": [
                r"SATA.*TX", r"SATA.*RX", r"SATA[TR]X",
            ],
            "freq_range": (100e6, 6e9),
            "z0_target": 85,
            "description": "SATA",
        },
    }

    def detect_interfaces(self, net_names: List[str]) -> List[dict]:
        """
        Detect high-speed interfaces from net names.

        Args:
            net_names: List of net names from PCB

        Returns:
            List of detected interfaces with matched nets
        """
        detected = []

        for iface_type, spec in self.INTERFACE_SPECS.items():
            matched_nets = []
            for net in net_names:
                for pattern in spec["patterns"]:
                    if re.search(pattern, net, re.IGNORECASE):
                        matched_nets.append(net)
                        break

            if matched_nets:
                # Calculate confidence based on number of matches
                expected_min = 2
                confidence = min(1.0, len(matched_nets) / expected_min)

                detected.append({
                    "type": iface_type,
                    "description": spec["description"],
                    "confidence": confidence,
                    "nets": list(set(matched_nets)),
                    "frequency_range_hz": spec["freq_range"],
                    "target_impedance_ohm": spec["z0_target"],
                })

        # Sort by confidence
        detected.sort(key=lambda x: x["confidence"], reverse=True)
        return detected

    def get_interface_spec(self, interface_type: str) -> Optional[dict]:
        """Get specification for an interface type."""
        return self.INTERFACE_SPECS.get(interface_type)

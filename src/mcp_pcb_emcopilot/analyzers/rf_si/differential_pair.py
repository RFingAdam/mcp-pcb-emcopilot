"""Differential pair analyzer for skew, mode conversion, and impedance analysis"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import math


@dataclass
class DiffPairResult:
    """Results from differential pair analysis"""
    # Pair identification
    pair_name: str
    positive_net: str
    negative_net: str

    # Impedance
    z_diff_ohms: float  # Differential impedance
    z_common_ohms: float  # Common mode impedance
    z_odd_ohms: float  # Odd mode impedance
    z_even_ohms: float  # Even mode impedance

    # Coupling
    coupling_coefficient: float  # k
    coupling_factor_db: float

    # Timing
    skew_ps: float  # Intra-pair skew
    skew_percent: float  # Skew as % of bit period
    delay_ps_per_mm: float  # Propagation delay

    # Length
    length_mm: float  # Average length
    length_mismatch_mm: float  # Length difference

    # Mode conversion
    differential_to_common_db: float  # Sdd to Scc
    common_to_differential_db: float  # Scc to Sdd
    mode_conversion_risk: str  # low, medium, high

    # Quality assessment
    quality_score: float  # 0-100
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    # Detailed metrics
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceGeometry:
    """Geometry definition for a single trace"""
    width_mm: float
    thickness_mm: float = 0.035  # 1oz copper default
    length_mm: float = 0  # Total routed length
    layer: int = 1
    via_count: int = 0


@dataclass
class DiffPairGeometry:
    """Geometry definition for differential pair"""
    positive_trace: TraceGeometry
    negative_trace: TraceGeometry
    spacing_mm: float  # Edge-to-edge spacing
    height_mm: float  # Height above reference plane
    dielectric_constant: float = 4.3
    configuration: str = "edge_coupled"  # edge_coupled, broadside_coupled


class DifferentialPairAnalyzer:
    """
    Differential pair analyzer for signal integrity.

    Analyzes differential pairs for:
    - Differential and common mode impedance
    - Intra-pair skew and timing
    - Mode conversion
    - Coupling quality

    Methods follow IPC-2141 and industry best practices.
    """

    # Speed of light in vacuum (mm/ps)
    C0_MM_PS = 0.2998

    # Standard differential impedance targets
    STANDARD_ZDIFF = {
        "usb2": 90.0,
        "usb3": 90.0,
        "hdmi": 100.0,
        "displayport": 100.0,
        "pcie_gen3": 85.0,
        "pcie_gen4": 85.0,
        "pcie_gen5": 85.0,
        "sata": 100.0,
        "ethernet_1g": 100.0,
        "ethernet_10g": 100.0,
        "ddr4": 80.0,
        "ddr5": 80.0,
        "lvds": 100.0,
        "mipi_dsi": 100.0,
        "mipi_csi": 100.0,
    }

    # Maximum skew limits (ps) by interface
    SKEW_LIMITS = {
        "usb2": 100,
        "usb3": 15,
        "hdmi_1.4": 20,
        "hdmi_2.0": 10,
        "displayport": 20,
        "pcie_gen3": 5,
        "pcie_gen4": 3,
        "pcie_gen5": 2,
        "sata": 20,
        "ethernet_1g": 50,
        "ethernet_10g": 10,
        "ddr4": 5,
        "ddr5": 3,
        "lvds": 50,
        "mipi_dsi": 15,
        "mipi_csi": 15,
    }

    def __init__(self):
        pass

    def analyze_diff_pair(
        self,
        geometry: DiffPairGeometry,
        pair_name: str = "DP1",
        interface_type: Optional[str] = None,
        data_rate_gbps: Optional[float] = None,
    ) -> DiffPairResult:
        """
        Analyze a differential pair.

        Args:
            geometry: Differential pair geometry
            pair_name: Name for this pair
            interface_type: Interface type (usb3, pcie_gen4, etc.)
            data_rate_gbps: Data rate in Gbps

        Returns:
            DiffPairResult with complete analysis
        """
        # Calculate impedances
        z_odd, z_even = self._calculate_mode_impedances(geometry)
        z_diff = 2 * z_odd
        z_common = z_even / 2

        # Calculate coupling
        k = (z_even - z_odd) / (z_even + z_odd)
        coupling_db = 20 * math.log10(abs(k)) if k > 0 else -60

        # Calculate timing
        prop_delay = self._calculate_propagation_delay(geometry)
        avg_length = (
            geometry.positive_trace.length_mm + geometry.negative_trace.length_mm
        ) / 2
        length_mismatch = abs(
            geometry.positive_trace.length_mm - geometry.negative_trace.length_mm
        )
        skew_ps = length_mismatch * prop_delay

        # Calculate skew percentage
        if data_rate_gbps:
            bit_period_ps = 1000 / data_rate_gbps  # ps
            skew_percent = (skew_ps / bit_period_ps) * 100
        else:
            skew_percent = 0

        # Calculate mode conversion
        dc_to_cm, cm_to_dc = self._calculate_mode_conversion(geometry, z_odd, z_even)

        # Assess mode conversion risk
        if dc_to_cm > -20:
            mode_risk = "high"
        elif dc_to_cm > -30:
            mode_risk = "medium"
        else:
            mode_risk = "low"

        # Quality assessment
        issues = []
        recommendations = []
        quality_score = 100.0

        # Check impedance
        target_z = None
        if interface_type and interface_type.lower() in self.STANDARD_ZDIFF:
            target_z = self.STANDARD_ZDIFF[interface_type.lower()]
            z_error = abs(z_diff - target_z) / target_z * 100
            if z_error > 10:
                issues.append(f"Impedance {z_diff:.1f}Ω deviates {z_error:.1f}% from {target_z}Ω target")
                quality_score -= min(20, z_error)
                recommendations.append(f"Adjust trace width or spacing for {target_z}Ω differential")
            elif z_error > 5:
                issues.append(f"Impedance {z_diff:.1f}Ω slightly off from {target_z}Ω target")
                quality_score -= z_error

        # Check skew
        skew_limit = None
        if interface_type and interface_type.lower() in self.SKEW_LIMITS:
            skew_limit = self.SKEW_LIMITS[interface_type.lower()]
            if skew_ps > skew_limit:
                issues.append(f"Skew {skew_ps:.1f}ps exceeds {skew_limit}ps limit for {interface_type}")
                quality_score -= min(30, (skew_ps / skew_limit - 1) * 30)
                recommendations.append(f"Reduce length mismatch to <{skew_limit/prop_delay:.2f}mm")

        # Check coupling
        if k < 0.1:
            issues.append("Weak coupling - traces may be too far apart")
            quality_score -= 10
            recommendations.append("Reduce spacing between differential traces")
        elif k > 0.5:
            issues.append("Very tight coupling - may cause manufacturing issues")
            quality_score -= 5

        # Check mode conversion
        if mode_risk == "high":
            issues.append("High mode conversion risk - EMI concerns")
            quality_score -= 15
            recommendations.append("Improve symmetry and reduce length mismatch")
        elif mode_risk == "medium":
            quality_score -= 5

        # Via penalty
        via_diff = abs(
            geometry.positive_trace.via_count - geometry.negative_trace.via_count
        )
        if via_diff > 0:
            issues.append(f"Via count mismatch: {via_diff} via(s) difference")
            quality_score -= via_diff * 3
            recommendations.append("Use equal number of vias in both traces")

        quality_score = max(0, quality_score)

        return DiffPairResult(
            pair_name=pair_name,
            positive_net=f"{pair_name}_P",
            negative_net=f"{pair_name}_N",
            z_diff_ohms=round(z_diff, 2),
            z_common_ohms=round(z_common, 2),
            z_odd_ohms=round(z_odd, 2),
            z_even_ohms=round(z_even, 2),
            coupling_coefficient=round(k, 4),
            coupling_factor_db=round(coupling_db, 2),
            skew_ps=round(skew_ps, 2),
            skew_percent=round(skew_percent, 2),
            delay_ps_per_mm=round(prop_delay, 3),
            length_mm=round(avg_length, 3),
            length_mismatch_mm=round(length_mismatch, 4),
            differential_to_common_db=round(dc_to_cm, 2),
            common_to_differential_db=round(cm_to_dc, 2),
            mode_conversion_risk=mode_risk,
            quality_score=round(quality_score, 1),
            issues=issues,
            recommendations=recommendations,
            metrics={
                "target_impedance": target_z,
                "skew_limit_ps": skew_limit,
                "interface_type": interface_type,
                "data_rate_gbps": data_rate_gbps,
                "effective_er": self._effective_er(geometry),
            },
        )

    def _calculate_mode_impedances(
        self, geometry: DiffPairGeometry
    ) -> Tuple[float, float]:
        """
        Calculate odd and even mode impedances.

        Returns:
            (z_odd, z_even) in ohms
        """
        w = geometry.positive_trace.width_mm
        t = geometry.positive_trace.thickness_mm
        h = geometry.height_mm
        s = geometry.spacing_mm
        er = geometry.dielectric_constant

        # Effective dielectric constant for microstrip
        u = w / h
        a = 1 + (1/49) * math.log((u**4 + (u/52)**2) / (u**4 + 0.432)) + \
            (1/18.7) * math.log(1 + (u/18.1)**3)
        b = 0.564 * ((er - 0.9) / (er + 3))**0.053
        er_eff = (er + 1) / 2 + ((er - 1) / 2) * (1 + 10/u)**(-a*b)

        # Single-ended impedance (Hammerstad-Jensen)
        f_u = 6 + (2 * math.pi - 6) * math.exp(-(30.666 / u)**0.7528)
        z0_single = (60 / math.sqrt(er_eff)) * math.log(f_u / u + math.sqrt(1 + (2/u)**2))

        # Coupling factor
        g = s / h

        # Odd mode impedance (tighter coupling = lower Z)
        if g < 0.1:
            g = 0.1  # Minimum spacing limit

        # Odd mode correction factor
        q1 = 0.8695 * u**0.194
        q2 = 1 + 0.7519 * g + 0.189 * g**2.31
        q3 = 0.1975 + (16.6 + (8.4/g)**6)**(-0.387) + (1/241) * math.log(g**10 / (1 + (g/3.4)**10))
        q4 = (2 * q1 / q2) * (math.exp(-g) * u**q3 + (2 - math.exp(-g)) * u**(-q3))

        # Odd mode effective dielectric
        ao = 0.7287 * (er_eff - (er + 1) / 2) * (1 - math.exp(-0.179 * u))
        bo = 0.747 * er / (0.15 + er)
        co = bo - (bo - 0.207) * math.exp(-0.414 * u)
        do = 0.593 + 0.694 * math.exp(-0.562 * u)
        er_eff_o = ((0.5 * (er + 1) + ao - er_eff) * math.exp(-co * g**do) + er_eff)

        z_odd = z0_single * (math.sqrt(er_eff / er_eff_o) / (1 - q4 * math.sqrt(er_eff) / z0_single / 377))

        # Even mode impedance (tighter coupling = higher Z)
        q5 = 1.794 + 1.14 * math.log(1 + 0.638 / (g + 0.517 * g**2.43))
        q6 = 0.2305 + (1/281.3) * math.log(g**10 / (1 + (g/5.8)**10)) + (1/5.1) * math.log(1 + 0.598 * g**1.154)
        q7 = (10 + 190 * g**2) / (1 + 82.3 * g**3)
        q8 = math.exp(-6.5 - 0.95 * math.log(g) - (g/0.15)**5)
        q9 = math.log(q7) * (q8 + 1/16.5)
        q10 = (1/q2) * (q2 * q4 - q5 * math.exp(math.log(u) * q6 * u**(-q9)))

        # Even mode effective dielectric
        ae = 1 + (1/49) * math.log((u**4 + (u/52)**2) / (u**4 + 0.432)) + \
             (1/18.7) * math.log(1 + (u/18.1)**3)
        be = 0.564 * ((er - 0.9) / (er + 3))**0.053
        er_eff_e = (0.5 * (er + 1) + ae * be * (er - 1) / 2)

        z_even = z0_single * (math.sqrt(er_eff / er_eff_e) / (1 - q10 * math.sqrt(er_eff) / z0_single / 377))

        # Ensure physical reasonableness
        z_odd = max(20, min(z_odd, 150))
        z_even = max(z_odd + 5, min(z_even, 200))

        return z_odd, z_even

    def _calculate_propagation_delay(self, geometry: DiffPairGeometry) -> float:
        """
        Calculate propagation delay in ps/mm.
        """
        er_eff = self._effective_er(geometry)
        # delay = sqrt(er_eff) / c
        delay_ps_per_mm = math.sqrt(er_eff) / self.C0_MM_PS
        return delay_ps_per_mm

    def _effective_er(self, geometry: DiffPairGeometry) -> float:
        """Calculate effective dielectric constant."""
        w = geometry.positive_trace.width_mm
        h = geometry.height_mm
        er = geometry.dielectric_constant

        u = w / h
        a = 1 + (1/49) * math.log((u**4 + (u/52)**2) / (u**4 + 0.432)) + \
            (1/18.7) * math.log(1 + (u/18.1)**3)
        b = 0.564 * ((er - 0.9) / (er + 3))**0.053
        er_eff = (er + 1) / 2 + ((er - 1) / 2) * (1 + 10/u)**(-a*b)
        return er_eff  # type: ignore[no-any-return]

    def _calculate_mode_conversion(
        self, geometry: DiffPairGeometry, z_odd: float, z_even: float
    ) -> Tuple[float, float]:
        """
        Calculate mode conversion (differential to common and vice versa).

        Returns:
            (Sdc in dB, Scd in dB)
        """
        # Mode conversion depends on asymmetry
        length_diff = abs(
            geometry.positive_trace.length_mm - geometry.negative_trace.length_mm
        )
        width_diff = abs(
            geometry.positive_trace.width_mm - geometry.negative_trace.width_mm
        )

        # Asymmetry factor
        avg_length = (
            geometry.positive_trace.length_mm + geometry.negative_trace.length_mm
        ) / 2
        if avg_length > 0:
            length_asymmetry = length_diff / avg_length
        else:
            length_asymmetry = 0

        avg_width = (
            geometry.positive_trace.width_mm + geometry.negative_trace.width_mm
        ) / 2
        if avg_width > 0:
            width_asymmetry = width_diff / avg_width
        else:
            width_asymmetry = 0

        # Via asymmetry
        via_diff = abs(
            geometry.positive_trace.via_count - geometry.negative_trace.via_count
        )

        # Estimate mode conversion (simplified model)
        # Perfect symmetry = -infinity dB, bad asymmetry = close to 0 dB
        asymmetry_factor = length_asymmetry + width_asymmetry + via_diff * 0.05

        if asymmetry_factor < 0.001:
            dc_to_cm = -60.0  # Excellent
        elif asymmetry_factor < 0.01:
            dc_to_cm = -40 - 20 * (0.01 - asymmetry_factor) / 0.01
        elif asymmetry_factor < 0.1:
            dc_to_cm = -30 - 10 * (0.1 - asymmetry_factor) / 0.1
        else:
            dc_to_cm = max(-30, -10 * math.log10(asymmetry_factor + 0.001))

        # Common to differential is typically similar
        cm_to_dc = dc_to_cm

        return dc_to_cm, cm_to_dc

    def find_optimal_geometry(
        self,
        target_z_diff: float,
        height_mm: float,
        dielectric_constant: float,
        min_width_mm: float = 0.1,
        max_width_mm: float = 0.5,
        min_spacing_mm: float = 0.1,
        max_spacing_mm: float = 0.5,
        copper_thickness_mm: float = 0.035,
    ) -> Dict[str, float]:
        """
        Find optimal trace width and spacing for target differential impedance.

        Args:
            target_z_diff: Target differential impedance in ohms
            height_mm: Height above reference plane
            dielectric_constant: Substrate Er
            min/max_width_mm: Width constraints
            min/max_spacing_mm: Spacing constraints
            copper_thickness_mm: Copper thickness

        Returns:
            Dict with optimal width, spacing, and achieved impedance
        """
        best_error = float('inf')
        best_result = None

        # Sweep width and spacing
        width_steps = 20
        spacing_steps = 20

        for w_idx in range(width_steps):
            width = min_width_mm + (max_width_mm - min_width_mm) * w_idx / (width_steps - 1)

            for s_idx in range(spacing_steps):
                spacing = min_spacing_mm + (max_spacing_mm - min_spacing_mm) * s_idx / (spacing_steps - 1)

                trace = TraceGeometry(width_mm=width, thickness_mm=copper_thickness_mm)
                geometry = DiffPairGeometry(
                    positive_trace=trace,
                    negative_trace=TraceGeometry(width_mm=width, thickness_mm=copper_thickness_mm),
                    spacing_mm=spacing,
                    height_mm=height_mm,
                    dielectric_constant=dielectric_constant,
                )

                z_odd, z_even = self._calculate_mode_impedances(geometry)
                z_diff = 2 * z_odd

                error = abs(z_diff - target_z_diff)
                if error < best_error:
                    best_error = error
                    best_result = {
                        "width_mm": round(width, 4),
                        "spacing_mm": round(spacing, 4),
                        "z_diff_ohms": round(z_diff, 2),
                        "z_odd_ohms": round(z_odd, 2),
                        "z_even_ohms": round(z_even, 2),
                        "error_ohms": round(error, 2),
                        "coupling_coefficient": round((z_even - z_odd) / (z_even + z_odd), 4),
                    }

        return best_result  # type: ignore[return-value]

    def analyze_routing_path(
        self,
        path_segments: List[Dict[str, Any]],
        pair_name: str = "DP1",
        interface_type: Optional[str] = None,
    ) -> DiffPairResult:
        """
        Analyze a complete differential pair routing path with multiple segments.

        Args:
            path_segments: List of segment dicts with:
                - length_mm: Segment length
                - width_mm: Trace width
                - spacing_mm: Pair spacing
                - height_mm: Height to reference
                - dielectric_constant: Er
                - via_p: Number of vias in positive
                - via_n: Number of vias in negative
            pair_name: Name for the pair
            interface_type: Interface type for limit checking

        Returns:
            DiffPairResult with aggregated analysis
        """
        if not path_segments:
            raise ValueError("At least one path segment required")

        # Aggregate lengths
        total_length_p = 0
        total_length_n = 0
        total_vias_p = 0
        total_vias_n = 0
        weighted_z_diff = 0
        total_length = 0

        for seg in path_segments:
            seg_length = seg.get("length_mm", 0)
            total_length_p += seg_length
            total_length_n += seg_length
            total_vias_p += seg.get("via_p", 0)
            total_vias_n += seg.get("via_n", 0)

            # Calculate segment impedance
            trace = TraceGeometry(
                width_mm=seg.get("width_mm", 0.15),
                length_mm=seg_length,
            )
            geometry = DiffPairGeometry(
                positive_trace=trace,
                negative_trace=TraceGeometry(width_mm=seg.get("width_mm", 0.15)),
                spacing_mm=seg.get("spacing_mm", 0.15),
                height_mm=seg.get("height_mm", 0.1),
                dielectric_constant=seg.get("dielectric_constant", 4.3),
            )
            z_odd, z_even = self._calculate_mode_impedances(geometry)
            z_diff = 2 * z_odd
            weighted_z_diff += z_diff * seg_length
            total_length += seg_length

        # Calculate weighted average impedance
        if total_length > 0:
            avg_z_diff = weighted_z_diff / total_length
        else:
            avg_z_diff = 100

        # Create representative geometry for other calculations
        first_seg = path_segments[0]
        avg_trace_p = TraceGeometry(
            width_mm=first_seg.get("width_mm", 0.15),
            length_mm=total_length_p,
            via_count=total_vias_p,
        )
        avg_trace_n = TraceGeometry(
            width_mm=first_seg.get("width_mm", 0.15),
            length_mm=total_length_n,
            via_count=total_vias_n,
        )
        avg_geometry = DiffPairGeometry(
            positive_trace=avg_trace_p,
            negative_trace=avg_trace_n,
            spacing_mm=first_seg.get("spacing_mm", 0.15),
            height_mm=first_seg.get("height_mm", 0.1),
            dielectric_constant=first_seg.get("dielectric_constant", 4.3),
        )

        # Get data rate from interface type
        data_rates = {
            "usb2": 0.48,
            "usb3": 5.0,
            "hdmi_1.4": 3.4,
            "hdmi_2.0": 6.0,
            "displayport": 8.1,
            "pcie_gen3": 8.0,
            "pcie_gen4": 16.0,
            "pcie_gen5": 32.0,
            "sata": 6.0,
            "ethernet_1g": 1.25,
            "ethernet_10g": 10.3125,
        }
        data_rate = data_rates.get(interface_type.lower() if interface_type else "", None)

        return self.analyze_diff_pair(
            avg_geometry,
            pair_name=pair_name,
            interface_type=interface_type,
            data_rate_gbps=data_rate,
        )

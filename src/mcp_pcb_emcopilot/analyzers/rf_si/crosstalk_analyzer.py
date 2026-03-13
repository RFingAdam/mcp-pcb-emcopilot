"""
Crosstalk analyzer for PCB trace coupling analysis.

Calculates NEXT (Near-End Crosstalk) and FEXT (Far-End Crosstalk)
for parallel trace configurations.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class CouplingType(Enum):
    """Crosstalk coupling types"""
    EDGE_COUPLED = "edge_coupled"
    BROADSIDE_COUPLED = "broadside_coupled"
    MIXED = "mixed"


class Severity(Enum):
    """Crosstalk severity levels"""
    ACCEPTABLE = "acceptable"
    MARGINAL = "marginal"
    CRITICAL = "critical"


@dataclass
class CrosstalkResult:
    """Result of crosstalk analysis"""
    # Primary metrics
    next_db: float  # Near-End Crosstalk in dB
    fext_db: float  # Far-End Crosstalk in dB
    next_percent: float  # NEXT as percentage
    fext_percent: float  # FEXT as percentage

    # Coupling coefficients
    backward_coupling: float  # Kb (NEXT related)
    forward_coupling: float   # Kf (FEXT related)

    # Saturation length
    saturation_length_mm: float  # Length where NEXT saturates

    # Timing impact
    timing_noise_ps: float  # Estimated timing noise

    # Severity assessment
    severity: Severity
    recommendation: str

    # Input parameters
    spacing_mm: float = 0.0
    coupling_length_mm: float = 0.0
    trace_width_mm: float = 0.0
    dielectric_height_mm: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "next_db": round(self.next_db, 2),
            "fext_db": round(self.fext_db, 2),
            "next_percent": round(self.next_percent, 2),
            "fext_percent": round(self.fext_percent, 2),
            "backward_coupling": round(self.backward_coupling, 4),
            "forward_coupling": round(self.forward_coupling, 4),
            "saturation_length_mm": round(self.saturation_length_mm, 2),
            "timing_noise_ps": round(self.timing_noise_ps, 2),
            "severity": self.severity.value,
            "recommendation": self.recommendation,
        }


class CrosstalkAnalyzer:
    """
    Crosstalk analyzer for parallel PCB traces.

    Analyzes coupling between aggressor and victim traces for:
    - Edge-coupled (side-by-side) traces
    - Broadside-coupled (stacked) traces
    - General coupled transmission lines

    Usage:
        analyzer = CrosstalkAnalyzer()
        result = analyzer.analyze_edge_coupled(
            spacing_mm=0.15,
            coupling_length_mm=50,
            trace_width_mm=0.15,
            dielectric_height_mm=0.2,
            dielectric_constant=4.3,
        )
        print(f"NEXT: {result.next_db:.1f} dB")
    """

    # Physical constants
    C0 = 299792458  # Speed of light in m/s

    # Severity thresholds (dB)
    NEXT_ACCEPTABLE = -40  # Below this is acceptable
    NEXT_MARGINAL = -25    # Between this and acceptable is marginal
    FEXT_ACCEPTABLE = -35
    FEXT_MARGINAL = -20

    def __init__(
        self,
        default_rise_time_ps: float = 100,
        default_frequency_hz: float = 1e9,
    ):
        """
        Initialize analyzer.

        Args:
            default_rise_time_ps: Default signal rise time
            default_frequency_hz: Default frequency for analysis
        """
        self.default_rise_time = default_rise_time_ps
        self.default_frequency = default_frequency_hz

    def analyze_edge_coupled(
        self,
        spacing_mm: float,
        coupling_length_mm: float,
        trace_width_mm: float,
        dielectric_height_mm: float,
        dielectric_constant: float,
        trace_impedance_ohm: float = 50.0,
        rise_time_ps: Optional[float] = None,
    ) -> CrosstalkResult:
        """
        Analyze crosstalk for edge-coupled (side-by-side) traces.

        Args:
            spacing_mm: Edge-to-edge spacing between traces
            coupling_length_mm: Length of parallel run
            trace_width_mm: Width of traces
            dielectric_height_mm: Height above ground plane
            dielectric_constant: Substrate Er
            trace_impedance_ohm: Trace impedance
            rise_time_ps: Signal rise time

        Returns:
            CrosstalkResult with analysis
        """
        rise_time = rise_time_ps or self.default_rise_time

        # Effective spacing (edge-to-edge)
        s = spacing_mm
        w = trace_width_mm
        h = dielectric_height_mm

        # Coupling ratios
        s_h = s / h
        w_h = w / h

        # Backward coupling coefficient (NEXT)
        # Based on empirical formula for microstrip
        kb = self._calculate_backward_coupling(s_h, w_h, dielectric_constant)

        # Forward coupling coefficient (FEXT)
        # FEXT is polarity-dependent and length-dependent
        kf = self._calculate_forward_coupling(s_h, w_h, dielectric_constant)

        # Propagation velocity
        eps_eff = (dielectric_constant + 1) / 2  # Approximate for microstrip
        vp = self.C0 / math.sqrt(eps_eff)  # m/s

        # Rise distance (length the edge travels during rise time)
        rise_distance_mm = vp * rise_time * 1e-12 * 1000  # mm

        # Saturation length for NEXT
        saturation_length = rise_distance_mm / 2

        # NEXT calculation
        if coupling_length_mm < saturation_length:
            # Short coupled region - NEXT increases with length
            next_voltage = kb * (coupling_length_mm / saturation_length)
        else:
            # Long coupled region - NEXT saturates
            next_voltage = kb

        # FEXT calculation
        # FEXT continues to increase with length (proportional to Kf * length / rise_distance)
        fext_voltage = kf * (coupling_length_mm / rise_distance_mm)

        # Convert to dB
        next_db = 20 * math.log10(abs(next_voltage) + 1e-10)
        fext_db = 20 * math.log10(abs(fext_voltage) + 1e-10)

        # Convert to percentage
        next_percent = abs(next_voltage) * 100
        fext_percent = abs(fext_voltage) * 100

        # Timing noise estimate
        # Crosstalk causes timing jitter proportional to noise amplitude
        timing_noise = rise_time * max(next_percent, fext_percent) / 100

        # Severity assessment
        severity, recommendation = self._assess_severity(
            next_db, fext_db, s, h, coupling_length_mm
        )

        return CrosstalkResult(
            next_db=next_db,
            fext_db=fext_db,
            next_percent=next_percent,
            fext_percent=fext_percent,
            backward_coupling=kb,
            forward_coupling=kf,
            saturation_length_mm=saturation_length,
            timing_noise_ps=timing_noise,
            severity=severity,
            recommendation=recommendation,
            spacing_mm=spacing_mm,
            coupling_length_mm=coupling_length_mm,
            trace_width_mm=trace_width_mm,
            dielectric_height_mm=dielectric_height_mm,
        )

    def analyze_broadside_coupled(
        self,
        vertical_spacing_mm: float,
        coupling_length_mm: float,
        trace_width_mm: float,
        dielectric_constant: float,
        trace_impedance_ohm: float = 50.0,
        rise_time_ps: Optional[float] = None,
    ) -> CrosstalkResult:
        """
        Analyze crosstalk for broadside-coupled (stacked) traces.

        This occurs when traces on different layers overlap.

        Args:
            vertical_spacing_mm: Vertical distance between traces
            coupling_length_mm: Length of overlap
            trace_width_mm: Width of traces
            dielectric_constant: Dielectric Er between layers
            trace_impedance_ohm: Trace impedance
            rise_time_ps: Signal rise time

        Returns:
            CrosstalkResult with analysis
        """
        rise_time = rise_time_ps or self.default_rise_time

        h = vertical_spacing_mm
        w = trace_width_mm

        # For broadside coupling, the coupling is generally stronger
        w_h = w / h

        # Broadside coupling coefficients (stronger than edge)
        kb = 0.5 * (1 - 1 / (1 + w_h))  # Simplified model
        kf = 0.3 * w_h / (1 + w_h)

        # Limit coefficients to physical values
        kb = min(kb, 0.4)
        kf = min(kf, 0.3)

        # Propagation velocity
        vp = self.C0 / math.sqrt(dielectric_constant)
        rise_distance_mm = vp * rise_time * 1e-12 * 1000

        saturation_length = rise_distance_mm / 2

        # NEXT and FEXT
        if coupling_length_mm < saturation_length:
            next_voltage = kb * (coupling_length_mm / saturation_length)
        else:
            next_voltage = kb

        fext_voltage = kf * (coupling_length_mm / rise_distance_mm)

        # Convert to dB and percentage
        next_db = 20 * math.log10(abs(next_voltage) + 1e-10)
        fext_db = 20 * math.log10(abs(fext_voltage) + 1e-10)
        next_percent = abs(next_voltage) * 100
        fext_percent = abs(fext_voltage) * 100

        timing_noise = rise_time * max(next_percent, fext_percent) / 100

        severity, recommendation = self._assess_severity(
            next_db, fext_db, h, h, coupling_length_mm, is_broadside=True
        )

        return CrosstalkResult(
            next_db=next_db,
            fext_db=fext_db,
            next_percent=next_percent,
            fext_percent=fext_percent,
            backward_coupling=kb,
            forward_coupling=kf,
            saturation_length_mm=saturation_length,
            timing_noise_ps=timing_noise,
            severity=severity,
            recommendation=recommendation,
            spacing_mm=vertical_spacing_mm,
            coupling_length_mm=coupling_length_mm,
            trace_width_mm=trace_width_mm,
            dielectric_height_mm=vertical_spacing_mm,
        )

    def _calculate_backward_coupling(
        self,
        s_h: float,
        w_h: float,
        dielectric_constant: float,
    ) -> float:
        """
        Calculate backward (NEXT) coupling coefficient.

        Based on empirical formulas for microstrip coupling.
        """
        # Coupling decreases exponentially with spacing
        # and increases with dielectric constant
        er_factor = math.sqrt(dielectric_constant) / 2

        # Empirical formula
        if s_h < 0.1:
            # Very tight spacing
            kb = 0.3 * er_factor
        elif s_h < 1:
            kb = 0.3 * er_factor * math.exp(-2 * s_h)
        else:
            kb = 0.3 * er_factor * math.exp(-2) * (1 / s_h)

        # Width effect
        kb *= min(1.5, w_h + 0.5)

        return min(kb, 0.5)  # Physical limit

    def _calculate_forward_coupling(
        self,
        s_h: float,
        w_h: float,
        dielectric_constant: float,
    ) -> float:
        """
        Calculate forward (FEXT) coupling coefficient.

        FEXT is velocity-difference dependent.
        """
        # FEXT depends on odd/even mode velocity difference
        # Larger Er differences lead to more FEXT

        if s_h < 0.1:
            kf = 0.15
        elif s_h < 1:
            kf = 0.15 * math.exp(-1.5 * s_h)
        else:
            kf = 0.15 * math.exp(-1.5) * (1 / s_h)

        # Er effect (FEXT increases with Er for microstrip)
        er_factor = (dielectric_constant - 1) / dielectric_constant
        kf *= (1 + er_factor)

        return min(kf, 0.3)

    def _assess_severity(
        self,
        next_db: float,
        fext_db: float,
        spacing: float,
        height: float,
        length: float,
        is_broadside: bool = False,
    ) -> tuple:
        """Assess crosstalk severity and generate recommendations"""
        # Determine severity based on worst case
        if next_db > self.NEXT_MARGINAL or fext_db > self.FEXT_MARGINAL:
            severity = Severity.CRITICAL
        elif next_db > self.NEXT_ACCEPTABLE or fext_db > self.FEXT_ACCEPTABLE:
            severity = Severity.MARGINAL
        else:
            severity = Severity.ACCEPTABLE

        # Generate recommendation
        if severity == Severity.ACCEPTABLE:
            recommendation = "Crosstalk levels are within acceptable limits."
        elif severity == Severity.MARGINAL:
            recommendations = []
            if spacing / height < 2:
                recommendations.append(f"Increase trace spacing to ≥{2*height:.2f}mm (2H rule)")
            if length > 20:
                recommendations.append("Consider reducing parallel run length")
            if not is_broadside:
                recommendations.append("Add guard trace with ground vias")
            recommendation = "; ".join(recommendations) if recommendations else "Review signal integrity requirements"
        else:
            recommendations = []
            if spacing / height < 3:
                recommendations.append(f"Increase trace spacing to ≥{3*height:.2f}mm (3H rule)")
            recommendations.append("Reduce parallel coupling length")
            if not is_broadside:
                recommendations.append("Add grounded guard trace between aggressor and victim")
            else:
                recommendations.append("Route on different layer pairs or stagger traces")
            recommendation = "; ".join(recommendations)

        return severity, recommendation

    def analyze_trace_pair(
        self,
        aggressor_trace: dict,
        victim_trace: dict,
        stackup_height_mm: float,
        dielectric_constant: float,
        rise_time_ps: Optional[float] = None,
    ) -> CrosstalkResult:
        """
        Analyze crosstalk between two specific traces.

        Args:
            aggressor_trace: Dict with 'width_mm', 'layer', 'geometry' (list of points)
            victim_trace: Dict with same structure
            stackup_height_mm: Height to reference plane
            dielectric_constant: Substrate Er
            rise_time_ps: Signal rise time

        Returns:
            CrosstalkResult for the trace pair
        """
        # Calculate overlap region
        coupling_length, min_spacing = self._calculate_overlap(
            aggressor_trace.get('geometry', []),
            victim_trace.get('geometry', []),
        )

        if coupling_length == 0:
            return CrosstalkResult(
                next_db=-100,
                fext_db=-100,
                next_percent=0,
                fext_percent=0,
                backward_coupling=0,
                forward_coupling=0,
                saturation_length_mm=0,
                timing_noise_ps=0,
                severity=Severity.ACCEPTABLE,
                recommendation="No parallel coupling detected.",
            )

        # Determine if edge or broadside coupled
        aggressor_layer = aggressor_trace.get('layer', 'top')
        victim_layer = victim_trace.get('layer', 'top')

        if aggressor_layer == victim_layer:
            # Edge-coupled
            return self.analyze_edge_coupled(
                spacing_mm=min_spacing,
                coupling_length_mm=coupling_length,
                trace_width_mm=aggressor_trace.get('width_mm', 0.15),
                dielectric_height_mm=stackup_height_mm,
                dielectric_constant=dielectric_constant,
                rise_time_ps=rise_time_ps,
            )
        else:
            # Broadside-coupled
            return self.analyze_broadside_coupled(
                vertical_spacing_mm=stackup_height_mm,  # Approximate
                coupling_length_mm=coupling_length,
                trace_width_mm=aggressor_trace.get('width_mm', 0.15),
                dielectric_constant=dielectric_constant,
                rise_time_ps=rise_time_ps,
            )

    def _calculate_overlap(
        self,
        geometry1: List[tuple],
        geometry2: List[tuple],
    ) -> tuple:
        """
        Calculate parallel overlap between two trace geometries.

        Returns:
            (coupling_length_mm, minimum_spacing_mm)
        """
        if not geometry1 or not geometry2:
            return 0, 0

        total_coupling = 0
        min_spacing = float('inf')

        # Simplified: check if trace segments are parallel and close
        for i in range(len(geometry1) - 1):
            p1_start = geometry1[i]
            p1_end = geometry1[i + 1]

            for j in range(len(geometry2) - 1):
                p2_start = geometry2[j]
                p2_end = geometry2[j + 1]

                # Check if segments are parallel (within tolerance)
                coupling, spacing = self._segment_coupling(
                    p1_start, p1_end, p2_start, p2_end
                )

                total_coupling += coupling
                if spacing > 0:
                    min_spacing = min(min_spacing, spacing)

        if min_spacing == float('inf'):
            min_spacing = 0

        return total_coupling, min_spacing

    def _segment_coupling(
        self,
        p1_start: tuple,
        p1_end: tuple,
        p2_start: tuple,
        p2_end: tuple,
        parallel_threshold: float = 15,  # degrees
    ) -> tuple:
        """
        Check coupling between two line segments.

        Returns:
            (coupling_length_mm, spacing_mm)
        """
        # Calculate segment vectors
        v1 = (p1_end[0] - p1_start[0], p1_end[1] - p1_start[1])
        v2 = (p2_end[0] - p2_start[0], p2_end[1] - p2_start[1])

        # Check if parallel
        len1 = math.sqrt(v1[0]**2 + v1[1]**2)
        len2 = math.sqrt(v2[0]**2 + v2[1]**2)

        if len1 < 0.01 or len2 < 0.01:
            return 0, 0

        # Dot product for angle
        dot = (v1[0]*v2[0] + v1[1]*v2[1]) / (len1 * len2)
        dot = max(-1, min(1, dot))  # Clamp for acos
        angle = math.degrees(math.acos(abs(dot)))

        if angle > parallel_threshold:
            return 0, 0

        # Calculate perpendicular distance between lines
        # Using cross product
        dx = p2_start[0] - p1_start[0]
        dy = p2_start[1] - p1_start[1]

        cross = abs(v1[0] * dy - v1[1] * dx) / len1
        spacing = cross

        # Coupling length is the overlap in parallel direction
        coupling = min(len1, len2)

        return coupling, spacing

    def find_critical_nets(
        self,
        traces: List[dict],
        height_mm: float,
        dielectric_constant: float,
        threshold_db: float = -30,
    ) -> List[dict]:
        """
        Find trace pairs with critical crosstalk levels.

        Args:
            traces: List of trace dictionaries
            height_mm: Dielectric height
            dielectric_constant: Substrate Er
            threshold_db: Crosstalk threshold for reporting

        Returns:
            List of critical crosstalk pairs
        """
        critical_pairs = []

        for i, trace1 in enumerate(traces):
            for j, trace2 in enumerate(traces[i+1:], i+1):
                result = self.analyze_trace_pair(
                    trace1, trace2, height_mm, dielectric_constant
                )

                if result.next_db > threshold_db or result.fext_db > threshold_db:
                    critical_pairs.append({
                        'aggressor': trace1.get('net_name', f'trace_{i}'),
                        'victim': trace2.get('net_name', f'trace_{j}'),
                        'next_db': result.next_db,
                        'fext_db': result.fext_db,
                        'severity': result.severity.value,
                        'recommendation': result.recommendation,
                    })

        return sorted(critical_pairs, key=lambda x: max(x['next_db'], x['fext_db']), reverse=True)

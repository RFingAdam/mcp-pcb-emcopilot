"""Current loop analyzer for EMC assessment"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import math


@dataclass
class LoopAnalysisResult:
    """Results from current loop analysis"""
    # Loop identification
    loop_id: str
    signal_net: str
    return_path: str

    # Loop geometry
    loop_area_mm2: float
    loop_area_cm2: float
    loop_length_mm: float
    effective_height_mm: float

    # Emissions estimate
    emissions_dbuv_per_m: float  # At 3m
    emissions_frequency_mhz: float
    margin_to_limit_db: float  # Positive = pass

    # Risk assessment
    risk_level: str  # low, medium, high, critical
    emc_score: float  # 0-100

    # Return path quality
    return_path_continuous: bool
    return_path_vias: int
    plane_splits_crossed: int

    # Recommendations
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    # Details
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SignalPath:
    """Signal path definition for loop analysis"""
    net_name: str
    trace_layer: int
    reference_layer: int
    segments: List[Dict[str, float]]  # List of {x1, y1, x2, y2, width}
    via_locations: List[Tuple[float, float]] = field(default_factory=list)
    frequency_mhz: float = 100  # Signal frequency


class CurrentLoopAnalyzer:
    """
    Current loop analyzer for EMC compliance.

    Analyzes current return paths and loop areas to estimate:
    - Radiated emissions from loop antennas
    - Common mode noise risk
    - Return path discontinuities

    Based on loop antenna radiation models and CISPR/FCC limits.
    """

    # Speed of light (m/s)
    C0 = 2.998e8

    # Free space impedance (ohms)
    Z0 = 377

    # CISPR 22/32 Class B limits at 3m (dBuV/m)
    CISPR_CLASS_B_LIMITS = {
        (30, 230): 40,      # 30-230 MHz: 40 dBuV/m QP
        (230, 1000): 47,    # 230-1000 MHz: 47 dBuV/m QP
    }

    # FCC Part 15 Class B limits at 3m (dBuV/m)
    FCC_CLASS_B_LIMITS = {
        (30, 88): 40,
        (88, 216): 43.5,
        (216, 960): 46,
        (960, 40000): 54,
    }

    def __init__(self, standard: str = "cispr"):
        """
        Initialize analyzer.

        Args:
            standard: EMC standard ("cispr" or "fcc")
        """
        self.standard = standard.lower()
        self.limits = self.CISPR_CLASS_B_LIMITS if self.standard == "cispr" else self.FCC_CLASS_B_LIMITS

    def analyze_loop(
        self,
        signal_path: SignalPath,
        loop_id: str = "L1",
        current_ma: float = 10,
        rise_time_ns: float = 1,
    ) -> LoopAnalysisResult:
        """
        Analyze a signal current loop for EMC.

        Args:
            signal_path: Signal path definition
            loop_id: Identifier for this loop
            current_ma: Signal current in mA
            rise_time_ns: Signal rise time in ns

        Returns:
            LoopAnalysisResult with complete analysis
        """
        # Calculate loop geometry
        loop_area, loop_length, effective_height = self._calculate_loop_geometry(signal_path)

        # Calculate emissions
        freq_mhz = signal_path.frequency_mhz
        emissions_dbuv = self._calculate_emissions(
            loop_area_mm2=loop_area,
            frequency_mhz=freq_mhz,
            current_ma=current_ma,
        )

        # Get limit for this frequency
        limit = self._get_limit(freq_mhz)
        margin = limit - emissions_dbuv

        # Assess return path quality
        return_continuous = self._check_return_path_continuity(signal_path)
        num_vias = len(signal_path.via_locations)
        plane_splits = self._estimate_plane_splits(signal_path)

        # Risk assessment
        if margin < 0:
            risk_level = "critical"
            score = max(0, 30 + margin)  # Negative margin = very low score
        elif margin < 6:
            risk_level = "high"
            score = 40 + margin * 2
        elif margin < 12:
            risk_level = "medium"
            score = 60 + margin
        else:
            risk_level = "low"
            score = min(100, 80 + margin / 2)

        # Adjust for return path issues
        if not return_continuous:
            score -= 15
            risk_level = "high" if risk_level == "medium" else risk_level
        if plane_splits > 0:
            score -= plane_splits * 10

        score = max(0, min(100, score))

        # Generate issues and recommendations
        issues = []
        recommendations = []

        if margin < 0:
            issues.append(f"Emissions {-margin:.1f}dB over {self.standard.upper()} limit")
            recommendations.append("Reduce loop area or add filtering")

        if loop_area > 100:  # > 1 cm^2
            issues.append(f"Large loop area: {loop_area:.1f}mm²")
            recommendations.append("Route signal closer to reference plane")

        if not return_continuous:
            issues.append("Return path discontinuity detected")
            recommendations.append("Add stitching vias near signal vias")

        if plane_splits > 0:
            issues.append(f"Signal crosses {plane_splits} split plane(s)")
            recommendations.append("Avoid routing across power plane splits")

        if num_vias > 0 and len([v for v in signal_path.via_locations]) > num_vias * 0.5:
            recommendations.append(f"Add ground vias near {num_vias} signal vias")

        return LoopAnalysisResult(
            loop_id=loop_id,
            signal_net=signal_path.net_name,
            return_path=f"Layer {signal_path.reference_layer}",
            loop_area_mm2=round(loop_area, 2),
            loop_area_cm2=round(loop_area / 100, 4),
            loop_length_mm=round(loop_length, 2),
            effective_height_mm=round(effective_height, 3),
            emissions_dbuv_per_m=round(emissions_dbuv, 1),
            emissions_frequency_mhz=freq_mhz,
            margin_to_limit_db=round(margin, 1),
            risk_level=risk_level,
            emc_score=round(score, 1),
            return_path_continuous=return_continuous,
            return_path_vias=num_vias,
            plane_splits_crossed=plane_splits,
            issues=issues,
            recommendations=recommendations,
            metrics={
                "current_ma": current_ma,
                "rise_time_ns": rise_time_ns,
                "limit_dbuv_m": limit,
                "standard": self.standard,
            },
        )

    def _calculate_loop_geometry(
        self, signal_path: SignalPath
    ) -> Tuple[float, float, float]:
        """
        Calculate loop area and dimensions.

        Returns:
            (area_mm2, perimeter_mm, effective_height_mm)
        """
        total_length: float = 0
        for seg in signal_path.segments:
            dx = seg.get("x2", 0) - seg.get("x1", 0)
            dy = seg.get("y2", 0) - seg.get("y1", 0)
            total_length += math.sqrt(dx**2 + dy**2)

        # Effective height is distance between signal and reference layer
        # Assume typical stackup heights
        layer_heights = {
            (1, 2): 0.1,   # L1 to L2: ~100um (prepreg)
            (1, 3): 0.2,   # L1 to L3: ~200um
            (2, 3): 0.2,   # etc.
            (3, 4): 0.2,
        }
        layer_pair = (signal_path.trace_layer, signal_path.reference_layer)
        effective_height = layer_heights.get(layer_pair, 0.15)

        # Loop area = length × height
        loop_area = total_length * effective_height

        return loop_area, total_length, effective_height

    def _calculate_emissions(
        self,
        loop_area_mm2: float,
        frequency_mhz: float,
        current_ma: float,
        distance_m: float = 3,
    ) -> float:
        """
        Calculate radiated emissions from small loop antenna model.

        E = (1.316e-14 × A × I × f²) / d

        where:
        - A = loop area in m²
        - I = current in A
        - f = frequency in Hz
        - d = distance in m

        Returns:
            Field strength in dBuV/m
        """
        # Convert units
        area_m2 = loop_area_mm2 * 1e-6
        current_a = current_ma * 1e-3
        freq_hz = frequency_mhz * 1e6

        # Small loop antenna formula
        # E = (η₀ × π × A × I × f²) / (c² × d)
        # Simplified: E = 1.316e-14 × A × I × f² / d  (in V/m)
        e_field = (1.316e-14 * area_m2 * current_a * freq_hz**2) / distance_m

        # Convert to dBuV/m
        e_dbuv = 20 * math.log10(e_field * 1e6) if e_field > 0 else -60

        return e_dbuv

    def _get_limit(self, frequency_mhz: float) -> float:
        """Get emission limit for frequency."""
        for (f_low, f_high), limit in self.limits.items():
            if f_low <= frequency_mhz < f_high:
                return limit
        return 50  # Default

    def _check_return_path_continuity(self, signal_path: SignalPath) -> bool:
        """Check if return path is continuous (simplified)."""
        # In reality, would check against plane copper data
        # Here we assume continuous if no layer changes without vias
        if len(signal_path.via_locations) == 0 and signal_path.trace_layer != signal_path.reference_layer:
            return True  # Single layer, reference plane below
        return len(signal_path.via_locations) > 0 or signal_path.trace_layer == signal_path.reference_layer

    def _estimate_plane_splits(self, signal_path: SignalPath) -> int:
        """Estimate number of plane splits crossed (placeholder)."""
        # In reality, would check signal path against plane geometry
        return 0

    def analyze_multiple_loops(
        self,
        paths: List[SignalPath],
        current_ma: float = 10,
    ) -> List[LoopAnalysisResult]:
        """
        Analyze multiple signal loops.

        Args:
            paths: List of signal paths
            current_ma: Default current

        Returns:
            List of results sorted by risk
        """
        results = []
        for i, path in enumerate(paths):
            result = self.analyze_loop(path, loop_id=f"L{i+1}", current_ma=current_ma)
            results.append(result)

        # Sort by risk (critical first)
        risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        results.sort(key=lambda r: (risk_order.get(r.risk_level, 4), -r.loop_area_mm2))

        return results

    def calculate_max_loop_area(
        self,
        frequency_mhz: float,
        current_ma: float,
        margin_db: float = 6,
    ) -> float:
        """
        Calculate maximum allowable loop area for compliance.

        Args:
            frequency_mhz: Signal frequency
            current_ma: Signal current
            margin_db: Safety margin below limit

        Returns:
            Maximum loop area in mm²
        """
        limit = self._get_limit(frequency_mhz)
        target_field = limit - margin_db

        # Reverse the emissions calculation
        # E_dbuv = 20 * log10(1.316e-14 × A × I × f² / d × 1e6)
        # A = (10^(E_dbuv/20) × d) / (1.316e-14 × I × f² × 1e6)

        e_field_v_m = 10 ** (target_field / 20) * 1e-6  # V/m
        current_a = current_ma * 1e-3
        freq_hz = frequency_mhz * 1e6
        distance_m = 3

        area_m2 = (e_field_v_m * distance_m) / (1.316e-14 * current_a * freq_hz**2)
        area_mm2 = area_m2 * 1e6

        return round(area_mm2, 2)

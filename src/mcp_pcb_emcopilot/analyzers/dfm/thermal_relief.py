"""Thermal relief analyzer for DFM"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ThermalReliefResult:
    """Results from thermal relief analysis"""
    # Component identification
    component_ref: str
    pin_id: str
    location: Tuple[float, float]

    # Thermal relief configuration
    has_thermal_relief: bool
    relief_type: str  # spoke, solid, partial
    spoke_count: int
    spoke_width_mm: float
    spoke_gap_mm: float
    antipad_diameter_mm: float

    # Thermal characteristics
    thermal_resistance_c_per_w: float
    heat_dissipation_capacity_w: float
    soldering_difficulty: str  # easy, moderate, difficult, very_difficult

    # Assessment
    dfm_score: float  # 0-100
    risk_level: str  # low, medium, high

    # Issues and recommendations
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    # Details
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ThermalPad:
    """Thermal pad/via definition"""
    reference: str
    pin_id: str
    x_mm: float
    y_mm: float

    # Pad characteristics
    pad_diameter_mm: float
    drill_diameter_mm: float
    is_plated: bool = True

    # Connection to plane
    connected_to_plane: bool = True
    plane_copper_area_mm2: float = 1000  # Area of copper connected

    # Current thermal relief
    has_relief: bool = True
    spoke_count: int = 4
    spoke_width_mm: float = 0.254  # 10 mil
    gap_angle_deg: float = 45

    # Component thermal requirements
    power_dissipation_w: float = 0
    is_ground_pin: bool = False


class ThermalReliefAnalyzer:
    """
    Thermal relief analyzer for DFM.

    Analyzes:
    - Thermal relief configurations for PTH components
    - Solderability of plane-connected pads
    - Heat dissipation requirements

    Based on IPC-2221 and soldering process requirements.
    """

    # Copper thermal conductivity (W/m·K)
    COPPER_K = 385

    # Standard thermal relief configurations
    RELIEF_CONFIGS = {
        "ipc_class_2": {"spokes": 4, "spoke_width_mm": 0.254, "gap_angle_deg": 45},
        "ipc_class_3": {"spokes": 4, "spoke_width_mm": 0.381, "gap_angle_deg": 45},
        "high_current": {"spokes": 4, "spoke_width_mm": 0.508, "gap_angle_deg": 30},
        "thermal_pad": {"spokes": 0, "spoke_width_mm": 0, "gap_angle_deg": 0},  # Solid
    }

    # Minimum spoke width by IPC class
    MIN_SPOKE_WIDTH = {
        "class_1": 0.203,  # 8 mil
        "class_2": 0.254,  # 10 mil
        "class_3": 0.305,  # 12 mil
    }

    def __init__(self, ipc_class: str = "class_2"):
        """
        Initialize analyzer.

        Args:
            ipc_class: IPC class (class_1, class_2, class_3)
        """
        self.ipc_class = ipc_class
        self.min_spoke_width = self.MIN_SPOKE_WIDTH.get(ipc_class, 0.254)

    def analyze_pad(
        self,
        pad: ThermalPad,
        wave_solder: bool = False,
        reflow_profile: str = "standard",
    ) -> ThermalReliefResult:
        """
        Analyze thermal relief for a single pad.

        Args:
            pad: Thermal pad definition
            wave_solder: True if wave soldering process
            reflow_profile: Reflow profile type

        Returns:
            ThermalReliefResult with complete analysis
        """
        # Determine relief type
        if not pad.connected_to_plane:
            relief_type = "none"
            has_relief = False
        elif not pad.has_relief:
            relief_type = "solid"
            has_relief = False
        else:
            relief_type = f"{pad.spoke_count}_spoke"
            has_relief = True

        # Calculate thermal characteristics
        thermal_resistance = self._calculate_thermal_resistance(pad)
        heat_capacity = 1 / thermal_resistance if thermal_resistance > 0 else float('inf')

        # Assess soldering difficulty
        difficulty = self._assess_soldering_difficulty(
            pad,
            wave_solder,
            thermal_resistance,
        )

        # Calculate antipad diameter
        antipad = self._calculate_antipad(pad)

        # Calculate DFM score
        score = self._calculate_dfm_score(
            pad,
            has_relief,
            thermal_resistance,
            difficulty,
        )

        # Risk level
        if score >= 80:
            risk_level = "low"
        elif score >= 60:
            risk_level = "medium"
        else:
            risk_level = "high"

        # Issues and recommendations
        issues = []
        recommendations = []

        # Check for solid connection issues
        if pad.connected_to_plane and not pad.has_relief:
            if pad.plane_copper_area_mm2 > 100:
                issues.append("Solid connection to large copper plane")
                recommendations.append("Add thermal relief for better solderability")
                if wave_solder:
                    issues.append("Wave solder will likely fail on solid plane connection")

        # Check spoke width
        if has_relief and pad.spoke_width_mm < self.min_spoke_width:
            issues.append(f"Spoke width {pad.spoke_width_mm}mm below {self.min_spoke_width}mm minimum")
            recommendations.append(f"Increase spoke width to ≥{self.min_spoke_width}mm")

        # Check for thermal vs DFM tradeoff
        if pad.power_dissipation_w > 1:
            if has_relief and pad.spoke_count < 4:
                issues.append("Insufficient thermal path for power dissipation")
                recommendations.append("Use 4 or more spokes for high-power components")
            if has_relief and pad.spoke_width_mm < 0.5:
                recommendations.append("Widen spokes for better thermal performance")

        # Ground pin specific checks
        if pad.is_ground_pin:
            if not pad.connected_to_plane:
                issues.append("Ground pin not connected to ground plane")
            elif has_relief and pad.spoke_count < 4:
                recommendations.append("Use 4 spokes for reliable ground connection")

        return ThermalReliefResult(
            component_ref=pad.reference,
            pin_id=pad.pin_id,
            location=(pad.x_mm, pad.y_mm),
            has_thermal_relief=has_relief,
            relief_type=relief_type,
            spoke_count=pad.spoke_count if has_relief else 0,
            spoke_width_mm=round(pad.spoke_width_mm, 3),
            spoke_gap_mm=round(self._calculate_gap_width(pad), 3),
            antipad_diameter_mm=round(antipad, 3),
            thermal_resistance_c_per_w=round(thermal_resistance, 2),
            heat_dissipation_capacity_w=round(heat_capacity, 2),
            soldering_difficulty=difficulty,
            dfm_score=round(score, 1),
            risk_level=risk_level,
            issues=issues,
            recommendations=recommendations,
            metrics={
                "ipc_class": self.ipc_class,
                "plane_copper_area_mm2": pad.plane_copper_area_mm2,
                "power_dissipation_w": pad.power_dissipation_w,
                "wave_solder": wave_solder,
            },
        )

    def _calculate_thermal_resistance(self, pad: ThermalPad) -> float:
        """
        Calculate thermal resistance in °C/W.

        Simplified model based on spoke geometry.
        """
        if not pad.connected_to_plane:
            return 100  # High resistance, no plane connection

        if not pad.has_relief:
            # Solid connection - low resistance
            return 1.0

        # Calculate spoke cross-section
        spoke_area_mm2 = pad.spoke_width_mm * 0.035  # Assume 1oz copper
        total_spoke_area_mm2 = spoke_area_mm2 * pad.spoke_count

        # Approximate spoke length (half annular ring)
        antipad_radius = pad.pad_diameter_mm / 2 + 0.2  # Typical gap
        spoke_length_mm = antipad_radius

        # Thermal resistance: R = L / (k × A)
        # Convert to proper units
        spoke_area_m2 = total_spoke_area_mm2 * 1e-6
        spoke_length_m = spoke_length_mm * 1e-3

        if spoke_area_m2 > 0:
            thermal_resistance = spoke_length_m / (self.COPPER_K * spoke_area_m2)
        else:
            thermal_resistance = 50

        return thermal_resistance

    def _calculate_gap_width(self, pad: ThermalPad) -> float:
        """Calculate gap width between spokes."""
        if pad.spoke_count == 0:
            return 0

        # Gap based on angle
        circumference = math.pi * pad.pad_diameter_mm
        spoke_arc = pad.spoke_width_mm
        total_spoke_arc = spoke_arc * pad.spoke_count
        total_gap = circumference - total_spoke_arc
        gap_width = total_gap / pad.spoke_count

        return max(0, gap_width)

    def _calculate_antipad(self, pad: ThermalPad) -> float:
        """Calculate antipad diameter."""
        if not pad.has_relief:
            return 0

        # Typical antipad is pad + clearance
        gap = self._calculate_gap_width(pad)
        return pad.pad_diameter_mm + 2 * gap

    def _assess_soldering_difficulty(
        self,
        pad: ThermalPad,
        wave_solder: bool,
        thermal_resistance: float,
    ) -> str:
        """Assess soldering difficulty."""
        if not pad.connected_to_plane:
            return "easy"

        if not pad.has_relief:
            # Solid connection
            if pad.plane_copper_area_mm2 > 500:
                return "very_difficult" if wave_solder else "difficult"
            elif pad.plane_copper_area_mm2 > 100:
                return "difficult" if wave_solder else "moderate"
            else:
                return "moderate"

        # With relief
        if thermal_resistance > 20:
            return "easy"
        elif thermal_resistance > 5:
            return "moderate"
        else:
            return "difficult" if wave_solder else "moderate"

    def _calculate_dfm_score(
        self,
        pad: ThermalPad,
        has_relief: bool,
        thermal_resistance: float,
        difficulty: str,
    ) -> float:
        """Calculate DFM score."""
        score = 100.0

        if not pad.connected_to_plane:
            return score  # No plane connection, no issues

        # Relief presence
        if not has_relief and pad.plane_copper_area_mm2 > 50:
            score -= 30

        # Spoke width
        if has_relief and pad.spoke_width_mm < self.min_spoke_width:
            deficit = (self.min_spoke_width - pad.spoke_width_mm) / self.min_spoke_width
            score -= deficit * 20

        # Soldering difficulty
        difficulty_penalties = {
            "easy": 0,
            "moderate": 10,
            "difficult": 25,
            "very_difficult": 40,
        }
        score -= difficulty_penalties.get(difficulty, 0)

        # Thermal requirements
        if pad.power_dissipation_w > 0:
            max_power = 1 / thermal_resistance if thermal_resistance > 0 else 10
            if pad.power_dissipation_w > max_power * 0.8:
                score -= 15

        return max(0, min(100, score))

    def analyze_board(
        self,
        pads: List[ThermalPad],
        wave_solder: bool = False,
    ) -> Dict[str, Any]:
        """
        Analyze all thermal pads on a board.

        Args:
            pads: List of thermal pads
            wave_solder: Using wave solder process

        Returns:
            Board-level analysis
        """
        results = []
        issues_count = 0

        for pad in pads:
            result = self.analyze_pad(pad, wave_solder)
            results.append(result)
            if result.risk_level in ("high", "medium"):
                issues_count += 1

        # Statistics
        relief_count = sum(1 for r in results if r.has_thermal_relief)
        solid_count = sum(1 for r in results if r.relief_type == "solid")

        return {
            "total_pads": len(pads),
            "pads_with_relief": relief_count,
            "pads_solid": solid_count,
            "pads_with_issues": issues_count,
            "wave_solder_ready": issues_count == 0 and solid_count == 0,
            "results": results,
            "recommendations": list(set(
                rec for r in results for rec in r.recommendations
            ))[:5],
        }

    def recommend_relief(
        self,
        pad_diameter_mm: float,
        power_dissipation_w: float = 0,
        is_ground: bool = False,
        wave_solder: bool = False,
    ) -> Dict[str, Any]:
        """
        Recommend thermal relief configuration.

        Args:
            pad_diameter_mm: Pad diameter
            power_dissipation_w: Power to dissipate
            is_ground: Is this a ground pin
            wave_solder: Using wave solder

        Returns:
            Recommended configuration
        """
        # Base configuration
        if power_dissipation_w > 2:
            config = "high_current"
        elif wave_solder or pad_diameter_mm > 1.5:
            config = "ipc_class_3"
        else:
            config = "ipc_class_2"

        base = self.RELIEF_CONFIGS[config].copy()  # type: ignore[attr-defined]

        # Adjust for power dissipation
        if power_dissipation_w > 1:
            base["spoke_width_mm"] = max(base["spoke_width_mm"], 0.4)

        # Calculate antipad
        gap = pad_diameter_mm * 0.15  # 15% of pad
        antipad = pad_diameter_mm + 2 * gap

        return {
            "spoke_count": base["spokes"],
            "spoke_width_mm": base["spoke_width_mm"],
            "gap_angle_deg": base["gap_angle_deg"],
            "antipad_diameter_mm": round(antipad, 3),
            "config_name": config,
            "notes": [
                "4 spokes recommended for mechanical stability",
                "Wider spokes for better thermal performance",
                "Smaller gaps for easier soldering",
            ],
        }

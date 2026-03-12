"""ESD (Electrostatic Discharge) protection assessment analyzer"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import math


@dataclass
class ESDResult:
    """Results from ESD protection assessment"""
    # Assessment identification
    assessment_id: str
    interface_name: str
    interface_type: str  # usb, hdmi, ethernet, gpio, etc.

    # Protection devices
    has_tvs_diode: bool
    tvs_clamping_voltage: Optional[float]  # V
    protection_level: str  # IEC 61000-4-2 level

    # Protection path
    path_length_mm: float
    path_inductance_nh: float
    ground_path_impedance_mohm: float

    # Trace routing
    trace_width_mm: float
    clearance_to_sensitive_mm: float

    # Assessment
    esd_score: float  # 0-100
    risk_level: str  # low, medium, high, critical
    iec_contact_kv: float  # Expected withstand level
    iec_air_kv: float

    # Issues and recommendations
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    # Details
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ESDInterface:
    """ESD-sensitive interface definition"""
    name: str
    interface_type: str  # usb, hdmi, ethernet, gpio, antenna, etc.
    connector_location: Tuple[float, float]  # x, y in mm

    # Protection devices
    has_tvs: bool = False
    tvs_part_number: Optional[str] = None
    tvs_clamping_v: Optional[float] = None
    tvs_capacitance_pf: Optional[float] = None

    # Routing
    trace_length_to_ic_mm: float = 50
    trace_width_mm: float = 0.2
    protection_device_distance_mm: float = 5  # Distance from connector to TVS

    # Signal characteristics
    signal_voltage_v: float = 3.3
    max_frequency_mhz: float = 100

    # Ground path
    ground_via_count: int = 2
    ground_trace_width_mm: float = 0.5


@dataclass
class BoardESDConfig:
    """Board-level ESD configuration"""
    has_chassis_ground: bool = False
    chassis_bonding_points: int = 0
    enclosure_type: str = "plastic"  # plastic, metal, hybrid
    ground_plane_continuous: bool = True


class ESDAnalyzer:
    """
    ESD protection analyzer.

    Assesses ESD protection for:
    - External interfaces (USB, HDMI, Ethernet, etc.)
    - Antenna connections
    - GPIO and test points
    - Board-level protection strategy

    Based on IEC 61000-4-2 ESD immunity requirements.
    """

    # IEC 61000-4-2 test levels
    IEC_LEVELS = {
        1: {"contact": 2, "air": 2},
        2: {"contact": 4, "air": 4},
        3: {"contact": 6, "air": 8},
        4: {"contact": 8, "air": 15},
        "x": {"contact": 15, "air": 25},  # Special level
    }

    # Interface-specific requirements
    INTERFACE_REQUIREMENTS = {
        "usb": {"level": 4, "max_capacitance_pf": 5},
        "usb3": {"level": 4, "max_capacitance_pf": 0.5},
        "hdmi": {"level": 4, "max_capacitance_pf": 0.5},
        "displayport": {"level": 4, "max_capacitance_pf": 0.3},
        "ethernet": {"level": 4, "max_capacitance_pf": 15},
        "antenna_2g4": {"level": 4, "max_capacitance_pf": 0.3},
        "antenna_5g": {"level": 4, "max_capacitance_pf": 0.15},
        "gpio": {"level": 2, "max_capacitance_pf": 50},
        "sd_card": {"level": 3, "max_capacitance_pf": 5},
        "audio": {"level": 4, "max_capacitance_pf": 15},
        "power_jack": {"level": 4, "max_capacitance_pf": None},
    }

    def __init__(self):
        pass

    def analyze_interface(
        self,
        interface: ESDInterface,
        board_config: Optional[BoardESDConfig] = None,
        assessment_id: str = "ESD1",
    ) -> ESDResult:
        """
        Analyze ESD protection for an interface.

        Args:
            interface: Interface definition
            board_config: Board-level ESD configuration
            assessment_id: Assessment identifier

        Returns:
            ESDResult with complete analysis
        """
        if board_config is None:
            board_config = BoardESDConfig()

        # Get interface requirements
        req = self.INTERFACE_REQUIREMENTS.get(
            interface.interface_type.lower(),
            {"level": 2, "max_capacitance_pf": 10}
        )

        # Calculate protection path characteristics
        path_inductance = self._calculate_path_inductance(interface)
        ground_impedance = self._calculate_ground_impedance(interface)

        # Determine effective protection level
        if interface.has_tvs and interface.tvs_clamping_v:
            clamping_v = interface.tvs_clamping_v
            # Estimate withstand based on clamping and IC rating
            ic_abs_max = interface.signal_voltage_v + 0.5  # Typical abs max
            margin = clamping_v - ic_abs_max

            if margin < 0:
                protection_level = "inadequate"
                contact_kv = 0
            elif margin < 5:
                protection_level = f"Level {min(4, req['level'])}"
                contact_kv = 8
            else:
                protection_level = "Level 4+"
                contact_kv = 15
        else:
            protection_level = "unprotected"
            clamping_v = None
            contact_kv = 2  # Basic immunity only

        # Air discharge is typically higher
        air_kv = contact_kv * 1.5

        # Check TVS capacitance for high-speed interfaces
        capacitance_ok = True
        max_cap = req.get("max_capacitance_pf")
        if max_cap and interface.tvs_capacitance_pf:
            if interface.tvs_capacitance_pf > max_cap:
                capacitance_ok = False

        # Clearance to sensitive components
        clearance = self._estimate_clearance(interface)

        # Calculate ESD score
        score = self._calculate_esd_score(
            interface,
            board_config,
            req,
            path_inductance,
            ground_impedance,
            capacitance_ok,
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

        if not interface.has_tvs:
            issues.append("No TVS protection device")
            recommendations.append(f"Add TVS diode near connector for {interface.interface_type}")

        if interface.has_tvs:
            if interface.protection_device_distance_mm > 10:
                issues.append(f"TVS too far from connector ({interface.protection_device_distance_mm}mm)")
                recommendations.append("Place TVS within 5mm of connector")

            if not capacitance_ok and max_cap:
                issues.append(f"TVS capacitance {interface.tvs_capacitance_pf}pF exceeds {max_cap}pF limit")
                recommendations.append("Use lower capacitance TVS for high-speed interface")

        if path_inductance > 5:  # > 5 nH
            issues.append(f"High protection path inductance ({path_inductance:.1f}nH)")
            recommendations.append("Widen traces and minimize via count to protection device")

        if ground_impedance > 50:  # > 50 mΩ
            issues.append(f"High ground path impedance ({ground_impedance:.0f}mΩ)")
            recommendations.append("Add more ground vias and use wider ground traces")

        if interface.ground_via_count < 2:
            issues.append("Insufficient ground vias near protection device")
            recommendations.append("Add multiple ground vias close to TVS device")

        if board_config.enclosure_type == "plastic" and not board_config.has_chassis_ground:
            issues.append("No chassis ground in plastic enclosure")
            recommendations.append("Consider guard ring or enhanced PCB protection")

        if clearance < 0.5:
            issues.append(f"Sensitive traces too close to ESD path ({clearance:.2f}mm)")
            recommendations.append("Increase clearance from ESD entry to sensitive traces")

        return ESDResult(
            assessment_id=assessment_id,
            interface_name=interface.name,
            interface_type=interface.interface_type,
            has_tvs_diode=interface.has_tvs,
            tvs_clamping_voltage=clamping_v,
            protection_level=protection_level,
            path_length_mm=interface.protection_device_distance_mm,
            path_inductance_nh=round(path_inductance, 2),
            ground_path_impedance_mohm=round(ground_impedance, 1),
            trace_width_mm=interface.trace_width_mm,
            clearance_to_sensitive_mm=round(clearance, 2),
            esd_score=round(score, 1),
            risk_level=risk_level,
            iec_contact_kv=contact_kv,
            iec_air_kv=air_kv,
            issues=issues,
            recommendations=recommendations,
            metrics={
                "required_level": req["level"],
                "max_capacitance_pf": max_cap,
                "tvs_capacitance_pf": interface.tvs_capacitance_pf,
                "enclosure_type": board_config.enclosure_type,
                "has_chassis_ground": board_config.has_chassis_ground,
            },
        )

    def _calculate_path_inductance(self, interface: ESDInterface) -> float:
        """
        Calculate protection path inductance in nH.

        L ≈ 1 nH/mm for typical trace
        """
        # Trace inductance (rough estimate)
        trace_inductance = interface.protection_device_distance_mm * 1.0

        # Via inductance (roughly 0.5-1 nH per via)
        via_inductance = interface.ground_via_count * 0.7

        return trace_inductance + via_inductance

    def _calculate_ground_impedance(self, interface: ESDInterface) -> float:
        """
        Calculate ground path impedance in mΩ.
        """
        # Copper resistivity at DC
        rho = 1.68e-8  # Ω⋅m

        # Ground trace resistance
        trace_length_m = interface.protection_device_distance_mm * 1e-3
        trace_width_m = interface.ground_trace_width_mm * 1e-3
        trace_thickness_m = 35e-6  # 1 oz copper

        trace_r = rho * trace_length_m / (trace_width_m * trace_thickness_m)

        # Via resistance (very low, ~1 mΩ per via)
        via_r = 0.001 / interface.ground_via_count if interface.ground_via_count > 0 else 0.01

        # Total in mΩ
        return (trace_r + via_r) * 1000

    def _estimate_clearance(self, interface: ESDInterface) -> float:
        """Estimate clearance from ESD path to sensitive traces."""
        # Simplified: assume clearance relates to trace length
        # In reality, would check actual layout
        return min(interface.trace_length_to_ic_mm / 10, 2.0)

    def _calculate_esd_score(
        self,
        interface: ESDInterface,
        board_config: BoardESDConfig,
        requirements: Dict,
        path_inductance: float,
        ground_impedance: float,
        capacitance_ok: bool,
    ) -> float:
        """Calculate overall ESD protection score 0-100."""
        score = 100.0

        # TVS presence (40% weight)
        if not interface.has_tvs:
            score -= 40
        else:
            # TVS placement
            if interface.protection_device_distance_mm > 10:
                score -= 15
            elif interface.protection_device_distance_mm > 5:
                score -= 5

        # Path inductance (20% weight)
        if path_inductance > 10:
            score -= 20
        elif path_inductance > 5:
            score -= 10
        elif path_inductance > 2:
            score -= 5

        # Ground impedance (15% weight)
        if ground_impedance > 100:
            score -= 15
        elif ground_impedance > 50:
            score -= 10
        elif ground_impedance > 20:
            score -= 5

        # Capacitance (10% weight for high-speed)
        if not capacitance_ok:
            score -= 10

        # Board-level (15% weight)
        if board_config.has_chassis_ground:
            score += 5  # Bonus
        if board_config.enclosure_type == "metal":
            score += 5  # Better shielding
        if not board_config.ground_plane_continuous:
            score -= 10

        return max(0, min(100, score))

    def analyze_board(
        self,
        interfaces: List[ESDInterface],
        board_config: Optional[BoardESDConfig] = None,
    ) -> Dict[str, Any]:
        """
        Analyze ESD protection for all board interfaces.

        Args:
            interfaces: List of ESD-sensitive interfaces
            board_config: Board-level configuration

        Returns:
            Comprehensive ESD assessment
        """
        if board_config is None:
            board_config = BoardESDConfig()

        results = []
        critical_count = 0
        high_count = 0

        for i, interface in enumerate(interfaces):
            result = self.analyze_interface(
                interface,
                board_config,
                assessment_id=f"ESD{i+1}",
            )
            results.append(result)

            if result.risk_level == "critical":
                critical_count += 1
            elif result.risk_level == "high":
                high_count += 1

        # Overall assessment
        if critical_count > 0:
            overall_risk = "critical"
            overall_score = 20
        elif high_count > len(interfaces) / 2:
            overall_risk = "high"
            overall_score = 40
        elif high_count > 0:
            overall_risk = "medium"
            overall_score = 60
        else:
            overall_risk = "low"
            overall_score = sum(r.esd_score for r in results) / len(results) if results else 100

        # Board-level recommendations
        board_recommendations = []

        if board_config.enclosure_type == "plastic":
            board_recommendations.append("Consider spark gaps or transient suppression at board edge")

        if not board_config.has_chassis_ground:
            board_recommendations.append("Implement chassis ground bonding if possible")

        unprotected = [r for r in results if not r.has_tvs_diode]
        if unprotected:
            board_recommendations.append(
                f"{len(unprotected)} interface(s) lack TVS protection: "
                f"{', '.join(r.interface_name for r in unprotected)}"
            )

        return {
            "total_interfaces": len(interfaces),
            "critical_risk_count": critical_count,
            "high_risk_count": high_count,
            "overall_risk": overall_risk,
            "overall_score": round(overall_score, 1),
            "results": results,
            "board_recommendations": board_recommendations,
            "compliance_summary": {
                "iec_61000_4_2": overall_risk in ("low", "medium"),
                "recommended_testing": [
                    "Contact discharge: ±8kV",
                    "Air discharge: ±15kV",
                    "Test all external interfaces",
                ],
            },
        }

    def recommend_protection(
        self,
        interface_type: str,
        signal_voltage: float = 3.3,
        max_frequency_mhz: float = 100,
    ) -> Dict[str, Any]:
        """
        Recommend ESD protection for an interface type.

        Args:
            interface_type: Type of interface
            signal_voltage: Signal voltage level
            max_frequency_mhz: Maximum signal frequency

        Returns:
            Protection recommendations
        """
        req = self.INTERFACE_REQUIREMENTS.get(
            interface_type.lower(),
            {"level": 2, "max_capacitance_pf": 10}
        )

        # Calculate clamping voltage requirement
        # Clamping should be below IC abs max (typically Vcc + 0.3V + margin)
        max_clamping = signal_voltage + 3  # Reasonable margin

        # Capacitance budget
        max_cap = req.get("max_capacitance_pf", 50)

        # TVS recommendations based on frequency
        if max_frequency_mhz > 5000:
            tvs_type = "ultra-low capacitance"
            cap_target = min(0.1, max_cap) if max_cap else 0.1
        elif max_frequency_mhz > 1000:
            tvs_type = "very low capacitance"
            cap_target = min(0.3, max_cap) if max_cap else 0.3
        elif max_frequency_mhz > 100:
            tvs_type = "low capacitance"
            cap_target = min(1.0, max_cap) if max_cap else 1.0
        else:
            tvs_type = "standard"
            cap_target = min(5.0, max_cap) if max_cap else 5.0

        # Example part suggestions
        part_suggestions = {
            "ultra-low capacitance": ["PESD5V0L1BA", "PRTR5V0U2X", "SP3012-01ETG"],
            "very low capacitance": ["PESD3V3L1BA", "USBLC6-2SC6", "ESD7004"],
            "low capacitance": ["SPHV3-01ETG-C", "TPD2E001", "ESD7L5.0DT5G"],
            "standard": ["SMBJ5.0A", "SMAJ5.0A", "TVS3300"],
        }

        return {
            "interface_type": interface_type,
            "required_iec_level": req["level"],
            "iec_contact_kv": self.IEC_LEVELS[req["level"]]["contact"],
            "iec_air_kv": self.IEC_LEVELS[req["level"]]["air"],
            "max_clamping_voltage": round(max_clamping, 1),
            "max_capacitance_pf": max_cap,
            "target_capacitance_pf": cap_target,
            "tvs_type": tvs_type,
            "example_parts": part_suggestions.get(tvs_type, []),
            "placement_guidelines": [
                "Place TVS within 5mm of connector",
                "Use short, wide traces to ground",
                "Minimum 2 ground vias near TVS",
                "Keep ESD traces away from sensitive signals",
            ],
        }

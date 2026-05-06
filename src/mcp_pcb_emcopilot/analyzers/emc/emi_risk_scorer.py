"""EMI risk scorer for per-net EMI risk scoring and board-level predictions.

Combines return path analysis, net classification, and emission physics
to produce:
- Per-net EMI risk scores (0-100)
- Predicted emission spectrum vs FCC/CISPR limits
- Board region hot-spot identification
- Executive summary with actionable recommendations

This is the capstone module that ties together all EMC analysis into
quantitative, actionable results.

Operates on in-memory PCBDesignData from any parser.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Data structures
# =============================================================================

@dataclass
class NetEMIRisk:
    """EMI risk assessment for a single net."""
    net_name: str
    net_category: str
    risk_score: float  # 0-100
    risk_level: str  # "critical", "high", "medium", "low"
    frequency_content_mhz: list[float] = field(default_factory=list)
    effective_loop_area_mm2: float = 0.0
    estimated_current_ma: float = 10.0
    predicted_emission_dbuv_m: float = -60.0
    contributing_factors: list[dict] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class FrequencyRisk:
    """Risk at a specific frequency."""
    frequency_mhz: float
    source_nets: list[str] = field(default_factory=list)
    predicted_level_dbuv_m: float = -60.0
    limit_dbuv_m: float = 40.0
    margin_db: float = 100.0
    risk_level: str = "low"


@dataclass
class BoardRegionRisk:
    """EMI risk for a board region."""
    region_name: str
    center_x_mm: float
    center_y_mm: float
    radius_mm: float
    risk_score: float = 0.0
    contributing_nets: list[str] = field(default_factory=list)
    primary_concern: str = ""


@dataclass
class EMIRiskResult:
    """Complete EMI risk assessment."""
    net_risks: list[NetEMIRisk] = field(default_factory=list)
    top_risk_nets: list[str] = field(default_factory=list)
    frequency_risks: list[FrequencyRisk] = field(default_factory=list)
    board_regions: list[BoardRegionRisk] = field(default_factory=list)
    overall_risk_level: str = "low"
    overall_risk_score: float = 0.0
    predicted_problem_frequencies_mhz: list[float] = field(default_factory=list)
    standard_compliance: dict = field(default_factory=dict)
    executive_summary: str = ""
    recommendations: list[str] = field(default_factory=list)


# =============================================================================
# Constants
# =============================================================================

# Speed of light (m/s)
C0 = 2.998e8

# Typical frequency content by interface type
INTERFACE_FREQUENCIES = {
    "ddr": {"fundamental_mhz": 1600, "harmonics": 5},
    "ddr4": {"fundamental_mhz": 1200, "harmonics": 5},
    "usb": {"fundamental_mhz": 240, "harmonics": 7},
    "usb3": {"fundamental_mhz": 2500, "harmonics": 5},
    "pcie": {"fundamental_mhz": 4000, "harmonics": 3},
    "ethernet": {"fundamental_mhz": 62.5, "harmonics": 9},
    "clock": {"fundamental_mhz": 100, "harmonics": 11},
    "rf": {"fundamental_mhz": 2400, "harmonics": 3},
    "lvds": {"fundamental_mhz": 400, "harmonics": 5},
    "spi": {"fundamental_mhz": 50, "harmonics": 5},
    "i2c": {"fundamental_mhz": 1, "harmonics": 3},
    "uart": {"fundamental_mhz": 1, "harmonics": 3},
    "jtag": {"fundamental_mhz": 10, "harmonics": 3},
    "gpio": {"fundamental_mhz": 50, "harmonics": 5},
    "analog": {"fundamental_mhz": 10, "harmonics": 3},
    "unknown": {"fundamental_mhz": 50, "harmonics": 5},
}

# Typical signal currents by interface type (mA)
INTERFACE_CURRENTS_MA = {
    "ddr": 15,
    "ddr4": 12,
    "usb": 17,
    "usb3": 10,
    "pcie": 8,
    "ethernet": 20,
    "clock": 10,
    "rf": 5,
    "lvds": 3.5,
    "spi": 10,
    "i2c": 3,
    "uart": 10,
    "jtag": 10,
    "gpio": 8,
    "analog": 5,
    "unknown": 10,
}

# Typical rise times by interface type (ns)
INTERFACE_RISE_TIMES_NS = {
    "ddr": 0.3,
    "ddr4": 0.25,
    "usb": 0.5,
    "usb3": 0.1,
    "pcie": 0.05,
    "ethernet": 1.0,
    "clock": 0.5,
    "rf": 0.05,
    "lvds": 0.3,
    "spi": 1.0,
    "i2c": 10.0,
    "uart": 5.0,
    "jtag": 2.0,
    "gpio": 1.0,
    "analog": 5.0,
    "unknown": 1.0,
}

# FCC Part 15 Class B limits at 3m (dBuV/m)
FCC_CLASS_B_LIMITS = {
    30: 40.0,
    88: 40.0,
    216: 43.5,
    960: 46.0,
    40000: 54.0,
}

# FCC Part 15 Class A limits at 3m (dBuV/m) -- less strict
FCC_CLASS_A_LIMITS = {
    30: 49.5,
    88: 49.5,
    216: 49.5,
    960: 49.5,
    40000: 49.5,
}

# CISPR 32 Class B limits at 3m (dBuV/m quasi-peak)
CISPR_CLASS_B_LIMITS = {
    30: 40.0,
    230: 40.0,
    1000: 47.0,
    6000: 47.0,
}

# CISPR 32 Class A limits at 3m (dBuV/m quasi-peak)
CISPR_CLASS_A_LIMITS = {
    30: 50.0,
    230: 50.0,
    1000: 57.0,
    6000: 57.0,
}

# Standard lookup table
STANDARD_LIMITS = {
    "FCC_B": FCC_CLASS_B_LIMITS,
    "FCC_A": FCC_CLASS_A_LIMITS,
    "CISPR_B": CISPR_CLASS_B_LIMITS,
    "CISPR_A": CISPR_CLASS_A_LIMITS,
}

# Categories considered high-speed for EMI purposes
HIGH_SPEED_CATEGORIES = {"ddr", "usb", "pcie", "ethernet", "clock", "rf", "lvds"}

# Ground net keywords
GROUND_NET_KEYWORDS = ("GND", "VSS", "AGND", "DGND", "EARTH", "GROUND", "PGND", "SGND")

# Sensitive frequency bands
SENSITIVE_BANDS = [
    (88, 108, "FM broadcast"),
    (470, 890, "TV broadcast UHF"),
    (824, 894, "Cellular 850"),
    (1710, 1990, "Cellular PCS"),
    (2400, 2500, "WiFi/BT 2.4GHz"),
    (5150, 5850, "WiFi 5GHz"),
]


# =============================================================================
# Helper functions
# =============================================================================

def _get_limit_at_freq(frequency_mhz: float, limits: dict[Any, float]) -> float:
    """Interpolate emission limit at a given frequency.

    Limits dict has {frequency_boundary_mhz: limit_dbuv_m}.
    Returns the limit for the band containing the frequency.
    """
    sorted_freqs = sorted(limits.keys())

    if frequency_mhz < sorted_freqs[0]:
        return limits[sorted_freqs[0]]

    for i in range(len(sorted_freqs) - 1):
        if frequency_mhz <= sorted_freqs[i + 1]:
            return limits[sorted_freqs[i]]

    return limits[sorted_freqs[-1]]


def _calculate_emission_dbuv_m(
    loop_area_mm2: float,
    current_ma: float,
    frequency_mhz: float,
    distance_m: float = 3.0,
) -> float:
    """Calculate radiated emission from small loop antenna model.

    E = (1.316e-14 * A * I * f^2) / d  (in V/m)

    where:
        A = loop area in m^2
        I = current in A
        f = frequency in Hz
        d = distance in m

    Returns:
        Field strength in dBuV/m
    """
    if loop_area_mm2 <= 0 or current_ma <= 0 or frequency_mhz <= 0:
        return -60.0

    area_m2 = loop_area_mm2 * 1e-6
    current_a = current_ma * 1e-3
    freq_hz = frequency_mhz * 1e6

    e_field = (1.316e-14 * area_m2 * current_a * freq_hz ** 2) / distance_m

    if e_field > 0:
        return 20 * math.log10(e_field * 1e6)
    return -60.0


def _harmonic_amplitude_factor(
    harmonic_number: int,
    rise_time_ns: float,
    fundamental_mhz: float,
    duty_cycle: float = 0.5,
) -> float:
    """Calculate relative amplitude of a harmonic.

    Based on trapezoidal wave Fourier series with rise-time roll-off.

    For a trapezoidal wave:
    - Flat to f_knee = 0.35 / rise_time
    - Then -20 dB/decade roll-off

    The duty cycle affects which harmonics are present.
    """
    n = harmonic_number
    freq_mhz = fundamental_mhz * n

    # Duty cycle envelope (sinc function)
    if n == 1:
        dc_factor = 1.0
    else:
        arg = n * math.pi * duty_cycle
        if abs(arg) < 1e-10:
            dc_factor = 1.0
        else:
            dc_factor = abs(math.sin(arg) / arg)
        dc_factor = max(dc_factor, 0.001)

    # Rise time envelope
    if rise_time_ns <= 0:
        rt_factor = 1.0
    else:
        f_knee_mhz = 350.0 / rise_time_ns  # 0.35 / rise_time in GHz -> MHz
        if freq_mhz <= f_knee_mhz:
            rt_factor = 1.0
        else:
            rt_factor = f_knee_mhz / freq_mhz

    # 1/n factor for harmonics
    n_factor = 1.0 / n

    return dc_factor * rt_factor * n_factor


def _get_frequency_info(category: str, net_name: str = ""):
    """Get frequency characteristics for a net category."""
    import re

    # Check for specific subcategory hints
    name_upper = (net_name or "").upper()

    if category == "ddr":
        if "DDR5" in name_upper:
            return {"fundamental_mhz": 2400, "harmonics": 5}
        if "DDR4" in name_upper or "LPDDR4" in name_upper:
            return {"fundamental_mhz": 1200, "harmonics": 5}
        if "DDR3" in name_upper:
            return {"fundamental_mhz": 800, "harmonics": 5}

    if category == "usb":
        if "SS" in name_upper or "USB3" in name_upper:
            return {"fundamental_mhz": 2500, "harmonics": 5}

    if category == "pcie":
        if "GEN5" in name_upper:
            return {"fundamental_mhz": 8000, "harmonics": 3}
        if "GEN4" in name_upper:
            return {"fundamental_mhz": 4000, "harmonics": 3}

    if category == "clock":
        # Try to extract frequency from net name
        m = re.search(r'(\d+)\s*M', name_upper)
        if m:
            freq = float(m.group(1))
            return {"fundamental_mhz": freq, "harmonics": 11}

    return INTERFACE_FREQUENCIES.get(category, INTERFACE_FREQUENCIES["unknown"])


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    dx = x2 - x1
    dy = y2 - y1
    return math.sqrt(dx * dx + dy * dy)


# =============================================================================
# Main scorer
# =============================================================================

class EMIRiskScorer:
    """Scores EMI risk per net and predicts emission spectrum.

    Combines:
    - Return path analysis (loop areas, split crossings, via issues)
    - Net classification (interface type -> frequency content)
    - Emission physics (loop antenna model)
    - Regulatory limits (FCC/CISPR)

    To produce actionable EMI risk scores and predictions.
    """

    def score(
        self,
        design_data,
        return_path_result=None,
        classified_nets=None,
        standard: str = "FCC_B",
        test_distance_m: float = 3.0,
    ) -> EMIRiskResult:
        """Complete EMI risk scoring.

        Args:
            design_data: PCBDesignData with parsed design
            return_path_result: Optional ReturnPathAnalysisResult
            classified_nets: Optional NetClassificationResult from classifier
            standard: EMC standard for limit comparison
            test_distance_m: Measurement distance in meters

        Returns:
            EMIRiskResult with complete assessment
        """
        result = EMIRiskResult()
        limits = STANDARD_LIMITS.get(standard, FCC_CLASS_B_LIMITS)

        # Build classification lookup
        net_categories = {}
        if classified_nets is not None:
            for nc in classified_nets.classified_nets:
                net_categories[nc.net_name] = nc.category
        else:
            for net in design_data.nets:
                name_upper = (net.name or "").upper()
                is_ground = any(kw in name_upper for kw in GROUND_NET_KEYWORDS)
                is_power = any(kw in name_upper
                               for kw in ("VCC", "VDD", "VBAT", "VIN"))
                if is_ground:
                    net_categories[net.name] = "ground"
                elif is_power:
                    net_categories[net.name] = "power"
                else:
                    net_categories[net.name] = "unknown"

        # Build return path lookup
        rp_lookup = {}
        if return_path_result is not None:
            for nr in return_path_result.net_results:
                rp_lookup[nr.net_name] = nr

        # Score each signal net
        all_frequency_emissions: dict[float, list[tuple[float, str]]] = {}  # freq_mhz -> [(emission_dbuv, net_name)]

        for net in design_data.nets:
            category = net_categories.get(net.name, "unknown")
            if category in ("power", "ground"):
                continue

            # Get return path info if available
            rp_info = rp_lookup.get(net.name)
            loop_area = rp_info.effective_loop_area_mm2 if rp_info else None
            rp_quality = rp_info.return_path_quality if rp_info else None
            split_count = len(rp_info.split_crossings) if rp_info else 0
            bad_vias = (
                sum(1 for vt in rp_info.via_transitions if not vt.has_adequate_return)
                if rp_info else 0
            )

            # Calculate loop area if not provided by return path analysis
            if loop_area is None or loop_area <= 0:
                loop_area = self._estimate_loop_area(design_data, net)

            # Score this net
            net_risk = self.score_net(
                design_data=design_data,
                net_name=net.name,
                net_category=category,
                loop_area_mm2=loop_area,
                return_path_quality=rp_quality,
                split_crossings=split_count,
                bad_via_transitions=bad_vias,
                standard=standard,
                test_distance_m=test_distance_m,
            )
            result.net_risks.append(net_risk)

            # Collect frequency emissions for spectrum prediction
            for freq in net_risk.frequency_content_mhz:
                if freq not in all_frequency_emissions:
                    all_frequency_emissions[freq] = []
                emission = _calculate_emission_dbuv_m(
                    loop_area, net_risk.estimated_current_ma,
                    freq, test_distance_m,
                )
                all_frequency_emissions[freq].append((emission, net.name))

        # Sort nets by risk score (descending)
        result.net_risks.sort(key=lambda r: r.risk_score, reverse=True)
        result.top_risk_nets = [r.net_name for r in result.net_risks[:10]]

        # Build frequency risk analysis
        result.frequency_risks = self.predict_emission_spectrum(
            design_data,
            all_frequency_emissions,
            limits,
            test_distance_m,
        )

        # Identify hot regions
        result.board_regions = self.identify_hot_regions(
            design_data, result.net_risks,
        )

        # Overall risk assessment
        if result.net_risks:
            result.overall_risk_score = round(
                max(r.risk_score for r in result.net_risks), 1
            )
        else:
            result.overall_risk_score = 0

        if result.overall_risk_score >= 80:
            result.overall_risk_level = "critical"
        elif result.overall_risk_score >= 60:
            result.overall_risk_level = "high"
        elif result.overall_risk_score >= 40:
            result.overall_risk_level = "medium"
        else:
            result.overall_risk_level = "low"

        # Predicted problem frequencies
        result.predicted_problem_frequencies_mhz = [
            fr.frequency_mhz for fr in result.frequency_risks
            if fr.margin_db < 6
        ]

        # Standard compliance
        result.standard_compliance = self._assess_compliance(
            result.frequency_risks, standard,
        )

        # Executive summary
        result.executive_summary = self._build_executive_summary(result, standard)

        # Recommendations
        result.recommendations = self._build_recommendations(result)

        return result

    def score_net(
        self,
        design_data,
        net_name: str,
        net_category: str,
        loop_area_mm2: float,
        return_path_quality: Optional[str] = None,
        split_crossings: int = 0,
        bad_via_transitions: int = 0,
        standard: str = "FCC_B",
        test_distance_m: float = 3.0,
    ) -> NetEMIRisk:
        """Score EMI risk for a single net.

        Risk = f(frequency_content, loop_area, current, harmonics, return_path_quality)

        Args:
            design_data: PCBDesignData
            net_name: Net name
            net_category: Category from classifier
            loop_area_mm2: Effective loop area
            return_path_quality: Quality from return path analyzer
            split_crossings: Number of split-plane crossings
            bad_via_transitions: Number of via transitions without return vias
            standard: EMC standard
            test_distance_m: Test distance

        Returns:
            NetEMIRisk with complete scoring
        """
        limits = STANDARD_LIMITS.get(standard, FCC_CLASS_B_LIMITS)

        # Get frequency characteristics
        freq_info = _get_frequency_info(net_category, net_name)
        fundamental = freq_info["fundamental_mhz"]
        num_harmonics = freq_info["harmonics"]

        # Get typical current and rise time
        current_ma = INTERFACE_CURRENTS_MA.get(net_category, 10)
        rise_time_ns = INTERFACE_RISE_TIMES_NS.get(net_category, 1.0)

        # Build frequency content list
        frequency_content = []
        for n in range(1, num_harmonics + 1):
            freq = fundamental * n
            if freq <= 40000:  # Cap at 40 GHz
                frequency_content.append(round(freq, 2))

        # Calculate worst-case emission across all harmonics
        worst_emission = -60.0
        worst_freq = fundamental

        for n in range(1, num_harmonics + 1):
            freq = fundamental * n
            if freq > 40000:
                break

            amp_factor = _harmonic_amplitude_factor(
                n, rise_time_ns, fundamental,
            )
            effective_current = current_ma * amp_factor

            emission = _calculate_emission_dbuv_m(
                loop_area_mm2, effective_current, freq, test_distance_m,
            )

            limit = _get_limit_at_freq(freq, limits)
            margin = limit - emission

            # Track worst case by margin (not absolute emission)
            if emission > worst_emission:
                worst_emission = emission
                worst_freq = freq

        # Calculate risk score (0-100)
        # Base score from emission level vs limit
        limit_at_worst = _get_limit_at_freq(worst_freq, limits)
        margin = limit_at_worst - worst_emission

        contributing_factors = []

        # Factor 1: Emission margin (0-40 points)
        if margin < 0:
            emission_score: float = 40  # Over limit
        elif margin < 6:
            emission_score = 30 + (6 - margin) * 10 / 6  # 30-40
        elif margin < 12:
            emission_score = 15 + (12 - margin) * 15 / 6  # 15-30
        elif margin < 20:
            emission_score = (20 - margin) * 15 / 8  # 0-15
        else:
            emission_score = 0

        contributing_factors.append({
            "factor": "emission_margin",
            "weight": 0.4,
            "value": round(margin, 1),
            "description": f"Margin to {standard} limit: {margin:.1f}dB at {worst_freq:.0f}MHz",
        })

        # Factor 2: Loop area (0-25 points)
        if loop_area_mm2 > 500:
            area_score: float = 25
        elif loop_area_mm2 > 100:
            area_score = 15 + (loop_area_mm2 - 100) * 10 / 400
        elif loop_area_mm2 > 25:
            area_score = 5 + (loop_area_mm2 - 25) * 10 / 75
        else:
            area_score = loop_area_mm2 * 5 / 25

        contributing_factors.append({
            "factor": "loop_area",
            "weight": 0.25,
            "value": round(loop_area_mm2, 1),
            "description": f"Effective loop area: {loop_area_mm2:.1f} mm^2",
        })

        # Factor 3: Frequency content (0-15 points)
        if fundamental > 1000:
            freq_score = 15
        elif fundamental > 500:
            freq_score = 10 + (fundamental - 500) * 5 / 500
        elif fundamental > 100:
            freq_score = 5 + (fundamental - 100) * 5 / 400
        else:
            freq_score = fundamental * 5 / 100

        contributing_factors.append({
            "factor": "frequency_content",
            "weight": 0.15,
            "value": fundamental,
            "description": f"Fundamental: {fundamental:.0f}MHz ({net_category})",
        })

        # Factor 4: Return path quality (0-10 points)
        quality_scores = {
            "excellent": 0,
            "good": 2,
            "marginal": 6,
            "poor": 10,
        }
        rp_score = quality_scores.get(return_path_quality or "good", 5)

        contributing_factors.append({
            "factor": "return_path_quality",
            "weight": 0.1,
            "value": return_path_quality or "unknown",
            "description": f"Return path quality: {return_path_quality or 'unknown'}",
        })

        # Factor 5: Split crossings and via issues (0-10 points)
        structural_score = min(10, split_crossings * 5 + bad_via_transitions * 3)

        contributing_factors.append({
            "factor": "structural_issues",
            "weight": 0.1,
            "value": split_crossings + bad_via_transitions,
            "description": (
                f"{split_crossings} split crossing(s), "
                f"{bad_via_transitions} via issue(s)"
            ),
        })

        # Total risk score
        risk_score = emission_score + area_score + freq_score + rp_score + structural_score
        risk_score = min(100, max(0, risk_score))

        # Determine risk level
        if risk_score >= 80:
            risk_level = "critical"
        elif risk_score >= 60:
            risk_level = "high"
        elif risk_score >= 40:
            risk_level = "medium"
        else:
            risk_level = "low"

        # Build recommendations
        recommendations = []
        if margin < 0:
            recommendations.append(
                f"CRITICAL: Predicted emission exceeds {standard} limit by "
                f"{-margin:.1f}dB at {worst_freq:.0f}MHz. "
                "Reduce loop area and add filtering."
            )
        elif margin < 6:
            recommendations.append(
                f"Marginal compliance: only {margin:.1f}dB margin at "
                f"{worst_freq:.0f}MHz. Consider reducing loop area."
            )

        if loop_area_mm2 > 100:
            recommendations.append(
                f"Large loop area ({loop_area_mm2:.0f} mm^2). Route signal "
                "closer to reference plane or shorten trace."
            )

        if split_crossings > 0:
            recommendations.append(
                f"Signal crosses {split_crossings} reference plane split(s). "
                "Reroute to avoid gaps."
            )

        if bad_via_transitions > 0:
            recommendations.append(
                f"Add ground return vias near {bad_via_transitions} signal via(s)."
            )

        return NetEMIRisk(
            net_name=net_name,
            net_category=net_category,
            risk_score=round(risk_score, 1),
            risk_level=risk_level,
            frequency_content_mhz=frequency_content,
            effective_loop_area_mm2=round(loop_area_mm2, 2),
            estimated_current_ma=current_ma,
            predicted_emission_dbuv_m=round(worst_emission, 1),
            contributing_factors=contributing_factors,
            recommendations=recommendations,
        )

    def predict_emission_spectrum(
        self,
        design_data,
        frequency_emissions: Optional[dict] = None,
        limits: Optional[dict] = None,
        test_distance_m: float = 3.0,
    ) -> list[FrequencyRisk]:
        """Predict emission levels vs regulatory limits.

        For each frequency point, sums contributions from all nets
        (power sum in linear domain) and compares against the limit.

        Args:
            design_data: PCBDesignData
            frequency_emissions: Dict of freq_mhz -> [(emission_dbuv, net_name)]
            limits: Limit table to use
            test_distance_m: Test distance

        Returns:
            List of FrequencyRisk sorted by margin (worst first)
        """
        if limits is None:
            limits = FCC_CLASS_B_LIMITS

        if frequency_emissions is None:
            frequency_emissions = {}

        results = []

        for freq_mhz, emissions_list in sorted(frequency_emissions.items()):
            if freq_mhz < 30 or freq_mhz > 40000:
                continue  # Below regulatory range

            # Power sum of all contributions at this frequency
            linear_sum = 0
            source_nets = []
            for emission_dbuv, net_name in emissions_list:
                if emission_dbuv > -50:  # Only count meaningful contributions
                    linear_sum += 10 ** (emission_dbuv / 20)
                    if net_name not in source_nets:
                        source_nets.append(net_name)

            if linear_sum > 0:
                total_dbuv = 20 * math.log10(linear_sum)
            else:
                total_dbuv = -60.0

            limit = _get_limit_at_freq(freq_mhz, limits)
            margin = limit - total_dbuv

            if margin < 0:
                risk_level = "critical"
            elif margin < 6:
                risk_level = "high"
            elif margin < 12:
                risk_level = "medium"
            else:
                risk_level = "low"

            results.append(FrequencyRisk(
                frequency_mhz=round(freq_mhz, 2),
                source_nets=source_nets,
                predicted_level_dbuv_m=round(total_dbuv, 1),
                limit_dbuv_m=limit,
                margin_db=round(margin, 1),
                risk_level=risk_level,
            ))

        # Sort by margin (worst first)
        results.sort(key=lambda r: r.margin_db)

        return results

    def identify_hot_regions(
        self,
        design_data,
        net_risks: list[NetEMIRisk],
    ) -> list[BoardRegionRisk]:
        """Identify board regions with highest EMI risk.

        Clusters high-risk nets by their trace locations and identifies
        spatial hot-spots on the board.

        Args:
            design_data: PCBDesignData
            net_risks: List of per-net risk scores

        Returns:
            List of board region risks, sorted by risk score
        """
        # Build net-to-location map using trace centroids
        net_locations = {}  # net_name -> (avg_x, avg_y)
        net_index_map = {n.name: n.index for n in design_data.nets}

        for risk in net_risks:
            if risk.risk_score < 20:
                continue  # Skip low-risk nets

            net_idx = net_index_map.get(risk.net_name)
            if net_idx is None:
                continue

            traces = design_data.get_traces_on_net(net_idx)
            if not traces:
                continue

            # Calculate centroid
            total_x = sum(
                (t.x1_mm + t.x2_mm) / 2 for t in traces
            )
            total_y = sum(
                (t.y1_mm + t.y2_mm) / 2 for t in traces
            )
            n = len(traces)
            net_locations[risk.net_name] = (total_x / n, total_y / n)

        if not net_locations:
            return []

        # Simple grid-based clustering
        risk_lookup = {r.net_name: r for r in net_risks}

        # Determine board extent
        board_w = design_data.board_width_mm or 100
        board_h = design_data.board_height_mm or 100

        # Divide board into regions (roughly 20mm grid)
        grid_size = max(20, min(board_w, board_h) / 4)
        regions = []

        nx = max(1, int(math.ceil(board_w / grid_size)))
        ny = max(1, int(math.ceil(board_h / grid_size)))

        for gx in range(nx):
            for gy in range(ny):
                cx = (gx + 0.5) * grid_size
                cy = (gy + 0.5) * grid_size
                radius = grid_size * 0.7  # Overlap slightly

                # Find nets in this region
                contributing = []
                total_risk: float = 0

                for net_name, (nx_loc, ny_loc) in net_locations.items():
                    dist = _distance(cx, cy, nx_loc, ny_loc)
                    if dist <= radius:
                        risk_entry: NetEMIRisk | None = risk_lookup.get(net_name)
                        if risk_entry:
                            contributing.append(net_name)
                            total_risk += risk_entry.risk_score

                if contributing:
                    avg_risk = total_risk / len(contributing)

                    # Determine primary concern
                    worst_net = max(
                        contributing,
                        key=lambda n: risk_lookup.get(n, NetEMIRisk(
                            net_name=n, net_category="", risk_score=0,
                            risk_level="low",
                        )).risk_score,
                    )
                    worst_risk = risk_lookup.get(worst_net)
                    primary = (
                        f"{worst_risk.net_category} signal '{worst_net}' "
                        f"({worst_risk.risk_level} risk)"
                        if worst_risk else "Unknown"
                    )

                    regions.append(BoardRegionRisk(
                        region_name=f"Region ({gx},{gy})",
                        center_x_mm=round(cx, 1),
                        center_y_mm=round(cy, 1),
                        radius_mm=round(radius, 1),
                        risk_score=round(avg_risk, 1),
                        contributing_nets=contributing,
                        primary_concern=primary,
                    ))

        # Sort by risk score (highest first) and return top regions
        regions.sort(key=lambda r: r.risk_score, reverse=True)
        return regions[:10]

    def _estimate_loop_area(self, design_data, net) -> float:
        """Estimate loop area for a net when return path analysis is not available.

        Uses: total routed length x typical layer-to-plane distance.
        """
        traces = design_data.get_traces_on_net(net.index)
        if not traces:
            return 1.0  # Minimal default

        # Calculate total trace length
        total_length: float = sum(t.calc_length() for t in traces)

        # Estimate layer-to-plane distance
        # For a 4-layer board, typical is 0.2mm; for 2-layer, ~0.8mm
        if design_data.layer_count >= 4:
            layer_dist = 0.2
        elif design_data.layer_count >= 2:
            layer_dist = 0.8
        else:
            layer_dist = design_data.board_thickness_mm / 2

        return total_length * layer_dist

    def _assess_compliance(
        self,
        frequency_risks: list[FrequencyRisk],
        standard: str,
    ) -> dict:
        """Assess compliance against a standard.

        Returns dict with predicted pass/fail, margin, worst frequency.
        """
        if not frequency_risks:
            return {
                standard: {
                    "predicted_pass": True,
                    "margin_db": 100,
                    "worst_frequency_mhz": 0,
                    "notes": "No frequency data to analyze",
                }
            }

        worst = min(frequency_risks, key=lambda r: r.margin_db)

        return {
            standard: {
                "predicted_pass": worst.margin_db >= 0,
                "margin_db": round(worst.margin_db, 1),
                "worst_frequency_mhz": worst.frequency_mhz,
                "frequencies_over_limit": sum(
                    1 for r in frequency_risks if r.margin_db < 0
                ),
                "frequencies_marginal": sum(
                    1 for r in frequency_risks if 0 <= r.margin_db < 6
                ),
            }
        }

    def _build_executive_summary(self, result: EMIRiskResult, standard: str) -> str:
        """Build a concise executive summary of the EMI risk assessment."""
        parts = []

        # Overall status
        if result.overall_risk_level == "critical":
            parts.append(
                f"CRITICAL EMI RISK: Overall score {result.overall_risk_score}/100. "
                f"Predicted {standard} compliance failure."
            )
        elif result.overall_risk_level == "high":
            parts.append(
                f"HIGH EMI RISK: Overall score {result.overall_risk_score}/100. "
                "Design changes recommended before testing."
            )
        elif result.overall_risk_level == "medium":
            parts.append(
                f"MODERATE EMI RISK: Overall score {result.overall_risk_score}/100. "
                "Some improvements recommended."
            )
        else:
            parts.append(
                f"LOW EMI RISK: Overall score {result.overall_risk_score}/100. "
                f"Design appears likely to meet {standard} limits."
            )

        # Net summary
        total = len(result.net_risks)
        critical = sum(1 for r in result.net_risks if r.risk_level == "critical")
        high = sum(1 for r in result.net_risks if r.risk_level == "high")
        if critical > 0:
            parts.append(f"{critical} net(s) with critical EMI risk.")
        if high > 0:
            parts.append(f"{high} net(s) with high EMI risk.")
        parts.append(f"{total} signal net(s) analyzed.")

        # Problem frequencies
        if result.predicted_problem_frequencies_mhz:
            freq_strs = [
                f"{f:.0f}MHz" for f in result.predicted_problem_frequencies_mhz[:5]
            ]
            parts.append(
                f"Problem frequencies: {', '.join(freq_strs)}."
            )

        # Check sensitive bands
        sensitive_hits = []
        for fr in result.frequency_risks:
            if fr.margin_db < 6:
                for low, high, name in SENSITIVE_BANDS:
                    if low <= fr.frequency_mhz <= high:
                        sensitive_hits.append(name)
                        break

        if sensitive_hits:
            unique_hits = list(dict.fromkeys(sensitive_hits))
            parts.append(
                f"Emissions near sensitive bands: {', '.join(unique_hits[:3])}."
            )

        # Hot spots
        if result.board_regions:
            hottest = result.board_regions[0]
            parts.append(
                f"Highest risk region at ({hottest.center_x_mm:.0f}, "
                f"{hottest.center_y_mm:.0f})mm with {len(hottest.contributing_nets)} "
                "contributing net(s)."
            )

        return " ".join(parts)

    def _build_recommendations(self, result: EMIRiskResult) -> list[str]:
        """Build prioritized list of recommendations."""
        recs = []
        seen = set()

        # Collect from net risks (highest risk first)
        for net_risk in result.net_risks:
            for rec in net_risk.recommendations:
                if rec not in seen:
                    recs.append(rec)
                    seen.add(rec)
            if len(recs) >= 15:
                break

        # Add general recommendations based on overall assessment
        if result.overall_risk_level in ("critical", "high"):
            general = [
                "Consider adding a ground plane on an adjacent layer for all high-speed signals",
                "Add stitching vias along high-speed signal routes",
                "Review stackup for optimal reference plane placement",
                "Consider adding EMI filtering at board connectors",
            ]
            for rec in general:
                if rec not in seen:
                    recs.append(rec)
                    seen.add(rec)

        # Sensitive band warnings
        for fr in result.frequency_risks:
            if fr.margin_db < 6:
                for low, high, name in SENSITIVE_BANDS:
                    if low <= fr.frequency_mhz <= high:
                        rec = (
                            f"Emission near {name} band ({fr.frequency_mhz:.0f}MHz) "
                            f"with {fr.margin_db:.1f}dB margin. "
                            "Consider spread-spectrum clocking or additional filtering."
                        )
                        if rec not in seen:
                            recs.append(rec)
                            seen.add(rec)
                        break

        return recs

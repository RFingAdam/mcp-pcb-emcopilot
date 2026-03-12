"""Radiated emissions analyzer for EMC compliance"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import math


@dataclass
class EmissionsResult:
    """Results from radiated emissions analysis"""
    # Source identification
    source_id: str
    source_type: str  # clock, switching_regulator, high_speed_io, etc.
    description: str

    # Emission levels
    fundamental_frequency_mhz: float
    fundamental_emission_dbuv_m: float
    harmonics: List[Dict[str, float]]  # [{frequency_mhz, emission_dbuv_m, margin_db}]

    # Worst case
    worst_frequency_mhz: float
    worst_emission_dbuv_m: float
    worst_margin_db: float

    # Compliance assessment
    compliant: bool
    standard: str
    test_distance_m: float

    # Risk assessment
    risk_level: str  # pass, marginal, fail
    emc_score: float  # 0-100

    # Emission sources breakdown
    differential_mode_db: float
    common_mode_db: float
    dominant_mode: str

    # Recommendations
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    # Details
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EmissionSource:
    """Emission source definition"""
    name: str
    source_type: str  # clock, smps, ddr, pcie, etc.
    frequency_mhz: float
    signal_amplitude_v: float = 3.3
    rise_time_ns: float = 1.0
    duty_cycle: float = 0.5
    trace_length_mm: float = 50
    loop_area_mm2: float = 10
    cable_length_m: float = 0  # Attached cable


class EmissionsAnalyzer:
    """
    Radiated emissions analyzer for EMC pre-compliance.

    Estimates emissions from:
    - Clock signals and harmonics
    - Switching regulators
    - High-speed digital interfaces
    - Cable radiation

    Based on CISPR 22/32 and FCC Part 15 limits.
    """

    # Speed of light (m/s)
    C0 = 2.998e8

    # CISPR 22/32 Class B limits at 3m (dBuV/m)
    CISPR_CLASS_B = {
        30: 40, 50: 40, 100: 40, 150: 40, 200: 40, 230: 40,
        300: 47, 400: 47, 500: 47, 600: 47, 700: 47, 800: 47, 900: 47, 1000: 47,
    }

    # FCC Part 15 Class B limits at 3m (dBuV/m)
    FCC_CLASS_B = {
        30: 40, 50: 40, 88: 40, 100: 43.5, 150: 43.5, 200: 43.5, 216: 43.5,
        300: 46, 400: 46, 500: 46, 700: 46, 960: 46,
        1000: 54, 2000: 54, 5000: 54,
    }

    def __init__(self, standard: str = "cispr", distance_m: float = 3):
        """
        Initialize analyzer.

        Args:
            standard: EMC standard ("cispr" or "fcc")
            distance_m: Measurement distance
        """
        self.standard = standard.lower()
        self.distance_m = distance_m
        self.limits = self.CISPR_CLASS_B if self.standard == "cispr" else self.FCC_CLASS_B

    def analyze_source(
        self,
        source: EmissionSource,
        source_id: str = "E1",
        num_harmonics: int = 10,
    ) -> EmissionsResult:
        """
        Analyze emissions from a source.

        Args:
            source: Emission source definition
            source_id: Identifier for this source
            num_harmonics: Number of harmonics to analyze

        Returns:
            EmissionsResult with complete analysis
        """
        harmonics = []
        worst_margin = 100
        worst_freq = source.frequency_mhz
        worst_emission = -100

        # Calculate harmonic content based on signal shape
        harmonic_amplitudes = self._calculate_harmonic_amplitudes(
            source.duty_cycle,
            source.rise_time_ns,
            source.frequency_mhz,
            num_harmonics,
        )

        # Calculate emissions for each harmonic
        for n, amplitude_factor in enumerate(harmonic_amplitudes, 1):
            freq_mhz = source.frequency_mhz * n
            if freq_mhz > 6000:  # Stop at 6 GHz
                break

            # Differential mode emission (loop antenna)
            dm_emission = self._differential_mode_emission(
                source.loop_area_mm2,
                source.signal_amplitude_v * amplitude_factor,
                freq_mhz,
            )

            # Common mode emission (cable antenna)
            cm_emission = -100  # dBuV/m
            if source.cable_length_m > 0:
                cm_emission = self._common_mode_emission(
                    source.cable_length_m,
                    source.signal_amplitude_v * amplitude_factor,
                    freq_mhz,
                    source.trace_length_mm,
                )

            # Total emission (power sum)
            total_emission = self._power_sum_db([dm_emission, cm_emission])

            # Get limit
            limit = self._get_limit(freq_mhz)
            margin = limit - total_emission

            harmonics.append({
                "harmonic": n,
                "frequency_mhz": round(freq_mhz, 2),
                "emission_dbuv_m": round(total_emission, 1),
                "limit_dbuv_m": limit,
                "margin_db": round(margin, 1),
                "dm_contribution_db": round(dm_emission, 1),
                "cm_contribution_db": round(cm_emission, 1),
            })

            if margin < worst_margin:
                worst_margin = margin
                worst_freq = freq_mhz
                worst_emission = total_emission

        # Fundamental emissions
        fundamental_emission = harmonics[0]["emission_dbuv_m"] if harmonics else 0

        # Dominant mode
        if harmonics:
            avg_dm = sum(h["dm_contribution_db"] for h in harmonics) / len(harmonics)
            avg_cm = sum(h["cm_contribution_db"] for h in harmonics) / len(harmonics)
            dominant_mode = "differential" if avg_dm > avg_cm else "common"
        else:
            avg_dm = avg_cm = 0
            dominant_mode = "unknown"

        # Compliance and risk
        compliant = worst_margin >= 0
        if worst_margin >= 6:
            risk_level = "pass"
            score = 90 + min(10, worst_margin - 6)
        elif worst_margin >= 0:
            risk_level = "marginal"
            score = 70 + worst_margin * 3
        else:
            risk_level = "fail"
            score = max(0, 50 + worst_margin * 2)

        # Issues and recommendations
        issues = []
        recommendations = []

        if worst_margin < 0:
            issues.append(f"Exceeds {self.standard.upper()} limit by {-worst_margin:.1f}dB at {worst_freq:.1f}MHz")

        if worst_margin < 6:
            issues.append(f"Marginal compliance with only {worst_margin:.1f}dB margin")

        if dominant_mode == "common" and source.cable_length_m > 0:
            issues.append("Common mode emissions dominate - cable radiation issue")
            recommendations.append("Add common mode choke on cables")
            recommendations.append("Improve cable shield grounding")
        elif dominant_mode == "differential":
            recommendations.append("Reduce loop area in signal return path")
            recommendations.append("Add filtering at source")

        if source.rise_time_ns < 1:
            issues.append(f"Fast rise time ({source.rise_time_ns}ns) creates high harmonic content")
            recommendations.append("Slow edge rate if timing allows")
            recommendations.append("Use series resistors for edge rate control")

        # Check specific frequencies
        sensitive_freqs = [
            (88, 108, "FM broadcast band"),
            (470, 890, "TV broadcast band"),
            (824, 894, "Cellular 850"),
            (1710, 1990, "Cellular PCS"),
            (2400, 2500, "WiFi/Bluetooth 2.4GHz"),
            (5150, 5850, "WiFi 5GHz"),
        ]

        for low, high, name in sensitive_freqs:
            for h in harmonics:
                if low <= h["frequency_mhz"] <= high and h["margin_db"] < 6:
                    issues.append(f"Emission near {name} at {h['frequency_mhz']}MHz")
                    break

        return EmissionsResult(
            source_id=source_id,
            source_type=source.source_type,
            description=f"{source.name} @ {source.frequency_mhz}MHz",
            fundamental_frequency_mhz=source.frequency_mhz,
            fundamental_emission_dbuv_m=round(fundamental_emission, 1),
            harmonics=harmonics,
            worst_frequency_mhz=round(worst_freq, 2),
            worst_emission_dbuv_m=round(worst_emission, 1),
            worst_margin_db=round(worst_margin, 1),
            compliant=compliant,
            standard=self.standard.upper(),
            test_distance_m=self.distance_m,
            risk_level=risk_level,
            emc_score=round(max(0, min(100, score)), 1),
            differential_mode_db=round(avg_dm, 1),
            common_mode_db=round(avg_cm, 1),
            dominant_mode=dominant_mode,
            issues=issues,
            recommendations=recommendations,
            metrics={
                "rise_time_ns": source.rise_time_ns,
                "bandwidth_mhz": 350 / source.rise_time_ns,
                "loop_area_mm2": source.loop_area_mm2,
                "cable_length_m": source.cable_length_m,
            },
        )

    def _calculate_harmonic_amplitudes(
        self,
        duty_cycle: float,
        rise_time_ns: float,
        frequency_mhz: float,
        num_harmonics: int,
    ) -> List[float]:
        """
        Calculate relative amplitude of harmonics.

        Based on trapezoidal wave Fourier series.
        """
        amplitudes = []
        bandwidth_mhz = 350 / rise_time_ns  # -3dB bandwidth

        for n in range(1, num_harmonics + 1):
            freq = frequency_mhz * n

            # Duty cycle envelope
            if n == 1:
                dc_factor = 1.0
            else:
                dc_factor = abs(math.sin(n * math.pi * duty_cycle) / (n * math.pi * duty_cycle))
                if dc_factor == 0:
                    dc_factor = 0.001

            # Rise time envelope (-20dB/decade above bandwidth)
            if freq <= bandwidth_mhz:
                rt_factor = 1.0
            else:
                rt_factor = bandwidth_mhz / freq

            amplitudes.append(dc_factor * rt_factor)

        return amplitudes

    def _differential_mode_emission(
        self,
        loop_area_mm2: float,
        voltage_v: float,
        frequency_mhz: float,
    ) -> float:
        """
        Calculate differential mode emission from loop antenna.

        E = (1.316e-14 × A × I × f²) / d
        Assuming 50 ohm load: I = V / 50
        """
        current_a = voltage_v / 50  # Simplified
        area_m2 = loop_area_mm2 * 1e-6
        freq_hz = frequency_mhz * 1e6

        e_field = (1.316e-14 * area_m2 * current_a * freq_hz**2) / self.distance_m

        if e_field > 0:
            return 20 * math.log10(e_field * 1e6)
        return -100

    def _common_mode_emission(
        self,
        cable_length_m: float,
        voltage_v: float,
        frequency_mhz: float,
        source_trace_mm: float,
    ) -> float:
        """
        Calculate common mode emission from cable as monopole.

        E ≈ (f × I_cm × L) / d × factor
        """
        wavelength_m = 300 / frequency_mhz

        # Common mode current (estimate based on imbalance)
        # Assume 1-10% of signal current becomes common mode
        i_dm = voltage_v / 50
        imbalance_factor = 0.05  # 5% imbalance
        i_cm = i_dm * imbalance_factor

        # Cable electrical length factor
        if cable_length_m < wavelength_m / 4:
            length_factor = cable_length_m / (wavelength_m / 4)
        else:
            length_factor = 1.0  # Resonant or longer

        # Source coupling factor (longer traces = more CM)
        source_factor = min(1.0, source_trace_mm / 50)

        # Approximate field strength
        e_field = (frequency_mhz * 1e6 * i_cm * cable_length_m * length_factor * source_factor) / \
                  (self.distance_m * 2e9)

        if e_field > 0:
            return 20 * math.log10(e_field * 1e6)
        return -100

    def _get_limit(self, frequency_mhz: float) -> float:
        """Get emission limit for frequency."""
        # Find closest frequency in limit table
        freqs = sorted(self.limits.keys())
        for i, f in enumerate(freqs):
            if frequency_mhz <= f:
                return self.limits[f]
        return self.limits[freqs[-1]]

    def _power_sum_db(self, values_db: List[float]) -> float:
        """Sum power values in dB."""
        linear_sum = sum(10 ** (v / 10) for v in values_db if v > -90)
        if linear_sum > 0:
            return 10 * math.log10(linear_sum)
        return -100

    def analyze_board(
        self,
        sources: List[EmissionSource],
    ) -> Dict[str, Any]:
        """
        Analyze all emission sources on a board.

        Args:
            sources: List of emission sources

        Returns:
            Combined analysis results
        """
        results = []
        all_harmonics = []

        for i, source in enumerate(sources):
            result = self.analyze_source(source, source_id=f"E{i+1}")
            results.append(result)
            all_harmonics.extend(result.harmonics)

        # Find worst case across all sources
        if all_harmonics:
            worst = min(all_harmonics, key=lambda h: h["margin_db"])
            overall_margin = worst["margin_db"]
            overall_worst_freq = worst["frequency_mhz"]
        else:
            overall_margin = 100
            overall_worst_freq = 0

        # Count issues
        num_fails = sum(1 for r in results if r.risk_level == "fail")
        num_marginal = sum(1 for r in results if r.risk_level == "marginal")

        return {
            "total_sources": len(sources),
            "sources_failing": num_fails,
            "sources_marginal": num_marginal,
            "sources_passing": len(sources) - num_fails - num_marginal,
            "overall_margin_db": round(overall_margin, 1),
            "worst_frequency_mhz": round(overall_worst_freq, 2),
            "compliant": num_fails == 0,
            "results": results,
            "recommendations": list(set(r for res in results for r in res.recommendations)),
        }

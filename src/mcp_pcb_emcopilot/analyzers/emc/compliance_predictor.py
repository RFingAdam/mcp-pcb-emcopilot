"""Predictive EMC Compliance Analyzer.

Predicts electromagnetic compliance for various standards:
- FCC Part 15 (Class A/B)
- CISPR 22/32
- EN 55032
- Automotive EMC (CISPR 25)

Uses analytical methods to estimate radiated emissions based on:
- Clock frequencies and harmonics
- Trace lengths vs wavelength
- Cable lengths and shielding effectiveness
- PCB stackup and shielding
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class EMCStandard(str, Enum):
    """EMC compliance standards."""
    FCC_CLASS_A = "fcc_class_a"
    FCC_CLASS_B = "fcc_class_b"
    CISPR_22_CLASS_A = "cispr_22_class_a"
    CISPR_22_CLASS_B = "cispr_22_class_b"
    CISPR_32_CLASS_A = "cispr_32_class_a"
    CISPR_32_CLASS_B = "cispr_32_class_b"
    EN_55032_CLASS_A = "en_55032_class_a"
    EN_55032_CLASS_B = "en_55032_class_b"
    CISPR_25 = "cispr_25"  # Automotive


class EmissionType(str, Enum):
    """Types of EMI emissions."""
    RADIATED = "radiated"
    CONDUCTED = "conducted"


@dataclass
class ClockSource:
    """Clock source in the design."""
    name: str
    frequency_mhz: float
    amplitude_v: float = 3.3
    rise_time_ns: float = 1.0
    duty_cycle: float = 0.5
    trace_length_mm: float = 0.0
    is_differential: bool = False
    has_spread_spectrum: bool = False


@dataclass
class CableInterface:
    """External cable interface."""
    name: str
    cable_length_m: float
    is_shielded: bool = False
    shield_effectiveness_db: float = 0.0
    connector_type: str = "unknown"
    signal_frequency_mhz: float = 0.0


@dataclass
class EmissionPrediction:
    """Predicted emission at a frequency."""
    frequency_mhz: float
    predicted_level_dbuv_m: float
    limit_dbuv_m: float
    margin_db: float
    source: str
    mechanism: str  # clock_harmonic, trace_antenna, cable_radiation
    compliant: bool
    confidence: float = 0.8


@dataclass
class ComplianceResult:
    """Complete EMC compliance prediction result."""
    standard: EMCStandard
    emission_type: EmissionType

    # Overall prediction
    compliant: bool
    confidence: float
    margin_db: float  # Worst-case margin

    # Individual predictions
    predictions: list[EmissionPrediction] = field(default_factory=list)

    # Risk areas
    critical_frequencies: list[float] = field(default_factory=list)
    high_risk_sources: list[str] = field(default_factory=list)

    # Recommendations
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "standard": self.standard.value,
            "emission_type": self.emission_type.value,
            "compliant": self.compliant,
            "confidence": round(self.confidence, 2),
            "margin_db": round(self.margin_db, 1),
            "predictions": [
                {
                    "frequency_mhz": p.frequency_mhz,
                    "predicted_level_dbuv_m": round(p.predicted_level_dbuv_m, 1),
                    "limit_dbuv_m": round(p.limit_dbuv_m, 1),
                    "margin_db": round(p.margin_db, 1),
                    "source": p.source,
                    "mechanism": p.mechanism,
                    "compliant": p.compliant,
                }
                for p in self.predictions
            ],
            "critical_frequencies": self.critical_frequencies,
            "high_risk_sources": self.high_risk_sources,
            "recommendations": self.recommendations,
        }


# EMC emission limits in dBuV/m at 3m (radiated)
# Format: (freq_min_mhz, freq_max_mhz, limit_dbuv_m)
EMC_LIMITS = {
    EMCStandard.FCC_CLASS_A: [
        (30, 88, 49.5),
        (88, 216, 54.0),
        (216, 960, 56.9),
        (960, 40000, 60.0),
    ],
    EMCStandard.FCC_CLASS_B: [
        (30, 88, 40.0),
        (88, 216, 43.5),
        (216, 960, 46.0),
        (960, 40000, 54.0),
    ],
    EMCStandard.CISPR_32_CLASS_A: [
        (30, 230, 50.0),
        (230, 1000, 57.0),
        (1000, 6000, 60.0),
    ],
    EMCStandard.CISPR_32_CLASS_B: [
        (30, 230, 40.0),
        (230, 1000, 47.0),
        (1000, 6000, 54.0),
    ],
    EMCStandard.EN_55032_CLASS_A: [
        (30, 230, 50.0),
        (230, 1000, 57.0),
        (1000, 6000, 60.0),
    ],
    EMCStandard.EN_55032_CLASS_B: [
        (30, 230, 40.0),
        (230, 1000, 47.0),
        (1000, 6000, 54.0),
    ],
    EMCStandard.CISPR_25: [
        (150, 300, 34.0),  # Average limits
        (300, 1000, 34.0),
        (1000, 2500, 45.0),
    ],
}


class EMCCompliancePredictor:
    """Predictive EMC compliance analyzer.

    Estimates radiated emissions based on design characteristics
    and predicts compliance with various EMC standards.

    Usage:
        predictor = EMCCompliancePredictor()

        # Add clock sources
        predictor.add_clock(ClockSource(
            name="CPU_CLK",
            frequency_mhz=100,
            trace_length_mm=50,
        ))

        # Predict compliance
        result = predictor.predict_compliance(EMCStandard.FCC_CLASS_B)
    """

    # Speed of light in mm/ns
    C_MM_NS = 299.792458

    # Typical trace efficiency as antenna (0.1 = 10%)
    TRACE_ANTENNA_EFFICIENCY = 0.1

    def __init__(self):
        self.clocks: list[ClockSource] = []
        self.cables: list[CableInterface] = []
        self.pcb_shielding_db: float = 0.0
        self.enclosure_shielding_db: float = 0.0

    def add_clock(self, clock: ClockSource) -> None:
        """Add a clock source to analyze."""
        self.clocks.append(clock)

    def add_cable(self, cable: CableInterface) -> None:
        """Add an external cable interface."""
        self.cables.append(cable)

    def set_shielding(
        self,
        pcb_shielding_db: float = 0.0,
        enclosure_shielding_db: float = 0.0,
    ) -> None:
        """Set shielding effectiveness values."""
        self.pcb_shielding_db = pcb_shielding_db
        self.enclosure_shielding_db = enclosure_shielding_db

    def predict_compliance(
        self,
        standard: EMCStandard,
        emission_type: EmissionType = EmissionType.RADIATED,
        test_distance_m: float = 3.0,
    ) -> ComplianceResult:
        """Predict EMC compliance for a standard.

        Args:
            standard: EMC standard to check against
            emission_type: Type of emission to analyze
            test_distance_m: Measurement distance in meters

        Returns:
            ComplianceResult with predictions and recommendations
        """
        predictions = []
        critical_freqs = []
        high_risk = []

        # Get limits for this standard
        limits = EMC_LIMITS.get(standard, EMC_LIMITS[EMCStandard.FCC_CLASS_B])

        # Analyze each clock source
        for clock in self.clocks:
            clock_predictions = self._analyze_clock_emissions(
                clock, limits, test_distance_m
            )
            predictions.extend(clock_predictions)

            # Track high-risk sources
            for pred in clock_predictions:
                if not pred.compliant:
                    if clock.name not in high_risk:
                        high_risk.append(clock.name)
                    if pred.frequency_mhz not in critical_freqs:
                        critical_freqs.append(pred.frequency_mhz)

        # Analyze cable radiation
        for cable in self.cables:
            cable_predictions = self._analyze_cable_emissions(
                cable, limits, test_distance_m
            )
            predictions.extend(cable_predictions)

            for pred in cable_predictions:
                if not pred.compliant:
                    if cable.name not in high_risk:
                        high_risk.append(cable.name)
                    if pred.frequency_mhz not in critical_freqs:
                        critical_freqs.append(pred.frequency_mhz)

        # Calculate overall compliance
        compliant = all(p.compliant for p in predictions)
        worst_margin = min((p.margin_db for p in predictions), default=20.0)

        # Calculate confidence based on available data
        confidence = self._calculate_confidence()

        # Generate recommendations
        recommendations = self._generate_recommendations(
            predictions, high_risk, critical_freqs, standard
        )

        return ComplianceResult(
            standard=standard,
            emission_type=emission_type,
            compliant=compliant,
            confidence=confidence,
            margin_db=worst_margin,
            predictions=predictions,
            critical_frequencies=sorted(critical_freqs),
            high_risk_sources=high_risk,
            recommendations=recommendations,
        )

    def _analyze_clock_emissions(
        self,
        clock: ClockSource,
        limits: list[tuple],
        test_distance_m: float,
    ) -> list[EmissionPrediction]:
        """Analyze emissions from a clock source."""
        predictions = []

        # Calculate harmonics to analyze (up to 50th or max limit freq)
        max_freq = max(limit[1] for limit in limits)
        max_harmonic = min(50, int(max_freq / clock.frequency_mhz))

        for n in range(1, max_harmonic + 1):
            freq_mhz = n * clock.frequency_mhz

            # Get limit at this frequency
            limit_dbuv_m = self._get_limit_at_frequency(freq_mhz, limits)
            if limit_dbuv_m is None:
                continue

            # Calculate harmonic amplitude
            # Trapezoidal wave harmonics: sin(n*pi*D) / (n*pi*D) envelope
            duty = clock.duty_cycle
            if n == 1:
                harmonic_amplitude = clock.amplitude_v * 2 / math.pi
            else:
                # Envelope follows sinc function
                x = n * math.pi * duty
                if abs(math.sin(x)) < 0.001:
                    harmonic_amplitude = 0
                else:
                    harmonic_amplitude = clock.amplitude_v * 2 * abs(math.sin(x)) / (n * math.pi)

            # Rise time effect: 1/(1 + (f/f_knee)^2) where f_knee = 0.35/t_rise
            f_knee_mhz = 350 / clock.rise_time_ns
            rise_time_factor = 1 / math.sqrt(1 + (freq_mhz / f_knee_mhz)**2)
            harmonic_amplitude *= rise_time_factor

            # Spread spectrum reduction (typically 6-10 dB)
            if clock.has_spread_spectrum:
                harmonic_amplitude *= 0.25  # ~12 dB reduction

            # Trace as radiating antenna
            wavelength_mm = self.C_MM_NS * 1000 / freq_mhz
            electrical_length = clock.trace_length_mm / wavelength_mm

            # Radiation efficiency increases with electrical length
            if electrical_length < 0.1:
                radiation_efficiency = electrical_length * self.TRACE_ANTENNA_EFFICIENCY
            else:
                radiation_efficiency = min(0.5, electrical_length * self.TRACE_ANTENNA_EFFICIENCY * 2)

            # Differential mode reduction
            if clock.is_differential:
                radiation_efficiency *= 0.1  # 20 dB reduction

            # Calculate field strength at test distance
            # E = (120*pi * I * L * f) / (c * r) for short dipole
            # Simplified: E proportional to V * efficiency / distance
            power_factor = harmonic_amplitude * radiation_efficiency

            # Convert to field strength in uV/m
            field_uv_m = power_factor * 1e6 / test_distance_m

            # Apply shielding
            total_shielding_db = self.pcb_shielding_db + self.enclosure_shielding_db
            field_uv_m *= 10**(-total_shielding_db / 20)

            # Convert to dBuV/m
            if field_uv_m > 0:
                level_dbuv_m = 20 * math.log10(field_uv_m)
            else:
                level_dbuv_m = -40  # Very low

            # Calculate margin
            margin_db = limit_dbuv_m - level_dbuv_m

            predictions.append(EmissionPrediction(
                frequency_mhz=freq_mhz,
                predicted_level_dbuv_m=level_dbuv_m,
                limit_dbuv_m=limit_dbuv_m,
                margin_db=margin_db,
                source=clock.name,
                mechanism="clock_harmonic",
                compliant=margin_db >= 0,
                confidence=0.7 if electrical_length < 0.25 else 0.5,
            ))

        return predictions

    def _analyze_cable_emissions(
        self,
        cable: CableInterface,
        limits: list[tuple],
        test_distance_m: float,
    ) -> list[EmissionPrediction]:
        """Analyze emissions from cable interfaces."""
        predictions = []

        # Cable acts as antenna at frequencies where length is significant
        # fraction of wavelength
        cable_length_mm = cable.cable_length_m * 1000

        # Analyze at cable resonance frequencies and signal frequency
        analyze_freqs = []

        # First cable resonance (lambda/4)
        resonance_mhz = self.C_MM_NS * 250 / cable_length_mm
        analyze_freqs.append(resonance_mhz)

        # Second resonance (lambda/2)
        analyze_freqs.append(resonance_mhz * 2)

        # Signal frequency and harmonics
        if cable.signal_frequency_mhz > 0:
            for n in range(1, 6):
                analyze_freqs.append(cable.signal_frequency_mhz * n)

        for freq_mhz in analyze_freqs:
            limit_dbuv_m = self._get_limit_at_frequency(freq_mhz, limits)
            if limit_dbuv_m is None:
                continue

            # Estimate cable radiation
            wavelength_mm = self.C_MM_NS * 1000 / freq_mhz
            electrical_length = cable_length_mm / wavelength_mm

            # Base radiation level (empirical)
            base_level_dbuv_m = 30 + 10 * math.log10(1 + electrical_length)

            # Shielding reduction
            if cable.is_shielded:
                base_level_dbuv_m -= cable.shield_effectiveness_db
            else:
                # Unshielded cable can be significant radiator
                base_level_dbuv_m += 10

            # Enclosure shielding
            base_level_dbuv_m -= self.enclosure_shielding_db

            margin_db = limit_dbuv_m - base_level_dbuv_m

            predictions.append(EmissionPrediction(
                frequency_mhz=freq_mhz,
                predicted_level_dbuv_m=base_level_dbuv_m,
                limit_dbuv_m=limit_dbuv_m,
                margin_db=margin_db,
                source=cable.name,
                mechanism="cable_radiation",
                compliant=margin_db >= 0,
                confidence=0.5,
            ))

        return predictions

    def _get_limit_at_frequency(
        self, freq_mhz: float, limits: list[tuple[float, float, float]]
    ) -> float | None:
        """Get emission limit at a specific frequency."""
        for freq_min, freq_max, limit in limits:
            if freq_min <= freq_mhz <= freq_max:
                return limit
        return None

    def _calculate_confidence(self) -> float:
        """Calculate prediction confidence based on available data."""
        confidence = 0.5  # Base confidence

        # More clocks analyzed = more confidence
        if len(self.clocks) > 0:
            confidence += 0.1

        # Detailed clock info increases confidence
        for clock in self.clocks:
            if clock.trace_length_mm > 0:
                confidence += 0.05
            if clock.rise_time_ns > 0:
                confidence += 0.05

        # Cable info
        if len(self.cables) > 0:
            confidence += 0.1

        # Shielding info
        if self.enclosure_shielding_db > 0:
            confidence += 0.1

        return min(0.9, confidence)

    def _generate_recommendations(
        self,
        predictions: list[EmissionPrediction],
        high_risk: list[str],
        critical_freqs: list[float],
        standard: EMCStandard,
    ) -> list[str]:
        """Generate EMC improvement recommendations."""
        recommendations = []

        # Check for failures
        failed = [p for p in predictions if not p.compliant]

        if not failed:
            recommendations.append(
                f"Design predicted to comply with {standard.value} with margin"
            )
            return recommendations

        # Recommendations based on failure mechanisms
        clock_failures = [p for p in failed if p.mechanism == "clock_harmonic"]
        cable_failures = [p for p in failed if p.mechanism == "cable_radiation"]

        if clock_failures:
            # Find the worst clock source
            worst_source = max(clock_failures, key=lambda p: -p.margin_db).source

            recommendations.append(
                f"Critical: Clock source '{worst_source}' exceeds limits - "
                "consider spread spectrum, shorter traces, or better return path"
            )

            # Specific recommendations
            for clock in self.clocks:
                if clock.name in high_risk:
                    if not clock.has_spread_spectrum:
                        recommendations.append(
                            f"Add spread spectrum to {clock.name} (expect 6-10 dB improvement)"
                        )
                    if clock.trace_length_mm > 50:
                        recommendations.append(
                            f"Reduce {clock.name} trace length from {clock.trace_length_mm:.0f}mm"
                        )
                    if not clock.is_differential and clock.frequency_mhz > 50:
                        recommendations.append(
                            f"Consider differential routing for {clock.name}"
                        )

        if cable_failures:
            recommendations.append(
                "Cable interfaces are significant emission sources - "
                "improve cable shielding or add common-mode filtering"
            )

            for cable in self.cables:
                if cable.name in high_risk:
                    if not cable.is_shielded:
                        recommendations.append(
                            f"Use shielded cable for {cable.name} interface"
                        )
                    else:
                        recommendations.append(
                            f"Improve {cable.name} cable shield termination - "
                            "use 360-degree bonding"
                        )

        # General recommendations
        if self.enclosure_shielding_db < 20:
            recommendations.append(
                "Consider metal enclosure or shielded PCB can for additional attenuation"
            )

        # Frequency-specific
        if any(f > 1000 for f in critical_freqs):
            recommendations.append(
                "High-frequency emissions (>1GHz) detected - verify PCB stackup provides "
                "continuous reference planes under high-speed signals"
            )

        return recommendations

    def estimate_chamber_margin(
        self,
        result: ComplianceResult,
        chamber_uncertainty_db: float = 4.0,
    ) -> float:
        """Estimate margin needed for chamber test pass.

        Real-world testing has measurement uncertainty. Adds safety margin
        to prediction to estimate actual test outcome.

        Args:
            result: Compliance prediction result
            chamber_uncertainty_db: Typical measurement uncertainty

        Returns:
            Estimated margin with chamber uncertainty factored in
        """
        return result.margin_db - chamber_uncertainty_db


def quick_compliance_check(
    clock_frequencies_mhz: list[float],
    trace_lengths_mm: list[float],
    standard: EMCStandard = EMCStandard.FCC_CLASS_B,
) -> ComplianceResult:
    """Quick compliance check with minimal input.

    Convenience function for fast EMC screening.

    Args:
        clock_frequencies_mhz: List of clock frequencies
        trace_lengths_mm: Corresponding trace lengths
        standard: EMC standard to check

    Returns:
        ComplianceResult with predictions
    """
    predictor = EMCCompliancePredictor()

    for i, (freq, length) in enumerate(zip(clock_frequencies_mhz, trace_lengths_mm)):
        predictor.add_clock(ClockSource(
            name=f"CLK{i}",
            frequency_mhz=freq,
            trace_length_mm=length,
        ))

    return predictor.predict_compliance(standard)

"""Automotive EMC standards analysis — CISPR 25 and ISO 11452."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# CISPR 25 radiated emission limits (dBuV/m @ 1m, peak detector, ALSE method)
# Representative limits per class (simplified from CISPR 25:2021)
CISPR25_RADIATED_LIMITS: list[dict] = [
    {"freq_min_mhz": 0.15, "freq_max_mhz": 0.3, "limits": {1: 52, 2: 42, 3: 32, 4: 22, 5: 12}},
    {"freq_min_mhz": 0.53, "freq_max_mhz": 2.0, "limits": {1: 46, 2: 36, 3: 26, 4: 16, 5: 6}},
    {"freq_min_mhz": 5.9, "freq_max_mhz": 6.2, "limits": {1: 40, 2: 30, 3: 20, 4: 10, 5: 0}},
    {"freq_min_mhz": 30, "freq_max_mhz": 54, "limits": {1: 44, 2: 34, 3: 24, 4: 14, 5: 4}},
    {"freq_min_mhz": 70, "freq_max_mhz": 108, "limits": {1: 38, 2: 28, 3: 18, 4: 8, 5: -2}},
    {"freq_min_mhz": 144, "freq_max_mhz": 172, "limits": {1: 32, 2: 22, 3: 12, 4: 2, 5: -8}},
    {"freq_min_mhz": 420, "freq_max_mhz": 512, "limits": {1: 32, 2: 22, 3: 12, 4: 2, 5: -8}},
    {"freq_min_mhz": 820, "freq_max_mhz": 960, "limits": {1: 32, 2: 22, 3: 12, 4: 2, 5: -8}},
    {"freq_min_mhz": 1400, "freq_max_mhz": 2500, "limits": {1: 36, 2: 26, 3: 16, 4: 6, 5: -4}},
]

# CISPR 25 conducted emission limits (dBuV, voltage method on power leads)
CISPR25_CONDUCTED_LIMITS: list[dict] = [
    {"freq_min_mhz": 0.15, "freq_max_mhz": 0.3,
     "limits": {1: {"peak": 90, "avg": 80}, 2: {"peak": 80, "avg": 70}, 3: {"peak": 70, "avg": 60}, 4: {"peak": 60, "avg": 50}, 5: {"peak": 50, "avg": 40}}},
    {"freq_min_mhz": 0.53, "freq_max_mhz": 1.8,
     "limits": {1: {"peak": 80, "avg": 70}, 2: {"peak": 70, "avg": 60}, 3: {"peak": 60, "avg": 50}, 4: {"peak": 50, "avg": 40}, 5: {"peak": 40, "avg": 30}}},
    {"freq_min_mhz": 5.9, "freq_max_mhz": 6.2,
     "limits": {1: {"peak": 70, "avg": 60}, 2: {"peak": 60, "avg": 50}, 3: {"peak": 50, "avg": 40}, 4: {"peak": 40, "avg": 30}, 5: {"peak": 30, "avg": 20}}},
    {"freq_min_mhz": 30, "freq_max_mhz": 108,
     "limits": {1: {"peak": 60, "avg": 50}, 2: {"peak": 50, "avg": 40}, 3: {"peak": 40, "avg": 30}, 4: {"peak": 30, "avg": 20}, 5: {"peak": 20, "avg": 10}}},
]

# ISO 11452 BCI test levels (bulk current injection)
ISO11452_BCI_LEVELS: dict[int, dict] = {
    1: {"current_ma": 1, "description": "Level I -- lowest"},
    2: {"current_ma": 3, "description": "Level II"},
    3: {"current_ma": 10, "description": "Level III -- typical automotive"},
    4: {"current_ma": 30, "description": "Level IV -- high"},
    5: {"current_ma": 100, "description": "Level V -- highest"},
}

# ISO 11452-2 field strength immunity levels (V/m)
ISO11452_FIELD_LEVELS: dict[int, dict] = {
    1: {"field_strength_vm": 1, "description": "Level I -- lowest"},
    2: {"field_strength_vm": 3, "description": "Level II"},
    3: {"field_strength_vm": 10, "description": "Level III -- typical automotive"},
    4: {"field_strength_vm": 30, "description": "Level IV -- high"},
    5: {"field_strength_vm": 60, "description": "Level V -- highest"},
}


@dataclass
class AutomotiveComplianceResult:
    standard: str  # "CISPR 25" or "ISO 11452"
    category: str  # "radiated", "conducted", "immunity"
    test_class: int
    frequency_mhz: float
    limit_value: float
    limit_unit: str
    predicted_value: Optional[float] = None
    margin_db: Optional[float] = None
    status: str = "unknown"  # "pass", "marginal", "fail", "unknown"
    recommendation: str = ""


@dataclass
class AutomotiveEMCAnalysis:
    findings: list[AutomotiveComplianceResult] = field(default_factory=list)
    overall_status: str = "unknown"
    cispr25_class: int = 3
    iso11452_level: int = 3
    recommendations: list[str] = field(default_factory=list)
    score: float = 0.0


class AutomotiveEMCAnalyzer:
    """Analyze PCB designs against automotive EMC standards."""

    def get_cispr25_limit(
        self, frequency_mhz: float, cispr_class: int = 3, category: str = "radiated",
    ) -> Optional[dict]:
        """Look up CISPR 25 limit for a frequency and class."""
        if cispr_class < 1 or cispr_class > 5:
            return None

        limits_table = CISPR25_RADIATED_LIMITS if category == "radiated" else CISPR25_CONDUCTED_LIMITS

        for entry in limits_table:
            if entry["freq_min_mhz"] <= frequency_mhz <= entry["freq_max_mhz"]:
                limit_data = entry["limits"].get(cispr_class)
                if limit_data is None:
                    return None
                if isinstance(limit_data, dict):
                    return {
                        "frequency_mhz": frequency_mhz,
                        "class": cispr_class,
                        "category": category,
                        "peak_limit_dbuv": limit_data["peak"],
                        "avg_limit_dbuv": limit_data["avg"],
                        "freq_range": f"{entry['freq_min_mhz']}-{entry['freq_max_mhz']} MHz",
                    }
                else:
                    return {
                        "frequency_mhz": frequency_mhz,
                        "class": cispr_class,
                        "category": category,
                        "limit_dbuvm": limit_data,
                        "freq_range": f"{entry['freq_min_mhz']}-{entry['freq_max_mhz']} MHz",
                    }
        return None

    def get_iso11452_level(self, level: int = 3) -> Optional[dict]:
        """Get ISO 11452 immunity test level parameters."""
        if level < 1 or level > 5:
            return None
        field_info = ISO11452_FIELD_LEVELS.get(level, {})
        bci_info = ISO11452_BCI_LEVELS.get(level, {})
        return {
            "level": level,
            "field_strength_vm": field_info.get("field_strength_vm"),
            "bci_current_ma": bci_info.get("current_ma"),
            "description": field_info.get("description", ""),
        }

    def predict_cispr25_compliance(
        self,
        clock_frequencies_mhz: list[float],
        trace_lengths_mm: Optional[list[float]] = None,
        shielding_db: float = 0.0,
        cispr_class: int = 3,
    ) -> list[AutomotiveComplianceResult]:
        """Predict CISPR 25 compliance for clock harmonics."""
        results = []

        if trace_lengths_mm is None:
            trace_lengths_mm = [50.0] * len(clock_frequencies_mhz)

        for i, f_clk in enumerate(clock_frequencies_mhz):
            trace_len = trace_lengths_mm[min(i, len(trace_lengths_mm) - 1)]

            # Check fundamental and harmonics up to 2500 MHz
            for harmonic in range(1, 20):
                f_harm = f_clk * harmonic
                if f_harm > 2500:
                    break

                limit_info = self.get_cispr25_limit(f_harm, cispr_class, "radiated")
                if limit_info is None:
                    continue

                limit_dbuvm = limit_info.get("limit_dbuvm", 0)

                # Estimate emission: simplified model
                # E = (2.6e-5 * f^2 * I * A) / r  for small loop
                # Approximate using trace as electrically short monopole
                wavelength_mm = 3e11 / (f_harm * 1e6)
                electrical_length = trace_len / wavelength_mm

                # Harmonic amplitude rolls off at ~20 dB/decade for trapezoidal
                harmonic_rolloff_db = 0 if harmonic == 1 else -20 * math.log10(harmonic)

                # Base emission estimate (empirical, calibrated to typical PCBs)
                base_emission_dbuvm = 40 + 20 * math.log10(f_harm) + 20 * math.log10(max(electrical_length, 0.01))
                predicted_dbuvm = base_emission_dbuvm + harmonic_rolloff_db - shielding_db

                margin = limit_dbuvm - predicted_dbuvm

                if margin > 6:
                    status = "pass"
                elif margin > 0:
                    status = "marginal"
                else:
                    status = "fail"

                rec = ""
                if status == "fail":
                    rec = f"Harmonic {harmonic} of {f_clk}MHz clock exceeds CISPR 25 Class {cispr_class} by {abs(margin):.1f}dB. Consider spread-spectrum clocking, shielding, or shorter traces."
                elif status == "marginal":
                    rec = f"Harmonic {harmonic} of {f_clk}MHz clock has only {margin:.1f}dB margin. Add filtering or reduce trace length."

                results.append(AutomotiveComplianceResult(
                    standard="CISPR 25",
                    category="radiated",
                    test_class=cispr_class,
                    frequency_mhz=f_harm,
                    limit_value=limit_dbuvm,
                    limit_unit="dBuV/m",
                    predicted_value=round(predicted_dbuvm, 1),
                    margin_db=round(margin, 1),
                    status=status,
                    recommendation=rec,
                ))

        return results

    def analyze_automotive_design(
        self,
        clock_frequencies_mhz: list[float],
        cispr_class: int = 3,
        iso_level: int = 3,
        has_shielding: bool = False,
        has_input_filter: bool = False,
    ) -> AutomotiveEMCAnalysis:
        """Full automotive EMC analysis."""
        shielding_db = 20.0 if has_shielding else 0.0

        # Run CISPR 25 prediction
        cispr_results = self.predict_cispr25_compliance(
            clock_frequencies_mhz, shielding_db=shielding_db, cispr_class=cispr_class,
        )

        analysis = AutomotiveEMCAnalysis(
            findings=cispr_results,
            cispr25_class=cispr_class,
            iso11452_level=iso_level,
        )

        # Determine overall status
        statuses = [r.status for r in cispr_results]
        if "fail" in statuses:
            analysis.overall_status = "fail"
        elif "marginal" in statuses:
            analysis.overall_status = "marginal"
        elif statuses:
            analysis.overall_status = "pass"

        # Calculate score
        if cispr_results:
            pass_count = sum(1 for r in cispr_results if r.status == "pass")
            analysis.score = round(pass_count / len(cispr_results) * 100, 1)

        # Generate recommendations
        if not has_shielding:
            analysis.recommendations.append(
                "Consider adding a metallic enclosure or board-level shielding can for EMC-critical circuits."
            )
        if not has_input_filter:
            analysis.recommendations.append(
                "Add input power line filter (common-mode choke + capacitors) for conducted emission compliance."
            )
        if any(f > 100 for f in clock_frequencies_mhz):
            analysis.recommendations.append(
                "High-frequency clocks (>100MHz) detected. Use spread-spectrum clocking (SSC) to reduce peak emissions by 10-15 dB."
            )

        iso_info = self.get_iso11452_level(iso_level)
        if iso_info and iso_info.get("field_strength_vm", 0) >= 10:
            analysis.recommendations.append(
                f"ISO 11452 Level {iso_level} ({iso_info['field_strength_vm']} V/m) requires robust immunity. "
                "Ensure all I/O lines have TVS protection and decoupling at connector entry points."
            )

        return analysis

    def to_dict(self, analysis: AutomotiveEMCAnalysis) -> dict:
        """Convert analysis to dict for tool output."""
        return {
            "overall_status": analysis.overall_status,
            "score": analysis.score,
            "cispr25_class": analysis.cispr25_class,
            "iso11452_level": analysis.iso11452_level,
            "findings_count": len(analysis.findings),
            "findings": [
                {
                    "standard": f.standard,
                    "category": f.category,
                    "frequency_mhz": f.frequency_mhz,
                    "limit": f"{f.limit_value} {f.limit_unit}",
                    "predicted": f"{f.predicted_value} {f.limit_unit}" if f.predicted_value is not None else None,
                    "margin_db": f.margin_db,
                    "status": f.status,
                    "recommendation": f.recommendation,
                }
                for f in analysis.findings
                if f.status in ("fail", "marginal")  # Only report issues
            ],
            "recommendations": analysis.recommendations,
        }

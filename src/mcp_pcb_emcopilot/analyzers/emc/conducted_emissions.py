"""Conducted emissions analysis — LISN model, CISPR 25 & FCC Part 15 Subpart B.

Predicts conducted emissions from SMPS switching waveforms through a standard
50µH/50Ω LISN (Line Impedance Stabilisation Network) model and compares against
CISPR 25 conducted limits and FCC Part 15 Subpart B conducted limits.

All calculations are pure Python — no external dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

from .automotive_emc import CISPR25_CONDUCTED_LIMITS

# =============================================================================
# FCC Part 15 Subpart B conducted emission limits (dBµV, voltage method)
# =============================================================================

FCC_PART15_CONDUCTED_LIMITS: dict[str, list[dict]] = {
    "A": [
        {"freq_min_mhz": 0.15, "freq_max_mhz": 0.5, "qp_limit_dbuv": 79, "avg_limit_dbuv": 66},
        {"freq_min_mhz": 0.5, "freq_max_mhz": 30.0, "qp_limit_dbuv": 73, "avg_limit_dbuv": 60},
    ],
    "B": [
        {"freq_min_mhz": 0.15, "freq_max_mhz": 0.5, "qp_limit_dbuv": 66, "avg_limit_dbuv": 56},
        {"freq_min_mhz": 0.5, "freq_max_mhz": 5.0, "qp_limit_dbuv": 56, "avg_limit_dbuv": 46},
        {"freq_min_mhz": 5.0, "freq_max_mhz": 30.0, "qp_limit_dbuv": 60, "avg_limit_dbuv": 50},
    ],
}


# =============================================================================
# LISN model
# =============================================================================

@dataclass
class LISNModel:
    """Standard 50µH / 50Ω LISN (per CISPR 16-1-2).

    The LISN presents a defined impedance to the EUT power port.
    Above the corner frequency (~150 kHz for 50µH), the impedance
    is dominated by the 50Ω measurement resistor.

    Parameters
    ----------
    inductance_uh : float
        LISN inductor value (µH). Default 50µH per CISPR 16.
    resistance_ohm : float
        Measurement resistor (Ω). Default 50Ω.
    """

    inductance_uh: float = 50.0
    resistance_ohm: float = 50.0

    @property
    def corner_frequency_hz(self) -> float:
        """Corner frequency where |Z_L| = R.  f_c = R / (2π L)."""
        l_h = self.inductance_uh * 1e-6
        if l_h <= 0:
            return 1e9
        return self.resistance_ohm / (2 * math.pi * l_h)

    def impedance_at(self, frequency_hz: float) -> float:
        """Magnitude of LISN impedance at given frequency.

        Z_LISN = (j·ω·L · R) / (R + j·ω·L)
        |Z_LISN| = (ω·L · R) / sqrt(R² + (ω·L)²)
        """
        if frequency_hz <= 0:
            return 0.0
        omega = 2 * math.pi * frequency_hz
        xl = omega * self.inductance_uh * 1e-6
        r = self.resistance_ohm
        return (xl * r) / math.sqrt(r ** 2 + xl ** 2)


# =============================================================================
# Conducted emission finding
# =============================================================================

@dataclass
class ConductedEmissionFinding:
    """A single conducted emission finding at a harmonic frequency."""

    harmonic: int
    frequency_mhz: float
    predicted_level_dbuv: float
    lisn_impedance_ohm: float
    cispr25_peak_limit: Optional[float] = None
    cispr25_avg_limit: Optional[float] = None
    fcc_qp_limit: Optional[float] = None
    fcc_avg_limit: Optional[float] = None
    margin_db: Optional[float] = None
    status: str = "unknown"  # "pass", "marginal", "fail"
    limiting_standard: str = ""
    recommendation: str = ""


@dataclass
class ConductedEmissionAnalysis:
    """Results of a conducted emission analysis."""

    findings: list[ConductedEmissionFinding] = field(default_factory=list)
    overall_status: str = "unknown"
    worst_margin_db: Optional[float] = None
    worst_frequency_mhz: Optional[float] = None
    score: float = 0.0
    cispr_class: int = 3
    fcc_class: str = "B"
    smps_params: dict = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# =============================================================================
# Analyzer
# =============================================================================

class ConductedEmissionAnalyzer:
    """Predict conducted emissions from SMPS through a LISN and check compliance."""

    def __init__(self, lisn: Optional[LISNModel] = None):
        self.lisn = lisn or LISNModel()

    # -----------------------------------------------------------------
    # Limit look-ups
    # -----------------------------------------------------------------
    def get_fcc_conducted_limit(
        self, frequency_mhz: float, fcc_class: str = "B",
    ) -> Optional[dict]:
        """Look up FCC Part 15 Subpart B conducted limit."""
        cls = fcc_class.upper()
        limits = FCC_PART15_CONDUCTED_LIMITS.get(cls)
        if limits is None:
            return None
        for entry in limits:
            if entry["freq_min_mhz"] <= frequency_mhz <= entry["freq_max_mhz"]:
                return {
                    "frequency_mhz": frequency_mhz,
                    "class": cls,
                    "qp_limit_dbuv": entry["qp_limit_dbuv"],
                    "avg_limit_dbuv": entry["avg_limit_dbuv"],
                    "freq_range": f"{entry['freq_min_mhz']}-{entry['freq_max_mhz']} MHz",
                }
        return None

    def get_cispr25_conducted_limit(
        self, frequency_mhz: float, cispr_class: int = 3,
    ) -> Optional[dict]:
        """Look up CISPR 25 conducted limit (reusing shared constant)."""
        if cispr_class < 1 or cispr_class > 5:
            return None
        for entry in CISPR25_CONDUCTED_LIMITS:
            if entry["freq_min_mhz"] <= frequency_mhz <= entry["freq_max_mhz"]:
                limit_data = entry["limits"].get(cispr_class)
                if limit_data is None:
                    return None
                return {
                    "frequency_mhz": frequency_mhz,
                    "class": cispr_class,
                    "peak_limit_dbuv": limit_data["peak"],
                    "avg_limit_dbuv": limit_data["avg"],
                    "freq_range": f"{entry['freq_min_mhz']}-{entry['freq_max_mhz']} MHz",
                }
        return None

    # -----------------------------------------------------------------
    # SMPS harmonic prediction through LISN
    # -----------------------------------------------------------------
    def predict_smps_harmonics(
        self,
        switching_freq_khz: float,
        input_voltage: float,
        duty_cycle: float,
        rise_time_ns: float,
        num_harmonics: int = 50,
        input_filter_db: float = 0.0,
    ) -> list[dict]:
        """Predict SMPS conducted emission harmonics through the LISN.

        Uses a trapezoidal current waveform model. The current waveform
        harmonics are multiplied by the LISN impedance to yield the
        voltage measured at the LISN output.

        Parameters
        ----------
        switching_freq_khz : float
            SMPS switching frequency (kHz).
        input_voltage : float
            DC input voltage (V).
        duty_cycle : float
            Switch duty cycle 0-1.
        rise_time_ns : float
            Current rise/fall time (ns).
        num_harmonics : int
            Number of harmonics to compute.
        input_filter_db : float
            Attenuation from any input EMI filter (dB). Applied to all harmonics.

        Returns
        -------
        list[dict]
            Per-harmonic amplitude in dBµV at LISN output.
        """
        f_sw_hz = switching_freq_khz * 1e3
        period_s = 1.0 / f_sw_hz if f_sw_hz > 0 else 1e-3
        rise_time_s = rise_time_ns * 1e-9
        duty_cycle = max(0.01, min(duty_cycle, 0.99))

        # Peak input current estimate (buck approximation)
        # I_peak ≈ V_in * D / R_load   simplified, scale by voltage
        # For a generic model we use V_in * D as a proxy for current amplitude
        # because we don't know the load. Normalise to a typical 1A base.
        i_peak_a = input_voltage * duty_cycle / 12.0  # normalise to ~1A for 12V/0.5D

        results = []
        for n in range(1, num_harmonics + 1):
            f_n_hz = f_sw_hz * n
            f_n_mhz = f_n_hz / 1e6

            # Trapezoidal Fourier coefficient |Cn|
            # |Cn| = (2·I·D) · |sinc(n·π·D)| · |sinc(n·π·tr/T)|
            x_d = n * math.pi * duty_cycle
            sinc_d = abs(math.sin(x_d) / x_d) if abs(x_d) > 1e-10 else 1.0

            x_tr = n * math.pi * rise_time_s / period_s
            sinc_tr = abs(math.sin(x_tr) / x_tr) if abs(x_tr) > 1e-10 else 1.0

            i_n = 2.0 * i_peak_a * duty_cycle * sinc_d * sinc_tr

            # Voltage at LISN output
            z_lisn = self.lisn.impedance_at(f_n_hz)
            v_lisn = i_n * z_lisn  # V

            # Convert to dBµV
            v_uv = v_lisn * 1e6
            if v_uv > 0:
                level_dbuv = 20 * math.log10(v_uv)
            else:
                level_dbuv = -100.0

            # Apply input filter attenuation
            level_dbuv -= input_filter_db

            results.append({
                "harmonic": n,
                "frequency_mhz": round(f_n_mhz, 4),
                "frequency_hz": f_n_hz,
                "current_amplitude_a": round(i_n, 6),
                "lisn_impedance_ohm": round(z_lisn, 2),
                "level_dbuv": round(level_dbuv, 1),
            })

        return results

    # -----------------------------------------------------------------
    # Full compliance prediction
    # -----------------------------------------------------------------
    def predict_conducted_compliance(
        self,
        switching_freq_khz: float,
        input_voltage: float,
        duty_cycle: float,
        rise_time_ns: float,
        cispr_class: int = 3,
        fcc_class: str = "B",
        num_harmonics: int = 50,
        input_filter_db: float = 0.0,
    ) -> ConductedEmissionAnalysis:
        """Predict conducted emissions and compare against CISPR 25 + FCC limits.

        Parameters
        ----------
        switching_freq_khz : float
            SMPS switching frequency (kHz).
        input_voltage : float
            Input DC voltage (V).
        duty_cycle : float
            Duty cycle 0-1.
        rise_time_ns : float
            Current rise/fall time (ns).
        cispr_class : int
            CISPR 25 class 1-5 (default 3).
        fcc_class : str
            FCC class "A" or "B" (default "B").
        num_harmonics : int
            Number of harmonics.
        input_filter_db : float
            Input EMI filter attenuation (dB).

        Returns
        -------
        ConductedEmissionAnalysis
        """
        harmonics = self.predict_smps_harmonics(
            switching_freq_khz=switching_freq_khz,
            input_voltage=input_voltage,
            duty_cycle=duty_cycle,
            rise_time_ns=rise_time_ns,
            num_harmonics=num_harmonics,
            input_filter_db=input_filter_db,
        )

        findings: list[ConductedEmissionFinding] = []
        worst_margin: Optional[float] = None
        worst_freq: Optional[float] = None

        for h in harmonics:
            f_mhz = h["frequency_mhz"]

            # Only analyse 150 kHz to 30 MHz (conducted emission range)
            if f_mhz < 0.15 or f_mhz > 108:
                continue

            level = h["level_dbuv"]

            # Look up limits
            cispr_info = self.get_cispr25_conducted_limit(f_mhz, cispr_class)
            fcc_info = self.get_fcc_conducted_limit(f_mhz, fcc_class)

            cispr_peak = cispr_info["peak_limit_dbuv"] if cispr_info else None
            cispr_avg = cispr_info["avg_limit_dbuv"] if cispr_info else None
            fcc_qp = fcc_info["qp_limit_dbuv"] if fcc_info else None
            fcc_avg = fcc_info["avg_limit_dbuv"] if fcc_info else None

            # Determine worst-case margin (use peak/QP vs predicted level)
            margins = []
            limiting_std = ""
            if cispr_peak is not None:
                m = cispr_peak - level
                margins.append((m, f"CISPR 25 Class {cispr_class} peak"))
            if fcc_qp is not None:
                m = fcc_qp - level
                margins.append((m, f"FCC Part 15 Class {fcc_class} QP"))

            if margins:
                best_worst = min(margins, key=lambda x: x[0])
                margin = best_worst[0]
                limiting_std = best_worst[1]
            else:
                margin = None
                limiting_std = ""

            # Status
            if margin is not None:
                if margin > 6:
                    status = "pass"
                elif margin > 0:
                    status = "marginal"
                else:
                    status = "fail"
            else:
                status = "unknown"

            # Recommendation
            rec = ""
            if status == "fail":
                rec = (
                    f"Harmonic {h['harmonic']} at {f_mhz:.3f} MHz exceeds {limiting_std} "
                    f"by {abs(margin):.1f} dB. Add input LC filter or increase switching "
                    f"frequency to push harmonics above 30 MHz."
                )
            elif status == "marginal":
                rec = (
                    f"Harmonic {h['harmonic']} at {f_mhz:.3f} MHz has only {margin:.1f} dB margin "
                    f"to {limiting_std}. Consider additional filtering."
                )

            finding = ConductedEmissionFinding(
                harmonic=h["harmonic"],
                frequency_mhz=f_mhz,
                predicted_level_dbuv=level,
                lisn_impedance_ohm=h["lisn_impedance_ohm"],
                cispr25_peak_limit=cispr_peak,
                cispr25_avg_limit=cispr_avg,
                fcc_qp_limit=fcc_qp,
                fcc_avg_limit=fcc_avg,
                margin_db=round(margin, 1) if margin is not None else None,
                status=status,
                limiting_standard=limiting_std,
                recommendation=rec,
            )
            findings.append(finding)

            if margin is not None and (worst_margin is None or margin < worst_margin):
                worst_margin = margin
                worst_freq = f_mhz

        # Overall status
        statuses = [f.status for f in findings]
        if "fail" in statuses:
            overall = "fail"
        elif "marginal" in statuses:
            overall = "marginal"
        elif statuses:
            overall = "pass"
        else:
            overall = "unknown"

        # Score
        if findings:
            pass_count = sum(1 for f in findings if f.status == "pass")
            score = round(pass_count / len(findings) * 100, 1)
        else:
            score = 0.0

        # Top-level recommendations
        recs: list[str] = []
        if overall == "fail":
            recs.append(
                "Add a common-mode choke and π-filter on the power input to attenuate "
                "conducted emissions in the 150 kHz – 30 MHz range."
            )
        if input_filter_db < 10 and overall != "pass":
            recs.append(
                "Consider an LC input filter with corner frequency below the switching "
                f"frequency ({switching_freq_khz} kHz). A 2nd-order filter provides "
                "40 dB/decade attenuation."
            )
        if rise_time_ns < 10:
            recs.append(
                f"Fast rise time ({rise_time_ns} ns) generates significant high-frequency "
                "content. Slowing transitions with gate resistance can reduce harmonics "
                "above 10 MHz."
            )
        if switching_freq_khz < 150:
            recs.append(
                f"Switching frequency ({switching_freq_khz} kHz) places multiple harmonics "
                "in the 150 kHz – 500 kHz conducted emission band. Consider increasing "
                "f_sw or adding a pre-regulator."
            )

        # Knee frequency
        f_knee_mhz = 1000.0 / (math.pi * rise_time_ns) if rise_time_ns > 0 else 1e6

        notes = [
            f"LISN: {self.lisn.inductance_uh} µH / {self.lisn.resistance_ohm} Ω, "
            f"corner freq = {self.lisn.corner_frequency_hz/1e3:.1f} kHz",
            f"Switching: {switching_freq_khz} kHz, D = {duty_cycle:.2f}, "
            f"V_in = {input_voltage} V",
            f"Rise time: {rise_time_ns} ns, knee freq = {f_knee_mhz:.1f} MHz",
            f"Standards: CISPR 25 Class {cispr_class}, FCC Part 15 Class {fcc_class}",
        ]
        if input_filter_db > 0:
            notes.append(f"Input filter: {input_filter_db} dB attenuation applied")

        analysis = ConductedEmissionAnalysis(
            findings=findings,
            overall_status=overall,
            worst_margin_db=round(worst_margin, 1) if worst_margin is not None else None,
            worst_frequency_mhz=round(worst_freq, 4) if worst_freq is not None else None,
            score=score,
            cispr_class=cispr_class,
            fcc_class=fcc_class.upper(),
            smps_params={
                "switching_freq_khz": switching_freq_khz,
                "input_voltage": input_voltage,
                "duty_cycle": duty_cycle,
                "rise_time_ns": rise_time_ns,
                "input_filter_db": input_filter_db,
            },
            recommendations=recs,
            notes=notes,
        )
        return analysis

    # -----------------------------------------------------------------
    # Serialisation for MCP tool output
    # -----------------------------------------------------------------
    def to_dict(self, analysis: ConductedEmissionAnalysis) -> dict:
        """Convert analysis to dict for MCP tool output."""
        return {
            "overall_status": analysis.overall_status,
            "score": analysis.score,
            "worst_margin_db": analysis.worst_margin_db,
            "worst_frequency_mhz": analysis.worst_frequency_mhz,
            "cispr25_class": analysis.cispr_class,
            "fcc_class": analysis.fcc_class,
            "findings_count": len(analysis.findings),
            "findings": [
                {
                    "harmonic": f.harmonic,
                    "frequency_mhz": f.frequency_mhz,
                    "predicted_level_dbuv": f.predicted_level_dbuv,
                    "lisn_impedance_ohm": f.lisn_impedance_ohm,
                    "cispr25_peak_limit": f.cispr25_peak_limit,
                    "cispr25_avg_limit": f.cispr25_avg_limit,
                    "fcc_qp_limit": f.fcc_qp_limit,
                    "fcc_avg_limit": f.fcc_avg_limit,
                    "margin_db": f.margin_db,
                    "status": f.status,
                    "limiting_standard": f.limiting_standard,
                    "recommendation": f.recommendation,
                }
                for f in analysis.findings
                if f.status in ("fail", "marginal")
            ],
            "all_findings_summary": [
                {
                    "harmonic": f.harmonic,
                    "frequency_mhz": f.frequency_mhz,
                    "level_dbuv": f.predicted_level_dbuv,
                    "margin_db": f.margin_db,
                    "status": f.status,
                }
                for f in analysis.findings
            ],
            "smps_params": analysis.smps_params,
            "recommendations": analysis.recommendations,
            "notes": analysis.notes,
        }

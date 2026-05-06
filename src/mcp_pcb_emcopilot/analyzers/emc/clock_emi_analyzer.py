"""
Clock and SMPS harmonic EMI analysis.

Models the harmonic envelope of digital clock signals (trapezoidal waveform)
and SMPS switching waveforms, predicts emission levels, and compares against
FCC/CISPR limits.  Includes spread-spectrum clocking (SSC) dithering reduction.

All calculations are pure Python — no external dependencies.
"""

from __future__ import annotations

import math
from typing import Any, Optional


def _trapezoidal_harmonic_amplitude(
    n: int,
    v_peak: float,
    duty_cycle: float,
    rise_time_s: float,
    period_s: float,
) -> float:
    """Amplitude of the nth harmonic of a trapezoidal waveform.

    Uses the standard Fourier series for a trapezoidal pulse train:
        |Cn| = (2 * V * d) / (n * pi) * |sinc(n*pi*d)| * |sinc(n*pi*tr/T)|

    where d = duty cycle, tr = rise/fall time, T = period.
    """
    if n <= 0:
        return 0.0

    # sinc(x) = sin(pi*x) / (pi*x), using x directly
    def sinc(x: float) -> float:
        if abs(x) < 1e-12:
            return 1.0
        return abs(math.sin(math.pi * x) / (math.pi * x))

    # Duty cycle envelope
    duty_sinc = sinc(n * duty_cycle)

    # Rise time envelope
    tr_ratio = rise_time_s / period_s if period_s > 0 else 0
    rise_sinc = sinc(n * tr_ratio)

    amplitude = 2 * v_peak * duty_cycle * duty_sinc * rise_sinc / 1.0
    # The 1/(n*pi) factor is already in the sinc for duty
    # More precisely: Cn = (2*V*d/1) * sinc(n*d) * sinc(n*tr/T)
    return amplitude


def _trapezoidal_envelope_dbua(
    n: int,
    v_peak_v: float,
    duty_cycle: float,
    rise_time_ns: float,
    frequency_mhz: float,
) -> float:
    """Harmonic amplitude in dBuA assuming 50-ohm measurement.

    Converts voltage to current (I = V/50) then to dBuA.
    """
    period_s = 1.0 / (frequency_mhz * 1e6)
    rise_time_s = rise_time_ns * 1e-9

    v_n = _trapezoidal_harmonic_amplitude(n, v_peak_v, duty_cycle, rise_time_s, period_s)

    # Current in 50-ohm system
    i_a = v_n / 50.0
    i_ua = i_a * 1e6

    if i_ua <= 0:
        return -100.0
    return 20 * math.log10(i_ua)


def calculate_clock_emi(
    clock_frequency_mhz: float,
    rise_time_ns: float = 1.0,
    voltage_swing_v: float = 3.3,
    duty_cycle: float = 0.5,
    num_harmonics: int = 20,
    ssc_enabled: bool = False,
    ssc_deviation_percent: float = 0.5,
    trace_length_mm: float = 50.0,
    limit_standard: str = "fcc_classb",
) -> dict:
    """Calculate clock signal harmonic EMI envelope.

    Parameters
    ----------
    clock_frequency_mhz : float
        Fundamental clock frequency (MHz).
    rise_time_ns : float
        Signal rise time 10-90% (ns).
    voltage_swing_v : float
        Peak voltage swing (V).
    duty_cycle : float
        Duty cycle (0 to 1).
    num_harmonics : int
        Number of harmonics to compute.
    ssc_enabled : bool
        Whether spread-spectrum clocking is active.
    ssc_deviation_percent : float
        SSC frequency deviation (typically 0.25-0.5%).
    trace_length_mm : float
        Trace length — used for antenna efficiency estimate.
    limit_standard : str
        Emission limit: "fcc_classb", "fcc_classa", "cispr32_classb", "cispr32_classa".

    Returns
    -------
    dict
        Harmonic frequencies, amplitudes, comparison to limits.
    """
    # Knee frequency (bandwidth of trapezoidal waveform)
    f_knee_mhz = 1000.0 / (math.pi * rise_time_ns)  # 1/(pi*tr) in MHz

    # Emission limits (simplified, at 3m distance, dBuV/m)
    # These are approximate — real limits vary with frequency
    _limits = {
        "fcc_classb": {
            "30-88_mhz": 40.0,
            "88-216_mhz": 43.5,
            "216-960_mhz": 46.0,
            "above_960_mhz": 54.0,
        },
        "fcc_classa": {
            "30-88_mhz": 49.5,
            "88-216_mhz": 54.0,
            "216-960_mhz": 56.0,
            "above_960_mhz": 60.0,
        },
        "cispr32_classb": {
            "30-230_mhz": 40.0,
            "230-1000_mhz": 47.0,
            "above_1000_mhz": 56.0,
        },
        "cispr32_classa": {
            "30-230_mhz": 50.0,
            "230-1000_mhz": 57.0,
            "above_1000_mhz": 60.0,
        },
    }

    def _get_limit(f_mhz: float, std: str) -> float:
        limits = _limits.get(std, _limits["fcc_classb"])
        if "above_1000_mhz" in limits:
            # CISPR style
            if f_mhz < 230:
                return limits.get("30-230_mhz", 40)
            elif f_mhz < 1000:
                return limits.get("230-1000_mhz", 47)
            else:
                return limits.get("above_1000_mhz", 56)
        else:
            # FCC style
            if f_mhz < 88:
                return limits.get("30-88_mhz", 40)
            elif f_mhz < 216:
                return limits.get("88-216_mhz", 43.5)
            elif f_mhz < 960:
                return limits.get("216-960_mhz", 46)
            else:
                return limits.get("above_960_mhz", 54)

    harmonics: list[dict[str, Any]] = []
    worst_margin_db = 100.0
    worst_harmonic = 1

    for n in range(1, num_harmonics + 1):
        f_mhz = clock_frequency_mhz * n
        if f_mhz < 1.0:
            continue

        period_s = 1.0 / (clock_frequency_mhz * 1e6)
        rise_time_s = rise_time_ns * 1e-9

        # Harmonic amplitude (voltage)
        v_n = _trapezoidal_harmonic_amplitude(n, voltage_swing_v, duty_cycle, rise_time_s, period_s)

        # Convert to dBuV (for radiated emission comparison)
        # Simplified: assume short electric dipole radiation
        # E = (1.316e-14 * f^2 * I * L) / r   [V/m at distance r]
        # where I = V/Z, L = trace_length
        i_a = v_n / 50.0  # current in trace
        wavelength_mm = 3e8 / (f_mhz * 1e6) * 1e3
        trace_fraction = trace_length_mm / wavelength_mm  # electrical length

        # Antenna efficiency of a short trace (proportional to (L/lambda)^2)
        eff = min(trace_fraction**2, 1.0)

        # Radiated field estimate at 3m (very approximate, from loop + dipole model)
        # E_field ≈ 1.316e-14 * f^2 * I * L / r  (for short dipole)
        f_hz = f_mhz * 1e6
        e_field = 1.316e-14 * (f_hz**2) * i_a * (trace_length_mm * 1e-3) / 3.0
        if e_field > 0:
            e_dbuvm = 20 * math.log10(e_field * 1e6)  # V/m -> uV/m -> dBuV/m
        else:
            e_dbuvm = -100.0

        # SSC reduction (spreads energy, reduces peak by ~8-10 dB typically)
        ssc_reduction_db = 0.0
        if ssc_enabled and ssc_deviation_percent > 0:
            # Reduction is approximately 20*log10(f_fund / (f_fund * dev%))
            # Typically 8-10 dB for 0.5% deviation
            ssc_reduction_db = 20 * math.log10(1.0 / (ssc_deviation_percent / 100.0 * n))
            ssc_reduction_db = min(ssc_reduction_db, 20.0)  # cap at practical limit
            ssc_reduction_db = max(ssc_reduction_db, 0.0)
            e_dbuvm -= ssc_reduction_db

        # Get limit
        limit_dbuvm = _get_limit(f_mhz, limit_standard)
        margin = limit_dbuvm - e_dbuvm

        if margin < worst_margin_db:
            worst_margin_db = margin
            worst_harmonic = n

        harmonics.append({
            "harmonic": n,
            "frequency_mhz": round(f_mhz, 2),
            "amplitude_v": round(v_n, 6),
            "estimated_emission_dbuvm": round(e_dbuvm, 1),
            "limit_dbuvm": limit_dbuvm,
            "margin_db": round(margin, 1),
            "ssc_reduction_db": round(ssc_reduction_db, 1),
            "below_knee": f_mhz <= f_knee_mhz,
        })

    pass_fail = "PASS" if worst_margin_db >= 0 else "FAIL"

    notes = []
    notes.append(f"Knee frequency: {f_knee_mhz:.0f} MHz (1/(pi*{rise_time_ns} ns))")
    notes.append("Harmonics above knee frequency roll off at -40 dB/decade")
    if ssc_enabled:
        notes.append(f"SSC enabled: {ssc_deviation_percent}% deviation — reduces peak emissions")
    if rise_time_ns < 0.5:
        notes.append("Very fast rise time — broadband emissions will be significant")
    if worst_margin_db < 0:
        notes.append(
            f"Harmonic {worst_harmonic} ({clock_frequency_mhz*worst_harmonic:.0f} MHz) "
            f"exceeds {limit_standard} limit by {-worst_margin_db:.1f} dB"
        )

    recommendations = []
    if worst_margin_db < 0:
        recommendations.append("Slow down rise time to reduce high-frequency harmonics")
        if not ssc_enabled:
            recommendations.append("Enable spread-spectrum clocking for ~8-10 dB reduction")
        recommendations.append("Add series resistance (22-33 ohm) near clock driver")
        recommendations.append("Shorten clock trace or use differential signaling")
    elif worst_margin_db < 6:
        recommendations.append(f"Only {worst_margin_db:.1f} dB margin — borderline. Consider SSC or slower edges.")

    return {
        "harmonics": harmonics,
        "worst_margin_db": round(worst_margin_db, 1),
        "worst_harmonic": worst_harmonic,
        "worst_frequency_mhz": round(clock_frequency_mhz * worst_harmonic, 2),
        "pass_fail": pass_fail,
        "knee_frequency_mhz": round(f_knee_mhz, 0),
        "limit_standard": limit_standard,
        "ssc_enabled": ssc_enabled,
        "notes": notes,
        "recommendations": recommendations,
    }


def calculate_smps_emi(
    switching_frequency_khz: float,
    duty_cycle: float = 0.5,
    input_voltage_v: float = 12.0,
    output_voltage_v: float = 3.3,
    output_current_a: float = 2.0,
    rise_time_ns: float = 10.0,
    inductor_value_uh: float = 4.7,
    num_harmonics: int = 30,
    pcb_loop_area_cm2: float = 1.0,
    limit_standard: str = "cispr32_classb",
) -> dict:
    """Calculate SMPS switching harmonic EMI.

    Parameters
    ----------
    switching_frequency_khz : float
        SMPS switching frequency (kHz).
    duty_cycle : float
        Switch duty cycle (0 to 1). If 0, auto-calculated from Vin/Vout.
    input_voltage_v : float
        Input supply voltage (V).
    output_voltage_v : float
        Output voltage (V).
    output_current_a : float
        Output load current (A).
    rise_time_ns : float
        Switch transition rise time (ns).
    inductor_value_uh : float
        Output inductor value (uH).
    num_harmonics : int
        Number of harmonics to analyze.
    pcb_loop_area_cm2 : float
        Hot loop area on PCB (cm^2) — critical for emissions.
    limit_standard : str
        Emission limit standard.

    Returns
    -------
    dict
        Harmonic analysis, hot loop assessment, EMI risk.
    """
    # Auto-calculate duty cycle for buck converter if not specified
    if duty_cycle <= 0 or duty_cycle >= 1:
        if input_voltage_v > 0:
            duty_cycle = output_voltage_v / input_voltage_v
            duty_cycle = max(0.05, min(duty_cycle, 0.95))

    f_sw_hz = switching_frequency_khz * 1e3
    period_s = 1.0 / f_sw_hz

    # Knee frequency
    f_knee_mhz = 1000.0 / (math.pi * rise_time_ns)

    # Peak switch current (triangle waveform)
    # I_peak = I_out + delta_I/2, delta_I = (Vin - Vout) * D * T / L
    delta_i = (input_voltage_v - output_voltage_v) * duty_cycle * period_s / (inductor_value_uh * 1e-6)
    i_peak = output_current_a + delta_i / 2

    # Input ripple current (worst case, trapezoidal through input cap)
    i_rms_input = output_current_a * math.sqrt(duty_cycle * (1 - duty_cycle))

    # Hot loop radiation: magnetic dipole model
    # H = (I * A * omega^2) / (4 * pi * c * r) for a small loop
    # E = Z0 * H = 377 * H
    loop_area_m2 = pcb_loop_area_cm2 * 1e-4

    harmonics: list[dict[str, Any]] = []
    worst_margin_db = 100.0
    worst_harmonic = 1

    for n in range(1, num_harmonics + 1):
        f_mhz = switching_frequency_khz * n / 1000.0
        f_hz = f_mhz * 1e6

        # Current harmonic (trapezoidal spectrum)
        i_n = _trapezoidal_harmonic_amplitude(n, i_peak, duty_cycle,
                                              rise_time_ns * 1e-9, period_s)

        # Radiated emission from hot loop (magnetic dipole at 3m)
        omega = 2 * math.pi * f_hz
        # |E| = (Z0 * omega^2 * I * A) / (4 * pi * c * r)  for small loop
        e_field = (377 * omega**2 * i_n * loop_area_m2) / (4 * math.pi * 3e8 * 3.0)

        if e_field > 0:
            e_dbuvm = 20 * math.log10(e_field * 1e6)
        else:
            e_dbuvm = -100.0

        # Get limit (only meaningful for f > 30 MHz typically)
        limit: Optional[float]
        margin: Optional[float]
        if f_mhz >= 30:
            # Reuse limit function pattern
            if "cispr" in limit_standard:
                if f_mhz < 230:
                    limit = 40 if "classb" in limit_standard else 50
                elif f_mhz < 1000:
                    limit = 47 if "classb" in limit_standard else 57
                else:
                    limit = 56 if "classb" in limit_standard else 60
            else:
                if f_mhz < 88:
                    limit = 40 if "classb" in limit_standard else 49.5
                elif f_mhz < 216:
                    limit = 43.5 if "classb" in limit_standard else 54
                elif f_mhz < 960:
                    limit = 46 if "classb" in limit_standard else 56
                else:
                    limit = 54 if "classb" in limit_standard else 60

            margin = limit - e_dbuvm
            if margin < worst_margin_db:
                worst_margin_db = margin
                worst_harmonic = n
        else:
            # Out of regulated range — no limit / margin to compute.
            limit = None
            margin = None

        harmonics.append({
            "harmonic": n,
            "frequency_mhz": round(f_mhz, 3),
            "current_amplitude_a": round(i_n, 6),
            "estimated_emission_dbuvm": round(e_dbuvm, 1),
            "limit_dbuvm": limit,
            "margin_db": round(margin, 1) if margin is not None else None,
        })

    pass_fail = "PASS" if worst_margin_db >= 0 else "FAIL"

    notes = []
    notes.append(f"Switching frequency: {switching_frequency_khz} kHz, duty cycle: {duty_cycle:.2f}")
    notes.append(f"Peak switch current: {i_peak:.2f} A, input ripple RMS: {i_rms_input:.2f} A")
    notes.append(f"Knee frequency: {f_knee_mhz:.0f} MHz")
    notes.append(f"Hot loop area: {pcb_loop_area_cm2} cm^2")

    if pcb_loop_area_cm2 > 2.0:
        notes.append("WARNING: Hot loop area > 2 cm^2 — minimize immediately")

    recommendations = []
    if worst_margin_db < 0:
        recommendations.append(
            f"Emission at harmonic {worst_harmonic} "
            f"({switching_frequency_khz*worst_harmonic/1000:.1f} MHz) "
            f"exceeds limit by {-worst_margin_db:.1f} dB"
        )
    if pcb_loop_area_cm2 > 0.5:
        recommendations.append(
            f"Reduce hot loop area from {pcb_loop_area_cm2} cm^2. "
            "Place input cap adjacent to switch FET with shortest path to GND."
        )
    if rise_time_ns < 5:
        recommendations.append(
            f"Fast switching ({rise_time_ns} ns) spreads energy to high frequencies. "
            "Add gate resistance or use slower driver if EMI is marginal."
        )
    if not any("snubber" in r.lower() for r in recommendations) and worst_margin_db < 6:
        recommendations.append(
            "Consider RC snubber across the switch to damp ringing"
        )

    return {
        "harmonics": harmonics,
        "worst_margin_db": round(worst_margin_db, 1),
        "worst_harmonic": worst_harmonic,
        "pass_fail": pass_fail,
        "power_stage": {
            "duty_cycle": round(duty_cycle, 3),
            "peak_current_a": round(i_peak, 2),
            "input_ripple_rms_a": round(i_rms_input, 2),
            "current_ripple_pp_a": round(delta_i, 2),
        },
        "knee_frequency_mhz": round(f_knee_mhz, 0),
        "hot_loop_area_cm2": pcb_loop_area_cm2,
        "limit_standard": limit_standard,
        "notes": notes,
        "recommendations": recommendations,
    }


# =============================================================================
# MCP tool-facing functions (Issues #14 / #15)
# =============================================================================

# Speed of light (m/s)
_C0 = 299792458.0

# FCC Part 15 Class B limits at 3m (dBuV/m)
_FCC_CLASS_B_LIMITS = [
    (30, 88, 40.0),
    (88, 216, 43.5),
    (216, 960, 46.0),
    (960, 40000, 54.0),
]

# CISPR 32 Class B limits at 3m (dBuV/m)
_CISPR_CLASS_B_LIMITS = [
    (30, 230, 40.0),
    (230, 1000, 47.0),
    (1000, 6000, 54.0),
]


def _get_regulatory_limit(frequency_mhz: float, standard: str = "fcc_b") -> float:
    """Get emission limit for a frequency under a given standard."""
    std_lower = standard.lower().replace(" ", "_").replace("-", "_")
    limits = _CISPR_CLASS_B_LIMITS if "cispr" in std_lower else _FCC_CLASS_B_LIMITS
    for f_low, f_high, limit in limits:
        if f_low <= frequency_mhz <= f_high:
            return limit
    if frequency_mhz < 30:
        return 999.0
    return limits[-1][2]


def analyze_clock_emi(
    frequency_mhz: float,
    voltage_v: float = 3.3,
    rise_time_ps: float = 500.0,
    current_ma: float = 10.0,
    loop_area_mm2: float = 10.0,
    spread_spectrum_percent: float = 0.0,
    duty_cycle: float = 0.5,
    standard: str = "fcc_b",
    num_harmonics: int = 20,
    test_distance_m: float = 3.0,
) -> dict:
    """Analyze clock/crystal EMI with trapezoidal harmonic envelope.

    Computes harmonic spectrum, radiated emission from signal loop, spread
    spectrum reduction, and compares each harmonic against FCC/CISPR limits.

    Parameters
    ----------
    frequency_mhz : float
        Clock fundamental frequency (MHz).
    voltage_v : float
        Signal amplitude (V pk-pk).
    rise_time_ps : float
        Rise/fall time (ps).
    current_ma : float
        Signal current (mA).
    loop_area_mm2 : float
        Signal loop area (mm^2).
    spread_spectrum_percent : float
        Modulation percentage (0 = none, 0.5-2 typical).
    duty_cycle : float
        Duty cycle 0-1.
    standard : str
        EMC standard (fcc_b, cispr_b).
    num_harmonics : int
        Number of harmonics to compute.
    test_distance_m : float
        Measurement distance (m).

    Returns
    -------
    dict
        harmonics list, overall_compliant, risk_level, worst_margin_db,
        spread_spectrum_reduction_db, envelope corner frequencies,
        notes, recommendations.
    """
    freq_hz = frequency_mhz * 1e6
    period_s = 1.0 / freq_hz if freq_hz > 0 else 1e-6
    tau_s = duty_cycle * period_s
    tr_s = rise_time_ps * 1e-12

    f1_mhz = (1.0 / (math.pi * tau_s)) / 1e6 if tau_s > 0 else freq_hz * 100
    f2_mhz = (1.0 / (math.pi * tr_s)) / 1e6 if tr_s > 0 else freq_hz * 1000

    # Spread spectrum reduction
    ss_reduction_db = 0.0
    if spread_spectrum_percent > 0:
        spreading_bw_hz = spread_spectrum_percent / 100.0 * freq_hz
        rbw_hz = 120e3
        if spreading_bw_hz > rbw_hz:
            ss_reduction_db = min(10.0 * math.log10(spreading_bw_hz / rbw_hz), 20.0)

    harmonics: list[dict[str, Any]] = []
    worst_margin_db = 999.0
    worst_freq_mhz = frequency_mhz
    worst_emission = -100.0
    total_compliant = True
    ref_amplitude_v = None

    for n in range(1, num_harmonics + 1):
        fn_mhz = frequency_mhz * n
        fn_hz = fn_mhz * 1e6
        if fn_mhz > 6000:
            break

        x_tau = n * math.pi * duty_cycle
        x_tr = n * math.pi * tr_s * freq_hz
        sinc_tau = abs(math.sin(x_tau) / x_tau) if abs(x_tau) > 1e-10 else 1.0
        sinc_tr = abs(math.sin(x_tr) / x_tr) if abs(x_tr) > 1e-10 else 1.0

        amplitude_v = 2.0 * voltage_v * duty_cycle * sinc_tau * sinc_tr
        if ref_amplitude_v is None:
            ref_amplitude_v = amplitude_v
        amplitude_db_rel = (
            20.0 * math.log10(max(amplitude_v, 1e-15) / max(ref_amplitude_v, 1e-15))
            if ref_amplitude_v > 0 else -100
        )

        # Radiated emission from current loop
        current_a = current_ma * 1e-3
        area_m2 = loop_area_mm2 * 1e-6
        i_harmonic = current_a * amplitude_v / ref_amplitude_v if ref_amplitude_v > 0 else 0
        e_field = (1.316e-14 * fn_hz ** 2 * i_harmonic * area_m2) / test_distance_m
        emission_dbuv = 20.0 * math.log10(e_field * 1e6) if e_field > 0 else -100.0
        emission_with_ss = emission_dbuv - ss_reduction_db

        limit_dbuv = _get_regulatory_limit(fn_mhz, standard)
        margin_db = limit_dbuv - emission_with_ss
        compliant = margin_db >= 0
        if not compliant:
            total_compliant = False
        if fn_mhz >= 30 and margin_db < worst_margin_db:
            worst_margin_db = margin_db
            worst_freq_mhz = fn_mhz
            worst_emission = emission_with_ss

        harmonics.append({
            "harmonic_number": n,
            "frequency_mhz": round(fn_mhz, 3),
            "amplitude_v": round(amplitude_v, 6),
            "amplitude_db_rel": round(amplitude_db_rel, 1),
            "emission_dbuv_m": round(emission_with_ss, 1),
            "emission_no_ss_dbuv_m": round(emission_dbuv, 1),
            "limit_dbuv_m": limit_dbuv,
            "margin_db": round(margin_db, 1),
            "compliant": compliant,
        })

    risk_level = "pass" if worst_margin_db >= 6 else "marginal" if worst_margin_db >= 0 else "fail"
    failing = [h for h in harmonics if not h["compliant"]]
    marginal_list = [h for h in harmonics if h["compliant"] and h["margin_db"] < 6]

    notes = [
        f"Clock: {frequency_mhz} MHz, {voltage_v}V, {rise_time_ps}ps rise time",
        f"Envelope corners: f1={f1_mhz:.1f} MHz (-20dB/dec), f2={f2_mhz:.1f} MHz (-40dB/dec)",
        f"Loop area: {loop_area_mm2} mm^2, current: {current_ma} mA",
        f"Standard: {standard.upper()}, distance: {test_distance_m}m",
    ]
    if spread_spectrum_percent > 0:
        notes.append(f"Spread spectrum: {spread_spectrum_percent}%, ~{ss_reduction_db:.1f}dB reduction")

    recommendations = []
    if failing:
        freqs = ", ".join(f"{h['frequency_mhz']}MHz" for h in failing[:5])
        recommendations.append(f"FAIL: {len(failing)} harmonic(s) exceed limit: {freqs}")
    if marginal_list:
        recommendations.append(f"{len(marginal_list)} harmonic(s) have <6dB margin")
    if rise_time_ps < 200 and risk_level != "pass":
        recommendations.append(f"Rise time ({rise_time_ps}ps) is very fast. Add series resistance.")
    if spread_spectrum_percent == 0 and risk_level != "pass":
        recommendations.append("Consider spread-spectrum clocking (0.5-1%) for 6-10dB reduction.")
    if loop_area_mm2 > 20 and risk_level != "pass":
        recommendations.append(f"Loop area ({loop_area_mm2}mm^2) is large. Route over reference plane.")

    return {
        "harmonics": harmonics,
        "fundamental_frequency_mhz": frequency_mhz,
        "num_harmonics_analyzed": len(harmonics),
        "overall_compliant": total_compliant,
        "risk_level": risk_level,
        "worst_margin_db": round(worst_margin_db, 1) if worst_margin_db < 900 else None,
        "worst_frequency_mhz": round(worst_freq_mhz, 3) if worst_margin_db < 900 else None,
        "worst_emission_dbuv_m": round(worst_emission, 1) if worst_margin_db < 900 else None,
        "failing_harmonics": len(failing),
        "marginal_harmonics": len(marginal_list),
        "spread_spectrum_reduction_db": round(ss_reduction_db, 1),
        "envelope_f1_mhz": round(f1_mhz, 1),
        "envelope_f2_mhz": round(f2_mhz, 1),
        "standard": standard.upper(),
        "test_distance_m": test_distance_m,
        "notes": notes,
        "recommendations": recommendations,
        "parameters": {
            "frequency_mhz": frequency_mhz,
            "voltage_v": voltage_v,
            "rise_time_ps": rise_time_ps,
            "current_ma": current_ma,
            "loop_area_mm2": loop_area_mm2,
            "spread_spectrum_percent": spread_spectrum_percent,
            "duty_cycle": duty_cycle,
        },
    }


def analyze_smps_emi(
    switching_freq_khz: float,
    input_voltage_v: float,
    output_voltage_v: float,
    output_current_a: float,
    input_loop_area_mm2: float = 20.0,
    output_loop_area_mm2: float = 20.0,
    topology: str = "buck",
    standard: str = "fcc_b",
    num_harmonics: int = 20,
    test_distance_m: float = 3.0,
) -> dict:
    """Analyze SMPS switching harmonic EMI.

    Models harmonics from duty cycle, estimates radiated emissions from
    input and output current loops, and recommends filter parameters.

    Parameters
    ----------
    switching_freq_khz : float
        Switching frequency (kHz).
    input_voltage_v : float
        Input voltage (V).
    output_voltage_v : float
        Output voltage (V).
    output_current_a : float
        Output load current (A).
    input_loop_area_mm2 : float
        Input current loop area (mm^2).
    output_loop_area_mm2 : float
        Output current loop area (mm^2).
    topology : str
        Converter topology (buck, boost, buck_boost).
    standard : str
        EMC standard (fcc_b, cispr_b).
    num_harmonics : int
        Harmonics to analyze.
    test_distance_m : float
        Measurement distance (m).

    Returns
    -------
    dict
        harmonics, compliance, filter_recommendations, notes,
        recommendations.
    """
    freq_hz = switching_freq_khz * 1e3
    freq_mhz = switching_freq_khz / 1e3

    # Duty cycle from topology
    topo = topology.lower().replace("-", "_")
    if topo == "buck":
        duty_cycle = output_voltage_v / input_voltage_v if input_voltage_v > 0 else 0.5
    elif topo == "boost":
        duty_cycle = 1.0 - (input_voltage_v / output_voltage_v) if output_voltage_v > 0 else 0.5
    elif topo in ("buck_boost", "buckboost"):
        denom = input_voltage_v + output_voltage_v
        duty_cycle = output_voltage_v / denom if denom > 0 else 0.5
    else:
        duty_cycle = 0.5
    duty_cycle = max(0.01, min(0.99, duty_cycle))

    # Currents
    if topo == "buck":
        i_in_avg = duty_cycle * output_current_a
        i_in_peak = output_current_a
        out_ripple = output_current_a * 0.3
    elif topo == "boost":
        i_in_avg = output_current_a / max(1.0 - duty_cycle, 0.01)
        i_in_peak = i_in_avg * 1.3
        out_ripple = output_current_a * 0.4
    else:
        i_in_avg = output_current_a
        i_in_peak = output_current_a * 1.5
        out_ripple = output_current_a * 0.35

    rise_time_ns = 20.0
    rise_time_s = rise_time_ns * 1e-9
    f_rise_mhz = (1.0 / (math.pi * rise_time_s)) / 1e6

    input_area_m2 = input_loop_area_mm2 * 1e-6
    output_area_m2 = output_loop_area_mm2 * 1e-6

    harmonics: list[dict[str, Any]] = []
    worst_margin = 999.0
    worst_freq = freq_mhz
    worst_emission = -100.0
    total_compliant = True

    for n in range(1, num_harmonics + 1):
        fn_hz = freq_hz * n
        fn_mhz = fn_hz / 1e6
        if fn_mhz > 6000:
            break

        x = n * math.pi * duty_cycle
        sinc_d = abs(math.sin(x) / x) if abs(x) > 1e-10 else 1.0
        x_tr = n * math.pi * rise_time_s * freq_hz
        sinc_tr = abs(math.sin(x_tr) / x_tr) if abs(x_tr) > 1e-10 else 1.0
        amp_factor = sinc_d * sinc_tr

        # Input loop
        i_in_harm = i_in_peak * amp_factor
        e_in = (1.316e-14 * fn_hz ** 2 * i_in_harm * input_area_m2) / test_distance_m
        in_dbuv = 20.0 * math.log10(e_in * 1e6) if e_in > 0 else -100.0

        # Output loop
        i_out_harm = out_ripple * amp_factor
        e_out = (1.316e-14 * fn_hz ** 2 * i_out_harm * output_area_m2) / test_distance_m
        out_dbuv = 20.0 * math.log10(e_out * 1e6) if e_out > 0 else -100.0

        # Total (power sum)
        total_lin = sum(10 ** (v / 10) for v in (in_dbuv, out_dbuv) if v > -90)
        total_dbuv = 10.0 * math.log10(total_lin) if total_lin > 0 else -100.0

        limit = _get_regulatory_limit(fn_mhz, standard)
        margin = limit - total_dbuv
        compliant = margin >= 0
        if not compliant:
            total_compliant = False
        if fn_mhz >= 30 and margin < worst_margin:
            worst_margin = margin
            worst_freq = fn_mhz
            worst_emission = total_dbuv

        dominant = "input" if in_dbuv > out_dbuv else "output"
        harmonics.append({
            "harmonic_number": n,
            "frequency_mhz": round(fn_mhz, 3),
            "amplitude_factor": round(amp_factor, 4),
            "input_emission_dbuv_m": round(in_dbuv, 1),
            "output_emission_dbuv_m": round(out_dbuv, 1),
            "total_emission_dbuv_m": round(total_dbuv, 1),
            "limit_dbuv_m": limit,
            "margin_db": round(margin, 1),
            "compliant": compliant,
            "dominant_source": dominant,
        })

    risk_level = "pass" if worst_margin >= 6 else "marginal" if worst_margin >= 0 else "fail"
    failing = [h for h in harmonics if not h["compliant"]]
    marginal_list = [h for h in harmonics if h["compliant"] and h["margin_db"] < 6]

    # Filter recommendations
    corner_khz = switching_freq_khz / 10.0
    corner_hz = corner_khz * 1e3
    target_z = 0.5
    c_uf = 1e6 / (2 * math.pi * freq_hz * target_z)
    c_f = c_uf * 1e-6
    l_uh = 1e6 / (4 * math.pi ** 2 * corner_hz ** 2 * c_f) if corner_hz > 0 and c_f > 0 else 10.0
    atten = 40 * math.log10(freq_hz / corner_hz) if corner_hz > 0 else 0

    filter_recommendations = {
        "input_filter": {
            "corner_frequency_khz": round(corner_khz, 1),
            "suggested_capacitor_uf": round(c_uf, 2),
            "suggested_inductor_uh": round(l_uh, 2),
            "filter_type": "LC pi-filter",
            "attenuation_at_fsw_db": round(atten, 1),
        },
        "output_filter": {
            "corner_frequency_khz": round(corner_khz, 1),
            "suggested_capacitor_uf": round(c_uf * 2, 2),
            "suggested_inductor_uh": round(l_uh * 0.5, 2),
            "filter_type": "LC filter (output inductor already present)",
        },
    }

    notes = [
        f"Topology: {topology}, duty cycle D = {duty_cycle:.3f}",
        f"Switching: {switching_freq_khz} kHz, rise time ~{rise_time_ns:.0f}ns",
        f"Input current: avg {i_in_avg:.2f}A, peak {i_in_peak:.2f}A",
        f"Output ripple: ~{out_ripple:.2f}A",
        f"Rise time corner: {f_rise_mhz:.1f} MHz",
        f"Standard: {standard.upper()}, distance: {test_distance_m}m",
    ]

    recommendations = []
    if failing:
        freqs = ", ".join(f"{h['frequency_mhz']:.0f}MHz" for h in failing[:5])
        recommendations.append(f"FAIL: {len(failing)} harmonic(s) exceed limit at: {freqs}")

    in_dom = sum(1 for h in harmonics if h["dominant_source"] == "input")
    if in_dom > len(harmonics) / 2:
        recommendations.append(
            f"Input loop is dominant EMI source. Minimize input loop area "
            f"(currently {input_loop_area_mm2}mm^2)."
        )
    else:
        recommendations.append(
            f"Output loop contributes significantly. Minimize output loop area "
            f"(currently {output_loop_area_mm2}mm^2)."
        )

    if risk_level != "pass":
        recommendations.append(
            f"Add input EMI filter with corner <= {corner_khz:.0f} kHz "
            f"(LC: {l_uh:.1f}uH + {c_uf:.1f}uF)."
        )
    if marginal_list:
        recommendations.append(
            f"{len(marginal_list)} harmonic(s) have <6dB margin."
        )

    return {
        "harmonics": harmonics,
        "switching_frequency_khz": switching_freq_khz,
        "duty_cycle": round(duty_cycle, 3),
        "topology": topology,
        "num_harmonics_analyzed": len(harmonics),
        "overall_compliant": total_compliant,
        "risk_level": risk_level,
        "worst_margin_db": round(worst_margin, 1) if worst_margin < 900 else None,
        "worst_frequency_mhz": round(worst_freq, 3) if worst_margin < 900 else None,
        "worst_emission_dbuv_m": round(worst_emission, 1) if worst_margin < 900 else None,
        "failing_harmonics": len(failing),
        "marginal_harmonics": len(marginal_list),
        "input_current_avg_a": round(i_in_avg, 3),
        "input_current_peak_a": round(i_in_peak, 3),
        "output_ripple_a": round(out_ripple, 3),
        "filter_recommendations": filter_recommendations,
        "standard": standard.upper(),
        "test_distance_m": test_distance_m,
        "notes": notes,
        "recommendations": recommendations,
        "parameters": {
            "switching_freq_khz": switching_freq_khz,
            "input_voltage_v": input_voltage_v,
            "output_voltage_v": output_voltage_v,
            "output_current_a": output_current_a,
            "input_loop_area_mm2": input_loop_area_mm2,
            "output_loop_area_mm2": output_loop_area_mm2,
            "topology": topology,
        },
    }

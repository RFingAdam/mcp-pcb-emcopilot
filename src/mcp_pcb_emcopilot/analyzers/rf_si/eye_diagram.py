"""
Statistical eye diagram and channel simulation for high-speed serial links.

Models a PCB channel as a lossy transmission line (conductor + dielectric loss
vs frequency), applies the frequency-domain transfer function to an ideal bit
pattern, and estimates eye opening metrics.

All calculations are pure Python -- no numpy dependency.
"""

from __future__ import annotations

import math
from typing import Optional

# Physical constants
C0 = 299792458.0          # speed of light (m/s)
MU0 = 4.0 * math.pi * 1e-7  # permeability of free space (H/m)
SIGMA_CU = 5.8e7          # conductivity of annealed copper (S/m)


# ---------------------------------------------------------------------------
# Standard eye-opening thresholds (eye_height_mv, eye_width_fraction_ui)
# Keyed by protocol / generic tier.
# ---------------------------------------------------------------------------
_STANDARD_THRESHOLDS = {
    "pcie3": {"min_eye_height_mv": 15, "min_eye_width_ui": 0.30},
    "pcie4": {"min_eye_height_mv": 15, "min_eye_width_ui": 0.30},
    "pcie5": {"min_eye_height_mv": 10, "min_eye_width_ui": 0.25},
    "usb3":  {"min_eye_height_mv": 50, "min_eye_width_ui": 0.40},
    "sata3": {"min_eye_height_mv": 50, "min_eye_width_ui": 0.40},
    "generic_low":  {"min_eye_height_mv": 100, "min_eye_width_ui": 0.50},
    "generic_high": {"min_eye_height_mv": 25,  "min_eye_width_ui": 0.30},
}


def _effective_dielectric_constant(er: float) -> float:
    """Approximate effective Er for microstrip (wide-trace limit)."""
    return (er + 1.0) / 2.0 + (er - 1.0) / 2.0 * (1.0 / math.sqrt(1.0 + 12.0))


def _microstrip_z0(trace_width_mm: float, dielectric_height_mm: float,
                   er: float) -> tuple[float, float]:
    """Return (Z0, er_eff) for a simple microstrip.

    Uses the Hammerstad-Jensen formula.
    """
    w = trace_width_mm
    h = dielectric_height_mm
    u = w / h
    er_eff = (er + 1) / 2 + (er - 1) / 2 * (1 + 12 / u) ** (-0.5)
    if u <= 1:
        z0 = (60.0 / math.sqrt(er_eff)) * math.log(8.0 / u + 0.25 * u)
    else:
        z0 = (120.0 * math.pi) / (math.sqrt(er_eff) * (u + 1.393 + 0.667 * math.log(u + 1.444)))
    return z0, er_eff


def _conductor_loss_db_per_m(frequency_hz: float, trace_width_mm: float,
                             copper_thickness_um: float,
                             z0_ohm: float = 50.0) -> float:
    """Conductor (skin-effect) loss at *frequency_hz* in dB/m.

    Uses the standard microstrip conductor loss formula:
        alpha_c = R_s / (Z0 * w_eff)
    where R_s = sqrt(pi * f * mu0 / sigma).
    """
    if frequency_hz <= 0:
        return 0.0

    w_m = trace_width_mm * 1e-3
    t_m = copper_thickness_um * 1e-6

    # Skin depth
    delta = math.sqrt(1.0 / (math.pi * frequency_hz * MU0 * SIGMA_CU))

    # Surface resistance
    if delta < t_m:
        r_s = 1.0 / (SIGMA_CU * delta)
    else:
        r_s = 1.0 / (SIGMA_CU * t_m)

    # Attenuation constant for microstrip (Np/m)
    # alpha_c = R_s / (Z0 * w)  -- standard relation
    if w_m > 0 and z0_ohm > 0:
        alpha_c = r_s / (z0_ohm * w_m)
    else:
        alpha_c = 0.0
    return alpha_c * 8.686  # Np/m -> dB/m


def _dielectric_loss_db_per_m(frequency_hz: float, er_eff: float,
                              loss_tangent: float) -> float:
    """Dielectric loss at *frequency_hz* in dB/m."""
    if frequency_hz <= 0 or loss_tangent <= 0:
        return 0.0
    alpha_d = (math.pi * frequency_hz * math.sqrt(er_eff) * loss_tangent) / C0
    return alpha_d * 8.686


def _total_channel_loss_db(frequency_hz: float, trace_length_mm: float,
                           trace_width_mm: float, dielectric_height_mm: float,
                           copper_thickness_um: float, er: float,
                           loss_tangent: float) -> float:
    """Total insertion loss (dB, always >= 0) for the channel at *frequency_hz*.

    Combines conductor and dielectric loss.
    """
    z0, er_eff = _microstrip_z0(trace_width_mm, dielectric_height_mm, er)
    cond = _conductor_loss_db_per_m(frequency_hz, trace_width_mm,
                                     copper_thickness_um, z0_ohm=z0)
    diel = _dielectric_loss_db_per_m(frequency_hz, er_eff, loss_tangent)
    total_per_m = cond + diel
    length_m = trace_length_mm / 1000.0
    return total_per_m * length_m


def _isi_penalty_from_pulse_response(channel_loss_at_nyquist_db: float,
                                     num_taps: int = 5) -> float:
    """Estimate ISI penalty from a simplified pulse-response tail summation.

    The channel is modelled as a single-pole low-pass (RC equivalent).
    The ISI penalty is the sum of |cursor - 1| + sum(|pre/post cursors|).

    We approximate:
        cursor amplitude ~ 10^(-IL/20)
        post-cursor k    ~ cursor * (1 - cursor)^k

    Returns a fractional penalty in [0, 1).
    """
    if channel_loss_at_nyquist_db <= 0:
        return 0.0

    h0 = 10 ** (-channel_loss_at_nyquist_db / 20.0)  # main cursor
    if h0 >= 1.0:
        return 0.0

    # Geometric decay model for post-cursors
    decay = 1.0 - h0
    tail_sum = 0.0
    for k in range(1, num_taps + 1):
        tail_sum += h0 * (decay ** k)

    # ISI penalty is the sum of tail energy relative to cursor
    penalty = tail_sum / h0 if h0 > 0 else 0.0
    return min(penalty, 0.95)  # cap at 95 %


def calculate_eye_opening(
    data_rate_gbps: float,
    trace_length_mm: float,
    dielectric_constant: float,
    loss_tangent: float,
    trace_width_mm: float,
    dielectric_height_mm: float,
    copper_thickness_oz: float = 1.0,
    rise_time_ps: float = 50.0,
    v_swing_mv: float = 800.0,
    standard: Optional[str] = None,
) -> dict:
    """Calculate statistical eye opening for a high-speed channel.

    Parameters
    ----------
    data_rate_gbps : float
        Data rate in Gb/s (NRZ assumed).
    trace_length_mm : float
        Trace length in mm.
    dielectric_constant : float
        Substrate relative permittivity (e.g. 4.3 for FR4).
    loss_tangent : float
        Dielectric loss tangent (e.g. 0.02 for FR4).
    trace_width_mm : float
        Trace width in mm.
    dielectric_height_mm : float
        Height to reference plane in mm.
    copper_thickness_oz : float
        Copper weight in oz (1 oz = 35 um, default 1.0).
    rise_time_ps : float
        Signal rise time (20-80%) in ps.
    v_swing_mv : float
        Full differential or single-ended voltage swing in mV (default 800).
    standard : str or None
        Protocol name for pass/fail thresholds (pcie3, pcie4, pcie5,
        usb3, sata3, generic_low, generic_high).  None = generic_high.

    Returns
    -------
    dict
        eye_height_mv, eye_width_ps, jitter breakdown, pass/fail, etc.
    """
    copper_thickness_um = copper_thickness_oz * 35.0  # oz -> um

    # Nyquist frequency
    f_nyquist_hz = data_rate_gbps * 1e9 / 2.0

    # Unit interval
    ui_ps = 1e12 / (data_rate_gbps * 1e9)

    # Channel insertion loss at Nyquist (dB, positive = loss)
    il_at_nyquist = _total_channel_loss_db(
        f_nyquist_hz, trace_length_mm, trace_width_mm,
        dielectric_height_mm, copper_thickness_um,
        dielectric_constant, loss_tangent,
    )

    # Also compute loss at a few other frequencies for reporting
    il_at_1ghz = _total_channel_loss_db(
        1e9, trace_length_mm, trace_width_mm,
        dielectric_height_mm, copper_thickness_um,
        dielectric_constant, loss_tangent,
    )
    il_at_3rd = _total_channel_loss_db(
        f_nyquist_hz * 3, trace_length_mm, trace_width_mm,
        dielectric_height_mm, copper_thickness_um,
        dielectric_constant, loss_tangent,
    )

    # ISI penalty from pulse response model
    isi_penalty = _isi_penalty_from_pulse_response(il_at_nyquist)

    # --- Eye height ---
    # H(f_nyquist) in linear
    h_nyquist_linear = 10.0 ** (-il_at_nyquist / 20.0)
    eye_height_mv = v_swing_mv * h_nyquist_linear * (1.0 - isi_penalty)
    eye_height_mv = max(eye_height_mv, 0.0)

    # --- Jitter ---
    # Deterministic jitter (ISI-induced): proportional to tail energy
    # Approximate: DJ_isi ~ isi_penalty * UI  (bounded heuristic)
    dj_isi_ps = isi_penalty * ui_ps * 0.5  # factor 0.5 empirical

    # Rise-time limited DJ contribution
    # If rise time > UI, it eats into the eye
    dj_rise_ps = max(0.0, rise_time_ps - ui_ps) * 0.5

    # Total deterministic jitter
    dj_total_ps = dj_isi_ps + dj_rise_ps

    # Random jitter (RMS) -- estimate from empirical model
    # Typical PCB channel RJ is 1-5 ps RMS; scale with loss
    rj_rms_ps = 1.0 + 0.3 * il_at_nyquist  # heuristic

    # Total jitter at BER = 1e-12: TJ = DJ + 2 * n * RJ_rms
    # where n = 7.03 for 1e-12 BER (inverse Q-function)
    n_ber12 = 7.03
    tj_ps = dj_total_ps + 2.0 * n_ber12 * rj_rms_ps

    # --- Eye width ---
    eye_width_ps = ui_ps - tj_ps
    eye_width_ps = max(eye_width_ps, 0.0)

    # Propagation delay through channel
    _, er_eff = _microstrip_z0(trace_width_mm, dielectric_height_mm, dielectric_constant)
    prop_delay_ps = trace_length_mm * 1e-3 / C0 * math.sqrt(er_eff) * 1e12

    # --- Pass / Fail ---
    std_key = (standard or "generic_high").lower().replace("-", "").replace(" ", "_")
    thresholds = _STANDARD_THRESHOLDS.get(std_key, _STANDARD_THRESHOLDS["generic_high"])
    min_height = thresholds["min_eye_height_mv"]
    min_width_ui = thresholds["min_eye_width_ui"]
    min_width_ps = min_width_ui * ui_ps

    height_pass = eye_height_mv >= min_height
    width_pass = eye_width_ps >= min_width_ps
    pass_fail = "PASS" if (height_pass and width_pass) else "FAIL"

    # --- Recommendations ---
    recommendations = []
    if not height_pass:
        recommendations.append(
            f"Eye height {eye_height_mv:.1f} mV < {min_height} mV limit. "
            "Consider lower-loss laminate, shorter trace, or equalization."
        )
    if not width_pass:
        recommendations.append(
            f"Eye width {eye_width_ps:.1f} ps < {min_width_ps:.1f} ps limit. "
            "Reduce jitter sources or shorten trace."
        )
    if il_at_nyquist > 10:
        recommendations.append(
            f"Channel loss at Nyquist ({il_at_nyquist:.1f} dB) is very high. "
            "Consider Megtron 6 (Df=0.002) or Rogers 4350B."
        )
    if isi_penalty > 0.3:
        recommendations.append(
            f"ISI penalty {isi_penalty*100:.0f}% -- equalization (CTLE/DFE) may be needed."
        )

    return {
        "eye_height_mv": round(eye_height_mv, 1),
        "eye_width_ps": round(eye_width_ps, 1),
        "eye_width_ui": round(eye_width_ps / ui_ps, 3) if ui_ps > 0 else 0.0,
        "unit_interval_ps": round(ui_ps, 1),
        "pass_fail": pass_fail,
        "standard": std_key,
        "channel_loss": {
            "insertion_loss_at_nyquist_db": round(il_at_nyquist, 2),
            "insertion_loss_at_1ghz_db": round(il_at_1ghz, 2),
            "insertion_loss_at_3rd_harmonic_db": round(il_at_3rd, 2),
            "nyquist_frequency_ghz": round(f_nyquist_hz / 1e9, 3),
        },
        "jitter": {
            "deterministic_jitter_ps": round(dj_total_ps, 1),
            "isi_jitter_ps": round(dj_isi_ps, 1),
            "rise_time_jitter_ps": round(dj_rise_ps, 1),
            "random_jitter_rms_ps": round(rj_rms_ps, 2),
            "total_jitter_ber12_ps": round(tj_ps, 1),
        },
        "isi_penalty_percent": round(isi_penalty * 100, 1),
        "propagation_delay_ps": round(prop_delay_ps, 1),
        "effective_er": round(er_eff, 3),
        "thresholds": {
            "min_eye_height_mv": min_height,
            "min_eye_width_ui": min_width_ui,
            "min_eye_width_ps": round(min_width_ps, 1),
        },
        "parameters": {
            "data_rate_gbps": data_rate_gbps,
            "trace_length_mm": trace_length_mm,
            "dielectric_constant": dielectric_constant,
            "loss_tangent": loss_tangent,
            "trace_width_mm": trace_width_mm,
            "dielectric_height_mm": dielectric_height_mm,
            "copper_thickness_oz": copper_thickness_oz,
            "rise_time_ps": rise_time_ps,
            "v_swing_mv": v_swing_mv,
        },
        "recommendations": recommendations,
    }

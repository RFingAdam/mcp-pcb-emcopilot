"""
Differential pair mode conversion analysis.

Calculates:
- Even/odd mode impedances from geometry (Wadell / Kirschning-Jansen formulas)
- SCD21 from length asymmetry
- Estimated common-mode current from mode conversion
- Estimated radiated-emission increase from common-mode energy
"""

from __future__ import annotations

import math
from typing import Optional

# Physical constants
C0 = 299792458.0          # speed of light, m/s
MU0 = 4 * math.pi * 1e-7
EPS0 = 8.854e-12


def _effective_er_microstrip(w: float, h: float, er: float) -> float:
    """Hammerstad-Jensen effective dielectric constant for microstrip."""
    wh = w / h
    if wh <= 1:
        eps_eff = (er + 1) / 2 + (er - 1) / 2 * (
            1 / math.sqrt(1 + 12 / wh) + 0.04 * (1 - wh) ** 2
        )
    else:
        eps_eff = (er + 1) / 2 + (er - 1) / 2 / math.sqrt(1 + 12 / wh)
    return eps_eff


def _microstrip_z0(w: float, h: float, er: float, er_eff: float) -> float:
    """Microstrip Z0 from width/height ratio and effective Er."""
    wh = w / h
    if wh <= 1:
        return 60 / math.sqrt(er_eff) * math.log(8 / wh + wh / 4)
    else:
        return 120 * math.pi / math.sqrt(er_eff) / (
            wh + 1.393 + 0.667 * math.log(wh + 1.444)
        )


def _mode_impedances_microstrip(w: float, s: float, h: float, er: float):
    """Calculate odd/even mode impedances for edge-coupled microstrip.

    Uses the Kirschning-Jansen formulas (simplified Wadell approach)
    consistent with the DifferentialPairAnalyzer in differential_pair.py.

    Returns (z_odd, z_even, er_eff).
    """
    u = w / h
    g = s / h

    # Effective dielectric constant (Hammerstad-Jensen)
    a = 1 + (1 / 49) * math.log((u ** 4 + (u / 52) ** 2) / (u ** 4 + 0.432)) + \
        (1 / 18.7) * math.log(1 + (u / 18.1) ** 3)
    b = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
    er_eff = (er + 1) / 2 + ((er - 1) / 2) * (1 + 10 / u) ** (-a * b)

    # Single-ended impedance (Hammerstad-Jensen)
    f_u = 6 + (2 * math.pi - 6) * math.exp(-(30.666 / u) ** 0.7528)
    z0_se = (60 / math.sqrt(er_eff)) * math.log(f_u / u + math.sqrt(1 + (2 / u) ** 2))

    # Clamp minimum spacing ratio
    if g < 0.1:
        g = 0.1

    # --- Odd-mode ---
    q1 = 0.8695 * u ** 0.194
    q2 = 1 + 0.7519 * g + 0.189 * g ** 2.31
    q3 = 0.1975 + (16.6 + (8.4 / g) ** 6) ** (-0.387) + \
         (1 / 241) * math.log(g ** 10 / (1 + (g / 3.4) ** 10))
    q4 = (2 * q1 / q2) * (math.exp(-g) * u ** q3 + (2 - math.exp(-g)) * u ** (-q3))

    ao = 0.7287 * (er_eff - (er + 1) / 2) * (1 - math.exp(-0.179 * u))
    bo = 0.747 * er / (0.15 + er)
    co = bo - (bo - 0.207) * math.exp(-0.414 * u)
    do = 0.593 + 0.694 * math.exp(-0.562 * u)
    er_eff_o = (0.5 * (er + 1) + ao - er_eff) * math.exp(-co * g ** do) + er_eff

    z_odd = z0_se * (math.sqrt(er_eff / er_eff_o) /
                     (1 - q4 * math.sqrt(er_eff) / z0_se / 377))

    # --- Even-mode ---
    q5 = 1.794 + 1.14 * math.log(1 + 0.638 / (g + 0.517 * g ** 2.43))
    q6 = 0.2305 + (1 / 281.3) * math.log(g ** 10 / (1 + (g / 5.8) ** 10)) + \
         (1 / 5.1) * math.log(1 + 0.598 * g ** 1.154)
    q7 = (10 + 190 * g ** 2) / (1 + 82.3 * g ** 3)
    q8 = math.exp(-6.5 - 0.95 * math.log(g) - (g / 0.15) ** 5)
    q9 = math.log(q7) * (q8 + 1 / 16.5)
    q10 = (1 / q2) * (q2 * q4 - q5 * math.exp(math.log(u) * q6 * u ** (-q9)))

    ae = 1 + (1 / 49) * math.log((u ** 4 + (u / 52) ** 2) / (u ** 4 + 0.432)) + \
         (1 / 18.7) * math.log(1 + (u / 18.1) ** 3)
    be = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
    er_eff_e = 0.5 * (er + 1) + ae * be * (er - 1) / 2

    z_even = z0_se * (math.sqrt(er_eff / er_eff_e) /
                      (1 - q10 * math.sqrt(er_eff) / z0_se / 377))

    # Physical bounds
    z_odd = max(20, min(z_odd, 150))
    z_even = max(z_odd + 5, min(z_even, 200))

    return z_odd, z_even, er_eff


def _mode_impedances_stripline(w: float, s: float, h: float, er: float):
    """Calculate odd/even mode impedances for edge-coupled stripline.

    Simplified model using coupling-factor approach.

    Returns (z_odd, z_even, er_eff).
    """
    # Total height between ground planes
    b = 2 * h

    # Stripline single-ended Z0 (Cohn formula)
    wh = w / b
    if wh < 0.35:
        k = math.cosh(math.pi * w / (2 * b))
        z0_se = 30 * math.pi / math.sqrt(er) / k
    else:
        z0_se = (60 / math.sqrt(er)) * math.log(4 * b / (0.67 * math.pi * (0.8 * w)))

    # Coupling factor (stronger in stripline)
    s_h = s / h
    coupling = 0.4 * math.exp(-s_h / 0.5) if s_h < 3 else 0.08

    z_odd = z0_se * (1 - coupling)
    z_even = z0_se * (1 + coupling)

    # For stripline, er_eff = er
    return z_odd, z_even, er


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_mode_conversion(
    trace_width_mm: float,
    trace_spacing_mm: float,
    dielectric_height_mm: float,
    dielectric_constant: float,
    length_asymmetry_mm: float,
    data_rate_gbps: float,
    trace_type: str = "microstrip",
) -> dict:
    """Analyze differential pair mode conversion.

    Parameters
    ----------
    trace_width_mm : float
        Width of each trace in mm.
    trace_spacing_mm : float
        Edge-to-edge spacing between traces in mm.
    dielectric_height_mm : float
        Height above reference plane in mm.
    dielectric_constant : float
        Substrate relative permittivity.
    length_asymmetry_mm : float
        Length mismatch (delta_L) between the two traces in mm.
    data_rate_gbps : float
        Signaling rate in Gb/s (used to derive fundamental frequency).
    trace_type : str
        ``"microstrip"`` or ``"stripline"``.

    Returns
    -------
    dict with even/odd mode impedances, SCD21 vs frequency, common-mode
    current estimate, and EMI impact assessment.
    """
    # --- Mode impedances ---
    if trace_type == "stripline":
        z_odd, z_even, er_eff = _mode_impedances_stripline(
            trace_width_mm, trace_spacing_mm, dielectric_height_mm, dielectric_constant
        )
    else:
        z_odd, z_even, er_eff = _mode_impedances_microstrip(
            trace_width_mm, trace_spacing_mm, dielectric_height_mm, dielectric_constant
        )

    z_diff = 2 * z_odd
    z_common = z_even / 2
    coupling_k = (z_even - z_odd) / (z_even + z_odd)

    # --- SCD21 from length asymmetry ---
    # SCD21 ≈ -20*log10(pi * delta_L * f * sqrt(er_eff) / c)
    # Evaluated at the fundamental and several harmonics of the data rate.
    delta_L_m = length_asymmetry_mm / 1000

    # Fundamental = data_rate / 2 (NRZ Nyquist)
    f_fundamental = data_rate_gbps * 1e9 / 2

    scd21_vs_freq = []
    for harmonic in [1, 3, 5, 7]:
        f_hz = f_fundamental * harmonic
        f_ghz = f_hz / 1e9
        arg = math.pi * delta_L_m * f_hz * math.sqrt(er_eff) / C0
        if arg > 0:
            # SCD21 = 20*log10(arg):
            #   arg << 1 → large negative dB (good, minimal conversion)
            #   arg → 1  → 0 dB (total mode conversion)
            if arg >= 1:
                scd21_db = 0.0
            else:
                scd21_db = 20 * math.log10(arg)
        else:
            scd21_db = -80.0  # negligible
        scd21_vs_freq.append({
            "harmonic": harmonic,
            "frequency_ghz": round(f_ghz, 4),
            "scd21_db": round(scd21_db, 2),
        })

    # Worst-case SCD21 (closest to 0 dB = most mode conversion)
    worst_scd21 = max(entry["scd21_db"] for entry in scd21_vs_freq)

    # --- Common-mode current estimate ---
    # V_diff typical ≈ 400 mV pp for high-speed serdes
    v_diff_v = 0.4
    # I_common ≈ V_diff * 10^(SCD21/20) / Z_common
    scd21_linear = 10 ** (worst_scd21 / 20)
    v_common = v_diff_v * scd21_linear
    i_common_ma = v_common / z_common * 1000 if z_common > 0 else 0

    # --- Skew ---
    # velocity = C0 / sqrt(er_eff) in m/s; delay_per_mm = 1e9 * sqrt(er_eff) / C0 ps/mm
    prop_delay_ps_per_mm = math.sqrt(er_eff) * 1e9 / C0  # ps/mm
    skew_ps = length_asymmetry_mm * prop_delay_ps_per_mm
    bit_period_ps = 1e12 / (data_rate_gbps * 1e9)
    skew_percent = (skew_ps / bit_period_ps) * 100 if bit_period_ps > 0 else 0

    # --- EMI impact ---
    # Common-mode radiation is proportional to I_cm * f * cable_length.
    # Estimate relative increase in dB compared to a zero-skew pair.
    # 6 dB per doubling of I_cm, and I_cm is proportional to SCD21.
    emi_increase_db = -worst_scd21  # since SCD21 is negative, flipping sign
    # (SCD21 of -40 dB means common mode is 40 dB below differential → low EMI,
    #  SCD21 of -20 dB means only 20 dB below → +20 dB more EMI than ideal)

    # Risk assessment
    if worst_scd21 > -20:
        risk = "high"
        emi_comment = "Significant common-mode radiation expected — reduce skew or improve symmetry"
    elif worst_scd21 > -30:
        risk = "medium"
        emi_comment = "Moderate mode conversion — may cause EMI issues in sensitive designs"
    elif worst_scd21 > -40:
        risk = "low"
        emi_comment = "Acceptable mode conversion for most applications"
    else:
        risk = "negligible"
        emi_comment = "Excellent differential symmetry — minimal mode conversion"

    notes = []
    if length_asymmetry_mm > 0.5:
        notes.append(f"Length mismatch {length_asymmetry_mm:.2f} mm — consider length tuning serpentine")
    if skew_percent > 10:
        notes.append(f"Skew {skew_ps:.1f} ps is {skew_percent:.1f}% of UI — may degrade eye opening")
    if coupling_k < 0.1:
        notes.append("Weak coupling — traces may be too far apart for good differential signaling")
    elif coupling_k > 0.5:
        notes.append("Very tight coupling — check manufacturing feasibility")

    return {
        "z_odd_ohm": round(z_odd, 2),
        "z_even_ohm": round(z_even, 2),
        "z_diff_ohm": round(z_diff, 2),
        "z_common_ohm": round(z_common, 2),
        "coupling_coefficient": round(coupling_k, 4),
        "effective_er": round(er_eff, 4),
        "scd21_vs_frequency": scd21_vs_freq,
        "worst_scd21_db": round(worst_scd21, 2),
        "common_mode_current_ma": round(i_common_ma, 4),
        "common_mode_voltage_mv": round(v_common * 1000, 3),
        "skew_ps": round(skew_ps, 2),
        "skew_percent_ui": round(skew_percent, 2),
        "emi_increase_db": round(emi_increase_db, 2),
        "mode_conversion_risk": risk,
        "emi_impact": emi_comment,
        "parameters": {
            "trace_width_mm": trace_width_mm,
            "trace_spacing_mm": trace_spacing_mm,
            "dielectric_height_mm": dielectric_height_mm,
            "dielectric_constant": dielectric_constant,
            "length_asymmetry_mm": length_asymmetry_mm,
            "data_rate_gbps": data_rate_gbps,
            "trace_type": trace_type,
        },
        "notes": notes,
    }

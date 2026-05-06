"""
S-parameter extraction and insertion loss analysis for PCB traces.

Calculates frequency-swept S-parameters from trace geometry using
analytical models for conductor loss (skin effect + Hammerstad roughness),
dielectric loss, and mismatch loss.

This is a lightweight, zero-dependency module (no numpy/scikit-rf) designed
for the MCP tool interface.  For full ABCD-matrix cascading with via models
use the SParameterCalculator in sparam_calculator.py instead.
"""

from __future__ import annotations

import math

# Physical constants
C0 = 299792458.0          # speed of light, m/s
MU0 = 4 * math.pi * 1e-7  # permeability of free space
SIGMA_CU = 5.8e7           # copper conductivity, S/m
RHO_CU = 1 / SIGMA_CU     # copper resistivity


def _skin_depth(frequency_hz: float) -> float:
    """Return skin depth in meters for copper at *frequency_hz*."""
    if frequency_hz <= 0:
        return float("inf")
    return math.sqrt(RHO_CU / (math.pi * frequency_hz * MU0))


def _hammerstad_roughness_factor(skin_depth_m: float, surface_roughness_m: float) -> float:
    """Hammerstad-Bekkadal surface-roughness correction factor."""
    if skin_depth_m <= 0:
        return 1.0
    x = (2 * surface_roughness_m / skin_depth_m) ** 2
    return 1 + (2 / math.pi) * math.atan(1.4 * x)


def _effective_er_microstrip(w: float, h: float, er: float) -> float:
    """Hammerstad-Jensen effective dielectric constant for microstrip.

    Parameters are in consistent units (both mm or both m — ratio only).
    """
    wh = w / h
    if wh <= 1:
        eps_eff = (er + 1) / 2 + (er - 1) / 2 * (
            1 / math.sqrt(1 + 12 / wh) + 0.04 * (1 - wh) ** 2
        )
    else:
        eps_eff = (er + 1) / 2 + (er - 1) / 2 / math.sqrt(1 + 12 / wh)
    return eps_eff


def _microstrip_z0(w: float, h: float, t: float, er: float):
    """Return (Z0, er_eff) for microstrip.  Dimensions in mm."""
    # Effective width (Hammerstad thickness correction)
    if w / h < 0.5 * math.pi:
        w_eff = w + t / math.pi * (1 + math.log(4 * math.pi * w / max(t, 1e-6)))
    else:
        w_eff = w + t / math.pi * (1 + math.log(2 * h / max(t, 1e-6)))
    er_eff = _effective_er_microstrip(w_eff, h, er)

    wh = w_eff / h
    if wh <= 1:
        z0 = 60 / math.sqrt(er_eff) * math.log(8 / wh + wh / 4)
    else:
        z0 = 120 * math.pi / math.sqrt(er_eff) / (
            wh + 1.393 + 0.667 * math.log(wh + 1.444)
        )
    return z0, er_eff


def _conductor_loss_db_per_m(frequency_hz: float, z0: float, width_mm: float,
                              copper_thickness_um: float, surface_roughness_um: float) -> float:
    """Conductor loss in dB/m including skin effect and roughness."""
    if frequency_hz <= 0:
        return 0.0
    delta = _skin_depth(frequency_hz)
    delta_um = delta * 1e6
    rq = surface_roughness_um * 1e-6

    roughness = _hammerstad_roughness_factor(delta, rq)

    # Surface resistance
    rs = math.sqrt(math.pi * frequency_hz * MU0 * RHO_CU) * roughness

    # alpha_c = Rs / (Z0 * w)  [Np/m]  (thin-strip approximation)
    width_m = width_mm / 1000
    alpha_c = rs / (z0 * width_m) if (z0 > 0 and width_m > 0) else 0.0
    return alpha_c * 8.686  # Np/m → dB/m


def _dielectric_loss_db_per_m(frequency_hz: float, er_eff: float, loss_tangent: float) -> float:
    """Dielectric attenuation in dB/m.

    alpha_d = (pi * f * sqrt(er_eff) * tan_delta) / c   [Np/m]
    """
    if frequency_hz <= 0 or loss_tangent <= 0:
        return 0.0
    alpha_d = (math.pi * frequency_hz * math.sqrt(er_eff) * loss_tangent) / C0
    return alpha_d * 8.686


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_insertion_loss(
    trace_length_mm: float,
    trace_width_mm: float,
    dielectric_height_mm: float,
    dielectric_constant: float,
    loss_tangent: float,
    copper_thickness_oz: float = 1.0,
    surface_roughness_um: float = 0.5,
    freq_start_mhz: float = 10.0,
    freq_stop_mhz: float = 10000.0,
    num_points: int = 50,
) -> dict:
    """Calculate frequency-swept insertion loss (S21) and return loss (S11).

    Models included:
    * Conductor loss — skin-effect + Hammerstad surface roughness
    * Dielectric loss — alpha_d formula
    * Mismatch loss — from impedance deviation vs 50 ohm reference

    Returns dict with arrays ``frequency_mhz``, ``s21_db``, ``s11_db``,
    plus scalar summaries and notes.
    """
    if num_points < 2:
        num_points = 2
    if freq_start_mhz <= 0:
        freq_start_mhz = 1.0
    if freq_stop_mhz <= freq_start_mhz:
        freq_stop_mhz = freq_start_mhz + 1.0

    copper_thickness_um = copper_thickness_oz * 35.0  # 1 oz = 35 um
    trace_thickness_mm = copper_thickness_oz * 0.035
    length_m = trace_length_mm / 1000
    length_inch = trace_length_mm / 25.4
    z0_ref = 50.0  # reference impedance

    z0, er_eff = _microstrip_z0(trace_width_mm, dielectric_height_mm,
                                 trace_thickness_mm, dielectric_constant)

    # Mismatch: S11 from impedance discontinuity (constant with frequency for a simple
    # model — no length-dependent resonance in this simplified extractor).
    if z0 + z0_ref > 0:
        gamma_mismatch = abs(z0 - z0_ref) / (z0 + z0_ref)
    else:
        gamma_mismatch = 0.0
    if gamma_mismatch > 0:
        s11_mismatch_db = 20 * math.log10(gamma_mismatch)
    else:
        s11_mismatch_db = -60.0  # perfect match floor
    mismatch_loss_db = -10 * math.log10(1 - gamma_mismatch ** 2) if gamma_mismatch < 1 else 100.0

    frequencies_mhz = []
    s21_db_arr = []
    s11_db_arr = []
    conductor_loss_arr = []
    dielectric_loss_arr = []

    # Logarithmic frequency sweep for better coverage
    log_start = math.log10(freq_start_mhz)
    log_stop = math.log10(freq_stop_mhz)

    for i in range(num_points):
        frac = i / (num_points - 1) if num_points > 1 else 0
        f_mhz = 10 ** (log_start + frac * (log_stop - log_start))
        f_hz = f_mhz * 1e6

        cond_db_m = _conductor_loss_db_per_m(f_hz, z0, trace_width_mm,
                                              copper_thickness_um, surface_roughness_um)
        diel_db_m = _dielectric_loss_db_per_m(f_hz, er_eff, loss_tangent)

        cond_total = cond_db_m * length_m
        diel_total = diel_db_m * length_m
        total_loss = cond_total + diel_total + mismatch_loss_db

        s21 = -total_loss  # S21 is negative dB

        frequencies_mhz.append(round(f_mhz, 4))
        s21_db_arr.append(round(s21, 4))
        s11_db_arr.append(round(s11_mismatch_db, 2))
        conductor_loss_arr.append(round(cond_total, 4))
        dielectric_loss_arr.append(round(diel_total, 4))

    # Summary at a few key frequencies
    notes = []
    for check_ghz in [1, 5, 10]:
        check_mhz = check_ghz * 1000
        if check_mhz < freq_start_mhz or check_mhz > freq_stop_mhz:
            continue
        f_hz = check_mhz * 1e6
        cond = _conductor_loss_db_per_m(f_hz, z0, trace_width_mm,
                                         copper_thickness_um, surface_roughness_um)
        diel = _dielectric_loss_db_per_m(f_hz, er_eff, loss_tangent)
        per_inch = (cond + diel) * 0.0254
        notes.append(f"At {check_ghz} GHz: {per_inch:.3f} dB/inch "
                     f"(conductor {cond*0.0254:.3f} + dielectric {diel*0.0254:.3f})")

    if loss_tangent > 0.015:
        notes.append(f"High loss tangent ({loss_tangent}) — consider low-loss laminate for >5 GHz")
    if surface_roughness_um > 1.0:
        notes.append(f"Rough copper ({surface_roughness_um} um) adds significant conductor loss at high frequency")

    z_deviation_pct = abs(z0 - z0_ref) / z0_ref * 100
    if z_deviation_pct > 10:
        notes.append(f"Trace impedance {z0:.1f} ohm deviates {z_deviation_pct:.1f}% from 50 ohm — adjust width")

    return {
        "frequency_mhz": frequencies_mhz,
        "s21_db": s21_db_arr,
        "s11_db": s11_db_arr,
        "conductor_loss_db": conductor_loss_arr,
        "dielectric_loss_db": dielectric_loss_arr,
        "trace_impedance_ohm": round(z0, 2),
        "effective_er": round(er_eff, 4),
        "mismatch_loss_db": round(mismatch_loss_db, 4),
        "return_loss_db": round(-s11_mismatch_db, 2),  # positive convention
        "vswr": round((1 + gamma_mismatch) / max(1 - gamma_mismatch, 1e-9), 3),
        "trace_length_mm": trace_length_mm,
        "trace_length_inch": round(length_inch, 3),
        "parameters": {
            "trace_width_mm": trace_width_mm,
            "dielectric_height_mm": dielectric_height_mm,
            "dielectric_constant": dielectric_constant,
            "loss_tangent": loss_tangent,
            "copper_thickness_oz": copper_thickness_oz,
            "surface_roughness_um": surface_roughness_um,
        },
        "notes": notes,
    }


def calculate_return_loss(
    impedance_ohm: float,
    target_impedance_ohm: float,
    frequency_mhz: float,
) -> dict:
    """Calculate return loss and VSWR from impedance mismatch.

    Parameters
    ----------
    impedance_ohm : float
        Actual trace / load impedance.
    target_impedance_ohm : float
        Target (reference) impedance.
    frequency_mhz : float
        Frequency of interest (for context; mismatch is frequency-flat
        in the simple model).

    Returns
    -------
    dict with S11_dB, mismatch_loss_dB, VSWR, reflection coefficient.
    """
    z = impedance_ohm
    z0 = target_impedance_ohm
    if z + z0 <= 0:
        return {"error": "Impedances must be positive"}

    gamma = abs(z - z0) / (z + z0)
    if gamma > 0:
        s11_db = 20 * math.log10(gamma)
    else:
        s11_db = -60.0

    mismatch_loss_db = -10 * math.log10(1 - gamma ** 2) if gamma < 1 else 100.0
    vswr = (1 + gamma) / max(1 - gamma, 1e-9)

    notes = []
    if vswr > 2.0:
        notes.append(f"VSWR {vswr:.2f} — significant mismatch, consider impedance matching")
    elif vswr > 1.5:
        notes.append(f"VSWR {vswr:.2f} — moderate mismatch")
    else:
        notes.append(f"VSWR {vswr:.3f} — good match")

    return {
        "s11_db": round(s11_db, 3),
        "return_loss_db": round(-s11_db, 3),
        "mismatch_loss_db": round(mismatch_loss_db, 4),
        "vswr": round(vswr, 4),
        "reflection_coefficient": round(gamma, 5),
        "impedance_ohm": impedance_ohm,
        "target_impedance_ohm": target_impedance_ohm,
        "frequency_mhz": frequency_mhz,
        "notes": notes,
    }

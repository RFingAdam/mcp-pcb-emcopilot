"""
Frequency-swept PDN impedance profiling.

Models VRM, bulk capacitors, MLCC decoupling capacitors, and plane capacitance
as individual RLC networks combined in parallel.  Sweeps from freq_start to
freq_stop on a logarithmic grid and compares the resulting |Z(f)| against a
target impedance derived from supply voltage, ripple budget, and max load
current.  Anti-resonance peaks that exceed the target are flagged.

All arithmetic uses the stdlib ``cmath`` module -- no numpy required.
"""

from __future__ import annotations

import cmath
import math
from typing import Optional

# Vacuum permittivity (F/m)
_EPS0 = 8.854187817e-12


def _log_space(start: float, stop: float, num: int) -> list[float]:
    """Return *num* logarithmically-spaced points from *start* to *stop*."""
    if num < 2:
        return [start]
    log_start = math.log10(start)
    log_stop = math.log10(stop)
    step = (log_stop - log_start) / (num - 1)
    return [10 ** (log_start + i * step) for i in range(num)]


def _cap_impedance(freq_hz: float, capacitance_f: float, esr_ohm: float, esl_h: float) -> complex:
    """Impedance of a series RLC (capacitor model): Z = ESR + j(wL - 1/wC)."""
    omega = 2 * math.pi * freq_hz
    z_c = -1j / (omega * capacitance_f) if capacitance_f > 0 else 0j
    z_l = 1j * omega * esl_h
    return esr_ohm + z_c + z_l


def _vrm_impedance(freq_hz: float, r_out_ohm: float, l_out_h: float) -> complex:
    """VRM output impedance modelled as R_out in parallel with L_out.

    Below the VRM bandwidth the impedance is dominated by R_out (the
    feedback-regulated output impedance).  Above the bandwidth the inductor
    dominates and the impedance rises with frequency.
    """
    omega = 2 * math.pi * freq_hz
    z_l = 1j * omega * l_out_h
    if abs(z_l) < 1e-15:
        return complex(r_out_ohm, 0)
    # Parallel combination: 1/Z = 1/R + 1/jωL
    return (r_out_ohm * z_l) / (r_out_ohm + z_l)


def calculate_pdn_impedance(
    supply_voltage_v: float,
    max_current_a: float,
    ripple_percent: float = 5.0,
    capacitors: Optional[list[dict]] = None,
    vrm_bandwidth_khz: float = 50.0,
    vrm_r_out_mohm: float = 1.0,
    plane_area_mm2: float = 0.0,
    dielectric_height_mm: float = 0.1,
    dielectric_constant: float = 4.3,
    freq_start_hz: float = 1.0,
    freq_stop_hz: float = 1e9,
    num_points: int = 500,
) -> dict:
    """Perform a frequency-swept PDN impedance analysis.

    Parameters
    ----------
    supply_voltage_v : float
        Nominal supply rail voltage (V).
    max_current_a : float
        Maximum transient load current (A).
    ripple_percent : float
        Allowed peak-to-peak voltage ripple as a percentage of the supply.
    capacitors : list[dict] | None
        Each dict: ``{capacitance_uf, esr_mohm, esl_nh, quantity}``.
        Represents bulk electrolytics **and** MLCC decoupling caps.
    vrm_bandwidth_khz : float
        VRM control-loop bandwidth in kHz.  Used to derive the output
        inductance: ``L_out = R_out / (2 * pi * BW)``.
    vrm_r_out_mohm : float
        VRM closed-loop output resistance in milliohms.
    plane_area_mm2 : float
        Area of the power-ground plane pair (mm^2).  Set to 0 to omit.
    dielectric_height_mm : float
        Spacing between power and ground planes (mm).
    dielectric_constant : float
        Relative permittivity of the dielectric between planes.
    freq_start_hz : float
        Start of the sweep (Hz).
    freq_stop_hz : float
        End of the sweep (Hz).
    num_points : int
        Number of logarithmically-spaced frequency points.

    Returns
    -------
    dict
        Keys: ``frequencies_hz``, ``impedance_ohm``, ``phase_deg``,
        ``target_impedance_ohm``, ``anti_resonances``, ``meets_target``,
        ``worst_impedance_ohm``, ``worst_frequency_hz``, ``notes``.
    """
    # ------------------------------------------------------------------ target
    z_target = (supply_voltage_v * ripple_percent / 100.0) / max_current_a

    # ----------------------------------------------------------- VRM model
    r_out = vrm_r_out_mohm * 1e-3  # to Ohms
    bw_hz = vrm_bandwidth_khz * 1e3
    l_out = r_out / (2 * math.pi * bw_hz) if bw_hz > 0 else 1e-6

    # ------------------------------------------------------- plane capacitance
    c_plane = 0.0
    if plane_area_mm2 > 0 and dielectric_height_mm > 0:
        area_m2 = plane_area_mm2 * 1e-6
        height_m = dielectric_height_mm * 1e-3
        c_plane = dielectric_constant * _EPS0 * area_m2 / height_m

    # ----------------------------------------------------- build capacitor list
    cap_list: list[dict] = []
    if capacitors:
        for cap in capacitors:
            cap_list.append({
                "c_f": cap.get("capacitance_uf", 0.1) * 1e-6,
                "esr": cap.get("esr_mohm", 10) * 1e-3,
                "esl": cap.get("esl_nh", 0.5) * 1e-9,
                "qty": cap.get("quantity", 1),
            })

    # ----------------------------------------------------------------- sweep
    frequencies = _log_space(freq_start_hz, freq_stop_hz, num_points)
    impedance_mag: list[float] = []
    impedance_phase: list[float] = []

    for f in frequencies:
        # Total admittance (sum of parallel branches)
        y_total = 0j

        # VRM branch
        z_vrm = _vrm_impedance(f, r_out, l_out)
        if abs(z_vrm) > 1e-15:
            y_total += 1.0 / z_vrm

        # Plane capacitance branch (ideal cap -- negligible ESR/ESL)
        if c_plane > 0:
            omega = 2 * math.pi * f
            z_plane = 1.0 / (1j * omega * c_plane)
            y_total += 1.0 / z_plane

        # Discrete capacitors
        for cap in cap_list:
            z_cap = _cap_impedance(f, cap["c_f"], cap["esr"], cap["esl"])
            if abs(z_cap) > 1e-15:
                y_total += cap["qty"] / z_cap

        # Convert admittance back to impedance
        if abs(y_total) > 1e-15:
            z_total = 1.0 / y_total
        else:
            z_total = complex(1e6, 0)

        impedance_mag.append(abs(z_total))
        impedance_phase.append(math.degrees(cmath.phase(z_total)))

    # ------------------------------------------------ anti-resonance detection
    # An anti-resonance is a *local maximum* in |Z(f)| where impedance rises
    # between two capacitor SRFs.  We look for peaks that exceed z_target.
    anti_resonances: list[dict] = []
    worst_z = 0.0
    worst_f = frequencies[0]

    for i in range(1, len(frequencies) - 1):
        z_prev, z_cur, z_next = impedance_mag[i - 1], impedance_mag[i], impedance_mag[i + 1]
        if z_cur > z_prev and z_cur > z_next:
            # local peak
            if z_cur > z_target:
                anti_resonances.append({
                    "frequency_hz": round(frequencies[i], 2),
                    "impedance_ohm": round(z_cur, 6),
                    "exceeds_target_by_db": round(20 * math.log10(z_cur / z_target), 2),
                })
        if z_cur > worst_z:
            worst_z = z_cur
            worst_f = frequencies[i]

    # Also check endpoints
    if impedance_mag[0] > worst_z:
        worst_z = impedance_mag[0]
        worst_f = frequencies[0]
    if impedance_mag[-1] > worst_z:
        worst_z = impedance_mag[-1]
        worst_f = frequencies[-1]

    meets_target = worst_z <= z_target

    # ----------------------------------------------------------------- notes
    notes: list[str] = []
    notes.append(f"Target impedance: {z_target*1e3:.2f} mohm ({supply_voltage_v}V * {ripple_percent}% / {max_current_a}A)")
    if c_plane > 0:
        notes.append(f"Plane capacitance: {c_plane*1e9:.2f} nF ({plane_area_mm2} mm^2, {dielectric_height_mm} mm spacing, er={dielectric_constant})")
    if cap_list:
        total_caps = sum(c["qty"] for c in cap_list)
        notes.append(f"Discrete capacitors: {total_caps} total across {len(cap_list)} value(s)")
    notes.append(f"VRM: R_out={vrm_r_out_mohm} mohm, BW={vrm_bandwidth_khz} kHz, L_out={l_out*1e6:.3f} uH")
    if anti_resonances:
        notes.append(f"{len(anti_resonances)} anti-resonance peak(s) exceed target impedance")
    if meets_target:
        margin_db = 20 * math.log10(z_target / worst_z) if worst_z > 0 else float("inf")
        notes.append(f"PASS: worst-case impedance {worst_z*1e3:.2f} mohm with {margin_db:.1f} dB margin")
    else:
        overshoot_db = 20 * math.log10(worst_z / z_target) if z_target > 0 else float("inf")
        notes.append(f"FAIL: worst-case impedance {worst_z*1e3:.2f} mohm exceeds target by {overshoot_db:.1f} dB")

    return {
        "frequencies_hz": [round(f, 2) for f in frequencies],
        "impedance_ohm": [round(z, 8) for z in impedance_mag],
        "phase_deg": [round(p, 2) for p in impedance_phase],
        "target_impedance_ohm": round(z_target, 8),
        "anti_resonances": anti_resonances,
        "meets_target": meets_target,
        "worst_impedance_ohm": round(worst_z, 8),
        "worst_frequency_hz": round(worst_f, 2),
        "notes": notes,
    }

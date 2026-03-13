"""Power plane cavity resonance analyzer.

Calculates resonant modes of rectangular plane pairs and identifies
problematic frequencies that may couple with switching or clock harmonics.
"""
from __future__ import annotations

import math
from typing import Any


# Physical constants
_C0 = 299792458.0  # Speed of light (m/s)
_MU0 = 4 * math.pi * 1e-7  # Permeability of free space (H/m)
_EPS0 = 8.854187817e-12  # Permittivity of free space (F/m)


def analyze_cavity_resonance(
    plane_width_mm: float,
    plane_height_mm: float,
    dielectric_height_mm: float,
    dielectric_constant: float,
    max_frequency_hz: float = 5e9,
    loss_tangent: float = 0.02,
    copper_conductivity: float = 5.8e7,
) -> dict[str, Any]:
    """Calculate resonant modes of a rectangular plane pair cavity.

    Uses the cavity model for parallel plate resonance:
    f_mn = c / (2 * sqrt(er)) * sqrt((m/a)^2 + (n/b)^2)

    where m,n are mode indices, a,b are plane dimensions.

    Parameters
    ----------
    plane_width_mm : float
        Width of the rectangular plane in mm.
    plane_height_mm : float
        Height (length) of the rectangular plane in mm.
    dielectric_height_mm : float
        Spacing between the power and ground planes in mm.
    dielectric_constant : float
        Relative permittivity of the dielectric between planes.
    max_frequency_hz : float
        Upper frequency limit for mode search (Hz). Default 5 GHz.
    loss_tangent : float
        Dielectric loss tangent. Default 0.02 (FR-4).
    copper_conductivity : float
        Copper conductivity in S/m. Default 5.8e7.

    Returns
    -------
    dict[str, Any]
        Cavity resonance analysis results including modes, problematic
        frequencies, and decoupling recommendations.
    """
    a = plane_width_mm / 1000.0  # convert to meters
    b = plane_height_mm / 1000.0
    h = dielectric_height_mm / 1000.0
    er = dielectric_constant

    modes: list[dict[str, Any]] = []
    v = _C0 / math.sqrt(er)  # velocity in dielectric

    # Calculate upper bounds for mode indices
    max_m = int(2 * a * max_frequency_hz / v) + 2
    max_n = int(2 * b * max_frequency_hz / v) + 2

    for m in range(0, max_m + 1):
        for n in range(0, max_n + 1):
            if m == 0 and n == 0:
                continue  # DC mode, skip

            f_mn = (v / 2) * math.sqrt((m / a) ** 2 + (n / b) ** 2)

            if f_mn <= max_frequency_hz:
                # Calculate Q factor (simplified)
                omega = 2 * math.pi * f_mn

                # Dielectric Q
                Q_dielectric = 1.0 / loss_tangent if loss_tangent > 0 else 1000.0

                # Skin depth and conductor loss
                if omega > 0:
                    skin_depth = math.sqrt(2.0 / (omega * _MU0 * copper_conductivity))
                else:
                    skin_depth = 1e-6
                Rs = 1.0 / (copper_conductivity * skin_depth) if skin_depth > 0 else 0.0

                # Conductor Q
                Q_conductor = (omega * _MU0 * h / (2 * Rs)) if Rs > 0 else 1000.0

                # Combined Q (parallel combination of loss mechanisms)
                if Q_conductor > 0 and Q_dielectric > 0:
                    Q_total = 1.0 / (1.0 / Q_dielectric + 1.0 / Q_conductor)
                else:
                    Q_total = Q_dielectric

                # Impedance at resonance (simplified peak impedance)
                if omega > 0:
                    Z_peak = Q_total * h / (er * _EPS0 * a * b * omega)
                else:
                    Z_peak = 0.0

                # Bandwidth
                bw_mhz = round(f_mn / (Q_total * 1e6), 1) if Q_total > 0 else 0.0

                modes.append({
                    "mode": f"TM{m}{n}",
                    "frequency_hz": round(f_mn, 0),
                    "frequency_mhz": round(f_mn / 1e6, 1),
                    "q_factor": round(Q_total, 1),
                    "peak_impedance_ohm": round(Z_peak, 3),
                    "bandwidth_mhz": bw_mhz,
                })

    # Sort by frequency
    modes.sort(key=lambda x: x["frequency_hz"])

    # Identify problematic modes (near common clock frequencies)
    common_clocks = [
        25e6, 33.33e6, 48e6, 50e6, 100e6, 125e6, 133e6,
        200e6, 266e6, 333e6, 400e6, 500e6, 800e6,
        1e9, 1.6e9, 2.4e9, 2.5e9, 3.2e9,
    ]
    problematic: list[dict[str, Any]] = []
    for mode in modes:
        for clk in common_clocks:
            if abs(mode["frequency_hz"] - clk) / clk < 0.05:  # within 5%
                problematic.append({
                    **mode,
                    "near_clock_mhz": round(clk / 1e6, 1),
                    "offset_percent": round(
                        abs(mode["frequency_hz"] - clk) / clk * 100, 1
                    ),
                })

    # Decoupling recommendations for first 10 modes
    recommendations: list[dict[str, Any]] = []
    for mode in modes[:10]:
        f = mode["frequency_hz"]
        # C = 1 / (4 * pi^2 * f^2 * ESL)
        # Assuming 1 nH ESL for MLCC
        esl = 1e-9
        if f > 0:
            c_needed = 1.0 / (4 * math.pi ** 2 * f ** 2 * esl)
        else:
            c_needed = 0.0
        if c_needed > 0:
            recommendations.append({
                "mode": mode["mode"],
                "frequency_mhz": mode["frequency_mhz"],
                "suggested_cap_nf": round(c_needed * 1e9, 2),
                "suggested_cap_value": _format_cap(c_needed),
            })

    return {
        "success": True,
        "plane_dimensions_mm": {
            "width": plane_width_mm,
            "height": plane_height_mm,
        },
        "dielectric": {
            "height_mm": dielectric_height_mm,
            "er": dielectric_constant,
            "loss_tangent": loss_tangent,
        },
        "total_modes_found": len(modes),
        "modes": modes[:20],  # Return first 20 modes
        "problematic_modes": problematic,
        "decoupling_recommendations": recommendations[:10],
        "first_resonance_mhz": modes[0]["frequency_mhz"] if modes else None,
    }


def _format_cap(farads: float) -> str:
    """Format capacitance value in human-readable units."""
    if farads >= 1e-6:
        return f"{farads * 1e6:.1f}uF"
    elif farads >= 1e-9:
        return f"{farads * 1e9:.1f}nF"
    else:
        return f"{farads * 1e12:.1f}pF"

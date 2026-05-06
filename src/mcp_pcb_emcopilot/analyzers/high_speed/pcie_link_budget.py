"""
PCIe link budget analysis and lane skew validation.

Calculates total insertion loss from trace, connector, via, and package
contributions, then compares against PCIe generation spec limits.
Equalizer margin is the difference between the spec limit and actual loss.
Lane-to-lane skew is validated against generation-specific requirements.

All arithmetic uses pure Python math -- no numpy required.
"""

from __future__ import annotations

import math

# PCIe generation specifications
# Each entry: (data_rate_gts, nyquist_freq_ghz, insertion_loss_limit_db, max_lane_skew_ps)
_PCIE_SPECS: dict[int, dict] = {
    1: {
        "data_rate_gts": 2.5,
        "nyquist_ghz": 1.25,
        "loss_limit_db": 3.5,
        "max_lane_skew_ps": 20000,  # Gen1/2 very relaxed
        "label": "Gen1 (2.5 GT/s)",
    },
    2: {
        "data_rate_gts": 5.0,
        "nyquist_ghz": 2.5,
        "loss_limit_db": 5.0,
        "max_lane_skew_ps": 8000,
        "label": "Gen2 (5 GT/s)",
    },
    3: {
        "data_rate_gts": 8.0,
        "nyquist_ghz": 4.0,
        "loss_limit_db": 8.0,
        "max_lane_skew_ps": 1500,
        "label": "Gen3 (8 GT/s)",
    },
    4: {
        "data_rate_gts": 16.0,
        "nyquist_ghz": 8.0,
        "loss_limit_db": 16.0,
        "max_lane_skew_ps": 200,
        "label": "Gen4 (16 GT/s)",
    },
    5: {
        "data_rate_gts": 32.0,
        "nyquist_ghz": 16.0,
        "loss_limit_db": 28.0,
        "max_lane_skew_ps": 200,
        "label": "Gen5 (32 GT/s)",
    },
    6: {
        "data_rate_gts": 64.0,
        "nyquist_ghz": 32.0,
        "loss_limit_db": 36.0,
        "max_lane_skew_ps": 200,
        "label": "Gen6 (64 GT/s)",
    },
}


def _trace_loss_db(
    length_mm: float,
    frequency_ghz: float,
    dielectric_constant: float,
    loss_tangent: float,
    copper_thickness_oz: float,
) -> float:
    """Estimate total trace insertion loss (conductor + dielectric) in dB.

    Conductor loss uses the skin-effect model:
        alpha_c = R_s / (2 * Z0 * w_eff)  (simplified to sqrt(f) dependency)

    Dielectric loss:
        alpha_d = pi * f * sqrt(er_eff) * tan_d / c

    Both are summed and multiplied by length.
    """
    f_hz = frequency_ghz * 1e9
    length_m = length_mm * 1e-3

    # Effective permittivity (rough microstrip estimate)
    er_eff = (dielectric_constant + 1) / 2 + (dielectric_constant - 1) / 2 * 0.6

    # --- Conductor loss (skin effect) ---
    # Surface resistance: Rs = sqrt(pi * f * mu0 / sigma)
    mu0 = 4 * math.pi * 1e-7
    sigma_cu = 5.8e7  # S/m
    rs = math.sqrt(math.pi * f_hz * mu0 / sigma_cu) if f_hz > 0 else 0

    # Approximate Z0 ~ 50 ohm, trace width from copper thickness
    copper_t_m = copper_thickness_oz * 35e-6  # 1 oz = 35 um
    # Rough conductor attenuation: alpha_c = Rs / (Z0 * width)
    # We use an empirical model: conductor_loss_db_per_m ~ k_c * sqrt(f_ghz)
    # where k_c accounts for 50-ohm geometry at the given copper weight
    k_c = rs / (2 * 50) * 8.686  # Np/m -> dB/m
    conductor_loss_db = k_c * length_m

    # --- Dielectric loss ---
    c0 = 299792458.0
    if f_hz > 0 and loss_tangent > 0:
        alpha_d = (math.pi * f_hz * math.sqrt(er_eff) * loss_tangent) / c0  # Np/m
        dielectric_loss_db = alpha_d * 8.686 * length_m
    else:
        dielectric_loss_db = 0.0

    return conductor_loss_db + dielectric_loss_db


def calculate_pcie_link_budget(
    pcie_gen: int,
    trace_length_mm: float,
    dielectric_constant: float = 4.0,
    loss_tangent: float = 0.02,
    copper_thickness_oz: float = 0.5,
    connector_loss_db: float = 0.0,
    via_loss_db: float = 0.0,
    package_loss_db: float = 0.0,
) -> dict:
    """Calculate PCIe link insertion loss budget and equalizer margin.

    Parameters
    ----------
    pcie_gen : int
        PCIe generation (1-6).
    trace_length_mm : float
        Total PCB trace length for the lane (mm).
    dielectric_constant : float
        Dielectric constant of the laminate.
    loss_tangent : float
        Dielectric loss tangent (e.g. 0.02 for standard FR4).
    copper_thickness_oz : float
        Copper weight (oz).  0.5 oz is common for inner layers.
    connector_loss_db : float
        Total connector insertion loss (dB) -- positive value.
    via_loss_db : float
        Total via transition insertion loss (dB) -- positive value.
    package_loss_db : float
        IC package trace/ball insertion loss (dB) -- positive value.

    Returns
    -------
    dict
        Keys: ``pcie_generation``, ``spec_limit_db``, ``trace_loss_db``,
        ``connector_loss_db``, ``via_loss_db``, ``package_loss_db``,
        ``total_loss_db``, ``equalizer_margin_db``, ``pass_fail``, ``notes``.
    """
    if pcie_gen not in _PCIE_SPECS:
        raise ValueError(f"Unsupported PCIe generation: {pcie_gen}. Use 1-6.")

    spec = _PCIE_SPECS[pcie_gen]
    freq_ghz = spec["nyquist_ghz"]
    spec_limit = spec["loss_limit_db"]

    trace_loss = _trace_loss_db(
        trace_length_mm, freq_ghz, dielectric_constant, loss_tangent, copper_thickness_oz,
    )

    total_loss = trace_loss + connector_loss_db + via_loss_db + package_loss_db
    eq_margin = spec_limit - total_loss
    pass_fail = "PASS" if eq_margin > 0 else "FAIL"

    notes: list[str] = []
    notes.append(f"{spec['label']} @ {freq_ghz} GHz Nyquist")
    notes.append(f"Trace loss: {trace_loss:.2f} dB over {trace_length_mm} mm")
    if connector_loss_db > 0:
        notes.append(f"Connector loss: {connector_loss_db:.2f} dB")
    if via_loss_db > 0:
        notes.append(f"Via loss: {via_loss_db:.2f} dB")
    if package_loss_db > 0:
        notes.append(f"Package loss: {package_loss_db:.2f} dB")

    if eq_margin < 0:
        notes.append(f"FAIL: total loss exceeds spec by {-eq_margin:.2f} dB -- reduce trace length, use lower-loss laminate, or add retimers")
    elif eq_margin < 3:
        notes.append(f"WARNING: only {eq_margin:.2f} dB margin -- consider design improvements for production robustness")
    else:
        notes.append(f"PASS: {eq_margin:.2f} dB equalizer margin available")

    if loss_tangent > 0.015 and pcie_gen >= 4:
        notes.append("Consider low-loss laminate (Megtron 6, IS680, etc.) for Gen4+ designs")

    return {
        "pcie_generation": spec["label"],
        "nyquist_frequency_ghz": freq_ghz,
        "spec_limit_db": round(spec_limit, 2),
        "trace_loss_db": round(trace_loss, 3),
        "connector_loss_db": round(connector_loss_db, 3),
        "via_loss_db": round(via_loss_db, 3),
        "package_loss_db": round(package_loss_db, 3),
        "total_loss_db": round(total_loss, 3),
        "equalizer_margin_db": round(eq_margin, 3),
        "pass_fail": pass_fail,
        "notes": notes,
    }


def validate_pcie_lanes(
    lane_lengths_mm: dict[str, float],
    dielectric_constant: float = 4.0,
    pcie_gen: int = 4,
) -> dict:
    """Validate lane-to-lane skew for a set of PCIe lanes.

    Parameters
    ----------
    lane_lengths_mm : dict[str, float]
        Mapping of lane name to trace length in mm.
        Example: ``{"TX0": 80.5, "TX1": 81.2, "TX2": 79.8, "TX3": 80.0}``
    dielectric_constant : float
        Dielectric constant used for propagation delay calculation.
    pcie_gen : int
        PCIe generation (1-6) for spec lookup.

    Returns
    -------
    dict
        Keys: ``lanes``, ``reference_lane``, ``skews_ps``, ``max_skew_ps``,
        ``spec_limit_ps``, ``pass_fail``, ``notes``.
    """
    if pcie_gen not in _PCIE_SPECS:
        raise ValueError(f"Unsupported PCIe generation: {pcie_gen}. Use 1-6.")

    spec = _PCIE_SPECS[pcie_gen]
    max_skew_limit_ps = spec["max_lane_skew_ps"]

    # Propagation delay: v_prop = c / sqrt(er_eff)
    c0 = 299792458.0  # m/s
    er_eff = (dielectric_constant + 1) / 2 + (dielectric_constant - 1) / 2 * 0.6
    v_prop = c0 / math.sqrt(er_eff)  # m/s
    delay_ps_per_mm = (1e-3 / v_prop) * 1e12  # ps/mm

    # Per-lane delays
    lane_delays: dict[str, float] = {}
    for lane_name, length in lane_lengths_mm.items():
        lane_delays[lane_name] = length * delay_ps_per_mm

    if not lane_delays:
        return {
            "lanes": {},
            "reference_lane": None,
            "skews_ps": {},
            "max_skew_ps": 0.0,
            "spec_limit_ps": max_skew_limit_ps,
            "pass_fail": "PASS",
            "notes": ["No lanes provided"],
        }

    # Reference lane = the one with minimum delay (shortest trace)
    ref_lane = min(lane_delays, key=lambda k: lane_delays[k])
    ref_delay = lane_delays[ref_lane]

    # Calculate skew relative to reference
    skews: dict[str, float] = {}
    for lane_name, delay in lane_delays.items():
        skews[lane_name] = round(delay - ref_delay, 2)

    max_skew = max(skews.values()) if skews else 0.0
    pass_fail = "PASS" if max_skew <= max_skew_limit_ps else "FAIL"

    # Build per-lane info
    lanes_info: dict[str, dict] = {}
    for lane_name in lane_lengths_mm:
        lanes_info[lane_name] = {
            "length_mm": round(lane_lengths_mm[lane_name], 3),
            "delay_ps": round(lane_delays[lane_name], 2),
            "skew_ps": skews[lane_name],
            "within_spec": skews[lane_name] <= max_skew_limit_ps,
        }

    notes: list[str] = []
    notes.append(f"{spec['label']}: max lane-to-lane skew = {max_skew_limit_ps} ps")
    notes.append(f"Propagation delay: {delay_ps_per_mm:.3f} ps/mm (er_eff={er_eff:.2f})")
    notes.append(f"Reference lane: {ref_lane} ({lane_lengths_mm[ref_lane]:.2f} mm)")

    if pass_fail == "FAIL":
        worst_lane = max(skews, key=lambda k: skews[k])
        notes.append(
            f"FAIL: lane {worst_lane} skew {max_skew:.1f} ps exceeds {max_skew_limit_ps} ps limit "
            f"-- shorten by {(max_skew - max_skew_limit_ps) / delay_ps_per_mm:.2f} mm or add serpentine to shorter lanes"
        )
    else:
        margin_ps = max_skew_limit_ps - max_skew
        notes.append(f"PASS: max skew {max_skew:.1f} ps with {margin_ps:.1f} ps margin")

    return {
        "lanes": lanes_info,
        "reference_lane": ref_lane,
        "skews_ps": skews,
        "max_skew_ps": round(max_skew, 2),
        "spec_limit_ps": max_skew_limit_ps,
        "pass_fail": pass_fail,
        "pcie_generation": spec["label"],
        "delay_ps_per_mm": round(delay_ps_per_mm, 3),
        "notes": notes,
    }

"""
Return current density analysis and ground stitch optimization.

Models the return current distribution on a reference plane beneath a
signal trace using the analytical 1/(pi*h) * h^2/(h^2 + x^2) model,
and calculates optimal via stitching spacing to contain return current
within acceptable bounds at a given frequency.

All calculations are pure Python — no external dependencies.
"""

import math
from typing import Optional

# Speed of light (m/s)
C0 = 299792458.0


def _return_current_density(x_mm: float, h_mm: float) -> float:
    """Normalized return current density at lateral offset x from trace.

    J(x) = (1/pi) * h / (h^2 + x^2)

    where h is the trace-to-plane height and x is the lateral offset.
    Result is normalized such that integral from -inf to +inf = 1.

    Parameters
    ----------
    x_mm : float
        Lateral offset from trace center (mm).
    h_mm : float
        Height from trace to reference plane (mm).

    Returns
    -------
    float
        Current density (per mm), normalized to unit total current.
    """
    if h_mm <= 0:
        return 0.0
    return (1.0 / math.pi) * h_mm / (h_mm**2 + x_mm**2)


def _cumulative_return_current(half_width_mm: float, h_mm: float) -> float:
    """Fraction of return current within +/- half_width_mm of trace center.

    Integral of J(x) from -half_width to +half_width:
        I_frac = (2/pi) * arctan(half_width / h)
    """
    if h_mm <= 0:
        return 1.0
    return (2.0 / math.pi) * math.atan(half_width_mm / h_mm)


def _wavelength_mm(frequency_hz: float, er_eff: float) -> float:
    """Wavelength in mm for a signal on a PCB at given frequency."""
    if frequency_hz <= 0:
        return float("inf")
    return (C0 / math.sqrt(er_eff) / frequency_hz) * 1e3


def calculate_return_current_density(
    trace_height_mm: float,
    signal_current_ma: float = 100.0,
    analysis_width_mm: float = 20.0,
    num_points: int = 100,
) -> dict:
    """Calculate the return current density profile across the reference plane.

    Parameters
    ----------
    trace_height_mm : float
        Height from signal trace to reference plane (mm).
    signal_current_ma : float
        Signal current magnitude (mA) for absolute density calculation.
    analysis_width_mm : float
        Total width to analyze, centered on trace (mm).
    num_points : int
        Number of sample points across the width.

    Returns
    -------
    dict
        x positions (mm), current density (mA/mm), cumulative fraction.
    """
    half_width = analysis_width_mm / 2.0
    step = analysis_width_mm / max(num_points - 1, 1)
    signal_current_a = signal_current_ma / 1000.0

    x_positions = []
    density_ma_per_mm = []
    cumulative_fraction = []

    for i in range(num_points):
        x = -half_width + i * step
        j_norm = _return_current_density(x, trace_height_mm)
        j_abs = j_norm * signal_current_a * 1000.0  # mA/mm

        x_positions.append(round(x, 3))
        density_ma_per_mm.append(round(j_abs, 4))
        cumulative_fraction.append(
            round(_cumulative_return_current(abs(x), trace_height_mm), 4)
        )

    # Key metrics
    peak_density = _return_current_density(0, trace_height_mm) * signal_current_a * 1000
    within_3h = _cumulative_return_current(3 * trace_height_mm, trace_height_mm)
    within_5h = _cumulative_return_current(5 * trace_height_mm, trace_height_mm)
    within_10h = _cumulative_return_current(10 * trace_height_mm, trace_height_mm)

    notes = [
        f"Peak density at trace center: {peak_density:.2f} mA/mm",
        f"{within_3h*100:.1f}% of return current within +/- 3h ({3*trace_height_mm:.2f} mm)",
        f"{within_5h*100:.1f}% of return current within +/- 5h ({5*trace_height_mm:.2f} mm)",
        f"{within_10h*100:.1f}% of return current within +/- 10h ({10*trace_height_mm:.2f} mm)",
    ]

    if trace_height_mm > 0.3:
        notes.append(
            "Large trace-to-plane spacing spreads return current widely — "
            "EMI risk increases. Use inner layers closer to planes."
        )

    return {
        "x_positions_mm": x_positions,
        "density_ma_per_mm": density_ma_per_mm,
        "cumulative_fraction": cumulative_fraction,
        "peak_density_ma_per_mm": round(peak_density, 4),
        "current_containment": {
            "within_3h_percent": round(within_3h * 100, 1),
            "within_5h_percent": round(within_5h * 100, 1),
            "within_10h_percent": round(within_10h * 100, 1),
        },
        "trace_height_mm": trace_height_mm,
        "signal_current_ma": signal_current_ma,
        "notes": notes,
    }


def calculate_ground_stitch_spacing(
    max_frequency_hz: float,
    dielectric_constant: float = 4.3,
    trace_height_mm: float = 0.1,
    target_containment_percent: float = 90.0,
    lambda_fraction: float = 20.0,
) -> dict:
    """Calculate optimal ground via stitching spacing.

    Combines two constraints:
    1. Electrical: spacing < lambda/N (default lambda/20) at max frequency
    2. Return current: spacing must contain target_containment_percent of return current

    Parameters
    ----------
    max_frequency_hz : float
        Maximum signal frequency or harmonic to contain (Hz).
    dielectric_constant : float
        Substrate relative permittivity.
    trace_height_mm : float
        Height to reference plane (mm).
    target_containment_percent : float
        Desired return current containment (e.g. 90%).
    lambda_fraction : float
        Fraction of wavelength for spacing rule (e.g. 20 for lambda/20).

    Returns
    -------
    dict
        Recommended spacing, wavelength, containment analysis.
    """
    er_eff = (dielectric_constant + 1.0) / 2.0
    wavelength = _wavelength_mm(max_frequency_hz, er_eff)

    # Constraint 1: lambda / N
    spacing_lambda = wavelength / lambda_fraction

    # Constraint 2: return current containment
    # I_frac = (2/pi) * arctan(half_width / h)
    # half_width = h * tan(pi * I_frac / 2)
    frac = target_containment_percent / 100.0
    frac = min(frac, 0.999)
    half_width = trace_height_mm * math.tan(math.pi * frac / 2.0)
    spacing_current = 2 * half_width  # full width for containment

    # Take the more restrictive (smaller) of the two
    recommended_spacing = min(spacing_lambda, spacing_current)

    notes = []
    notes.append(
        f"Lambda at {max_frequency_hz/1e6:.1f} MHz: {wavelength:.1f} mm "
        f"(er_eff={er_eff:.2f})"
    )
    notes.append(
        f"Lambda/{lambda_fraction:.0f} spacing: {spacing_lambda:.2f} mm"
    )
    notes.append(
        f"Current containment ({target_containment_percent:.0f}%) spacing: "
        f"{spacing_current:.2f} mm"
    )

    if spacing_lambda < spacing_current:
        limiting_factor = "wavelength"
        notes.append("Wavelength is the tighter constraint")
    else:
        limiting_factor = "current_containment"
        notes.append("Return current containment is the tighter constraint")

    if max_frequency_hz > 1e9 and dielectric_constant > 4.0:
        notes.append(
            "At frequencies above 1 GHz, consider that the actual wavelength "
            "depends on the effective Er, not bulk Er."
        )

    return {
        "recommended_spacing_mm": round(recommended_spacing, 2),
        "spacing_from_wavelength_mm": round(spacing_lambda, 2),
        "spacing_from_containment_mm": round(spacing_current, 2),
        "limiting_factor": limiting_factor,
        "wavelength_mm": round(wavelength, 1),
        "effective_er": round(er_eff, 3),
        "frequency_hz": max_frequency_hz,
        "lambda_fraction": lambda_fraction,
        "target_containment_percent": target_containment_percent,
        "notes": notes,
    }


# =============================================================================
# MCP tool-facing functions (Issue #14)
# =============================================================================

# Physical constants for MCP wrappers
_MU0 = 4 * math.pi * 1e-7
_SIGMA_CU = 5.8e7  # S/m for annealed copper


def analyze_return_current_density(
    trace_x_start: float,
    trace_y_start: float,
    trace_x_end: float,
    trace_y_end: float,
    plane_width_mm: float,
    plane_height_mm: float,
    frequency_mhz: float,
    plane_gaps: Optional[list] = None,
) -> dict:
    """Estimate return current density distribution on a reference plane.

    Builds a 10x10 grid of current density for the plane beneath the trace,
    detects crowding near gaps and edges, and classifies the frequency regime
    (resistive / transition / inductive).

    Parameters
    ----------
    trace_x_start, trace_y_start : float
        Trace start coordinates (mm).
    trace_x_end, trace_y_end : float
        Trace end coordinates (mm).
    plane_width_mm, plane_height_mm : float
        Reference plane dimensions (mm).
    frequency_mhz : float
        Signal frequency (MHz).
    plane_gaps : list or None
        Optional gap dicts with keys x_start_mm, y_start_mm, x_end_mm,
        y_end_mm, width_mm.

    Returns
    -------
    dict
        current_distribution (10x10 grid), crowding_locations,
        max_density_ratio, transition_frequency_mhz, current_spreading_mm,
        frequency_regime, notes, recommendations.
    """
    freq_hz = frequency_mhz * 1e6

    # Trace geometry
    dx = trace_x_end - trace_x_start
    dy = trace_y_end - trace_y_start
    trace_length_mm = math.sqrt(dx * dx + dy * dy)
    if trace_length_mm < 0.001:
        trace_length_mm = 0.001

    trace_mid_x = (trace_x_start + trace_x_end) / 2.0
    trace_mid_y = (trace_y_start + trace_y_end) / 2.0

    # Default dielectric height (typical prepreg)
    h_mm = 0.2

    # Skin depth
    if freq_hz > 0:
        skin_depth_mm = math.sqrt(1.0 / (math.pi * freq_hz * _MU0 * _SIGMA_CU)) * 1e3
    else:
        skin_depth_mm = 100.0

    # Transition frequency: f_transition ~ R_dc / (2*pi*L)
    copper_thickness_mm = 0.035
    rho_per_sq = 1.0 / (_SIGMA_CU * copper_thickness_mm * 1e-3)
    h_m = h_mm * 1e-3
    f_transition_hz = rho_per_sq / (2 * math.pi * _MU0 * h_m) if h_m > 0 else 1e9
    f_transition_mhz = f_transition_hz / 1e6

    # Current spreading width
    if freq_hz > f_transition_hz:
        spreading_mm = 3.0 * h_mm
        regime = "inductive"
    elif freq_hz > 0:
        ratio = freq_hz / f_transition_hz
        dc_spreading = min(plane_width_mm, plane_height_mm) / 2.0
        hf_spreading = 3.0 * h_mm
        spreading_mm = hf_spreading + (dc_spreading - hf_spreading) * (1.0 - ratio)
        regime = "transition"
    else:
        spreading_mm = min(plane_width_mm, plane_height_mm) / 2.0
        regime = "resistive"

    # Build 10x10 current density grid
    grid_nx, grid_ny = 10, 10
    cell_w = plane_width_mm / grid_nx
    cell_h = plane_height_mm / grid_ny

    ux = dx / trace_length_mm if trace_length_mm > 0.001 else 1.0
    uy = dy / trace_length_mm if trace_length_mm > 0.001 else 0.0
    px, py = -uy, ux  # perpendicular

    current_grid = []
    max_density = 0.0
    min_density = float("inf")

    for iy in range(grid_ny):
        row = []
        cy = cell_h * (iy + 0.5)
        for ix in range(grid_nx):
            cx = cell_w * (ix + 0.5)
            rel_x = cx - trace_mid_x
            rel_y = cy - trace_mid_y
            perp_dist = abs(rel_x * px + rel_y * py)

            along = rel_x * ux + rel_y * uy
            half_len = trace_length_mm / 2.0
            if abs(along) > half_len:
                extra = abs(along) - half_len
                perp_dist = math.sqrt(perp_dist ** 2 + extra ** 2)

            h_eff = max(h_mm, 0.01)
            if regime == "resistive":
                density = 1.0 / (1.0 + (perp_dist / max(spreading_mm, 0.1)) ** 2)
            else:
                density = h_eff ** 2 / (h_eff ** 2 + perp_dist ** 2)

            row.append(round(density, 4))
            if density > max_density:
                max_density = density
            if density < min_density:
                min_density = density
        current_grid.append(row)

    # Normalize peak to 1.0
    if max_density > 0:
        for iy in range(grid_ny):
            for ix in range(grid_nx):
                current_grid[iy][ix] = round(current_grid[iy][ix] / max_density, 4)
        max_density_ratio = max_density / max(min_density, 1e-10)
    else:
        max_density_ratio = 1.0

    # Crowding near gaps
    crowding_locations = []
    if plane_gaps:
        for gap in plane_gaps:
            gap_mid_x = (gap.get("x_start_mm", 0) + gap.get("x_end_mm", 0)) / 2.0
            gap_mid_y = (gap.get("y_start_mm", 0) + gap.get("y_end_mm", 0)) / 2.0
            gap_width = gap.get("width_mm", 1.0)
            dist = math.sqrt((trace_mid_x - gap_mid_x) ** 2 + (trace_mid_y - gap_mid_y) ** 2)
            crowding = 1.0 + gap_width / (2.0 * max(dist, 0.01))
            crowding_locations.append({
                "gap_center_x_mm": round(gap_mid_x, 2),
                "gap_center_y_mm": round(gap_mid_y, 2),
                "distance_to_trace_mm": round(dist, 2),
                "crowding_factor": round(crowding, 2),
                "severity": "critical" if crowding > 3.0 else "warning" if crowding > 1.5 else "acceptable",
            })

    # Edge crowding
    edge_margin = 2.0 * h_mm
    for label, dist in [
        ("left_edge", trace_mid_x),
        ("right_edge", plane_width_mm - trace_mid_x),
        ("top_edge", trace_mid_y),
        ("bottom_edge", plane_height_mm - trace_mid_y),
    ]:
        if 0 < dist < edge_margin:
            crowding_locations.append({
                "location": label,
                "distance_mm": round(dist, 2),
                "crowding_factor": round(1.0 + edge_margin / (2.0 * dist), 2),
            })

    # Notes / recommendations
    notes = [
        f"Frequency regime: {regime} (transition at {f_transition_mhz:.1f} MHz)",
        f"Current spreading width: {spreading_mm:.2f} mm (90% of current)",
        f"Skin depth in copper: {skin_depth_mm:.3f} mm at {frequency_mhz} MHz",
        f"Max/min density ratio: {max_density_ratio:.1f}:1",
    ]

    recommendations = []
    if regime == "inductive":
        recommendations.append(
            f"At {frequency_mhz} MHz, return current concentrates under the trace "
            f"(within {spreading_mm:.1f} mm). Ensure continuous reference plane."
        )
    elif regime == "transition":
        recommendations.append(
            f"At {frequency_mhz} MHz, current spreading is moderate ({spreading_mm:.1f} mm). "
            "Maintain good plane coverage."
        )
    else:
        recommendations.append(
            "At DC/low frequency, return current spreads broadly. "
            "Ensure low-resistance return paths."
        )

    critical = [c for c in crowding_locations if c.get("severity") == "critical"]
    if critical:
        recommendations.append(
            f"CRITICAL: {len(critical)} location(s) with severe current crowding "
            "near plane gaps. Reroute signal or stitch the gap."
        )

    return {
        "current_distribution": current_grid,
        "grid_cell_width_mm": round(cell_w, 2),
        "grid_cell_height_mm": round(cell_h, 2),
        "crowding_locations": crowding_locations,
        "max_density_ratio": round(max_density_ratio, 1),
        "current_spreading_mm": round(spreading_mm, 2),
        "transition_frequency_mhz": round(f_transition_mhz, 1),
        "frequency_regime": regime,
        "skin_depth_mm": round(skin_depth_mm, 4),
        "trace_length_mm": round(trace_length_mm, 2),
        "notes": notes,
        "recommendations": recommendations,
        "parameters": {
            "trace_x_start": trace_x_start,
            "trace_y_start": trace_y_start,
            "trace_x_end": trace_x_end,
            "trace_y_end": trace_y_end,
            "plane_width_mm": plane_width_mm,
            "plane_height_mm": plane_height_mm,
            "frequency_mhz": frequency_mhz,
            "plane_gaps": plane_gaps,
        },
    }


def optimize_ground_stitching(
    plane_width_mm: float,
    plane_height_mm: float,
    max_frequency_mhz: float,
    dielectric_constant: float,
    existing_vias: Optional[list] = None,
    plane_gaps: Optional[list] = None,
) -> dict:
    """Optimize ground via stitching for a reference plane.

    Via spacing rule: spacing < lambda / (20 * sqrt(er)).

    Parameters
    ----------
    plane_width_mm, plane_height_mm : float
        Reference plane dimensions (mm).
    max_frequency_mhz : float
        Maximum operating frequency (MHz).
    dielectric_constant : float
        Substrate dielectric constant.
    existing_vias : list or None
        Existing via locations [{x_mm, y_mm}, ...].
    plane_gaps : list or None
        Gap definitions [{x_start_mm, y_start_mm, x_end_mm, y_end_mm, width_mm}, ...].

    Returns
    -------
    dict
        suggested_via_locations, spacing_mm, density_per_cm2, notes,
        coverage_analysis, recommendations.
    """
    freq_hz = max_frequency_mhz * 1e6

    # Wavelength in dielectric
    if freq_hz > 0 and dielectric_constant > 0:
        wavelength_mm = (C0 / freq_hz) * 1e3 / math.sqrt(dielectric_constant)
    else:
        wavelength_mm = 1e6

    required_spacing_mm = wavelength_mm / 20.0

    min_spacing = 1.0
    max_spacing = 25.0
    spacing_mm = max(min_spacing, min(max_spacing, required_spacing_mm))

    n_cols = max(2, int(math.ceil(plane_width_mm / spacing_mm)) + 1)
    n_rows = max(2, int(math.ceil(plane_height_mm / spacing_mm)) + 1)
    actual_spacing_x = plane_width_mm / max(n_cols - 1, 1)
    actual_spacing_y = plane_height_mm / max(n_rows - 1, 1)

    # Gap exclusion zones
    gap_zones = []
    if plane_gaps:
        for gap in plane_gaps:
            gap_zones.append({
                "x_min": gap.get("x_start_mm", 0) - 0.5,
                "x_max": gap.get("x_end_mm", 0) + 0.5,
                "y_min": gap.get("y_start_mm", 0) - 0.5,
                "y_max": gap.get("y_end_mm", 0) + 0.5,
            })

    def _in_gap(x, y):
        for gz in gap_zones:
            if gz["x_min"] <= x <= gz["x_max"] and gz["y_min"] <= y <= gz["y_max"]:
                return True
        return False

    existing_set = [(v.get("x_mm", 0), v.get("y_mm", 0)) for v in (existing_vias or [])]

    def _near_existing(x, y, threshold=1.0):
        for ex, ey in existing_set:
            if math.sqrt((x - ex) ** 2 + (y - ey) ** 2) < threshold:
                return True
        return False

    suggested_vias = []
    skipped_gap = 0
    skipped_existing = 0
    margin = 0.5

    for row in range(n_rows):
        y = margin + row * actual_spacing_y
        if y > plane_height_mm - margin:
            y = plane_height_mm - margin
        for col in range(n_cols):
            x = margin + col * actual_spacing_x
            if x > plane_width_mm - margin:
                x = plane_width_mm - margin
            if _in_gap(x, y):
                skipped_gap += 1
                continue
            if _near_existing(x, y):
                skipped_existing += 1
                continue
            suggested_vias.append({"x_mm": round(x, 2), "y_mm": round(y, 2)})

    # Gap stitching vias
    gap_stitch_vias = []
    if plane_gaps:
        for gap in plane_gaps:
            gx_s = gap.get("x_start_mm", 0)
            gy_s = gap.get("y_start_mm", 0)
            gx_e = gap.get("x_end_mm", 0)
            gy_e = gap.get("y_end_mm", 0)
            gw = gap.get("width_mm", 1.0)
            gap_len = math.sqrt((gx_e - gx_s) ** 2 + (gy_e - gy_s) ** 2)
            if gap_len < 0.1:
                continue
            n_stitch = max(2, int(math.ceil(gap_len / spacing_mm)) + 1)
            gdx = gx_e - gx_s
            gdy = gy_e - gy_s
            glen = math.sqrt(gdx * gdx + gdy * gdy)
            gpx = -gdy / glen if glen > 0 else 0
            gpy = gdx / glen if glen > 0 else 1
            for i in range(n_stitch):
                t = i / max(n_stitch - 1, 1)
                gx = gx_s + t * gdx
                gy = gy_s + t * gdy
                offset = gw / 2.0 + 0.5
                for sign in (-1, 1):
                    vx = gx + sign * offset * gpx
                    vy = gy + sign * offset * gpy
                    if 0 <= vx <= plane_width_mm and 0 <= vy <= plane_height_mm:
                        if not _near_existing(vx, vy) and not _in_gap(vx, vy):
                            too_close = any(
                                math.sqrt((sv["x_mm"] - vx) ** 2 + (sv["y_mm"] - vy) ** 2) < min_spacing * 0.8
                                for sv in suggested_vias + gap_stitch_vias
                            )
                            if not too_close:
                                gap_stitch_vias.append({
                                    "x_mm": round(vx, 2),
                                    "y_mm": round(vy, 2),
                                    "purpose": "gap_stitching",
                                })

    all_suggested = suggested_vias + gap_stitch_vias
    total_vias = len(all_suggested) + len(existing_set)

    area_cm2 = (plane_width_mm * plane_height_mm) / 100.0
    density_per_cm2 = total_vias / max(area_cm2, 0.01)

    # Coverage analysis (quadrants)
    all_positions = existing_set + [(v["x_mm"], v["y_mm"]) for v in all_suggested]
    quadrants = [
        ("top_left", 0, 0, plane_width_mm / 2, plane_height_mm / 2),
        ("top_right", plane_width_mm / 2, 0, plane_width_mm, plane_height_mm / 2),
        ("bottom_left", 0, plane_height_mm / 2, plane_width_mm / 2, plane_height_mm),
        ("bottom_right", plane_width_mm / 2, plane_height_mm / 2, plane_width_mm, plane_height_mm),
    ]
    coverage_analysis = []
    for qn, xn, yn, xx, yx in quadrants:
        cnt = sum(1 for vx, vy in all_positions if xn <= vx <= xx and yn <= vy <= yx)
        qa = ((xx - xn) * (yx - yn)) / 100.0
        qd = cnt / max(qa, 0.01)
        coverage_analysis.append({
            "quadrant": qn, "via_count": cnt,
            "density_per_cm2": round(qd, 1),
            "adequate": qd >= density_per_cm2 * 0.5,
        })

    notes = [
        f"Wavelength in substrate: {wavelength_mm:.1f} mm at {max_frequency_mhz} MHz (er={dielectric_constant})",
        f"Required via spacing (lambda/20): {required_spacing_mm:.2f} mm",
        f"Actual grid spacing: {actual_spacing_x:.2f} x {actual_spacing_y:.2f} mm",
        f"Total suggested new vias: {len(all_suggested)} ({len(gap_stitch_vias)} for gap stitching)",
        f"Existing vias retained: {len(existing_set)}",
        f"Via density: {density_per_cm2:.1f} per cm2",
    ]
    if skipped_gap > 0:
        notes.append(f"Skipped {skipped_gap} locations inside plane gaps")
    if skipped_existing > 0:
        notes.append(f"Skipped {skipped_existing} locations near existing vias")

    recommendations = []
    if required_spacing_mm < min_spacing:
        recommendations.append(
            f"Required spacing ({required_spacing_mm:.2f} mm) below practical minimum. "
            "Consider stacked vias or via arrays."
        )
    if gap_stitch_vias:
        recommendations.append(
            f"Added {len(gap_stitch_vias)} stitching vias near plane gaps."
        )
    underserved = [q for q in coverage_analysis if not q["adequate"]]
    if underserved:
        names = ", ".join(q["quadrant"] for q in underserved)
        recommendations.append(f"Regions with low coverage: {names}.")

    return {
        "suggested_via_locations": all_suggested,
        "spacing_mm": round(spacing_mm, 2),
        "actual_spacing_x_mm": round(actual_spacing_x, 2),
        "actual_spacing_y_mm": round(actual_spacing_y, 2),
        "density_per_cm2": round(density_per_cm2, 1),
        "total_new_vias": len(all_suggested),
        "existing_vias_count": len(existing_set),
        "wavelength_mm": round(wavelength_mm, 1),
        "coverage_analysis": coverage_analysis,
        "notes": notes,
        "recommendations": recommendations,
        "parameters": {
            "plane_width_mm": plane_width_mm,
            "plane_height_mm": plane_height_mm,
            "max_frequency_mhz": max_frequency_mhz,
            "dielectric_constant": dielectric_constant,
            "existing_vias_count": len(existing_set),
            "plane_gaps_count": len(plane_gaps) if plane_gaps else 0,
        },
    }

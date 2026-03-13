"""Return path discontinuity and current density visualization.

Provides numerical models for return-current behaviour at plane splits,
via transitions, and slot crossings.  All methods accept plain numeric
inputs (frequencies in Hz, dimensions in mm) and return dataclass results
suitable for JSON serialisation.

Key physics implemented:
* Frequency-dependent skin depth in copper
* Via transition current spreading (coaxial / radial model)
* Loop area increase at each discontinuity type
* Slot crossing impedance increase estimation
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------
C0 = 299792458.0              # speed of light  (m/s)
MU0 = 4.0 * math.pi * 1e-7   # permeability of free space  (H/m)
EPS0 = 8.854e-12              # permittivity of free space  (F/m)
SIGMA_CU = 5.8e7              # conductivity of annealed copper  (S/m)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SkinDepthResult:
    """Result of a skin-depth calculation."""

    frequency_hz: float
    skin_depth_mm: float
    conductivity_s_per_m: float
    notes: list[str] = field(default_factory=list)


@dataclass
class ViaCurrentSpreadResult:
    """Result of a via current-spreading estimation."""

    via_drill_mm: float
    antipad_mm: float
    plane_thickness_mm: float
    frequency_hz: float
    spreading_radius_mm: float
    skin_depth_mm: float
    effective_area_mm2: float
    current_density_ratio: float
    notes: list[str] = field(default_factory=list)


@dataclass
class LoopAreaResult:
    """Loop area contribution from a single discontinuity."""

    discontinuity_type: str          # "plane_split", "via_transition", "slot_crossing"
    loop_area_mm2: float
    trace_length_mm: float
    height_mm: float
    detour_mm: float
    notes: list[str] = field(default_factory=list)


@dataclass
class SlotCrossingResult:
    """Impedance increase estimate for a trace crossing a slot."""

    slot_width_mm: float
    trace_width_mm: float
    plane_height_mm: float
    frequency_hz: float
    impedance_increase_ohm: float
    impedance_increase_pct: float
    reference_impedance_ohm: float
    excess_loop_area_mm2: float
    notes: list[str] = field(default_factory=list)


@dataclass
class DiscontinuitySummary:
    """Aggregated summary across multiple discontinuities."""

    total_excess_loop_area_mm2: float
    discontinuity_count: int
    worst_loop_area_mm2: float
    worst_type: str
    items: list[LoopAreaResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Visualizer / analyser class
# ---------------------------------------------------------------------------

class ReturnPathVisualizer:
    """Compute return-path discontinuity metrics for visualisation.

    All public methods are pure functions of their numeric arguments --
    no design-data object is required.  This makes unit-testing and
    integration into both MCP tool handlers and report generators
    straightforward.

    Usage::

        viz = ReturnPathVisualizer()
        sd = viz.skin_depth(frequency_hz=1e9)
        print(sd.skin_depth_mm)
    """

    # -----------------------------------------------------------------
    # Skin depth
    # -----------------------------------------------------------------

    def skin_depth(
        self,
        frequency_hz: float,
        conductivity: float = SIGMA_CU,
    ) -> SkinDepthResult:
        """Frequency-dependent skin depth in a conductor.

        Formula: delta = 1 / sqrt(pi * f * mu0 * sigma)

        Parameters
        ----------
        frequency_hz:
            Signal frequency in Hz.  Must be >= 0.
            At f=0 (DC), returns an effectively infinite depth (1e6 mm).
        conductivity:
            Conductor conductivity in S/m.  Defaults to annealed copper.

        Returns
        -------
        SkinDepthResult
        """
        notes: list[str] = []

        if frequency_hz <= 0.0:
            notes.append("DC (0 Hz): skin depth is effectively infinite.")
            return SkinDepthResult(
                frequency_hz=0.0,
                skin_depth_mm=1e6,
                conductivity_s_per_m=conductivity,
                notes=notes,
            )

        if conductivity <= 0.0:
            raise ValueError("conductivity must be positive")

        delta_m = 1.0 / math.sqrt(math.pi * frequency_hz * MU0 * conductivity)
        delta_mm = delta_m * 1e3

        if frequency_hz >= 1e9:
            notes.append(
                f"At {frequency_hz / 1e9:.1f} GHz the skin depth is very thin; "
                "surface roughness may dominate losses."
            )
        if delta_mm < 0.035:
            notes.append(
                f"Skin depth ({delta_mm:.4f} mm) is less than standard 1-oz copper "
                "(0.035 mm).  Current concentrates at the surface."
            )

        return SkinDepthResult(
            frequency_hz=frequency_hz,
            skin_depth_mm=delta_mm,
            conductivity_s_per_m=conductivity,
            notes=notes,
        )

    # -----------------------------------------------------------------
    # Via current spreading
    # -----------------------------------------------------------------

    def via_current_spreading(
        self,
        via_drill_mm: float,
        antipad_mm: float,
        plane_thickness_mm: float = 0.035,
        frequency_hz: float = 1e9,
    ) -> ViaCurrentSpreadResult:
        """Estimate how return current spreads radially from a via barrel.

        At high frequencies the current crowds at the via barrel edge and
        spreads outward on the plane within roughly one skin depth of
        the barrel wall.  The effective conduction area is the annular
        ring between the barrel outer radius and a spreading radius
        that depends on skin depth and antipad clearance.

        Parameters
        ----------
        via_drill_mm:
            Finished drill diameter (mm).
        antipad_mm:
            Antipad (clearance hole) diameter in the reference plane (mm).
        plane_thickness_mm:
            Copper thickness of the reference plane (mm).
        frequency_hz:
            Signal frequency (Hz).

        Returns
        -------
        ViaCurrentSpreadResult
        """
        notes: list[str] = []

        sd = self.skin_depth(frequency_hz)
        skin_depth_mm = sd.skin_depth_mm

        barrel_radius_mm = via_drill_mm / 2.0
        antipad_radius_mm = antipad_mm / 2.0

        # The current on the plane enters at the antipad edge and spreads
        # outward.  At high frequency the spreading radius is limited by
        # inductive effects to approximately antipad_radius + 3 * skin_depth.
        if frequency_hz > 0:
            spreading_radius_mm = antipad_radius_mm + 3.0 * skin_depth_mm
        else:
            # DC: current spreads broadly; cap at 10x antipad radius
            spreading_radius_mm = antipad_radius_mm * 10.0

        # Effective conduction area = annular ring on the plane
        inner_r = antipad_radius_mm
        outer_r = spreading_radius_mm
        if outer_r <= inner_r:
            outer_r = inner_r + 0.01  # avoid zero area

        effective_area_mm2 = math.pi * (outer_r ** 2 - inner_r ** 2)

        # Current density ratio: peak (at antipad edge) vs. uniform
        # For a radial current sheet, J(r) ~ 1/r, so peak/avg scales
        # as outer_r / inner_r  (logarithmic average).
        if inner_r > 0:
            density_ratio = outer_r / inner_r
        else:
            density_ratio = 1.0

        if density_ratio > 3.0:
            notes.append(
                f"High current crowding at via barrel (ratio {density_ratio:.1f}:1). "
                "Consider larger antipad or additional return vias."
            )

        if antipad_radius_mm - barrel_radius_mm < 0.1:
            notes.append(
                "Antipad clearance < 0.1 mm -- capacitive coupling to barrel "
                "may degrade signal integrity."
            )

        return ViaCurrentSpreadResult(
            via_drill_mm=via_drill_mm,
            antipad_mm=antipad_mm,
            plane_thickness_mm=plane_thickness_mm,
            frequency_hz=frequency_hz,
            spreading_radius_mm=round(spreading_radius_mm, 4),
            skin_depth_mm=round(skin_depth_mm, 4),
            effective_area_mm2=round(effective_area_mm2, 4),
            current_density_ratio=round(density_ratio, 2),
            notes=notes,
        )

    # -----------------------------------------------------------------
    # Loop area at discontinuities
    # -----------------------------------------------------------------

    def loop_area_plane_split(
        self,
        trace_length_mm: float,
        split_width_mm: float,
        plane_height_mm: float = 0.2,
    ) -> LoopAreaResult:
        """Loop area increase when a trace crosses a plane split.

        The return current must detour around the split.  The excess
        loop area is approximately:

            A_excess = trace_length_crossing * detour

        where *detour* is conservatively 2 x split_width (the current
        goes around each side of the gap).

        Parameters
        ----------
        trace_length_mm:
            Length of trace over the split region (mm).
        split_width_mm:
            Width of the gap in the reference plane (mm).
        plane_height_mm:
            Distance from trace to the reference plane (mm).
        """
        detour_mm = 2.0 * split_width_mm
        # The excess loop area is the detour path height times length.
        # The "height" component is the gap width (the current must
        # traverse the gap width vertically in the plane).
        excess_area = trace_length_mm * detour_mm

        notes: list[str] = []
        if split_width_mm > 5.0:
            notes.append(
                f"Split width {split_width_mm:.1f} mm is large -- consider "
                "stitching capacitors or rerouting."
            )

        return LoopAreaResult(
            discontinuity_type="plane_split",
            loop_area_mm2=round(excess_area, 4),
            trace_length_mm=trace_length_mm,
            height_mm=plane_height_mm,
            detour_mm=detour_mm,
            notes=notes,
        )

    def loop_area_via_transition(
        self,
        plane_spacing_mm: float,
        return_via_distance_mm: float,
    ) -> LoopAreaResult:
        """Loop area from a signal via with its nearest return via.

        The excess loop area is approximated by the rectangle between
        the signal via and the closest ground / return via, with height
        equal to the inter-plane spacing.

        Parameters
        ----------
        plane_spacing_mm:
            Distance between the two reference planes the via crosses (mm).
        return_via_distance_mm:
            Lateral distance to the nearest return (ground) via (mm).
        """
        excess_area = plane_spacing_mm * return_via_distance_mm

        notes: list[str] = []
        if return_via_distance_mm > 2.0:
            notes.append(
                f"Return via is {return_via_distance_mm:.1f} mm away -- place "
                "a ground via within 1-2 mm of each signal via."
            )

        return LoopAreaResult(
            discontinuity_type="via_transition",
            loop_area_mm2=round(excess_area, 4),
            trace_length_mm=0.0,
            height_mm=plane_spacing_mm,
            detour_mm=return_via_distance_mm,
            notes=notes,
        )

    def loop_area_slot_crossing(
        self,
        trace_length_mm: float,
        slot_width_mm: float,
        plane_height_mm: float = 0.2,
    ) -> LoopAreaResult:
        """Loop area increase for a trace crossing a narrow slot.

        A slot in the reference plane forces the return current to
        detour around the slot ends.  The model is similar to a plane
        split but scaled by the ratio of slot width to plane height.

        Parameters
        ----------
        trace_length_mm:
            Length of trace traversing the slot (mm).
        slot_width_mm:
            Width of the slot (mm).
        plane_height_mm:
            Trace-to-plane height (mm).
        """
        # Detour is approximately the slot width (current goes around
        # the nearest slot end).
        detour_mm = slot_width_mm
        excess_area = trace_length_mm * detour_mm

        notes: list[str] = []
        if slot_width_mm > 2.0 * plane_height_mm:
            notes.append(
                "Slot width exceeds 2x the trace height -- treat as a plane split."
            )

        return LoopAreaResult(
            discontinuity_type="slot_crossing",
            loop_area_mm2=round(excess_area, 4),
            trace_length_mm=trace_length_mm,
            height_mm=plane_height_mm,
            detour_mm=detour_mm,
            notes=notes,
        )

    # -----------------------------------------------------------------
    # Slot crossing impedance
    # -----------------------------------------------------------------

    def slot_crossing_impedance(
        self,
        slot_width_mm: float,
        trace_width_mm: float,
        plane_height_mm: float = 0.2,
        frequency_hz: float = 1e9,
        dielectric_constant: float = 4.3,
        reference_z0_ohm: float = 50.0,
    ) -> SlotCrossingResult:
        """Estimate the impedance increase caused by a slot crossing.

        When a trace crosses a slot in its reference plane, the return
        current must detour, increasing the effective loop inductance.
        The excess inductance is modelled as:

            L_excess ~ (MU0 / pi) * slot_width * ln(slot_width / trace_width)

        and converted to an impedance increase at the given frequency:

            delta_Z = 2 * pi * f * L_excess

        Parameters
        ----------
        slot_width_mm:
            Width of the slot in the reference plane (mm).
        trace_width_mm:
            Width of the signal trace (mm).
        plane_height_mm:
            Height from trace to reference plane (mm).
        frequency_hz:
            Signal frequency (Hz).
        dielectric_constant:
            Substrate relative permittivity.
        reference_z0_ohm:
            Nominal characteristic impedance of the trace (ohm).

        Returns
        -------
        SlotCrossingResult
        """
        notes: list[str] = []

        slot_width_m = slot_width_mm * 1e-3
        trace_width_m = trace_width_mm * 1e-3

        # Guard against log(0) or negative
        if trace_width_m <= 0:
            trace_width_m = 1e-6
        ratio = slot_width_m / trace_width_m
        if ratio < 1.0:
            ratio = 1.0  # slot narrower than trace -- minimal effect

        # Excess inductance (H)
        l_excess_h = (MU0 / math.pi) * slot_width_m * math.log(ratio)

        # Impedance increase
        if frequency_hz > 0:
            omega = 2.0 * math.pi * frequency_hz
            delta_z = omega * l_excess_h
        else:
            delta_z = 0.0

        # Percentage
        if reference_z0_ohm > 0:
            pct = (delta_z / reference_z0_ohm) * 100.0
        else:
            pct = 0.0

        # Excess loop area
        excess_loop = slot_width_mm * trace_width_mm

        if pct > 20.0:
            notes.append(
                f"Impedance increase ({pct:.1f}%) exceeds 20% -- likely to "
                "cause significant reflections.  Route around the slot."
            )
        elif pct > 5.0:
            notes.append(
                f"Impedance increase ({pct:.1f}%) may cause marginal reflections."
            )

        return SlotCrossingResult(
            slot_width_mm=slot_width_mm,
            trace_width_mm=trace_width_mm,
            plane_height_mm=plane_height_mm,
            frequency_hz=frequency_hz,
            impedance_increase_ohm=round(delta_z, 4),
            impedance_increase_pct=round(pct, 2),
            reference_impedance_ohm=reference_z0_ohm,
            excess_loop_area_mm2=round(excess_loop, 4),
            notes=notes,
        )

    # -----------------------------------------------------------------
    # Aggregate helper
    # -----------------------------------------------------------------

    def summarize_discontinuities(
        self,
        items: list[LoopAreaResult],
    ) -> DiscontinuitySummary:
        """Aggregate a list of loop-area results into a summary.

        Parameters
        ----------
        items:
            Individual discontinuity results from the ``loop_area_*``
            methods.

        Returns
        -------
        DiscontinuitySummary
        """
        if not items:
            return DiscontinuitySummary(
                total_excess_loop_area_mm2=0.0,
                discontinuity_count=0,
                worst_loop_area_mm2=0.0,
                worst_type="none",
                items=[],
                notes=["No discontinuities provided."],
            )

        total = sum(i.loop_area_mm2 for i in items)
        worst = max(items, key=lambda i: i.loop_area_mm2)

        notes: list[str] = []
        if total > 100.0:
            notes.append(
                f"Total excess loop area ({total:.1f} mm^2) exceeds 1 cm^2 -- "
                "significant EMI risk."
            )
        if len(items) > 5:
            notes.append(
                f"{len(items)} discontinuities detected -- consider "
                "consolidating return paths."
            )

        return DiscontinuitySummary(
            total_excess_loop_area_mm2=round(total, 4),
            discontinuity_count=len(items),
            worst_loop_area_mm2=round(worst.loop_area_mm2, 4),
            worst_type=worst.discontinuity_type,
            items=items,
            notes=notes,
        )

    # -----------------------------------------------------------------
    # Current density profile (for visualisation data)
    # -----------------------------------------------------------------

    def current_density_profile(
        self,
        trace_height_mm: float,
        analysis_width_mm: float = 20.0,
        num_points: int = 50,
    ) -> dict:
        """Return-current density distribution on the reference plane.

        Uses the classical J(x) = (1/pi) * h / (h^2 + x^2) model.

        Parameters
        ----------
        trace_height_mm:
            Height from trace to reference plane (mm).
        analysis_width_mm:
            Total lateral width to sample (mm), centred on the trace.
        num_points:
            Number of sample points.

        Returns
        -------
        dict with keys ``x_mm``, ``density_normalised``, ``peak_density``,
        ``within_3h_pct``, ``within_5h_pct``.
        """
        half = analysis_width_mm / 2.0
        step = analysis_width_mm / max(num_points - 1, 1)
        h = max(trace_height_mm, 1e-6)

        xs: list[float] = []
        densities: list[float] = []
        for i in range(num_points):
            x = -half + i * step
            j = (1.0 / math.pi) * h / (h ** 2 + x ** 2)
            xs.append(round(x, 4))
            densities.append(round(j, 6))

        peak = (1.0 / math.pi) * (1.0 / h)
        within_3h = (2.0 / math.pi) * math.atan(3.0)
        within_5h = (2.0 / math.pi) * math.atan(5.0)

        return {
            "x_mm": xs,
            "density_normalised": densities,
            "peak_density_per_mm": round(peak, 6),
            "within_3h_pct": round(within_3h * 100.0, 2),
            "within_5h_pct": round(within_5h * 100.0, 2),
            "trace_height_mm": trace_height_mm,
        }

"""Near-field probe and current loop EMI modeling.

Models near-field electromagnetic emissions from PCB sources using
magnetic dipole (small loop) and electric dipole (short trace) models.

Physics
-------
- Magnetic dipole H-field (reactive near-field, r << lambda):
    H = (I * A) / (4 * pi * r^3)  [A/m]

- Magnetic dipole H-field (radiating near-field / far-field transition):
    H = (I * A * omega^2) / (4 * pi * c^2 * r)  [A/m]

- Electric dipole E-field (near-field, r << lambda):
    E = (V * l * omega) / (4 * pi * c * r^2)  [V/m]

- Near-field to far-field transition distance:
    r_transition = lambda / (2 * pi)

Reference: Paul, C.R. "Introduction to Electromagnetic Compatibility", Ch. 9.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# Speed of light (m/s)
_C = 299_792_458.0


# ---------------------------------------------------------------------------
# Source classification
# ---------------------------------------------------------------------------

# Sources dominated by magnetic field (low impedance, current-driven)
MAGNETIC_SOURCE_TYPES = frozenset({
    "current_loop",
    "smps_inductor",
    "motor_driver",
    "power_trace",
    "transformer",
})

# Sources dominated by electric field (high impedance, voltage-driven)
ELECTRIC_SOURCE_TYPES = frozenset({
    "clock_trace",
    "high_impedance_trace",
    "crystal_oscillator",
    "reset_line",
    "unshielded_cable",
})


def classify_source(source_type: str) -> str:
    """Classify a PCB source as 'magnetic' or 'electric'.

    Returns 'magnetic', 'electric', or 'unknown'.
    """
    st = source_type.lower().replace("-", "_").replace(" ", "_")
    if st in MAGNETIC_SOURCE_TYPES:
        return "magnetic"
    if st in ELECTRIC_SOURCE_TYPES:
        return "electric"
    return "unknown"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class NearFieldSource:
    """A single near-field EMI source on the PCB."""
    name: str
    source_type: str  # e.g. "current_loop", "clock_trace"
    frequency_mhz: float
    # Magnetic sources
    current_a: float = 0.0
    area_mm2: float = 0.0
    # Electric sources
    voltage_v: float = 0.0
    length_mm: float = 0.0

    @property
    def field_type(self) -> str:
        return classify_source(self.source_type)


@dataclass
class FieldPoint:
    """Field strength at a specific distance."""
    distance_m: float
    h_field_a_per_m: float = 0.0
    e_field_v_per_m: float = 0.0
    h_field_dba_per_m: float = 0.0
    e_field_dbuv_per_m: float = 0.0
    region: str = "reactive_near_field"  # or "radiating_near_field", "far_field"


@dataclass
class SourceResult:
    """Analysis result for a single source."""
    name: str
    source_type: str
    field_type: str  # "magnetic" or "electric"
    frequency_mhz: float
    wavelength_m: float
    transition_distance_m: float
    field_points: list[FieldPoint] = field(default_factory=list)


@dataclass
class NearFieldAnalysis:
    """Complete near-field analysis result."""
    sources: list[SourceResult] = field(default_factory=list)
    summary: str = ""
    dominant_source: str = ""
    max_h_field_dba_per_m: float = 0.0
    max_e_field_dbuv_per_m: float = 0.0
    recommendations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core calculation functions
# ---------------------------------------------------------------------------

def wavelength(frequency_mhz: float) -> float:
    """Return wavelength in meters for given frequency in MHz."""
    if frequency_mhz <= 0:
        return float("inf")
    return _C / (frequency_mhz * 1e6)


def transition_distance(frequency_mhz: float) -> float:
    """Near-field to far-field transition distance (meters).

    r_transition = lambda / (2 * pi)
    """
    lam = wavelength(frequency_mhz)
    if lam == float("inf"):
        return float("inf")
    return lam / (2 * math.pi)


def h_field_magnetic_dipole(
    current_a: float,
    area_m2: float,
    frequency_mhz: float,
    distance_m: float,
) -> float:
    """H-field from a small current loop (magnetic dipole).

    Uses reactive near-field formula for r << lambda/(2*pi),
    far-field formula for r >> lambda/(2*pi), and blends in between.

    Returns H in A/m.
    """
    if current_a == 0 or area_m2 == 0 or distance_m <= 0 or frequency_mhz <= 0:
        return 0.0

    r_trans = transition_distance(frequency_mhz)
    omega = 2 * math.pi * frequency_mhz * 1e6
    moment = current_a * area_m2  # magnetic dipole moment (A*m^2)

    # Reactive near-field: H = I*A / (4*pi*r^3)
    h_near = moment / (4 * math.pi * distance_m ** 3)

    # Far-field: H = I*A*omega^2 / (4*pi*c^2*r)
    h_far = moment * omega ** 2 / (4 * math.pi * _C ** 2 * distance_m)

    # Use the dominant term (whichever is larger, which naturally gives
    # the correct asymptotic behaviour in each region)
    return max(h_near, h_far)


def e_field_electric_dipole(
    voltage_v: float,
    length_m: float,
    frequency_mhz: float,
    distance_m: float,
) -> float:
    """E-field from a short electric dipole (voltage-driven trace).

    Near-field (r << lambda/(2*pi)):
        E = V * l * omega / (4 * pi * c * r^2)

    Returns E in V/m.
    """
    if voltage_v == 0 or length_m == 0 or distance_m <= 0 or frequency_mhz <= 0:
        return 0.0

    omega = 2 * math.pi * frequency_mhz * 1e6

    # Near-field formula
    e_near = abs(voltage_v) * length_m * omega / (4 * math.pi * _C * distance_m ** 2)

    # Far-field: E = V * l * omega^2 / (4 * pi * c^2 * r)  (for completeness)
    e_far = abs(voltage_v) * length_m * omega ** 2 / (4 * math.pi * _C ** 2 * distance_m)

    return max(e_near, e_far)


def to_db_h(h_a_per_m: float) -> float:
    """Convert H-field in A/m to dBA/m."""
    if h_a_per_m <= 0:
        return -999.0
    return 20 * math.log10(h_a_per_m)


def to_db_e(e_v_per_m: float) -> float:
    """Convert E-field in V/m to dBuV/m."""
    if e_v_per_m <= 0:
        return -999.0
    return 20 * math.log10(e_v_per_m * 1e6)  # V/m → uV/m → dBuV/m


def determine_region(distance_m: float, frequency_mhz: float) -> str:
    """Classify the observation distance into field regions."""
    r_trans = transition_distance(frequency_mhz)
    if r_trans == float("inf"):
        return "reactive_near_field"
    if distance_m < r_trans * 0.5:
        return "reactive_near_field"
    elif distance_m < r_trans * 2.0:
        return "radiating_near_field"
    else:
        return "far_field"


# ---------------------------------------------------------------------------
# Analyzer class
# ---------------------------------------------------------------------------

class NearFieldAnalyzer:
    """Analyze near-field emissions from PCB sources."""

    # Standard evaluation distances (meters)
    DEFAULT_DISTANCES_M = [0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0]

    # Common near-field probe sensitivity thresholds (dBA/m)
    PROBE_SENSITIVITIES = {
        "Langer RF-B 3-2": -20.0,   # H-field probe, ~1mm resolution
        "Langer RF-R 50-1": -10.0,  # H-field probe, ~5mm resolution
        "Beehive 100C": -5.0,       # General purpose H-field
        "Typical H-probe": 0.0,     # Generic reference
    }

    def __init__(self, distances_m: Optional[list[float]] = None):
        self.distances_m = distances_m or self.DEFAULT_DISTANCES_M

    def _make_source(self, spec: dict) -> NearFieldSource:
        """Create NearFieldSource from a dict specification."""
        return NearFieldSource(
            name=spec.get("name", spec.get("source_type", "unknown")),
            source_type=spec.get("type", spec.get("source_type", "unknown")),
            frequency_mhz=spec.get("frequency_mhz", 0.0),
            current_a=spec.get("current_a", 0.0),
            area_mm2=spec.get("area_mm2", 0.0),
            voltage_v=spec.get("voltage_v", 0.0),
            length_mm=spec.get("length_mm", 0.0),
        )

    def analyze_source(self, source: NearFieldSource) -> SourceResult:
        """Analyze a single near-field source at all evaluation distances."""
        lam = wavelength(source.frequency_mhz)
        r_trans = transition_distance(source.frequency_mhz)

        result = SourceResult(
            name=source.name,
            source_type=source.source_type,
            field_type=source.field_type,
            frequency_mhz=source.frequency_mhz,
            wavelength_m=lam,
            transition_distance_m=r_trans,
        )

        area_m2 = source.area_mm2 * 1e-6  # mm^2 -> m^2
        length_m = source.length_mm * 1e-3  # mm -> m

        for d in self.distances_m:
            h = h_field_magnetic_dipole(source.current_a, area_m2, source.frequency_mhz, d)
            e = e_field_electric_dipole(source.voltage_v, length_m, source.frequency_mhz, d)
            region = determine_region(d, source.frequency_mhz)

            fp = FieldPoint(
                distance_m=d,
                h_field_a_per_m=h,
                e_field_v_per_m=e,
                h_field_dba_per_m=to_db_h(h),
                e_field_dbuv_per_m=to_db_e(e),
                region=region,
            )
            result.field_points.append(fp)

        return result

    def analyze_sources(self, sources: list[dict]) -> NearFieldAnalysis:
        """Analyze multiple near-field sources.

        Parameters
        ----------
        sources : list of dicts
            Each dict has: type, frequency_mhz, and either
            {current_a, area_mm2} for magnetic sources or
            {voltage_v, length_mm} for electric sources.
            Optional: name.

        Returns
        -------
        NearFieldAnalysis with field strengths at standard distances.
        """
        analysis = NearFieldAnalysis()

        for spec in sources:
            src = self._make_source(spec)
            result = self.analyze_source(src)
            analysis.sources.append(result)

        # Find overall maximums
        max_h = -999.0
        max_e = -999.0
        dominant = ""

        for sr in analysis.sources:
            for fp in sr.field_points:
                if fp.h_field_dba_per_m > max_h:
                    max_h = fp.h_field_dba_per_m
                    dominant = sr.name
                if fp.e_field_dbuv_per_m > max_e:
                    max_e = fp.e_field_dbuv_per_m

        analysis.max_h_field_dba_per_m = round(max_h, 1)
        analysis.max_e_field_dbuv_per_m = round(max_e, 1)
        analysis.dominant_source = dominant

        # Generate recommendations
        analysis.recommendations = self._generate_recommendations(analysis)

        # Summary
        n_mag = sum(1 for s in analysis.sources if s.field_type == "magnetic")
        n_elec = sum(1 for s in analysis.sources if s.field_type == "electric")
        analysis.summary = (
            f"Analyzed {len(analysis.sources)} source(s) "
            f"({n_mag} magnetic, {n_elec} electric). "
            f"Dominant source: {dominant}."
        )

        return analysis

    def _generate_recommendations(self, analysis: NearFieldAnalysis) -> list[str]:
        """Generate EMI mitigation recommendations based on analysis."""
        recs: list[str] = []
        for sr in analysis.sources:
            # Check at 10mm distance (common probe distance)
            fp_10mm = None
            for fp in sr.field_points:
                if abs(fp.distance_m - 0.01) < 0.001:
                    fp_10mm = fp
                    break

            if fp_10mm is None:
                continue

            if sr.field_type == "magnetic" and fp_10mm.h_field_dba_per_m > 0:
                recs.append(
                    f"{sr.name}: High magnetic field ({fp_10mm.h_field_dba_per_m:.0f} dBA/m at 10mm). "
                    f"Reduce loop area or add shielding."
                )
            if sr.field_type == "electric" and fp_10mm.e_field_dbuv_per_m > 120:
                recs.append(
                    f"{sr.name}: High electric field ({fp_10mm.e_field_dbuv_per_m:.0f} dBuV/m at 10mm). "
                    f"Add series resistance, reduce trace length, or shield."
                )

        return recs

    def to_dict(self, analysis: NearFieldAnalysis) -> dict:
        """Convert analysis to dict for MCP tool output."""
        return {
            "summary": analysis.summary,
            "dominant_source": analysis.dominant_source,
            "max_h_field_dba_per_m": analysis.max_h_field_dba_per_m,
            "max_e_field_dbuv_per_m": analysis.max_e_field_dbuv_per_m,
            "source_count": len(analysis.sources),
            "sources": [
                {
                    "name": sr.name,
                    "source_type": sr.source_type,
                    "field_type": sr.field_type,
                    "frequency_mhz": sr.frequency_mhz,
                    "wavelength_m": round(sr.wavelength_m, 3) if sr.wavelength_m != float("inf") else None,
                    "transition_distance_m": round(sr.transition_distance_m, 4) if sr.transition_distance_m != float("inf") else None,
                    "field_points": [
                        {
                            "distance_m": fp.distance_m,
                            "h_field_a_per_m": _fmt(fp.h_field_a_per_m),
                            "e_field_v_per_m": _fmt(fp.e_field_v_per_m),
                            "h_field_dba_per_m": round(fp.h_field_dba_per_m, 1),
                            "e_field_dbuv_per_m": round(fp.e_field_dbuv_per_m, 1),
                            "region": fp.region,
                        }
                        for fp in sr.field_points
                    ],
                }
                for sr in analysis.sources
            ],
            "recommendations": analysis.recommendations,
        }


def _fmt(v: float) -> float:
    """Format a float to reasonable precision."""
    if v == 0:
        return 0.0
    if abs(v) < 1e-12:
        return float(f"{v:.4e}")
    return float(f"{v:.6g}")

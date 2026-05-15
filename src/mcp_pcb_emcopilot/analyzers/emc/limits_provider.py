"""Centralised regulatory-limit lookup.

A single ``get_limit(standard, class_or_level, frequency_mhz, detector)``
function backs every analyzer + report that needs a CISPR / FCC / ISO /
IEC limit value. It returns a :class:`LimitPoint` whose ``source`` field
records whether the value came from:

- ``"local_fallback"`` — the in-process tables copied here from the
  per-analyzer dicts. Stable, vendor-neutral, always available.
- ``"live_regs"`` — a value pushed in at runtime by the regulations
  bridge after Claude executed an ``mcp__emc-regulations__*`` lookup.

Analyzers stay backwards-compatible: the legacy ``CISPR25_RADIATED_LIMITS``
/ ``FCC_PART15_CONDUCTED_LIMITS`` / ``_FCC_CLASS_B_LIMITS`` constants in
the original files keep working — they are now thin wrappers that read
the same data through this provider.

This module is intentionally thread-unsafe (single-process MCP server).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# =============================================================================
# Data shape
# =============================================================================


@dataclass
class LimitPoint:
    """Result of a single limit lookup."""

    standard: str
    class_or_level: str
    frequency_mhz: float
    detector: str
    limit_value: float        # in the standard's native unit
    limit_unit: str           # e.g. "dBuV/m", "dBuV", "V/m", "mA"
    band_min_mhz: float
    band_max_mhz: float
    source: str               # "local_fallback" | "live_regs"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "standard": self.standard,
            "class_or_level": self.class_or_level,
            "frequency_mhz": self.frequency_mhz,
            "detector": self.detector,
            "limit_value": self.limit_value,
            "limit_unit": self.limit_unit,
            "band": [self.band_min_mhz, self.band_max_mhz],
            "source": self.source,
            "notes": self.notes,
        }


# =============================================================================
# Local fallback tables (verbatim copies of what the per-analyzer files use).
# These remain the canonical source of truth in the absence of a live
# emc-regulations lookup; the per-analyzer constants now read from here.
# =============================================================================

# CISPR 25 radiated, dBuV/m @ 1 m (ALSE, peak detector). Index: class 1..5.
_CISPR25_RADIATED: list[dict] = [
    {"f_min": 0.15, "f_max": 0.3,    "lim": {1: 52, 2: 42, 3: 32, 4: 22, 5: 12}},
    {"f_min": 0.53, "f_max": 2.0,    "lim": {1: 46, 2: 36, 3: 26, 4: 16, 5: 6}},
    {"f_min": 5.9,  "f_max": 6.2,    "lim": {1: 40, 2: 30, 3: 20, 4: 10, 5: 0}},
    {"f_min": 30,   "f_max": 54,     "lim": {1: 44, 2: 34, 3: 24, 4: 14, 5: 4}},
    {"f_min": 70,   "f_max": 108,    "lim": {1: 38, 2: 28, 3: 18, 4: 8,  5: -2}},
    {"f_min": 144,  "f_max": 172,    "lim": {1: 32, 2: 22, 3: 12, 4: 2,  5: -8}},
    {"f_min": 420,  "f_max": 512,    "lim": {1: 32, 2: 22, 3: 12, 4: 2,  5: -8}},
    {"f_min": 820,  "f_max": 960,    "lim": {1: 32, 2: 22, 3: 12, 4: 2,  5: -8}},
    {"f_min": 1400, "f_max": 2500,   "lim": {1: 36, 2: 26, 3: 16, 4: 6,  5: -4}},
]

# CISPR 25 conducted, dBuV (voltage on power leads). class -> {peak, avg}.
_CISPR25_CONDUCTED: list[dict] = [
    {"f_min": 0.15, "f_max": 0.3,  "lim": {
        1: {"peak": 90, "avg": 80}, 2: {"peak": 80, "avg": 70},
        3: {"peak": 70, "avg": 60}, 4: {"peak": 60, "avg": 50},
        5: {"peak": 50, "avg": 40},
    }},
    {"f_min": 0.53, "f_max": 1.8,  "lim": {
        1: {"peak": 80, "avg": 70}, 2: {"peak": 70, "avg": 60},
        3: {"peak": 60, "avg": 50}, 4: {"peak": 50, "avg": 40},
        5: {"peak": 40, "avg": 30},
    }},
    {"f_min": 5.9,  "f_max": 6.2,  "lim": {
        1: {"peak": 70, "avg": 60}, 2: {"peak": 60, "avg": 50},
        3: {"peak": 50, "avg": 40}, 4: {"peak": 40, "avg": 30},
        5: {"peak": 30, "avg": 20},
    }},
    {"f_min": 30,   "f_max": 108,  "lim": {
        1: {"peak": 60, "avg": 50}, 2: {"peak": 50, "avg": 40},
        3: {"peak": 40, "avg": 30}, 4: {"peak": 30, "avg": 20},
        5: {"peak": 20, "avg": 10},
    }},
]

# FCC Part 15 radiated emission limits @ 3 m, dBuV/m. Single-class lookup
# returns the relevant limit for that class (A or B).
_FCC_PART_15_RADIATED: dict[str, list[tuple[float, float, float]]] = {
    "A": [
        (30, 88,    49.5),
        (88, 216,   54.0),
        (216, 960,  56.9),
        (960, 40000, 60.0),
    ],
    "B": [
        (30, 88,    40.0),
        (88, 216,   43.5),
        (216, 960,  46.0),
        (960, 40000, 54.0),
    ],
}

# FCC Part 15 conducted, dBuV (on power leads). class -> bands.
_FCC_PART_15_CONDUCTED: dict[str, list[dict]] = {
    "A": [
        {"f_min": 0.15, "f_max": 0.5,  "qp": 79, "avg": 66},
        {"f_min": 0.5,  "f_max": 30.0, "qp": 73, "avg": 60},
    ],
    "B": [
        {"f_min": 0.15, "f_max": 0.5,  "qp": 66, "avg": 56},
        {"f_min": 0.5,  "f_max": 5.0,  "qp": 56, "avg": 46},
        {"f_min": 5.0,  "f_max": 30.0, "qp": 60, "avg": 50},
    ],
}

# CISPR 32 radiated @ 3 m, dBuV/m. (Class A / B, generic IT/multimedia.)
_CISPR_32_RADIATED: dict[str, list[tuple[float, float, float]]] = {
    "A": [
        (30, 230,   50.0),
        (230, 1000, 57.0),
        (1000, 6000, 60.0),
    ],
    "B": [
        (30, 230,   40.0),
        (230, 1000, 47.0),
        (1000, 6000, 54.0),
    ],
}

# ISO 11452-2 field-strength immunity levels (V/m).
_ISO_11452_FIELD: dict[int, float] = {1: 1, 2: 3, 3: 10, 4: 30, 5: 60}

# ISO 11452-4 BCI bulk-current levels (mA).
_ISO_11452_BCI: dict[int, float] = {1: 1, 2: 3, 3: 10, 4: 30, 5: 100}

# IEC 60601-1-2 immunity test levels (representative envelope per edition).
_IEC_60601_IMMUNITY: dict[str, dict[str, float]] = {
    "4.0": {"esd_contact_kv": 6, "esd_air_kv": 8, "rf_vm": 3, "burst_kv": 1, "surge_kv": 1},
    "4.1": {"esd_contact_kv": 8, "esd_air_kv": 15, "rf_vm": 10, "burst_kv": 2, "surge_kv": 2},
}


# =============================================================================
# Runtime cache populated by the regulations bridge
# =============================================================================

# Keyed by (standard, class_or_level, freq_mhz_bucket, detector). Values are
# pre-built ``LimitPoint`` objects with ``source="live_regs"``. The cache is
# read first by :func:`get_limit`; on miss we fall through to the local table.
_LIVE_CACHE: dict[tuple, LimitPoint] = {}


def _cache_key(standard: str, class_or_level: str, freq_mhz: float, detector: str) -> tuple:
    return (
        standard.upper(),
        str(class_or_level).upper(),
        round(float(freq_mhz), 4),
        detector.upper(),
    )


def cache_live_result(point: LimitPoint) -> None:
    """Record a live emc-regulations result into the runtime cache.

    Called by ``integrations.regulations_bridge.apply_limit_result`` after
    Claude feeds back the sibling-MCP response via
    ``pcb_attach_external_result``.
    """
    key = _cache_key(point.standard, point.class_or_level, point.frequency_mhz, point.detector)
    _LIVE_CACHE[key] = LimitPoint(
        standard=point.standard.upper(),
        class_or_level=str(point.class_or_level).upper(),
        frequency_mhz=point.frequency_mhz,
        detector=point.detector.upper(),
        limit_value=point.limit_value,
        limit_unit=point.limit_unit,
        band_min_mhz=point.band_min_mhz,
        band_max_mhz=point.band_max_mhz,
        source="live_regs",
        notes=point.notes,
    )


def clear_live_cache() -> None:
    """Reset the runtime cache. Test helper."""
    _LIVE_CACHE.clear()


def has_live_value(standard: str, class_or_level: str, freq_mhz: float, detector: str = "QP") -> bool:
    """True if a live regs cache entry exists for this exact lookup."""
    return _cache_key(standard, class_or_level, freq_mhz, detector) in _LIVE_CACHE


# =============================================================================
# Public lookup
# =============================================================================


def _lookup_fallback(
    standard: str,
    class_or_level: str,
    freq_mhz: float,
    detector: str,
) -> LimitPoint | None:
    """Resolve a limit from the local fallback tables.

    Returns ``None`` when the (standard, class, freq) tuple is outside the
    coverage of every table — the caller can then surface that gap.
    """
    std = standard.upper()
    klass = str(class_or_level).upper()
    det = detector.upper()

    if std in {"CISPR_25", "CISPR25", "CISPR_25_RADIATED", "CISPR_25_CONDUCTED"}:
        try:
            kint = int(klass)
        except ValueError:
            return None
        # Disambiguate radiated vs conducted when the bands overlap. The AVG
        # detector is only defined for conducted in CISPR-25, so it pins the
        # category. An explicit ``CISPR_25_CONDUCTED`` standard also pins it.
        # Default is radiated, which preserves existing call-site behaviour.
        prefer_conducted = (std == "CISPR_25_CONDUCTED") or (det == "AVG")
        if not prefer_conducted:
            for band in _CISPR25_RADIATED:
                if band["f_min"] <= freq_mhz <= band["f_max"] and kint in band["lim"]:
                    return LimitPoint(
                        standard="CISPR_25",
                        class_or_level=klass,
                        frequency_mhz=freq_mhz,
                        detector=det,
                        limit_value=float(band["lim"][kint]),
                        limit_unit="dBuV/m",
                        band_min_mhz=float(band["f_min"]),
                        band_max_mhz=float(band["f_max"]),
                        source="local_fallback",
                        notes="CISPR 25 radiated, ALSE, 1 m",
                    )
        for band in _CISPR25_CONDUCTED:
            if band["f_min"] <= freq_mhz <= band["f_max"] and kint in band["lim"]:
                sub = band["lim"][kint]
                value = sub.get("avg" if det == "AVG" else "peak")
                return LimitPoint(
                    standard="CISPR_25",
                    class_or_level=klass,
                    frequency_mhz=freq_mhz,
                    detector=det,
                    limit_value=float(value),
                    limit_unit="dBuV",
                    band_min_mhz=float(band["f_min"]),
                    band_max_mhz=float(band["f_max"]),
                    source="local_fallback",
                    notes="CISPR 25 conducted (voltage method)",
                )
        # Conducted-preferred path didn't match — fall back to radiated.
        if prefer_conducted:
            for band in _CISPR25_RADIATED:
                if band["f_min"] <= freq_mhz <= band["f_max"] and kint in band["lim"]:
                    return LimitPoint(
                        standard="CISPR_25",
                        class_or_level=klass,
                        frequency_mhz=freq_mhz,
                        detector=det,
                        limit_value=float(band["lim"][kint]),
                        limit_unit="dBuV/m",
                        band_min_mhz=float(band["f_min"]),
                        band_max_mhz=float(band["f_max"]),
                        source="local_fallback",
                        notes="CISPR 25 radiated, ALSE, 1 m",
                    )
        return None

    if std in {"FCC_PART_15_B", "FCC_PART_15_A", "FCC_15B", "FCC_15A"}:
        klass_letter = "B" if "B" in std or klass == "B" else "A"
        # Pick conducted vs radiated by frequency (<30 MHz conducted, >=30 MHz radiated).
        if freq_mhz < 30:
            for band in _FCC_PART_15_CONDUCTED[klass_letter]:
                if band["f_min"] <= freq_mhz <= band["f_max"]:
                    val = band["avg" if det == "AVG" else "qp"]
                    return LimitPoint(
                        standard=f"FCC_PART_15_{klass_letter}",
                        class_or_level=klass_letter,
                        frequency_mhz=freq_mhz,
                        detector=det,
                        limit_value=float(val),
                        limit_unit="dBuV",
                        band_min_mhz=float(band["f_min"]),
                        band_max_mhz=float(band["f_max"]),
                        source="local_fallback",
                        notes="FCC Part 15 conducted",
                    )
        for f_lo, f_hi, lim in _FCC_PART_15_RADIATED[klass_letter]:
            if f_lo <= freq_mhz <= f_hi:
                return LimitPoint(
                    standard=f"FCC_PART_15_{klass_letter}",
                    class_or_level=klass_letter,
                    frequency_mhz=freq_mhz,
                    detector=det,
                    limit_value=float(lim),
                    limit_unit="dBuV/m",
                    band_min_mhz=float(f_lo),
                    band_max_mhz=float(f_hi),
                    source="local_fallback",
                    notes="FCC Part 15 radiated @ 3 m",
                )
        return None

    if std in {"CISPR_32", "EN_55032"}:
        klass_letter = klass if klass in {"A", "B"} else "B"
        for f_lo, f_hi, lim in _CISPR_32_RADIATED[klass_letter]:
            if f_lo <= freq_mhz <= f_hi:
                return LimitPoint(
                    standard="CISPR_32",
                    class_or_level=klass_letter,
                    frequency_mhz=freq_mhz,
                    detector=det,
                    limit_value=float(lim),
                    limit_unit="dBuV/m",
                    band_min_mhz=float(f_lo),
                    band_max_mhz=float(f_hi),
                    source="local_fallback",
                    notes="CISPR 32 radiated @ 3 m",
                )
        return None

    if std.startswith("ISO_11452"):
        try:
            level = int(klass)
        except ValueError:
            return None
        if std.endswith("_4"):
            val = _ISO_11452_BCI.get(level)
            unit = "mA"
            notes = "ISO 11452-4 BCI bulk-current injection level"
        else:
            val = _ISO_11452_FIELD.get(level)
            unit = "V/m"
            notes = "ISO 11452-2 field strength immunity"
        if val is None:
            return None
        return LimitPoint(
            standard=std,
            class_or_level=klass,
            frequency_mhz=freq_mhz,
            detector=det,
            limit_value=float(val),
            limit_unit=unit,
            band_min_mhz=0.0,
            band_max_mhz=2500.0,
            source="local_fallback",
            notes=notes,
        )

    if std.startswith("IEC_60601"):
        edition = "4.1" if "4_1" in std or klass.upper() == "4.1" else "4.0"
        levels = _IEC_60601_IMMUNITY.get(edition, {})
        rf_vm = levels.get("rf_vm", 3.0)
        return LimitPoint(
            standard=f"IEC_60601_1_2_ED_{edition.replace('.', '_')}",
            class_or_level=klass,
            frequency_mhz=freq_mhz,
            detector=det,
            limit_value=float(rf_vm),
            limit_unit="V/m",
            band_min_mhz=80.0,
            band_max_mhz=2700.0,
            source="local_fallback",
            notes=f"IEC 60601-1-2 Ed {edition} RF immunity envelope",
        )

    return None


def get_limit(
    standard: str,
    class_or_level: str,
    frequency_mhz: float,
    detector: str = "QP",
) -> LimitPoint | None:
    """Return the regulatory limit for ``(standard, class, freq, detector)``.

    Lookup order:
    1. Runtime live-regs cache (populated by ``cache_live_result``).
    2. Local fallback tables in this module.
    3. ``None`` if neither path resolves — callers must surface the gap.
    """
    key = _cache_key(standard, class_or_level, frequency_mhz, detector)
    cached = _LIVE_CACHE.get(key)
    if cached is not None:
        return cached
    return _lookup_fallback(standard, class_or_level, frequency_mhz, detector)


# =============================================================================
# Backwards-compatibility shims
# =============================================================================
# The legacy per-analyzer constants are still imported elsewhere. Re-export
# them here so a one-line change (`from ..limits_provider import ...`) is
# enough to migrate a caller, without rewriting any maths.

CISPR25_RADIATED_LIMITS_LEGACY = [
    {
        "freq_min_mhz": b["f_min"],
        "freq_max_mhz": b["f_max"],
        "limits": dict(b["lim"]),
    }
    for b in _CISPR25_RADIATED
]

CISPR25_CONDUCTED_LIMITS_LEGACY = [
    {
        "freq_min_mhz": b["f_min"],
        "freq_max_mhz": b["f_max"],
        "limits": {k: dict(v) for k, v in b["lim"].items()},
    }
    for b in _CISPR25_CONDUCTED
]

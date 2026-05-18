"""Helpers for normalising schematic / BOM entries that may arrive as
dicts (PDF parser) or dataclasses (KiCad / Altium parsers)."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def coerce(obj: Any) -> dict[str, Any]:
    """Return a plain dict view of *obj* regardless of its concrete type."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if is_dataclass(obj):
        return asdict(obj)
    # Fallback — read public attributes.
    return {
        k: getattr(obj, k)
        for k in dir(obj)
        if not k.startswith("_") and not callable(getattr(obj, k, None))
    }


def component_refdes(c: Any) -> str:
    """Return the refdes string (uppercased) for a component-like entry."""
    d = coerce(c)
    ref = d.get("reference") or d.get("refdes") or d.get("ref") or ""
    return str(ref).strip().upper()


def component_value(c: Any) -> str:
    d = coerce(c)
    val = d.get("value") or ""
    return str(val).strip()


def component_footprint(c: Any) -> str:
    d = coerce(c)
    fp = d.get("footprint") or d.get("package") or ""
    return str(fp).strip()


def component_part_number(c: Any) -> str:
    d = coerce(c)
    pn = d.get("part_number") or d.get("mpn") or d.get("manufacturer_part_number") or ""
    return str(pn).strip()


def component_manufacturer(c: Any) -> str:
    d = coerce(c)
    mfr = d.get("manufacturer") or d.get("mfr") or ""
    return str(mfr).strip()


def net_name(n: Any) -> str:
    d = coerce(n)
    name = d.get("name") or d.get("net_name") or ""
    return str(name).strip()


def is_power_net(n: Any) -> bool:
    d = coerce(n)
    if d.get("is_power"):
        return True
    name = net_name(n).upper()
    if not name:
        return False
    return name.startswith(("VCC", "VDD", "V3", "V5", "V12", "V24", "VBAT", "VBUS", "VIN", "+"))


def is_ground_net(n: Any) -> bool:
    d = coerce(n)
    if d.get("is_ground"):
        return True
    name = net_name(n).upper()
    return name.startswith(("GND", "VSS", "AGND", "DGND", "PGND", "SGND"))


def refdes_prefix(ref: str) -> str:
    """Return the leading letter(s) of a refdes (e.g. 'R12' → 'R', 'CMC1' → 'CMC')."""
    out = []
    for ch in ref:
        if ch.isalpha():
            out.append(ch.upper())
        else:
            break
    return "".join(out)


# Component-class heuristics ---------------------------------------------------

_CAPACITOR_PREFIXES = {"C", "CC"}
_RESISTOR_PREFIXES = {"R", "RR"}
_INDUCTOR_PREFIXES = {"L", "LL", "FB"}
_IC_PREFIXES = {"U", "IC"}
_DIODE_PREFIXES = {"D"}
_TVS_PREFIXES = {"TVS", "ESD", "Z", "TZ", "PESD", "SMAJ", "RCLAMP"}
_FUSE_PREFIXES = {"F"}
_CMC_PREFIXES = {"CMC", "BLM", "FB"}
_TRANSFORMER_PREFIXES = {"T", "TR"}
_TEST_POINT_PREFIXES = {"TP"}
_CONNECTOR_PREFIXES = {"J", "P", "CN"}


def is_capacitor(c: Any) -> bool:
    return refdes_prefix(component_refdes(c)) in _CAPACITOR_PREFIXES


def is_resistor(c: Any) -> bool:
    return refdes_prefix(component_refdes(c)) in _RESISTOR_PREFIXES


def is_inductor(c: Any) -> bool:
    return refdes_prefix(component_refdes(c)) in _INDUCTOR_PREFIXES


def is_ic(c: Any) -> bool:
    return refdes_prefix(component_refdes(c)) in _IC_PREFIXES


def is_diode(c: Any) -> bool:
    return refdes_prefix(component_refdes(c)) in _DIODE_PREFIXES


def is_tvs(c: Any) -> bool:
    prefix = refdes_prefix(component_refdes(c))
    if prefix in _TVS_PREFIXES:
        return True
    val = component_value(c).upper()
    pn = component_part_number(c).upper()
    keywords = ("TVS", "ESD", "SMAJ", "RCLAMP", "PESD")
    return any(k in val for k in keywords) or any(k in pn for k in keywords)


def is_common_mode_choke(c: Any) -> bool:
    prefix = refdes_prefix(component_refdes(c))
    if prefix in _CMC_PREFIXES:
        return True
    val = component_value(c).upper()
    pn = component_part_number(c).upper()
    return "CMC" in val or "COMMON" in val or "CMC" in pn


def is_connector(c: Any) -> bool:
    return refdes_prefix(component_refdes(c)) in _CONNECTOR_PREFIXES


def is_fuse(c: Any) -> bool:
    return refdes_prefix(component_refdes(c)) in _FUSE_PREFIXES


# Value parsing for component_rating analyzer ----------------------------------

def parse_capacitance_uf(value: str) -> float | None:
    """Convert a cap value string ('100nF', '0.1uF', '10uF/25V') to microfarads."""
    if not value:
        return None
    v = value.strip().lower().split("/")[0].split(",")[0]  # strip ratings + tolerance
    # Normalise unit suffixes
    multipliers = [
        ("pf", 1e-6),
        ("nf", 1e-3),
        ("uf", 1.0),
        ("μf", 1.0),
        ("mf", 1e3),
    ]
    for suffix, mul in multipliers:
        if v.endswith(suffix):
            try:
                return float(v.removesuffix(suffix).strip()) * mul
            except ValueError:
                return None
    try:
        return float(v)  # assume already in uF
    except ValueError:
        return None


def parse_voltage_v(value: str) -> float | None:
    """Extract a working voltage rating from a value or description.

    Examples: ``'10uF/25V'`` → 25.0, ``'0.1uF 50V X7R'`` → 50.0.
    """
    if not value:
        return None
    import re
    m = re.search(r"(\d+(?:\.\d+)?)\s*V\b", value, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None

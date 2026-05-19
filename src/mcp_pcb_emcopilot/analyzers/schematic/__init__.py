"""Schematic-aware analyzers (Phase 4b).

Operate on the schematic side of a design — components and nets either as
dicts (from PDF/heuristic parsers) or :class:`ParsedComponent` /
:class:`ParsedNet` dataclasses (from native KiCad/Altium parsers). Each
analyzer is robust to either input shape via the helpers in :mod:`._normalise`.

These are intentionally lightweight: the parsers themselves still vary in
how much they extract (text-only PDF vs full pin-net mapping from native
KiCad), so the analyzers degrade gracefully when key fields are missing
(confidence drops; findings stay informational instead of CRITICAL).
"""

from .component_rating import analyze_component_rating
from .decoupling_per_ic import analyze_decoupling_per_ic
from .power_topology import analyze_power_topology
from .protection_circuits import analyze_protection_circuits
from .signal_flow import analyze_signal_flow

__all__ = [
    "analyze_component_rating",
    "analyze_decoupling_per_ic",
    "analyze_power_topology",
    "analyze_protection_circuits",
    "analyze_signal_flow",
]

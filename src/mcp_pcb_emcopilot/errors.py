"""Structured error types and validation helpers for PCB EMCopilot.

Provides consistent error handling across all parsers, analyzers, and server tools.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PCBError(Exception):
    """Base error for all PCB EMCopilot errors."""
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": type(self).__name__,
            "code": self.code,
            "message": self.message,
            "context": self.context,
        }


class ParseError(PCBError):
    """Error during file parsing."""
    pass


class ValidationError(PCBError):
    """Error during input validation."""
    pass


class AnalysisError(PCBError):
    """Error during analysis/calculation."""
    pass


class SessionError(PCBError):
    """Error related to session management."""
    pass


class MissingDependencyError(PCBError):
    """An optional dependency required for this output is not usable.

    Distinct from a bare :class:`ImportError` for two reasons. First, callers
    need to tell "this feature needs an extra installed" apart from "the import
    machinery is broken", and the MCP layer already serialises :class:`PCBError`
    into a structured tool response. Second, an optional dependency can be
    installed and still unusable — ``cairosvg`` imports ``cairocffi``, which
    raises :class:`OSError` when the native Cairo library is absent (the normal
    situation on Windows). Guarding only ``ImportError`` lets that escape, so
    code intended to degrade gracefully crashes instead.
    """
    pass


class InsufficientDataError(PCBError):
    """The analysis cannot be answered from the data available.

    Deliberately distinct from its siblings:

    - :class:`ValidationError` — the caller passed something malformed.
    - :class:`AnalysisError` — the computation was attempted and failed.
    - :class:`InsufficientDataError` — the inputs are well-formed, they are
      simply *absent*, and any number returned would be invented.

    This exists because the alternative is worse than an error. Several
    analyzers iterate a collection that is empty on an unparsed or
    partially-parsed design, produce zero findings, and report that as a clean
    result — a confident "no problems found" that a user has every reason to
    trust. For a compliance-adjacent tool, "we could not look" and "we looked
    and it is fine" must never serialise to the same thing.

    Raise it rather than returning a sentinel field: a sentinel has to be
    checked at every call site, and a forgotten check silently reproduces the
    original failure. An unhandled raise degrades to a refusal, never to a
    fabricated number.
    """
    pass


class InsufficientSystemContextError(InsufficientDataError):
    """The design parsed fine, but the surrounding system is undetermined.

    Some questions are unanswerable from a board file alone no matter how well
    it parsed. A module or SoM that mounts on a carrier board is the motivating
    case: well below a wavelength the board itself is a poor radiator, so the
    radiating structure is the carrier, and absolute radiated-emissions or
    compliance figures do not exist without the carrier's dimensions.

    A subclass of :class:`InsufficientDataError` so existing handlers catch it,
    but separately identifiable because the remedy differs — supplying a
    stackup or a better export will not fix this one.
    """
    pass


def require_data(analysis: str, **inputs: Any) -> None:
    """Raise :class:`InsufficientDataError` naming every falsy input.

    Usage::

        require_data("return path analysis", nets=design.nets, layers=design.layers)

    Greppable via ``require_data(`` / ``INSUFFICIENT_DATA`` /
    ``InsufficientDataError`` so the set of guarded analyses can be audited.
    """
    missing = sorted(name for name, value in inputs.items() if not value)
    if missing:
        raise InsufficientDataError(
            "INSUFFICIENT_DATA",
            f"Cannot perform {analysis}: the parsed design has no "
            f"{', '.join(missing)}. This is a data gap, not a pass — no result "
            "is reported because any value would be invented.",
            {"analysis": analysis, "missing": missing},
        )


def error_response(code: str, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a structured error response dict for MCP tool results."""
    return {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "context": context or {},
        },
    }


def validate_positive(value: float, name: str) -> float:
    """Validate that a value is positive (> 0)."""
    if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
        raise ValidationError("INVALID_TYPE", f"{name} must be a finite number, got {value!r}", {name: value})
    if value <= 0:
        raise ValidationError("INVALID_VALUE", f"{name} must be positive, got {value}", {name: value})
    return float(value)


def validate_non_negative(value: float, name: str) -> float:
    """Validate that a value is non-negative (>= 0)."""
    if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
        raise ValidationError("INVALID_TYPE", f"{name} must be a finite number, got {value!r}", {name: value})
    if value < 0:
        raise ValidationError("INVALID_VALUE", f"{name} must be non-negative, got {value}", {name: value})
    return float(value)


def validate_range(value: float, min_val: float, max_val: float, name: str) -> float:
    """Validate that a value falls within a range [min_val, max_val]."""
    if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
        raise ValidationError("INVALID_TYPE", f"{name} must be a finite number, got {value!r}", {name: value})
    if not (min_val <= value <= max_val):
        raise ValidationError(
            "OUT_OF_RANGE",
            f"{name} must be between {min_val} and {max_val}, got {value}",
            {name: value, "min": min_val, "max": max_val},
        )
    return float(value)


def validate_session(session_id: str, manager: Any) -> Any:
    """Validate that a session exists and return the design data."""
    design = manager.get(session_id)
    if design is None:
        raise SessionError(
            "INVALID_SESSION",
            f"No active session with ID '{session_id}'. Use pcb_parse_layout to create one first.",
            {"session_id": session_id, "available_sessions": list(manager.list_sessions()) if hasattr(manager, 'list_sessions') else []},
        )
    return design


def validate_string(value: Any, name: str, allowed: list[str] | None = None) -> str:
    """Validate that a value is a non-empty string, optionally from allowed values."""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("INVALID_STRING", f"{name} must be a non-empty string, got {value!r}", {name: value})
    if allowed and value not in allowed:
        raise ValidationError(
            "INVALID_OPTION",
            f"{name} must be one of {allowed}, got '{value}'",
            {name: value, "allowed": allowed},
        )
    return value

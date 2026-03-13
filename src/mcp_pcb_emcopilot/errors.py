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

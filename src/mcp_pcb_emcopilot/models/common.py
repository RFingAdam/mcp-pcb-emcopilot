"""Shared enums and base types for PCB analysis."""

from enum import Enum


class TraceType(str, Enum):
    MICROSTRIP = "microstrip"
    STRIPLINE = "stripline"
    COPLANAR = "coplanar"
    DIFFERENTIAL = "differential"


class ViaType(str, Enum):
    THROUGH = "through"
    BLIND = "blind"
    BURIED = "buried"
    MICROVIA = "microvia"


class LayerType(str, Enum):
    SIGNAL = "signal"
    PLANE = "plane"
    MIXED = "mixed"
    DIELECTRIC = "dielectric"
    SOLDER_MASK = "solder_mask"
    SILK_SCREEN = "silk_screen"
    SOLDER_PASTE = "solder_paste"
    DRILL = "drill"


class DesignType(str, Enum):
    DIGITAL = "digital"
    ANALOG = "analog"
    MIXED_SIGNAL = "mixed_signal"
    RF = "rf"
    POWER = "power"
    HIGH_SPEED = "high_speed"

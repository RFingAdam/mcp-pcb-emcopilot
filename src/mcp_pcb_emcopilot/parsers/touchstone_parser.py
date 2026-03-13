"""Touchstone S-parameter file parser.

Parses Touchstone files (.s1p, .s2p, .s4p, .snp) to extract:
- Option line (frequency units, parameter type, data format, reference impedance)
- S-parameter data at each frequency point
- Support for RI (real/imaginary), MA (magnitude/angle), DB (dB/angle) formats
- 1-port, 2-port, and 4-port files
- Conversion to complex S-parameters internally
"""
from __future__ import annotations

import cmath
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Frequency unit multipliers
_FREQ_UNITS: dict[str, float] = {
    "hz": 1.0,
    "khz": 1e3,
    "mhz": 1e6,
    "ghz": 1e9,
}


@dataclass
class TouchstoneData:
    """Parsed Touchstone S-parameter data."""
    port_count: int = 0
    frequencies_hz: list[float] = field(default_factory=list)
    s_parameters: dict[tuple[int, int], list[complex]] = field(default_factory=dict)
    reference_impedance: float = 50.0
    source_file: str = ""
    param_type: str = "S"
    original_format: str = "RI"
    freq_unit: str = "GHz"

    @property
    def num_points(self) -> int:
        """Number of frequency points."""
        return len(self.frequencies_hz)

    @property
    def freq_range_hz(self) -> tuple[float, float]:
        """Frequency range (min, max) in Hz."""
        if not self.frequencies_hz:
            return (0.0, 0.0)
        return (min(self.frequencies_hz), max(self.frequencies_hz))

    def get_s(self, i: int, j: int) -> list[complex]:
        """Get S-parameter S(i,j) data.

        Args:
            i: Output port (1-based).
            j: Input port (1-based).

        Returns:
            List of complex S-parameter values at each frequency.

        Raises:
            KeyError: If the port pair is not available.
        """
        key = (i, j)
        if key not in self.s_parameters:
            raise KeyError(f"S{i}{j} not available. Available: {list(self.s_parameters.keys())}")
        return self.s_parameters[key]

    def get_s_db(self, i: int, j: int) -> list[float]:
        """Get S-parameter magnitude in dB."""
        values = self.get_s(i, j)
        return [20 * math.log10(abs(v) + 1e-15) for v in values]

    def get_s_phase_deg(self, i: int, j: int) -> list[float]:
        """Get S-parameter phase in degrees."""
        values = self.get_s(i, j)
        return [math.degrees(cmath.phase(v)) for v in values]

    def get_s_magnitude(self, i: int, j: int) -> list[float]:
        """Get S-parameter linear magnitude."""
        values = self.get_s(i, j)
        return [abs(v) for v in values]

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        result: dict = {
            "port_count": self.port_count,
            "num_points": self.num_points,
            "freq_range_hz": list(self.freq_range_hz),
            "reference_impedance": self.reference_impedance,
            "source_file": self.source_file,
            "param_type": self.param_type,
            "original_format": self.original_format,
        }

        # Add S-parameter summary
        sparams: dict = {}
        for (i, j), values in self.s_parameters.items():
            key = f"S{i}{j}"
            db_vals = [20 * math.log10(abs(v) + 1e-15) for v in values]
            sparams[key] = {
                "min_db": round(min(db_vals), 3) if db_vals else None,
                "max_db": round(max(db_vals), 3) if db_vals else None,
                "points": len(values),
            }
        result["s_parameters_summary"] = sparams

        return result


def _parse_option_line(line: str) -> dict:
    """Parse the Touchstone option line.

    Format: # [freq_unit] [param_type] [format] R [impedance]

    Args:
        line: The option line string (starting with #).

    Returns:
        Dict with freq_unit, param_type, format, impedance.
    """
    result = {
        "freq_unit": "ghz",
        "param_type": "S",
        "format": "MA",
        "impedance": 50.0,
    }

    # Remove the # prefix
    content = line.lstrip("#").strip()
    parts = content.split()

    i = 0
    while i < len(parts):
        token = parts[i].upper()

        if token in ("HZ", "KHZ", "MHZ", "GHZ"):
            result["freq_unit"] = token.lower()
        elif token in ("S", "Y", "Z", "H", "G"):
            result["param_type"] = token
        elif token in ("RI", "MA", "DB"):
            result["format"] = token
        elif token == "R" and i + 1 < len(parts):
            try:
                result["impedance"] = float(parts[i + 1])
                i += 1
            except ValueError:
                pass
        i += 1

    return result


def _values_to_complex(v1: float, v2: float, fmt: str) -> complex:
    """Convert a pair of values to a complex number based on format.

    Args:
        v1: First value (real, magnitude, or dB).
        v2: Second value (imaginary, angle_deg, or angle_deg).
        fmt: Data format ("RI", "MA", or "DB").

    Returns:
        Complex number.
    """
    if fmt == "RI":
        return complex(v1, v2)
    elif fmt == "MA":
        return cmath.rect(v1, math.radians(v2))
    elif fmt == "DB":
        magnitude = 10.0 ** (v1 / 20.0)
        return cmath.rect(magnitude, math.radians(v2))
    else:
        raise ValueError(f"Unknown format: {fmt}")


def _detect_port_count(file_path: str) -> int:
    """Detect port count from file extension.

    Args:
        file_path: Path to the Touchstone file.

    Returns:
        Port count (1, 2, 4, etc.) or 2 as default.
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    match = re.match(r"\.s(\d+)p", ext)
    if match:
        return int(match.group(1))

    return 2  # Default


class TouchstoneParser:
    """Parser for Touchstone (.snp) files.

    Supports .s1p, .s2p, .s4p and other port counts.
    Handles RI, MA, and DB data formats.
    Converts all frequencies to Hz and all data to complex S-parameters.

    Usage:
        parser = TouchstoneParser()
        data = parser.parse_file("channel.s2p")
        s21_db = data.get_s_db(2, 1)
    """

    def parse_file(self, file_path: str) -> TouchstoneData:
        """Parse a Touchstone file from disk.

        Args:
            file_path: Path to the Touchstone file.

        Returns:
            TouchstoneData with parsed S-parameter data.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the file format is invalid.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Touchstone file not found: {file_path}")

        content = path.read_text(encoding="utf-8", errors="replace")
        port_count = _detect_port_count(file_path)
        return self.parse_string(content, port_count=port_count, source_file=file_path)

    def parse_string(
        self,
        content: str,
        port_count: int = 2,
        source_file: str = "",
    ) -> TouchstoneData:
        """Parse Touchstone content from a string.

        Args:
            content: Touchstone file content.
            port_count: Number of ports (default 2).
            source_file: Source file path for metadata.

        Returns:
            TouchstoneData with parsed S-parameter data.

        Raises:
            ValueError: If the content is invalid.
        """
        data = TouchstoneData(
            port_count=port_count,
            source_file=source_file,
        )

        lines = content.splitlines()
        option_parsed = False
        freq_unit_mult = 1e9  # Default GHz
        data_format = "MA"
        n = port_count

        # Initialize S-parameter storage
        for i in range(1, n + 1):
            for j in range(1, n + 1):
                data.s_parameters[(i, j)] = []

        # Collect all data values (across potentially continued lines)
        all_data_values: list[list[float]] = []
        current_line_values: list[float] = []

        # Number of values per frequency point
        values_per_point = 2 * n * n + 1  # freq + n*n complex pairs

        for line in lines:
            stripped = line.strip()

            # Skip empty lines
            if not stripped:
                continue

            # Skip comment lines
            if stripped.startswith("!"):
                continue

            # Option line
            if stripped.startswith("#"):
                options = _parse_option_line(stripped)
                freq_unit_mult = _FREQ_UNITS.get(options["freq_unit"], 1e9)
                data_format = options["format"]
                data.reference_impedance = options["impedance"]
                data.param_type = options["param_type"]
                data.original_format = data_format
                data.freq_unit = options["freq_unit"].upper()
                option_parsed = True
                continue

            # Data line - parse all numeric values
            # Remove inline comments (! at end of line)
            if "!" in stripped:
                stripped = stripped[:stripped.index("!")].strip()
            if not stripped:
                continue

            try:
                values = [float(x) for x in stripped.split()]
            except ValueError:
                continue

            current_line_values.extend(values)

            # Check if we have enough values for a complete data point
            while len(current_line_values) >= values_per_point:
                point_values = current_line_values[:values_per_point]
                current_line_values = current_line_values[values_per_point:]

                # First value is frequency
                freq_hz = point_values[0] * freq_unit_mult
                data.frequencies_hz.append(freq_hz)

                # Remaining values are S-parameter pairs
                pair_idx = 1
                if n == 1:
                    # 1-port: S11
                    v1, v2 = point_values[pair_idx], point_values[pair_idx + 1]
                    s_val = _values_to_complex(v1, v2, data_format)
                    data.s_parameters[(1, 1)].append(s_val)
                elif n == 2:
                    # 2-port: S11, S21, S12, S22
                    port_order = [(1, 1), (2, 1), (1, 2), (2, 2)]
                    for pi, pj in port_order:
                        v1 = point_values[pair_idx]
                        v2 = point_values[pair_idx + 1]
                        s_val = _values_to_complex(v1, v2, data_format)
                        data.s_parameters[(pi, pj)].append(s_val)
                        pair_idx += 2
                else:
                    # N-port: row-major order S11, S12, ... S1N, S21, ...
                    for row in range(1, n + 1):
                        for col in range(1, n + 1):
                            v1 = point_values[pair_idx]
                            v2 = point_values[pair_idx + 1]
                            s_val = _values_to_complex(v1, v2, data_format)
                            data.s_parameters[(row, col)].append(s_val)
                            pair_idx += 2

        return data


def analyze_sparams(
    data: TouchstoneData,
    analysis_type: str,
) -> dict:
    """Analyze imported S-parameters.

    Args:
        data: TouchstoneData from parser.
        analysis_type: Type of analysis:
            - "insertion_loss": Analyze S21 insertion loss
            - "return_loss": Analyze S11 return loss
            - "crosstalk": Analyze near/far-end crosstalk (4-port)
            - "impedance": Calculate impedance profile from S11

    Returns:
        Analysis results dictionary.
    """
    if analysis_type == "insertion_loss":
        return _analyze_insertion_loss(data)
    elif analysis_type == "return_loss":
        return _analyze_return_loss(data)
    elif analysis_type == "crosstalk":
        return _analyze_crosstalk(data)
    elif analysis_type == "impedance":
        return _analyze_impedance(data)
    else:
        raise ValueError(f"Unknown analysis type: {analysis_type}. "
                         f"Supported: insertion_loss, return_loss, crosstalk, impedance")


def _analyze_insertion_loss(data: TouchstoneData) -> dict:
    """Analyze insertion loss from S21."""
    if data.port_count < 2:
        return {"error": "Insertion loss requires at least 2-port data"}

    s21_db = data.get_s_db(2, 1)
    freqs = data.frequencies_hz

    worst_il = min(s21_db) if s21_db else 0.0
    worst_il_freq = freqs[s21_db.index(worst_il)] if s21_db else 0.0

    # Find -3dB bandwidth
    bw_3db = None
    for i, (f, il) in enumerate(zip(freqs, s21_db)):
        if il < -3.0:
            bw_3db = f
            break

    # Loss at specific frequencies
    loss_at_freqs: dict[str, Optional[float]] = {}
    target_freqs = {"1_GHz": 1e9, "2.5_GHz": 2.5e9, "5_GHz": 5e9, "8_GHz": 8e9}
    for label, target_f in target_freqs.items():
        loss_at_freqs[label] = _interpolate_at_freq(freqs, s21_db, target_f)

    return {
        "analysis_type": "insertion_loss",
        "worst_case_il_db": round(worst_il, 3),
        "worst_case_frequency_hz": worst_il_freq,
        "bandwidth_3db_hz": bw_3db,
        "loss_at_frequencies": {
            k: round(v, 3) if v is not None else None
            for k, v in loss_at_freqs.items()
        },
        "frequency_range_hz": list(data.freq_range_hz),
        "num_points": data.num_points,
    }


def _analyze_return_loss(data: TouchstoneData) -> dict:
    """Analyze return loss from S11."""
    s11_db = data.get_s_db(1, 1)
    freqs = data.frequencies_hz

    worst_rl = max(s11_db) if s11_db else 0.0
    worst_rl_freq = freqs[s11_db.index(worst_rl)] if s11_db else 0.0

    # Average return loss
    avg_rl = sum(s11_db) / len(s11_db) if s11_db else 0.0

    # Return loss at specific frequencies
    rl_at_freqs: dict[str, Optional[float]] = {}
    target_freqs = {"1_GHz": 1e9, "2.5_GHz": 2.5e9, "5_GHz": 5e9, "8_GHz": 8e9}
    for label, target_f in target_freqs.items():
        rl_at_freqs[label] = _interpolate_at_freq(freqs, s11_db, target_f)

    return {
        "analysis_type": "return_loss",
        "worst_case_rl_db": round(worst_rl, 3),
        "worst_case_frequency_hz": worst_rl_freq,
        "average_rl_db": round(avg_rl, 3),
        "return_loss_at_frequencies": {
            k: round(v, 3) if v is not None else None
            for k, v in rl_at_freqs.items()
        },
        "frequency_range_hz": list(data.freq_range_hz),
        "num_points": data.num_points,
    }


def _analyze_crosstalk(data: TouchstoneData) -> dict:
    """Analyze crosstalk from 4-port data."""
    if data.port_count < 4:
        # For 2-port, we can still report S12 as a coupling indicator
        if data.port_count >= 2:
            s12_db = data.get_s_db(1, 2)
            worst_coupling = max(s12_db) if s12_db else -100.0
            return {
                "analysis_type": "crosstalk",
                "port_count": data.port_count,
                "note": "2-port data: S12 used as coupling indicator",
                "worst_case_coupling_db": round(worst_coupling, 3),
                "num_points": data.num_points,
            }
        return {"error": "Crosstalk analysis requires at least 2-port data"}

    # 4-port: S31 = NEXT, S41 = FEXT typically
    try:
        next_db = data.get_s_db(3, 1)
    except KeyError:
        next_db = []
    try:
        fext_db = data.get_s_db(4, 1)
    except KeyError:
        fext_db = []

    result: dict = {
        "analysis_type": "crosstalk",
        "port_count": data.port_count,
        "num_points": data.num_points,
    }

    if next_db:
        result["worst_next_db"] = round(max(next_db), 3)
    if fext_db:
        result["worst_fext_db"] = round(max(fext_db), 3)

    return result


def _analyze_impedance(data: TouchstoneData) -> dict:
    """Calculate impedance profile from S11."""
    s11 = data.get_s(1, 1)
    z0 = data.reference_impedance
    freqs = data.frequencies_hz

    impedances = []
    for s_val in s11:
        # Z = Z0 * (1 + S11) / (1 - S11)
        denom = 1.0 - s_val
        if abs(denom) > 1e-10:
            z = z0 * (1.0 + s_val) / denom
            impedances.append(abs(z))
        else:
            impedances.append(float("inf"))

    avg_z = sum(z for z in impedances if z < 1e6) / max(len([z for z in impedances if z < 1e6]), 1)
    min_z = min(z for z in impedances if z < 1e6) if any(z < 1e6 for z in impedances) else 0
    max_z = max(z for z in impedances if z < 1e6) if any(z < 1e6 for z in impedances) else 0

    return {
        "analysis_type": "impedance",
        "reference_impedance_ohm": z0,
        "average_impedance_ohm": round(avg_z, 2),
        "min_impedance_ohm": round(min_z, 2),
        "max_impedance_ohm": round(max_z, 2),
        "impedance_variation_percent": round((max_z - min_z) / avg_z * 100, 1) if avg_z > 0 else 0,
        "num_points": data.num_points,
    }


def check_channel_compliance(
    data: TouchstoneData,
    protocol: str,
) -> dict:
    """Check S-parameters against protocol specification limits.

    Args:
        data: TouchstoneData from parser.
        protocol: Protocol to check against:
            - "usb3": USB 3.x SuperSpeed
            - "pcie_gen3": PCIe Gen3 (8 GT/s)
            - "pcie_gen4": PCIe Gen4 (16 GT/s)
            - "100gbase": 100GBASE Ethernet

    Returns:
        Compliance check results with pass/fail per limit.
    """
    specs = _PROTOCOL_SPECS.get(protocol)
    if specs is None:
        return {
            "error": f"Unknown protocol: {protocol}. "
                     f"Supported: {list(_PROTOCOL_SPECS.keys())}",
        }

    if data.port_count < 2:
        return {"error": "Compliance checking requires at least 2-port data"}

    s21_db = data.get_s_db(2, 1)
    s11_db = data.get_s_db(1, 1)
    freqs = data.frequencies_hz

    results: dict = {
        "protocol": protocol,
        "protocol_name": specs["name"],
        "nyquist_frequency_ghz": specs["nyquist_ghz"],
        "checks": [],
        "overall_pass": True,
    }

    # Check insertion loss at Nyquist
    il_at_nyquist = _interpolate_at_freq(freqs, s21_db, specs["nyquist_ghz"] * 1e9)
    if il_at_nyquist is not None:
        il_pass = il_at_nyquist >= specs["max_il_at_nyquist_db"]
        results["checks"].append({
            "parameter": "insertion_loss_at_nyquist",
            "measured_db": round(il_at_nyquist, 3),
            "limit_db": specs["max_il_at_nyquist_db"],
            "pass": il_pass,
            "margin_db": round(il_at_nyquist - specs["max_il_at_nyquist_db"], 3),
        })
        if not il_pass:
            results["overall_pass"] = False

    # Check return loss
    # Find worst return loss up to Nyquist
    rl_values_in_band = [
        s11 for f, s11 in zip(freqs, s11_db)
        if f <= specs["nyquist_ghz"] * 1e9
    ]
    if rl_values_in_band:
        worst_rl = max(rl_values_in_band)
        rl_pass = worst_rl <= specs["max_rl_db"]
        results["checks"].append({
            "parameter": "return_loss_in_band",
            "measured_db": round(worst_rl, 3),
            "limit_db": specs["max_rl_db"],
            "pass": rl_pass,
            "margin_db": round(specs["max_rl_db"] - worst_rl, 3),
        })
        if not rl_pass:
            results["overall_pass"] = False

    # Check IL at specific frequencies if defined
    for check_freq_ghz in specs.get("check_frequencies_ghz", []):
        il_at_freq = _interpolate_at_freq(freqs, s21_db, check_freq_ghz * 1e9)
        if il_at_freq is not None:
            results["checks"].append({
                "parameter": f"insertion_loss_at_{check_freq_ghz}GHz",
                "measured_db": round(il_at_freq, 3),
                "frequency_ghz": check_freq_ghz,
            })

    return results


def _interpolate_at_freq(
    freqs: list[float],
    values: list[float],
    target_freq: float,
) -> Optional[float]:
    """Interpolate a value at a target frequency.

    Args:
        freqs: Frequency points.
        values: Values at each frequency.
        target_freq: Target frequency to interpolate at.

    Returns:
        Interpolated value, or None if out of range.
    """
    if not freqs or not values or len(freqs) != len(values):
        return None

    if target_freq <= freqs[0]:
        return values[0]
    if target_freq >= freqs[-1]:
        return values[-1]

    for i in range(len(freqs) - 1):
        if freqs[i] <= target_freq <= freqs[i + 1]:
            if abs(freqs[i + 1] - freqs[i]) < 1e-10:
                return values[i]
            fraction = (target_freq - freqs[i]) / (freqs[i + 1] - freqs[i])
            return values[i] + fraction * (values[i + 1] - values[i])

    return None


# Protocol specifications for compliance checking
_PROTOCOL_SPECS: dict[str, dict] = {
    "usb3": {
        "name": "USB 3.2 Gen1 SuperSpeed (5 GT/s)",
        "nyquist_ghz": 2.5,
        "max_il_at_nyquist_db": -8.0,  # Max allowed IL (S21) at Nyquist
        "max_rl_db": -10.0,  # Max return loss (S11) in band
        "check_frequencies_ghz": [1.25, 2.5, 5.0],
    },
    "pcie_gen3": {
        "name": "PCIe Gen3 (8 GT/s)",
        "nyquist_ghz": 4.0,
        "max_il_at_nyquist_db": -12.0,
        "max_rl_db": -10.0,
        "check_frequencies_ghz": [2.0, 4.0, 8.0],
    },
    "pcie_gen4": {
        "name": "PCIe Gen4 (16 GT/s)",
        "nyquist_ghz": 8.0,
        "max_il_at_nyquist_db": -20.0,
        "max_rl_db": -8.0,
        "check_frequencies_ghz": [4.0, 8.0, 16.0],
    },
    "100gbase": {
        "name": "100GBASE-KR4 / 25.78 Gbaud",
        "nyquist_ghz": 12.89,
        "max_il_at_nyquist_db": -25.0,
        "max_rl_db": -8.0,
        "check_frequencies_ghz": [6.0, 12.89],
    },
}

"""IBIS (Input/Output Buffer Information Specification) file parser.

Parses IBIS .ibs files to extract:
- Component info (name, manufacturer, package RLC)
- Pin list with signal/model assignments
- Model definitions with I-V curves and waveforms
- typ/min/max triplet columns
- Engineering notation (1.0n, 5.0p, etc.)
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Engineering notation suffixes
_ENG_SUFFIXES: dict[str, float] = {
    "T": 1e12, "t": 1e12,
    "G": 1e9, "g": 1e9,
    "M": 1e6, "m": 1e-3,
    "k": 1e3, "K": 1e3,
    "n": 1e-9, "N": 1e-9,
    "p": 1e-12, "P": 1e-12,
    "f": 1e-15, "F": 1e-15,
    "u": 1e-6, "U": 1e-6,
}

# Regex for engineering notation: number followed by optional suffix and optional unit
_ENG_RE = re.compile(
    r"^([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)\s*([TtGgMmkKnNpPfFuU])?\s*([A-Za-z/]*)\s*$"
)


def parse_eng_notation(value_str: str) -> float:
    """Parse a value string with optional engineering notation suffix.

    Examples:
        '1.0n' -> 1e-9
        '5.0pF' -> 5e-12
        '0.1' -> 0.1
        '50.0mA' -> 0.05
        '-3.3V' -> -3.3 (no suffix, V is unit)
        '1.5nH' -> 1.5e-9

    Args:
        value_str: String containing the value with optional suffix.

    Returns:
        Float value in base units.

    Raises:
        ValueError: If the string cannot be parsed.
    """
    s = value_str.strip()
    if not s:
        raise ValueError("Empty value string")

    match = _ENG_RE.match(s)
    if match:
        num = float(match.group(1))
        suffix = match.group(2)
        if suffix and suffix in _ENG_SUFFIXES:
            return num * _ENG_SUFFIXES[suffix]
        return num

    # Try plain float
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"Cannot parse engineering notation: '{value_str}'")


def _parse_triplet(parts: list[str]) -> dict[str, float]:
    """Parse a typ/min/max triplet from a list of string values.

    Args:
        parts: List of 1-3 value strings.

    Returns:
        Dict with 'typ', and optionally 'min', 'max' keys.
    """
    result: dict[str, float] = {}
    if len(parts) >= 1 and parts[0].strip():
        result["typ"] = parse_eng_notation(parts[0])
    if len(parts) >= 2 and parts[1].strip():
        result["min"] = parse_eng_notation(parts[1])
    if len(parts) >= 3 and parts[2].strip():
        result["max"] = parse_eng_notation(parts[2])
    return result


@dataclass
class IBISModel:
    """Parsed IBIS model data."""
    component_name: str = ""
    manufacturer: str = ""
    ibis_version: str = ""
    package_rlc: dict[str, dict[str, float]] = field(default_factory=dict)
    pins: list[dict] = field(default_factory=list)
    models: dict[str, dict] = field(default_factory=dict)

    def get_model(self, model_name: str) -> Optional[dict]:
        """Get a model definition by name (case-insensitive)."""
        for name, model in self.models.items():
            if name.lower() == model_name.lower():
                return model
        return None

    def get_pin_by_number(self, pin_num: str) -> Optional[dict]:
        """Get a pin by its number."""
        for pin in self.pins:
            if str(pin.get("pin_num")) == str(pin_num):
                return pin
        return None

    def model_names(self) -> list[str]:
        """Return list of model names."""
        return list(self.models.keys())

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "component_name": self.component_name,
            "manufacturer": self.manufacturer,
            "ibis_version": self.ibis_version,
            "package_rlc": self.package_rlc,
            "pin_count": len(self.pins),
            "pins": self.pins,
            "model_count": len(self.models),
            "model_names": self.model_names(),
            "models": self.models,
        }


class IBISParser:
    """Parser for IBIS (.ibs) files.

    Usage:
        parser = IBISParser()
        model = parser.parse_file("component.ibs")
        print(model.component_name)
        print(model.models["IO_3V3"])
    """

    # Valid model types per IBIS spec
    VALID_MODEL_TYPES = {
        "input", "output", "i/o", "3-state", "open_drain", "open_sink",
        "open_source", "i/o_open_drain", "i/o_open_sink", "i/o_open_source",
        "terminator", "series", "series_switch",
    }

    def parse_file(self, file_path: str) -> IBISModel:
        """Parse an IBIS file from disk.

        Args:
            file_path: Path to the .ibs file.

        Returns:
            IBISModel with parsed data.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the file is not valid IBIS format.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"IBIS file not found: {file_path}")

        content = path.read_text(encoding="utf-8", errors="replace")
        return self.parse_string(content)

    def parse_string(self, content: str) -> IBISModel:
        """Parse IBIS content from a string.

        Args:
            content: IBIS file content as string.

        Returns:
            IBISModel with parsed data.

        Raises:
            ValueError: If the content is not valid IBIS format.
        """
        model = IBISModel()
        lines = content.splitlines()

        current_section: Optional[str] = None
        current_model_name: Optional[str] = None
        current_subsection: Optional[str] = None
        current_waveform: Optional[dict] = None

        i = 0
        while i < len(lines):
            line = lines[i]
            i += 1

            # Strip inline comments (IBIS uses | as comment marker)
            if "|" in line:
                # Only strip if | is not inside quotes
                comment_pos = line.index("|")
                line = line[:comment_pos]

            stripped = line.strip()

            # Skip empty lines and full comment lines
            if not stripped:
                continue

            # Check for section headers [SectionName]
            section_match = re.match(r"^\[([^\]]+)\](.*)$", stripped)
            if section_match:
                section_name = section_match.group(1).strip()
                section_rest = section_match.group(2).strip()
                current_subsection = None
                current_waveform = None

                section_lower = section_name.lower()

                if section_lower == "ibis ver":
                    current_section = "ibis_ver"
                    if section_rest:
                        model.ibis_version = section_rest.strip()

                elif section_lower == "component":
                    current_section = "component"
                    if section_rest:
                        model.component_name = section_rest.strip()

                elif section_lower == "manufacturer":
                    current_section = "manufacturer"
                    if section_rest:
                        model.manufacturer = section_rest.strip()

                elif section_lower == "package":
                    current_section = "package"

                elif section_lower == "pin":
                    current_section = "pin"

                elif section_lower == "model":
                    current_section = "model"
                    if section_rest:
                        current_model_name = section_rest.strip()
                        if current_model_name not in model.models:
                            model.models[current_model_name] = {
                                "model_type": "",
                                "vinl": None,
                                "vinh": None,
                                "vmeas": None,
                                "c_comp": {},
                                "voltage_range": {},
                                "ramp": {},
                                "pullup": [],
                                "pulldown": [],
                                "rising_waveform": [],
                                "falling_waveform": [],
                            }

                elif section_lower == "pullup":
                    current_subsection = "pullup"

                elif section_lower == "pulldown":
                    current_subsection = "pulldown"

                elif section_lower == "rising waveform":
                    current_subsection = "rising_waveform"
                    current_waveform = {
                        "r_fixture": None,
                        "v_fixture": None,
                        "data": [],
                    }

                elif section_lower == "falling waveform":
                    current_subsection = "falling_waveform"
                    current_waveform = {
                        "r_fixture": None,
                        "v_fixture": None,
                        "data": [],
                    }

                elif section_lower == "voltage range":
                    current_subsection = "voltage_range"
                    # Voltage Range can have values on the same line: [Voltage Range] typ min max
                    if section_rest and current_model_name:
                        parts = section_rest.split()
                        try:
                            triplet = _parse_triplet(parts[:3])
                            model.models[current_model_name]["voltage_range"] = triplet
                        except (ValueError, IndexError):
                            pass

                elif section_lower == "ramp":
                    current_subsection = "ramp"

                elif section_lower == "end":
                    # End of file marker
                    break

                else:
                    # Unknown section - reset subsection tracking
                    current_section = section_lower
                    current_subsection = None

                continue

            # Process data within sections
            if current_section == "ibis_ver" and not model.ibis_version:
                model.ibis_version = stripped

            elif current_section == "component" and not model.component_name:
                model.component_name = stripped

            elif current_section == "manufacturer" and not model.manufacturer:
                model.manufacturer = stripped

            elif current_section == "package":
                self._parse_package_line(stripped, model)

            elif current_section == "pin":
                self._parse_pin_line(stripped, model)

            elif current_section == "model":
                if current_subsection == "pullup" and current_model_name:
                    self._parse_iv_line(stripped, model.models[current_model_name], "pullup")
                elif current_subsection == "pulldown" and current_model_name:
                    self._parse_iv_line(stripped, model.models[current_model_name], "pulldown")
                elif current_subsection in ("rising_waveform", "falling_waveform") and current_model_name and current_waveform is not None:
                    if stripped.lower().startswith("r_fixture"):
                        val = stripped.split("=")[-1].strip() if "=" in stripped else ""
                        if val:
                            try:
                                current_waveform["r_fixture"] = parse_eng_notation(val)
                            except ValueError:
                                pass
                    elif stripped.lower().startswith("v_fixture"):
                        val = stripped.split("=")[-1].strip() if "=" in stripped else ""
                        if val:
                            try:
                                current_waveform["v_fixture"] = parse_eng_notation(val)
                            except ValueError:
                                pass
                    elif stripped.lower().startswith("v_fixture_min"):
                        pass  # ignore fixture min/max for now
                    elif stripped.lower().startswith("v_fixture_max"):
                        pass
                    else:
                        self._parse_waveform_line(stripped, current_waveform)
                        # Store waveform data on model
                        existing = model.models[current_model_name].get(current_subsection, [])
                        # Replace last waveform entry or append new
                        if existing and existing[-1] is current_waveform:
                            pass  # already the same reference
                        elif current_waveform not in existing:
                            existing.append(current_waveform)
                            model.models[current_model_name][current_subsection] = existing
                elif current_subsection == "ramp" and current_model_name:
                    self._parse_ramp_line(stripped, model.models[current_model_name])
                elif current_subsection == "voltage_range" and current_model_name:
                    # Voltage range data lines (if values weren't on the header line)
                    parts = stripped.split()
                    if parts and not parts[0].startswith("|"):
                        try:
                            triplet = _parse_triplet(parts[:3])
                            if triplet:
                                model.models[current_model_name]["voltage_range"] = triplet
                        except (ValueError, IndexError):
                            pass
                else:
                    # Model-level parameters
                    if current_model_name:
                        self._parse_model_param(stripped, model.models[current_model_name])

        return model

    def _parse_package_line(self, line: str, model: IBISModel) -> None:
        """Parse a line from the [Package] section."""
        parts = line.split()
        if len(parts) < 2:
            return

        param_name = parts[0].lower()
        if param_name in ("r_pkg", "l_pkg", "c_pkg"):
            try:
                triplet = _parse_triplet(parts[1:4])
                model.package_rlc[param_name.upper()] = triplet
            except (ValueError, IndexError):
                pass

    def _parse_pin_line(self, line: str, model: IBISModel) -> None:
        """Parse a line from the [Pin] section."""
        # Skip header lines
        if line.lower().startswith("pin") and "signal" in line.lower():
            return

        parts = line.split()
        if len(parts) < 3:
            return

        # Skip if it looks like a header/divider
        if parts[0].startswith("-") or parts[0].startswith("="):
            return

        pin: dict = {
            "pin_num": parts[0],
            "signal": parts[1],
            "model_name": parts[2],
        }

        # Optional R_pin, L_pin, C_pin
        if len(parts) >= 4:
            try:
                pin["R_pin"] = parse_eng_notation(parts[3])
            except ValueError:
                pass
        if len(parts) >= 5:
            try:
                pin["L_pin"] = parse_eng_notation(parts[4])
            except ValueError:
                pass
        if len(parts) >= 6:
            try:
                pin["C_pin"] = parse_eng_notation(parts[5])
            except ValueError:
                pass

        model.pins.append(pin)

    def _parse_model_param(self, line: str, model_dict: dict) -> None:
        """Parse a model-level parameter line."""
        lower = line.lower()

        # Model_type
        if lower.startswith("model_type"):
            parts_mt = line.split(None, 1)
            if len(parts_mt) > 1:
                mtype = parts_mt[1].strip().lower()
                model_dict["model_type"] = mtype

        # Vinl
        elif lower.startswith("vinl"):
            vinl_s = line.split("=")[-1].strip() if "=" in line else ""
            if vinl_s:
                try:
                    model_dict["vinl"] = parse_eng_notation(vinl_s)
                except ValueError:
                    pass

        # Vinh
        elif lower.startswith("vinh"):
            vinh_s = line.split("=")[-1].strip() if "=" in line else ""
            if vinh_s:
                try:
                    model_dict["vinh"] = parse_eng_notation(vinh_s)
                except ValueError:
                    pass

        # Vmeas
        elif lower.startswith("vmeas"):
            vmeas_s = line.split("=")[-1].strip() if "=" in line else ""
            if vmeas_s:
                try:
                    model_dict["vmeas"] = parse_eng_notation(vmeas_s)
                except ValueError:
                    pass

        # C_comp
        elif lower.startswith("c_comp"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    triplet = _parse_triplet(parts[1:4])
                    model_dict["c_comp"] = triplet
                except ValueError:
                    pass

    def _parse_ramp_line(self, line: str, model_dict: dict) -> None:
        """Parse a [Ramp] section data line (dV/dt rise/fall)."""
        lower = line.lower()
        for prefix in ("dv/dt_r", "dv/dt_f"):
            if lower.startswith(prefix):
                rest = line.split(None, 1)
                if len(rest) > 1:
                    model_dict.setdefault("ramp", {})[prefix.replace("/", "_")] = rest[1].strip()
                return
        # R_load
        if lower.startswith("r_load"):
            rest = line.split(None, 1)
            if len(rest) > 1:
                try:
                    model_dict.setdefault("ramp", {})["r_load"] = parse_eng_notation(rest[1].strip())
                except ValueError:
                    pass

    def _parse_iv_line(self, line: str, model_dict: dict, section: str) -> None:
        """Parse an I-V curve data line (Pullup/Pulldown)."""
        parts = line.split()
        if len(parts) < 2:
            return

        # Skip comment-like lines
        if parts[0].startswith("|") or parts[0].startswith("!"):
            return

        try:
            voltage = parse_eng_notation(parts[0])
            currents = _parse_triplet(parts[1:4])
            model_dict[section].append({
                "voltage": voltage,
                **currents,
            })
        except (ValueError, IndexError):
            pass

    def _parse_waveform_line(self, line: str, waveform: dict) -> None:
        """Parse a waveform data line (Rising/Falling Waveform)."""
        parts = line.split()
        if len(parts) < 2:
            return

        # Skip comment-like lines
        if parts[0].startswith("|") or parts[0].startswith("!"):
            return

        try:
            time_val = parse_eng_notation(parts[0])
            voltages = _parse_triplet(parts[1:4])
            waveform["data"].append({
                "time": time_val,
                **voltages,
            })
        except (ValueError, IndexError):
            pass


def analyze_ibis_timing(
    model_data: dict,
    data_rate_gbps: float,
    trace_length_mm: float,
) -> dict:
    """Analyze timing from IBIS waveform data.

    Uses rising/falling waveform data to estimate rise/fall times,
    then calculates eye opening and timing margins for the given
    data rate and trace length.

    Args:
        model_data: A model dict from IBISModel.models.
        data_rate_gbps: Data rate in Gb/s.
        trace_length_mm: Trace length in mm.

    Returns:
        Dictionary with timing analysis results.
    """
    # Extract rise/fall times from waveform data
    rise_time_ps = _extract_transition_time(model_data.get("rising_waveform", []))
    fall_time_ps = _extract_transition_time(model_data.get("falling_waveform", []))

    # Unit interval
    ui_ps = 1e12 / (data_rate_gbps * 1e9) if data_rate_gbps > 0 else float("inf")

    # Propagation delay (assume FR4, Er_eff ~ 3.0)
    er_eff = 3.0
    c0 = 299792458.0  # m/s
    prop_delay_ps = (trace_length_mm * 1e-3 / c0) * math.sqrt(er_eff) * 1e12

    # Simple channel loss estimate (dB at Nyquist)
    f_nyquist_ghz = data_rate_gbps / 2.0
    # Typical FR4 loss: ~0.5 dB/inch at 1 GHz, scales as sqrt(f)
    loss_per_inch_at_1ghz = 0.5
    trace_length_inches = trace_length_mm / 25.4
    il_at_nyquist_db = loss_per_inch_at_1ghz * trace_length_inches * math.sqrt(f_nyquist_ghz)

    # Eye height estimate
    v_swing_mv = 800.0  # Default swing
    if model_data.get("rising_waveform"):
        wf = model_data["rising_waveform"][0] if model_data["rising_waveform"] else {}
        wf_data = wf.get("data", [])
        if len(wf_data) >= 2:
            v_start = wf_data[0].get("typ", 0.0)
            v_end = wf_data[-1].get("typ", 3.3)
            v_swing_mv = abs(v_end - v_start) * 1000

    h_linear = 10.0 ** (-il_at_nyquist_db / 20.0)
    eye_height_mv = v_swing_mv * h_linear
    eye_height_mv = max(eye_height_mv, 0.0)

    # Eye width estimate
    max_transition = max(rise_time_ps, fall_time_ps) if rise_time_ps > 0 and fall_time_ps > 0 else rise_time_ps or fall_time_ps
    jitter_ps = max_transition * 0.1  # 10% of transition time as DJ estimate
    eye_width_ps = ui_ps - jitter_ps - max_transition * 0.3  # Heuristic
    eye_width_ps = max(eye_width_ps, 0.0)

    # C_comp loading effect
    c_comp = model_data.get("c_comp", {})
    # parse_eng_notation stores in Farads; convert to pF
    c_comp_pf = c_comp.get("typ", 0.0) * 1e12

    # Timing margin
    timing_margin_ps = eye_width_ps - (ui_ps * 0.3)  # 30% UI minimum opening
    timing_margin_ps = max(timing_margin_ps, 0.0)

    return {
        "rise_time_ps": round(rise_time_ps, 1),
        "fall_time_ps": round(fall_time_ps, 1),
        "unit_interval_ps": round(ui_ps, 1),
        "propagation_delay_ps": round(prop_delay_ps, 1),
        "insertion_loss_at_nyquist_db": round(il_at_nyquist_db, 2),
        "eye_height_mv": round(eye_height_mv, 1),
        "eye_width_ps": round(eye_width_ps, 1),
        "timing_margin_ps": round(timing_margin_ps, 1),
        "c_comp_pf": round(c_comp_pf, 2),
        "data_rate_gbps": data_rate_gbps,
        "trace_length_mm": trace_length_mm,
        "model_type": model_data.get("model_type", "unknown"),
        "pass_fail": "PASS" if eye_height_mv > 50 and eye_width_ps > ui_ps * 0.3 else "FAIL",
    }


def _extract_transition_time(waveforms: list[dict]) -> float:
    """Extract 20-80% transition time from waveform data in picoseconds.

    Args:
        waveforms: List of waveform dicts with 'data' key containing
                   time/voltage points.

    Returns:
        Transition time in picoseconds, or 0 if insufficient data.
    """
    if not waveforms:
        return 0.0

    wf = waveforms[0] if isinstance(waveforms, list) else waveforms
    data_points = wf.get("data", [])

    if len(data_points) < 2:
        return 0.0

    # Get voltage range from typ values
    voltages = [p.get("typ", 0.0) for p in data_points if "typ" in p]
    times = [p.get("time", 0.0) for p in data_points if "time" in p]

    if len(voltages) < 2 or len(times) < 2:
        return 0.0

    v_min = float(min(voltages))
    v_max = float(max(voltages))
    v_range = v_max - v_min

    if v_range <= 0:
        return 0.0

    # Find 20% and 80% crossing times
    v_20 = v_min + 0.2 * v_range
    v_80 = v_min + 0.8 * v_range

    t_20 = _interpolate_time(data_points, v_20)
    t_80 = _interpolate_time(data_points, v_80)

    if t_20 is not None and t_80 is not None:
        transition_time_s = abs(t_80 - t_20)
        return transition_time_s * 1e12  # Convert to ps

    # Fallback: use total time span
    total_time = abs(float(times[-1]) - float(times[0]))
    return total_time * 1e12 * 0.6  # Approximate 20-80% as 60% of total


def _interpolate_time(data_points: list[dict], target_voltage: float) -> Optional[float]:
    """Interpolate time for a target voltage from waveform data.

    Args:
        data_points: List of {'time': t, 'typ': v, ...} dicts.
        target_voltage: Voltage to find crossing time for.

    Returns:
        Interpolated time, or None if crossing not found.
    """
    for i in range(len(data_points) - 1):
        v1 = float(data_points[i].get("typ", 0.0))
        v2 = float(data_points[i + 1].get("typ", 0.0))
        t1 = float(data_points[i].get("time", 0.0))
        t2 = float(data_points[i + 1].get("time", 0.0))

        # Check if target voltage is between these two points
        if (v1 <= target_voltage <= v2) or (v2 <= target_voltage <= v1):
            if abs(v2 - v1) < 1e-15:
                return t1
            # Linear interpolation
            fraction = (target_voltage - v1) / (v2 - v1)
            return t1 + fraction * (t2 - t1)

    return None

"""IBIS-driven eye diagram generation for high-speed serial links.

Parses IBIS model data (V-T waveforms, I-V curves) and convolves the
driver output with a frequency-dependent channel loss model (from S-parameter
data or analytical trace-loss) to produce a time-domain eye diagram estimate.

Supports LPDDR4, USB 2.0, and generic CMOS buffer models.

All calculations are pure Python -- no numpy dependency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# Physical constants
C0 = 299792458.0  # speed of light (m/s)
MU0 = 4.0 * math.pi * 1e-7  # permeability of free space (H/m)
SIGMA_CU = 5.8e7  # conductivity of annealed copper (S/m)


# ---------------------------------------------------------------------------
# Data classes for IBIS model and S-parameter data
# ---------------------------------------------------------------------------

@dataclass
class WaveformPoint:
    """A single (time, voltage) point with typ/min/max columns."""
    time_s: float
    typ: float
    min: Optional[float] = None
    max: Optional[float] = None


@dataclass
class IVPoint:
    """A single (voltage, current) point with typ/min/max columns."""
    voltage: float
    typ: float
    min: Optional[float] = None
    max: Optional[float] = None


@dataclass
class Waveform:
    """A waveform table from [Rising Waveform] or [Falling Waveform]."""
    r_fixture: float = 50.0
    v_fixture: float = 0.0
    v_fixture_min: Optional[float] = None
    v_fixture_max: Optional[float] = None
    data: list[WaveformPoint] = field(default_factory=list)


@dataclass
class IBISModel:
    """Parsed IBIS buffer model data.

    Holds the electrical characteristics extracted from an IBIS file:
    V-T waveforms, I-V curves, and metadata needed for eye diagram
    generation.
    """
    model_name: str = ""
    model_type: str = "i/o"  # i/o, output, input, 3-state, open_drain, etc.
    v_supply: float = 3.3
    vinl: float = 0.8
    vinh: float = 2.0
    vmeas: float = 1.5

    # Capacitance
    c_comp_typ: float = 3.0e-12
    c_comp_min: Optional[float] = None
    c_comp_max: Optional[float] = None

    # I-V curves
    pullup: list[IVPoint] = field(default_factory=list)
    pulldown: list[IVPoint] = field(default_factory=list)

    # Waveforms
    rising_waveform: list[Waveform] = field(default_factory=list)
    falling_waveform: list[Waveform] = field(default_factory=list)

    # Package parasitics
    r_pkg: float = 0.1
    l_pkg: float = 1.0e-9
    c_pkg: float = 0.5e-12

    @property
    def v_swing(self) -> float:
        """Full output voltage swing (V)."""
        if self.rising_waveform:
            wf = self.rising_waveform[0]
            voltages = [p.typ for p in wf.data]
            if voltages:
                return max(voltages) - min(voltages)
        return self.v_supply

    @property
    def rise_time_s(self) -> float:
        """20%-80% rise time extracted from rising waveform (seconds)."""
        if not self.rising_waveform or not self.rising_waveform[0].data:
            # Default: 1 ns rise time
            return 1.0e-9
        return _extract_edge_time(self.rising_waveform[0].data, rising=True)

    @property
    def fall_time_s(self) -> float:
        """20%-80% fall time extracted from falling waveform (seconds)."""
        if not self.falling_waveform or not self.falling_waveform[0].data:
            return self.rise_time_s
        return _extract_edge_time(self.falling_waveform[0].data, rising=False)

    def output_impedance(self, state: str = "high") -> float:
        """Estimate output impedance from I-V curves.

        Uses the slope of the pullup or pulldown curve near the operating
        point to estimate Ron.

        Args:
            state: "high" for pullup impedance, "low" for pulldown.

        Returns:
            Estimated impedance in ohms.
        """
        iv_data = self.pullup if state == "high" else self.pulldown
        if len(iv_data) < 2:
            return 50.0  # default

        # Find two points near mid-range and compute slope
        n = len(iv_data)
        mid = n // 2
        i1 = max(0, mid - 1)
        i2 = min(n - 1, mid + 1)
        if i1 == i2:
            return 50.0

        dv = iv_data[i2].voltage - iv_data[i1].voltage
        di = iv_data[i2].typ - iv_data[i1].typ
        if abs(di) < 1e-15:
            return 50.0
        return abs(dv / di)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return {
            "model_name": self.model_name,
            "model_type": self.model_type,
            "v_supply": self.v_supply,
            "v_swing": round(self.v_swing, 4),
            "rise_time_ps": round(self.rise_time_s * 1e12, 1),
            "fall_time_ps": round(self.fall_time_s * 1e12, 1),
            "output_impedance_high_ohm": round(self.output_impedance("high"), 2),
            "output_impedance_low_ohm": round(self.output_impedance("low"), 2),
            "c_comp_pF": round(self.c_comp_typ * 1e12, 3),
            "num_rising_waveforms": len(self.rising_waveform),
            "num_falling_waveforms": len(self.falling_waveform),
            "num_pullup_points": len(self.pullup),
            "num_pulldown_points": len(self.pulldown),
        }


@dataclass
class SParameterData:
    """Parsed S-parameter (Touchstone) data for channel loss modeling.

    Stores frequency-domain S21 (insertion loss) data for convolution
    with driver waveform.
    """
    frequencies_hz: list[float] = field(default_factory=list)
    s21_complex: list[complex] = field(default_factory=list)
    s11_complex: list[complex] = field(default_factory=list)
    reference_impedance: float = 50.0
    port_count: int = 2

    @property
    def num_points(self) -> int:
        return len(self.frequencies_hz)

    @property
    def freq_range_hz(self) -> tuple[float, float]:
        if not self.frequencies_hz:
            return (0.0, 0.0)
        return (self.frequencies_hz[0], self.frequencies_hz[-1])

    def s21_db(self) -> list[float]:
        """Insertion loss in dB (negative values = loss)."""
        result = []
        for s in self.s21_complex:
            mag = abs(s)
            if mag > 0:
                result.append(20.0 * math.log10(mag))
            else:
                result.append(-100.0)
        return result

    def s21_magnitude(self) -> list[float]:
        """Insertion loss magnitude (linear)."""
        return [abs(s) for s in self.s21_complex]

    def interpolate_s21_mag(self, freq_hz: float) -> float:
        """Linearly interpolate S21 magnitude at a given frequency."""
        if not self.frequencies_hz or not self.s21_complex:
            return 1.0  # pass-through
        if freq_hz <= self.frequencies_hz[0]:
            return abs(self.s21_complex[0])
        if freq_hz >= self.frequencies_hz[-1]:
            return abs(self.s21_complex[-1])
        # Find bracketing indices
        for i in range(len(self.frequencies_hz) - 1):
            f0 = self.frequencies_hz[i]
            f1 = self.frequencies_hz[i + 1]
            if f0 <= freq_hz <= f1:
                t = (freq_hz - f0) / (f1 - f0) if f1 > f0 else 0.0
                m0 = abs(self.s21_complex[i])
                m1 = abs(self.s21_complex[i + 1])
                return m0 + t * (m1 - m0)
        return abs(self.s21_complex[-1])

    def to_dict(self) -> dict:
        return {
            "num_points": self.num_points,
            "freq_range_hz": self.freq_range_hz,
            "reference_impedance": self.reference_impedance,
            "port_count": self.port_count,
        }


# ---------------------------------------------------------------------------
# Eye diagram result
# ---------------------------------------------------------------------------

@dataclass
class EyeDiagramResult:
    """Result of IBIS-driven eye diagram generation."""
    eye_height_mv: float = 0.0
    eye_width_ps: float = 0.0
    eye_width_ui: float = 0.0
    unit_interval_ps: float = 0.0
    data_rate_gbps: float = 0.0

    # Driver info
    rise_time_ps: float = 0.0
    fall_time_ps: float = 0.0
    v_swing_mv: float = 0.0
    output_impedance_ohm: float = 50.0

    # Channel info
    insertion_loss_at_nyquist_db: float = 0.0
    channel_bandwidth_ghz: float = 0.0

    # ISI / jitter
    isi_penalty_percent: float = 0.0
    deterministic_jitter_ps: float = 0.0
    random_jitter_rms_ps: float = 1.0
    total_jitter_ber12_ps: float = 0.0

    # Verdict
    pass_fail: str = "PASS"
    protocol: str = "generic"
    recommendations: list[str] = field(default_factory=list)

    # Time-domain eye waveform samples (optional)
    eye_time_ps: list[float] = field(default_factory=list)
    eye_voltage_mv: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "eye_height_mv": round(self.eye_height_mv, 1),
            "eye_width_ps": round(self.eye_width_ps, 1),
            "eye_width_ui": round(self.eye_width_ui, 3),
            "unit_interval_ps": round(self.unit_interval_ps, 1),
            "data_rate_gbps": self.data_rate_gbps,
            "rise_time_ps": round(self.rise_time_ps, 1),
            "fall_time_ps": round(self.fall_time_ps, 1),
            "v_swing_mv": round(self.v_swing_mv, 1),
            "output_impedance_ohm": round(self.output_impedance_ohm, 2),
            "insertion_loss_at_nyquist_db": round(self.insertion_loss_at_nyquist_db, 2),
            "channel_bandwidth_ghz": round(self.channel_bandwidth_ghz, 3),
            "isi_penalty_percent": round(self.isi_penalty_percent, 1),
            "deterministic_jitter_ps": round(self.deterministic_jitter_ps, 1),
            "random_jitter_rms_ps": round(self.random_jitter_rms_ps, 2),
            "total_jitter_ber12_ps": round(self.total_jitter_ber12_ps, 1),
            "pass_fail": self.pass_fail,
            "protocol": self.protocol,
            "recommendations": self.recommendations,
        }


# ---------------------------------------------------------------------------
# Protocol specifications for pass/fail thresholds
# ---------------------------------------------------------------------------

_PROTOCOL_SPECS: dict[str, dict] = {
    "lpddr4": {
        "data_rate_gbps": 4.267,
        "v_swing_mv": 400.0,
        "min_eye_height_mv": 50.0,
        "min_eye_width_ui": 0.25,
        "v_supply": 1.1,
        "rise_time_ps": 200.0,
    },
    "usb2": {
        "data_rate_gbps": 0.48,
        "v_swing_mv": 400.0,
        "min_eye_height_mv": 100.0,
        "min_eye_width_ui": 0.40,
        "v_supply": 3.3,
        "rise_time_ps": 4000.0,
    },
    "generic": {
        "data_rate_gbps": 1.0,
        "v_swing_mv": 800.0,
        "min_eye_height_mv": 100.0,
        "min_eye_width_ui": 0.30,
        "v_supply": 3.3,
        "rise_time_ps": 500.0,
    },
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _extract_edge_time(data: list[WaveformPoint], rising: bool) -> float:
    """Extract 20%-80% edge time from waveform data points.

    Args:
        data: List of WaveformPoint sorted by time.
        rising: True for rising edge, False for falling.

    Returns:
        Edge time in seconds.
    """
    if len(data) < 2:
        return 1.0e-9

    voltages = [p.typ for p in data]
    v_min = min(voltages)
    v_max = max(voltages)
    v_range = v_max - v_min
    if v_range < 1e-6:
        return 1.0e-9  # flat waveform

    v20 = v_min + 0.2 * v_range
    v80 = v_min + 0.8 * v_range

    t20 = None
    t80 = None

    for i in range(len(data) - 1):
        va = data[i].typ
        vb = data[i + 1].typ
        ta = data[i].time_s
        tb = data[i + 1].time_s

        if rising:
            # Find crossing of v20 (going up)
            if t20 is None and va <= v20 <= vb and vb > va:
                frac = (v20 - va) / (vb - va) if vb != va else 0.0
                t20 = ta + frac * (tb - ta)
            # Find crossing of v80 (going up)
            if t80 is None and va <= v80 <= vb and vb > va:
                frac = (v80 - va) / (vb - va) if vb != va else 0.0
                t80 = ta + frac * (tb - ta)
        else:
            # For falling waveform: voltage goes from high to low
            if t80 is None and va >= v80 >= vb and va > vb:
                frac = (va - v80) / (va - vb) if va != vb else 0.0
                t80 = ta + frac * (tb - ta)
            if t20 is None and va >= v20 >= vb and va > vb:
                frac = (va - v20) / (va - vb) if va != vb else 0.0
                t20 = ta + frac * (tb - ta)

    if t20 is not None and t80 is not None:
        return abs(t80 - t20)

    # Fallback: use total waveform duration * 0.6
    duration = data[-1].time_s - data[0].time_s
    return max(duration * 0.6, 1.0e-12)


def _convolve_1d(signal: list[float], kernel: list[float]) -> list[float]:
    """Discrete linear convolution of two 1D sequences.

    Pure-Python implementation (no numpy). Returns a list of length
    len(signal) + len(kernel) - 1.
    """
    ns = len(signal)
    nk = len(kernel)
    out_len = ns + nk - 1
    result = [0.0] * out_len
    for i in range(ns):
        si = signal[i]
        if si == 0.0:
            continue
        for j in range(nk):
            result[i + j] += si * kernel[j]
    return result


def _generate_bit_pattern(num_bits: int = 64) -> list[int]:
    """Generate a pseudo-random bit sequence using LFSR.

    Uses a 7-bit LFSR (x^7 + x^6 + 1) for a maximal-length sequence.
    """
    bits: list[int] = []
    state = 0x7F  # initial seed (all ones)
    for _ in range(num_bits):
        bit = state & 1
        bits.append(bit)
        feedback = ((state >> 6) ^ (state >> 5)) & 1
        state = ((state >> 1) | (feedback << 6)) & 0x7F
    return bits


def _channel_impulse_from_sparam(
    sparam: SParameterData,
    num_time_points: int,
    dt_s: float,
) -> list[float]:
    """Compute approximate channel impulse response from S21 data.

    Uses inverse DFT approximation to convert frequency-domain S21
    to a time-domain impulse response.
    """
    h = [0.0] * num_time_points

    if not sparam.frequencies_hz or not sparam.s21_complex:
        # Pass-through channel
        if num_time_points > 0:
            h[0] = 1.0
        return h

    # Approximate IDFT using real part of sum
    for n in range(num_time_points):
        t = n * dt_s
        val = 0.0
        for k in range(len(sparam.frequencies_hz)):
            f = sparam.frequencies_hz[k]
            s21 = sparam.s21_complex[k]
            mag = abs(s21)
            phase = math.atan2(s21.imag, s21.real)
            # Add linear phase from propagation delay
            val += mag * math.cos(2.0 * math.pi * f * t + phase)
        # Normalize by number of frequency points
        if len(sparam.frequencies_hz) > 0:
            val /= len(sparam.frequencies_hz)
        h[n] = val

    # Normalize impulse response so energy is preserved
    energy = sum(abs(x) for x in h)
    if energy > 0:
        scale = 1.0 / energy
        h = [x * scale for x in h]

    return h


def _channel_impulse_from_loss_db(
    loss_at_nyquist_db: float,
    num_time_points: int,
) -> list[float]:
    """Create a simplified channel impulse response from insertion loss.

    Models the channel as a single-pole low-pass whose 3dB point
    corresponds approximately to the given Nyquist loss.
    """
    h = [0.0] * num_time_points
    if num_time_points == 0:
        return h

    if loss_at_nyquist_db <= 0:
        # Lossless channel: impulse at t=0
        h[0] = 1.0
        return h

    # Main cursor amplitude from insertion loss
    h0 = 10.0 ** (-loss_at_nyquist_db / 20.0)
    h0 = min(h0, 1.0)
    decay = 1.0 - h0

    # Exponential decay model for ISI taps
    h[0] = h0
    for i in range(1, num_time_points):
        h[i] = h0 * (decay ** i)

    # Normalize
    total = sum(h)
    if total > 0:
        h = [x / total for x in h]

    return h


# ---------------------------------------------------------------------------
# IBIS waveform parsing from dict structures
# ---------------------------------------------------------------------------

def parse_ibis_waveform(waveform_data: list[dict]) -> list[WaveformPoint]:
    """Parse a list of waveform dicts (as from IBISParser) into WaveformPoint.

    Each dict should have 'time' and 'typ' keys, optionally 'min' and 'max'.
    Time values can be float or string (engineering notation).

    Args:
        waveform_data: List of dicts with keys 'time', 'typ', 'min', 'max'.

    Returns:
        List of WaveformPoint dataclass instances.
    """
    points: list[WaveformPoint] = []
    for entry in waveform_data:
        t = _to_float(entry.get("time", 0.0))
        typ = _to_float(entry.get("typ", 0.0))
        mn = _to_float_or_none(entry.get("min"))
        mx = _to_float_or_none(entry.get("max"))
        points.append(WaveformPoint(time_s=t, typ=typ, min=mn, max=mx))
    return points


def parse_ibis_iv_curve(iv_data: list[dict]) -> list[IVPoint]:
    """Parse a list of I-V curve dicts into IVPoint instances.

    Each dict should have 'voltage' and 'typ' keys, optionally 'min', 'max'.

    Args:
        iv_data: List of dicts with keys 'voltage', 'typ', 'min', 'max'.

    Returns:
        List of IVPoint dataclass instances.
    """
    points: list[IVPoint] = []
    for entry in iv_data:
        v = _to_float(entry.get("voltage", 0.0))
        typ = _to_float(entry.get("typ", 0.0))
        mn = _to_float_or_none(entry.get("min"))
        mx = _to_float_or_none(entry.get("max"))
        points.append(IVPoint(voltage=v, typ=typ, min=mn, max=mx))
    return points


def _to_float(value) -> float:
    """Convert a value to float, supporting strings with engineering notation."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return 0.0
        try:
            return float(value)
        except ValueError:
            # Try engineering notation
            return _parse_eng_simple(value)
    return 0.0


def _to_float_or_none(value) -> Optional[float]:
    """Convert value to float or return None if missing/empty."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.strip()
        if not value or value.lower() == "na":
            return None
        try:
            return float(value)
        except ValueError:
            return _parse_eng_simple(value)
    return None


def _parse_eng_simple(s: str) -> float:
    """Simple engineering notation parser for suffixed values."""
    suffixes = {
        "T": 1e12, "t": 1e12, "G": 1e9, "g": 1e9,
        "M": 1e6, "k": 1e3, "K": 1e3,
        "m": 1e-3, "u": 1e-6, "U": 1e-6,
        "n": 1e-9, "N": 1e-9, "p": 1e-12, "P": 1e-12,
        "f": 1e-15, "F": 1e-15,
    }
    s = s.strip()
    # Strip trailing unit letters (A, V, H, s, etc.)
    while s and s[-1].isalpha() and s[-1] not in suffixes:
        s = s[:-1]
    if not s:
        return 0.0
    if s[-1] in suffixes:
        return float(s[:-1]) * suffixes[s[-1]]
    return float(s)


# ---------------------------------------------------------------------------
# Main generator class
# ---------------------------------------------------------------------------

class IBISEyeGenerator:
    """IBIS-driven eye diagram generator.

    Combines IBIS buffer model data with channel loss (from S-parameters
    or analytical models) to produce time-domain eye diagram estimates.

    Usage::

        gen = IBISEyeGenerator()
        model = gen.parse_ibis_model(ibis_dict)
        sparam = gen.parse_sparam_data(freq_hz, s21_complex)
        result = gen.generate_eye(model, data_rate_gbps=4.267, sparam=sparam)
    """

    def __init__(self) -> None:
        self._num_bits = 64
        self._samples_per_bit = 32

    # ----- IBIS model construction -----

    def parse_ibis_model(
        self,
        model_dict: dict,
        *,
        model_name: str = "",
    ) -> IBISModel:
        """Construct an IBISModel from a dict (as from IBISParser.models[name]).

        Args:
            model_dict: Dictionary with IBIS model fields (pullup, pulldown,
                        rising_waveform, falling_waveform, etc.).
            model_name: Optional model name override.

        Returns:
            Populated IBISModel dataclass.
        """
        model = IBISModel()
        model.model_name = model_name or model_dict.get("model_name", "")
        model.model_type = model_dict.get("model_type", "i/o")

        # Voltage levels
        model.vinl = _to_float(model_dict.get("vinl", 0.8))
        model.vinh = _to_float(model_dict.get("vinh", 2.0))
        model.vmeas = _to_float(model_dict.get("vmeas", 1.5))

        # C_comp
        c_comp = model_dict.get("c_comp", {})
        if isinstance(c_comp, dict):
            model.c_comp_typ = _to_float(c_comp.get("typ", 3e-12))
            model.c_comp_min = _to_float_or_none(c_comp.get("min"))
            model.c_comp_max = _to_float_or_none(c_comp.get("max"))
        else:
            model.c_comp_typ = _to_float(c_comp)

        # I-V curves
        pullup_data = model_dict.get("pullup", [])
        if pullup_data:
            model.pullup = parse_ibis_iv_curve(pullup_data)

        pulldown_data = model_dict.get("pulldown", [])
        if pulldown_data:
            model.pulldown = parse_ibis_iv_curve(pulldown_data)

        # Waveforms
        for wf_data in model_dict.get("rising_waveform", []):
            wf = Waveform(
                r_fixture=_to_float(wf_data.get("r_fixture", 50.0)),
                v_fixture=_to_float(wf_data.get("v_fixture", 0.0)),
            )
            wf.data = parse_ibis_waveform(wf_data.get("data", []))
            model.rising_waveform.append(wf)

        for wf_data in model_dict.get("falling_waveform", []):
            wf = Waveform(
                r_fixture=_to_float(wf_data.get("r_fixture", 50.0)),
                v_fixture=_to_float(wf_data.get("v_fixture", 0.0)),
            )
            wf.data = parse_ibis_waveform(wf_data.get("data", []))
            model.falling_waveform.append(wf)

        # Supply voltage: infer from waveform or use v_fixture
        if model.rising_waveform:
            wf = model.rising_waveform[0]
            if wf.v_fixture > 0:
                model.v_supply = wf.v_fixture
            elif wf.data:
                model.v_supply = max(p.typ for p in wf.data)

        return model

    def build_ibis_model(
        self,
        *,
        rising_waveform: list[WaveformPoint],
        falling_waveform: Optional[list[WaveformPoint]] = None,
        pullup: Optional[list[IVPoint]] = None,
        pulldown: Optional[list[IVPoint]] = None,
        v_supply: float = 3.3,
        model_name: str = "custom",
        model_type: str = "i/o",
        r_fixture: float = 50.0,
        c_comp: float = 3.0e-12,
    ) -> IBISModel:
        """Build an IBISModel directly from waveform/IV data.

        Convenience method when not parsing from an IBIS dict.
        """
        model = IBISModel(
            model_name=model_name,
            model_type=model_type,
            v_supply=v_supply,
            c_comp_typ=c_comp,
        )

        wf_rise = Waveform(r_fixture=r_fixture, v_fixture=v_supply)
        wf_rise.data = rising_waveform
        model.rising_waveform.append(wf_rise)

        if falling_waveform:
            wf_fall = Waveform(r_fixture=r_fixture, v_fixture=v_supply)
            wf_fall.data = falling_waveform
            model.falling_waveform.append(wf_fall)

        if pullup:
            model.pullup = pullup
        if pulldown:
            model.pulldown = pulldown

        return model

    # ----- S-parameter channel data -----

    def parse_sparam_data(
        self,
        frequencies_hz: list[float],
        s21_complex: list[complex],
        *,
        s11_complex: Optional[list[complex]] = None,
        reference_impedance: float = 50.0,
    ) -> SParameterData:
        """Create SParameterData from frequency/S21 arrays.

        Args:
            frequencies_hz: Frequency points in Hz.
            s21_complex: Complex S21 values at each frequency.
            s11_complex: Optional complex S11 values.
            reference_impedance: Reference impedance (ohms).

        Returns:
            SParameterData dataclass.
        """
        sparam = SParameterData(
            frequencies_hz=list(frequencies_hz),
            s21_complex=list(s21_complex),
            reference_impedance=reference_impedance,
        )
        if s11_complex:
            sparam.s11_complex = list(s11_complex)
        return sparam

    def create_lossy_channel(
        self,
        loss_at_nyquist_db: float,
        data_rate_gbps: float,
        *,
        num_points: int = 50,
    ) -> SParameterData:
        """Create synthetic S-parameter data for a lossy channel.

        Models the channel as a frequency-dependent loss that reaches
        the specified value at the Nyquist frequency.

        Args:
            loss_at_nyquist_db: Insertion loss at Nyquist (dB, positive).
            data_rate_gbps: Data rate in Gb/s.
            num_points: Number of frequency points.

        Returns:
            SParameterData with synthetic S21.
        """
        f_nyquist = data_rate_gbps * 1e9 / 2.0
        f_max = f_nyquist * 3.0  # extend to 3rd harmonic

        freqs = []
        s21_vals = []

        for i in range(num_points):
            f = f_max * (i + 1) / num_points
            # sqrt(f) loss model (typical of PCB channels)
            if f_nyquist > 0 and loss_at_nyquist_db > 0:
                loss_db = loss_at_nyquist_db * math.sqrt(f / f_nyquist)
            else:
                loss_db = 0.0
            mag = 10.0 ** (-loss_db / 20.0)
            # Add linear phase (propagation delay ~ 6 ns/m for FR4)
            phase = -2.0 * math.pi * f * 1e-9  # simple delay
            s21 = complex(mag * math.cos(phase), mag * math.sin(phase))
            freqs.append(f)
            s21_vals.append(s21)

        return SParameterData(
            frequencies_hz=freqs,
            s21_complex=s21_vals,
        )

    # ----- Protocol-specific model factories -----

    def create_lpddr4_model(
        self,
        *,
        rise_time_ps: float = 200.0,
        v_supply: float = 1.1,
    ) -> IBISModel:
        """Create a synthetic LPDDR4 buffer model.

        LPDDR4 uses VDDQ=1.1V, 4.267 Gbps per pin, with fast edge rates.
        """
        v_high = v_supply
        t_rise = rise_time_ps * 1e-12
        n_pts = 10
        dt = t_rise / 6.0  # enough time points to cover 20-80%

        rising = []
        falling = []
        for i in range(n_pts):
            t = i * dt
            # Sigmoid waveform
            x = (t - t_rise * 0.5) / (t_rise * 0.167)  # centered on 50%
            v = v_high / (1.0 + math.exp(-x))
            rising.append(WaveformPoint(time_s=t, typ=v))
            falling.append(WaveformPoint(time_s=t, typ=v_high - v))

        # I-V curves: LPDDR4 low-voltage swing
        pulldown = []
        pullup = []
        ron = 40.0  # typical LPDDR4 Ron
        for v in [x * 0.1 for x in range(-5, 16)]:
            pulldown.append(IVPoint(voltage=v, typ=v / ron))
            pullup.append(IVPoint(voltage=v, typ=(v - v_supply) / ron))

        return self.build_ibis_model(
            rising_waveform=rising,
            falling_waveform=falling,
            pullup=pullup,
            pulldown=pulldown,
            v_supply=v_supply,
            model_name="LPDDR4_DQ",
            model_type="i/o",
            r_fixture=50.0,
            c_comp=1.5e-12,
        )

    def create_usb2_model(
        self,
        *,
        rise_time_ps: float = 4000.0,
        v_supply: float = 3.3,
    ) -> IBISModel:
        """Create a synthetic USB 2.0 Full-Speed buffer model.

        USB 2.0 FS runs at 12 Mbps (HS at 480 Mbps) with 3.3V signaling.
        Edge rates are relatively slow compared to LPDDR4.
        """
        v_high = v_supply
        t_rise = rise_time_ps * 1e-12
        n_pts = 10
        dt = t_rise / 6.0

        rising = []
        falling = []
        for i in range(n_pts):
            t = i * dt
            x = (t - t_rise * 0.5) / (t_rise * 0.167)
            v = v_high / (1.0 + math.exp(-x))
            rising.append(WaveformPoint(time_s=t, typ=v))
            falling.append(WaveformPoint(time_s=t, typ=v_high - v))

        # USB 2.0 driver impedance: ~45 ohm
        ron = 45.0
        pulldown = []
        pullup = []
        for v_val in [x * 0.3 for x in range(-5, 16)]:
            pulldown.append(IVPoint(voltage=v_val, typ=v_val / ron))
            pullup.append(IVPoint(voltage=v_val, typ=(v_val - v_supply) / ron))

        return self.build_ibis_model(
            rising_waveform=rising,
            falling_waveform=falling,
            pullup=pullup,
            pulldown=pulldown,
            v_supply=v_supply,
            model_name="USB2_FS",
            model_type="i/o",
            r_fixture=50.0,
            c_comp=5.0e-12,
        )

    def create_generic_cmos_model(
        self,
        *,
        v_supply: float = 3.3,
        rise_time_ps: float = 500.0,
        ron: float = 50.0,
    ) -> IBISModel:
        """Create a generic CMOS output buffer model."""
        v_high = v_supply
        t_rise = rise_time_ps * 1e-12
        n_pts = 10
        dt = t_rise / 6.0

        rising = []
        falling = []
        for i in range(n_pts):
            t = i * dt
            x = (t - t_rise * 0.5) / (t_rise * 0.167)
            v = v_high / (1.0 + math.exp(-x))
            rising.append(WaveformPoint(time_s=t, typ=v))
            falling.append(WaveformPoint(time_s=t, typ=v_high - v))

        pulldown = []
        pullup = []
        for v_val in [x * 0.3 for x in range(-5, 16)]:
            pulldown.append(IVPoint(voltage=v_val, typ=v_val / ron))
            pullup.append(IVPoint(voltage=v_val, typ=(v_val - v_supply) / ron))

        return self.build_ibis_model(
            rising_waveform=rising,
            falling_waveform=falling,
            pullup=pullup,
            pulldown=pulldown,
            v_supply=v_supply,
            model_name="GENERIC_CMOS",
            model_type="output",
            r_fixture=50.0,
            c_comp=3.0e-12,
        )

    # ----- Eye diagram generation -----

    def generate_eye(
        self,
        ibis_model: IBISModel,
        data_rate_gbps: float,
        *,
        sparam: Optional[SParameterData] = None,
        channel_loss_db: Optional[float] = None,
        protocol: Optional[str] = None,
    ) -> EyeDiagramResult:
        """Generate an eye diagram from IBIS model and channel data.

        The method:
        1. Builds a time-domain bit waveform from the IBIS rising/falling edges
        2. Computes the channel impulse response (from S-params or loss model)
        3. Convolves the driver waveform with the channel impulse response
        4. Folds the result into a 2-UI eye diagram
        5. Measures eye height and width

        Args:
            ibis_model: Parsed IBIS buffer model.
            data_rate_gbps: Data rate in Gb/s (NRZ assumed).
            sparam: Optional S-parameter data for channel loss.
            channel_loss_db: Alternative: insertion loss at Nyquist (dB).
                             Ignored if sparam is provided.
            protocol: Protocol name for thresholds (lpddr4, usb2, generic).

        Returns:
            EyeDiagramResult with metrics and optional waveform data.
        """
        proto_key = (protocol or "generic").lower().replace("-", "").replace(" ", "_")
        proto_key = proto_key.replace("usb_2.0", "usb2").replace("usb2.0", "usb2")
        spec = _PROTOCOL_SPECS.get(proto_key, _PROTOCOL_SPECS["generic"])

        # Basic timing
        ui_s = 1.0 / (data_rate_gbps * 1e9)
        ui_ps = ui_s * 1e12
        f_nyquist = data_rate_gbps * 1e9 / 2.0

        # Driver characteristics
        v_swing = ibis_model.v_swing * 1e3  # V -> mV
        if v_swing < 1.0:
            v_swing = spec["v_swing_mv"]
        rise_time_s = ibis_model.rise_time_s
        fall_time_s = ibis_model.fall_time_s
        z_out = ibis_model.output_impedance("high")

        # Samples per bit and impulse response length
        spb = self._samples_per_bit
        dt = ui_s / spb

        # -- Step 1: Build bit pattern waveform --
        bits = _generate_bit_pattern(self._num_bits)
        waveform = self._build_bit_waveform(ibis_model, bits, spb, dt)

        # -- Step 2: Channel impulse response --
        num_taps = spb * 4  # 4 UI of ISI
        if sparam is not None and sparam.num_points > 0:
            h = _channel_impulse_from_sparam(sparam, num_taps, dt)
            # Compute IL at Nyquist from S-params
            s21_at_nyquist = sparam.interpolate_s21_mag(f_nyquist)
            if s21_at_nyquist > 0:
                il_at_nyquist_db = -20.0 * math.log10(s21_at_nyquist)
            else:
                il_at_nyquist_db = 60.0
        elif channel_loss_db is not None and channel_loss_db > 0:
            h = _channel_impulse_from_loss_db(channel_loss_db, num_taps)
            il_at_nyquist_db = channel_loss_db
        else:
            # Lossless channel
            h = [0.0] * num_taps
            h[0] = 1.0
            il_at_nyquist_db = 0.0

        # -- Step 3: Convolve driver waveform with channel impulse --
        convolved = _convolve_1d(waveform, h)

        # -- Step 4: Fold into 2-UI eye --
        eye_samples = spb * 2  # 2 UI wide
        eye_time_ps, eye_traces = self._fold_to_eye(convolved, spb, eye_samples)

        # -- Step 5: Measure eye opening --
        eye_height_mv, eye_width_ps = self._measure_eye(
            eye_traces, eye_time_ps, v_swing, ui_ps
        )

        # Jitter analysis
        rise_time_ps = rise_time_s * 1e12
        fall_time_ps = fall_time_s * 1e12

        # ISI penalty
        if il_at_nyquist_db > 0:
            h0 = 10.0 ** (-il_at_nyquist_db / 20.0)
            h0 = min(h0, 1.0)
            decay = 1.0 - h0
            tail = sum(h0 * (decay ** k) for k in range(1, 6))
            isi_penalty = tail / h0 if h0 > 0 else 0.0
            isi_penalty = min(isi_penalty, 0.95)
        else:
            isi_penalty = 0.0

        # Deterministic jitter
        dj_isi_ps = isi_penalty * ui_ps * 0.5
        dj_rise_ps = max(0.0, max(rise_time_ps, fall_time_ps) - ui_ps) * 0.5
        dj_total_ps = dj_isi_ps + dj_rise_ps

        # Random jitter
        rj_rms_ps = 1.0 + 0.3 * il_at_nyquist_db

        # Total jitter at BER=1e-12
        n_ber12 = 7.03
        tj_ps = dj_total_ps + 2.0 * n_ber12 * rj_rms_ps

        # Refine eye width from jitter
        eye_width_ps_jitter = ui_ps - tj_ps
        eye_width_ps = min(eye_width_ps, max(eye_width_ps_jitter, 0.0))

        eye_width_ui = eye_width_ps / ui_ps if ui_ps > 0 else 0.0

        # Channel bandwidth (3 dB point estimate)
        if il_at_nyquist_db > 0:
            # f_3dB ~ f_nyquist * (3.0 / IL_at_nyquist)
            bw_ghz = f_nyquist * (3.0 / max(il_at_nyquist_db, 0.1)) / 1e9
        else:
            bw_ghz = f_nyquist * 10.0 / 1e9  # effectively unlimited

        # -- Pass / Fail --
        min_height = spec["min_eye_height_mv"]
        min_width_ui = spec["min_eye_width_ui"]

        height_pass = eye_height_mv >= min_height
        width_pass = eye_width_ui >= min_width_ui
        pass_fail = "PASS" if (height_pass and width_pass) else "FAIL"

        # Recommendations
        recommendations: list[str] = []
        if not height_pass:
            recommendations.append(
                f"Eye height {eye_height_mv:.1f} mV < {min_height:.0f} mV limit. "
                "Consider lower-loss laminate or shorter trace."
            )
        if not width_pass:
            recommendations.append(
                f"Eye width {eye_width_ui:.3f} UI < {min_width_ui:.2f} UI limit. "
                "Reduce jitter or shorten trace."
            )
        if il_at_nyquist_db > 10:
            recommendations.append(
                f"Channel loss at Nyquist ({il_at_nyquist_db:.1f} dB) is high. "
                "Consider equalization (CTLE/DFE)."
            )
        if isi_penalty > 0.3:
            recommendations.append(
                f"ISI penalty {isi_penalty * 100:.0f}% -- equalization recommended."
            )

        # Flatten eye_traces for output (just concatenate all traces)
        flat_voltage: list[float] = []
        for trace in eye_traces:
            flat_voltage.extend(trace)

        return EyeDiagramResult(
            eye_height_mv=round(eye_height_mv, 1),
            eye_width_ps=round(eye_width_ps, 1),
            eye_width_ui=round(eye_width_ui, 3),
            unit_interval_ps=round(ui_ps, 1),
            data_rate_gbps=data_rate_gbps,
            rise_time_ps=round(rise_time_ps, 1),
            fall_time_ps=round(fall_time_ps, 1),
            v_swing_mv=round(v_swing, 1),
            output_impedance_ohm=round(z_out, 2),
            insertion_loss_at_nyquist_db=round(il_at_nyquist_db, 2),
            channel_bandwidth_ghz=round(bw_ghz, 3),
            isi_penalty_percent=round(isi_penalty * 100, 1),
            deterministic_jitter_ps=round(dj_total_ps, 1),
            random_jitter_rms_ps=round(rj_rms_ps, 2),
            total_jitter_ber12_ps=round(tj_ps, 1),
            pass_fail=pass_fail,
            protocol=proto_key,
            recommendations=recommendations,
            eye_time_ps=eye_time_ps,
            eye_voltage_mv=flat_voltage,
        )

    # ----- Internal methods -----

    def _build_bit_waveform(
        self,
        model: IBISModel,
        bits: list[int],
        samples_per_bit: int,
        dt: float,
    ) -> list[float]:
        """Build time-domain waveform from bit pattern and IBIS edges.

        Uses the rising/falling waveform shapes from the IBIS model to
        construct transitions between bits.
        """
        total_samples = len(bits) * samples_per_bit
        waveform = [0.0] * total_samples

        v_high = model.v_supply
        v_low = 0.0

        # Precompute normalized edge shapes (0 to 1 over samples_per_bit)
        rise_shape = self._normalize_edge(model, rising=True, num_samples=samples_per_bit)
        fall_shape = self._normalize_edge(model, rising=False, num_samples=samples_per_bit)

        current_v = v_low if bits[0] == 0 else v_high

        for bit_idx, bit in enumerate(bits):
            target_v = v_high if bit == 1 else v_low
            start = bit_idx * samples_per_bit

            if target_v > current_v:
                # Rising transition
                for s in range(samples_per_bit):
                    frac = rise_shape[s]
                    waveform[start + s] = current_v + frac * (target_v - current_v)
            elif target_v < current_v:
                # Falling transition
                for s in range(samples_per_bit):
                    frac = fall_shape[s]
                    waveform[start + s] = current_v - frac * (current_v - target_v)
            else:
                # Same level
                for s in range(samples_per_bit):
                    waveform[start + s] = current_v

            current_v = target_v

        # Convert to mV
        return [v * 1e3 for v in waveform]

    def _normalize_edge(
        self,
        model: IBISModel,
        rising: bool,
        num_samples: int,
    ) -> list[float]:
        """Normalize waveform edge to [0, 1] over num_samples points.

        Uses the IBIS rising or falling waveform data if available,
        otherwise uses a sigmoid approximation.
        """
        wf_list = model.rising_waveform if rising else model.falling_waveform

        if wf_list and wf_list[0].data and len(wf_list[0].data) >= 2:
            data = wf_list[0].data
            voltages = [p.typ for p in data]
            v_min = min(voltages)
            v_max = max(voltages)
            v_range = v_max - v_min

            if v_range < 1e-9:
                # Flat waveform
                return [1.0] * num_samples

            times = [p.time_s for p in data]
            t_start = times[0]
            t_end = times[-1]
            t_range = t_end - t_start
            if t_range <= 0:
                return [1.0] * num_samples

            # Resample waveform to num_samples points
            shape = []
            for s in range(num_samples):
                t = t_start + (s / max(num_samples - 1, 1)) * t_range
                # Linear interpolation in waveform data
                v = self._interp_waveform(data, t)
                if rising:
                    frac = (v - v_min) / v_range
                else:
                    frac = (v_max - v) / v_range
                frac = max(0.0, min(1.0, frac))
                shape.append(frac)
            return shape

        # Fallback: sigmoid edge
        edge_time = model.rise_time_s if rising else model.fall_time_s
        shape = []
        for s in range(num_samples):
            # Map sample index to time centered on edge
            t_frac = s / max(num_samples - 1, 1)  # 0..1
            x = (t_frac - 0.5) * 12.0  # sigmoid steepness
            frac = 1.0 / (1.0 + math.exp(-x))
            shape.append(frac)
        return shape

    def _interp_waveform(self, data: list[WaveformPoint], t: float) -> float:
        """Linear interpolation of waveform data at time t."""
        if not data:
            return 0.0
        if t <= data[0].time_s:
            return data[0].typ
        if t >= data[-1].time_s:
            return data[-1].typ
        for i in range(len(data) - 1):
            if data[i].time_s <= t <= data[i + 1].time_s:
                dt = data[i + 1].time_s - data[i].time_s
                if dt <= 0:
                    return data[i].typ
                frac = (t - data[i].time_s) / dt
                return data[i].typ + frac * (data[i + 1].typ - data[i].typ)
        return data[-1].typ

    def _fold_to_eye(
        self,
        waveform: list[float],
        samples_per_bit: int,
        eye_samples: int,
    ) -> tuple[list[float], list[list[float]]]:
        """Fold a long waveform into overlapping 2-UI segments for eye diagram.

        Returns:
            (time_ps, traces) where traces is a list of 2-UI voltage segments.
        """
        # Skip first few bits to avoid startup transients
        skip = samples_per_bit * 4
        traces: list[list[float]] = []

        remaining = len(waveform) - skip
        num_segments = remaining // samples_per_bit - 1

        for seg in range(max(num_segments, 0)):
            start = skip + seg * samples_per_bit
            end = start + eye_samples
            if end > len(waveform):
                break
            traces.append(waveform[start:end])

        # Time axis in ps (assuming dt is set from UI)
        # We don't have dt here, so normalize to 0..2 UI
        time_ps = []
        if eye_samples > 0:
            for i in range(eye_samples):
                time_ps.append(2.0 * i / eye_samples)  # in UI

        return time_ps, traces

    def _measure_eye(
        self,
        traces: list[list[float]],
        time_ps: list[float],
        v_swing_mv: float,
        ui_ps: float,
    ) -> tuple[float, float]:
        """Measure eye height and width from folded eye traces.

        Uses a statistical approach: at each time sample across the eye,
        collect all trace voltages and identify the "high" and "low"
        clusters to determine the eye opening.

        Traces that are actively transitioning (near mid-rail) are excluded
        from the measurement at the center sample point.

        Returns:
            (eye_height_mv, eye_width_ps)
        """
        if not traces or not traces[0]:
            return v_swing_mv, ui_ps

        eye_len = len(traces[0])
        if eye_len == 0:
            return v_swing_mv, ui_ps

        # Compute global min and max across all traces at all times
        global_min = float("inf")
        global_max = float("-inf")
        for trace in traces:
            for v in trace:
                if v < global_min:
                    global_min = v
                if v > global_max:
                    global_max = v

        v_range = global_max - global_min
        if v_range < 1e-6:
            # All traces are flat at same level
            return 0.0, ui_ps

        # Threshold for classifying a sample as "high" or "low"
        v_thresh_high = global_min + 0.7 * v_range
        v_thresh_low = global_min + 0.3 * v_range

        # At each time sample, find the min of "high" samples and max of "low" samples
        # This gives us the eye opening vs time
        eye_opening = [0.0] * eye_len

        for i in range(eye_len):
            high_vals = []
            low_vals = []
            for trace in traces:
                if i < len(trace):
                    v = trace[i]
                    if v >= v_thresh_high:
                        high_vals.append(v)
                    elif v <= v_thresh_low:
                        low_vals.append(v)
                    # else: in transition zone, skip

            if high_vals and low_vals:
                eye_opening[i] = min(high_vals) - max(low_vals)
            elif high_vals or low_vals:
                # Only one rail present at this time -- eye is open
                eye_opening[i] = v_range
            else:
                # All traces in transition zone
                eye_opening[i] = 0.0

        # Eye height: the max eye opening in the center region
        # (use max rather than min because transitions close the eye at edges)
        center = eye_len // 2
        window = max(eye_len // 4, 1)
        max_opening = 0.0
        for i in range(center - window, center + window):
            if 0 <= i < eye_len:
                if eye_opening[i] > max_opening:
                    max_opening = eye_opening[i]

        eye_height = max(max_opening, 0.0)

        # Eye width: find the contiguous region around the best opening
        # where eye_opening > some fraction of the max
        thresh = max_opening * 0.1 if max_opening > 0 else 0.0

        # Find the sample with max opening
        best_idx = center
        for i in range(center - window, center + window):
            if 0 <= i < eye_len and eye_opening[i] == max_opening:
                best_idx = i
                break

        left = best_idx
        right = best_idx

        for i in range(best_idx, -1, -1):
            if eye_opening[i] <= thresh:
                left = i + 1
                break
            if i == 0:
                left = 0

        for i in range(best_idx, eye_len):
            if eye_opening[i] <= thresh:
                right = i - 1
                break
            if i == eye_len - 1:
                right = eye_len - 1

        width_frac = (right - left) / eye_len * 2.0  # in UI
        eye_width = width_frac * ui_ps

        return eye_height, max(eye_width, 0.0)

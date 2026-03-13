"""EMI filter design with insertion loss calculation.

Supports Pi-filter (C-L-C), LC low-pass, common-mode choke (CMC),
and ferrite bead topologies.  Given a set of failure frequencies and
required attenuations the ``auto_design_filter`` helper selects the
best topology and component values, returning a complete insertion-loss
curve suitable for MCP tool output.

Transfer functions are evaluated in the 50-ohm LISN context that is
standard for conducted-emission measurements (CISPR 16 / FCC).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FilterSpec:
    """Complete description of a designed filter."""
    topology: str = "none"  # "pi", "lc", "cmc", "ferrite", or "none"
    components: dict = field(default_factory=dict)
    cutoff_frequency_mhz: float = 0.0
    source_impedance_ohm: float = 50.0
    load_impedance_ohm: float = 50.0
    description: str = ""


@dataclass
class InsertionLossResult:
    """Insertion loss curve data."""
    frequencies_mhz: list[float] = field(default_factory=list)
    insertion_loss_db: list[float] = field(default_factory=list)
    cutoff_frequency_mhz: float = 0.0
    max_attenuation_db: float = 0.0


@dataclass
class FilterDesignResult:
    """Full result from auto_design_filter."""
    filter_spec: FilterSpec = field(default_factory=FilterSpec)
    insertion_loss: InsertionLossResult = field(default_factory=InsertionLossResult)
    meets_requirements: bool = False
    failure_frequencies_mhz: list[float] = field(default_factory=list)
    required_attenuation_db: list[float] = field(default_factory=list)
    achieved_attenuation_db: list[float] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------

def _pi_filter_transfer(
    freq_hz: float,
    c1_f: float,
    l_h: float,
    c2_f: float,
    rs: float = 50.0,
    rl: float = 50.0,
) -> complex:
    """Transfer function H(jw) for a Pi-filter (C1-L-C2) between Rs and Rl.

    Circuit: Rs -- C1 to GND -- L series -- C2 to GND -- Rl
    Using ABCD (transmission) matrix approach.
    """
    w = 2 * math.pi * freq_hz
    if w == 0:
        return complex(1.0, 0.0)

    # Admittances of shunt caps
    y_c1 = complex(0, w * c1_f)
    y_c2 = complex(0, w * c2_f)
    # Impedance of series inductor
    z_l = complex(0, w * l_h)

    # ABCD matrix: Y(C1) * Z(L) * Y(C2)
    # Shunt Y:  [[1, 0], [Y, 1]]
    # Series Z: [[1, Z], [0, 1]]
    # M = M_c1 * M_l * M_c2
    # M_c1 = [[1, 0], [y_c1, 1]]
    # M_l  = [[1, z_l], [0, 1]]
    # M_c2 = [[1, 0], [y_c2, 1]]

    # M_c1 * M_l
    a11 = 1 + 0j
    a12 = z_l
    a21 = y_c1
    a22 = y_c1 * z_l + 1

    # (M_c1 * M_l) * M_c2
    A = a11
    B = a12
    C = a21 + a11 * y_c2
    D = a22 + a12 * y_c2

    # Correct: multiply on right by M_c2
    A_final = a11 + a12 * y_c2  # Wait -- let me redo properly.
    # Actually for right multiplication by [[1,0],[y_c2,1]]:
    # [A B] = [a11 a12] * [[1,0],[y_c2,1]] = [a11+a12*y_c2, a12]
    # [C D]   [a21 a22]   [[y_c2,1]]        [a21+a22*y_c2, a22]
    A_final = a11 + a12 * y_c2
    B_final = a12
    C_final = a21 + a22 * y_c2
    D_final = a22

    # H = 2 * Rl / (A*Rl + B + C*Rs*Rl + D*Rs)
    denom = A_final * rl + B_final + C_final * rs * rl + D_final * rs
    if abs(denom) < 1e-30:
        return complex(0.0, 0.0)
    # Voltage transfer with matched source/load
    h = (2 * rl) / denom
    return h


def _lc_lowpass_transfer(
    freq_hz: float,
    l_h: float,
    c_f: float,
    rs: float = 50.0,
    rl: float = 50.0,
) -> complex:
    """Transfer function for series-L, shunt-C low-pass filter."""
    w = 2 * math.pi * freq_hz
    if w == 0:
        return complex(1.0, 0.0)

    z_l = complex(0, w * l_h)
    y_c = complex(0, w * c_f)

    # ABCD: Series Z then Shunt Y
    # M = [[1, z_l],[0, 1]] * [[1, 0],[y_c, 1]]
    A = 1 + z_l * y_c
    B = z_l
    C = y_c
    D = complex(1.0, 0.0)

    denom = A * rl + B + C * rs * rl + D * rs
    if abs(denom) < 1e-30:
        return complex(0.0, 0.0)
    h = (2 * rl) / denom
    return h


def _cmc_impedance(freq_hz: float, l_cm_h: float, srf_hz: float) -> complex:
    """Common-mode choke impedance model.

    Below SRF: Z rises (inductive, |Z| ~ wL)
    At SRF: peak impedance (parallel resonance of L with parasitic C)
    Above SRF: impedance falls (parasitic C dominates, core losses increase)

    We model as a series R-L in parallel with parasitic C, where R is
    frequency-dependent core loss that increases strongly above SRF.
    This naturally produces a peak near SRF and roll-off above.
    """
    w = 2 * math.pi * freq_hz
    if w == 0:
        return complex(0.0, 0.0)
    if l_cm_h <= 0 or srf_hz <= 0:
        return complex(0.0, 0.0)

    # Parasitic capacitance from SRF: f_srf = 1/(2*pi*sqrt(L*C))
    w_srf = 2 * math.pi * srf_hz
    c_p = 1.0 / (w_srf ** 2 * l_cm_h)

    # Frequency-dependent core loss resistance.
    # Increases strongly with frequency (ferrite core losses).
    # Use Gaussian-like profile peaking near SRF to create the classic
    # CMC impedance shape: rise -> peak -> fall.
    f_ratio = freq_hz / srf_hz
    # Peak Z at SRF determined by Q factor (~10 for typical CMC)
    q_at_srf = 10.0
    z_peak = q_at_srf * w_srf * l_cm_h

    # Model the total impedance magnitude directly with a smooth
    # empirical curve that matches real CMC data sheets:
    # |Z| rises as w*L below SRF, peaks at SRF, falls above SRF.
    sigma = 0.5  # log-space half-width of the peak
    log_ratio = math.log10(max(f_ratio, 1e-10))

    # Resistive component: Gaussian peak at SRF
    r_f = z_peak * math.exp(-(log_ratio ** 2) / (2 * sigma ** 2))

    # Reactive component: inductive below SRF, reduces near and above SRF
    if f_ratio < 0.5:
        x_f = w * l_cm_h  # pure inductive
    elif f_ratio < 2.0:
        # Transition through resonance -- reactance passes through zero
        x_f = w * l_cm_h * (1.0 - f_ratio ** 2) / (1.0 + 0.1 * f_ratio ** 2)
    else:
        # Above SRF: capacitive, magnitude decreasing
        x_f = -1.0 / (w * c_p) * 0.5

    return complex(r_f, x_f)


def _cmc_transfer(
    freq_hz: float,
    l_cm_h: float,
    srf_hz: float,
    rs: float = 50.0,
    rl: float = 50.0,
) -> complex:
    """Transfer function for CMC as series impedance between Rs and Rl."""
    z_cmc = _cmc_impedance(freq_hz, l_cm_h, srf_hz)
    # Voltage divider: H = Rl / (Rs + Z_CMC + Rl)
    denom = rs + z_cmc + rl
    if abs(denom) < 1e-30:
        return complex(0.0, 0.0)
    return complex(rl, 0) / denom


def _ferrite_bead_impedance(freq_hz: float, z_peak_ohm: float, srf_hz: float) -> complex:
    """Ferrite bead impedance model.

    R(f): Gaussian peak at SRF in resistance
    X(f): inductive below SRF, capacitive above
    """
    if freq_hz <= 0:
        return complex(0.0, 0.0)

    f_ratio = freq_hz / srf_hz if srf_hz > 0 else 0.0

    # Gaussian R peak
    sigma = 0.6  # log-space width
    log_ratio = math.log10(max(f_ratio, 1e-10))
    r_f = z_peak_ohm * math.exp(-(log_ratio ** 2) / (2 * sigma ** 2))

    # Reactance: positive (inductive) below SRF, negative above
    # Model as inductor with parasitic capacitance
    # At SRF, X = 0 (resonance)
    if f_ratio < 1.0:
        x_f = z_peak_ohm * 0.5 * f_ratio * (1 - f_ratio ** 2)
    else:
        x_f = -z_peak_ohm * 0.3 * (f_ratio - 1) / (1 + 0.5 * (f_ratio - 1))

    return complex(r_f, x_f)


def _ferrite_transfer(
    freq_hz: float,
    z_peak_ohm: float,
    srf_hz: float,
    rs: float = 50.0,
    rl: float = 50.0,
) -> complex:
    """Transfer function for ferrite bead as series element."""
    z_fb = _ferrite_bead_impedance(freq_hz, z_peak_ohm, srf_hz)
    denom = rs + z_fb + rl
    if abs(denom) < 1e-30:
        return complex(0.0, 0.0)
    return complex(rl, 0) / denom


# ---------------------------------------------------------------------------
# FilterDesigner class
# ---------------------------------------------------------------------------

class FilterDesigner:
    """EMI filter designer with insertion loss calculation."""

    def __init__(self, source_impedance_ohm: float = 50.0, load_impedance_ohm: float = 50.0):
        self.rs = source_impedance_ohm
        self.rl = load_impedance_ohm

    # ------------------------------------------------------------------
    # Public: calculate insertion loss for any topology
    # ------------------------------------------------------------------
    def calculate_insertion_loss(
        self,
        topology: str,
        components: dict,
        frequencies_mhz: Optional[list[float]] = None,
    ) -> InsertionLossResult:
        """Calculate insertion loss (dB) across a frequency sweep.

        Parameters
        ----------
        topology : str
            One of "pi", "lc", "cmc", "ferrite".
        components : dict
            Topology-dependent component values:
            - pi:  {"c1_pf": float, "l_uh": float, "c2_pf": float}
            - lc:  {"l_uh": float, "c_pf": float}
            - cmc: {"l_cm_uh": float, "srf_mhz": float}
            - ferrite: {"z_peak_ohm": float, "srf_mhz": float}
        frequencies_mhz : list[float] | None
            Frequency points.  Defaults to 0.1 -- 1000 MHz log-spaced.
        """
        if frequencies_mhz is None:
            import numpy as np
            frequencies_mhz = np.logspace(-1, 3, 500).tolist()

        il_db: list[float] = []
        for f_mhz in frequencies_mhz:
            f_hz = f_mhz * 1e6
            h = self._transfer_function(topology, components, f_hz)
            mag = abs(h)
            if mag < 1e-15:
                il_db.append(-300.0)  # clip
            else:
                il_db.append(20 * math.log10(mag))
            # Insertion loss is negative of the transfer function gain
            # i.e., IL = -20*log10(|H|) but we report as signed dB
            # (negative = attenuation).  Convention: 0 dB at DC, negative values = loss.

        # Find -3 dB cutoff
        cutoff_mhz = 0.0
        for i, db_val in enumerate(il_db):
            if db_val <= -3.0:
                cutoff_mhz = frequencies_mhz[i]
                break

        max_atten = min(il_db) if il_db else 0.0

        return InsertionLossResult(
            frequencies_mhz=frequencies_mhz,
            insertion_loss_db=il_db,
            cutoff_frequency_mhz=round(cutoff_mhz, 4),
            max_attenuation_db=round(max_atten, 2),
        )

    # ------------------------------------------------------------------
    # Public: auto-design filter
    # ------------------------------------------------------------------
    def auto_design_filter(
        self,
        failure_frequencies_mhz: list[float],
        required_attenuation_db: list[float],
        filter_type: str = "auto",
    ) -> FilterDesignResult:
        """Design an EMI filter given failure frequencies and required attenuation.

        Parameters
        ----------
        failure_frequencies_mhz : list[float]
            Frequencies where emissions exceed the limit.
        required_attenuation_db : list[float]
            Required attenuation (positive dB) at each failure frequency.
        filter_type : str
            "auto", "pi", "lc", "cmc", or "ferrite".
        """
        if not failure_frequencies_mhz:
            return FilterDesignResult(
                meets_requirements=True,
                recommendations=["No failure frequencies provided; no filter needed."],
            )

        # Pad required_attenuation to match failure_frequencies length
        while len(required_attenuation_db) < len(failure_frequencies_mhz):
            required_attenuation_db.append(required_attenuation_db[-1] if required_attenuation_db else 20.0)

        min_fail_freq = min(failure_frequencies_mhz)
        max_atten_needed = max(required_attenuation_db)

        # Select topology
        if filter_type == "auto":
            topology = self._select_topology(min_fail_freq, max_atten_needed)
        else:
            topology = filter_type

        # Design component values
        components, cutoff_mhz, desc = self._design_components(
            topology, failure_frequencies_mhz, required_attenuation_db,
        )

        spec = FilterSpec(
            topology=topology,
            components=components,
            cutoff_frequency_mhz=round(cutoff_mhz, 4),
            source_impedance_ohm=self.rs,
            load_impedance_ohm=self.rl,
            description=desc,
        )

        # Calculate insertion loss curve
        il_result = self.calculate_insertion_loss(topology, components)

        # Check whether requirements are met
        achieved: list[float] = []
        all_met = True
        for f_fail, req_db in zip(failure_frequencies_mhz, required_attenuation_db):
            il_at_freq = self._interpolate_il(
                il_result.frequencies_mhz, il_result.insertion_loss_db, f_fail,
            )
            achieved.append(round(-il_at_freq, 2))  # positive = attenuation
            if -il_at_freq < req_db:
                all_met = False

        recs: list[str] = []
        if not all_met:
            recs.append(
                "Filter does not fully meet all attenuation requirements. "
                "Consider cascading a second stage or choosing a higher-order topology."
            )
        if topology == "pi":
            recs.append(
                f"Pi-filter designed with cutoff ~{cutoff_mhz:.2f} MHz. "
                "Verify capacitor SRF exceeds highest failure frequency."
            )
        elif topology == "lc":
            recs.append(
                f"LC low-pass designed with cutoff ~{cutoff_mhz:.2f} MHz. "
                "Ensure inductor SRF is well above cutoff."
            )
        elif topology == "cmc":
            recs.append(
                "Common-mode choke selected. Only attenuates common-mode noise; "
                "add differential-mode filtering if needed."
            )
        elif topology == "ferrite":
            recs.append(
                "Ferrite bead provides broadband attenuation near its SRF. "
                "Check DC resistance and current rating."
            )

        return FilterDesignResult(
            filter_spec=spec,
            insertion_loss=il_result,
            meets_requirements=all_met,
            failure_frequencies_mhz=failure_frequencies_mhz,
            required_attenuation_db=required_attenuation_db,
            achieved_attenuation_db=achieved,
            recommendations=recs,
        )

    # ------------------------------------------------------------------
    # Public: to_dict
    # ------------------------------------------------------------------
    def to_dict(self, result: FilterDesignResult) -> dict:
        """Serialize a FilterDesignResult to MCP-friendly dict."""
        # Down-sample curve for transport (keep ~100 points)
        il = result.insertion_loss
        step = max(1, len(il.frequencies_mhz) // 100)
        sampled_freq = il.frequencies_mhz[::step]
        sampled_il = il.insertion_loss_db[::step]

        return {
            "topology": result.filter_spec.topology,
            "components": result.filter_spec.components,
            "cutoff_frequency_mhz": result.filter_spec.cutoff_frequency_mhz,
            "source_impedance_ohm": result.filter_spec.source_impedance_ohm,
            "load_impedance_ohm": result.filter_spec.load_impedance_ohm,
            "description": result.filter_spec.description,
            "meets_requirements": result.meets_requirements,
            "failure_frequencies_mhz": result.failure_frequencies_mhz,
            "required_attenuation_db": result.required_attenuation_db,
            "achieved_attenuation_db": result.achieved_attenuation_db,
            "insertion_loss_curve": {
                "frequencies_mhz": [round(f, 4) for f in sampled_freq],
                "insertion_loss_db": [round(v, 2) for v in sampled_il],
            },
            "max_attenuation_db": il.max_attenuation_db,
            "recommendations": result.recommendations,
        }

    # ------------------------------------------------------------------
    # CMC impedance (public for tests)
    # ------------------------------------------------------------------
    def cmc_impedance(self, freq_mhz: float, l_cm_uh: float, srf_mhz: float) -> float:
        """Return |Z| of CMC at given frequency."""
        return abs(_cmc_impedance(freq_mhz * 1e6, l_cm_uh * 1e-6, srf_mhz * 1e6))

    # ------------------------------------------------------------------
    # Ferrite bead impedance (public for tests)
    # ------------------------------------------------------------------
    def ferrite_impedance(self, freq_mhz: float, z_peak_ohm: float, srf_mhz: float) -> float:
        """Return |Z| of ferrite bead at given frequency."""
        return abs(_ferrite_bead_impedance(freq_mhz * 1e6, z_peak_ohm, srf_mhz * 1e6))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _transfer_function(self, topology: str, components: dict, freq_hz: float) -> complex:
        """Dispatch to the appropriate transfer function model."""
        if topology == "pi":
            c1_f = components.get("c1_pf", 100) * 1e-12
            l_h = components.get("l_uh", 1.0) * 1e-6
            c2_f = components.get("c2_pf", 100) * 1e-12
            return _pi_filter_transfer(freq_hz, c1_f, l_h, c2_f, self.rs, self.rl)
        elif topology == "lc":
            l_h = components.get("l_uh", 1.0) * 1e-6
            c_f = components.get("c_pf", 100) * 1e-12
            return _lc_lowpass_transfer(freq_hz, l_h, c_f, self.rs, self.rl)
        elif topology == "cmc":
            l_cm_h = components.get("l_cm_uh", 10.0) * 1e-6
            srf_hz = components.get("srf_mhz", 100.0) * 1e6
            return _cmc_transfer(freq_hz, l_cm_h, srf_hz, self.rs, self.rl)
        elif topology == "ferrite":
            z_peak = components.get("z_peak_ohm", 600.0)
            srf_hz = components.get("srf_mhz", 100.0) * 1e6
            return _ferrite_transfer(freq_hz, z_peak, srf_hz, self.rs, self.rl)
        else:
            raise ValueError(f"Unknown filter topology: {topology}")

    def _select_topology(self, min_fail_freq_mhz: float, max_atten_db: float) -> str:
        """Heuristic topology selection."""
        if max_atten_db > 40 and min_fail_freq_mhz < 30:
            return "pi"  # Pi-filter for high attenuation at lower frequencies
        elif max_atten_db > 30:
            return "pi"
        elif min_fail_freq_mhz > 100:
            return "ferrite"  # Ferrite beads excel at high freq
        elif max_atten_db <= 15 and min_fail_freq_mhz > 50:
            return "ferrite"
        elif min_fail_freq_mhz < 10:
            return "cmc"  # CMC for low-frequency CM noise
        else:
            return "lc"

    def _design_components(
        self,
        topology: str,
        fail_freqs: list[float],
        req_atten: list[float],
    ) -> tuple[dict, float, str]:
        """Design component values for the chosen topology.

        Returns (components_dict, cutoff_frequency_mhz, description).
        """
        min_fail = min(fail_freqs)
        max_atten = max(req_atten)

        if topology == "pi":
            return self._design_pi(min_fail, max_atten)
        elif topology == "lc":
            return self._design_lc(min_fail, max_atten)
        elif topology == "cmc":
            return self._design_cmc(min_fail, max_atten)
        elif topology == "ferrite":
            return self._design_ferrite(fail_freqs, max_atten)
        else:
            raise ValueError(f"Unknown topology: {topology}")

    def _design_pi(self, min_fail_mhz: float, max_atten_db: float) -> tuple[dict, float, str]:
        """Design a Pi-filter targeting cutoff well below min failure freq."""
        # Place cutoff at ~1/3 of min failure frequency
        f_cutoff_mhz = min_fail_mhz / 3.0
        f_cutoff_hz = f_cutoff_mhz * 1e6
        w_c = 2 * math.pi * f_cutoff_hz

        # For a 3rd-order Butterworth pi: C1=C2, L chosen for cutoff
        # Normalized prototype: g1=1.0, g2=2.0, g3=1.0
        # C = g / (w_c * R), L = g * R / w_c
        r = self.rs  # assumes matched
        g1, g2, g3 = 1.0, 2.0, 1.0
        c1_f = g1 / (w_c * r)
        l_h = g2 * r / w_c
        c2_f = g3 / (w_c * r)

        c1_pf = c1_f * 1e12
        l_uh = l_h * 1e6
        c2_pf = c2_f * 1e12

        components = {
            "c1_pf": round(c1_pf, 2),
            "l_uh": round(l_uh, 4),
            "c2_pf": round(c2_pf, 2),
        }
        desc = (
            f"3rd-order Butterworth Pi-filter (C-L-C) with cutoff at "
            f"{f_cutoff_mhz:.2f} MHz. C1={c1_pf:.1f} pF, L={l_uh:.3f} uH, "
            f"C2={c2_pf:.1f} pF."
        )
        return components, f_cutoff_mhz, desc

    def _design_lc(self, min_fail_mhz: float, max_atten_db: float) -> tuple[dict, float, str]:
        """Design a 2nd-order LC low-pass filter."""
        f_cutoff_mhz = min_fail_mhz / 2.5
        f_cutoff_hz = f_cutoff_mhz * 1e6
        w_c = 2 * math.pi * f_cutoff_hz

        # Butterworth 2nd order: g1=1.414, g2=1.414
        r = self.rs
        g1, g2 = 1.4142, 1.4142
        l_h = g1 * r / w_c
        c_f = g2 / (w_c * r)

        l_uh = l_h * 1e6
        c_pf = c_f * 1e12

        components = {"l_uh": round(l_uh, 4), "c_pf": round(c_pf, 2)}
        desc = (
            f"2nd-order Butterworth LC low-pass with cutoff at "
            f"{f_cutoff_mhz:.2f} MHz. L={l_uh:.3f} uH, C={c_pf:.1f} pF."
        )
        return components, f_cutoff_mhz, desc

    def _design_cmc(self, min_fail_mhz: float, max_atten_db: float) -> tuple[dict, float, str]:
        """Design a common-mode choke."""
        # Place SRF near the worst failure frequency for max impedance there
        srf_mhz = min_fail_mhz * 1.5
        # Choose L_CM so impedance at failure freq gives needed attenuation
        # At resonance, |Z| ~ Q * w * L.  We want |Z| >> Rs+Rl
        # IL ~ 20*log10(Rl / (Rs + Z + Rl))  =>  Z = (Rs+Rl) * (10^(atten/20) - 1)
        z_needed = (self.rs + self.rl) * (10 ** (max_atten_db / 20.0) - 1)
        # At SRF, Z ~ Q * w_srf * L  (Q~20)
        w_srf = 2 * math.pi * srf_mhz * 1e6
        q = 20.0
        l_cm_h = z_needed / (q * w_srf) if w_srf > 0 else 1e-6
        l_cm_uh = l_cm_h * 1e6

        # Reasonable bounds
        l_cm_uh = max(0.1, min(l_cm_uh, 10000.0))

        components = {
            "l_cm_uh": round(l_cm_uh, 3),
            "srf_mhz": round(srf_mhz, 2),
        }
        desc = (
            f"Common-mode choke with L_CM={l_cm_uh:.2f} uH, SRF={srf_mhz:.1f} MHz. "
            f"Peak impedance near {srf_mhz:.0f} MHz."
        )
        cutoff_mhz = srf_mhz / 5.0  # rough "useful" range start
        return components, cutoff_mhz, desc

    def _design_ferrite(
        self, fail_freqs: list[float], max_atten_db: float,
    ) -> tuple[dict, float, str]:
        """Design ferrite bead selection."""
        # Place SRF near geometric mean of failure frequencies
        geo_mean = math.exp(sum(math.log(max(f, 0.01)) for f in fail_freqs) / len(fail_freqs))
        srf_mhz = geo_mean

        # Z_peak needed:  IL = 20*log10(Rl/(Rs+Z+Rl))
        z_needed = (self.rs + self.rl) * (10 ** (max_atten_db / 20.0) - 1)
        z_peak_ohm = max(z_needed * 1.5, 100.0)  # margin

        components = {
            "z_peak_ohm": round(z_peak_ohm, 1),
            "srf_mhz": round(srf_mhz, 2),
        }
        desc = (
            f"Ferrite bead with Z_peak={z_peak_ohm:.0f} ohm at SRF={srf_mhz:.1f} MHz. "
            f"Select a part with rated current above DC load."
        )
        cutoff_mhz = srf_mhz / 3.0
        return components, cutoff_mhz, desc

    @staticmethod
    def _interpolate_il(
        freqs: list[float], il_db: list[float], target_freq: float,
    ) -> float:
        """Linear interpolation of insertion loss at a target frequency."""
        if not freqs:
            return 0.0
        if target_freq <= freqs[0]:
            return il_db[0]
        if target_freq >= freqs[-1]:
            return il_db[-1]
        for i in range(len(freqs) - 1):
            if freqs[i] <= target_freq <= freqs[i + 1]:
                t = (target_freq - freqs[i]) / (freqs[i + 1] - freqs[i])
                return il_db[i] + t * (il_db[i + 1] - il_db[i])
        return il_db[-1]

"""Immunity margin analysis with coupling path model.

Models electric-field coupling, BCI (bulk current injection), and cable
transfer impedance to predict induced voltages at IC pins.  Compares
against per-IC-type upset/damage thresholds and returns margins.

Reference standards: ISO 11452-2 (radiated), ISO 11452-4 (BCI).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# ISO 11452 field strength and BCI levels (duplicated from automotive_emc
# for self-contained use — values are identical)
# ---------------------------------------------------------------------------
ISO11452_FIELD_LEVELS: dict[int, float] = {
    1: 1.0,
    2: 3.0,
    3: 10.0,
    4: 30.0,
    5: 60.0,
}

ISO11452_BCI_LEVELS_MA: dict[int, float] = {
    1: 1.0,
    2: 3.0,
    3: 10.0,
    4: 30.0,
    5: 100.0,
}

# ---------------------------------------------------------------------------
# IC upset / damage threshold database
# ---------------------------------------------------------------------------
IC_THRESHOLDS: dict[str, dict[str, float | str]] = {
    "cmos_logic": {
        "upset_v": 0.3,
        "damage_v": 2.0,
        "description": "CMOS logic (3.3V/1.8V)",
    },
    "lpddr4": {
        "upset_v": 0.2,
        "damage_v": 0.7,
        "description": "LPDDR4 DRAM",
    },
    "usb2_phy": {
        "upset_v": 0.4,
        "damage_v": 3.6,
        "description": "USB 2.0 PHY transceiver",
    },
    "ethernet_phy": {
        "upset_v": 1.0,
        "damage_v": 4.0,
        "description": "10/100/1000 Ethernet PHY",
    },
    "gnss_receiver": {
        "upset_v": 0.0,          # uses desense_dbm instead
        "damage_v": 0.0,
        "desense_dbm": -110.0,
        "description": "GNSS/GPS receiver front-end",
    },
}

# Speed of light (m/s)
C0 = 299_792_458.0


# ---------------------------------------------------------------------------
# Core physics functions
# ---------------------------------------------------------------------------

def effective_height(trace_length_mm: float, frequency_hz: float) -> float:
    """Effective antenna height for an electrically short trace.

    For an electrically short trace (l << lambda), h_eff ≈ l.
    For longer traces the effective height saturates at lambda / pi.

    Returns h_eff in metres.
    """
    l_m = trace_length_mm / 1000.0
    wavelength = C0 / frequency_hz if frequency_hz > 0 else 1e10
    # Electrically short approximation
    h_max = wavelength / math.pi
    return min(l_m, h_max)


def antenna_factor(frequency_hz: float, gain_linear: float = 1.0) -> float:
    """Antenna factor AF = E / V  for a receive antenna.

    AF = 9.73 / (λ × √G)   (linear, in 1/m)

    Parameters
    ----------
    frequency_hz : float
        Operating frequency in Hz.
    gain_linear : float
        Antenna gain (linear, not dB).  Default 1.0 (isotropic).

    Returns
    -------
    float
        Antenna factor in 1/m.
    """
    if frequency_hz <= 0 or gain_linear <= 0:
        return 0.0
    wavelength = C0 / frequency_hz
    return 9.73 / (wavelength * math.sqrt(gain_linear))


def voltage_from_field(e_field_vm: float, trace_length_mm: float,
                       frequency_hz: float = 100e6) -> float:
    """Induced voltage from electric field coupling.

    V_induced = E_field × h_eff

    Parameters
    ----------
    e_field_vm : float
        Incident electric field strength (V/m).
    trace_length_mm : float
        PCB trace length acting as receiving element (mm).
    frequency_hz : float
        Frequency of the incident field (Hz).

    Returns
    -------
    float
        Induced voltage in volts.
    """
    h_eff = effective_height(trace_length_mm, frequency_hz)
    return e_field_vm * h_eff


def transfer_impedance_unshielded(
    r_dc_ohm_per_m: float,
    mutual_inductance_nh_per_m: float,
    frequency_hz: float,
    cable_length_m: float,
) -> float:
    """Transfer impedance for an unshielded cable/trace pair.

    Z_T = R_DC + jωM   →   |Z_T| = sqrt(R_DC² + (ωM)²)

    Returns total |Z_T| in ohms (for the given cable length).
    """
    omega = 2 * math.pi * frequency_hz
    m_h_per_m = mutual_inductance_nh_per_m * 1e-9
    zt_per_m = math.sqrt(r_dc_ohm_per_m ** 2 + (omega * m_h_per_m) ** 2)
    return zt_per_m * cable_length_m


def transfer_impedance_shielded(
    r_shield_ohm_per_m: float,
    shield_thickness_mm: float,
    frequency_hz: float,
    cable_length_m: float,
    conductivity_s_per_m: float = 5.8e7,   # copper
) -> float:
    """Transfer impedance for a shielded cable.

    Z_T = R_shield × e^(-t/δ)
    where δ = skin depth = sqrt(2 / (ω μ₀ σ))

    Returns total |Z_T| in ohms (for the given cable length).
    """
    if frequency_hz <= 0:
        return r_shield_ohm_per_m * cable_length_m

    omega = 2 * math.pi * frequency_hz
    mu0 = 4 * math.pi * 1e-7
    skin_depth = math.sqrt(2 / (omega * mu0 * conductivity_s_per_m))
    t_m = shield_thickness_mm / 1000.0
    zt_per_m = r_shield_ohm_per_m * math.exp(-t_m / skin_depth)
    return zt_per_m * cable_length_m


def bci_pin_voltage(
    bci_current_a: float,
    z_transfer_ohm: float,
    coupling_factor: float = 1.0,
) -> float:
    """BCI to pin voltage conversion.

    V_pin = I_bci × Z_transfer × coupling_factor
    """
    return bci_current_a * z_transfer_ohm * coupling_factor


def get_ic_threshold(ic_type: str) -> dict[str, float | str]:
    """Look up IC upset / damage thresholds.

    Returns a copy of the threshold dict, or a conservative default.
    """
    if ic_type in IC_THRESHOLDS:
        return dict(IC_THRESHOLDS[ic_type])
    # Conservative default
    return {
        "upset_v": 0.3,
        "damage_v": 2.0,
        "description": f"Unknown IC type '{ic_type}' — using conservative CMOS defaults",
    }


# ---------------------------------------------------------------------------
# Margin calculation
# ---------------------------------------------------------------------------

def _margin_db(induced_v: float, threshold_v: float) -> float:
    """Calculate margin in dB.  Positive = pass, negative = fail."""
    if induced_v <= 0:
        return 60.0  # effectively infinite margin
    if threshold_v <= 0:
        return -60.0  # no threshold → always fail
    return 20 * math.log10(threshold_v / induced_v)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class InterfaceImmunityResult:
    """Result for a single interface under one coupling mechanism."""
    interface_name: str
    ic_type: str
    coupling_type: str          # "electric_field" or "bci"
    induced_voltage_v: float
    upset_threshold_v: float
    damage_threshold_v: float
    upset_margin_db: float
    damage_margin_db: float
    status: str                  # "pass", "marginal", "fail"
    recommendation: str = ""


@dataclass
class ImmunityAnalysisResult:
    """Top-level immunity analysis output."""
    iso_level: int
    field_strength_vm: float
    bci_current_ma: float
    interface_results: list[InterfaceImmunityResult] = field(default_factory=list)
    overall_status: str = "unknown"
    score: float = 0.0
    recommendations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class ImmunityAnalyzer:
    """Immunity margin analyzer with coupling path models."""

    def analyze_immunity(
        self,
        interfaces: list[dict[str, Any]],
        field_strength_vm: float = 10.0,
        iso_level: int = 3,
    ) -> ImmunityAnalysisResult:
        """Analyze immunity margins for a list of interfaces.

        Parameters
        ----------
        interfaces : list[dict]
            Each dict must contain:
              - name : str              — interface label
              - cable_length_mm : float — cable / trace run length
              - shielding : str         — "none", "unshielded", "shielded"
              - ic_type : str           — key into IC_THRESHOLDS
              - trace_length_mm : float — on-board trace to IC pin
            Optional keys:
              - coupling_factor : float (default 1.0)
              - shield_thickness_mm : float (default 0.1)
              - r_dc_ohm_per_m : float (default 0.05)
              - mutual_inductance_nh_per_m : float (default 10.0)
              - r_shield_ohm_per_m : float (default 0.01)
        field_strength_vm : float
            Incident field strength in V/m (default 10 = ISO 11452 Level III).
        iso_level : int
            ISO 11452 level (1-5).  If given, overrides field_strength_vm
            with the standard value for that level.

        Returns
        -------
        ImmunityAnalysisResult
        """
        # Resolve ISO level
        if iso_level in ISO11452_FIELD_LEVELS:
            field_strength_vm = ISO11452_FIELD_LEVELS[iso_level]
        bci_current_ma = ISO11452_BCI_LEVELS_MA.get(iso_level, 10.0)
        bci_current_a = bci_current_ma / 1000.0

        frequency_hz = 100e6  # representative test frequency (100 MHz)

        results: list[InterfaceImmunityResult] = []

        for iface in interfaces:
            name = iface.get("name", "unknown")
            cable_length_mm = float(iface.get("cable_length_mm", 100.0))
            shielding = iface.get("shielding", "none")
            ic_type = iface.get("ic_type", "cmos_logic")
            trace_length_mm = float(iface.get("trace_length_mm", 25.0))
            coupling_factor = float(iface.get("coupling_factor", 1.0))
            shield_thickness_mm = float(iface.get("shield_thickness_mm", 0.1))
            r_dc = float(iface.get("r_dc_ohm_per_m", 0.05))
            m_nh = float(iface.get("mutual_inductance_nh_per_m", 10.0))
            r_shield = float(iface.get("r_shield_ohm_per_m", 0.01))

            cable_length_m = cable_length_mm / 1000.0

            thresholds = get_ic_threshold(ic_type)
            upset_v = float(thresholds["upset_v"])
            damage_v = float(thresholds["damage_v"])

            # --- Electric field coupling ---
            v_e = voltage_from_field(field_strength_vm, trace_length_mm, frequency_hz)
            e_upset_margin = _margin_db(v_e, upset_v)
            e_damage_margin = _margin_db(v_e, damage_v)

            if e_upset_margin < 0:
                e_status = "fail"
            elif e_upset_margin < 6:
                e_status = "marginal"
            else:
                e_status = "pass"

            e_rec = ""
            if e_status == "fail":
                e_rec = (
                    f"Electric field coupling on '{name}' exceeds {ic_type} upset "
                    f"threshold by {abs(e_upset_margin):.1f} dB. Shorten trace, add "
                    f"filtering, or use shielded enclosure."
                )
            elif e_status == "marginal":
                e_rec = (
                    f"Electric field margin on '{name}' is only {e_upset_margin:.1f} dB "
                    f"(< 6 dB). Consider additional filtering or shorter trace routing."
                )

            results.append(InterfaceImmunityResult(
                interface_name=name,
                ic_type=ic_type,
                coupling_type="electric_field",
                induced_voltage_v=round(v_e, 6),
                upset_threshold_v=upset_v,
                damage_threshold_v=damage_v,
                upset_margin_db=round(e_upset_margin, 1),
                damage_margin_db=round(e_damage_margin, 1),
                status=e_status,
                recommendation=e_rec,
            ))

            # --- BCI coupling ---
            if shielding == "shielded":
                z_t = transfer_impedance_shielded(
                    r_shield, shield_thickness_mm, frequency_hz, cable_length_m,
                )
            else:
                z_t = transfer_impedance_unshielded(
                    r_dc, m_nh, frequency_hz, cable_length_m,
                )

            v_bci = bci_pin_voltage(bci_current_a, z_t, coupling_factor)
            b_upset_margin = _margin_db(v_bci, upset_v)
            b_damage_margin = _margin_db(v_bci, damage_v)

            if b_upset_margin < 0:
                b_status = "fail"
            elif b_upset_margin < 6:
                b_status = "marginal"
            else:
                b_status = "pass"

            b_rec = ""
            if b_status == "fail":
                b_rec = (
                    f"BCI coupling on '{name}' exceeds {ic_type} upset threshold by "
                    f"{abs(b_upset_margin):.1f} dB. Add common-mode choke, shielded "
                    f"cable, or TVS protection at connector."
                )
            elif b_status == "marginal":
                b_rec = (
                    f"BCI margin on '{name}' is only {b_upset_margin:.1f} dB "
                    f"(< 6 dB). Consider adding ferrite or common-mode filtering."
                )

            results.append(InterfaceImmunityResult(
                interface_name=name,
                ic_type=ic_type,
                coupling_type="bci",
                induced_voltage_v=round(v_bci, 6),
                upset_threshold_v=upset_v,
                damage_threshold_v=damage_v,
                upset_margin_db=round(b_upset_margin, 1),
                damage_margin_db=round(b_damage_margin, 1),
                status=b_status,
                recommendation=b_rec,
            ))

        # Overall status
        statuses = [r.status for r in results]
        if "fail" in statuses:
            overall = "fail"
        elif "marginal" in statuses:
            overall = "marginal"
        elif statuses:
            overall = "pass"
        else:
            overall = "unknown"

        # Score (percentage of passing results)
        if results:
            pass_count = sum(1 for r in results if r.status == "pass")
            score = round(pass_count / len(results) * 100, 1)
        else:
            score = 0.0

        # Top-level recommendations
        recommendations: list[str] = []
        failing = [r for r in results if r.status == "fail"]
        marginal = [r for r in results if r.status == "marginal"]
        if failing:
            recommendations.append(
                f"{len(failing)} interface coupling path(s) exceed IC upset "
                f"thresholds. Immediate mitigation required."
            )
        if marginal:
            recommendations.append(
                f"{len(marginal)} interface(s) have < 6 dB margin. "
                f"Consider adding protection."
            )
        if not failing and not marginal:
            recommendations.append(
                "All interfaces have adequate immunity margins (> 6 dB)."
            )

        return ImmunityAnalysisResult(
            iso_level=iso_level,
            field_strength_vm=field_strength_vm,
            bci_current_ma=bci_current_ma,
            interface_results=results,
            overall_status=overall,
            score=score,
            recommendations=recommendations,
        )

    def to_dict(self, result: ImmunityAnalysisResult) -> dict[str, Any]:
        """Convert analysis result to JSON-safe dict for MCP output."""
        return {
            "iso_level": result.iso_level,
            "field_strength_vm": result.field_strength_vm,
            "bci_current_ma": result.bci_current_ma,
            "overall_status": result.overall_status,
            "score": result.score,
            "interface_count": len(result.interface_results),
            "interfaces": [
                {
                    "interface_name": r.interface_name,
                    "ic_type": r.ic_type,
                    "coupling_type": r.coupling_type,
                    "induced_voltage_v": r.induced_voltage_v,
                    "upset_threshold_v": r.upset_threshold_v,
                    "damage_threshold_v": r.damage_threshold_v,
                    "upset_margin_db": r.upset_margin_db,
                    "damage_margin_db": r.damage_margin_db,
                    "status": r.status,
                    "recommendation": r.recommendation,
                }
                for r in result.interface_results
            ],
            "recommendations": result.recommendations,
        }

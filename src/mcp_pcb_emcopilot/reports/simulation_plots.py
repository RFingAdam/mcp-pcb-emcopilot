"""Simulation result plot generators for PCB design review reports.

Generates publication-quality matplotlib charts from MCP tool output data.
Each function returns a path to a saved PNG image suitable for embedding
in DOCX, HTML, or PDF reports.

Standard theme: dark background (#0f172a) with cyan accent (#22d3ee),
matching the EMCopilot brand.  A light theme variant is also available.

Usage
-----
    from mcp_pcb_emcopilot.reports.simulation_plots import SimulationPlotter

    plotter = SimulationPlotter(output_dir="/tmp/report_plots")
    path = plotter.eye_diagram(height_mv=738, width_ui=0.93, ...)
    # -> "/tmp/report_plots/eye_diagram.png"
"""
from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass, field
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np


# ---------------------------------------------------------------------------
# Theme configuration
# ---------------------------------------------------------------------------
DARK_THEME = {
    "bg": "#0f172a",
    "fg": "#e2e8f0",
    "grid": "#1e293b",
    "accent": "#22d3ee",
    "pass": "#4ade80",
    "fail": "#f87171",
    "warning": "#fbbf24",
    "marginal": "#fb923c",
    "limit": "#ef4444",
    "secondary": "#94a3b8",
    "trace1": "#22d3ee",
    "trace2": "#a78bfa",
    "trace3": "#34d399",
    "trace4": "#f472b6",
    "fill_alpha": 0.15,
}

LIGHT_THEME = {
    "bg": "#ffffff",
    "fg": "#1e293b",
    "grid": "#e2e8f0",
    "accent": "#0891b2",
    "pass": "#16a34a",
    "fail": "#dc2626",
    "warning": "#d97706",
    "marginal": "#ea580c",
    "limit": "#dc2626",
    "secondary": "#64748b",
    "trace1": "#0891b2",
    "trace2": "#7c3aed",
    "trace3": "#059669",
    "trace4": "#db2777",
    "fill_alpha": 0.10,
}


def _apply_theme(ax: plt.Axes, theme: dict) -> None:
    """Apply a consistent visual theme to axes."""
    ax.set_facecolor(theme["bg"])
    ax.figure.set_facecolor(theme["bg"])
    ax.tick_params(colors=theme["fg"], which="both")
    ax.xaxis.label.set_color(theme["fg"])
    ax.yaxis.label.set_color(theme["fg"])
    ax.title.set_color(theme["fg"])
    for spine in ax.spines.values():
        spine.set_color(theme["grid"])
    ax.grid(True, color=theme["grid"], linewidth=0.5, alpha=0.7)


def _add_methodology_box(ax: plt.Axes, text: str, theme: dict) -> None:
    """Add a methodology annotation box in the lower-right corner."""
    ax.text(
        0.98, 0.02, text,
        transform=ax.transAxes, fontsize=6, color=theme["secondary"],
        ha="right", va="bottom", fontstyle="italic",
        bbox=dict(boxstyle="round,pad=0.3", facecolor=theme["bg"],
                  edgecolor=theme["grid"], alpha=0.9),
    )


def _add_status_badge(ax: plt.Axes, status: str, theme: dict) -> None:
    """Add a PASS/FAIL/WARNING badge in the upper-right corner."""
    colors = {
        "PASS": theme["pass"], "FAIL": theme["fail"],
        "WARNING": theme["warning"], "MARGINAL": theme["marginal"],
    }
    color = colors.get(status.upper(), theme["secondary"])
    ax.text(
        0.98, 0.95, f"  {status.upper()}  ",
        transform=ax.transAxes, fontsize=10, fontweight="bold",
        color=theme["bg"] if status.upper() != "WARNING" else "#000",
        ha="right", va="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor=color, edgecolor="none"),
    )


class SimulationPlotter:
    """Generate simulation result plots for design review reports."""

    def __init__(
        self,
        output_dir: Optional[str] = None,
        theme: str = "dark",
        dpi: int = 200,
        figsize: tuple[float, float] = (8, 4.5),
    ):
        self.output_dir = output_dir or tempfile.mkdtemp(prefix="emcopilot_plots_")
        os.makedirs(self.output_dir, exist_ok=True)
        self.theme = DARK_THEME if theme == "dark" else LIGHT_THEME
        self.dpi = dpi
        self.figsize = figsize

    def _save(self, fig: plt.Figure, name: str) -> str:
        path = os.path.join(self.output_dir, f"{name}.png")
        fig.savefig(path, dpi=self.dpi, bbox_inches="tight",
                    facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        return path

    # ------------------------------------------------------------------
    # 1. Eye Diagram
    # ------------------------------------------------------------------
    def eye_diagram(
        self,
        height_mv: float = 738.0,
        width_ui: float = 0.93,
        jitter_ps: float = 15.0,
        data_rate_gbps: float = 3.2,
        rise_time_ps: float = 100.0,
        voltage_swing_mv: float = 800.0,
        spec_name: str = "LPDDR4",
        status: str = "PASS",
    ) -> str:
        """Generate a synthetic eye diagram from signal integrity parameters."""
        t = self.theme
        fig, ax = plt.subplots(figsize=self.figsize)
        _apply_theme(ax, t)

        ui_ps = 1e3 / data_rate_gbps  # unit interval in ps
        n_traces = 80
        n_points = 500

        time = np.linspace(-1.0, 1.0, n_points)  # in UI
        half_swing = voltage_swing_mv / 2

        rng = np.random.default_rng(42)
        for _ in range(n_traces):
            jitter_offset = rng.normal(0, jitter_ps / ui_ps * 0.5)
            noise = rng.normal(0, (voltage_swing_mv - height_mv) / 6)
            bit = rng.choice([-1, 1])
            rise = rise_time_ps / ui_ps

            signal = bit * half_swing * np.tanh((time - jitter_offset) / (rise * 0.5))
            signal += noise

            ax.plot(time, signal, color=t["accent"], alpha=0.08, linewidth=0.5)

        # Draw eye opening rectangle
        eye_left = -(width_ui / 2)
        eye_right = width_ui / 2
        eye_top = height_mv / 2
        eye_bottom = -height_mv / 2
        rect = plt.Rectangle(
            (eye_left, eye_bottom), width_ui, height_mv,
            fill=False, edgecolor=t["pass"], linewidth=1.5, linestyle="--",
            label=f"Eye opening: {height_mv:.0f} mV × {width_ui:.2f} UI",
        )
        ax.add_patch(rect)

        # Annotations
        ax.annotate(
            f"{height_mv:.0f} mV", xy=(0, eye_top), xytext=(0.6, eye_top + 50),
            color=t["pass"], fontsize=9, fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=t["pass"], lw=1),
        )
        ax.annotate(
            f"{width_ui:.2f} UI", xy=(eye_right, 0), xytext=(eye_right + 0.15, -100),
            color=t["pass"], fontsize=9, fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=t["pass"], lw=1),
        )

        ax.set_xlim(-1.0, 1.0)
        ax.set_ylim(-voltage_swing_mv * 0.7, voltage_swing_mv * 0.7)
        ax.set_xlabel("Time (UI)")
        ax.set_ylabel("Voltage (mV)")
        ax.set_title(f"{spec_name} Eye Diagram — {data_rate_gbps:.1f} Gbps")
        ax.legend(loc="upper left", fontsize=8,
                  facecolor=t["bg"], edgecolor=t["grid"], labelcolor=t["fg"])

        _add_status_badge(ax, status, t)
        _add_methodology_box(
            ax,
            f"Synthetic eye | {n_traces} traces | Jitter: {jitter_ps:.0f} ps | "
            f"Rise: {rise_time_ps:.0f} ps | pcb_calc_eye_diagram",
            t,
        )

        return self._save(fig, "eye_diagram")

    # ------------------------------------------------------------------
    # 2. S-Parameter Plot (Insertion Loss / Return Loss)
    # ------------------------------------------------------------------
    def s_parameter_plot(
        self,
        freq_ghz: Optional[list[float]] = None,
        s21_db: Optional[list[float]] = None,
        s11_db: Optional[list[float]] = None,
        s21_limit_db: Optional[float] = None,
        channel_name: str = "DDR Channel",
        status: str = "PASS",
    ) -> str:
        """Generate S-parameter frequency response plot."""
        t = self.theme
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(self.figsize[0] * 1.2, self.figsize[1]))
        _apply_theme(ax1, t)
        _apply_theme(ax2, t)

        if freq_ghz is None:
            freq_ghz = np.linspace(0.01, 6.0, 200).tolist()
        if s21_db is None:
            freq = np.array(freq_ghz)
            s21_db = (-0.5 * freq - 0.08 * freq**2).tolist()
        if s11_db is None:
            freq = np.array(freq_ghz)
            s11_db = (-15 - 5 * np.sin(freq * 2) + 0.5 * freq).tolist()

        freq = np.array(freq_ghz)
        s21 = np.array(s21_db)
        s11 = np.array(s11_db)

        # Insertion loss (S21)
        ax1.plot(freq, s21, color=t["trace1"], linewidth=1.5, label="S21 (Insertion Loss)")
        ax1.fill_between(freq, s21, alpha=t["fill_alpha"], color=t["trace1"])
        if s21_limit_db is not None:
            ax1.axhline(y=s21_limit_db, color=t["limit"], linestyle="--",
                        linewidth=1, label=f"Limit: {s21_limit_db} dB")
        ax1.set_xlabel("Frequency (GHz)")
        ax1.set_ylabel("S21 (dB)")
        ax1.set_title("Insertion Loss")
        ax1.legend(fontsize=7, facecolor=t["bg"], edgecolor=t["grid"], labelcolor=t["fg"])
        ax1.set_ylim(min(s21) * 1.2, 1)

        # Return loss (S11)
        ax2.plot(freq, s11, color=t["trace2"], linewidth=1.5, label="S11 (Return Loss)")
        ax2.fill_between(freq, s11, alpha=t["fill_alpha"], color=t["trace2"])
        ax2.axhline(y=-10, color=t["limit"], linestyle="--", linewidth=1, label="−10 dB target")
        ax2.set_xlabel("Frequency (GHz)")
        ax2.set_ylabel("S11 (dB)")
        ax2.set_title("Return Loss")
        ax2.legend(fontsize=7, facecolor=t["bg"], edgecolor=t["grid"], labelcolor=t["fg"])
        ax2.set_ylim(min(s11) * 1.2, 0)

        fig.suptitle(f"S-Parameter Analysis — {channel_name}", color=t["fg"],
                     fontsize=13, fontweight="bold")
        fig.tight_layout(rect=[0, 0, 1, 0.93])

        _add_status_badge(ax2, status, t)
        _add_methodology_box(
            ax1,
            f"pcb_calc_insertion_loss / pcb_calc_return_loss | {len(freq_ghz)} freq points",
            t,
        )

        return self._save(fig, "s_parameters")

    # ------------------------------------------------------------------
    # 3. PDN Impedance Profile
    # ------------------------------------------------------------------
    def pdn_impedance(
        self,
        rail_voltage: float = 1.8,
        load_current_a: float = 2.0,
        ripple_pct: float = 5.0,
        freq_mhz: Optional[list[float]] = None,
        impedance_ohm: Optional[list[float]] = None,
        status: str = "FAIL",
    ) -> str:
        """Generate PDN impedance vs. frequency plot with target line."""
        t = self.theme
        fig, ax = plt.subplots(figsize=self.figsize)
        _apply_theme(ax, t)

        target_z = rail_voltage * (ripple_pct / 100.0) / load_current_a

        if freq_mhz is None:
            freq_mhz = np.logspace(-1, 3, 300).tolist()
        if impedance_ohm is None:
            freq = np.array(freq_mhz)
            # Simulated PDN impedance with resonance peaks
            z_bulk = 0.01 / (1 + (freq / 0.5) ** 2)
            z_mlcc = 0.005 + 0.0001 * freq
            z_plane = 0.001 * (1 + 0.01 * freq)
            # Anti-resonance peaks
            z_ar1 = 0.5 * np.exp(-((np.log10(freq) - 1.0) ** 2) / 0.05)
            z_ar2 = 0.3 * np.exp(-((np.log10(freq) - 2.2) ** 2) / 0.08)
            impedance_ohm = (z_bulk + z_mlcc + z_plane + z_ar1 + z_ar2).tolist()

        freq = np.array(freq_mhz)
        z = np.array(impedance_ohm)

        ax.loglog(freq, z, color=t["trace1"], linewidth=1.5, label="PDN Impedance")
        ax.axhline(y=target_z, color=t["limit"], linestyle="--", linewidth=1.5,
                   label=f"Target: {target_z*1000:.1f} mΩ ({rail_voltage}V × {ripple_pct}% / {load_current_a}A)")

        # Color regions above/below target
        ax.fill_between(freq, z, target_z, where=(z > target_z),
                        alpha=0.15, color=t["fail"], label="Exceeds target")
        ax.fill_between(freq, z, target_z, where=(z <= target_z),
                        alpha=0.10, color=t["pass"])

        ax.set_xlabel("Frequency (MHz)")
        ax.set_ylabel("Impedance (Ω)")
        ax.set_title(f"PDN Impedance Profile — {rail_voltage}V Rail")
        ax.legend(fontsize=7, facecolor=t["bg"], edgecolor=t["grid"], labelcolor=t["fg"],
                  loc="upper left")

        _add_status_badge(ax, status, t)
        _add_methodology_box(
            ax,
            f"pcb_calc_pdn_impedance | Target Z = {target_z*1000:.1f} mΩ | "
            f"V={rail_voltage}V, I={load_current_a}A, ripple={ripple_pct}%",
            t,
        )

        return self._save(fig, "pdn_impedance")

    # ------------------------------------------------------------------
    # 4. Clock EMI Spectrum (FCC + CISPR limits)
    # ------------------------------------------------------------------
    def clock_emi_spectrum(
        self,
        clock_mhz: float = 100.0,
        rise_time_ns: float = 0.5,
        trace_length_mm: float = 25.0,
        n_harmonics: int = 15,
        standard: str = "FCC Class B",
        cispr25_class: Optional[int] = None,
        status: str = "FAIL",
    ) -> str:
        """Generate clock EMI harmonic spectrum with regulatory limit overlay."""
        t = self.theme
        fig, ax = plt.subplots(figsize=self.figsize)
        _apply_theme(ax, t)

        harmonics = list(range(1, n_harmonics + 1))
        freqs_mhz = [clock_mhz * h for h in harmonics]

        # Trapezoidal wave harmonic envelope
        knee_freq = 1 / (math.pi * rise_time_ns * 1e-9) / 1e6
        wavelength_base = 3e11 / (clock_mhz * 1e6)  # mm
        elec_len = trace_length_mm / wavelength_base

        emissions = []
        for h, f in zip(harmonics, freqs_mhz):
            rolloff = 0 if h == 1 else -20 * math.log10(h)
            if f > knee_freq:
                rolloff -= 20 * math.log10(f / knee_freq)
            base = 40 + 20 * math.log10(f) + 20 * math.log10(max(elec_len * h, 0.01))
            emissions.append(base + rolloff)

        # FCC Class B limits (simplified)
        fcc_limits = []
        for f in freqs_mhz:
            if f < 88:
                fcc_limits.append(40.0)
            elif f < 216:
                fcc_limits.append(43.5)
            elif f < 960:
                fcc_limits.append(46.0)
            else:
                fcc_limits.append(54.0)

        # Bar chart of harmonics
        bar_colors = []
        for e, l in zip(emissions, fcc_limits):
            if e > l:
                bar_colors.append(t["fail"])
            elif e > l - 6:
                bar_colors.append(t["warning"])
            else:
                bar_colors.append(t["pass"])

        x_pos = np.arange(len(harmonics))
        bars = ax.bar(x_pos, emissions, width=0.6, color=bar_colors, alpha=0.85,
                      edgecolor="none", label="Predicted emission")

        # Limit line
        ax.step(x_pos, fcc_limits, where="mid", color=t["limit"], linewidth=2,
                linestyle="--", label=f"{standard} limit")

        # CISPR 25 overlay if requested
        if cispr25_class is not None:
            from ..analyzers.emc.automotive_emc import AutomotiveEMCAnalyzer
            analyzer = AutomotiveEMCAnalyzer()
            cispr_limits = []
            for f in freqs_mhz:
                info = analyzer.get_cispr25_limit(f, cispr25_class, "radiated")
                if info and "limit_dbuvm" in info:
                    cispr_limits.append(info["limit_dbuvm"])
                else:
                    cispr_limits.append(None)

            # Plot only where we have limits
            valid_x = [x for x, cl in zip(x_pos, cispr_limits) if cl is not None]
            valid_l = [cl for cl in cispr_limits if cl is not None]
            if valid_x:
                ax.step(valid_x, valid_l, where="mid", color=t["trace4"], linewidth=2,
                        linestyle="-.", label=f"CISPR 25 Class {cispr25_class}")

        # Knee frequency marker
        knee_idx = None
        for i, f in enumerate(freqs_mhz):
            if f >= knee_freq and knee_idx is None:
                knee_idx = i
        if knee_idx is not None and knee_idx < len(x_pos):
            ax.axvline(x=x_pos[knee_idx], color=t["secondary"], linestyle=":",
                       linewidth=1, alpha=0.7)
            ax.text(x_pos[knee_idx] + 0.1, max(emissions) * 0.95,
                    f"f_knee={knee_freq:.0f} MHz", color=t["secondary"],
                    fontsize=7, rotation=90, va="top")

        ax.set_xticks(x_pos)
        ax.set_xticklabels([f"{f:.0f}" for f in freqs_mhz], rotation=45, fontsize=7)
        ax.set_xlabel("Frequency (MHz)")
        ax.set_ylabel("Level (dBµV/m)")
        ax.set_title(f"Clock EMI Spectrum — {clock_mhz:.0f} MHz, {rise_time_ns} ns rise")
        ax.legend(fontsize=7, facecolor=t["bg"], edgecolor=t["grid"], labelcolor=t["fg"])

        _add_status_badge(ax, status, t)
        _add_methodology_box(
            ax,
            f"pcb_analyze_clock_emi | Trace: {trace_length_mm} mm | "
            f"Knee: {knee_freq:.0f} MHz | Trapezoidal envelope model",
            t,
        )

        return self._save(fig, "clock_emi_spectrum")

    # ------------------------------------------------------------------
    # 5. CISPR 25 Automotive Compliance Plot
    # ------------------------------------------------------------------
    def cispr25_compliance(
        self,
        clock_mhz: float = 100.0,
        cispr_class: int = 3,
        shielding_db: float = 0.0,
        status: str = "FAIL",
    ) -> str:
        """Generate CISPR 25 compliance plot with harmonic overlay on limit mask."""
        t = self.theme
        fig, ax = plt.subplots(figsize=self.figsize)
        _apply_theme(ax, t)

        from ..analyzers.emc.automotive_emc import (
            AutomotiveEMCAnalyzer, CISPR25_RADIATED_LIMITS,
        )
        analyzer = AutomotiveEMCAnalyzer()

        # Draw limit mask
        for band in CISPR25_RADIATED_LIMITS:
            lim = band["limits"].get(cispr_class)
            if lim is None:
                continue
            ax.fill_between(
                [band["freq_min_mhz"], band["freq_max_mhz"]],
                [lim, lim], [-20, -20],
                alpha=0.08, color=t["pass"],
            )
            ax.plot(
                [band["freq_min_mhz"], band["freq_max_mhz"]],
                [lim, lim],
                color=t["limit"], linewidth=2, linestyle="--",
            )
            # Band label
            mid = (band["freq_min_mhz"] + band["freq_max_mhz"]) / 2
            ax.text(mid, lim + 2, f"{lim} dB", color=t["limit"],
                    fontsize=6, ha="center", va="bottom")

        # Plot harmonics
        results = analyzer.predict_cispr25_compliance(
            [clock_mhz], shielding_db=shielding_db, cispr_class=cispr_class,
        )

        for r in results:
            color = t["fail"] if r.status == "fail" else (
                t["warning"] if r.status == "marginal" else t["pass"]
            )
            marker = "v" if r.status == "fail" else ("s" if r.status == "marginal" else "^")
            ax.scatter(r.frequency_mhz, r.predicted_value, color=color,
                       marker=marker, s=60, zorder=5, edgecolors="white", linewidth=0.5)
            # Label failures
            if r.status in ("fail", "marginal"):
                ax.annotate(
                    f"{r.margin_db:+.0f} dB",
                    xy=(r.frequency_mhz, r.predicted_value),
                    xytext=(5, 8), textcoords="offset points",
                    color=color, fontsize=7, fontweight="bold",
                )

        # Legend
        from matplotlib.lines import Line2D
        legend_elements = [
            Line2D([0], [0], color=t["limit"], linestyle="--", lw=2,
                   label=f"CISPR 25 Class {cispr_class} limit"),
            Line2D([0], [0], marker="^", color="w", markerfacecolor=t["pass"],
                   markersize=8, linestyle="None", label="Pass (>6 dB margin)"),
            Line2D([0], [0], marker="s", color="w", markerfacecolor=t["warning"],
                   markersize=8, linestyle="None", label="Marginal (0-6 dB)"),
            Line2D([0], [0], marker="v", color="w", markerfacecolor=t["fail"],
                   markersize=8, linestyle="None", label="Fail (exceeds limit)"),
        ]
        ax.legend(handles=legend_elements, fontsize=7,
                  facecolor=t["bg"], edgecolor=t["grid"], labelcolor=t["fg"],
                  loc="upper right")

        ax.set_xscale("log")
        ax.set_xlabel("Frequency (MHz)")
        ax.set_ylabel("Level (dBµV/m)")
        ax.set_title(f"CISPR 25 Class {cispr_class} Compliance — {clock_mhz:.0f} MHz Clock")
        ax.set_xlim(0.1, 3000)

        _add_status_badge(ax, status, t)
        shielding_text = f" | Shielding: {shielding_db:.0f} dB" if shielding_db > 0 else ""
        _add_methodology_box(
            ax,
            f"pcb_analyze_automotive_emc | CISPR 25:2021 ALSE{shielding_text}",
            t,
        )

        return self._save(fig, "cispr25_compliance")

    # ------------------------------------------------------------------
    # 6. Cavity Resonance Frequency Map
    # ------------------------------------------------------------------
    def cavity_resonance(
        self,
        board_width_mm: float = 73.0,
        board_height_mm: float = 38.0,
        er: float = 4.2,
        n_modes: int = 8,
        sensitive_bands: Optional[list[dict]] = None,
        status: str = "WARNING",
    ) -> str:
        """Generate power plane cavity resonance mode map."""
        t = self.theme
        fig, ax = plt.subplots(figsize=self.figsize)
        _apply_theme(ax, t)

        a = board_width_mm / 1000  # meters
        b = board_height_mm / 1000
        c = 3e8  # speed of light

        modes = []
        for m_idx in range(5):
            for n_idx in range(5):
                if m_idx == 0 and n_idx == 0:
                    continue
                f = (c / (2 * math.sqrt(er))) * math.sqrt(
                    (m_idx / a) ** 2 + (n_idx / b) ** 2
                ) / 1e6
                if f < 5000:
                    modes.append((f"TM{m_idx}{n_idx}", f, m_idx, n_idx))

        modes.sort(key=lambda x: x[1])
        modes = modes[:n_modes]

        if sensitive_bands is None:
            sensitive_bands = [
                {"name": "WiFi 2.4G", "min": 2400, "max": 2500, "color": t["trace1"]},
                {"name": "LTE B7", "min": 2500, "max": 2690, "color": t["trace2"]},
                {"name": "GNSS L1", "min": 1559, "max": 1591, "color": t["trace3"]},
                {"name": "Cell 2100", "min": 1920, "max": 2170, "color": t["trace4"]},
                {"name": "Cell 900", "min": 880, "max": 960, "color": t["marginal"]},
            ]

        # Draw sensitive bands as vertical spans
        for band in sensitive_bands:
            ax.axvspan(band["min"], band["max"], alpha=0.15, color=band["color"],
                       label=band["name"])

        # Plot resonant modes as vertical lines with markers
        for mode_name, freq, m_idx, n_idx in modes:
            in_band = any(b["min"] <= freq <= b["max"] for b in sensitive_bands)
            color = t["fail"] if in_band else t["pass"]
            ax.axvline(x=freq, color=color, linewidth=2 if in_band else 1,
                       alpha=0.9 if in_band else 0.6)
            ax.text(freq, 0.95 - 0.08 * (m_idx % 3), mode_name,
                    transform=ax.get_xaxis_transform(),
                    color=color, fontsize=9, fontweight="bold" if in_band else "normal",
                    ha="center", va="top",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor=t["bg"],
                              edgecolor=color, alpha=0.9))

        ax.set_xlabel("Frequency (MHz)")
        ax.set_yticks([])
        ax.set_title(
            f"Power Plane Cavity Resonance — "
            f"{board_width_mm:.0f} × {board_height_mm:.0f} mm, εr={er}"
        )
        ax.legend(fontsize=7, facecolor=t["bg"], edgecolor=t["grid"], labelcolor=t["fg"],
                  loc="lower right", ncol=2)
        ax.set_xlim(500, max(m[1] for m in modes) * 1.1)

        _add_status_badge(ax, status, t)
        _add_methodology_box(
            ax,
            f"pcb_calc_plane_resonance | TM mode formula | "
            f"a={board_width_mm}mm, b={board_height_mm}mm, εr={er}",
            t,
        )

        return self._save(fig, "cavity_resonance")

    # ------------------------------------------------------------------
    # 7. Thermal Budget Chart
    # ------------------------------------------------------------------
    def thermal_budget(
        self,
        components: Optional[list[dict]] = None,
        ambient_c: float = 40.0,
        status: str = "WARNING",
    ) -> str:
        """Generate thermal budget bar chart for critical components."""
        t = self.theme
        fig, ax = plt.subplots(figsize=self.figsize)
        _apply_theme(ax, t)

        if components is None:
            components = [
                {"name": "U10 (CPU)", "tj": 117, "tj_max": 125, "power_w": 3.5},
                {"name": "U6 (PMIC)", "tj": 95, "tj_max": 150, "power_w": 1.2},
                {"name": "U1 (DDR)", "tj": 72, "tj_max": 105, "power_w": 0.8},
                {"name": "U8 (WiFi)", "tj": 65, "tj_max": 105, "power_w": 0.5},
                {"name": "U13 (ETH)", "tj": 58, "tj_max": 125, "power_w": 0.3},
            ]

        names = [c["name"] for c in components]
        tjs = [c["tj"] for c in components]
        tj_maxs = [c["tj_max"] for c in components]
        margins = [c["tj_max"] - c["tj"] for c in components]

        x = np.arange(len(names))

        # Stacked: temperature reached + margin to max
        bar_colors = []
        for m in margins:
            if m < 10:
                bar_colors.append(t["fail"])
            elif m < 25:
                bar_colors.append(t["warning"])
            else:
                bar_colors.append(t["pass"])

        bars_tj = ax.barh(x, tjs, height=0.5, color=bar_colors, alpha=0.85,
                          label="Junction temp (°C)")
        bars_margin = ax.barh(x, margins, left=tjs, height=0.5,
                              color=t["grid"], alpha=0.5, label="Margin to Tj_max")

        # Tj_max markers
        for i, (tj, tj_max) in enumerate(zip(tjs, tj_maxs)):
            ax.plot(tj_max, i, marker="|", color=t["limit"], markersize=20, markeredgewidth=2)
            ax.text(tj + margins[i] / 2, i, f"+{margins[i]}°C",
                    ha="center", va="center", fontsize=8, fontweight="bold",
                    color=t["fg"])

        ax.axvline(x=ambient_c, color=t["secondary"], linestyle=":", linewidth=1,
                   label=f"Ambient: {ambient_c}°C")

        ax.set_yticks(x)
        ax.set_yticklabels(names, fontsize=9)
        ax.set_xlabel("Temperature (°C)")
        ax.set_title(f"Thermal Budget — {ambient_c}°C Ambient")
        ax.legend(fontsize=7, facecolor=t["bg"], edgecolor=t["grid"], labelcolor=t["fg"],
                  loc="lower right")
        ax.invert_yaxis()

        _add_status_badge(ax, status, t)
        _add_methodology_box(ax, "pcb_analyze_thermal | Tj = Ta + P × θ_JA", t)

        return self._save(fig, "thermal_budget")

    # ------------------------------------------------------------------
    # 8. Impedance Profile (trace geometry vs target)
    # ------------------------------------------------------------------
    def impedance_profile(
        self,
        trace_widths_mm: Optional[list[float]] = None,
        impedances_ohm: Optional[list[float]] = None,
        target_ohm: float = 50.0,
        tolerance_pct: float = 10.0,
        trace_type: str = "Microstrip",
        status: str = "PASS",
    ) -> str:
        """Generate impedance vs. trace width profile."""
        t = self.theme
        fig, ax = plt.subplots(figsize=self.figsize)
        _apply_theme(ax, t)

        if trace_widths_mm is None:
            trace_widths_mm = np.linspace(0.05, 0.5, 50).tolist()
        if impedances_ohm is None:
            w = np.array(trace_widths_mm)
            impedances_ohm = (87 / math.sqrt(4.2 + 1.41) *
                              np.log(5.98 * 0.2 / (0.8 * w + 0.035))).tolist()

        w = np.array(trace_widths_mm)
        z = np.array(impedances_ohm)

        ax.plot(w, z, color=t["trace1"], linewidth=2, label=f"{trace_type} impedance")

        # Target band
        z_hi = target_ohm * (1 + tolerance_pct / 100)
        z_lo = target_ohm * (1 - tolerance_pct / 100)
        ax.axhspan(z_lo, z_hi, alpha=0.12, color=t["pass"],
                   label=f"Target: {target_ohm}Ω ±{tolerance_pct}%")
        ax.axhline(y=target_ohm, color=t["pass"], linestyle="--", linewidth=1)

        # Find optimal width
        z_arr = np.array(impedances_ohm)
        closest_idx = np.argmin(np.abs(z_arr - target_ohm))
        opt_w = trace_widths_mm[closest_idx]
        opt_z = impedances_ohm[closest_idx]
        ax.scatter([opt_w], [opt_z], color=t["accent"], s=100, zorder=5,
                   edgecolors="white", linewidth=1.5)
        ax.annotate(
            f"Optimal: {opt_w:.3f} mm → {opt_z:.1f} Ω",
            xy=(opt_w, opt_z), xytext=(opt_w + 0.05, opt_z + 8),
            color=t["accent"], fontsize=9, fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=t["accent"], lw=1.5),
        )

        ax.set_xlabel("Trace Width (mm)")
        ax.set_ylabel("Impedance (Ω)")
        ax.set_title(f"{trace_type} Impedance vs. Trace Width")
        ax.legend(fontsize=7, facecolor=t["bg"], edgecolor=t["grid"], labelcolor=t["fg"])

        _add_status_badge(ax, status, t)
        _add_methodology_box(
            ax,
            f"pcb_calc_{trace_type.lower()}_impedance | εr=4.2 | h=0.2mm | 1oz Cu",
            t,
        )

        return self._save(fig, "impedance_profile")

    # ------------------------------------------------------------------
    # 9. Design Comparison Summary
    # ------------------------------------------------------------------
    def design_comparison(
        self,
        changes: Optional[dict] = None,
        design_a: str = "Rev A",
        design_b: str = "Rev B",
    ) -> str:
        """Generate design revision comparison summary chart."""
        t = self.theme
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(self.figsize[0] * 1.1, self.figsize[1]),
                                         gridspec_kw={"width_ratios": [1, 1.5]})
        _apply_theme(ax1, t)
        _apply_theme(ax2, t)

        if changes is None:
            changes = {
                "Components added": 12,
                "Components removed": 3,
                "Components moved": 8,
                "Nets added": 5,
                "Nets removed": 2,
                "Board resized": 1,
                "Layer count changed": 0,
            }

        categories = list(changes.keys())
        values = list(changes.values())

        colors = []
        for v in values:
            if v == 0:
                colors.append(t["secondary"])
            elif v > 5:
                colors.append(t["warning"])
            else:
                colors.append(t["accent"])

        # Bar chart
        y_pos = np.arange(len(categories))
        ax1.barh(y_pos, values, color=colors, height=0.6, alpha=0.85)
        ax1.set_yticks(y_pos)
        ax1.set_yticklabels(categories, fontsize=8)
        ax1.set_xlabel("Count")
        ax1.set_title(f"{design_a} → {design_b}")
        ax1.invert_yaxis()

        for i, v in enumerate(values):
            if v > 0:
                ax1.text(v + 0.2, i, str(v), va="center", color=t["fg"], fontsize=9)

        # Summary pie chart
        total = sum(values)
        if total > 0:
            nonzero = {k: v for k, v in changes.items() if v > 0}
            pie_colors = [t["trace1"], t["trace2"], t["trace3"], t["trace4"],
                          t["accent"], t["warning"], t["marginal"]][:len(nonzero)]
            wedges, texts, autotexts = ax2.pie(
                nonzero.values(), labels=nonzero.keys(),
                colors=pie_colors, autopct="%1.0f%%",
                textprops={"color": t["fg"], "fontsize": 8},
                pctdistance=0.75,
            )
            for at in autotexts:
                at.set_fontsize(7)
                at.set_color(t["bg"])
            ax2.set_title(f"Change Distribution ({total} total)")
        else:
            ax2.text(0.5, 0.5, "No changes", transform=ax2.transAxes,
                     ha="center", va="center", fontsize=14, color=t["secondary"])

        fig.suptitle(f"Design Revision Comparison — {design_a} vs {design_b}",
                     color=t["fg"], fontsize=13, fontweight="bold")
        fig.tight_layout(rect=[0, 0, 1, 0.93])

        _add_methodology_box(ax1, "pcb_compare_designs | DesignComparator", t)

        return self._save(fig, "design_comparison")

    # ------------------------------------------------------------------
    # 10. Conducted Emissions Plot (LISN model + limit masks)
    # ------------------------------------------------------------------
    def conducted_emissions_plot(
        self,
        switching_freq_khz: float = 200.0,
        input_voltage: float = 12.0,
        duty_cycle: float = 0.5,
        rise_time_ns: float = 20.0,
        cispr_class: int = 3,
        fcc_class: str = "B",
        num_harmonics: int = 50,
        input_filter_db: float = 0.0,
        status: str = "FAIL",
    ) -> str:
        """Generate conducted emissions spectrum with CISPR 25 and FCC limit overlays.

        X-axis: frequency 150 kHz -- 30 MHz (log scale).
        Y-axis: level in dBuV.
        Plots predicted harmonics and overlays CISPR 25 conducted limits
        (peak + average) and FCC Class B/A limit as dashed lines.
        """
        from ..analyzers.emc.conducted_emissions import (
            ConductedEmissionAnalyzer,
            FCC_PART15_CONDUCTED_LIMITS,
        )
        from ..analyzers.emc.automotive_emc import CISPR25_CONDUCTED_LIMITS

        t = self.theme
        fig, ax = plt.subplots(figsize=self.figsize)
        _apply_theme(ax, t)

        # Run the analyzer
        analyzer = ConductedEmissionAnalyzer()
        analysis = analyzer.predict_conducted_compliance(
            switching_freq_khz=switching_freq_khz,
            input_voltage=input_voltage,
            duty_cycle=duty_cycle,
            rise_time_ns=rise_time_ns,
            cispr_class=cispr_class,
            fcc_class=fcc_class,
            num_harmonics=num_harmonics,
            input_filter_db=input_filter_db,
        )

        # -- Plot predicted emissions as bar markers --
        for finding in analysis.findings:
            f_mhz = finding.frequency_mhz
            level = finding.predicted_level_dbuv
            if finding.status == "fail":
                color = t["fail"]
            elif finding.status == "marginal":
                color = t["warning"]
            else:
                color = t["pass"]
            ax.scatter(f_mhz, level, color=color, s=30, zorder=5,
                       edgecolors="white", linewidth=0.3)

        # Connect predicted emissions with a line
        freqs = [f.frequency_mhz for f in analysis.findings]
        levels = [f.predicted_level_dbuv for f in analysis.findings]
        if freqs:
            ax.plot(freqs, levels, color=t["accent"], linewidth=1.0, alpha=0.7,
                    label="Predicted emission")

        # -- CISPR 25 conducted limit mask (peak + average) --
        for band in CISPR25_CONDUCTED_LIMITS:
            lim_data = band["limits"].get(cispr_class)
            if lim_data is None:
                continue
            f_min = band["freq_min_mhz"]
            f_max = band["freq_max_mhz"]
            peak = lim_data["peak"]
            avg = lim_data["avg"]
            # Peak limit (solid red)
            ax.plot([f_min, f_max], [peak, peak], color=t["limit"],
                    linewidth=2, linestyle="-")
            # Average limit (dotted red)
            ax.plot([f_min, f_max], [avg, avg], color=t["limit"],
                    linewidth=1.5, linestyle=":")

        # Manual legend entries for CISPR limits
        from matplotlib.lines import Line2D
        cispr_peak_line = Line2D([0], [0], color=t["limit"], linewidth=2,
                                 linestyle="-",
                                 label=f"CISPR 25 Cl.{cispr_class} peak")
        cispr_avg_line = Line2D([0], [0], color=t["limit"], linewidth=1.5,
                                linestyle=":",
                                label=f"CISPR 25 Cl.{cispr_class} avg")

        # -- FCC Part 15 limit (dashed) --
        fcc_limits = FCC_PART15_CONDUCTED_LIMITS.get(fcc_class.upper(), [])
        for entry in fcc_limits:
            f_min = entry["freq_min_mhz"]
            f_max = entry["freq_max_mhz"]
            qp = entry["qp_limit_dbuv"]
            ax.plot([f_min, f_max], [qp, qp], color=t["trace2"],
                    linewidth=1.5, linestyle="--")

        fcc_line = Line2D([0], [0], color=t["trace2"], linewidth=1.5,
                          linestyle="--",
                          label=f"FCC Part 15 Cl.{fcc_class} QP")

        # Legend
        pred_line = Line2D([0], [0], color=t["accent"], linewidth=1.0,
                           label="Predicted emission")
        ax.legend(handles=[pred_line, cispr_peak_line, cispr_avg_line, fcc_line],
                  fontsize=7, facecolor=t["bg"], edgecolor=t["grid"],
                  labelcolor=t["fg"], loc="upper right")

        ax.set_xscale("log")
        ax.set_xlabel("Frequency (MHz)")
        ax.set_ylabel("Level (dBµV)")
        ax.set_xlim(0.1, 120)
        ax.set_title(
            f"Conducted Emissions — {switching_freq_khz:.0f} kHz SMPS, "
            f"V_in={input_voltage}V"
        )

        _add_status_badge(ax, status, t)
        filter_text = f" | Filter: {input_filter_db:.0f} dB" if input_filter_db > 0 else ""
        _add_methodology_box(
            ax,
            f"pcb_analyze_conducted_emissions | LISN 50µH/50Ω | "
            f"D={duty_cycle:.2f}, tr={rise_time_ns}ns{filter_text}",
            t,
        )

        return self._save(fig, "conducted_emissions")

    # ------------------------------------------------------------------
    # 11. Near-Field EMI Plot
    # ------------------------------------------------------------------
    def near_field_plot(
        self,
        sources: Optional[list[dict]] = None,
        distances_m: Optional[list[float]] = None,
        status: str = "WARNING",
    ) -> str:
        """Generate near-field H-field and E-field vs distance dual-panel plot.

        Parameters
        ----------
        sources : list of dict, optional
            Near-field sources. Each dict has: name, type, frequency_mhz,
            and either {current_a, area_mm2} or {voltage_v, length_mm}.
        distances_m : list of float, optional
            Evaluation distances in meters.
        status : str
            Badge text (PASS/FAIL/WARNING).

        Returns
        -------
        str : Path to saved PNG file.
        """
        t = self.theme

        if distances_m is None:
            distances_m = np.logspace(-3, 1, 100).tolist()

        if sources is None:
            sources = [
                {"name": "SMPS Loop", "type": "current_loop", "frequency_mhz": 500.0,
                 "current_a": 2.0, "area_mm2": 25.0},
                {"name": "100MHz CLK", "type": "clock_trace", "frequency_mhz": 100.0,
                 "voltage_v": 3.3, "length_mm": 20.0},
                {"name": "Reset Line", "type": "reset_line", "frequency_mhz": 50.0,
                 "voltage_v": 3.3, "length_mm": 40.0},
            ]

        from ..analyzers.emc.near_field import (
            NearFieldAnalyzer,
            h_field_magnetic_dipole,
            e_field_electric_dipole,
            to_db_h,
            to_db_e,
            transition_distance,
            classify_source,
        )

        fig, (ax_h, ax_e) = plt.subplots(
            1, 2, figsize=(self.figsize[0] * 1.3, self.figsize[1]),
        )
        _apply_theme(ax_h, t)
        _apply_theme(ax_e, t)

        trace_colors = [t["trace1"], t["trace2"], t["trace3"], t["trace4"],
                        t["accent"], t["warning"], t["marginal"]]
        dist_arr = np.array(distances_m)

        # Track transition distances to draw markers
        all_transitions: list[tuple[float, str]] = []

        for i, src in enumerate(sources):
            color = trace_colors[i % len(trace_colors)]
            freq = src.get("frequency_mhz", 100.0)
            name = src.get("name", f"Source {i+1}")
            src_type = src.get("type", "unknown")
            field_class = classify_source(src_type)

            area_m2 = src.get("area_mm2", 0.0) * 1e-6
            current_a = src.get("current_a", 0.0)
            length_m = src.get("length_mm", 0.0) * 1e-3
            voltage_v = src.get("voltage_v", 0.0)

            r_trans = transition_distance(freq)
            if r_trans != float("inf"):
                all_transitions.append((r_trans, name))

            # Calculate H-field and E-field at all distances
            h_vals = []
            e_vals = []
            for d in distances_m:
                h = h_field_magnetic_dipole(current_a, area_m2, freq, d)
                e = e_field_electric_dipole(voltage_v, length_m, freq, d)
                h_vals.append(to_db_h(h))
                e_vals.append(to_db_e(e))

            h_arr = np.array(h_vals)
            e_arr = np.array(e_vals)

            # Plot H-field (left panel)
            valid_h = h_arr > -900
            if np.any(valid_h):
                ax_h.plot(dist_arr[valid_h], h_arr[valid_h], color=color,
                          linewidth=1.5, label=f"{name} ({freq:.0f} MHz)")

            # Plot E-field (right panel)
            valid_e = e_arr > -900
            if np.any(valid_e):
                ax_e.plot(dist_arr[valid_e], e_arr[valid_e], color=color,
                          linewidth=1.5, label=f"{name} ({freq:.0f} MHz)")

        # Draw near-field/far-field transition as vertical dashed lines
        plotted_transitions: set[float] = set()
        for r_trans, name in all_transitions:
            if r_trans in plotted_transitions:
                continue
            plotted_transitions.add(r_trans)
            for ax in (ax_h, ax_e):
                ax.axvline(x=r_trans, color=t["secondary"], linestyle="--",
                           linewidth=1, alpha=0.7)

        # Add a single transition label on each panel
        if all_transitions:
            r_first = all_transitions[0][0]
            for ax in (ax_h, ax_e):
                ylims = ax.get_ylim()
                ax.text(r_first * 1.15, ylims[1] * 0.95 if ylims[1] > 0 else ylims[0] + (ylims[1] - ylims[0]) * 0.92,
                        "NF/FF\ntransition", color=t["secondary"],
                        fontsize=7, va="top")

        # Reference levels: probe sensitivity thresholds on H-field panel
        probe_refs = NearFieldAnalyzer.PROBE_SENSITIVITIES
        for probe_name, sensitivity_dba in list(probe_refs.items())[:3]:
            ax_h.axhline(y=sensitivity_dba, color=t["limit"], linestyle=":",
                         linewidth=0.8, alpha=0.5)
            ax_h.text(dist_arr[-1] * 0.8, sensitivity_dba + 1,
                      probe_name, color=t["limit"], fontsize=6,
                      ha="right", va="bottom", alpha=0.7)

        # Axis formatting
        ax_h.set_xscale("log")
        ax_h.set_xlabel("Distance (m)")
        ax_h.set_ylabel("H-field (dBA/m)")
        ax_h.set_title("Magnetic Field (H)")
        ax_h.legend(fontsize=6, facecolor=t["bg"], edgecolor=t["grid"],
                    labelcolor=t["fg"], loc="upper right")

        ax_e.set_xscale("log")
        ax_e.set_xlabel("Distance (m)")
        ax_e.set_ylabel("E-field (dBuV/m)")
        ax_e.set_title("Electric Field (E)")
        ax_e.legend(fontsize=6, facecolor=t["bg"], edgecolor=t["grid"],
                    labelcolor=t["fg"], loc="upper right")

        fig.suptitle("Near-Field EMI Analysis", color=t["fg"],
                     fontsize=13, fontweight="bold")
        fig.tight_layout(rect=[0, 0, 1, 0.93])

        _add_status_badge(ax_e, status, t)
        _add_methodology_box(
            ax_h,
            f"pcb_analyze_near_field | Magnetic/electric dipole model | "
            f"{len(sources)} source(s)",
            t,
        )

        return self._save(fig, "near_field_emi")

    # ------------------------------------------------------------------
    # 12. EMI Filter Insertion Loss Response Plot
    # ------------------------------------------------------------------
    def filter_response_plot(
        self,
        frequencies_mhz: Optional[list[float]] = None,
        insertion_loss_db: Optional[list[float]] = None,
        failure_frequencies_mhz: Optional[list[float]] = None,
        required_attenuation_db: Optional[list[float]] = None,
        cutoff_frequency_mhz: Optional[float] = None,
        topology: str = "Pi-filter",
        original_emission_dbuv: Optional[list[float]] = None,
        filtered_emission_dbuv: Optional[list[float]] = None,
        emission_freqs_mhz: Optional[list[float]] = None,
        limit_dbuv: Optional[float] = None,
        status: str = "PASS",
    ) -> str:
        """Generate EMI filter insertion loss Bode magnitude plot.

        Parameters
        ----------
        frequencies_mhz : list[float]
            Frequency sweep for insertion loss curve.
        insertion_loss_db : list[float]
            Insertion loss values (negative = attenuation).
        failure_frequencies_mhz : list[float]
            Frequencies where the original design failed.
        required_attenuation_db : list[float]
            Required attenuation at each failure frequency (positive dB).
        cutoff_frequency_mhz : float
            -3 dB cutoff frequency.
        topology : str
            Filter topology name for title.
        original_emission_dbuv : list[float]
            Original emission levels before filtering (optional overlay).
        filtered_emission_dbuv : list[float]
            Emission levels after filtering (optional overlay).
        emission_freqs_mhz : list[float]
            Frequency axis for emission overlays.
        limit_dbuv : float
            Emission limit line for before/after comparison.
        status : str
            PASS / FAIL / WARNING badge.

        Returns
        -------
        str : Path to saved PNG file.
        """
        t = self.theme

        has_emission_overlay = (
            original_emission_dbuv is not None
            and filtered_emission_dbuv is not None
            and emission_freqs_mhz is not None
        )

        if has_emission_overlay:
            fig, (ax1, ax2) = plt.subplots(
                1, 2, figsize=(self.figsize[0] * 1.3, self.figsize[1]),
            )
            _apply_theme(ax1, t)
            _apply_theme(ax2, t)
        else:
            fig, ax1 = plt.subplots(figsize=self.figsize)
            _apply_theme(ax1, t)
            ax2 = None

        # --- Default data if not provided ---
        if frequencies_mhz is None or insertion_loss_db is None:
            frequencies_mhz = np.logspace(-1, 3, 300).tolist()
            fc = 10.0
            insertion_loss_db = [
                -60 * max(0, np.log10(f / fc)) if f > fc else 0.0
                for f in frequencies_mhz
            ]
            cutoff_frequency_mhz = fc

        freq = np.array(frequencies_mhz)
        il = np.array(insertion_loss_db)

        # --- Insertion loss curve ---
        ax1.semilogx(freq, il, color=t["trace1"], linewidth=2,
                      label="Insertion loss")
        ax1.fill_between(freq, il, alpha=t["fill_alpha"], color=t["trace1"])

        # -3 dB cutoff marker
        if cutoff_frequency_mhz and cutoff_frequency_mhz > 0:
            ax1.axvline(x=cutoff_frequency_mhz, color=t["secondary"],
                        linestyle=":", linewidth=1, alpha=0.8)
            ax1.axhline(y=-3.0, color=t["secondary"], linestyle=":",
                        linewidth=1, alpha=0.5)
            ax1.scatter([cutoff_frequency_mhz], [-3.0], color=t["accent"],
                        s=80, zorder=5, edgecolors="white", linewidth=1.5)
            ax1.annotate(
                f"-3 dB @ {cutoff_frequency_mhz:.2f} MHz",
                xy=(cutoff_frequency_mhz, -3.0),
                xytext=(cutoff_frequency_mhz * 2, -3.0 + 5),
                color=t["accent"], fontsize=8, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=t["accent"], lw=1),
            )

        # Required attenuation at failure frequencies as scatter points
        if failure_frequencies_mhz and required_attenuation_db:
            fail_freqs = np.array(failure_frequencies_mhz)
            req_atten = np.array(required_attenuation_db)
            ax1.scatter(
                fail_freqs, -req_atten, color=t["fail"], marker="x",
                s=100, linewidths=2, zorder=6,
                label="Required attenuation",
            )
            for ff, ra in zip(failure_frequencies_mhz, required_attenuation_db):
                ax1.annotate(
                    f"-{ra:.0f} dB", xy=(ff, -ra),
                    xytext=(5, 8), textcoords="offset points",
                    color=t["fail"], fontsize=7, fontweight="bold",
                )

        ax1.set_xlabel("Frequency (MHz)")
        ax1.set_ylabel("Insertion Loss (dB)")
        ax1.set_title(f"{topology} Insertion Loss")
        ax1.legend(fontsize=7, facecolor=t["bg"], edgecolor=t["grid"],
                   labelcolor=t["fg"], loc="lower left")
        ax1.set_ylim(min(il) * 1.15, 5)

        _add_methodology_box(
            ax1,
            f"pcb_design_emi_filter | {topology} | "
            f"Rs/Rl = 50\u03a9 | ABCD transfer matrix",
            t,
        )

        # --- Optional: before/after emission comparison ---
        if has_emission_overlay and ax2 is not None:
            ef = np.array(emission_freqs_mhz)
            orig = np.array(original_emission_dbuv)
            filt = np.array(filtered_emission_dbuv)

            ax2.semilogx(ef, orig, color=t["fail"], linewidth=1.5,
                         linestyle="--", label="Before filter", alpha=0.8)
            ax2.semilogx(ef, filt, color=t["pass"], linewidth=2,
                         label="After filter")

            if limit_dbuv is not None:
                ax2.axhline(y=limit_dbuv, color=t["limit"], linestyle="--",
                            linewidth=1.5, label=f"Limit: {limit_dbuv} dBuV/m")
                ax2.fill_between(ef, filt, limit_dbuv,
                                 where=(filt > limit_dbuv),
                                 alpha=0.15, color=t["fail"])

            ax2.set_xlabel("Frequency (MHz)")
            ax2.set_ylabel("Emission Level (dBuV/m)")
            ax2.set_title("Before / After Filtering")
            ax2.legend(fontsize=7, facecolor=t["bg"], edgecolor=t["grid"],
                       labelcolor=t["fg"])

        if has_emission_overlay:
            fig.suptitle(
                f"EMI Filter Design \u2014 {topology}",
                color=t["fg"], fontsize=13, fontweight="bold",
            )
            fig.tight_layout(rect=[0, 0, 1, 0.93])

        _add_status_badge(ax1, status, t)

        return self._save(fig, "filter_response")

    # ------------------------------------------------------------------
    # 13. Immunity Margin Analysis (horizontal bar chart)
    # ------------------------------------------------------------------
    def immunity_margin_plot(
        self,
        interface_results: Optional[list[dict]] = None,
        iso_level: int = 3,
        status: str = "WARNING",
    ) -> str:
        """Generate immunity margin horizontal bar chart.

        Green bars for positive margin (pass), red for negative (fail),
        orange for marginal (< 6 dB).  Marks the 0 dB reference line
        (upset threshold) and labels each bar with its margin value.

        Parameters
        ----------
        interface_results : list[dict]
            Each dict must contain: interface_name, coupling_type,
            upset_margin_db, status.
        iso_level : int
            ISO 11452 level (for title).
        status : str
            Overall badge status.

        Returns
        -------
        str : Path to saved PNG file.
        """
        t = self.theme
        fig, ax = plt.subplots(figsize=self.figsize)
        _apply_theme(ax, t)

        if interface_results is None:
            interface_results = [
                {"interface_name": "USB", "coupling_type": "electric_field",
                 "upset_margin_db": 12.3, "status": "pass"},
                {"interface_name": "USB", "coupling_type": "bci",
                 "upset_margin_db": 4.1, "status": "marginal"},
                {"interface_name": "CAN bus", "coupling_type": "electric_field",
                 "upset_margin_db": -3.5, "status": "fail"},
                {"interface_name": "CAN bus", "coupling_type": "bci",
                 "upset_margin_db": -8.2, "status": "fail"},
                {"interface_name": "Ethernet", "coupling_type": "electric_field",
                 "upset_margin_db": 18.0, "status": "pass"},
                {"interface_name": "Ethernet", "coupling_type": "bci",
                 "upset_margin_db": 9.7, "status": "pass"},
            ]

        labels = [
            f"{r['interface_name']} ({r['coupling_type']})"
            for r in interface_results
        ]
        margins = [r["upset_margin_db"] for r in interface_results]

        bar_colors = []
        for m in margins:
            if m < 0:
                bar_colors.append(t["fail"])
            elif m < 6:
                bar_colors.append(t["marginal"])
            else:
                bar_colors.append(t["pass"])

        y_pos = np.arange(len(labels))
        bars = ax.barh(y_pos, margins, height=0.55, color=bar_colors, alpha=0.85,
                       edgecolor="none")

        # 0 dB reference line (threshold)
        ax.axvline(x=0, color=t["limit"], linewidth=2, linestyle="-",
                   label="Upset threshold (0 dB)")

        # 6 dB margin guideline
        ax.axvline(x=6, color=t["warning"], linewidth=1, linestyle="--",
                   alpha=0.6, label="6 dB margin guideline")

        # Label each bar with the margin value
        for i, (margin, bar) in enumerate(zip(margins, bars)):
            x_pos_text = margin + (1.0 if margin >= 0 else -1.0)
            ha = "left" if margin >= 0 else "right"
            ax.text(x_pos_text, i, f"{margin:+.1f} dB",
                    va="center", ha=ha, fontsize=8, fontweight="bold",
                    color=t["fg"])

        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=8)
        ax.set_xlabel("Margin (dB)")

        roman_numerals = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}
        level_str = roman_numerals.get(iso_level, str(iso_level))
        ax.set_title(
            f"Immunity Margin Analysis \u2014 ISO 11452 Level {level_str}"
        )
        ax.invert_yaxis()

        # Legend
        from matplotlib.lines import Line2D
        legend_elements = [
            Line2D([0], [0], color=t["limit"], linewidth=2, linestyle="-",
                   label="Upset threshold (0 dB)"),
            Line2D([0], [0], color=t["warning"], linewidth=1, linestyle="--",
                   label="6 dB guideline"),
            Line2D([0], [0], color=t["pass"], linewidth=6, linestyle="-",
                   label="Pass (> 6 dB)", alpha=0.85),
            Line2D([0], [0], color=t["marginal"], linewidth=6, linestyle="-",
                   label="Marginal (0\u20136 dB)", alpha=0.85),
            Line2D([0], [0], color=t["fail"], linewidth=6, linestyle="-",
                   label="Fail (< 0 dB)", alpha=0.85),
        ]
        ax.legend(handles=legend_elements, fontsize=7,
                  facecolor=t["bg"], edgecolor=t["grid"], labelcolor=t["fg"],
                  loc="lower right")

        _add_status_badge(ax, status, t)
        _add_methodology_box(
            ax,
            f"pcb_analyze_immunity_margin | ISO 11452 Level {iso_level} | "
            f"E-field + BCI coupling model",
            t,
        )

        return self._save(fig, "immunity_margin")

    # ------------------------------------------------------------------
    # 14. Generate all standard plots
    # ------------------------------------------------------------------
    def generate_all(self, **kwargs) -> dict[str, str]:
        """Generate all standard simulation plots. Returns {name: path}."""
        plots = {}
        plots["eye_diagram"] = self.eye_diagram(**kwargs.get("eye_diagram", {}))
        plots["s_parameters"] = self.s_parameter_plot(**kwargs.get("s_parameters", {}))
        plots["pdn_impedance"] = self.pdn_impedance(**kwargs.get("pdn_impedance", {}))
        plots["clock_emi_spectrum"] = self.clock_emi_spectrum(**kwargs.get("clock_emi", {}))
        plots["cispr25_compliance"] = self.cispr25_compliance(**kwargs.get("cispr25", {}))
        plots["cavity_resonance"] = self.cavity_resonance(**kwargs.get("cavity_resonance", {}))
        plots["thermal_budget"] = self.thermal_budget(**kwargs.get("thermal", {}))
        plots["impedance_profile"] = self.impedance_profile(**kwargs.get("impedance", {}))
        plots["conducted_emissions"] = self.conducted_emissions_plot(
            **kwargs.get("conducted_emissions", {}))
        plots["near_field_emi"] = self.near_field_plot(
            **kwargs.get("near_field", {}))
        plots["filter_response"] = self.filter_response_plot(
            **kwargs.get("filter_response", {}))
        plots["immunity_margin"] = self.immunity_margin_plot(
            **kwargs.get("immunity_margin", {}))
        return plots

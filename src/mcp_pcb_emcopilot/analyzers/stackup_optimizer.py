"""Stackup optimization with comparative analysis.

Generates alternative stackup proposals and compares impedance, insertion loss,
cavity resonance, and cost/complexity across variants.  Supports 2- through
12-layer stackups with FR-4, mid-Tg, and high-speed laminate materials.

Issue #40
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------
C0 = 299792458.0  # Speed of light (m/s)
MU0 = 4 * math.pi * 1e-7  # Permeability of free space (H/m)
EPS0 = 8.854e-12  # Permittivity of free space (F/m)

# Copper conductivity (S/m)
_COPPER_CONDUCTIVITY = 5.8e7

# ---------------------------------------------------------------------------
# Key frequencies for insertion-loss comparison
# ---------------------------------------------------------------------------
KEY_FREQUENCIES: dict[str, float] = {
    "Ethernet_625MHz": 625e6,
    "DDR_1.6GHz": 1.6e9,
    "USB_5GHz": 5e9,
    "PCIe_8GHz": 8e9,
}

# ---------------------------------------------------------------------------
# Material library
# ---------------------------------------------------------------------------
MATERIAL_LIBRARY: dict[str, dict] = {
    "FR4_standard": {
        "description": "Standard FR-4 (Tg 130-140C)",
        "dielectric_constant": 4.3,
        "loss_tangent": 0.020,
        "cost_factor": 1.0,
    },
    "FR4_mid_tg": {
        "description": "Mid-Tg FR-4 (Tg 150-170C)",
        "dielectric_constant": 4.2,
        "loss_tangent": 0.016,
        "cost_factor": 1.2,
    },
    "high_speed": {
        "description": "High-speed laminate (Megtron 6 class)",
        "dielectric_constant": 3.6,
        "loss_tangent": 0.004,
        "cost_factor": 3.0,
    },
    "rogers": {
        "description": "Rogers 4350B RF laminate",
        "dielectric_constant": 3.48,
        "loss_tangent": 0.0037,
        "cost_factor": 5.0,
    },
}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ImpedanceResult:
    """Single-ended or differential impedance for one layer."""
    layer_name: str
    trace_type: str  # "microstrip" or "stripline"
    impedance_ohm: float
    effective_dielectric: float
    width_mm: float
    height_mm: float  # dielectric height to reference plane
    dielectric_constant: float

    def to_dict(self) -> dict:
        return {
            "layer_name": self.layer_name,
            "trace_type": self.trace_type,
            "impedance_ohm": round(self.impedance_ohm, 2),
            "effective_dielectric": round(self.effective_dielectric, 3),
            "width_mm": round(self.width_mm, 4),
            "height_mm": round(self.height_mm, 4),
            "dielectric_constant": round(self.dielectric_constant, 3),
        }


@dataclass
class StackupLayer:
    """A single layer in a stackup variant."""
    name: str
    layer_type: str  # "signal", "plane", "dielectric"
    thickness_mm: float
    material: str = "FR4_standard"
    copper_weight_oz: float = 1.0

    @property
    def is_copper(self) -> bool:
        return self.layer_type in ("signal", "plane")


@dataclass
class StackupVariant:
    """One complete stackup proposal."""
    name: str
    layers: list[StackupLayer] = field(default_factory=list)
    material: str = "FR4_standard"
    total_thickness_mm: float = 0.0
    layer_count: int = 0
    signal_layer_count: int = 0
    plane_layer_count: int = 0
    impedance_results: list[ImpedanceResult] = field(default_factory=list)
    insertion_loss_db: dict[str, dict[str, float]] = field(default_factory=dict)
    cavity_resonances_mhz: list[float] = field(default_factory=list)
    cost_score: float = 0.0
    complexity_score: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "material": self.material,
            "layer_count": self.layer_count,
            "signal_layer_count": self.signal_layer_count,
            "plane_layer_count": self.plane_layer_count,
            "total_thickness_mm": round(self.total_thickness_mm, 3),
            "layers": [
                {
                    "name": ly.name,
                    "type": ly.layer_type,
                    "thickness_mm": round(ly.thickness_mm, 4),
                    "material": ly.material,
                }
                for ly in self.layers
            ],
            "impedance_results": [r.to_dict() for r in self.impedance_results],
            "insertion_loss_db": {
                freq_label: {
                    layer: round(val, 4)
                    for layer, val in layers.items()
                }
                for freq_label, layers in self.insertion_loss_db.items()
            },
            "cavity_resonances_mhz": [round(f, 1) for f in self.cavity_resonances_mhz],
            "cost_score": round(self.cost_score, 2),
            "complexity_score": round(self.complexity_score, 2),
            "notes": self.notes,
        }


@dataclass
class StackupComparison:
    """Side-by-side comparison of multiple stackup variants."""
    impedance_comparison: dict[str, list[dict]] = field(default_factory=dict)
    insertion_loss_comparison: dict[str, dict[str, dict[str, float]]] = field(
        default_factory=dict
    )
    resonance_comparison: dict[str, list[float]] = field(default_factory=dict)
    cost_comparison: dict[str, float] = field(default_factory=dict)
    best_impedance_variant: str = ""
    best_loss_variant: str = ""
    best_cost_variant: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "impedance_comparison": self.impedance_comparison,
            "insertion_loss_comparison": {
                variant: {
                    freq: {layer: round(v, 4) for layer, v in layers.items()}
                    for freq, layers in freqs.items()
                }
                for variant, freqs in self.insertion_loss_comparison.items()
            },
            "resonance_comparison": {
                k: [round(f, 1) for f in v]
                for k, v in self.resonance_comparison.items()
            },
            "cost_comparison": {k: round(v, 2) for k, v in self.cost_comparison.items()},
            "best_impedance_variant": self.best_impedance_variant,
            "best_loss_variant": self.best_loss_variant,
            "best_cost_variant": self.best_cost_variant,
            "recommendation": self.recommendation,
        }


@dataclass
class StackupOptimizationResult:
    """Top-level result returned by the optimizer."""
    success: bool = True
    variants: list[StackupVariant] = field(default_factory=list)
    comparison: Optional[StackupComparison] = None
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "variants": [v.to_dict() for v in self.variants],
            "comparison": self.comparison.to_dict() if self.comparison else {},
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# StackupOptimizer
# ---------------------------------------------------------------------------

class StackupOptimizer:
    """Generate and compare alternative PCB stackup proposals.

    Usage::

        opt = StackupOptimizer()
        result = opt.optimize(
            target_layer_count=4,
            target_impedance_ohm=50.0,
            board_width_mm=100.0,
            board_height_mm=80.0,
        )
        for v in result.variants:
            print(v.name, v.cost_score)
    """

    # Default trace width for impedance calculations (mm)
    DEFAULT_TRACE_WIDTH_MM = 0.127  # ~5 mil
    # Default copper thickness per oz (mm)
    COPPER_OZ_TO_MM = 0.035
    # Default trace length for insertion-loss estimate (mm)
    DEFAULT_TRACE_LENGTH_MM = 50.0

    def optimize(
        self,
        target_layer_count: int = 4,
        target_impedance_ohm: float = 50.0,
        board_width_mm: float = 100.0,
        board_height_mm: float = 80.0,
        materials: Optional[list[str]] = None,
        trace_width_mm: Optional[float] = None,
        trace_length_mm: Optional[float] = None,
        max_frequency_hz: float = 10e9,
    ) -> StackupOptimizationResult:
        """Run full stackup optimization.

        Parameters
        ----------
        target_layer_count : int
            Desired copper layer count (2, 4, 6, 8, ...).
        target_impedance_ohm : float
            Target single-ended impedance in ohms.
        board_width_mm, board_height_mm : float
            Board dimensions for cavity resonance calculation.
        materials : list[str] | None
            Material keys from ``MATERIAL_LIBRARY`` to evaluate.
            Defaults to ``["FR4_standard", "FR4_mid_tg", "high_speed"]``.
        trace_width_mm : float | None
            Override trace width for impedance calc.
        trace_length_mm : float | None
            Trace length for insertion-loss estimate.
        max_frequency_hz : float
            Upper frequency for cavity resonance search.

        Returns
        -------
        StackupOptimizationResult
        """
        if materials is None:
            materials = ["FR4_standard", "FR4_mid_tg", "high_speed"]

        tw = trace_width_mm or self.DEFAULT_TRACE_WIDTH_MM
        tl = trace_length_mm or self.DEFAULT_TRACE_LENGTH_MM

        variants: list[StackupVariant] = []
        for mat_key in materials:
            mat = MATERIAL_LIBRARY.get(mat_key)
            if mat is None:
                continue

            variant = self.generate_stackup(
                layer_count=target_layer_count,
                material=mat_key,
            )

            # Impedance per signal layer
            self.calculate_impedances(variant, tw)

            # Insertion loss at key frequencies
            self.calculate_insertion_loss(variant, tw, tl)

            # Cavity resonances
            self.calculate_cavity_resonances(
                variant,
                board_width_mm,
                board_height_mm,
                max_frequency_hz,
            )

            # Cost / complexity scoring
            self.calculate_cost_score(variant)

            variants.append(variant)

        comparison = self.compare_variants(variants, target_impedance_ohm)

        summary_parts: list[str] = []
        summary_parts.append(
            f"Generated {len(variants)} stackup variant(s) for a "
            f"{target_layer_count}-layer board."
        )
        if comparison:
            if comparison.best_impedance_variant:
                summary_parts.append(
                    f"Best impedance match: {comparison.best_impedance_variant}."
                )
            if comparison.best_loss_variant:
                summary_parts.append(
                    f"Lowest insertion loss: {comparison.best_loss_variant}."
                )
            if comparison.best_cost_variant:
                summary_parts.append(
                    f"Lowest cost: {comparison.best_cost_variant}."
                )
            if comparison.recommendation:
                summary_parts.append(comparison.recommendation)

        return StackupOptimizationResult(
            success=True,
            variants=variants,
            comparison=comparison,
            summary=" ".join(summary_parts),
        )

    # ------------------------------------------------------------------
    # Stackup generation
    # ------------------------------------------------------------------

    def generate_stackup(
        self,
        layer_count: int = 4,
        material: str = "FR4_standard",
    ) -> StackupVariant:
        """Build a symmetric stackup for the given layer count and material.

        Supports layer counts of 1, 2, 4, 6, 8, 10, 12.
        Odd counts > 1 are rounded up to the next even number.
        """
        mat_info = MATERIAL_LIBRARY.get(material, MATERIAL_LIBRARY["FR4_standard"])

        # Clamp to sane range
        lc = max(1, layer_count)
        if lc > 1 and lc % 2 != 0:
            lc += 1  # round up to even

        layers: list[StackupLayer] = []

        if lc == 1:
            # Single-sided board
            layers.append(StackupLayer(
                name="Top", layer_type="signal",
                thickness_mm=self.COPPER_OZ_TO_MM, material=material,
            ))
            layers.append(StackupLayer(
                name="Core", layer_type="dielectric",
                thickness_mm=1.5, material=material,
            ))
        elif lc == 2:
            layers = self._build_2_layer(material)
        elif lc == 4:
            layers = self._build_4_layer(material)
        elif lc == 6:
            layers = self._build_6_layer(material)
        elif lc == 8:
            layers = self._build_8_layer(material)
        else:
            layers = self._build_generic_even(lc, material)

        total = sum(ly.thickness_mm for ly in layers)
        copper_layers = [ly for ly in layers if ly.is_copper]
        signal_layers = [ly for ly in layers if ly.layer_type == "signal"]
        plane_layers = [ly for ly in layers if ly.layer_type == "plane"]

        variant = StackupVariant(
            name=f"{lc}L-{mat_info['description'][:20]}",
            layers=layers,
            material=material,
            total_thickness_mm=total,
            layer_count=len(copper_layers),
            signal_layer_count=len(signal_layers),
            plane_layer_count=len(plane_layers),
        )
        return variant

    # -- helpers for common stackups --

    def _build_2_layer(self, material: str) -> list[StackupLayer]:
        cu = self.COPPER_OZ_TO_MM
        return [
            StackupLayer("Top", "signal", cu, material),
            StackupLayer("Core", "dielectric", 1.5, material),
            StackupLayer("Bottom", "signal", cu, material),
        ]

    def _build_4_layer(self, material: str) -> list[StackupLayer]:
        cu = self.COPPER_OZ_TO_MM
        return [
            StackupLayer("Top", "signal", cu, material),
            StackupLayer("Prepreg1", "dielectric", 0.2, material),
            StackupLayer("GND", "plane", cu, material),
            StackupLayer("Core", "dielectric", 1.0, material),
            StackupLayer("PWR", "plane", cu, material),
            StackupLayer("Prepreg2", "dielectric", 0.2, material),
            StackupLayer("Bottom", "signal", cu, material),
        ]

    def _build_6_layer(self, material: str) -> list[StackupLayer]:
        cu = self.COPPER_OZ_TO_MM
        return [
            StackupLayer("Top", "signal", cu, material),
            StackupLayer("Prepreg1", "dielectric", 0.15, material),
            StackupLayer("GND1", "plane", cu, material),
            StackupLayer("Core1", "dielectric", 0.3, material),
            StackupLayer("Sig2", "signal", cu, material),
            StackupLayer("Prepreg2", "dielectric", 0.3, material),
            StackupLayer("GND2", "plane", cu, material),
            StackupLayer("Core2", "dielectric", 0.3, material),
            StackupLayer("PWR", "plane", cu, material),
            StackupLayer("Prepreg3", "dielectric", 0.15, material),
            StackupLayer("Bottom", "signal", cu, material),
        ]

    def _build_8_layer(self, material: str) -> list[StackupLayer]:
        cu = self.COPPER_OZ_TO_MM
        return [
            StackupLayer("Top", "signal", cu, material),
            StackupLayer("Prepreg1", "dielectric", 0.1, material),
            StackupLayer("GND1", "plane", cu, material),
            StackupLayer("Core1", "dielectric", 0.2, material),
            StackupLayer("Sig2", "signal", cu, material),
            StackupLayer("Prepreg2", "dielectric", 0.2, material),
            StackupLayer("PWR1", "plane", cu, material),
            StackupLayer("Core2", "dielectric", 0.2, material),
            StackupLayer("GND2", "plane", cu, material),
            StackupLayer("Prepreg3", "dielectric", 0.2, material),
            StackupLayer("Sig3", "signal", cu, material),
            StackupLayer("Core3", "dielectric", 0.2, material),
            StackupLayer("PWR2", "plane", cu, material),
            StackupLayer("Prepreg4", "dielectric", 0.1, material),
            StackupLayer("Bottom", "signal", cu, material),
        ]

    def _build_generic_even(self, lc: int, material: str) -> list[StackupLayer]:
        """Fallback for 10, 12, ... layers."""
        cu = self.COPPER_OZ_TO_MM
        # Target ~1.6mm total thickness
        n_dielectric = lc  # number of dielectric gaps = lc (approx)
        die_thickness = max(0.08, (1.6 - lc * cu) / n_dielectric)

        layers: list[StackupLayer] = []
        for i in range(lc):
            if i == 0:
                ltype = "signal"
                name = "Top"
            elif i == lc - 1:
                ltype = "signal"
                name = "Bottom"
            elif i % 2 == 1:
                ltype = "plane"
                name = f"Plane{i}"
            else:
                ltype = "signal"
                name = f"Sig{i}"

            layers.append(StackupLayer(name, ltype, cu, material))
            if i < lc - 1:
                dname = f"Die{i}" if i % 2 == 0 else f"Core{i}"
                layers.append(StackupLayer(dname, "dielectric", die_thickness, material))

        return layers

    # ------------------------------------------------------------------
    # Impedance calculation
    # ------------------------------------------------------------------

    def calculate_impedances(
        self,
        variant: StackupVariant,
        trace_width_mm: float,
    ) -> None:
        """Calculate impedance for every signal layer in *variant*."""
        mat = MATERIAL_LIBRARY.get(variant.material, MATERIAL_LIBRARY["FR4_standard"])
        er = mat["dielectric_constant"]

        variant.impedance_results = []

        signal_layers = [ly for ly in variant.layers if ly.layer_type == "signal"]

        for sig in signal_layers:
            # Find nearest reference plane (above or below)
            idx = variant.layers.index(sig)
            h_mm = self._distance_to_nearest_plane(variant.layers, idx)

            if h_mm <= 0:
                # No reference plane found: assume full board thickness
                h_mm = variant.total_thickness_mm

            trace_type = self._classify_trace_type(variant.layers, idx)

            if trace_type == "microstrip":
                z0, eps_eff = self._calc_microstrip(trace_width_mm, h_mm, er)
            else:
                z0, eps_eff = self._calc_stripline(trace_width_mm, h_mm, er)

            variant.impedance_results.append(ImpedanceResult(
                layer_name=sig.name,
                trace_type=trace_type,
                impedance_ohm=z0,
                effective_dielectric=eps_eff,
                width_mm=trace_width_mm,
                height_mm=h_mm,
                dielectric_constant=er,
            ))

    def _distance_to_nearest_plane(
        self, layers: list[StackupLayer], sig_idx: int
    ) -> float:
        """Sum dielectric thickness from signal layer to nearest plane."""
        # Search downward
        down = self._distance_to_plane(layers, sig_idx, direction=1)
        # Search upward
        up = self._distance_to_plane(layers, sig_idx, direction=-1)

        candidates = [d for d in (down, up) if d > 0]
        return min(candidates) if candidates else 0.0

    @staticmethod
    def _distance_to_plane(
        layers: list[StackupLayer], start_idx: int, direction: int
    ) -> float:
        """Walk in *direction* (+1 down, -1 up) accumulating dielectric."""
        total = 0.0
        idx = start_idx + direction
        while 0 <= idx < len(layers):
            ly = layers[idx]
            if ly.layer_type == "dielectric":
                total += ly.thickness_mm
            elif ly.layer_type == "plane":
                return total
            elif ly.layer_type == "signal":
                # Another signal layer, not a plane reference
                return 0.0
            idx += direction
        return 0.0  # no plane found

    @staticmethod
    def _classify_trace_type(layers: list[StackupLayer], sig_idx: int) -> str:
        """Return 'microstrip' if the signal layer is on the outside, else 'stripline'."""
        # Check if there's a plane both above and below
        has_plane_above = False
        has_plane_below = False
        for i in range(sig_idx - 1, -1, -1):
            if layers[i].layer_type == "plane":
                has_plane_above = True
                break
            if layers[i].layer_type == "signal":
                break
        for i in range(sig_idx + 1, len(layers)):
            if layers[i].layer_type == "plane":
                has_plane_below = True
                break
            if layers[i].layer_type == "signal":
                break
        if has_plane_above and has_plane_below:
            return "stripline"
        return "microstrip"

    # -- impedance formulas ---

    @staticmethod
    def _calc_microstrip(
        w_mm: float, h_mm: float, er: float, t_mm: float = 0.035
    ) -> tuple[float, float]:
        """Hammerstad-Jensen microstrip impedance. Returns (Z0, eps_eff)."""
        if h_mm <= 0 or w_mm <= 0:
            return (0.0, er)

        # Effective width
        if w_mm / h_mm < 0.5 * math.pi:
            w_eff = w_mm + t_mm / math.pi * (
                1 + math.log(4 * math.pi * w_mm / t_mm)
            )
        else:
            w_eff = w_mm + t_mm / math.pi * (
                1 + math.log(2 * h_mm / t_mm)
            )

        w_h = w_eff / h_mm

        if w_h <= 1:
            eps_eff = (er + 1) / 2 + (er - 1) / 2 * (
                1 / math.sqrt(1 + 12 / w_h) + 0.04 * (1 - w_h) ** 2
            )
        else:
            eps_eff = (er + 1) / 2 + (er - 1) / 2 / math.sqrt(1 + 12 / w_h)

        if w_h <= 1:
            z0 = 60 / math.sqrt(eps_eff) * math.log(8 / w_h + w_h / 4)
        else:
            z0 = 120 * math.pi / math.sqrt(eps_eff) / (
                w_h + 1.393 + 0.667 * math.log(w_h + 1.444)
            )

        return (z0, eps_eff)

    @staticmethod
    def _calc_stripline(
        w_mm: float, h_mm: float, er: float, t_mm: float = 0.035
    ) -> tuple[float, float]:
        """Symmetric stripline impedance (Cohn/Wheeler). Returns (Z0, eps_eff)."""
        if h_mm <= 0 or w_mm <= 0:
            return (0.0, er)

        b = 2 * h_mm  # total height between planes

        w_eff = w_mm
        t_b = t_mm / b
        w_b = w_eff / b

        if w_b < 0.35:
            arg = math.pi * w_eff / (2 * b)
            k = math.cosh(arg) if arg < 700 else 1e300
            if k > 0:
                z0 = 30 * math.pi / math.sqrt(er) / k
            else:
                z0 = 0.0
        else:
            cf = (1 - t_b) * (0.0885 * er + 0.3)
            z0 = 30 * math.pi / math.sqrt(er) * b / (w_eff + cf * b)

        eps_eff = er  # stripline: effective Er = bulk Er
        return (z0, eps_eff)

    # ------------------------------------------------------------------
    # Insertion loss
    # ------------------------------------------------------------------

    def calculate_insertion_loss(
        self,
        variant: StackupVariant,
        trace_width_mm: float,
        trace_length_mm: float,
    ) -> None:
        """Estimate total insertion loss (conductor + dielectric) for each
        signal layer at each key frequency.

        Results stored in ``variant.insertion_loss_db``.
        """
        mat = MATERIAL_LIBRARY.get(variant.material, MATERIAL_LIBRARY["FR4_standard"])
        er = mat["dielectric_constant"]
        tan_d = mat["loss_tangent"]

        variant.insertion_loss_db = {}

        for freq_label, freq_hz in KEY_FREQUENCIES.items():
            layer_losses: dict[str, float] = {}

            for imp_res in variant.impedance_results:
                eps_eff = imp_res.effective_dielectric
                z0 = imp_res.impedance_ohm
                if z0 <= 0:
                    layer_losses[imp_res.layer_name] = 0.0
                    continue

                # Conductor loss  (dB/mm)
                omega = 2 * math.pi * freq_hz
                skin_depth = math.sqrt(2 / (omega * MU0 * _COPPER_CONDUCTIVITY))
                rs = 1 / (_COPPER_CONDUCTIVITY * skin_depth)
                w_m = trace_width_mm / 1000
                alpha_c_db_m = 8.686 * rs / (z0 * w_m)
                alpha_c_db_mm = alpha_c_db_m / 1000

                # Dielectric loss  (dB/mm)
                lambda_0_mm = C0 / freq_hz * 1000
                alpha_d_np_mm = math.pi * math.sqrt(eps_eff) * tan_d / lambda_0_mm
                alpha_d_db_mm = alpha_d_np_mm * 8.686

                total_loss_db = (alpha_c_db_mm + alpha_d_db_mm) * trace_length_mm
                layer_losses[imp_res.layer_name] = total_loss_db

            variant.insertion_loss_db[freq_label] = layer_losses

    # ------------------------------------------------------------------
    # Cavity resonance
    # ------------------------------------------------------------------

    def calculate_cavity_resonances(
        self,
        variant: StackupVariant,
        board_width_mm: float,
        board_height_mm: float,
        max_frequency_hz: float = 10e9,
    ) -> None:
        """Find plane-pair cavity resonances for the variant.

        Considers each adjacent pair of plane layers (including signal layers
        adjacent to planes are skipped -- only plane-to-plane cavities).
        """
        mat = MATERIAL_LIBRARY.get(variant.material, MATERIAL_LIBRARY["FR4_standard"])
        er = mat["dielectric_constant"]

        variant.cavity_resonances_mhz = []

        # Find all plane-pair cavities
        plane_indices = [
            i for i, ly in enumerate(variant.layers)
            if ly.layer_type == "plane"
        ]

        if len(plane_indices) < 2:
            # For 2-layer boards or stackups without two planes, use the two
            # outer copper layers (signal-signal) as the cavity
            copper_indices = [
                i for i, ly in enumerate(variant.layers) if ly.is_copper
            ]
            if len(copper_indices) >= 2:
                plane_indices = [copper_indices[0], copper_indices[-1]]
            else:
                return

        for i in range(len(plane_indices) - 1):
            idx_a = plane_indices[i]
            idx_b = plane_indices[i + 1]

            # Dielectric height between the two planes
            h_mm = sum(
                ly.thickness_mm
                for ly in variant.layers[idx_a + 1 : idx_b]
                if ly.layer_type == "dielectric"
            )
            # Also add copper of any embedded signal layers
            h_mm += sum(
                ly.thickness_mm
                for ly in variant.layers[idx_a + 1 : idx_b]
                if ly.layer_type == "signal"
            )

            if h_mm <= 0:
                continue

            resonances = self._cavity_modes(
                board_width_mm, board_height_mm, er, max_frequency_hz
            )
            variant.cavity_resonances_mhz.extend(resonances)

        # Remove duplicates and sort
        variant.cavity_resonances_mhz = sorted(set(
            round(f, 1) for f in variant.cavity_resonances_mhz
        ))

    @staticmethod
    def _cavity_modes(
        a_mm: float, b_mm: float, er: float, max_freq_hz: float
    ) -> list[float]:
        """TM_mn cavity resonance frequencies in MHz."""
        a = a_mm / 1000.0
        b = b_mm / 1000.0
        v = C0 / math.sqrt(er)

        max_m = int(2 * a * max_freq_hz / v) + 2
        max_n = int(2 * b * max_freq_hz / v) + 2

        modes: list[float] = []
        for m in range(0, max_m + 1):
            for n in range(0, max_n + 1):
                if m == 0 and n == 0:
                    continue
                f_mn = (v / 2) * math.sqrt((m / a) ** 2 + (n / b) ** 2)
                if f_mn <= max_freq_hz:
                    modes.append(f_mn / 1e6)  # MHz
        return modes

    # ------------------------------------------------------------------
    # Cost / complexity scoring
    # ------------------------------------------------------------------

    def calculate_cost_score(self, variant: StackupVariant) -> None:
        """Assign a relative cost and complexity score (1 = cheapest)."""
        mat = MATERIAL_LIBRARY.get(variant.material, MATERIAL_LIBRARY["FR4_standard"])
        cost_factor = mat["cost_factor"]

        # Base cost scales roughly with layer count squared (fabrication)
        lc = variant.layer_count
        base_cost = lc ** 1.5

        # Material cost multiplier
        variant.cost_score = round(base_cost * cost_factor, 2)

        # Complexity: driven by layer count and HDI considerations
        complexity = 1.0
        if lc >= 8:
            complexity += 1.0  # sequential lamination likely
        if lc >= 10:
            complexity += 1.0  # HDI may be needed
        if any(
            ly.thickness_mm < 0.1
            for ly in variant.layers
            if ly.layer_type == "dielectric"
        ):
            complexity += 0.5  # thin dielectrics harder to manufacture

        variant.complexity_score = round(complexity, 2)

        # Notes
        variant.notes = []
        if lc <= 2:
            variant.notes.append("Simple 2-layer; limited routing and EMC performance.")
        elif lc == 4:
            variant.notes.append("Standard 4-layer with dedicated GND and PWR planes.")
        elif lc == 6:
            variant.notes.append("6-layer provides extra routing with embedded signal layer.")
        elif lc >= 8:
            variant.notes.append(
                f"{lc}-layer stackup; may require sequential lamination."
            )

        if cost_factor >= 3.0:
            variant.notes.append("Premium laminate improves loss but raises cost significantly.")

    # ------------------------------------------------------------------
    # Comparative analysis
    # ------------------------------------------------------------------

    def compare_variants(
        self,
        variants: list[StackupVariant],
        target_impedance_ohm: float = 50.0,
    ) -> StackupComparison:
        """Build side-by-side comparison of *variants*."""
        comp = StackupComparison()

        if not variants:
            return comp

        # --- impedance comparison ---
        best_imp_name = ""
        best_imp_error = float("inf")
        for v in variants:
            results_dicts = [r.to_dict() for r in v.impedance_results]
            comp.impedance_comparison[v.name] = results_dicts

            # Average impedance error vs target
            if v.impedance_results:
                avg_err = sum(
                    abs(r.impedance_ohm - target_impedance_ohm)
                    for r in v.impedance_results
                ) / len(v.impedance_results)
                if avg_err < best_imp_error:
                    best_imp_error = avg_err
                    best_imp_name = v.name

        comp.best_impedance_variant = best_imp_name

        # --- insertion-loss comparison ---
        best_loss_name = ""
        best_loss_total = float("inf")
        for v in variants:
            comp.insertion_loss_comparison[v.name] = v.insertion_loss_db

            total_loss = sum(
                val
                for layers in v.insertion_loss_db.values()
                for val in layers.values()
            )
            if total_loss < best_loss_total:
                best_loss_total = total_loss
                best_loss_name = v.name

        comp.best_loss_variant = best_loss_name

        # --- cavity resonance comparison ---
        for v in variants:
            comp.resonance_comparison[v.name] = v.cavity_resonances_mhz

        # --- cost comparison ---
        best_cost_name = ""
        best_cost = float("inf")
        for v in variants:
            comp.cost_comparison[v.name] = v.cost_score
            if v.cost_score < best_cost:
                best_cost = v.cost_score
                best_cost_name = v.name

        comp.best_cost_variant = best_cost_name

        # --- recommendation ---
        comp.recommendation = self._generate_recommendation(
            variants, target_impedance_ohm, comp
        )

        return comp

    @staticmethod
    def _generate_recommendation(
        variants: list[StackupVariant],
        target_z: float,
        comp: StackupComparison,
    ) -> str:
        """Produce a one-liner recommendation."""
        if not variants:
            return "No variants to compare."

        # Score each variant: lower is better
        # Weight: impedance match 40%, loss 30%, cost 30%
        scores: dict[str, float] = {}
        max_imp_err = 1.0
        max_loss = 1.0
        max_cost = 1.0

        imp_errors: dict[str, float] = {}
        loss_totals: dict[str, float] = {}
        for v in variants:
            if v.impedance_results:
                imp_errors[v.name] = sum(
                    abs(r.impedance_ohm - target_z)
                    for r in v.impedance_results
                ) / len(v.impedance_results)
            else:
                imp_errors[v.name] = 999.0
            loss_totals[v.name] = sum(
                val
                for layers in v.insertion_loss_db.values()
                for val in layers.values()
            )

        max_imp_err = max(imp_errors.values()) or 1.0
        max_loss = max(loss_totals.values()) or 1.0
        max_cost = max(v.cost_score for v in variants) or 1.0

        for v in variants:
            norm_imp = imp_errors[v.name] / max_imp_err
            norm_loss = loss_totals[v.name] / max_loss
            norm_cost = v.cost_score / max_cost
            scores[v.name] = 0.4 * norm_imp + 0.3 * norm_loss + 0.3 * norm_cost

        best = min(scores, key=scores.get)  # type: ignore[arg-type]
        return f"Recommended variant: {best} (weighted score {scores[best]:.2f})."

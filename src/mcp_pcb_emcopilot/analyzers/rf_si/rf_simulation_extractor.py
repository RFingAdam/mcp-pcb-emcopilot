"""
RF Simulation Extractor.

Extracts simulation candidates from a parsed PCB design for full-wave
EM validation via OpenEMS.  Identifies microstrip, stripline,
coupled differential pairs, and via transitions on RF / high-speed nets,
then returns them as findings (info severity) and as structured
SimulationCandidate objects.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ...models.pcb_data import PCBDesignData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Interface-frequency lookup (GHz)
# ---------------------------------------------------------------------------
INTERFACE_FREQUENCIES: Dict[str, float] = {
    "halow": 0.9,
    "wifi": 2.4,
    "bluetooth": 2.4,
    "usb": 0.48,
    "ddr": 1.6,
    "ethernet": 0.125,
    "emmc": 0.2,
    "pcie": 4.0,
}

# Priority by interface category (0-1, higher = more important to simulate)
INTERFACE_PRIORITY: Dict[str, float] = {
    "rf": 1.0,
    "pcie": 0.8,
    "usb": 0.8,
    "ddr": 0.7,
    "ethernet": 0.5,
    "emmc": 0.4,
}

# RF subcategories that get top priority (1.0)
_RF_TOP_SUBCATEGORIES = {"halow", "wifi", "bluetooth", "antenna"}

# Default target impedances for deviation calculation
_TARGET_Z0: Dict[str, float] = {
    "rf": 50.0,
    "usb": 90.0,
    "pcie": 85.0,
    "ddr": 50.0,
    "ethernet": 100.0,
    "emmc": 50.0,
}

# Maximum candidates returned by analyze() and to_candidates()
DEFAULT_MAX_CANDIDATES = 10

# Categories considered high-speed / RF
HS_CATEGORIES = {"rf", "usb", "ddr", "pcie", "ethernet", "emmc"}

# Maximum spacing (mm) for parallel-segment detection of diff pairs
MAX_DIFF_PAIR_SPACING_MM = 3.0


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class SimulationCandidate:
    """A PCB structure suitable for full-wave EM simulation."""

    name: str
    structure_type: str  # microstrip | stripline | coupled_microstrip | coupled_stripline | via_transition
    interface: str       # rf, usb, ddr, pcie, ethernet, emmc
    frequency_ghz: float
    priority: float

    # Geometry
    trace_width_mm: float = 0.0
    trace_length_mm: float = 0.0
    dielectric_height_mm: float = 0.0
    dielectric_er: float = 4.3
    copper_thickness_mm: float = 0.035
    layer_name: str = ""
    layer_type: str = ""  # microstrip | stripline

    # Differential pair
    spacing_mm: Optional[float] = None  # center-to-center P-N spacing

    # Via transition
    via_drill_mm: Optional[float] = None
    via_pad_mm: Optional[float] = None

    # Analytical reference
    z0_analytical: float = 0.0
    z_diff_analytical: Optional[float] = None

    # Source nets
    net_names: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Impedance formulas (same Hammerstad / stripline formulas used elsewhere)
# ---------------------------------------------------------------------------
def _microstrip_z0(w_mm: float, h_mm: float, er: float, t_mm: float = 0.035) -> float:
    """Hammerstad-Jensen microstrip impedance."""
    if w_mm <= 0 or h_mm <= 0 or er <= 0:
        return 0.0
    w_eff = w_mm + (t_mm / math.pi) * (1 + math.log(max(4 * math.pi * w_mm / t_mm, 1e-6)))
    u = w_eff / h_mm
    er_eff = (er + 1) / 2 + (er - 1) / 2 * (1 + 12 / max(u, 1e-6)) ** (-0.5)
    if u <= 1:
        return (60 / math.sqrt(er_eff)) * math.log(8 / u + u / 4)
    return (120 * math.pi) / (math.sqrt(er_eff) * (u + 1.393 + 0.667 * math.log(u + 1.444)))


def _stripline_z0(w_mm: float, b_mm: float, er: float, t_mm: float = 0.018) -> float:
    """Centered stripline impedance."""
    if w_mm <= 0 or b_mm <= 0 or er <= 0 or b_mm <= t_mm:
        return 0.0
    w_eff = w_mm + (t_mm / math.pi) * (1 + math.log(max(4 * math.pi * w_mm / t_mm, 1e-6)))
    m = 6 * (b_mm - t_mm) / (3 * b_mm - 2 * t_mm)
    denom = 0.67 * (0.8 + w_eff / (b_mm - t_mm))
    if denom <= 0 or m / denom <= 0:
        return 0.0
    return (60 / math.sqrt(er)) * math.log(m / denom)


def _diff_z0(z_se: float, s_mm: float, h_mm: float) -> float:
    """Approximate differential impedance from single-ended and spacing."""
    if z_se <= 0 or h_mm <= 0:
        return 0.0
    return 2 * z_se * (1 - 0.48 * math.exp(-0.96 * s_mm / h_mm))


# ---------------------------------------------------------------------------
# Priority / dedup / sort helpers
# ---------------------------------------------------------------------------

def _compute_priority(
    category: str,
    subcategory: Optional[str],
    structure_type: str,
    z_diff: Optional[float],
    z_se: float,
) -> float:
    """Assign a priority score following the documented rules.

    - RF signal nets with subcategory in (halow, wifi, bluetooth, antenna): 1.0
    - Differential pairs with >20% impedance deviation: 0.9
    - USB/PCIe single-ended: 0.8
    - DDR clock/strobe: 0.7
    - Via transitions on high-speed nets: 0.6
    - Ethernet: 0.5
    - eMMC/SDIO: 0.4
    - Everything else: 0.2
    """
    sub_lower = (subcategory or "").lower()

    # RF top-priority subcategories
    if category == "rf" and sub_lower in _RF_TOP_SUBCATEGORIES:
        return 1.0

    # Via transitions on any high-speed net
    if structure_type == "via_transition":
        return 0.6

    # Differential pair with >20% deviation from target
    if "coupled" in structure_type and z_diff is not None:
        target = _TARGET_Z0.get(category, 50.0)
        if target > 0 and abs(z_diff - target) / target > 0.20:
            return 0.9

    # USB / PCIe single-ended
    if category in ("usb", "pcie"):
        return 0.8

    # DDR clock/strobe
    if category == "ddr":
        return 0.7

    # Ethernet
    if category == "ethernet":
        return 0.5

    # eMMC / SDIO
    if category in ("emmc", "sdio"):
        return 0.4

    # RF without top subcategory still gets the base interface priority
    if category == "rf":
        return 1.0

    return 0.2


def _deduplicate_candidates(
    candidates: List[SimulationCandidate],
) -> List[SimulationCandidate]:
    """Deduplicate: same structure_type + layer + trace width (within 5%) -> keep longest."""
    buckets: Dict[tuple, SimulationCandidate] = {}
    for c in candidates:
        # Quantise width to 5% buckets
        w_bucket = round(c.trace_width_mm / max(c.trace_width_mm * 0.05, 0.001)) if c.trace_width_mm > 0 else 0
        key = (c.structure_type, c.layer_name.lower(), w_bucket)
        existing = buckets.get(key)
        if existing is None or c.trace_length_mm > existing.trace_length_mm:
            buckets[key] = c
    return list(buckets.values())


def _sort_candidates(
    candidates: List[SimulationCandidate],
) -> List[SimulationCandidate]:
    """Sort by priority (highest first), then by impedance deviation from target (largest first)."""
    def sort_key(c: SimulationCandidate) -> tuple:
        target = _TARGET_Z0.get(c.interface, 50.0)
        z_ref = c.z_diff_analytical if c.z_diff_analytical else c.z0_analytical
        deviation = abs(z_ref - target) if z_ref > 0 and target > 0 else 0.0
        return (-c.priority, -deviation)

    candidates.sort(key=sort_key)
    return candidates


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------
class RFSimulationExtractor:
    """Extracts simulation-worthy structures from a parsed PCB design."""

    # ------------------------------------------------------------------
    # Standard analyzer interface
    # ------------------------------------------------------------------
    def analyze(
        self,
        design: PCBDesignData,
        classified_nets: Any = None,
        interfaces: Any = None,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
    ) -> List[Dict[str, Any]]:
        """Analyze design and return findings (info-level) listing simulation candidates.

        This is the standard analyzer interface used by ``_run_generic_analyzer``.
        Returns at most *max_candidates* findings, deduplicated and prioritised.
        """
        candidates = self.extract(design, classified_nets)
        candidates = _deduplicate_candidates(candidates)
        candidates = _sort_candidates(candidates)
        candidates = candidates[:max_candidates]

        findings: List[Dict[str, Any]] = []
        for c in candidates:
            # Build actionable description
            nets_str = ", ".join(c.net_names[:3])
            target_z = _TARGET_Z0.get(c.interface, 50.0)
            z_ref = c.z_diff_analytical if c.z_diff_analytical else c.z0_analytical
            deviation_pct = abs(z_ref - target_z) / target_z * 100 if target_z > 0 and z_ref > 0 else 0.0

            desc_parts = [
                f"{c.structure_type} on {c.layer_name}",
                f"net {nets_str}",
                f"({c.interface} interface)",
                f"— w={c.trace_width_mm:.3f}mm, L={c.trace_length_mm:.1f}mm",
            ]
            if c.z_diff_analytical:
                desc_parts.append(
                    f"Zdiff={c.z_diff_analytical:.1f}\u03A9 (target {target_z:.0f}\u03A9, {deviation_pct:.0f}% dev)"
                )
            else:
                desc_parts.append(
                    f"Z0={c.z0_analytical:.1f}\u03A9 (target {target_z:.0f}\u03A9, {deviation_pct:.0f}% dev)"
                )
            desc_parts.append(f"@ {c.frequency_ghz}GHz.")

            sim_validates = "impedance and insertion loss"
            if "via" in c.structure_type:
                sim_validates = "via transition discontinuity and return loss"
            elif "coupled" in c.structure_type:
                sim_validates = "differential impedance, mode conversion, and skew"
            desc_parts.append(f"Simulation validates {sim_validates}.")

            findings.append({
                "severity": "info",
                "category": f"EM simulation candidate: {c.name}",
                "description": " ".join(desc_parts),
                "recommendation": (
                    "Run pcb_generate_em_simulation to get full-wave S-parameter validation."
                ),
                "details": {
                    "name": c.name,
                    "structure_type": c.structure_type,
                    "interface": c.interface,
                    "frequency_ghz": c.frequency_ghz,
                    "priority": c.priority,
                    "trace_width_mm": c.trace_width_mm,
                    "trace_length_mm": c.trace_length_mm,
                    "dielectric_height_mm": c.dielectric_height_mm,
                    "dielectric_er": c.dielectric_er,
                    "copper_thickness_mm": c.copper_thickness_mm,
                    "layer_name": c.layer_name,
                    "layer_type": c.layer_type,
                    "spacing_mm": c.spacing_mm,
                    "via_drill_mm": c.via_drill_mm,
                    "via_pad_mm": c.via_pad_mm,
                    "z0_analytical": round(c.z0_analytical, 2),
                    "z_diff_analytical": round(c.z_diff_analytical, 2) if c.z_diff_analytical else None,
                    "net_names": c.net_names,
                },
            })

        if not findings:
            findings.append({
                "severity": "info",
                "category": "EM simulation extraction",
                "description": "No RF/high-speed structures identified for EM simulation.",
                "recommendation": "Verify net classification includes RF or high-speed nets.",
            })

        return findings

    # ------------------------------------------------------------------
    # Core extraction
    # ------------------------------------------------------------------
    def extract(
        self,
        design: PCBDesignData,
        classified_nets: Any = None,
    ) -> List[SimulationCandidate]:
        """Extract simulation candidates from the design.

        Args:
            design: Parsed PCB data.
            classified_nets: Optional ``NetClassificationResult``.

        Returns:
            List of ``SimulationCandidate`` sorted by priority descending.
        """
        if classified_nets is None:
            return []

        layer_model = self._build_layer_model(design)
        if not layer_model:
            return []

        # Index traces by net name for fast lookup
        net_traces: Dict[str, List] = {}
        for t in design.traces:
            nn = t.net_name or ""
            net_traces.setdefault(nn, []).append(t)

        # Index vias by net name
        net_vias: Dict[str, List] = {}
        for v in design.vias:
            nn = v.net_name or ""
            net_vias.setdefault(nn, []).append(v)

        candidates: List[SimulationCandidate] = []

        # Build set of diff-pair net names for later lookup
        dp_nets: Dict[str, Any] = {}  # net_name -> DifferentialPair
        diff_pairs = getattr(classified_nets, "differential_pairs", [])
        for dp in diff_pairs:
            dp_nets[dp.positive_net] = dp
            dp_nets[dp.negative_net] = dp

        # Track which diff pairs we've already processed
        processed_dp: set = set()

        # Iterate classified nets
        for nc in getattr(classified_nets, "classified_nets", []):
            if nc.category not in HS_CATEGORIES:
                continue

            net_name = nc.net_name
            traces = net_traces.get(net_name, [])
            if not traces:
                continue

            # Determine frequency
            freq = self._resolve_frequency(nc.category, nc.subcategory)
            if freq <= 0:
                continue

            # Find dominant layer
            dom_layer, dom_traces = self._dominant_layer(traces)
            lm = layer_model.get(dom_layer.lower())
            if not lm:
                continue

            # Geometry
            total_length = sum(t.calc_length() if hasattr(t, 'calc_length') else (t.length_mm or 0.0) for t in dom_traces)
            if total_length <= 0:
                continue
            widths = [t.width_mm for t in dom_traces if t.width_mm > 0]
            trace_w = sum(widths) / len(widths) if widths else 0.0
            if trace_w <= 0:
                continue

            h_mm = lm["h_mm"]
            er = lm["er"]
            t_mm = lm["t_mm"]
            ltype = lm["type"]  # microstrip or stripline

            # Check if part of a differential pair
            dp = dp_nets.get(net_name)
            if dp and dp.pair_name not in processed_dp:
                processed_dp.add(dp.pair_name)
                # Measure P-N spacing
                p_traces = net_traces.get(dp.positive_net, [])
                n_traces = net_traces.get(dp.negative_net, [])
                spacing = self._measure_diff_spacing(p_traces, n_traces, dom_layer)

                struct_type = f"coupled_{ltype}"
                z_se = self._calc_z0(trace_w, h_mm, er, t_mm, ltype)
                z_diff = _diff_z0(z_se, spacing, h_mm) if spacing and spacing > 0 else None

                priority = _compute_priority(nc.category, nc.subcategory, struct_type, z_diff, z_se)

                candidates.append(SimulationCandidate(
                    name=f"{dp.pair_name}_diff_pair",
                    structure_type=struct_type,
                    interface=nc.category,
                    frequency_ghz=freq,
                    priority=priority,
                    trace_width_mm=trace_w,
                    trace_length_mm=round(total_length, 2),
                    dielectric_height_mm=h_mm,
                    dielectric_er=er,
                    copper_thickness_mm=t_mm,
                    layer_name=dom_layer,
                    layer_type=ltype,
                    spacing_mm=spacing,
                    z0_analytical=round(z_se, 2),
                    z_diff_analytical=round(z_diff, 2) if z_diff else None,
                    net_names=[dp.positive_net, dp.negative_net],
                ))
                continue  # don't also create a single-ended candidate for this net

            elif dp:
                # Already processed as part of the pair
                continue

            # Single-ended candidate
            z_se = self._calc_z0(trace_w, h_mm, er, t_mm, ltype)
            priority = _compute_priority(nc.category, nc.subcategory, ltype, None, z_se)

            candidates.append(SimulationCandidate(
                name=f"{net_name}_{ltype}",
                structure_type=ltype,
                interface=nc.category,
                frequency_ghz=freq,
                priority=priority,
                trace_width_mm=trace_w,
                trace_length_mm=round(total_length, 2),
                dielectric_height_mm=h_mm,
                dielectric_er=er,
                copper_thickness_mm=t_mm,
                layer_name=dom_layer,
                layer_type=ltype,
                z0_analytical=round(z_se, 2),
                net_names=[net_name],
            ))

            # Via transition candidate: net routes on multiple layers
            layers_used = {t.layer.lower() for t in traces}
            vias = net_vias.get(net_name, [])
            if len(layers_used) > 1 and vias:
                drill = vias[0].drill_mm
                pad = vias[0].pad_diameter_mm
                via_priority = _compute_priority(nc.category, nc.subcategory, "via_transition", None, 0.0)
                candidates.append(SimulationCandidate(
                    name=f"{net_name}_via_transition",
                    structure_type="via_transition",
                    interface=nc.category,
                    frequency_ghz=freq,
                    priority=via_priority,
                    trace_width_mm=trace_w,
                    trace_length_mm=0.0,
                    dielectric_height_mm=design.board_thickness_mm or 1.6,
                    dielectric_er=er,
                    copper_thickness_mm=t_mm,
                    layer_name=dom_layer,
                    layer_type="via",
                    via_drill_mm=drill,
                    via_pad_mm=pad,
                    z0_analytical=0.0,
                    net_names=[net_name],
                ))

        # Sort by priority descending, then frequency descending
        candidates.sort(key=lambda c: (-c.priority, -c.frequency_ghz))
        return candidates

    # ------------------------------------------------------------------
    # Convenience method for MCP tools
    # ------------------------------------------------------------------
    def to_candidates(
        self,
        design: PCBDesignData,
        classified_nets: Any = None,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
    ) -> List[SimulationCandidate]:
        """Extract, deduplicate, sort and return the top-N candidates."""
        candidates = self.extract(design, classified_nets)
        candidates = _deduplicate_candidates(candidates)
        candidates = _sort_candidates(candidates)
        return candidates[:max_candidates]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_layer_model(self, design: PCBDesignData) -> Dict[str, Dict]:
        """Build impedance-calculation model from stackup.

        Returns dict mapping layer_name (lowercase) -> {type, h_mm, er, t_mm}.
        """
        model: Dict[str, Dict] = {}
        layers = design.layers
        if not layers:
            return model

        copper_layers = [l for l in layers if l.layer_type in ("signal", "plane")]
        dielectric_layers = [l for l in layers if l.layer_type == "dielectric"]

        if not copper_layers or not dielectric_layers:
            return model

        for i, cu in enumerate(copper_layers):
            if cu.layer_type != "signal":
                continue

            is_outer = (i == 0 or i == len(copper_layers) - 1)
            copper_oz = cu.copper_weight_oz or (1.0 if is_outer else 0.5)
            t_mm = copper_oz * 0.035

            if is_outer:
                h_mm = self._find_adjacent_dielectric(cu, layers, "thickness")
                er = self._find_adjacent_dielectric(cu, layers, "er")
                if h_mm > 0 and er > 1:
                    model[cu.name.lower()] = {
                        "type": "microstrip",
                        "h_mm": h_mm,
                        "er": er,
                        "t_mm": t_mm,
                    }
            else:
                h_above, h_below, er = self._find_stripline_params(cu, layers, copper_layers, i)
                if h_above > 0 and h_below > 0 and er > 1:
                    model[cu.name.lower()] = {
                        "type": "stripline",
                        "h_mm": h_above + h_below,
                        "er": er,
                        "t_mm": t_mm,
                    }

        return model

    @staticmethod
    def _find_adjacent_dielectric(copper_layer: Any, all_layers: list, attr: str) -> float:
        """Find dielectric thickness or Er adjacent to a copper layer."""
        cu_row = getattr(copper_layer, "number", getattr(copper_layer, "row", 0))
        for l in all_layers:
            if l.layer_type == "dielectric" and abs(getattr(l, "number", getattr(l, "row", 0)) - cu_row) <= 2:
                if attr == "thickness":
                    if l.thickness_mm and l.thickness_mm > 0:
                        return l.thickness_mm
                elif attr == "er":
                    if l.dielectric_constant and l.dielectric_constant > 1:
                        return l.dielectric_constant
        return 0.0 if attr == "thickness" else 4.2

    @staticmethod
    def _find_stripline_params(
        cu_layer: Any, all_layers: list, copper_layers: list, cu_idx: int
    ) -> tuple:
        cu_row = getattr(cu_layer, "number", getattr(cu_layer, "row", 0))
        h_above = 0.0
        h_below = 0.0
        er = 4.2
        for l in all_layers:
            if l.layer_type != "dielectric":
                continue
            l_row = getattr(l, "number", getattr(l, "row", 0))
            if l_row < cu_row and abs(l_row - cu_row) <= 2:
                if l.thickness_mm and l.thickness_mm > 0:
                    h_above = l.thickness_mm
                    if l.dielectric_constant and l.dielectric_constant > 1:
                        er = l.dielectric_constant
            elif l_row > cu_row and abs(l_row - cu_row) <= 2:
                if l.thickness_mm and l.thickness_mm > 0:
                    h_below = l.thickness_mm
        return h_above, h_below, er

    @staticmethod
    def _resolve_frequency(category: str, subcategory: Optional[str]) -> float:
        """Resolve operating frequency for a net category/subcategory."""
        # Check subcategory first (e.g. "halow" subcategory of "rf")
        if subcategory:
            sub_lower = subcategory.lower()
            if sub_lower in INTERFACE_FREQUENCIES:
                return INTERFACE_FREQUENCIES[sub_lower]
        cat_lower = category.lower()
        return INTERFACE_FREQUENCIES.get(cat_lower, 0.0)

    @staticmethod
    def _dominant_layer(traces: list) -> tuple:
        """Find the layer with the most total trace length for a net."""
        layer_len: Dict[str, float] = {}
        layer_traces: Dict[str, list] = {}
        for t in traces:
            lname = t.layer or ""
            length = t.calc_length() if hasattr(t, "calc_length") else (t.length_mm or 0.0)
            layer_len[lname] = layer_len.get(lname, 0.0) + length
            layer_traces.setdefault(lname, []).append(t)

        if not layer_len:
            return "", []
        best = max(layer_len, key=lambda k: layer_len[k])
        return best, layer_traces.get(best, [])

    @staticmethod
    def _calc_z0(w_mm: float, h_mm: float, er: float, t_mm: float, ltype: str) -> float:
        """Calculate analytical Z0 using appropriate formula."""
        if ltype == "microstrip":
            return _microstrip_z0(w_mm, h_mm, er, t_mm)
        elif ltype == "stripline":
            return _stripline_z0(w_mm, h_mm, er, t_mm)
        return 0.0

    @staticmethod
    def _measure_diff_spacing(
        p_traces: list, n_traces: list, target_layer: str
    ) -> Optional[float]:
        """Measure center-to-center spacing between P and N traces using parallel segment detection.

        Uses the dot-product method: for each P segment, find N segments on the same
        layer that are approximately parallel (|cos(angle)| > 0.9) and within
        MAX_DIFF_PAIR_SPACING_MM, then measure perpendicular distance.
        """
        p_segs = [t for t in p_traces if (t.layer or "").lower() == target_layer.lower()]
        n_segs = [t for t in n_traces if (t.layer or "").lower() == target_layer.lower()]
        if not p_segs or not n_segs:
            return None

        spacings: List[float] = []
        for pt in p_segs:
            pdx = pt.x2_mm - pt.x1_mm
            pdy = pt.y2_mm - pt.y1_mm
            p_len = math.sqrt(pdx * pdx + pdy * pdy)
            if p_len < 0.01:
                continue

            for nt in n_segs:
                ndx = nt.x2_mm - nt.x1_mm
                ndy = nt.y2_mm - nt.y1_mm
                n_len = math.sqrt(ndx * ndx + ndy * ndy)
                if n_len < 0.01:
                    continue

                # Parallelism check: |cos(angle)| > 0.9
                dot = pdx * ndx + pdy * ndy
                cos_angle = dot / (p_len * n_len)
                if abs(cos_angle) < 0.9:
                    continue

                # Measure center-to-center distance between midpoints
                pmx = (pt.x1_mm + pt.x2_mm) / 2
                pmy = (pt.y1_mm + pt.y2_mm) / 2
                nmx = (nt.x1_mm + nt.x2_mm) / 2
                nmy = (nt.y1_mm + nt.y2_mm) / 2
                dist = math.sqrt((pmx - nmx) ** 2 + (pmy - nmy) ** 2)

                if 0 < dist < MAX_DIFF_PAIR_SPACING_MM:
                    spacings.append(dist)

        if not spacings:
            return None

        # Return median spacing
        spacings.sort()
        mid = len(spacings) // 2
        return round(spacings[mid], 4)

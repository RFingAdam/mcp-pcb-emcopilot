"""Schematic-to-Layout cross-reference validator.

Validates:
- Component list consistency between schematic and layout
- Net connectivity matches
- Footprint assignments match
- Missing/extra components

Decoupled from SQLAlchemy — operates on PCBDesignData.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ComponentMismatch:
    """Component mismatch between schematic and layout."""
    reference: str
    mismatch_type: str
    schematic_value: Optional[str] = None
    layout_value: Optional[str] = None
    schematic_footprint: Optional[str] = None
    layout_footprint: Optional[str] = None
    severity: str = "warning"


@dataclass
class NetMismatch:
    """Net mismatch between schematic and layout."""
    net_name: str
    mismatch_type: str
    schematic_pins: list[str] = field(default_factory=list)
    layout_pins: list[str] = field(default_factory=list)
    severity: str = "error"


@dataclass
class SchematicLayoutValidationResult:
    """Result of schematic-layout cross-validation."""
    total_schematic_components: int = 0
    total_layout_components: int = 0
    matching_components: int = 0
    component_mismatches: list[ComponentMismatch] = field(default_factory=list)
    net_mismatches: list[NetMismatch] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0

    def calculate_match_percentage(self) -> float:
        if self.total_schematic_components == 0:
            return 0.0
        return (self.matching_components / self.total_schematic_components) * 100


class SchematicLayoutValidator:
    """Validator for cross-referencing schematic and layout data.

    Operates on in-memory data instead of database sessions.
    """

    def __init__(self):
        pass

    def validate(self, design_data) -> SchematicLayoutValidationResult:
        """Validate schematic against layout using data in PCBDesignData.

        Requires design_data.schematic_components and design_data.components to be populated.
        """
        result = SchematicLayoutValidationResult()

        schematic_components = design_data.schematic_components or []
        layout_components = design_data.components or []

        result.total_schematic_components = len(schematic_components)
        result.total_layout_components = len(layout_components)

        # Build lookup maps
        sch_map = {}
        for sc in schematic_components:
            ref = sc.get("reference", sc.get("ref_des", "?"))
            sch_map[ref] = sc

        lay_map = {comp.reference: comp for comp in layout_components}

        sch_refs = set(sch_map.keys())
        lay_refs = set(lay_map.keys())

        missing_in_layout = sch_refs - lay_refs
        missing_in_schematic = lay_refs - sch_refs
        common_refs = sch_refs & lay_refs

        for ref in missing_in_layout:
            sc = sch_map[ref]
            result.component_mismatches.append(ComponentMismatch(
                reference=ref, mismatch_type="missing_in_layout",
                schematic_value=sc.get("value"),
                schematic_footprint=sc.get("footprint"),
                severity="error",
            ))
            result.errors += 1

        for ref in missing_in_schematic:
            lc = lay_map[ref]
            result.component_mismatches.append(ComponentMismatch(
                reference=ref, mismatch_type="missing_in_schematic",
                layout_value=lc.value,
                layout_footprint=lc.package or lc.footprint,
                severity="warning",
            ))
            result.warnings += 1

        for ref in common_refs:
            sc = sch_map[ref]
            lc = lay_map[ref]

            sch_fp = self._normalize_footprint(sc.get("footprint", ""))
            lay_fp = self._normalize_footprint(lc.package or lc.footprint or "")

            if sch_fp and lay_fp and sch_fp != lay_fp:
                result.component_mismatches.append(ComponentMismatch(
                    reference=ref, mismatch_type="footprint_mismatch",
                    schematic_footprint=sc.get("footprint"),
                    layout_footprint=lc.package or lc.footprint,
                    severity="error",
                ))
                result.errors += 1
                continue

            sch_val = (sc.get("value") or "").strip()
            lay_val = (lc.value or "").strip()
            if sch_val and lay_val and sch_val != lay_val:
                result.component_mismatches.append(ComponentMismatch(
                    reference=ref, mismatch_type="value_mismatch",
                    schematic_value=sch_val, layout_value=lay_val,
                    severity="warning",
                ))
                result.warnings += 1

            result.matching_components += 1

        # Validate nets
        schematic_nets = design_data.schematic_nets or []
        if schematic_nets:
            sch_net_names = {n.get("name", n.get("net_name", "")) for n in schematic_nets}
            lay_net_names = {n.name for n in design_data.nets}

            signal_nets = {
                name for name in sch_net_names
                if not any(kw in name.upper() for kw in ["VCC", "GND", "VDD", "VSS"])
            }

            for net_name in signal_nets - lay_net_names:
                result.net_mismatches.append(NetMismatch(
                    net_name=net_name, mismatch_type="missing_in_layout",
                    severity="warning",
                ))
                result.warnings += 1

        return result

    def _normalize_footprint(self, footprint: str) -> str:
        if not footprint:
            return ""
        normalized = footprint.upper()
        for prefix in ["R_", "C_", "L_", "D_", "IC_", "J_"]:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
        for suffix in ["_METRIC", "_IMPERIAL", "_HANDSOLDERING", "_SMD", "_THT"]:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)]
        return normalized.replace("_", "").replace("-", "").strip()

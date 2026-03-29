"""BOM-to-layout cross-reference analyzer.

Cross-references layout components against schematic/BOM data to detect:
- Missing components (in schematic/BOM but not in layout)
- Extra components (in layout but not in schematic/BOM)
- Value mismatches between sources
- DNP (Do Not Place) components
- Match percentage for design confidence

Follows the standard analyzer interface: analyze() -> List[Dict].
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Patterns that indicate a component should not be placed
_DNP_PATTERNS = re.compile(
    r"\b(DNP|NC|NO_?POP|NO_?STUFF|DO_?NOT_?PLACE|OPEN|REMOVED|SPARE)\b",
    re.IGNORECASE,
)


class BOMCrossReferenceAnalyzer:
    """Cross-reference layout components against schematic/BOM data.

    Data priority:
    1. ``design.schematic_components`` (from PDF schematic parse)
    2. ``design.bom_items`` (from BOM import)
    3. If neither available, returns an informational finding.
    """

    def analyze(
        self,
        design: Any,
        classified_nets: Any = None,
        interfaces: Any = None,
    ) -> List[Dict[str, Any]]:
        """Cross-reference layout components against schematic/BOM data."""
        findings: List[Dict[str, Any]] = []

        layout_components = getattr(design, "components", []) or []
        schematic_components = getattr(design, "schematic_components", []) or []
        bom_items = getattr(design, "bom_items", []) or []

        if not layout_components:
            findings.append({
                "category": "bom_cross_ref",
                "severity": "info",
                "description": "No layout components available for cross-reference.",
                "recommendation": "Parse a PCB layout first.",
            })
            return findings

        # Build reference source: prefer schematic, fall back to BOM
        ref_source, source_name = self._build_reference_source(
            schematic_components, bom_items,
        )

        if ref_source is None:
            findings.append({
                "category": "bom_cross_ref",
                "severity": "info",
                "description": (
                    "No schematic or BOM data available for cross-reference. "
                    f"Layout has {len(layout_components)} components."
                ),
                "recommendation": (
                    "Use pcb_parse_schematic_pdf to attach schematic data, "
                    "or provide a BOM for validation."
                ),
            })
            return findings

        # Build lookup maps (case-insensitive)
        layout_map = self._build_layout_map(layout_components)
        ref_map = ref_source  # already normalized

        layout_refs = set(layout_map.keys())
        source_refs = set(ref_map.keys())

        # Classify DNP in source
        dnp_refs = {
            ref for ref, info in ref_map.items()
            if self._is_dnp(info.get("value", ""))
        }
        # Also check layout DNP flag
        layout_dnp_refs = {
            ref for ref, comp in layout_map.items()
            if getattr(comp, "dnp", False) or self._is_dnp(getattr(comp, "value", "") or "")
        }

        active_source_refs = source_refs - dnp_refs

        # Missing: in source but not in layout (excluding DNP)
        missing_refs = sorted(active_source_refs - layout_refs)
        if missing_refs:
            grouped = self._group_by_prefix(missing_refs)
            for prefix, refs in grouped.items():
                if len(refs) <= 5:
                    desc = f"Components in {source_name} but missing from layout: {', '.join(refs)}"
                else:
                    desc = (
                        f"{len(refs)} {prefix}-type components in {source_name} but missing "
                        f"from layout (e.g. {', '.join(refs[:3])}...)"
                    )
                findings.append({
                    "category": "bom_cross_ref_missing",
                    "severity": "warning",
                    "description": desc,
                    "recommendation": (
                        "Verify these components are intentionally omitted from the layout, "
                        "or add them."
                    ),
                })

        # Extra: in layout but not in source
        extra_refs = sorted(layout_refs - source_refs)
        if extra_refs:
            grouped = self._group_by_prefix(extra_refs)
            for prefix, refs in grouped.items():
                if len(refs) <= 5:
                    desc = f"Components in layout but not in {source_name}: {', '.join(refs)}"
                else:
                    desc = (
                        f"{len(refs)} {prefix}-type components in layout but not in "
                        f"{source_name} (e.g. {', '.join(refs[:3])}...)"
                    )
                findings.append({
                    "category": "bom_cross_ref_extra",
                    "severity": "info",
                    "description": desc,
                    "recommendation": (
                        "These may be fiducials, test points, or mounting holes. "
                        "Verify they belong in the design."
                    ),
                })

        # Value mismatches (common refs, non-DNP)
        common_refs = sorted((layout_refs & active_source_refs) - layout_dnp_refs)
        mismatch_count = 0
        mismatch_examples: List[str] = []

        for ref in common_refs:
            layout_val = self._normalize_value(getattr(layout_map[ref], "value", "") or "")
            source_val = self._normalize_value(ref_map[ref].get("value", "") or "")
            if layout_val and source_val and layout_val != source_val:
                mismatch_count += 1
                if len(mismatch_examples) < 5:
                    mismatch_examples.append(
                        f"{ref}: layout='{getattr(layout_map[ref], 'value', '')}' "
                        f"vs {source_name}='{ref_map[ref].get('value', '')}'"
                    )

        if mismatch_count:
            desc = f"{mismatch_count} value mismatch(es) between layout and {source_name}"
            if mismatch_examples:
                desc += ": " + "; ".join(mismatch_examples)
            findings.append({
                "category": "bom_cross_ref_value_mismatch",
                "severity": "warning",
                "description": desc,
                "recommendation": (
                    "Reconcile component values between schematic/BOM and layout. "
                    "Value differences may indicate outdated data."
                ),
            })

        # DNP summary
        all_dnp = dnp_refs | layout_dnp_refs
        if all_dnp:
            findings.append({
                "category": "bom_cross_ref_dnp",
                "severity": "info",
                "description": f"{len(all_dnp)} DNP/NC component(s) identified and excluded from cross-reference.",
                "recommendation": "Review DNP components to confirm they are intentional.",
            })

        # Summary finding with match percentage
        matched = len(common_refs)
        total_source = len(active_source_refs)
        pct = (matched / total_source * 100) if total_source > 0 else 0.0

        severity = "info" if pct >= 90 else "warning" if pct >= 70 else "critical"
        findings.append({
            "category": "bom_cross_ref_summary",
            "severity": severity,
            "description": (
                f"BOM cross-reference: {matched}/{total_source} {source_name} components "
                f"matched in layout ({pct:.1f}%). "
                f"Layout has {len(layout_refs)} components, "
                f"{source_name} has {total_source} active + {len(dnp_refs)} DNP. "
                f"Missing: {len(missing_refs)}, Extra: {len(extra_refs)}, "
                f"Value mismatches: {mismatch_count}."
            ),
            "recommendation": (
                "A match rate above 95% is typical for production-ready designs."
                if pct < 95 else "Cross-reference looks healthy."
            ),
        })

        return findings

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_reference_source(
        self,
        schematic_components: list,
        bom_items: list,
    ) -> tuple:
        """Build normalized reference map from the best available source.

        Returns (ref_map, source_name) or (None, None).
        """
        if schematic_components:
            ref_map: Dict[str, Dict[str, str]] = {}
            for sc in schematic_components:
                ref = (sc.get("reference") or sc.get("ref_des") or "").strip().upper()
                if ref:
                    ref_map[ref] = {
                        "value": sc.get("value", ""),
                        "footprint": sc.get("footprint", ""),
                    }
            if ref_map:
                return ref_map, "schematic"

        if bom_items:
            ref_map = {}
            for item in bom_items:
                refs_str = item.get("references", item.get("ref_des", ""))
                for r in refs_str.split(","):
                    r = r.strip().upper()
                    if r:
                        ref_map[r] = {
                            "value": item.get("value", ""),
                            "part_number": item.get("part_number", ""),
                        }
            if ref_map:
                return ref_map, "BOM"

        return None, None

    @staticmethod
    def _build_layout_map(components: list) -> Dict[str, Any]:
        """Build case-insensitive reference -> component map from layout."""
        result: Dict[str, Any] = {}
        for comp in components:
            ref = (getattr(comp, "reference", "") or "").strip().upper()
            if ref:
                result[ref] = comp
        return result

    @staticmethod
    def _is_dnp(value: str) -> bool:
        return bool(_DNP_PATTERNS.search(value)) if value else False

    @staticmethod
    def _normalize_value(value: str) -> str:
        """Normalize component value for comparison (strip whitespace, lowercase)."""
        if not value:
            return ""
        return re.sub(r"\s+", "", value.strip().lower())

    @staticmethod
    def _group_by_prefix(refs: List[str]) -> Dict[str, List[str]]:
        """Group reference designators by alphabetic prefix (e.g. R, C, U)."""
        groups: Dict[str, List[str]] = {}
        for ref in refs:
            prefix = re.match(r"([A-Za-z]+)", ref)
            key = prefix.group(1) if prefix else "OTHER"
            groups.setdefault(key, []).append(ref)
        return groups

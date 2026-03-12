"""BOM (Bill of Materials) validator.

Validates:
- All layout components are in BOM
- BOM quantities match layout
- Part numbers are present
- Component values match

Decoupled from SQLAlchemy — operates on PCBDesignData.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BOMIssue:
    """BOM validation issue."""
    reference: str
    issue_type: str
    description: str
    expected_value: Optional[str] = None
    actual_value: Optional[str] = None
    severity: str = "warning"


@dataclass
class DatasheetRecommendation:
    """Recommendation for component datasheet lookup."""
    reference: str
    manufacturer: Optional[str] = None
    part_number: Optional[str] = None
    component_type: Optional[str] = None
    reason: str = "missing_datasheet"


@dataclass
class BOMValidationResult:
    """Result of BOM validation."""
    total_layout_components: int = 0
    total_bom_items: int = 0
    components_in_bom: int = 0
    quantity_matches: int = 0
    issues: list[BOMIssue] = field(default_factory=list)
    datasheet_recommendations: list[DatasheetRecommendation] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0
    infos: int = 0

    def calculate_coverage_percentage(self) -> float:
        if self.total_layout_components == 0:
            return 100.0
        return (self.components_in_bom / self.total_layout_components) * 100


class BOMValidator:
    """Validator for BOM completeness and accuracy.

    Operates on in-memory data instead of database sessions.
    """

    def __init__(self):
        pass

    def validate(self, design_data) -> BOMValidationResult:
        """Validate BOM against layout components.

        Requires design_data.bom_items and design_data.components to be populated.
        """
        result = BOMValidationResult()

        layout_components = design_data.components or []
        bom_items = design_data.bom_items or []

        result.total_layout_components = len(layout_components)
        result.total_bom_items = len(bom_items)

        # Build BOM lookup
        bom_map = {}
        for item in bom_items:
            refs_str = item.get("references", item.get("ref_des", ""))
            refs = [r.strip() for r in refs_str.split(",") if r.strip()]
            for ref in refs:
                bom_map[ref] = item

        # Build layout ref counts
        layout_ref_counts = {}
        for comp in layout_components:
            layout_ref_counts[comp.reference] = layout_ref_counts.get(comp.reference, 0) + 1

        # Validate each layout component
        for comp in layout_components:
            ref = comp.reference

            if ref not in bom_map:
                result.issues.append(BOMIssue(
                    reference=ref, issue_type="missing_from_bom",
                    description=f"Component {ref} in layout but not in BOM",
                    severity="error",
                ))
                result.errors += 1
                continue

            result.components_in_bom += 1
            bom_item = bom_map[ref]

            # Check quantity
            bom_refs = [r.strip() for r in bom_item.get("references", "").split(",") if r.strip()]
            if layout_ref_counts[ref] == len(bom_refs):
                result.quantity_matches += 1
            else:
                result.issues.append(BOMIssue(
                    reference=ref, issue_type="quantity_mismatch",
                    description=f"Quantity mismatch for {ref}",
                    expected_value=str(layout_ref_counts[ref]),
                    actual_value=str(len(bom_refs)),
                    severity="warning",
                ))
                result.warnings += 1

            # Check part number
            if not bom_item.get("part_number", "").strip():
                result.issues.append(BOMIssue(
                    reference=ref, issue_type="missing_part_number",
                    description=f"Component {ref} missing part number",
                    severity="warning",
                ))
                result.warnings += 1

            # Check value match
            comp_value = (comp.value or "").strip()
            bom_value = (bom_item.get("value") or "").strip()
            if comp_value and bom_value and comp_value != bom_value:
                result.issues.append(BOMIssue(
                    reference=ref, issue_type="value_mismatch",
                    description=f"Value mismatch for {ref}",
                    expected_value=comp_value, actual_value=bom_value,
                    severity="info",
                ))
                result.infos += 1

        return result

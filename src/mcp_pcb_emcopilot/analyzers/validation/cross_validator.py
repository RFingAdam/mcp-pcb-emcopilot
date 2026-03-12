"""Schematic-Layout-BOM Cross-Validator.

Performs three-way validation between:
- Schematic (component symbols, net connectivity, design intent)
- Layout (physical placement, actual routing, footprints)
- BOM (part numbers, quantities, sourcing)

Detects:
- Missing components in layout
- Unconnected nets
- Footprint/package mismatches
- Value discrepancies (R/C/L)
- Net name inconsistencies
- BOM quantity errors
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any


logger = logging.getLogger(__name__)


class ValidationSeverity(str, Enum):
    """Severity of validation issues."""
    CRITICAL = "critical"  # Design will not function
    ERROR = "error"        # Significant issue, needs fix
    WARNING = "warning"    # Potential issue, review needed
    INFO = "info"          # Informational only


class ValidationCategory(str, Enum):
    """Category of validation check."""
    COMPONENT_PRESENCE = "component_presence"
    NET_CONNECTIVITY = "net_connectivity"
    FOOTPRINT_MATCH = "footprint_match"
    VALUE_MATCH = "value_match"
    QUANTITY_MATCH = "quantity_match"
    PIN_MAPPING = "pin_mapping"
    REFERENCE_DESIGNATOR = "reference_designator"


@dataclass
class ValidationIssue:
    """A cross-validation issue found."""
    category: ValidationCategory
    severity: ValidationSeverity
    title: str
    description: str
    component_ref: Optional[str] = None
    net_name: Optional[str] = None
    schematic_value: Optional[str] = None
    layout_value: Optional[str] = None
    bom_value: Optional[str] = None
    recommendation: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "component_ref": self.component_ref,
            "net_name": self.net_name,
            "schematic_value": self.schematic_value,
            "layout_value": self.layout_value,
            "bom_value": self.bom_value,
            "recommendation": self.recommendation,
        }


@dataclass
class ComponentData:
    """Unified component data from any source."""
    reference: str
    value: Optional[str] = None
    footprint: Optional[str] = None
    part_number: Optional[str] = None
    manufacturer: Optional[str] = None
    description: Optional[str] = None
    pins: list[str] = field(default_factory=list)
    source: str = "unknown"  # schematic, layout, bom


@dataclass
class NetData:
    """Unified net data from any source."""
    name: str
    pins: list[tuple[str, str]] = field(default_factory=list)  # (component_ref, pin)
    source: str = "unknown"


@dataclass
class CrossValidationResult:
    """Result of cross-validation."""
    # Validation status
    valid: bool
    score: float  # 0-100

    # Issue counts by severity
    critical_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0

    # All issues
    issues: list[ValidationIssue] = field(default_factory=list)

    # Summary statistics
    components_in_schematic: int = 0
    components_in_layout: int = 0
    components_in_bom: int = 0
    nets_in_schematic: int = 0
    nets_in_layout: int = 0

    # Match statistics
    components_matched: int = 0
    nets_matched: int = 0
    values_matched: int = 0

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "score": round(self.score, 1),
            "issue_counts": {
                "critical": self.critical_count,
                "error": self.error_count,
                "warning": self.warning_count,
                "info": self.info_count,
            },
            "statistics": {
                "components_in_schematic": self.components_in_schematic,
                "components_in_layout": self.components_in_layout,
                "components_in_bom": self.components_in_bom,
                "nets_in_schematic": self.nets_in_schematic,
                "nets_in_layout": self.nets_in_layout,
                "components_matched": self.components_matched,
                "nets_matched": self.nets_matched,
                "values_matched": self.values_matched,
            },
            "issues": [issue.to_dict() for issue in self.issues],
        }


class CrossValidator:
    """Three-way validator for schematic, layout, and BOM data.

    Validates consistency between design artifacts and identifies
    discrepancies that could cause manufacturing or functional issues.

    Usage:
        validator = CrossValidator()

        # Add schematic data
        for comp in schematic_components:
            validator.add_schematic_component(comp)
        for net in schematic_nets:
            validator.add_schematic_net(net)

        # Add layout data
        for comp in layout_components:
            validator.add_layout_component(comp)
        for net in layout_nets:
            validator.add_layout_net(net)

        # Add BOM data
        for item in bom_items:
            validator.add_bom_item(item)

        # Run validation
        result = validator.validate()
    """

    def __init__(self):
        # Component data indexed by reference designator
        self.schematic_components: dict[str, ComponentData] = {}
        self.layout_components: dict[str, ComponentData] = {}
        self.bom_components: dict[str, ComponentData] = {}

        # Net data indexed by net name
        self.schematic_nets: dict[str, NetData] = {}
        self.layout_nets: dict[str, NetData] = {}

        # Configuration
        self.ignore_virtual_components = True
        self.value_tolerance_percent = 5.0
        self.fuzzy_footprint_match = True

    def add_schematic_component(
        self,
        reference: str,
        value: Optional[str] = None,
        footprint: Optional[str] = None,
        part_number: Optional[str] = None,
        pins: Optional[list[str]] = None,
    ):
        """Add a component from schematic."""
        self.schematic_components[reference] = ComponentData(
            reference=reference,
            value=value,
            footprint=footprint,
            part_number=part_number,
            pins=pins or [],
            source="schematic",
        )

    def add_layout_component(
        self,
        reference: str,
        value: Optional[str] = None,
        footprint: Optional[str] = None,
        part_number: Optional[str] = None,
        pins: Optional[list[str]] = None,
    ):
        """Add a component from layout."""
        self.layout_components[reference] = ComponentData(
            reference=reference,
            value=value,
            footprint=footprint,
            part_number=part_number,
            pins=pins or [],
            source="layout",
        )

    def add_bom_item(
        self,
        reference: str,
        value: Optional[str] = None,
        part_number: Optional[str] = None,
        manufacturer: Optional[str] = None,
        footprint: Optional[str] = None,
    ):
        """Add a component from BOM."""
        self.bom_components[reference] = ComponentData(
            reference=reference,
            value=value,
            footprint=footprint,
            part_number=part_number,
            manufacturer=manufacturer,
            source="bom",
        )

    def add_schematic_net(
        self,
        name: str,
        pins: list[tuple[str, str]],  # List of (component_ref, pin_number)
    ):
        """Add a net from schematic."""
        self.schematic_nets[name] = NetData(
            name=name,
            pins=pins,
            source="schematic",
        )

    def add_layout_net(
        self,
        name: str,
        pins: list[tuple[str, str]],
    ):
        """Add a net from layout."""
        self.layout_nets[name] = NetData(
            name=name,
            pins=pins,
            source="layout",
        )

    def validate(self) -> CrossValidationResult:
        """Run full cross-validation.

        Returns:
            CrossValidationResult with all issues found
        """
        issues: list[ValidationIssue] = []

        # Component presence validation
        issues.extend(self._validate_component_presence())

        # Net connectivity validation
        issues.extend(self._validate_net_connectivity())

        # Footprint matching
        issues.extend(self._validate_footprints())

        # Value matching
        issues.extend(self._validate_values())

        # BOM quantity validation
        issues.extend(self._validate_bom_quantities())

        # Calculate statistics
        result = self._build_result(issues)

        logger.info(
            f"Cross-validation complete: {result.score:.1f}% score, "
            f"{result.critical_count} critical, {result.error_count} errors"
        )

        return result

    def _validate_component_presence(self) -> list[ValidationIssue]:
        """Validate that components exist across all sources."""
        issues = []

        # Check schematic components in layout
        for ref, sch_comp in self.schematic_components.items():
            if self._should_ignore_component(ref):
                continue

            if ref not in self.layout_components:
                issues.append(ValidationIssue(
                    category=ValidationCategory.COMPONENT_PRESENCE,
                    severity=ValidationSeverity.CRITICAL,
                    title=f"Component {ref} missing from layout",
                    description=f"Schematic component {ref} ({sch_comp.value}) is not placed in layout",
                    component_ref=ref,
                    schematic_value=sch_comp.value,
                    recommendation="Add component to layout or remove from schematic if not needed",
                ))

        # Check layout components in schematic
        for ref, layout_comp in self.layout_components.items():
            if self._should_ignore_component(ref):
                continue

            if ref not in self.schematic_components:
                issues.append(ValidationIssue(
                    category=ValidationCategory.COMPONENT_PRESENCE,
                    severity=ValidationSeverity.ERROR,
                    title=f"Component {ref} not in schematic",
                    description=f"Layout component {ref} has no corresponding schematic symbol",
                    component_ref=ref,
                    layout_value=layout_comp.value,
                    recommendation="Add to schematic or remove from layout if not needed",
                ))

        # Check BOM vs schematic
        for ref, bom_comp in self.bom_components.items():
            if self._should_ignore_component(ref):
                continue

            if ref not in self.schematic_components:
                issues.append(ValidationIssue(
                    category=ValidationCategory.COMPONENT_PRESENCE,
                    severity=ValidationSeverity.WARNING,
                    title=f"BOM item {ref} not in schematic",
                    description=f"BOM lists {ref} ({bom_comp.part_number}) but not in schematic",
                    component_ref=ref,
                    bom_value=bom_comp.part_number,
                    recommendation="Verify BOM is up to date with schematic",
                ))

        return issues

    def _validate_net_connectivity(self) -> list[ValidationIssue]:
        """Validate net connectivity between schematic and layout."""
        issues = []

        # Check schematic nets in layout
        for net_name, sch_net in self.schematic_nets.items():
            if self._should_ignore_net(net_name):
                continue

            layout_net = self.layout_nets.get(net_name)

            if layout_net is None:
                # Check for renamed net
                renamed = self._find_similar_net(net_name, self.layout_nets)
                if renamed:
                    issues.append(ValidationIssue(
                        category=ValidationCategory.NET_CONNECTIVITY,
                        severity=ValidationSeverity.WARNING,
                        title=f"Net '{net_name}' may be renamed",
                        description=f"Schematic net '{net_name}' not found in layout, "
                                  f"but similar net '{renamed}' exists",
                        net_name=net_name,
                        schematic_value=net_name,
                        layout_value=renamed,
                        recommendation="Verify net naming is consistent",
                    ))
                else:
                    issues.append(ValidationIssue(
                        category=ValidationCategory.NET_CONNECTIVITY,
                        severity=ValidationSeverity.CRITICAL,
                        title=f"Net '{net_name}' missing from layout",
                        description=f"Schematic net '{net_name}' with "
                                  f"{len(sch_net.pins)} connections not routed",
                        net_name=net_name,
                        recommendation="Route all net connections in layout",
                    ))
            else:
                # Check pin connectivity
                sch_pins = set(sch_net.pins)
                layout_pins = set(layout_net.pins)

                missing_in_layout = sch_pins - layout_pins
                extra_in_layout = layout_pins - sch_pins

                if missing_in_layout:
                    issues.append(ValidationIssue(
                        category=ValidationCategory.NET_CONNECTIVITY,
                        severity=ValidationSeverity.CRITICAL,
                        title=f"Net '{net_name}' has missing connections",
                        description=f"Pins {list(missing_in_layout)[:5]} from schematic "
                                  "not connected in layout",
                        net_name=net_name,
                        recommendation="Complete all net connections in layout",
                    ))

                if extra_in_layout:
                    issues.append(ValidationIssue(
                        category=ValidationCategory.NET_CONNECTIVITY,
                        severity=ValidationSeverity.ERROR,
                        title=f"Net '{net_name}' has extra connections",
                        description=f"Pins {list(extra_in_layout)[:5]} connected in layout "
                                  "but not in schematic",
                        net_name=net_name,
                        recommendation="Review net connectivity - may indicate schematic error",
                    ))

        return issues

    def _validate_footprints(self) -> list[ValidationIssue]:
        """Validate footprint/package consistency."""
        issues = []

        for ref, sch_comp in self.schematic_components.items():
            if ref not in self.layout_components:
                continue

            layout_comp = self.layout_components[ref]

            sch_fp = sch_comp.footprint
            layout_fp = layout_comp.footprint

            if not sch_fp or not layout_fp:
                continue

            if not self._footprints_match(sch_fp, layout_fp):
                issues.append(ValidationIssue(
                    category=ValidationCategory.FOOTPRINT_MATCH,
                    severity=ValidationSeverity.ERROR,
                    title=f"Footprint mismatch for {ref}",
                    description=f"Schematic specifies '{sch_fp}' but layout has '{layout_fp}'",
                    component_ref=ref,
                    schematic_value=sch_fp,
                    layout_value=layout_fp,
                    recommendation="Ensure footprint is correct for the selected component",
                ))

        # Check BOM footprints
        for ref, bom_comp in self.bom_components.items():
            if ref not in self.layout_components or not bom_comp.footprint:
                continue

            layout_comp = self.layout_components[ref]
            if not layout_comp.footprint:
                continue

            if not self._footprints_match(bom_comp.footprint, layout_comp.footprint):
                issues.append(ValidationIssue(
                    category=ValidationCategory.FOOTPRINT_MATCH,
                    severity=ValidationSeverity.WARNING,
                    title=f"BOM footprint mismatch for {ref}",
                    description=f"BOM specifies '{bom_comp.footprint}' but layout has "
                              f"'{layout_comp.footprint}'",
                    component_ref=ref,
                    bom_value=bom_comp.footprint,
                    layout_value=layout_comp.footprint,
                    recommendation="Verify correct package is being ordered",
                ))

        return issues

    def _validate_values(self) -> list[ValidationIssue]:
        """Validate component values (R/C/L)."""
        issues = []

        for ref, sch_comp in self.schematic_components.items():
            if ref not in self.layout_components:
                continue

            layout_comp = self.layout_components[ref]
            bom_comp = self.bom_components.get(ref)

            sch_val = sch_comp.value
            layout_val = layout_comp.value

            if sch_val and layout_val:
                if not self._values_match(sch_val, layout_val):
                    issues.append(ValidationIssue(
                        category=ValidationCategory.VALUE_MATCH,
                        severity=ValidationSeverity.ERROR,
                        title=f"Value mismatch for {ref}",
                        description=f"Schematic value '{sch_val}' differs from layout '{layout_val}'",
                        component_ref=ref,
                        schematic_value=sch_val,
                        layout_value=layout_val,
                        recommendation="Sync values between schematic and layout",
                    ))

            # Check against BOM
            if bom_comp and bom_comp.value:
                if sch_val and not self._values_match(sch_val, bom_comp.value):
                    issues.append(ValidationIssue(
                        category=ValidationCategory.VALUE_MATCH,
                        severity=ValidationSeverity.WARNING,
                        title=f"BOM value mismatch for {ref}",
                        description=f"Schematic value '{sch_val}' differs from BOM '{bom_comp.value}'",
                        component_ref=ref,
                        schematic_value=sch_val,
                        bom_value=bom_comp.value,
                        recommendation="Ensure BOM reflects design intent",
                    ))

        return issues

    def _validate_bom_quantities(self) -> list[ValidationIssue]:
        """Validate BOM quantities match design."""
        issues = []

        # Group BOM items by part number
        bom_by_pn: dict[str, list[str]] = {}
        for ref, comp in self.bom_components.items():
            if comp.part_number:
                if comp.part_number not in bom_by_pn:
                    bom_by_pn[comp.part_number] = []
                bom_by_pn[comp.part_number].append(ref)

        # Check that all refs in BOM are in design
        for ref in self.bom_components:
            if ref not in self.schematic_components and ref not in self.layout_components:
                issues.append(ValidationIssue(
                    category=ValidationCategory.QUANTITY_MATCH,
                    severity=ValidationSeverity.WARNING,
                    title=f"BOM item {ref} not in design",
                    description=f"BOM includes {ref} but it's not in schematic or layout",
                    component_ref=ref,
                    recommendation="Remove obsolete items from BOM",
                ))

        # Check for missing BOM entries
        for ref in self.schematic_components:
            if self._should_ignore_component(ref):
                continue
            if ref not in self.bom_components:
                issues.append(ValidationIssue(
                    category=ValidationCategory.QUANTITY_MATCH,
                    severity=ValidationSeverity.INFO,
                    title=f"Component {ref} not in BOM",
                    description=f"Schematic component {ref} has no BOM entry",
                    component_ref=ref,
                    recommendation="Add to BOM for complete ordering",
                ))

        return issues

    def _should_ignore_component(self, ref: str) -> bool:
        """Check if component should be ignored in validation."""
        if not self.ignore_virtual_components:
            return False

        # Virtual/power symbols typically start with # or have no ref
        if ref.startswith("#") or ref.startswith("PWR") or ref.startswith("GND"):
            return True

        # Test points, mounting holes, fiducials
        for prefix in ["TP", "MH", "FID", "MP"]:
            if ref.startswith(prefix):
                return True

        return False

    def _should_ignore_net(self, name: str) -> bool:
        """Check if net should be ignored in validation."""
        # Power nets are often implicit
        power_nets = ["VCC", "VDD", "GND", "VSS", "VBAT", "3V3", "5V", "12V"]
        name_upper = name.upper()

        for pn in power_nets:
            if name_upper == pn or name_upper.startswith(f"{pn}_"):
                return True

        # Unnamed nets
        if name.startswith("Net-") or name.startswith("unconnected"):
            return True

        return False

    def _find_similar_net(
        self, name: str, nets: dict[str, NetData]
    ) -> Optional[str]:
        """Find a similarly named net (for renamed detection)."""
        name_lower = name.lower()

        for net_name in nets:
            net_lower = net_name.lower()

            # Exact match ignoring case
            if name_lower == net_lower:
                return net_name

            # One contains the other
            if name_lower in net_lower or net_lower in name_lower:
                return net_name

            # Remove common prefixes/suffixes and compare
            for prefix in ["net_", "n_", "sig_"]:
                n1 = name_lower.replace(prefix, "")
                n2 = net_lower.replace(prefix, "")
                if n1 == n2:
                    return net_name

        return None

    def _footprints_match(self, fp1: str, fp2: str) -> bool:
        """Check if two footprints match (with fuzzy matching)."""
        if fp1 == fp2:
            return True

        if not self.fuzzy_footprint_match:
            return False

        # Normalize footprint names
        fp1_norm = self._normalize_footprint(fp1)
        fp2_norm = self._normalize_footprint(fp2)

        return fp1_norm == fp2_norm

    def _normalize_footprint(self, fp: str) -> str:
        """Normalize footprint name for comparison."""
        # Remove library prefix (e.g., "Package_SO:SOIC-8" -> "SOIC-8")
        if ":" in fp:
            fp = fp.split(":")[-1]

        # Lowercase and remove common variations
        fp = fp.lower()
        fp = fp.replace("_handsoldering", "")
        fp = fp.replace("-", "")
        fp = fp.replace("_", "")

        return fp

    def _values_match(self, val1: str, val2: str) -> bool:
        """Check if two component values match."""
        if val1 == val2:
            return True

        # Parse and compare numeric values
        num1 = self._parse_value(val1)
        num2 = self._parse_value(val2)

        if num1 is not None and num2 is not None:
            # Within tolerance
            if num1 == 0 or num2 == 0:
                return num1 == num2
            diff_percent = abs(num1 - num2) / max(num1, num2) * 100
            return diff_percent <= self.value_tolerance_percent

        # String comparison with normalization
        return self._normalize_value(val1) == self._normalize_value(val2)

    def _parse_value(self, value: str) -> Optional[float]:
        """Parse a component value to numeric (e.g., "10k" -> 10000)."""
        if not value:
            return None

        value = value.strip().upper()

        # Multiplier suffixes
        multipliers = {
            "P": 1e-12,
            "N": 1e-9,
            "U": 1e-6,
            "M": 1e-3,  # Note: could also be Mega, context dependent
            "K": 1e3,
            "MEG": 1e6,
            "G": 1e9,
        }

        # Try to parse with suffix
        match = re.match(r"^([\d.]+)\s*([A-Z]*)", value)
        if match:
            try:
                num = float(match.group(1))
                suffix = match.group(2)

                if suffix in multipliers:
                    return num * multipliers[suffix]
                elif suffix in ["OHM", "OHMS", "R", "F", "H"]:
                    return num
                else:
                    return num

            except ValueError:
                pass

        return None

    def _normalize_value(self, value: str) -> str:
        """Normalize a value string for comparison."""
        value = value.lower().strip()
        value = value.replace(" ", "")
        value = value.replace("ohm", "")
        value = value.replace("ohms", "")
        return value

    def _build_result(self, issues: list[ValidationIssue]) -> CrossValidationResult:
        """Build the validation result from issues."""
        critical = sum(1 for i in issues if i.severity == ValidationSeverity.CRITICAL)
        error = sum(1 for i in issues if i.severity == ValidationSeverity.ERROR)
        warning = sum(1 for i in issues if i.severity == ValidationSeverity.WARNING)
        info = sum(1 for i in issues if i.severity == ValidationSeverity.INFO)

        # Calculate score (100 = perfect, deduct for issues)
        score = 100.0
        score -= critical * 20
        score -= error * 10
        score -= warning * 2
        score -= info * 0.5
        score = max(0.0, score)

        # Count matches
        matched_components = len(
            set(self.schematic_components.keys()) &
            set(self.layout_components.keys())
        )

        matched_nets = len(
            set(self.schematic_nets.keys()) &
            set(self.layout_nets.keys())
        )

        value_issues = sum(1 for i in issues
                         if i.category == ValidationCategory.VALUE_MATCH)
        total_comps = len(self.schematic_components)
        matched_values = total_comps - value_issues

        return CrossValidationResult(
            valid=critical == 0 and error == 0,
            score=score,
            critical_count=critical,
            error_count=error,
            warning_count=warning,
            info_count=info,
            issues=issues,
            components_in_schematic=len(self.schematic_components),
            components_in_layout=len(self.layout_components),
            components_in_bom=len(self.bom_components),
            nets_in_schematic=len(self.schematic_nets),
            nets_in_layout=len(self.layout_nets),
            components_matched=matched_components,
            nets_matched=matched_nets,
            values_matched=matched_values,
        )


def validate_design_consistency(
    schematic_components: list[dict],
    layout_components: list[dict],
    bom_items: Optional[list[dict]] = None,
    schematic_nets: Optional[list[dict]] = None,
    layout_nets: Optional[list[dict]] = None,
) -> CrossValidationResult:
    """Convenience function for cross-validation.

    Args:
        schematic_components: List of {reference, value, footprint, ...}
        layout_components: List of {reference, value, footprint, ...}
        bom_items: Optional list of {reference, part_number, value, ...}
        schematic_nets: Optional list of {name, pins: [(ref, pin), ...]}
        layout_nets: Optional list of {name, pins: [(ref, pin), ...]}

    Returns:
        CrossValidationResult
    """
    validator = CrossValidator()

    for comp in schematic_components:
        validator.add_schematic_component(
            reference=comp.get("reference", ""),
            value=comp.get("value"),
            footprint=comp.get("footprint"),
            part_number=comp.get("part_number"),
        )

    for comp in layout_components:
        validator.add_layout_component(
            reference=comp.get("reference", ""),
            value=comp.get("value"),
            footprint=comp.get("footprint"),
        )

    if bom_items:
        for item in bom_items:
            validator.add_bom_item(
                reference=item.get("reference", ""),
                value=item.get("value"),
                part_number=item.get("part_number"),
                manufacturer=item.get("manufacturer"),
            )

    if schematic_nets:
        for net in schematic_nets:
            validator.add_schematic_net(
                name=net.get("name", ""),
                pins=net.get("pins", []),
            )

    if layout_nets:
        for net in layout_nets:
            validator.add_layout_net(
                name=net.get("name", ""),
                pins=net.get("pins", []),
            )

    return validator.validate()

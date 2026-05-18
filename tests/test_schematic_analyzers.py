"""Tests for the Phase 4b schematic-aware analyzers (power_topology,
protection_circuits, decoupling_per_ic, component_rating) and the
three-way cross-reference."""

from __future__ import annotations

from mcp_pcb_emcopilot.analyzers.schematic.component_rating import (
    analyze_component_rating,
)
from mcp_pcb_emcopilot.analyzers.schematic.decoupling_per_ic import (
    analyze_decoupling_per_ic,
)
from mcp_pcb_emcopilot.analyzers.schematic.power_topology import (
    analyze_power_topology,
)
from mcp_pcb_emcopilot.analyzers.schematic.protection_circuits import (
    analyze_protection_circuits,
)
from mcp_pcb_emcopilot.analyzers.validation.three_way_xref import (
    analyze_three_way_xref,
)
from mcp_pcb_emcopilot.orchestrator import reset_finding_id_counters

# --- helpers ---------------------------------------------------------------

def setup_function():
    reset_finding_id_counters()


def _comp(reference, value="", pins=None, **extra):
    out = {"reference": reference, "value": value}
    if pins:
        out["pins"] = pins
    out.update(extra)
    return out


def _net(name, is_power=False, is_ground=False):
    return {"name": name, "is_power": is_power, "is_ground": is_ground}


def _bom(refs, value=None, part_number=None, manufacturer=None, description=None):
    return {
        "references": refs,
        "quantity": len(refs.split(",")),
        "value": value,
        "part_number": part_number,
        "manufacturer": manufacturer,
        "description": description,
    }


# =============================================================================
# power_topology
# =============================================================================

def test_power_topology_flags_zero_caps_rail():
    components = [_comp("U1", "STM32F407"), _comp("R1", "10k")]
    nets = [_net("VCC_3V3", is_power=True), _net("GND", is_ground=True)]
    findings = analyze_power_topology(components, nets)
    severities = {f.severity for f in findings}
    assert "high" in severities  # zero caps on VCC_3V3


def test_power_topology_flags_under_decoupled_rail():
    components = [
        _comp("U1", "STM32F407"),
        _comp("C1", "100nF"),  # only one cap, no bulk
    ]
    nets = [_net("VCC_3V3", is_power=True)]
    findings = analyze_power_topology(components, nets)
    medium_findings = [f for f in findings if f.severity == "medium"]
    assert any("only" in f.title.lower() or "bulk" in f.title.lower() for f in medium_findings)


def test_power_topology_no_source_flagged():
    components = [
        _comp("U1", "STM32F407"),
        _comp("C1", "10uF"),
        _comp("C2", "100nF"),
    ]
    nets = [_net("VCC_3V3", is_power=True)]
    findings = analyze_power_topology(components, nets)
    titles = " ".join(f.title for f in findings).lower()
    assert "no identified source" in titles


def test_power_topology_clean_design_no_issues():
    components = [
        _comp("U1", "TPS62A01-LDO"),  # regulator → source identified
        _comp("C1", "10uF"),
        _comp("C2", "100nF"),
        _comp("C3", "100nF"),
    ]
    nets = [_net("VCC_3V3", is_power=True)]
    findings = analyze_power_topology(components, nets)
    severe = [f for f in findings if f.severity in ("critical", "high")]
    assert not severe


def test_power_topology_handles_missing_power_nets():
    components = [_comp("U1", "STM32F407")]
    nets = [_net("GND", is_ground=True)]
    findings = analyze_power_topology(components, nets)
    assert any("No power nets" in f.title for f in findings)


# =============================================================================
# protection_circuits
# =============================================================================

def test_protection_flags_missing_tvs_with_pin_net_data():
    """When pin-net mapping is present, the analyzer reports per-net coverage."""
    components = [_comp("U1", "STM32F407", pins=[{"net": "USB_DP"}])]
    nets = [_net("USB_DP")]
    findings = analyze_protection_circuits(components, nets)
    assert any("TVS" in f.title and "USB_DP" in f.title for f in findings)


def test_protection_aggregate_fallback_when_no_pin_net():
    components = [_comp("U1", "STM32F407")]
    nets = [_net("USB_DP"), _net("USB_DM"), _net("ANT_OUT")]
    findings = analyze_protection_circuits(components, nets)
    # No pin-net → aggregate "X TVS for Y nets" finding
    aggregate = [f for f in findings if "external net" in f.title and "TVS" in f.title]
    assert aggregate, [f.title for f in findings]


def test_protection_flags_missing_cmc_on_usb_diff_pair():
    components = []  # no CMC anywhere
    nets = [_net("USB_DP"), _net("USB_DM")]
    findings = analyze_protection_circuits(components, nets)
    assert any("common-mode choke" in f.description for f in findings)


def test_protection_flags_missing_fuse_on_power_input():
    components = []  # no fuse
    nets = [_net("VIN")]
    findings = analyze_protection_circuits(components, nets)
    assert any("fuse" in f.title.lower() for f in findings)


def test_protection_no_external_nets_is_info_only():
    components = []
    nets = [_net("VCC_3V3", is_power=True), _net("GND", is_ground=True)]
    findings = analyze_protection_circuits(components, nets)
    severities = {f.severity for f in findings}
    assert severities == {"info"}


# =============================================================================
# decoupling_per_ic
# =============================================================================

def test_decoupling_aggregate_low_ratio():
    components = [
        _comp("U1", "STM32"),
        _comp("U2", "BMI"),
        _comp("U3", "FRAM"),
        _comp("C1", "100nF"),
        # 1 cap / 3 ICs = 0.33 ratio
    ]
    nets = []
    findings = analyze_decoupling_per_ic(components, nets)
    assert any(f.severity == "medium" for f in findings)


def test_decoupling_per_ic_uses_pin_net_mapping():
    components = [
        _comp("U1", "STM32", pins=[
            {"net": "VCC_3V3"},
            {"net": "VDD_CORE"},
            {"net": "GND"},
        ]),
        _comp("C1", "100nF", pins=[{"net": "VCC_3V3"}]),
        # No cap on VDD_CORE
    ]
    nets = []
    findings = analyze_decoupling_per_ic(components, nets)
    under = [f for f in findings if "under-decoupled" in f.title]
    assert under, [f.title for f in findings]


def test_decoupling_no_ics_is_info():
    findings = analyze_decoupling_per_ic([_comp("R1", "10k")], [])
    assert findings[0].severity == "info"


# =============================================================================
# component_rating
# =============================================================================

def test_component_rating_skips_when_no_bom():
    components = [_comp("C1", "10uF/25V")]
    nets = [_net("VCC_3V3", is_power=True)]
    findings = analyze_component_rating(components, nets, [])
    assert any("BOM" in f.title for f in findings)


def test_component_rating_flags_overvoltage_violation():
    """Cap rated 10V on a 12V rail = 120% utilisation → high severity."""
    components = [_comp("C1", "10uF/10V")]
    nets = [_net("V12V", is_power=True)]
    bom = [_bom("C1", value="10uF/10V")]
    findings = analyze_component_rating(components, nets, bom)
    violations = [f for f in findings if f.severity == "high"]
    assert violations


def test_component_rating_marginal_derating_is_medium():
    """Cap rated 25V on 24V rail = 96% → above 80% threshold, but <100% → medium."""
    components = [_comp("C1", "1uF/25V")]
    nets = [_net("V24V", is_power=True)]
    bom = [_bom("C1", value="1uF/25V")]
    findings = analyze_component_rating(components, nets, bom)
    assert any(f.severity == "medium" for f in findings)


def test_component_rating_clean_design():
    components = [_comp("C1", "100nF/50V")]
    nets = [_net("VCC_3V3", is_power=True)]
    bom = [_bom("C1", value="100nF/50V")]
    findings = analyze_component_rating(components, nets, bom)
    assert all(f.severity == "info" for f in findings)


# =============================================================================
# three_way_xref
# =============================================================================

class _LayoutComp:
    """Minimal stand-in for the layout's PCBComponent dataclass."""
    def __init__(self, reference, value="", footprint=""):
        self.reference = reference
        self.value = value
        self.footprint = footprint
        self.layer = "top"
        self.x_mm = 0.0
        self.y_mm = 0.0


def test_xref_critical_missing_from_layout():
    sch = [_comp("R1", "10k", footprint="0402"), _comp("R2", "4.7k", footprint="0402")]
    bom = [_bom("R1", value="10k"), _bom("R2", value="4.7k")]
    # Layout has R2 but is missing R1 — schematic + BOM both confirm R1 should exist.
    layout = [_LayoutComp("R2", "4.7k", footprint="0402")]
    findings = analyze_three_way_xref(sch, bom, layout)
    assert any(f.severity == "critical" and "missing from layout" in f.title for f in findings)


def test_xref_critical_value_mismatch_sch_vs_bom():
    sch = [_comp("R1", "10k")]
    bom = [_bom("R1", value="4.7k")]
    layout = [_LayoutComp("R1", "10k")]
    findings = analyze_three_way_xref(sch, bom, layout)
    assert any(f.severity == "critical" and "value mismatch" in f.title.lower() for f in findings)


def test_xref_critical_footprint_mismatch_sch_vs_layout():
    sch = [_comp("R1", "10k", footprint="0402")]
    bom = []
    layout = [_LayoutComp("R1", "10k", footprint="0603")]
    findings = analyze_three_way_xref(sch, bom, layout)
    assert any(f.severity == "critical" and "footprint mismatch" in f.title.lower() for f in findings)


def test_xref_low_severity_manufacturer_only_differs():
    sch = [_comp("R1", "10k", manufacturer="Yageo")]
    bom = [_bom("R1", value="10k", manufacturer="Vishay")]
    layout = [_LayoutComp("R1", "10k")]
    findings = analyze_three_way_xref(sch, bom, layout)
    assert any(f.severity == "low" and "manufacturer differs" in f.title.lower() for f in findings)


def test_xref_clean_when_all_match():
    sch = [_comp("R1", "10k", footprint="0402")]
    bom = [_bom("R1", value="10k")]
    layout = [_LayoutComp("R1", "10k", footprint="0402")]
    findings = analyze_three_way_xref(sch, bom, layout)
    assert findings[0].title == "Three-way cross-reference clean"


def test_xref_skips_when_only_one_source():
    findings = analyze_three_way_xref([_comp("R1", "10k")], [], [])
    assert any("fewer than two" in f.title for f in findings)


def test_xref_value_normalisation_handles_unit_variants():
    """'10 kΩ' and '10K' should compare equal."""
    sch = [_comp("R1", "10 kΩ")]
    bom = [_bom("R1", value="10K")]
    layout = [_LayoutComp("R1", "10K")]
    findings = analyze_three_way_xref(sch, bom, layout)
    # Should be clean — no value mismatch
    assert not any("value mismatch" in f.title.lower() for f in findings)

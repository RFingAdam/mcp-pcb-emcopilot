"""Report section registry — defines the fixed ordering and metadata for report sections."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SectionDef:
    """Definition of a report section."""

    number: int
    key: str
    title: str
    required: bool = False
    source_tools: tuple[str, ...] = ()


def get_section_by_key(key: str) -> SectionDef | None:
    """Look up a section definition by its key. Returns None if not found."""
    for s in REPORT_SECTIONS:
        if s.key == key:
            return s
    return None


REPORT_SECTIONS: list[SectionDef] = [
    SectionDef(1, "executive_summary", "Executive Summary", required=True),
    SectionDef(2, "board_overview", "Board Overview & Layout", required=True,
               source_tools=("pcb_parse_layout", "pcb_get_board_outline")),
    SectionDef(3, "stackup", "Layer Stackup Analysis",
               source_tools=("pcb_get_stackup",)),
    SectionDef(4, "schematic_overview", "Schematic Overview",
               source_tools=("pcb_parse_schematic_pdf",)),
    SectionDef(5, "cross_reference", "Schematic-Layout Cross-Reference",
               source_tools=("pcb_cross_reference_schematic",)),
    SectionDef(6, "net_classification", "Net Classification",
               source_tools=("pcb_classify_nets", "pcb_detect_interfaces")),
    SectionDef(7, "impedance", "Impedance Analysis",
               source_tools=("pcb_calc_microstrip_impedance", "pcb_calc_stripline_impedance",
                              "pcb_calc_differential_impedance", "pcb_calc_cpw_impedance")),
    SectionDef(8, "signal_integrity", "Signal Integrity Analysis",
               source_tools=("pcb_calc_eye_diagram", "pcb_calc_ibis_eye",
                              "pcb_analyze_mode_conversion", "pcb_analyze_crosstalk",
                              "pcb_analyze_differential_pair", "pcb_analyze_length_matching")),
    SectionDef(9, "high_speed", "High-Speed Digital Interfaces",
               source_tools=("pcb_analyze_ddr", "pcb_analyze_usb", "pcb_analyze_pcie",
                              "pcb_analyze_ethernet", "pcb_validate_ddr_topology",
                              "pcb_validate_pcie_lanes", "pcb_analyze_ddr_timing_budget",
                              "pcb_calc_pcie_link_budget")),
    SectionDef(10, "emc", "EMC / EMI Analysis",
               source_tools=("pcb_analyze_clock_emi", "pcb_analyze_emi_risk",
                              "pcb_analyze_smps_emi", "pcb_analyze_conducted_emissions",
                              "pcb_analyze_near_field", "pcb_predict_emissions",
                              "pcb_get_emi_hotspots")),
    SectionDef(11, "emi_filtering", "EMI Filter Design",
               source_tools=("pcb_design_emi_filter",)),
    SectionDef(12, "automotive_emc", "Automotive EMC",
               source_tools=("pcb_analyze_automotive_emc",)),
    SectionDef(13, "esd", "ESD Assessment",
               source_tools=("pcb_analyze_esd",)),
    SectionDef(14, "immunity", "Immunity Margin Analysis",
               source_tools=("pcb_analyze_immunity_margin",)),
    SectionDef(15, "power_integrity", "Power Integrity Analysis",
               source_tools=("pcb_analyze_pdn", "pcb_analyze_vrm", "pcb_analyze_decoupling",
                              "pcb_calc_plane_resonance", "pcb_calc_pdn_impedance")),
    SectionDef(16, "return_path", "Return Path Analysis",
               source_tools=("pcb_visualize_return_path", "pcb_find_split_crossings",
                              "pcb_trace_return_path", "pcb_analyze_return_paths",
                              "pcb_analyze_return_current", "pcb_analyze_return_current_density")),
    SectionDef(17, "antenna", "Antenna / Unintentional Radiation",
               source_tools=("pcb_analyze_trace_antenna", "pcb_analyze_slot_antenna",
                              "pcb_analyze_common_mode", "pcb_analyze_cable_coupling")),
    SectionDef(18, "thermal", "Thermal Analysis",
               source_tools=("pcb_analyze_thermal", "pcb_analyze_thermal_via",
                              "pcb_analyze_copper_spreading")),
    SectionDef(19, "dfm", "DFM (Design for Manufacturing)",
               source_tools=("pcb_analyze_solder_paste", "pcb_analyze_placement",
                              "pcb_analyze_assembly")),
    SectionDef(20, "stackup_optimization", "Stackup Optimization",
               source_tools=("pcb_optimize_stackup",)),
    SectionDef(21, "shielding", "Shielding Effectiveness",
               source_tools=("pcb_analyze_shielding",)),
    SectionDef(22, "grounding", "Grounding Analysis",
               source_tools=("pcb_analyze_grounding", "pcb_analyze_ground_stitch")),
    SectionDef(23, "test_plan", "Pre-Compliance Test Plan",
               source_tools=("pcb_generate_test_plan",)),
    SectionDef(24, "design_rules", "Design Rule Summary",
               source_tools=("pcb_get_design_rules",)),
    SectionDef(25, "drill_table", "Drill Table & Via Analysis",
               source_tools=("pcb_get_drill_table", "pcb_analyze_via")),
    SectionDef(26, "action_items", "Priority Action Items", required=True),
    SectionDef(27, "tool_coverage", "Tool Coverage & Methodology", required=True),
    SectionDef(28, "glossary", "Glossary & Abbreviations", required=True),
    SectionDef(29, "references", "References & Applicable Standards", required=True),
    SectionDef(30, "appendices", "Appendices", required=True),
]

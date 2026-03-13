"""Design review orchestrator.

Coordinates context intake, multi-domain analysis, cross-correlation,
and structured report generation for PCB design reviews.

Calls analyzer classes directly (not MCP tools) for efficiency.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .models.pcb_data import PCBDesignData
from .classifiers.net_classifier import NetClassifier, NetClassificationResult
from .classifiers.interface_detector import InterfaceDetector, InterfaceDetectionResult
from .classifiers.design_classifier import DesignClassifier, DesignClassificationResult


# =============================================================================
# Data structures
# =============================================================================

SEVERITY_ORDER = {"critical": 0, "high": 1, "warning": 2, "medium": 2, "low": 3, "info": 4}


@dataclass
class ReviewFinding:
    """A single finding from a domain analysis."""
    domain: str
    severity: str  # critical, warning, info
    title: str
    description: str
    recommendation: str = ""
    measured_value: Optional[float] = None
    limit_value: Optional[float] = None
    signal_name: Optional[str] = None
    related_findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "domain": self.domain,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "recommendation": self.recommendation,
        }
        if self.measured_value is not None:
            d["measured_value"] = self.measured_value
        if self.limit_value is not None:
            d["limit_value"] = self.limit_value
        if self.signal_name:
            d["signal_name"] = self.signal_name
        if self.related_findings:
            d["related_findings"] = self.related_findings
        return d


@dataclass
class DomainResult:
    """Results from a single analysis domain."""
    domain: str
    status: str = "pass"  # pass, warning, fail, error, skipped
    findings: list[ReviewFinding] = field(default_factory=list)
    analyzer_name: str = ""
    raw_data: dict = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity in ("warning", "medium", "high"))

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity in ("info", "low"))

    def to_dict(self) -> dict:
        d = {
            "domain": self.domain,
            "status": self.status,
            "analyzer": self.analyzer_name,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "findings": [f.to_dict() for f in self.findings],
        }
        if self.error:
            d["error"] = self.error
        return d


@dataclass
class CrossCorrelation:
    """A cross-domain correlation finding."""
    domains: list[str]
    title: str
    description: str
    severity: str
    recommendation: str

    def to_dict(self) -> dict:
        return {
            "domains": self.domains,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "recommendation": self.recommendation,
        }


@dataclass
class RiskEntry:
    """Entry in the risk matrix."""
    finding_title: str
    severity: str  # critical, warning, info
    likelihood: str  # high, medium, low
    risk_score: int  # 1-9

    def to_dict(self) -> dict:
        return {
            "finding": self.finding_title,
            "severity": self.severity,
            "likelihood": self.likelihood,
            "risk_score": self.risk_score,
        }


@dataclass
class ReviewResult:
    """Complete orchestrated design review result."""
    session_id: str
    timestamp: float
    design_classification: dict = field(default_factory=dict)
    detected_interfaces: list[str] = field(default_factory=list)
    domain_results: list[DomainResult] = field(default_factory=list)
    cross_correlations: list[CrossCorrelation] = field(default_factory=list)
    risk_matrix: list[RiskEntry] = field(default_factory=list)
    executive_summary: dict = field(default_factory=dict)
    recommendations: list[dict] = field(default_factory=list)
    review_context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "design_classification": self.design_classification,
            "detected_interfaces": self.detected_interfaces,
            "executive_summary": self.executive_summary,
            "domain_results": [d.to_dict() for d in self.domain_results],
            "cross_correlations": [c.to_dict() for c in self.cross_correlations],
            "risk_matrix": [r.to_dict() for r in self.risk_matrix],
            "recommendations": self.recommendations,
            "review_context": self.review_context,
        }


# =============================================================================
# Context management
# =============================================================================

def set_review_context(
    design: PCBDesignData,
    design_intent: str = "",
    target_standards: Optional[list[str]] = None,
    known_issues: Optional[list[str]] = None,
    impedance_targets: Optional[dict[str, float]] = None,
    thermal_limits: Optional[dict[str, float]] = None,
    operating_conditions: Optional[dict[str, Any]] = None,
) -> dict:
    """Store review context in the design session.

    Args:
        design: PCBDesignData for the session.
        design_intent: Free-text description of the design purpose.
        target_standards: List of target EMC standards (e.g. ["FCC_B", "CISPR_32"]).
        known_issues: List of known issues to investigate.
        impedance_targets: Dict of net_pattern: impedance_ohm targets.
        thermal_limits: Dict of thermal constraints (e.g. {"max_ambient_c": 40}).
        operating_conditions: Dict with temp_range, altitude, etc.

    Returns:
        The stored context dict.
    """
    ctx = {
        "design_intent": design_intent,
        "target_standards": target_standards or ["FCC_B"],
        "known_issues": known_issues or [],
        "impedance_targets": impedance_targets or {},
        "thermal_limits": thermal_limits or {},
        "operating_conditions": operating_conditions or {},
        "set_at": time.time(),
    }
    design.review_context = ctx
    return ctx


# =============================================================================
# Analyzer selection and dispatch
# =============================================================================

def _select_analyzers(
    design: PCBDesignData,
    classification: DesignClassificationResult,
    interfaces: InterfaceDetectionResult,
    net_cls: NetClassificationResult,
) -> list[str]:
    """Select which analyzers to run based on detected interfaces and design type.

    Returns list of analyzer keys to run.
    """
    analyzers = []

    # Build category map from classified nets
    cat_counts: dict[str, int] = {}
    for nc in net_cls.classified_nets:
        cat_counts[nc.category] = cat_counts.get(nc.category, 0) + 1

    # Interface-specific analyzers
    iface_types = {iface.interface_type.lower() for iface in interfaces.interfaces}
    iface_types_str = " ".join(iface_types)

    if any("ddr" in t for t in iface_types):
        analyzers.append("ddr")
    if any("usb" in t for t in iface_types):
        analyzers.append("usb")
    if any("pcie" in t for t in iface_types):
        analyzers.append("pcie")
    if any(t in ("gbe", "100base-tx", "sgmii", "ethernet") for t in iface_types):
        analyzers.append("ethernet")

    # High-speed signal analysis
    high_speed_cats = {"ddr", "usb", "pcie", "ethernet", "lvds", "rf"}
    has_high_speed = any(cat_counts.get(c, 0) > 0 for c in high_speed_cats)
    if has_high_speed or len(net_cls.differential_pairs) > 0:
        analyzers.append("return_path")
        analyzers.append("emi_risk")

    # Power analysis
    power_count = cat_counts.get("power", 0)
    if power_count > 0:
        analyzers.append("pdn")

    # Always-run analyzers
    analyzers.append("thermal")
    analyzers.append("dfm_placement")
    analyzers.append("emc_grounding")
    analyzers.append("validation")

    return list(dict.fromkeys(analyzers))  # deduplicate preserving order


def _run_return_path_analysis(
    design: PCBDesignData,
    net_cls: NetClassificationResult,
) -> DomainResult:
    """Run return path analysis."""
    from .analyzers.emc.return_path_analyzer import ReturnPathAnalyzer

    result = DomainResult(domain="emc_return_path", analyzer_name="ReturnPathAnalyzer")
    try:
        analyzer = ReturnPathAnalyzer()
        rp_result = analyzer.analyze(design, net_cls)

        # Extract findings from return path result
        for net_analysis in getattr(rp_result, "net_analyses", []):
            for issue in getattr(net_analysis, "issues", []):
                severity = getattr(issue, "severity", "warning")
                result.findings.append(ReviewFinding(
                    domain="emc_return_path",
                    severity=severity,
                    title=f"Return path issue: {getattr(issue, 'issue_type', 'unknown')}",
                    description=getattr(issue, "description", str(issue)),
                    recommendation=getattr(issue, "recommendation", ""),
                    signal_name=getattr(net_analysis, "net_name", None),
                ))

        result.status = "fail" if result.critical_count > 0 else "warning" if result.warning_count > 0 else "pass"
        result.raw_data = _safe_serialize(rp_result)
    except Exception as e:
        result.status = "error"
        result.error = str(e)
    return result


def _run_emi_risk_analysis(
    design: PCBDesignData,
    net_cls: NetClassificationResult,
    standard: str = "FCC_B",
) -> DomainResult:
    """Run EMI risk scoring."""
    from .analyzers.emc.emi_risk_scorer import EMIRiskScorer

    result = DomainResult(domain="emc_emi_risk", analyzer_name="EMIRiskScorer")
    try:
        scorer = EMIRiskScorer()
        emi_result = scorer.score(design, classified_nets=net_cls, standard=standard)

        # Convert top risks to findings
        for net_risk in getattr(emi_result, "net_risks", [])[:20]:
            risk_level = getattr(net_risk, "risk_level", "low")
            if risk_level in ("critical", "high"):
                severity = "critical" if risk_level == "critical" else "warning"
                result.findings.append(ReviewFinding(
                    domain="emc_emi_risk",
                    severity=severity,
                    title=f"EMI risk on {getattr(net_risk, 'net_name', 'unknown')}",
                    description=getattr(net_risk, "risk_factors", str(net_risk)),
                    signal_name=getattr(net_risk, "net_name", None),
                    measured_value=getattr(net_risk, "risk_score", None),
                ))

        for rec in getattr(emi_result, "recommendations", []):
            result.findings.append(ReviewFinding(
                domain="emc_emi_risk",
                severity="info",
                title="EMI recommendation",
                description=str(rec),
                recommendation=str(rec),
            ))

        overall = getattr(emi_result, "overall_risk_level", "low")
        result.status = "fail" if overall == "critical" else "warning" if overall in ("high", "medium") else "pass"
        result.raw_data = _safe_serialize(emi_result)
    except Exception as e:
        result.status = "error"
        result.error = str(e)
    return result


def _run_grounding_analysis(design: PCBDesignData) -> DomainResult:
    """Run grounding topology analysis."""
    from .analyzers.emc.grounding import GroundingAnalyzer, GroundPlane

    result = DomainResult(domain="emc_grounding", analyzer_name="GroundingAnalyzer")
    try:
        analyzer = GroundingAnalyzer()
        # Build ground planes from design zones
        planes = []
        gnd_zones = [z for z in design.zones if z.net_name and "gnd" in z.net_name.lower()]
        if gnd_zones:
            for i, zone in enumerate(gnd_zones):
                planes.append(GroundPlane(
                    layer_number=i,
                    name=zone.layer,
                    coverage_percent=80.0,
                    width_mm=design.board_width_mm or 100,
                    height_mm=design.board_height_mm or 100,
                ))
        else:
            # Assume at least one ground plane
            planes.append(GroundPlane(
                layer_number=0,
                name="GND",
                coverage_percent=80.0,
                width_mm=design.board_width_mm or 100,
                height_mm=design.board_height_mm or 100,
            ))

        gnd_result = analyzer.analyze_grounding(
            planes=planes,
            board_width_mm=design.board_width_mm or 100,
            board_height_mm=design.board_height_mm or 100,
            max_frequency_mhz=1000.0,
        )

        # Extract findings
        for issue in getattr(gnd_result, "issues", []):
            severity = getattr(issue, "severity", "warning")
            result.findings.append(ReviewFinding(
                domain="emc_grounding",
                severity=severity,
                title=f"Grounding: {getattr(issue, 'issue_type', 'issue')}",
                description=getattr(issue, "description", str(issue)),
                recommendation=getattr(issue, "recommendation", ""),
            ))

        result.status = "fail" if result.critical_count > 0 else "warning" if result.warning_count > 0 else "pass"
        result.raw_data = _safe_serialize(gnd_result)
    except Exception as e:
        result.status = "error"
        result.error = str(e)
    return result


def _run_pdn_analysis(
    design: PCBDesignData,
    net_cls: NetClassificationResult,
) -> DomainResult:
    """Run PDN impedance analysis for detected power rails."""
    from .analyzers.power_integrity.pdn_analyzer import PDNAnalyzer

    result = DomainResult(domain="power_integrity", analyzer_name="PDNAnalyzer")
    try:
        analyzer = PDNAnalyzer()
        power_nets = [nc for nc in net_cls.classified_nets if nc.category == "power"]

        if not power_nets:
            result.status = "skipped"
            return result

        # Analyze representative power rails
        for pn in power_nets[:10]:
            # Estimate voltage from net name
            voltage = _estimate_voltage_from_name(pn.net_name)
            if voltage <= 0:
                continue

            try:
                pdn_result = analyzer.analyze(
                    voltage=voltage,
                    max_current=1.0,
                    ripple_percent=5.0,
                    plane_area_mm2=(design.board_width_mm or 100) * (design.board_height_mm or 100) * 0.5,
                )

                for issue in getattr(pdn_result, "issues", []):
                    severity = getattr(issue, "severity", "warning")
                    result.findings.append(ReviewFinding(
                        domain="power_integrity",
                        severity=severity,
                        title=f"PDN issue on {pn.net_name}",
                        description=getattr(issue, "description", str(issue)),
                        recommendation=getattr(issue, "recommendation", ""),
                        signal_name=pn.net_name,
                    ))
            except Exception:
                pass  # Skip individual rail failures

        result.status = "fail" if result.critical_count > 0 else "warning" if result.warning_count > 0 else "pass"
    except Exception as e:
        result.status = "error"
        result.error = str(e)
    return result


def _run_thermal_analysis(
    design: PCBDesignData,
    thermal_limits: dict,
) -> DomainResult:
    """Run thermal analysis."""
    from .analyzers.thermal.power_dissipation import PowerDissipationAnalyzer

    result = DomainResult(domain="thermal", analyzer_name="PowerDissipationAnalyzer")
    try:
        analyzer = PowerDissipationAnalyzer()
        ambient = thermal_limits.get("max_ambient_c", 25.0)
        max_tj = thermal_limits.get("max_junction_c", 125.0)
        board_area = (design.board_width_mm or 100) * (design.board_height_mm or 100) / 100  # cm2

        # Build component list from design data
        components = []
        for comp in design.components:
            power_est = _estimate_component_power(comp)
            if power_est > 0:
                components.append({
                    "reference": comp.reference,
                    "package": comp.footprint or comp.package or "unknown",
                    "power_w": power_est,
                    "theta_ja": 40.0,  # Default estimate
                })

        if components:
            thermal_result = analyzer.analyze(
                components=components,
                ambient_temp_c=ambient,
                max_junction_temp_c=max_tj,
                board_area_cm2=board_area,
            )

            for issue in getattr(thermal_result, "issues", []):
                severity = getattr(issue, "severity", "warning")
                result.findings.append(ReviewFinding(
                    domain="thermal",
                    severity=severity,
                    title=f"Thermal: {getattr(issue, 'issue_type', 'issue')}",
                    description=getattr(issue, "description", str(issue)),
                    recommendation=getattr(issue, "recommendation", ""),
                ))

            result.raw_data = _safe_serialize(thermal_result)
        else:
            result.findings.append(ReviewFinding(
                domain="thermal",
                severity="info",
                title="No power-dissipating components identified",
                description="Could not estimate power dissipation from component data. Provide component power specs for detailed thermal analysis.",
            ))

        result.status = "fail" if result.critical_count > 0 else "warning" if result.warning_count > 0 else "pass"
    except Exception as e:
        result.status = "error"
        result.error = str(e)
    return result


def _run_dfm_placement_analysis(design: PCBDesignData) -> DomainResult:
    """Run DFM placement analysis."""
    from .analyzers.dfm.component_placement import PlacementAnalyzer, Component

    result = DomainResult(domain="dfm", analyzer_name="PlacementAnalyzer")
    try:
        analyzer = PlacementAnalyzer()

        # Build component list for analysis
        components = []
        for comp in design.components:
            components.append(Component(
                reference=comp.reference,
                package=comp.footprint or comp.package or "unknown",
                x_mm=comp.x_mm,
                y_mm=comp.y_mm,
                width_mm=3.0,  # Estimate
                height_mm=3.0,
                rotation_deg=comp.rotation,
                side="top" if "F" in comp.layer else "bottom",
            ))

        if len(components) >= 2:
            placement_result = analyzer.analyze(
                components=components,
                board_width_mm=design.board_width_mm or 100,
                board_height_mm=design.board_height_mm or 100,
            )

            for issue in getattr(placement_result, "issues", []):
                severity = getattr(issue, "severity", "warning")
                result.findings.append(ReviewFinding(
                    domain="dfm",
                    severity=severity,
                    title=f"DFM: {getattr(issue, 'issue_type', 'issue')}",
                    description=getattr(issue, "description", str(issue)),
                    recommendation=getattr(issue, "recommendation", ""),
                ))

            result.raw_data = _safe_serialize(placement_result)
        else:
            result.findings.append(ReviewFinding(
                domain="dfm",
                severity="info",
                title="Insufficient component data for placement analysis",
                description="Need at least 2 components with position data for placement DFM analysis.",
            ))

        result.status = "fail" if result.critical_count > 0 else "warning" if result.warning_count > 0 else "pass"
    except Exception as e:
        result.status = "error"
        result.error = str(e)
    return result


def _run_validation_analysis(design: PCBDesignData) -> DomainResult:
    """Run cross-validation and BOM checks."""
    from .analyzers.validation.bom_validator import BOMValidator
    from .analyzers.validation.schematic_layout_validator import SchematicLayoutValidator

    result = DomainResult(domain="validation", analyzer_name="Validators")
    try:
        if design.bom_items:
            bom_validator = BOMValidator()
            bom_result = bom_validator.validate(design)
            for issue in getattr(bom_result, "issues", []):
                result.findings.append(ReviewFinding(
                    domain="validation",
                    severity=getattr(issue, "severity", "warning"),
                    title=f"BOM: {getattr(issue, 'issue_type', 'issue')}",
                    description=getattr(issue, "description", str(issue)),
                ))

        if design.schematic_components:
            sch_validator = SchematicLayoutValidator()
            sch_result = sch_validator.validate(design)
            for mismatch in getattr(sch_result, "component_mismatches", []):
                result.findings.append(ReviewFinding(
                    domain="validation",
                    severity="warning",
                    title=f"Schematic mismatch: {getattr(mismatch, 'reference', 'unknown')}",
                    description=str(mismatch),
                ))

        if not design.bom_items and not design.schematic_components:
            result.findings.append(ReviewFinding(
                domain="validation",
                severity="info",
                title="No BOM or schematic data available",
                description="Upload BOM and/or schematic data for cross-validation checks.",
            ))

        result.status = "fail" if result.critical_count > 0 else "warning" if result.warning_count > 0 else "pass"
    except Exception as e:
        result.status = "error"
        result.error = str(e)
    return result


def _run_ddr_analysis(
    design: PCBDesignData,
    interfaces: InterfaceDetectionResult,
    net_cls: NetClassificationResult,
) -> DomainResult:
    """Run DDR-specific analysis based on detected interface."""
    from .analyzers.high_speed.ddr_analyzer import DDRAnalyzer, DDRStandard

    result = DomainResult(domain="high_speed_ddr", analyzer_name="DDRAnalyzer")
    try:
        analyzer = DDRAnalyzer()

        # Find DDR interface from detected interfaces
        ddr_iface = None
        for iface in interfaces.interfaces:
            if "ddr" in iface.interface_type.lower():
                ddr_iface = iface
                break

        if not ddr_iface:
            result.status = "skipped"
            return result

        # Determine DDR standard
        itype = ddr_iface.interface_type.upper()
        std_map = {
            "DDR3": DDRStandard.DDR3, "DDR4": DDRStandard.DDR4,
            "DDR5": DDRStandard.DDR5, "LPDDR4": DDRStandard.LPDDR4,
            "LPDDR5": DDRStandard.LPDDR5,
        }
        ddr_std = std_map.get(itype, DDRStandard.DDR4)

        # Build byte lane data from traces
        ddr_nets = [nc for nc in net_cls.classified_nets if nc.category == "ddr"]
        data_nets = [n for n in ddr_nets if n.subcategory == "data"]
        strobe_nets = [n for n in ddr_nets if n.subcategory == "strobe"]

        # Build minimal byte lane structure from trace data
        byte_lanes = []
        data_count = len(data_nets)
        lane_count = max(1, data_count // 8)
        for lane_idx in range(lane_count):
            lane_data_nets = data_nets[lane_idx * 8:(lane_idx + 1) * 8]
            dq_lengths = []
            for dn in lane_data_nets:
                net_obj = design.get_net_by_name(dn.net_name)
                if net_obj:
                    traces = design.get_traces_on_net(net_obj.index)
                    length = sum(t.calc_length() for t in traces)
                    dq_lengths.append(length)
                else:
                    dq_lengths.append(50.0)  # Default estimate

            # Find DQS for this lane
            dqs_length = 50.0
            if lane_idx < len(strobe_nets):
                dqs_net = design.get_net_by_name(strobe_nets[lane_idx].net_name)
                if dqs_net:
                    dqs_traces = design.get_traces_on_net(dqs_net.index)
                    dqs_length = sum(t.calc_length() for t in dqs_traces) or 50.0

            byte_lanes.append({
                "dq_lengths_mm": dq_lengths or [50.0],
                "dqs_length_mm": dqs_length,
            })

        if not byte_lanes:
            byte_lanes = [{"dq_lengths_mm": [50.0], "dqs_length_mm": 50.0}]

        # Determine data rate
        data_rate_map = {
            DDRStandard.DDR3: 1600, DDRStandard.DDR4: 2400,
            DDRStandard.DDR5: 4800, DDRStandard.LPDDR4: 3200,
            DDRStandard.LPDDR5: 5500,
        }
        data_rate = data_rate_map.get(ddr_std, 2400)

        ddr_result = analyzer.analyze(
            ddr_standard=ddr_std,
            data_rate_mtps=data_rate,
            byte_lanes=byte_lanes,
        )

        for issue in getattr(ddr_result, "issues", []):
            severity = getattr(issue, "severity", "warning")
            result.findings.append(ReviewFinding(
                domain="high_speed_ddr",
                severity=severity,
                title=f"DDR: {getattr(issue, 'issue_type', 'unknown')}",
                description=getattr(issue, "description", str(issue)),
                recommendation=getattr(issue, "recommendation", ""),
                signal_name=getattr(issue, "signal_name", None),
            ))

        result.status = "fail" if result.critical_count > 0 else "warning" if result.warning_count > 0 else "pass"
        result.raw_data = _safe_serialize(ddr_result)
    except Exception as e:
        result.status = "error"
        result.error = str(e)
    return result


def _run_usb_analysis(
    design: PCBDesignData,
    interfaces: InterfaceDetectionResult,
    net_cls: NetClassificationResult,
) -> DomainResult:
    """Run USB-specific analysis."""
    from .analyzers.high_speed.usb_analyzer import USBAnalyzer, USBVersion

    result = DomainResult(domain="high_speed_usb", analyzer_name="USBAnalyzer")
    try:
        analyzer = USBAnalyzer()

        usb_iface = None
        for iface in interfaces.interfaces:
            if "usb" in iface.interface_type.lower():
                usb_iface = iface
                break

        if not usb_iface:
            result.status = "skipped"
            return result

        # Determine USB version
        itype = usb_iface.interface_type.lower()
        if "3.2" in itype or "gen2x2" in itype:
            usb_ver = USBVersion.USB3_GEN2X2
        elif "3.1" in itype or "gen2" in itype:
            usb_ver = USBVersion.USB3_GEN2
        elif "3" in itype:
            usb_ver = USBVersion.USB3_GEN1
        else:
            usb_ver = USBVersion.USB2_HS

        # Build pair data from traces
        usb_nets = [nc for nc in net_cls.classified_nets if nc.category == "usb"]
        usb2_data = [n for n in usb_nets if n.subcategory and "usb2" in n.subcategory]
        ss_tx = [n for n in usb_nets if n.subcategory and "sstx" in n.subcategory]
        ss_rx = [n for n in usb_nets if n.subcategory and "ssrx" in n.subcategory]

        usb2_pair = None
        if usb2_data:
            lengths = []
            for n in usb2_data[:2]:
                net_obj = design.get_net_by_name(n.net_name)
                if net_obj:
                    traces = design.get_traces_on_net(net_obj.index)
                    lengths.append(sum(t.calc_length() for t in traces) or 50.0)
                else:
                    lengths.append(50.0)
            if len(lengths) >= 2:
                usb2_pair = {"p_length_mm": lengths[0], "n_length_mm": lengths[1]}

        sstx_pair = None
        if ss_tx:
            lengths = []
            for n in ss_tx[:2]:
                net_obj = design.get_net_by_name(n.net_name)
                if net_obj:
                    traces = design.get_traces_on_net(net_obj.index)
                    lengths.append(sum(t.calc_length() for t in traces) or 50.0)
                else:
                    lengths.append(50.0)
            if len(lengths) >= 2:
                sstx_pair = {"p_length_mm": lengths[0], "n_length_mm": lengths[1]}

        ssrx_pair = None
        if ss_rx:
            lengths = []
            for n in ss_rx[:2]:
                net_obj = design.get_net_by_name(n.net_name)
                if net_obj:
                    traces = design.get_traces_on_net(net_obj.index)
                    lengths.append(sum(t.calc_length() for t in traces) or 50.0)
                else:
                    lengths.append(50.0)
            if len(lengths) >= 2:
                ssrx_pair = {"p_length_mm": lengths[0], "n_length_mm": lengths[1]}

        usb_result = analyzer.analyze(
            usb_version=usb_ver,
            usb2_pair=usb2_pair,
            sstx_pair=sstx_pair,
            ssrx_pair=ssrx_pair,
        )

        for issue in getattr(usb_result, "issues", []):
            severity = getattr(issue, "severity", "warning")
            result.findings.append(ReviewFinding(
                domain="high_speed_usb",
                severity=severity,
                title=f"USB: {getattr(issue, 'issue_type', 'unknown')}",
                description=getattr(issue, "description", str(issue)),
                recommendation=getattr(issue, "recommendation", ""),
                signal_name=getattr(issue, "signal_name", None),
            ))

        result.status = "fail" if result.critical_count > 0 else "warning" if result.warning_count > 0 else "pass"
        result.raw_data = _safe_serialize(usb_result)
    except Exception as e:
        result.status = "error"
        result.error = str(e)
    return result


def _run_pcie_analysis(
    design: PCBDesignData,
    interfaces: InterfaceDetectionResult,
    net_cls: NetClassificationResult,
) -> DomainResult:
    """Run PCIe-specific analysis."""
    from .analyzers.high_speed.pcie_analyzer import PCIeAnalyzer, PCIeGeneration

    result = DomainResult(domain="high_speed_pcie", analyzer_name="PCIeAnalyzer")
    try:
        analyzer = PCIeAnalyzer()

        pcie_iface = None
        for iface in interfaces.interfaces:
            if "pcie" in iface.interface_type.lower():
                pcie_iface = iface
                break

        if not pcie_iface:
            result.status = "skipped"
            return result

        # Build lane data from traces
        pcie_nets = [nc for nc in net_cls.classified_nets if nc.category == "pcie"]
        tx_nets = [n for n in pcie_nets if n.subcategory == "tx"]
        rx_nets = [n for n in pcie_nets if n.subcategory == "rx"]

        # Build lane pairs
        tx_p = [n for n in tx_nets if n.differential_polarity == "P"]
        tx_n = [n for n in tx_nets if n.differential_polarity == "N"]
        rx_p = [n for n in rx_nets if n.differential_polarity == "P"]
        rx_n = [n for n in rx_nets if n.differential_polarity == "N"]

        lane_count = max(len(tx_p), len(rx_p), 1)
        lanes = []
        for i in range(lane_count):
            lane = {
                "tx_p_length_mm": 50.0, "tx_n_length_mm": 50.0,
                "rx_p_length_mm": 50.0, "rx_n_length_mm": 50.0,
                "via_count": 2,
            }
            # Get actual lengths from traces
            for nets_list, key in [(tx_p, "tx_p_length_mm"), (tx_n, "tx_n_length_mm"),
                                    (rx_p, "rx_p_length_mm"), (rx_n, "rx_n_length_mm")]:
                if i < len(nets_list):
                    net_obj = design.get_net_by_name(nets_list[i].net_name)
                    if net_obj:
                        traces = design.get_traces_on_net(net_obj.index)
                        length = sum(t.calc_length() for t in traces)
                        if length > 0:
                            lane[key] = length
            lanes.append(lane)

        pcie_result = analyzer.analyze(
            generation=PCIeGeneration.GEN3,
            lanes=lanes,
        )

        for issue in getattr(pcie_result, "issues", []):
            severity = getattr(issue, "severity", "warning")
            result.findings.append(ReviewFinding(
                domain="high_speed_pcie",
                severity=severity,
                title=f"PCIe: {getattr(issue, 'issue_type', 'unknown')}",
                description=getattr(issue, "description", str(issue)),
                recommendation=getattr(issue, "recommendation", ""),
                signal_name=getattr(issue, "signal_name", None),
            ))

        result.status = "fail" if result.critical_count > 0 else "warning" if result.warning_count > 0 else "pass"
        result.raw_data = _safe_serialize(pcie_result)
    except Exception as e:
        result.status = "error"
        result.error = str(e)
    return result


def _run_ethernet_analysis(
    design: PCBDesignData,
    interfaces: InterfaceDetectionResult,
    net_cls: NetClassificationResult,
) -> DomainResult:
    """Run Ethernet-specific analysis."""
    from .analyzers.high_speed.ethernet_analyzer import EthernetAnalyzer, EthernetSpeed

    result = DomainResult(domain="high_speed_ethernet", analyzer_name="EthernetAnalyzer")
    try:
        analyzer = EthernetAnalyzer()

        eth_iface = None
        for iface in interfaces.interfaces:
            itype = iface.interface_type.lower()
            if itype in ("gbe", "100base-tx", "sgmii", "ethernet"):
                eth_iface = iface
                break

        if not eth_iface:
            result.status = "skipped"
            return result

        # Determine speed
        itype = eth_iface.interface_type.lower()
        if "gbe" in itype or "1g" in itype:
            speed = EthernetSpeed.ETH_1G
        elif "100" in itype:
            speed = EthernetSpeed.ETH_100M
        elif "sgmii" in itype:
            speed = EthernetSpeed.ETH_1G
        else:
            speed = EthernetSpeed.ETH_1G

        # Build MDI pairs from classified nets
        eth_nets = [nc for nc in net_cls.classified_nets if nc.category == "ethernet"]
        mdi_nets = [n for n in eth_nets if n.subcategory and "mdi" in n.subcategory]

        mdi_pairs = []
        p_nets = [n for n in mdi_nets if n.differential_polarity == "P"]
        n_nets = [n for n in mdi_nets if n.differential_polarity == "N"]

        pair_count = max(len(p_nets), len(n_nets), 1)
        for i in range(min(pair_count, 4)):
            p_len = 50.0
            n_len = 50.0
            if i < len(p_nets):
                net_obj = design.get_net_by_name(p_nets[i].net_name)
                if net_obj:
                    traces = design.get_traces_on_net(net_obj.index)
                    p_len = sum(t.calc_length() for t in traces) or 50.0
            if i < len(n_nets):
                net_obj = design.get_net_by_name(n_nets[i].net_name)
                if net_obj:
                    traces = design.get_traces_on_net(net_obj.index)
                    n_len = sum(t.calc_length() for t in traces) or 50.0

            mdi_pairs.append({
                "pair_name": f"MDI{i}",
                "p_length_mm": p_len,
                "n_length_mm": n_len,
            })

        if not mdi_pairs:
            mdi_pairs = [{"pair_name": "MDI0", "p_length_mm": 50.0, "n_length_mm": 50.0}]

        eth_result = analyzer.analyze(
            speed=speed,
            mdi_pairs=mdi_pairs,
        )

        for issue in getattr(eth_result, "issues", []):
            severity = getattr(issue, "severity", "warning")
            result.findings.append(ReviewFinding(
                domain="high_speed_ethernet",
                severity=severity,
                title=f"Ethernet: {getattr(issue, 'issue_type', 'unknown')}",
                description=getattr(issue, "description", str(issue)),
                recommendation=getattr(issue, "recommendation", ""),
            ))

        result.status = "fail" if result.critical_count > 0 else "warning" if result.warning_count > 0 else "pass"
        result.raw_data = _safe_serialize(eth_result)
    except Exception as e:
        result.status = "error"
        result.error = str(e)
    return result


# =============================================================================
# Cross-domain correlation
# =============================================================================

def _cross_correlate(
    domain_results: list[DomainResult],
    design: PCBDesignData,
    classification: DesignClassificationResult,
) -> list[CrossCorrelation]:
    """Find cross-domain correlations between findings."""
    correlations = []

    # Build lookup by domain
    by_domain = {dr.domain: dr for dr in domain_results}

    # --- Thermal x SI: High-power components near high-speed traces ---
    thermal = by_domain.get("thermal")
    hs_domains = [by_domain.get(d) for d in
                  ("high_speed_ddr", "high_speed_usb", "high_speed_pcie", "high_speed_ethernet")
                  if d in by_domain]
    if thermal and any(hs_domains):
        thermal_issues = [f for f in (thermal.findings if thermal else []) if f.severity in ("critical", "warning")]
        hs_issues = []
        for hsd in hs_domains:
            if hsd:
                hs_issues.extend([f for f in hsd.findings if f.severity in ("critical", "warning")])

        if thermal_issues and hs_issues:
            correlations.append(CrossCorrelation(
                domains=["thermal", "high_speed"],
                title="Thermal hotspots near high-speed signals",
                description=(
                    f"Found {len(thermal_issues)} thermal issue(s) and {len(hs_issues)} "
                    f"high-speed routing issue(s). Thermal effects on high-speed traces can "
                    f"cause impedance shifts and timing degradation."
                ),
                severity="warning",
                recommendation=(
                    "Verify high-power components are not adjacent to critical high-speed traces. "
                    "Consider thermal relief and additional ground vias between hot components and "
                    "sensitive signal paths."
                ),
            ))

    # --- EMC x Routing: Split-plane crossings on high-speed nets ---
    rp = by_domain.get("emc_return_path")
    emi = by_domain.get("emc_emi_risk")
    if rp and emi:
        rp_critical = [f for f in rp.findings if f.severity == "critical"]
        emi_critical = [f for f in emi.findings if f.severity == "critical"]
        if rp_critical and emi_critical:
            correlations.append(CrossCorrelation(
                domains=["emc_return_path", "emc_emi_risk"],
                title="Return path discontinuities driving EMI risk",
                description=(
                    f"Return path analysis found {len(rp_critical)} critical issue(s) "
                    f"and EMI scoring found {len(emi_critical)} critical risk(s). "
                    f"Split-plane crossings on high-speed nets are a primary source of "
                    f"radiated emissions."
                ),
                severity="critical",
                recommendation=(
                    "Prioritize fixing return path discontinuities. Add stitching vias near "
                    "layer transitions. Route high-speed signals over continuous reference planes."
                ),
            ))

    # --- Power x Decoupling: PDN impedance at interface frequencies ---
    pdn = by_domain.get("power_integrity")
    if pdn and any(hs_domains):
        pdn_issues = [f for f in pdn.findings if f.severity in ("critical", "warning")]
        if pdn_issues:
            correlations.append(CrossCorrelation(
                domains=["power_integrity", "high_speed"],
                title="PDN impedance concerns at interface frequencies",
                description=(
                    f"Found {len(pdn_issues)} PDN issue(s) that could affect high-speed "
                    f"interface performance. Supply noise couples into signal integrity margins."
                ),
                severity="warning",
                recommendation=(
                    "Ensure adequate decoupling at frequencies matching interface data rates. "
                    "Place decoupling capacitors close to IC power pins with short, low-inductance "
                    "connections."
                ),
            ))

    # --- DFM x All: Manufacturing constraints affecting electrical ---
    dfm = by_domain.get("dfm")
    gnd = by_domain.get("emc_grounding")
    if dfm:
        dfm_critical = [f for f in dfm.findings if f.severity in ("critical", "warning")]
        if dfm_critical and gnd:
            gnd_issues = [f for f in gnd.findings if f.severity in ("critical", "warning")]
            if gnd_issues:
                correlations.append(CrossCorrelation(
                    domains=["dfm", "emc_grounding"],
                    title="DFM constraints affecting EMC grounding",
                    description=(
                        f"DFM has {len(dfm_critical)} issue(s) and grounding has "
                        f"{len(gnd_issues)} issue(s). Component placement and manufacturing "
                        f"constraints can limit ground plane continuity."
                    ),
                    severity="warning",
                    recommendation=(
                        "Review component placement for impact on ground plane integrity. "
                        "Ensure critical ground connections are not compromised by assembly constraints."
                    ),
                ))

    return correlations


# =============================================================================
# Risk matrix
# =============================================================================

def _build_risk_matrix(
    domain_results: list[DomainResult],
    cross_correlations: list[CrossCorrelation],
) -> list[RiskEntry]:
    """Build risk matrix from all findings."""
    entries = []

    severity_score = {"critical": 3, "high": 3, "warning": 2, "medium": 2, "low": 1, "info": 1}
    likelihood_map = {"critical": "high", "high": "high", "warning": "medium", "medium": "medium", "low": "low", "info": "low"}

    # From domain findings
    for dr in domain_results:
        for f in dr.findings:
            if f.severity in ("critical", "warning", "high", "medium"):
                sev = "critical" if f.severity in ("critical", "high") else "warning"
                lik = likelihood_map.get(f.severity, "medium")
                lik_score = {"high": 3, "medium": 2, "low": 1}.get(lik, 1)
                risk_score = severity_score.get(f.severity, 1) * lik_score
                entries.append(RiskEntry(
                    finding_title=f.title,
                    severity=sev,
                    likelihood=lik,
                    risk_score=min(9, risk_score),
                ))

    # From cross-correlations (bump risk score)
    for cc in cross_correlations:
        sev = cc.severity
        lik = "high" if sev == "critical" else "medium"
        lik_score = {"high": 3, "medium": 2, "low": 1}.get(lik, 1)
        sev_score = severity_score.get(sev, 1)
        entries.append(RiskEntry(
            finding_title=cc.title,
            severity=sev,
            likelihood=lik,
            risk_score=min(9, sev_score * lik_score),
        ))

    # Sort by risk score descending
    entries.sort(key=lambda e: e.risk_score, reverse=True)
    return entries


# =============================================================================
# Executive summary and recommendations
# =============================================================================

def _build_executive_summary(
    domain_results: list[DomainResult],
    classification: DesignClassificationResult,
    cross_correlations: list[CrossCorrelation],
) -> dict:
    """Build executive summary with pass/fail/warning counts per domain."""
    total_critical = 0
    total_warning = 0
    total_info = 0
    domain_statuses = {}

    for dr in domain_results:
        total_critical += dr.critical_count
        total_warning += dr.warning_count
        total_info += dr.info_count
        domain_statuses[dr.domain] = {
            "status": dr.status,
            "critical": dr.critical_count,
            "warnings": dr.warning_count,
            "info": dr.info_count,
        }

    overall = "FAIL" if total_critical > 0 else "WARNING" if total_warning > 0 else "PASS"

    return {
        "overall_status": overall,
        "design_type": classification.design_type,
        "complexity": classification.complexity_label,
        "total_critical": total_critical,
        "total_warnings": total_warning,
        "total_info": total_info,
        "total_findings": total_critical + total_warning + total_info,
        "domains_analyzed": len(domain_results),
        "cross_correlations": len(cross_correlations),
        "domain_statuses": domain_statuses,
    }


def _build_recommendations(
    domain_results: list[DomainResult],
    cross_correlations: list[CrossCorrelation],
    risk_matrix: list[RiskEntry],
) -> list[dict]:
    """Build prioritized recommendations."""
    recs = []
    seen = set()

    # From risk matrix (highest risk first)
    for risk in risk_matrix:
        if risk.risk_score >= 4:
            # Find the matching finding
            for dr in domain_results:
                for f in dr.findings:
                    if f.title == risk.finding_title and f.recommendation and f.recommendation not in seen:
                        seen.add(f.recommendation)
                        recs.append({
                            "priority": "high" if risk.risk_score >= 6 else "medium",
                            "domain": f.domain,
                            "recommendation": f.recommendation,
                            "risk_score": risk.risk_score,
                        })

    # From cross-correlations
    for cc in cross_correlations:
        if cc.recommendation not in seen:
            seen.add(cc.recommendation)
            recs.append({
                "priority": "high" if cc.severity == "critical" else "medium",
                "domain": " + ".join(cc.domains),
                "recommendation": cc.recommendation,
                "risk_score": 6 if cc.severity == "critical" else 4,
            })

    # From remaining findings with recommendations
    for dr in domain_results:
        for f in dr.findings:
            if f.recommendation and f.recommendation not in seen:
                seen.add(f.recommendation)
                recs.append({
                    "priority": "low",
                    "domain": f.domain,
                    "recommendation": f.recommendation,
                    "risk_score": 2,
                })

    # Sort by risk_score descending
    recs.sort(key=lambda r: r["risk_score"], reverse=True)
    return recs


# =============================================================================
# Main orchestration
# =============================================================================

def run_design_review(
    design: PCBDesignData,
    session_id: str,
) -> ReviewResult:
    """Run full orchestrated design review.

    1. Classify design type and detect interfaces
    2. Select relevant analyzers based on detected interfaces
    3. Run all selected analyzers
    4. Cross-correlate findings
    5. Build risk matrix, executive summary, and recommendations

    Args:
        design: PCBDesignData with parsed design data and optional review_context.
        session_id: Session identifier.

    Returns:
        ReviewResult with all findings, correlations, and recommendations.
    """
    ctx = design.review_context or {}

    # Phase 1: Classification
    net_classifier = NetClassifier()
    net_cls = net_classifier.classify(design)

    iface_detector = InterfaceDetector()
    interfaces = iface_detector.detect(design, net_cls)

    design_classifier = DesignClassifier()
    classification = design_classifier.classify(design, net_cls, interfaces)

    # Phase 2: Select analyzers
    analyzer_keys = _select_analyzers(design, classification, interfaces, net_cls)

    # Phase 3: Run analyzers
    domain_results: list[DomainResult] = []
    standard = (ctx.get("target_standards") or ["FCC_B"])[0]
    thermal_limits = ctx.get("thermal_limits", {})

    for key in analyzer_keys:
        if key == "return_path":
            domain_results.append(_run_return_path_analysis(design, net_cls))
        elif key == "emi_risk":
            domain_results.append(_run_emi_risk_analysis(design, net_cls, standard))
        elif key == "emc_grounding":
            domain_results.append(_run_grounding_analysis(design))
        elif key == "pdn":
            domain_results.append(_run_pdn_analysis(design, net_cls))
        elif key == "thermal":
            domain_results.append(_run_thermal_analysis(design, thermal_limits))
        elif key == "dfm_placement":
            domain_results.append(_run_dfm_placement_analysis(design))
        elif key == "validation":
            domain_results.append(_run_validation_analysis(design))
        elif key == "ddr":
            domain_results.append(_run_ddr_analysis(design, interfaces, net_cls))
        elif key == "usb":
            domain_results.append(_run_usb_analysis(design, interfaces, net_cls))
        elif key == "pcie":
            domain_results.append(_run_pcie_analysis(design, interfaces, net_cls))
        elif key == "ethernet":
            domain_results.append(_run_ethernet_analysis(design, interfaces, net_cls))

    # Phase 4: Cross-correlation
    cross_correlations = _cross_correlate(domain_results, design, classification)

    # Phase 5: Risk matrix, summary, recommendations
    risk_matrix = _build_risk_matrix(domain_results, cross_correlations)
    executive_summary = _build_executive_summary(domain_results, classification, cross_correlations)
    recommendations = _build_recommendations(domain_results, cross_correlations, risk_matrix)

    review_result = ReviewResult(
        session_id=session_id,
        timestamp=time.time(),
        design_classification=classification.to_dict(),
        detected_interfaces=[iface.interface_type for iface in interfaces.interfaces],
        domain_results=domain_results,
        cross_correlations=cross_correlations,
        risk_matrix=risk_matrix,
        executive_summary=executive_summary,
        recommendations=recommendations,
        review_context=ctx,
    )

    # Store in session
    design.review_results = review_result.to_dict()

    return review_result


# =============================================================================
# Report generation
# =============================================================================

def generate_report(
    design: PCBDesignData,
    session_id: str,
    report_format: str = "detailed",
) -> dict:
    """Generate a structured report from stored review results.

    Args:
        design: PCBDesignData with review_results populated.
        session_id: Session identifier.
        report_format: "summary", "detailed", or "json".

    Returns:
        Report dict in the requested format.
    """
    results = design.review_results
    if not results:
        return {"error": "No review results found. Run pcb_run_design_review first."}

    if report_format == "json":
        return results

    if report_format == "summary":
        summary = results.get("executive_summary", {})
        return {
            "report_type": "summary",
            "overall_status": summary.get("overall_status", "UNKNOWN"),
            "design_type": summary.get("design_type", "unknown"),
            "complexity": summary.get("complexity", "unknown"),
            "total_findings": summary.get("total_findings", 0),
            "critical": summary.get("total_critical", 0),
            "warnings": summary.get("total_warnings", 0),
            "info": summary.get("total_info", 0),
            "domains_analyzed": summary.get("domains_analyzed", 0),
            "cross_correlations": summary.get("cross_correlations", 0),
            "top_risks": [r for r in results.get("risk_matrix", [])[:5]],
            "top_recommendations": results.get("recommendations", [])[:5],
            "domain_statuses": summary.get("domain_statuses", {}),
        }

    # Detailed report
    summary = results.get("executive_summary", {})
    domain_details = []
    for dr in results.get("domain_results", []):
        domain_details.append({
            "domain": dr.get("domain", ""),
            "status": dr.get("status", ""),
            "critical": dr.get("critical_count", 0),
            "warnings": dr.get("warning_count", 0),
            "info": dr.get("info_count", 0),
            "findings": dr.get("findings", []),
        })

    return {
        "report_type": "detailed",
        "session_id": session_id,
        "executive_summary": summary,
        "design_classification": results.get("design_classification", {}),
        "detected_interfaces": results.get("detected_interfaces", []),
        "domain_details": domain_details,
        "cross_correlations": results.get("cross_correlations", []),
        "risk_matrix": results.get("risk_matrix", []),
        "recommendations": results.get("recommendations", []),
        "review_context": results.get("review_context", {}),
    }


# =============================================================================
# Helpers
# =============================================================================

def _safe_serialize(obj) -> dict:
    """Safely serialize an object to a dict."""
    try:
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        elif hasattr(obj, "__dataclass_fields__"):
            from dataclasses import asdict
            return asdict(obj)
        elif isinstance(obj, dict):
            return obj
        return {"raw": str(obj)}
    except Exception:
        return {"raw": str(obj)}


def _estimate_voltage_from_name(name: str) -> float:
    """Estimate voltage from a power net name."""
    import re
    name_upper = name.upper()

    # Match patterns like V3P3, V1P8, +3V3, VCC3V3, etc.
    m = re.search(r'(\d+)[PV](\d+)', name_upper)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")

    m = re.search(r'\+?(\d+)V(\d+)', name_upper)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")

    m = re.search(r'\+?(\d+)V\b', name_upper)
    if m:
        return float(m.group(1))

    # Common rail names
    if "3V3" in name_upper or "3P3" in name_upper:
        return 3.3
    if "1V8" in name_upper or "1P8" in name_upper:
        return 1.8
    if "1V2" in name_upper or "1P2" in name_upper:
        return 1.2
    if "5V" in name_upper:
        return 5.0
    if "12V" in name_upper:
        return 12.0

    return 0.0


def _estimate_component_power(comp) -> float:
    """Estimate power dissipation from component properties."""
    ref = comp.reference.upper()
    fp = (comp.footprint or comp.package or "").upper()

    # ICs (processors, FPGAs, etc.)
    if ref.startswith("U"):
        if any(x in fp for x in ("BGA", "QFP", "QFN")):
            if "BGA" in fp:
                return 2.0  # Estimate for BGA ICs
            return 0.5
        return 0.1

    # Voltage regulators
    if ref.startswith("VR") or ref.startswith("REG"):
        return 1.0

    # Power MOSFETs
    if ref.startswith("Q"):
        if any(x in fp for x in ("SOT223", "DPAK", "D2PAK", "TO252", "TO263")):
            return 1.0
        return 0.1

    return 0.0

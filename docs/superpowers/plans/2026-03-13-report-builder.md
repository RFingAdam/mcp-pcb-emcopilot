# Report Builder Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a generalized MCP tool that generates professional DOCX + HTML design review reports from any PCB session's analysis results.

**Architecture:** A `ReportBuilder` class harvests analysis results from the session, constructs `TrackedFinding` objects with full traceability (net/layer/component/coordinates), builds 30 fixed-order report sections (skipping empty ones), and outputs DOCX + HTML via existing helpers. One new MCP tool `pcb_generate_design_review_report` exposes this.

**Tech Stack:** Python 3.10+, python-docx (existing dep), existing `docx_report.py` / `html_report.py` / `simulation_plots.py` helpers.

**Spec:** `docs/superpowers/specs/2026-03-13-report-builder-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/mcp_pcb_emcopilot/reports/tracked_finding.py` | Create | `TrackedFinding` dataclass with traceability fields |
| `src/mcp_pcb_emcopilot/reports/section_registry.py` | Create | `SectionDef` dataclass and `REPORT_SECTIONS` ordered list |
| `src/mcp_pcb_emcopilot/reports/report_builder.py` | Create | `ReportBuilder` class — session harvesting, section builders, document assembly |
| `src/mcp_pcb_emcopilot/reports/__init__.py` | Modify | Export `ReportBuilder`, `TrackedFinding` |
| `src/mcp_pcb_emcopilot/reports/docx_report.py` | Modify | Make helper functions public (remove `_` prefix) |
| `src/mcp_pcb_emcopilot/models/pcb_data.py` | Modify | Add `analysis_cache` field to `PCBDesignData` |
| `src/mcp_pcb_emcopilot/server.py` | Modify | Add `pcb_generate_design_review_report` tool definition + handler |
| `tests/test_tracked_finding.py` | Create | Unit tests for `TrackedFinding` |
| `tests/test_section_registry.py` | Create | Unit tests for section ordering |
| `tests/test_report_builder.py` | Create | Integration tests for `ReportBuilder` |

---

## Chunk 1: TrackedFinding Dataclass

### Task 1: TrackedFinding dataclass

**Files:**
- Create: `src/mcp_pcb_emcopilot/reports/tracked_finding.py`
- Create: `tests/test_tracked_finding.py`

- [ ] **Step 1: Write failing tests for TrackedFinding**

```python
"""Tests for the TrackedFinding dataclass."""

from __future__ import annotations

import pytest

from mcp_pcb_emcopilot.reports.tracked_finding import TrackedFinding


class TestTrackedFindingCreation:
    """Tests for creating TrackedFinding instances."""

    def test_full_traceability_fields(self):
        """Finding with all traceability fields should serialize correctly."""
        f = TrackedFinding(
            finding_id="ANT-001",
            severity="WARNING",
            domain="antenna",
            title="Trace resonant at 2.4 GHz WiFi band",
            nets=["WiFi_2.4GHz"],
            layers=["L1"],
            components=["U12 (WiFi SoC)", "J8 (antenna connector)"],
            coordinates_mm=[(10.0, 20.0), (41.2, 20.0)],
            trace_length_mm=31.2,
            what_it_means="This trace acts as a quarter-wave antenna at 2.4 GHz.",
            how_calculated="f = c / (4 * L * sqrt(er_eff))",
            physical_mechanism="Quarter-wave monopole radiates and receives at WiFi frequency.",
            measured_value="31.2 mm routed length on L1 microstrip",
            limit_value="lambda/4 at 2.4 GHz = 31.25 mm",
            margin="-0.05 mm (resonant match)",
            recommendation="Route on inner layer L3 with continuous GND reference.",
            reference_standard="FCC Part 15.109",
        )
        d = f.to_dict()
        assert d["finding_id"] == "ANT-001"
        assert d["severity"] == "WARNING"
        assert d["nets"] == ["WiFi_2.4GHz"]
        assert d["layers"] == ["L1"]
        assert d["components"] == ["U12 (WiFi SoC)", "J8 (antenna connector)"]
        assert d["trace_length_mm"] == 31.2
        assert "quarter-wave" in d["what_it_means"]

    def test_optional_fields_default_to_none_or_empty(self):
        """Finding with only required fields should work."""
        f = TrackedFinding(
            finding_id="EMC-001",
            severity="CRITICAL",
            domain="emc",
            title="Clock EMI at 900 MHz",
            what_it_means="Clock harmonic exceeds emission limit.",
            how_calculated="Trapezoidal harmonic envelope.",
            physical_mechanism="Harmonic radiation from clock trace.",
            measured_value="63.2 dB above FCC Class B",
            limit_value="43.5 dBuV/m",
            margin="-63.2 dB",
            recommendation="Enable SSC or add pi-filter.",
            reference_standard="FCC Part 15",
        )
        assert f.nets == []
        assert f.layers == []
        assert f.components == []
        assert f.coordinates_mm == []
        assert f.trace_length_mm is None
        assert f.plot_path is None
        assert f.render_path is None

    def test_to_dict_roundtrip(self):
        """to_dict output should contain all fields."""
        f = TrackedFinding(
            finding_id="SI-001",
            severity="PASS",
            domain="signal_integrity",
            title="LPDDR4 eye meets spec",
            what_it_means="Eye opening is adequate.",
            how_calculated="Statistical eye analysis.",
            physical_mechanism="ISI and jitter reduce eye opening.",
            measured_value="738 mV height, 0.93 UI width",
            limit_value="> 200 mV, > 0.7 UI",
            margin="+538 mV, +0.23 UI",
            recommendation="",
            reference_standard="JEDEC JESD209-4",
            plot_path="/tmp/eye.png",
        )
        d = f.to_dict()
        assert set(d.keys()) == {
            "finding_id", "severity", "domain", "title",
            "nets", "layers", "components", "coordinates_mm",
            "trace_length_mm",
            "what_it_means", "how_calculated", "physical_mechanism",
            "measured_value", "limit_value", "margin",
            "recommendation", "reference_standard",
            "plot_path", "render_path",
        }


class TestTrackedFindingSeverity:
    """Tests for severity validation."""

    @pytest.mark.parametrize("severity", ["CRITICAL", "HIGH", "WARNING", "INFO", "PASS"])
    def test_valid_severities(self, severity):
        """All five severity levels should be accepted."""
        f = TrackedFinding(
            finding_id="TEST-001",
            severity=severity,
            domain="test",
            title="Test",
            what_it_means="x",
            how_calculated="x",
            physical_mechanism="x",
            measured_value="x",
            limit_value="x",
            margin="x",
            recommendation="x",
            reference_standard="x",
        )
        assert f.severity == severity

    def test_invalid_severity_raises(self):
        """Invalid severity string should raise ValueError."""
        with pytest.raises(ValueError, match="severity"):
            TrackedFinding(
                finding_id="TEST-001",
                severity="INVALID",
                domain="test",
                title="Test",
                what_it_means="x",
                how_calculated="x",
                physical_mechanism="x",
                measured_value="x",
                limit_value="x",
                margin="x",
                recommendation="x",
                reference_standard="x",
            )

    def test_severity_case_insensitive(self):
        """Severity should accept lowercase and normalize to uppercase."""
        f = TrackedFinding(
            finding_id="TEST-001",
            severity="critical",
            domain="test",
            title="Test",
            what_it_means="x",
            how_calculated="x",
            physical_mechanism="x",
            measured_value="x",
            limit_value="x",
            margin="x",
            recommendation="x",
            reference_standard="x",
        )
        assert f.severity == "CRITICAL"


class TestTrackedFindingId:
    """Tests for finding_id format."""

    def test_valid_id_format(self):
        """Finding ID should follow DOMAIN-NNN pattern."""
        f = TrackedFinding(
            finding_id="EMC-001",
            severity="HIGH",
            domain="emc",
            title="Test",
            what_it_means="x",
            how_calculated="x",
            physical_mechanism="x",
            measured_value="x",
            limit_value="x",
            margin="x",
            recommendation="x",
            reference_standard="x",
        )
        assert f.finding_id == "EMC-001"

    def test_invalid_id_format_raises(self):
        """Finding ID without dash-number should raise ValueError."""
        with pytest.raises(ValueError, match="finding_id"):
            TrackedFinding(
                finding_id="bad_id",
                severity="HIGH",
                domain="emc",
                title="Test",
                what_it_means="x",
                how_calculated="x",
                physical_mechanism="x",
                measured_value="x",
                limit_value="x",
                margin="x",
                recommendation="x",
                reference_standard="x",
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tracked_finding.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_pcb_emcopilot.reports.tracked_finding'`

- [ ] **Step 3: Implement TrackedFinding**

```python
"""TrackedFinding dataclass — traceable design review finding."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict


VALID_SEVERITIES = {"CRITICAL", "HIGH", "WARNING", "INFO", "PASS"}
_FINDING_ID_RE = re.compile(r"^[A-Z]+-\d{3}$")


@dataclass
class TrackedFinding:
    """A design review finding with full traceability.

    Every finding links back to specific nets, layers, components, and
    board coordinates so the report reader knows exactly what and where
    the issue is.
    """

    # Identity
    finding_id: str
    severity: str
    domain: str
    title: str

    # Explanation
    what_it_means: str
    how_calculated: str
    physical_mechanism: str

    # Data
    measured_value: str
    limit_value: str
    margin: str

    # Action
    recommendation: str
    reference_standard: str

    # Traceability (optional — not all findings map to a specific net)
    nets: list[str] = field(default_factory=list)
    layers: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    coordinates_mm: list[tuple] = field(default_factory=list)
    trace_length_mm: float | None = None

    # Visuals (populated during report generation)
    plot_path: str | None = None
    render_path: str | None = None

    def __post_init__(self):
        # Normalize and validate severity
        self.severity = self.severity.upper()
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(
                f"severity must be one of {VALID_SEVERITIES}, got '{self.severity}'"
            )
        # Validate finding_id format
        if not _FINDING_ID_RE.match(self.finding_id):
            raise ValueError(
                f"finding_id must match DOMAIN-NNN pattern (e.g., 'EMC-001'), "
                f"got '{self.finding_id}'"
            )

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return asdict(self)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tracked_finding.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/mcp_pcb_emcopilot/reports/tracked_finding.py tests/test_tracked_finding.py
git commit -m "feat: add TrackedFinding dataclass with traceability fields"
```

---

## Chunk 2: Section Registry

### Task 2: Section registry

**Files:**
- Create: `src/mcp_pcb_emcopilot/reports/section_registry.py`
- Create: `tests/test_section_registry.py`

- [ ] **Step 1: Write failing tests for section registry**

```python
"""Tests for the report section registry."""

from __future__ import annotations

import pytest

from mcp_pcb_emcopilot.reports.section_registry import (
    SectionDef,
    REPORT_SECTIONS,
    get_section_by_key,
)


class TestSectionDef:
    """Tests for SectionDef dataclass."""

    def test_section_def_creation(self):
        s = SectionDef(number=1, key="executive_summary", title="Executive Summary", required=True)
        assert s.number == 1
        assert s.key == "executive_summary"
        assert s.title == "Executive Summary"
        assert s.required is True

    def test_section_def_default_not_required(self):
        s = SectionDef(number=7, key="impedance", title="Impedance Analysis")
        assert s.required is False


class TestReportSections:
    """Tests for the REPORT_SECTIONS constant."""

    def test_all_30_sections_present(self):
        assert len(REPORT_SECTIONS) == 30

    def test_sections_numbered_1_to_30(self):
        numbers = [s.number for s in REPORT_SECTIONS]
        assert numbers == list(range(1, 31))

    def test_no_duplicate_keys(self):
        keys = [s.key for s in REPORT_SECTIONS]
        assert len(keys) == len(set(keys))

    def test_no_duplicate_numbers(self):
        numbers = [s.number for s in REPORT_SECTIONS]
        assert len(numbers) == len(set(numbers))

    def test_required_sections(self):
        required = [s for s in REPORT_SECTIONS if s.required]
        required_keys = {s.key for s in required}
        assert "executive_summary" in required_keys
        assert "board_overview" in required_keys
        assert "action_items" in required_keys
        assert "tool_coverage" in required_keys
        assert "glossary" in required_keys
        assert "references" in required_keys
        assert "appendices" in required_keys

    def test_first_section_is_executive_summary(self):
        assert REPORT_SECTIONS[0].key == "executive_summary"

    def test_last_section_is_appendices(self):
        assert REPORT_SECTIONS[-1].key == "appendices"


class TestGetSectionByKey:
    """Tests for section lookup."""

    def test_lookup_existing_key(self):
        s = get_section_by_key("impedance")
        assert s is not None
        assert s.title == "Impedance Analysis"

    def test_lookup_missing_key_returns_none(self):
        assert get_section_by_key("nonexistent") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_section_registry.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement section registry**

```python
"""Report section registry — defines the fixed ordering and metadata for report sections."""

from __future__ import annotations

from dataclasses import dataclass


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_section_registry.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/mcp_pcb_emcopilot/reports/section_registry.py tests/test_section_registry.py
git commit -m "feat: add section registry with 30 fixed-order report sections"
```

---

## Chunk 3: Model & Helper Changes

### Task 3: Add analysis_cache to PCBDesignData

**Files:**
- Modify: `src/mcp_pcb_emcopilot/models/pcb_data.py:168` (after `review_results`)

- [ ] **Step 1: Write failing test**

Create `tests/test_analysis_cache.py`:

```python
"""Tests for analysis_cache field on PCBDesignData."""

from __future__ import annotations

from mcp_pcb_emcopilot.models.pcb_data import PCBDesignData


class TestAnalysisCache:

    def test_analysis_cache_exists_and_empty_by_default(self):
        """PCBDesignData should have an analysis_cache dict, empty by default."""
        d = PCBDesignData()
        assert hasattr(d, "analysis_cache")
        assert isinstance(d.analysis_cache, dict)
        assert len(d.analysis_cache) == 0

    def test_analysis_cache_stores_tool_results(self):
        """Should be able to store and retrieve analysis results."""
        d = PCBDesignData()
        d.analysis_cache["pcb_analyze_esd"] = {"status": "FAIL", "score": 0}
        d.analysis_cache["pcb_analyze_thermal"] = {"status": "PASS", "margin": 8.0}
        assert len(d.analysis_cache) == 2
        assert d.analysis_cache["pcb_analyze_esd"]["status"] == "FAIL"

    def test_analysis_cache_independent_between_instances(self):
        """Each PCBDesignData instance should have its own cache."""
        d1 = PCBDesignData()
        d2 = PCBDesignData()
        d1.analysis_cache["test"] = "value1"
        assert "test" not in d2.analysis_cache
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_analysis_cache.py -v`
Expected: FAIL with `AttributeError: 'PCBDesignData' object has no attribute 'analysis_cache'`

- [ ] **Step 3: Add analysis_cache field to PCBDesignData**

In `src/mcp_pcb_emcopilot/models/pcb_data.py`, after the `review_results` field (around line 168), add:

```python
    analysis_cache: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analysis_cache.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/mcp_pcb_emcopilot/models/pcb_data.py tests/test_analysis_cache.py
git commit -m "feat: add analysis_cache field to PCBDesignData"
```

### Task 4: Make docx_report.py helpers public

**Files:**
- Modify: `src/mcp_pcb_emcopilot/reports/docx_report.py`

- [ ] **Step 1: Rename private helpers to public**

In `src/mcp_pcb_emcopilot/reports/docx_report.py`, rename:
- `_add_styled_table` → `add_styled_table`
- `_add_finding_box` → `add_finding_box`
- `_add_image_with_caption` → `add_image_with_caption`

Also update all internal call sites within the same file that reference these functions.

- [ ] **Step 2: Run existing tests to verify nothing broke**

Run: `pytest tests/ -v -k "report or docx or html" --tb=short`
Expected: All existing report tests PASS

- [ ] **Step 3: Update reports/__init__.py exports**

In `src/mcp_pcb_emcopilot/reports/__init__.py`, add:

```python
"""PCB design review report generation."""

from .tracked_finding import TrackedFinding
from .section_registry import REPORT_SECTIONS, SectionDef, get_section_by_key

__all__ = [
    "TrackedFinding",
    "REPORT_SECTIONS",
    "SectionDef",
    "get_section_by_key",
]
```

- [ ] **Step 4: Commit**

```bash
git add src/mcp_pcb_emcopilot/reports/docx_report.py src/mcp_pcb_emcopilot/reports/__init__.py
git commit -m "refactor: make docx_report helpers public, update reports exports"
```

---

## Chunk 4: ReportBuilder Core

### Task 5: ReportBuilder — session harvesting and skeleton

**Files:**
- Create: `src/mcp_pcb_emcopilot/reports/report_builder.py`
- Create: `tests/test_report_builder.py`

- [ ] **Step 1: Write failing tests for ReportBuilder core**

```python
"""Tests for the ReportBuilder class."""

from __future__ import annotations

import os
import pytest

from mcp_pcb_emcopilot.models.pcb_data import PCBDesignData, PCBLayer, PCBComponent, PCBNet, PCBTrace
from mcp_pcb_emcopilot.reports.report_builder import ReportBuilder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_design(**overrides) -> PCBDesignData:
    """Create a minimal PCBDesignData for testing."""
    defaults = dict(
        source_file="test_board.kicad_pcb",
        source_format="kicad",
        board_width_mm=100.0,
        board_height_mm=80.0,
        board_thickness_mm=1.6,
        title="Test Board",
        layers=[
            PCBLayer(number=0, name="F.Cu", layer_type="signal", thickness_mm=0.035),
            PCBLayer(number=1, name="GND", layer_type="plane", thickness_mm=0.035),
            PCBLayer(number=2, name="PWR", layer_type="plane", thickness_mm=0.035),
            PCBLayer(number=3, name="B.Cu", layer_type="signal", thickness_mm=0.035),
        ],
        components=[
            PCBComponent(reference="U1", value="MCU", package="BGA-256",
                         x_mm=50.0, y_mm=40.0, layer="F.Cu", rotation=0.0),
        ],
        nets=[
            PCBNet(name="GND", pin_count=12),
            PCBNet(name="VCC_3V3", pin_count=6),
        ],
        traces=[
            PCBTrace(layer="F.Cu", width_mm=0.2, net_name="VCC_3V3",
                     length_mm=15.0, x1_mm=10.0, y1_mm=20.0, x2_mm=25.0, y2_mm=20.0),
        ],
    )
    defaults.update(overrides)
    return PCBDesignData(**defaults)


def _make_review_results():
    """Create synthetic review_results dict."""
    return {
        "overall_status": "WARNING",
        "domains": {
            "emc": {
                "status": "WARNING",
                "score": 75,
                "findings": [
                    {
                        "severity": "WARNING",
                        "title": "EMI risk moderate",
                        "detail": "Board EMI score 75/100",
                        "recommendation": "Add shielding",
                    }
                ],
            },
            "signal_integrity": {
                "status": "PASS",
                "score": 95,
                "findings": [
                    {
                        "severity": "PASS",
                        "title": "DDR eye diagram OK",
                        "detail": "Eye height 738 mV",
                        "recommendation": "",
                    }
                ],
            },
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReportBuilderInit:
    """Tests for ReportBuilder initialization."""

    def test_creates_with_design_data(self):
        design = _make_design()
        builder = ReportBuilder(design)
        assert builder.design is design

    def test_creates_with_title_override(self):
        design = _make_design()
        builder = ReportBuilder(design, title="Custom Report Title")
        assert builder.title == "Custom Report Title"

    def test_default_title_from_design(self):
        design = _make_design(title="Test Board")
        builder = ReportBuilder(design)
        assert "Test Board" in builder.title


class TestSessionHarvesting:
    """Tests for collecting analysis results."""

    def test_harvest_from_review_results(self):
        design = _make_design(review_results=_make_review_results())
        builder = ReportBuilder(design)
        results = builder._harvest_session()
        assert "emc" in results
        assert "signal_integrity" in results

    def test_harvest_from_analysis_cache(self):
        design = _make_design()
        design.analysis_cache["pcb_analyze_esd"] = {"status": "FAIL"}
        builder = ReportBuilder(design)
        results = builder._harvest_session()
        assert "pcb_analyze_esd" in results

    def test_harvest_merges_both_sources(self):
        design = _make_design(review_results=_make_review_results())
        design.analysis_cache["pcb_analyze_esd"] = {"status": "FAIL"}
        builder = ReportBuilder(design)
        results = builder._harvest_session()
        assert "emc" in results
        assert "pcb_analyze_esd" in results

    def test_empty_session_returns_empty(self):
        design = _make_design()
        builder = ReportBuilder(design)
        results = builder._harvest_session()
        assert isinstance(results, dict)


class TestReportGeneration:
    """Tests for generating report files."""

    def test_empty_session_produces_valid_docx(self, tmp_path):
        design = _make_design()
        builder = ReportBuilder(design, output_dir=str(tmp_path))
        result = builder.generate(format="docx")
        assert result["docx_path"].endswith(".docx")
        assert os.path.exists(result["docx_path"])
        assert result["sections_generated"] >= 7  # required sections always present
        assert result["overall_verdict"] is not None

    def test_empty_session_produces_valid_html(self, tmp_path):
        design = _make_design()
        builder = ReportBuilder(design, output_dir=str(tmp_path))
        result = builder.generate(format="html")
        assert result["html_path"].endswith(".html")
        assert os.path.exists(result["html_path"])

    def test_both_format_produces_both_files(self, tmp_path):
        design = _make_design()
        builder = ReportBuilder(design, output_dir=str(tmp_path))
        result = builder.generate(format="both")
        assert os.path.exists(result["docx_path"])
        assert os.path.exists(result["html_path"])

    def test_session_with_results_includes_domain_sections(self, tmp_path):
        design = _make_design(review_results=_make_review_results())
        builder = ReportBuilder(design, output_dir=str(tmp_path))
        result = builder.generate(format="docx")
        assert result["sections_generated"] > 7  # more than just required

    def test_findings_count_in_result(self, tmp_path):
        design = _make_design(review_results=_make_review_results())
        builder = ReportBuilder(design, output_dir=str(tmp_path))
        result = builder.generate(format="docx")
        fc = result["findings_count"]
        assert isinstance(fc, dict)
        assert "critical" in fc
        assert "high" in fc
        assert "warning" in fc
        assert "pass" in fc

    def test_overall_verdict_critical(self, tmp_path):
        results = _make_review_results()
        results["domains"]["emc"]["findings"][0]["severity"] = "CRITICAL"
        design = _make_design(review_results=results)
        builder = ReportBuilder(design, output_dir=str(tmp_path))
        result = builder.generate(format="docx")
        assert "CRITICAL" in result["overall_verdict"]

    def test_overall_verdict_pass(self, tmp_path):
        results = _make_review_results()
        for domain in results["domains"].values():
            for f in domain["findings"]:
                f["severity"] = "PASS"
        design = _make_design(review_results=results)
        builder = ReportBuilder(design, output_dir=str(tmp_path))
        result = builder.generate(format="docx")
        assert "PASS" in result["overall_verdict"]

    def test_custom_title_in_output(self, tmp_path):
        design = _make_design()
        builder = ReportBuilder(design, title="Acme Widget Rev C", output_dir=str(tmp_path))
        result = builder.generate(format="docx")
        assert os.path.exists(result["docx_path"])

    def test_custom_confidentiality(self, tmp_path):
        design = _make_design()
        builder = ReportBuilder(design, confidentiality="PUBLIC", output_dir=str(tmp_path))
        result = builder.generate(format="docx")
        assert os.path.exists(result["docx_path"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_report_builder.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement ReportBuilder skeleton**

Create `src/mcp_pcb_emcopilot/reports/report_builder.py` with:

1. `ReportBuilder.__init__(self, design, title=None, confidentiality="CONFIDENTIAL", output_dir="/tmp/pcb_reports", auto_render=True)`
2. `ReportBuilder.generate(self, format="both") -> dict` — main entry point
3. `ReportBuilder._harvest_session(self) -> dict` — collects review_results + analysis_cache
4. `ReportBuilder._determine_verdict(self, all_findings) -> str` — verdict logic from spec 2.2
5. `ReportBuilder._build_docx(self, results, all_findings, verdict) -> str` — assembles DOCX using docx_report.py helpers
6. `ReportBuilder._build_html(self, results, all_findings, verdict) -> str` — assembles HTML using html_report.py
7. Required section stubs: `_build_executive_summary`, `_build_board_overview`, `_build_action_items`, `_build_tool_coverage`, `_build_glossary`, `_build_references`, `_build_appendices`
8. Domain section stubs (one per skippable section) that check for data and skip if empty

The initial implementation should produce a valid DOCX/HTML with cover page, required sections, and any domain sections that have data. Domain-specific section builders can start as simple data dumps and be refined later.

This is the largest file (~400-800 lines). Implement the skeleton with working required sections first. Domain section builders can emit basic tables and finding boxes from the review_results structure.

**Key implementation details:**

```python
class ReportBuilder:
    def __init__(self, design, title=None, confidentiality="CONFIDENTIAL",
                 output_dir="/tmp/pcb_reports", auto_render=True):
        self.design = design
        self.title = title or f"{design.title or 'PCB'} Design Review"
        self.confidentiality = confidentiality
        self.output_dir = output_dir
        self.auto_render = auto_render
        os.makedirs(output_dir, exist_ok=True)

    def generate(self, format="both"):
        results = self._harvest_session()
        all_findings = self._collect_findings(results)
        verdict = self._determine_verdict(all_findings)

        output = {
            "sections_generated": 0,
            "sections_skipped": 0,
            "findings_count": self._count_findings(all_findings),
            "plots_generated": 0,
            "renders_generated": 0,
            "overall_verdict": verdict,
            "docx_path": None,
            "html_path": None,
            "file_size_kb": 0,
        }

        if format in ("docx", "both"):
            output["docx_path"] = self._build_docx(results, all_findings, verdict)
        if format in ("html", "both"):
            output["html_path"] = self._build_html(results, all_findings, verdict)

        # Compute total file size
        total_bytes = 0
        for key in ("docx_path", "html_path"):
            if output[key] and os.path.exists(output[key]):
                total_bytes += os.path.getsize(output[key])
        output["file_size_kb"] = round(total_bytes / 1024, 1)

        return output

    def _harvest_session(self):
        merged = {}
        if self.design.review_results:
            if "domains" in self.design.review_results:
                merged.update(self.design.review_results["domains"])
            else:
                merged.update(self.design.review_results)
        merged.update(self.design.analysis_cache)
        return merged

    def _determine_verdict(self, findings):
        severities = {f.severity for f in findings} if findings else set()
        if "CRITICAL" in severities:
            return "CRITICAL \u2014 Remediation Required Before Prototype"
        if "HIGH" in severities:
            return "CONDITIONAL \u2014 Proceed with Caution, Address HIGH Items"
        if "WARNING" in severities:
            return "PASS WITH WARNINGS \u2014 Review Recommended Items"
        return "PASS \u2014 Ready for Prototype"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_report_builder.py -v`
Expected: All 14 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/mcp_pcb_emcopilot/reports/report_builder.py tests/test_report_builder.py
git commit -m "feat: add ReportBuilder with session harvesting and DOCX/HTML generation"
```

---

## Chunk 5: MCP Tool Integration

### Task 6: Add pcb_generate_design_review_report tool to server.py

**Files:**
- Modify: `src/mcp_pcb_emcopilot/server.py`

- [ ] **Step 1: Add tool definition to the tools list in server.py**

Find the tool definitions section (around line 200-600 where all tools are defined) and add using the existing `_make_tool()` helper pattern:

```python
_make_tool("pcb_generate_design_review_report",
    "Generate a professional PCB design review report (DOCX and/or HTML) "
    "from all analysis results in the current session. Produces a complete "
    "document with executive summary, domain analysis sections, findings with "
    "full traceability, simulation plots, and priority action items.",
    {
        "session_id": {"type": "string", "description": "Session ID containing analysis results"},
        "format": {"type": "string", "enum": ["docx", "html", "both"], "default": "both", "description": "Output format"},
        "output_dir": {"type": "string", "description": "Directory for output files (default: /tmp/pcb_reports/)"},
        "title": {"type": "string", "description": "Report title (e.g., 'Product X Rev B PCB Design Review')"},
        "confidentiality": {"type": "string", "default": "CONFIDENTIAL", "description": "Confidentiality marking for header/footer"},
        "run_analysis": {"type": "boolean", "default": False, "description": "If true, runs pcb_run_design_review first"},
        "auto_render": {"type": "boolean", "default": True, "description": "Auto-generate board/net renders for findings"},
    },
    ["session_id"],
),
```

- [ ] **Step 2: Add handler in the tool dispatch section**

Find the handler section (around line 2398, near `pcb_generate_report`) and add before the session management section:

```python
# === DESIGN REVIEW REPORT (DOCX/HTML) ===
if name == "pcb_generate_design_review_report":
    from .reports.report_builder import ReportBuilder
    data = _get_session(args["session_id"])

    if args.get("run_analysis", False):
        from .orchestrator import run_design_review
        run_design_review(data, args["session_id"])

    builder = ReportBuilder(
        design=data,
        title=args.get("title"),
        confidentiality=args.get("confidentiality", "CONFIDENTIAL"),
        output_dir=args.get("output_dir", "/tmp/pcb_reports"),
        auto_render=args.get("auto_render", True),
    )
    return builder.generate(format=args.get("format", "both"))
```

- [ ] **Step 3: Run full test suite to verify nothing broke**

Run: `pytest tests/ -v --tb=short`
Expected: All tests PASS (existing + new)

- [ ] **Step 4: Commit**

```bash
git add src/mcp_pcb_emcopilot/server.py
git commit -m "feat: add pcb_generate_design_review_report MCP tool"
```

### Task 7: Update reports __init__.py with ReportBuilder export

**Files:**
- Modify: `src/mcp_pcb_emcopilot/reports/__init__.py`

- [ ] **Step 1: Add ReportBuilder to exports**

```python
"""PCB design review report generation."""

from .tracked_finding import TrackedFinding
from .section_registry import REPORT_SECTIONS, SectionDef, get_section_by_key
from .report_builder import ReportBuilder

__all__ = [
    "ReportBuilder",
    "TrackedFinding",
    "REPORT_SECTIONS",
    "SectionDef",
    "get_section_by_key",
]
```

- [ ] **Step 2: Commit**

```bash
git add src/mcp_pcb_emcopilot/reports/__init__.py
git commit -m "feat: export ReportBuilder from reports package"
```

---

## Chunk 6: Final Verification

### Task 8: Full integration test and CI check

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 2: Run linter**

Run: `ruff check src/mcp_pcb_emcopilot/reports/tracked_finding.py src/mcp_pcb_emcopilot/reports/section_registry.py src/mcp_pcb_emcopilot/reports/report_builder.py`
Expected: No errors

- [ ] **Step 3: Run type checker**

Run: `mypy src/mcp_pcb_emcopilot/reports/tracked_finding.py src/mcp_pcb_emcopilot/reports/section_registry.py src/mcp_pcb_emcopilot/reports/report_builder.py`
Expected: No errors

- [ ] **Step 4: Fix any issues found in steps 1-3, commit fixes**

- [ ] **Step 5: Final commit and push**

```bash
git push origin main
```

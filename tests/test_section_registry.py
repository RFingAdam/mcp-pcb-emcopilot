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

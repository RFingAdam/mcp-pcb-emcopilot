"""Tests for analysis_cache field on PCBDesignData."""

from __future__ import annotations

from mcp_pcb_emcopilot.models.pcb_data import PCBDesignData


class TestAnalysisCache:

    def test_analysis_cache_exists_and_empty_by_default(self):
        """PCBDesignData should have an analysis_cache dict, empty by default."""
        d = PCBDesignData(source_file="test.kicad_pcb")
        assert hasattr(d, "analysis_cache")
        assert isinstance(d.analysis_cache, dict)
        assert len(d.analysis_cache) == 0

    def test_analysis_cache_stores_tool_results(self):
        """Should be able to store and retrieve analysis results."""
        d = PCBDesignData(source_file="test.kicad_pcb")
        d.analysis_cache["pcb_analyze_esd"] = {"status": "FAIL", "score": 0}
        d.analysis_cache["pcb_analyze_thermal"] = {"status": "PASS", "margin": 8.0}
        assert len(d.analysis_cache) == 2
        assert d.analysis_cache["pcb_analyze_esd"]["status"] == "FAIL"

    def test_analysis_cache_independent_between_instances(self):
        """Each PCBDesignData instance should have its own cache."""
        d1 = PCBDesignData(source_file="test1.kicad_pcb")
        d2 = PCBDesignData(source_file="test2.kicad_pcb")
        d1.analysis_cache["test"] = "value1"
        assert "test" not in d2.analysis_cache

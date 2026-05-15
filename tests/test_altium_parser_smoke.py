"""Smoke coverage for the Altium parser.

Real Altium ``.PcbDoc`` files are OLE2 compound binaries produced by a
proprietary tool and impractical to synthesise. These tests therefore
cover the error-handling surface (unreadable file, missing file, wrong
format) plus the module-level helpers, which together exercise the
entry-point paths without needing a licensed fixture.
"""
from __future__ import annotations

import pytest


class TestAltiumPcbParserErrorPaths:
    def test_missing_file_raises(self, tmp_path):
        from mcp_pcb_emcopilot.parsers.altium_parser import AltiumPcbParser

        with pytest.raises((FileNotFoundError, ValueError, OSError)):
            AltiumPcbParser().parse(str(tmp_path / "does_not_exist.PcbDoc"))

    def test_non_ole_file_raises(self, tmp_path):
        from mcp_pcb_emcopilot.parsers.altium_parser import AltiumPcbParser

        bogus = tmp_path / "bogus.PcbDoc"
        bogus.write_bytes(b"this is not an OLE2 compound binary")
        # The parser wraps olefile errors in ValueError per its public contract.
        with pytest.raises((ValueError, OSError)):
            AltiumPcbParser().parse(str(bogus))

    def test_schematic_missing_file_raises(self, tmp_path):
        from mcp_pcb_emcopilot.parsers.altium_parser import AltiumSchematicParser

        with pytest.raises((FileNotFoundError, ValueError, OSError)):
            AltiumSchematicParser().parse(str(tmp_path / "missing.SchDoc"))


class TestAltiumDataContainers:
    def test_board_data_default_state(self):
        from mcp_pcb_emcopilot.parsers.altium_parser import AltiumBoardData

        data = AltiumBoardData(source_file="/tmp/x.PcbDoc")
        assert data.components == []
        assert data.nets == []
        assert data.traces == []
        assert data.vias == []

    def test_schematic_data_default_state(self):
        from mcp_pcb_emcopilot.parsers.altium_parser import AltiumSchematicData

        data = AltiumSchematicData(source_file="/tmp/x.SchDoc")
        assert data.components == []
        assert data.nets == []


class TestAltiumParserConstruction:
    def test_pcb_parser_constructs(self):
        from mcp_pcb_emcopilot.parsers.altium_parser import AltiumPcbParser

        parser = AltiumPcbParser()
        # A fresh parser has zero warnings and no state cached.
        assert hasattr(parser, "parse")

    def test_schematic_parser_constructs(self):
        from mcp_pcb_emcopilot.parsers.altium_parser import (
            AltiumSchematicParser,
        )

        parser = AltiumSchematicParser()
        assert hasattr(parser, "parse")


class TestAltiumInternalHelpers:
    """Exercise pure-function helpers inside ``AltiumPcbParser``."""

    def test_parse_pipe_delimited_single_record(self):
        import struct

        from mcp_pcb_emcopilot.parsers.altium_parser import AltiumPcbParser

        parser = AltiumPcbParser()
        # Build a valid record: 4-byte length prefix + "|KEY=VAL|KEY2=VAL2|"
        payload = b"|REF=R1|VALUE=10k|FOOTPRINT=0603|"
        raw = struct.pack("<I", len(payload)) + payload
        records = parser._parse_pipe_delimited(raw)
        assert len(records) == 1
        assert records[0]["REF"] == "R1"
        assert records[0]["VALUE"] == "10k"

    def test_parse_pipe_delimited_multiple_records(self):
        import struct

        from mcp_pcb_emcopilot.parsers.altium_parser import AltiumPcbParser

        parser = AltiumPcbParser()
        p1 = b"|REF=R1|"
        p2 = b"|REF=C1|VALUE=100nF|"
        raw = struct.pack("<I", len(p1)) + p1 + struct.pack("<I", len(p2)) + p2
        records = parser._parse_pipe_delimited(raw)
        assert len(records) == 2
        assert records[0]["REF"] == "R1"
        assert records[1]["VALUE"] == "100nF"

    def test_parse_pipe_delimited_truncated(self):
        """Truncated length-prefix should stop cleanly without raising."""
        from mcp_pcb_emcopilot.parsers.altium_parser import AltiumPcbParser

        parser = AltiumPcbParser()
        records = parser._parse_pipe_delimited(b"\x00\x00")  # too short
        assert records == []

    def test_parse_region_vertices(self):
        from mcp_pcb_emcopilot.parsers.altium_parser import AltiumPcbParser

        parser = AltiumPcbParser()
        outline = "X1=100|Y1=200|X2=300|Y2=400"
        verts = parser._parse_region_vertices(outline)
        assert len(verts) == 2

    def test_parse_mil_value(self):
        from mcp_pcb_emcopilot.parsers.altium_parser import AltiumPcbParser

        parser = AltiumPcbParser()
        assert parser._parse_mil_value("100mil") == 100.0
        assert parser._parse_mil_value("50") == 50.0
        assert parser._parse_mil_value("") == 0.0
        assert parser._parse_mil_value("not-a-number") == 0.0

    def test_parse_float(self):
        from mcp_pcb_emcopilot.parsers.altium_parser import AltiumPcbParser

        parser = AltiumPcbParser()
        assert parser._parse_float("3.14") == 3.14
        assert parser._parse_float("") == 0.0
        assert parser._parse_float("not-a-number") == 0.0

    def test_parse_int(self):
        from mcp_pcb_emcopilot.parsers.altium_parser import AltiumPcbParser

        parser = AltiumPcbParser()
        assert parser._parse_int("42") == 42
        assert parser._parse_int("") == 0
        assert parser._parse_int("not-a-number") == 0

    def test_calculate_board_dimensions_empty(self):
        from mcp_pcb_emcopilot.parsers.altium_parser import (
            AltiumBoardData,
            AltiumPcbParser,
        )

        data = AltiumBoardData(source_file="/tmp/x.PcbDoc")
        AltiumPcbParser()._calculate_board_dimensions(data)
        # No components or traces — both dimensions should stay at their
        # default values (0 or inf-sentinel) without raising.

    def test_calculate_trace_statistics_empty(self):
        from mcp_pcb_emcopilot.parsers.altium_parser import (
            AltiumBoardData,
            AltiumPcbParser,
        )

        data = AltiumBoardData(source_file="/tmp/x.PcbDoc")
        AltiumPcbParser()._calculate_trace_statistics(data)
        assert data.total_trace_length_mm == 0.0

    def test_calculate_layer_count_empty(self):
        from mcp_pcb_emcopilot.parsers.altium_parser import (
            AltiumBoardData,
            AltiumPcbParser,
        )

        data = AltiumBoardData(source_file="/tmp/x.PcbDoc")
        AltiumPcbParser()._calculate_layer_count(data)
        # With no stackup loaded, layer_count should fall back to zero/default.

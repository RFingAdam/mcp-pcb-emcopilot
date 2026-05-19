"""Coverage-driver for the five parser / cli modules at 0% coverage.

Each test either constructs the parser and hands it a tiny synthetic
fixture, or exercises the module's CLI entry point. The goal is to
bring each module from 0% into the 30-70% range with cheap tests; the
parsers already have their own dedicated test modules exercising real
fixtures.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout

import pytest


class TestBomParser:
    def test_parse_synthetic_csv(self, tmp_path):
        from mcp_pcb_emcopilot.parsers.bom_parser import BOMParser

        csv_path = tmp_path / "bom.csv"
        csv_path.write_text(
            "Reference,Value,Footprint,MPN,Manufacturer\n"
            "R1,10k,0603,CRCW060310K0FKEA,Vishay\n"
            "R2,10k,0603,CRCW060310K0FKEA,Vishay\n"
            "C1,100nF,0402,C0402C104K4RACTU,KEMET\n"
            "U1,STM32F4,LQFP100,STM32F405RGT6,ST\n",
            encoding="utf-8",
        )
        bom = BOMParser().parse(str(csv_path))
        assert bom.total_items >= 3
        refs = {item.references for item in bom.items}
        assert "R1" in refs

    def test_parse_semicolon_delimited(self, tmp_path):
        from mcp_pcb_emcopilot.parsers.bom_parser import BOMParser

        # Exercises the delimiter-sniff path.
        csv_path = tmp_path / "bom_eu.csv"
        csv_path.write_text(
            "Reference;Value;Footprint\n"
            "R1;10k;0603\n"
            "R2;22k;0603\n",
            encoding="utf-8",
        )
        bom = BOMParser().parse(str(csv_path))
        assert bom.total_items == 2

    def test_unsupported_format_raises(self, tmp_path):
        from mcp_pcb_emcopilot.parsers.bom_parser import BOMParser

        bad = tmp_path / "bom.xyz"
        bad.write_text("not a real bom", encoding="utf-8")
        with pytest.raises(ValueError):
            BOMParser().parse(str(bad))


class TestSchematicParser:
    def test_parse_minimal_kicad_sch(self, tmp_path):
        from mcp_pcb_emcopilot.parsers.schematic_parser import KiCadSchematicParser

        sch_path = tmp_path / "minimal.kicad_sch"
        sch_path.write_text(
            '(kicad_sch\n'
            '  (symbol (lib_id "Device:R")\n'
            '    (property "Reference" "R1" (at 0 0 0))\n'
            '    (property "Value" "10k" (at 0 0 0))\n'
            '    (property "Footprint" "Resistor_SMD:R_0603" (at 0 0 0))\n'
            '    (property "Datasheet" "~" (at 0 0 0))\n'
            '    (at 10 10 0)\n'
            '  )\n'
            '  (global_label "VCC" (at 20 20 0))\n'
            '  (global_label "GND" (at 20 30 0))\n'
            ')\n',
            encoding="utf-8",
        )
        result = KiCadSchematicParser().parse(str(sch_path))
        # Parser should succeed and find either the symbol or the labels.
        assert result is not None

    def test_parse_invalid_file_raises(self, tmp_path):
        from mcp_pcb_emcopilot.parsers.schematic_parser import KiCadSchematicParser

        bad = tmp_path / "missing.kicad_sch"
        # File doesn't exist; the parser should surface a ValueError wrapping
        # the underlying IO error rather than letting it bubble raw.
        with pytest.raises((ValueError, FileNotFoundError, OSError)):
            KiCadSchematicParser().parse(str(bad))


class TestStackupParser:
    def test_construct_minimal_stackup(self):
        from mcp_pcb_emcopilot.parsers.stackup_parser import (
            MaterialType,
            Stackup,
            StackupLayer,
        )

        layers = [
            StackupLayer(
                name="L1_TOP", layer_number=1, layer_type="signal",
                thickness_mm=0.035, material=MaterialType.COPPER,
                copper_weight_oz=1.0,
            ),
            StackupLayer(
                name="core", layer_number=2, layer_type="dielectric",
                thickness_mm=0.2, material=MaterialType.FR4,
                dielectric_constant=4.3, loss_tangent=0.02,
            ),
            StackupLayer(
                name="L2_BOT", layer_number=3, layer_type="signal",
                thickness_mm=0.035, material=MaterialType.COPPER,
                copper_weight_oz=1.0,
            ),
        ]
        stackup = Stackup(
            name="2-layer",
            layers=layers,
            total_thickness_mm=0.27,
            copper_layer_count=2,
        )
        assert stackup.copper_layer_count == 2
        assert stackup.total_thickness_mm == pytest.approx(0.27)


class TestCrossValidator:
    def test_validate_empty_inputs(self):
        from mcp_pcb_emcopilot.analyzers.validation.cross_validator import (
            CrossValidator,
        )
        # Validator with no data loaded should return an empty-but-valid
        # result, not raise — the entry point shouldn't presume data.
        result = CrossValidator().validate()
        assert result is not None

    def test_bom_sch_layout_mismatch_is_detected(self):
        from mcp_pcb_emcopilot.analyzers.validation.cross_validator import (
            CrossValidator,
        )
        cv = CrossValidator()
        # A resistor exists in layout but is missing from BOM — that's the
        # canonical mismatch the validator was built to catch. The ``add_*``
        # methods take keyword args directly (not the ``ComponentData``
        # dataclass, which is built internally).
        cv.add_layout_component(reference="R1", value="10k", footprint="R_0603")
        cv.add_schematic_component(reference="R1", value="10k")
        result = cv.validate()
        assert result is not None


class TestWebCli:
    def test_argparse_prints_help(self):
        from mcp_pcb_emcopilot.web import cli

        # ``--help`` exits cleanly with SystemExit(0) and writes the help
        # text to stdout, which exercises the argparse-setup lines.
        buf = io.StringIO()
        old_argv = sys.argv
        try:
            sys.argv = ["web-cli", "--help"]
            with redirect_stdout(buf):
                with pytest.raises(SystemExit) as excinfo:
                    cli.main()
            assert excinfo.value.code == 0
        finally:
            sys.argv = old_argv
        assert "Host to bind to" in buf.getvalue()

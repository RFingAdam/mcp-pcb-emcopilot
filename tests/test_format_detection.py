"""Tests for PCB file format auto-detection."""
import os
import tempfile

import pytest

from mcp_pcb_emcopilot.parsers import detect_format


class TestDetectFormat:
    """Test detect_format() with all supported extensions."""

    # --- KiCad ---

    def test_kicad_pcb(self):
        assert detect_format("board.kicad_pcb") == "kicad"

    def test_kicad_pcb_uppercase(self):
        assert detect_format("BOARD.KICAD_PCB") == "kicad"

    def test_kicad_pcb_path(self):
        assert detect_format("/some/path/to/my_design.kicad_pcb") == "kicad"

    # --- ODB++ ---

    def test_odb_tgz(self):
        assert detect_format("design.tgz") == "odb"

    def test_odb_tar_gz(self):
        assert detect_format("design.tar.gz") == "odb"

    def test_odb_zip(self):
        assert detect_format("design.zip") == "odb"

    # --- Gerber ---

    def test_gerber_gbr(self):
        assert detect_format("copper_top.gbr") == "gerber"

    def test_gerber_ger(self):
        assert detect_format("copper_top.ger") == "gerber"

    def test_gerber_gtl(self):
        assert detect_format("board.gtl") == "gerber"

    def test_gerber_gbl(self):
        assert detect_format("board.gbl") == "gerber"

    def test_gerber_gts(self):
        assert detect_format("board.gts") == "gerber"

    def test_gerber_gbs(self):
        assert detect_format("board.gbs") == "gerber"

    def test_gerber_gto(self):
        assert detect_format("board.gto") == "gerber"

    def test_gerber_gbo(self):
        assert detect_format("board.gbo") == "gerber"

    def test_gerber_gtp(self):
        assert detect_format("board.gtp") == "gerber"

    def test_gerber_gbp(self):
        assert detect_format("board.gbp") == "gerber"

    # --- Altium ---

    def test_altium_pcbdoc(self):
        assert detect_format("board.PcbDoc") == "altium"

    def test_altium_pcbdoc_lowercase(self):
        assert detect_format("board.pcbdoc") == "altium"

    # --- IPC-2581 ---

    def test_ipc2581_xml_with_content(self, tmp_path):
        """XML file with IPC-2581 content should be detected as ipc2581."""
        xml_file = tmp_path / "design.xml"
        xml_file.write_text('<?xml version="1.0"?><IPC-2581 revision="C"/>')
        assert detect_format(str(xml_file)) == "ipc2581"

    def test_ipc2581_xml_with_stackup_content(self, tmp_path):
        """XML file with Stackup content should be detected as ipc2581."""
        xml_file = tmp_path / "design.xml"
        xml_file.write_text('<?xml version="1.0"?><Root><Stackup/></Root>')
        assert detect_format(str(xml_file)) == "ipc2581"

    def test_ipc2581_xml_without_content(self):
        """XML file that doesn't exist falls through to default ipc2581."""
        assert detect_format("nonexistent.xml") == "ipc2581"

    def test_ipc2581_cvg(self):
        assert detect_format("design.cvg") == "ipc2581"

    # --- STEP ---

    def test_step_lowercase(self):
        assert detect_format("enclosure.step") == "step"

    def test_step_stp(self):
        assert detect_format("enclosure.stp") == "step"

    # --- BOM ---

    def test_bom_csv(self):
        assert detect_format("bom.csv") == "bom"

    # --- Schematic ---

    def test_schematic_kicad_sch(self):
        assert detect_format("sheet1.kicad_sch") == "schematic"

    # --- Schematic PDF ---

    def test_schematic_pdf(self):
        assert detect_format("schematic.pdf") == "schematic_pdf"

    # --- Unknown ---

    def test_unknown_txt(self):
        assert detect_format("readme.txt") == "unknown"

    def test_unknown_jpg(self):
        assert detect_format("photo.jpg") == "unknown"

    def test_unknown_no_extension(self):
        assert detect_format("myfile") == "unknown"

    def test_unknown_empty_string(self):
        assert detect_format("") == "unknown"

    def test_unknown_random_extension(self):
        assert detect_format("design.xyz123") == "unknown"

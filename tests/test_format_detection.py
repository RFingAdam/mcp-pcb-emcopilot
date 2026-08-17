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


# ---------------------------------------------------------------------------
# Altium Gerber-job detection
#
# An Altium export uses per-layer extensions rather than a uniform `.gbr`, so
# `.G1`-`.G8` are the inner copper layers and `.TX1`-`.TX9` the per-span drill
# files. These were all reported as "unknown", which made 8 of 10 copper layers
# and every drill file unloadable.
# ---------------------------------------------------------------------------

class TestAltiumGerberExtensions:
    @pytest.mark.parametrize("name", [
        "board.G1", "board.G2", "board.G4", "board.G8",
        "board.g1", "board.G12",
    ])
    def test_inner_copper_layers_are_gerber(self, name):
        assert detect_format(name) == "gerber"

    @pytest.mark.parametrize("name", ["board.GKO", "board.GM", "board.GM5", "board.GM13"])
    def test_outline_and_mechanical_layers_are_gerber(self, name):
        assert detect_format(name) == "gerber"

    def test_outer_copper_still_detected(self):
        assert detect_format("board.GTL") == "gerber"
        assert detect_format("board.GBL") == "gerber"


class TestDrillDetection:
    @pytest.mark.parametrize("name", [
        "job.drl", "job.xln", "job.exc",
        "job-Plated.TX1", "job-Plated.TX9", "job.DR1",
    ])
    def test_drill_extensions_are_excellon(self, name):
        assert detect_format(name) == "excellon"

    def test_ascii_drill_txt_is_detected_by_content(self, tmp_path):
        """Altium names the through-hole drill export `<job>-Plated.TXT`.

        `.txt` is shared with Allegro exports and fabrication status reports, so
        content is the only reliable discriminator.
        """
        p = tmp_path / "job-Plated.TXT"
        p.write_text("M48\n;FILE_FORMAT=2:5\nINCH,LZ\nT01C0.004\n%\nT01\nX0100000Y0100000\nM30\n")
        assert detect_format(str(p)) == "excellon"

    def test_a_status_report_sharing_the_txt_extension_is_not_a_drill_file(self, tmp_path):
        p = tmp_path / "Status Report.Txt"
        p.write_text("Fabrication Status Report\nLayers: 10\nAll checks passed\n")
        assert detect_format(str(p)) == "unknown"

    def test_allegro_txt_detection_is_unchanged(self, tmp_path):
        """Allegro is checked before the drill sniff, so it must still win."""
        p = tmp_path / "export.txt"
        p.write_text("$HEADER\nsome allegro content\n$NETS\n")
        assert detect_format(str(p)) == "allegro"


class TestJobDetection:
    def test_a_directory_is_a_job(self, tmp_path):
        (tmp_path / "board.GTL").write_text("%FSLAX25Y25*%\nM02*\n")
        assert detect_format(str(tmp_path)) == "gerber_job"

    def test_a_directory_without_a_suffix_is_still_a_job(self, tmp_path):
        d = tmp_path / "no_suffix_dir"
        d.mkdir()
        assert detect_format(str(d)) == "gerber_job"

    def test_zip_of_gerbers_is_a_job_not_odb(self, tmp_path):
        """`.zip` is claimed by ODB++, but Gerber jobs ship zipped too.

        Routing one into the ODB++ parser fails confusingly, so archive members
        are sniffed.
        """
        import zipfile
        z = tmp_path / "job.zip"
        with zipfile.ZipFile(z, "w") as archive:
            archive.writestr("board.GTL", "%FSLAX25Y25*%\nM02*\n")
            archive.writestr("board.G1", "%FSLAX25Y25*%\nM02*\n")
            archive.writestr("board.GBL", "%FSLAX25Y25*%\nM02*\n")
            archive.writestr("NC Drill/job.TX1", "M48\n%\nM30\n")
        assert detect_format(str(z)) == "gerber_job"

    def test_zip_of_odb_structure_is_still_odb(self, tmp_path):
        import zipfile
        z = tmp_path / "design.zip"
        with zipfile.ZipFile(z, "w") as archive:
            archive.writestr("myjob/matrix/matrix", "layer info")
            archive.writestr("myjob/steps/pcb/layers/top/features", "data")
        assert detect_format(str(z)) == "odb"

    def test_nonexistent_zip_keeps_the_historical_answer(self):
        """test_odb_zip asserts this; an unreadable archive cannot be sniffed."""
        assert detect_format("design.zip") == "odb"

    def test_empty_string_is_not_a_directory(self):
        """Path("") normalises to Path("."), which *is* a directory.

        os.path.isdir("") is False, which is why detection uses it.
        """
        assert detect_format("") == "unknown"

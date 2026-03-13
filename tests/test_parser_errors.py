"""Tests for parser error handling.

Validates that the parsers raise structured ParseError for:
- File not found
- Empty file
- Wrong format / corrupt data
- File too large (simulated)
"""
import os
import tempfile

import pytest

from mcp_pcb_emcopilot.errors import ParseError
from mcp_pcb_emcopilot.parsers import _MAX_FILE_SIZE, _validate_file, parse_pcb_file


class TestFileNotFound:
    def test_nonexistent_file(self):
        with pytest.raises(ParseError) as exc_info:
            parse_pcb_file("/tmp/nonexistent_board_12345.kicad_pcb")
        e = exc_info.value
        assert e.code == "FILE_NOT_FOUND"
        assert "not found" in e.message.lower()
        assert e.context["file"] == "/tmp/nonexistent_board_12345.kicad_pcb"

    def test_nonexistent_odb(self):
        with pytest.raises(ParseError) as exc_info:
            parse_pcb_file("/tmp/nonexistent_design.tgz")
        assert exc_info.value.code == "FILE_NOT_FOUND"

    def test_nonexistent_step(self):
        with pytest.raises(ParseError) as exc_info:
            parse_pcb_file("/tmp/nonexistent_model.step")
        assert exc_info.value.code == "FILE_NOT_FOUND"


class TestEmptyFile:
    def test_empty_kicad(self):
        with tempfile.NamedTemporaryFile(suffix=".kicad_pcb", delete=False) as f:
            path = f.name
        try:
            with pytest.raises(ParseError) as exc_info:
                parse_pcb_file(path)
            e = exc_info.value
            assert e.code == "EMPTY_FILE"
            assert "empty" in e.message.lower()
        finally:
            os.unlink(path)

    def test_empty_gerber(self):
        with tempfile.NamedTemporaryFile(suffix=".gbr", delete=False) as f:
            path = f.name
        try:
            with pytest.raises(ParseError) as exc_info:
                parse_pcb_file(path)
            assert exc_info.value.code == "EMPTY_FILE"
        finally:
            os.unlink(path)

    def test_empty_step(self):
        with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as f:
            path = f.name
        try:
            with pytest.raises(ParseError) as exc_info:
                parse_pcb_file(path)
            assert exc_info.value.code == "EMPTY_FILE"
        finally:
            os.unlink(path)


class TestWrongFormat:
    """Test that passing a .txt file as a .kicad_pcb raises ParseError."""

    def test_text_as_kicad(self):
        with tempfile.NamedTemporaryFile(suffix=".kicad_pcb", delete=False, mode="w") as f:
            f.write("This is not a valid KiCad PCB file, just plain text.")
            path = f.name
        try:
            with pytest.raises(ParseError) as exc_info:
                parse_pcb_file(path)
            e = exc_info.value
            assert e.code == "PARSE_FAILED"
            assert "kicad" in e.message.lower() or "parse" in e.message.lower()
        finally:
            os.unlink(path)

    def test_text_as_gerber(self):
        with tempfile.NamedTemporaryFile(suffix=".gbr", delete=False, mode="w") as f:
            f.write("Not a gerber file.")
            path = f.name
        try:
            # Gerber parser may succeed with empty result or fail;
            # either ParseError or success is acceptable.
            # We just make sure no unstructured exception leaks.
            try:
                result = parse_pcb_file(path)
                # If it succeeds, that's fine -- some parsers are lenient
            except ParseError:
                pass  # Expected
        finally:
            os.unlink(path)


class TestCorruptBinary:
    """Test corrupt binary data."""

    def test_random_bytes_as_kicad(self):
        with tempfile.NamedTemporaryFile(suffix=".kicad_pcb", delete=False, mode="wb") as f:
            f.write(os.urandom(256))
            path = f.name
        try:
            with pytest.raises(ParseError) as exc_info:
                parse_pcb_file(path)
            e = exc_info.value
            assert e.code == "PARSE_FAILED"
            assert e.context["file"] == path
            assert e.context["format"] == "kicad"
        finally:
            os.unlink(path)

    def test_random_bytes_as_step(self):
        """STEP parser is lenient (text-based best-effort), so corrupt data may
        produce an empty result rather than an error. We verify no unstructured
        exception leaks."""
        with tempfile.NamedTemporaryFile(suffix=".step", delete=False, mode="wb") as f:
            f.write(os.urandom(256))
            path = f.name
        try:
            try:
                result = parse_pcb_file(path)
                # STEP parser returns empty result for unrecognised content -- acceptable
                assert result.source_format == "step"
            except ParseError:
                pass  # Also acceptable
        finally:
            os.unlink(path)

    def test_random_bytes_as_ipc2581(self):
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="wb") as f:
            f.write(os.urandom(256))
            path = f.name
        try:
            with pytest.raises(ParseError) as exc_info:
                parse_pcb_file(path)
            e = exc_info.value
            assert e.code == "PARSE_FAILED"
        finally:
            os.unlink(path)


class TestFileTooLarge:
    """Test file size validation (without creating a huge file)."""

    def test_validate_file_size_check(self, monkeypatch):
        """Use monkeypatch to simulate a file that exceeds the size limit."""
        with tempfile.NamedTemporaryFile(suffix=".kicad_pcb", delete=False, mode="w") as f:
            f.write("(kicad_pcb)")
            path = f.name
        try:
            # Monkeypatch Path.stat to report a huge file size
            import pathlib
            original_stat = pathlib.Path.stat

            class FakeStat:
                st_size = 600 * 1024 * 1024  # 600 MB

            def fake_stat(self, *a, **kw):
                return FakeStat()

            monkeypatch.setattr(pathlib.Path, "stat", fake_stat)

            with pytest.raises(ParseError) as exc_info:
                parse_pcb_file(path)
            e = exc_info.value
            assert e.code == "FILE_TOO_LARGE"
            assert "500MB" in e.message
            assert e.context["size_bytes"] == 600 * 1024 * 1024
        finally:
            # Restore stat before cleanup
            monkeypatch.undo()
            os.unlink(path)


class TestUnsupportedFormat:
    """Test unsupported file extension."""

    def test_txt_file(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
            f.write("Hello world")
            path = f.name
        try:
            with pytest.raises(ParseError) as exc_info:
                parse_pcb_file(path)
            e = exc_info.value
            assert e.code == "UNSUPPORTED_FORMAT"
            assert "unknown" in e.message.lower() or "unsupported" in e.message.lower()
        finally:
            os.unlink(path)


class TestParseErrorStructure:
    """Verify ParseError to_dict structure."""

    def test_to_dict_structure(self):
        with pytest.raises(ParseError) as exc_info:
            parse_pcb_file("/tmp/does_not_exist_ever.kicad_pcb")
        d = exc_info.value.to_dict()
        assert d["error_type"] == "ParseError"
        assert d["code"] == "FILE_NOT_FOUND"
        assert isinstance(d["message"], str)
        assert isinstance(d["context"], dict)

    def test_parse_error_is_exception(self):
        e = ParseError("TEST", "test message", {"key": "val"})
        assert isinstance(e, Exception)
        assert str(e) == "[TEST] test message"

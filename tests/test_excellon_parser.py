"""ASCII Excellon (NC drill) parser tests.

All fixtures here are synthetic and inline. The decisive property under test is
zero suppression, because getting it wrong still parses cleanly and yields
coordinates that are wrong by a factor of 100 — a silent failure rather than a
loud one.
"""
from __future__ import annotations

import pytest

from mcp_pcb_emcopilot.parsers.excellon_parser import (
    ExcellonBinaryError,
    ExcellonParser,
    decode_coordinate,
    is_binary_excellon,
    parse_excellon,
)

# A minimal Altium-shaped export: 2:5 inch, leading zeros kept.
JOB_LZ = """M48
;Layer_Color=9474304
;FILE_FORMAT=2:5
INCH,LZ
;TYPE=PLATED
T01F00S00C0.00394
T02F00S00C0.00800
%
T01
X0003173Y0004218
X0124400Y0059055
T02
X0100000Y0100000
M30
"""


def _parse(text: str, name: str = "job.txt"):
    return ExcellonParser().parse_from_bytes(text.encode("utf-8"), name)


# ---------------------------------------------------------------------------
# decode_coordinate — the load-bearing function
# ---------------------------------------------------------------------------

class TestZeroSuppression:
    """LZ and TZ are opposites, and both are opposite to Gerber's convention."""

    def test_lz_full_width_token(self):
        # "0003173" at 2:5 -> 00.03173 in -> 0.80594 mm
        assert decode_coordinate("0003173", 2, 5, "keep_leading", "inch") == pytest.approx(0.80594, abs=1e-5)

    def test_lz_short_token_pads_right(self):
        """The case that catches a Gerber-style decoder.

        "01244" with trailing zeros suppressed is 01.24400 in = 31.5976 mm.
        Left-padding it (the Gerber rule) gives 0.01244 in = 0.316 mm — a 100x
        error that still looks like a plausible coordinate.
        """
        assert decode_coordinate("01244", 2, 5, "keep_leading", "inch") == pytest.approx(31.5976, abs=1e-4)

    def test_tz_short_token_pads_left(self):
        # TZ: leading zeros suppressed, so "1244" -> 00.01244 in
        assert decode_coordinate("1244", 2, 5, "keep_trailing", "inch") == pytest.approx(0.316, abs=1e-3)

    def test_lz_and_tz_disagree_on_the_same_token(self):
        """If these ever match, one of the two rules has been broken."""
        lz = decode_coordinate("01244", 2, 5, "keep_leading", "inch")
        tz = decode_coordinate("01244", 2, 5, "keep_trailing", "inch")
        assert lz != tz
        assert lz > tz

    def test_explicit_decimal_point_overrides_padding(self):
        assert decode_coordinate("1.5", 2, 5, "keep_leading", "inch") == pytest.approx(38.1)

    def test_metric_units_are_not_scaled(self):
        # 3:3 metric, "012500" -> 012.500 mm
        assert decode_coordinate("012500", 3, 3, "keep_leading", "mm") == pytest.approx(12.5)

    def test_negative_coordinates(self):
        assert decode_coordinate("-0100000", 2, 5, "keep_leading", "inch") == pytest.approx(-25.4)

    def test_overlong_token_keeps_the_declared_decimal_width(self):
        # 3 integer digits supplied against a 2:5 declaration.
        assert decode_coordinate("10024400", 2, 5, "keep_leading", "inch") == pytest.approx(100.244 * 25.4, abs=1e-2)

    def test_empty_token_is_zero(self):
        assert decode_coordinate("", 2, 5, "keep_leading", "inch") == 0.0


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

class TestHeader:
    def test_file_format_comment_is_mined_not_skipped(self):
        """The format spec lives in a comment, unlike Gerber's %FS command.

        A parser that skips comments loses it and silently falls back to a
        default width.
        """
        d = _parse(JOB_LZ)
        assert (d.integer_digits, d.decimal_digits) == (2, 5)
        assert d.format_source == "file_format_comment"

    def test_units_and_zero_mode(self):
        d = _parse(JOB_LZ)
        assert d.units == "inch"
        assert d.zeros_mode == "keep_leading"

    def test_metric_tz_header(self):
        d = _parse("M48\nMETRIC,TZ\nT01C0.100\n%\nT01\nX012500Y012500\nM30\n")
        assert d.units == "mm"
        assert d.zeros_mode == "keep_trailing"

    def test_plated_flag_from_type_comment(self):
        assert _parse(JOB_LZ).plated is True

    def test_tool_diameters_convert_from_file_units(self):
        d = _parse(JOB_LZ)
        assert d.tools[1].diameter_mm == pytest.approx(0.00394 * 25.4, abs=1e-6)
        assert d.tools[2].diameter_mm == pytest.approx(0.2032, abs=1e-6)

    def test_tool_diameter_in_mil(self):
        assert _parse(JOB_LZ).tools[2].diameter_mil == pytest.approx(8.0, abs=0.01)

    def test_tool_modifier_order_is_not_assumed(self):
        """Altium writes T02F00S00C0.00800; other tools reorder the modifiers."""
        d = _parse("M48\nINCH,LZ\nT07C0.00500F20S100\n%\nT07\nX0100000Y0100000\nM30\n")
        assert d.tools[7].diameter_mm == pytest.approx(0.127, abs=1e-6)

    def test_missing_format_declaration_is_warned_about(self):
        d = _parse("M48\n%\nT01\nX0100000Y0100000\nM30\n")
        assert any("format was not declared" in w for w in d.warnings)


# ---------------------------------------------------------------------------
# Body
# ---------------------------------------------------------------------------

class TestBody:
    def test_hits_are_counted_per_tool(self):
        d = _parse(JOB_LZ)
        assert d.hit_count == 3
        assert d.tools[1].hit_count == 2
        assert d.tools[2].hit_count == 1

    def test_hits_carry_their_tool_diameter(self):
        d = _parse(JOB_LZ)
        assert d.hits[0].diameter_mm == pytest.approx(0.100076, abs=1e-5)
        assert d.hits[2].diameter_mm == pytest.approx(0.2032, abs=1e-6)

    def test_counts_by_diameter_groups_correctly(self):
        counts = _parse(JOB_LZ).counts_by_diameter()
        assert counts[round(0.2032, 4)] == 1
        assert sum(counts.values()) == 3

    def test_sticky_coordinates_reuse_the_unchanged_axis(self):
        """Excellon omits an axis that does not change between hits.

        Without persistence the omitted axis defaults to 0 and the hole lands on
        the board edge — wrong, and wrong in a way that still looks like data.
        """
        d = _parse(
            "M48\n;FILE_FORMAT=2:5\nINCH,LZ\nT01C0.00400\n%\nT01\n"
            "X0100000Y0200000\nX0300000\nY0400000\nM30\n"
        )
        assert d.hit_count == 3
        assert d.hits[1].y_mm == pytest.approx(d.hits[0].y_mm)
        assert d.hits[1].x_mm != pytest.approx(d.hits[0].x_mm)
        assert d.hits[2].x_mm == pytest.approx(d.hits[1].x_mm)

    def test_leading_single_axis_hit_is_reported_not_guessed(self):
        d = _parse("M48\n;FILE_FORMAT=2:5\nINCH,LZ\nT01C0.004\n%\nT01\nX0100000\nM30\n")
        assert d.hit_count == 0
        assert any("only one axis" in w for w in d.warnings)

    def test_g85_slot_records_both_endpoints(self):
        d = _parse(
            "M48\n;FILE_FORMAT=2:5\nINCH,LZ\nT01C0.00400\n%\nT01\n"
            "X0100000Y0100000G85X0200000Y0100000\nM30\n"
        )
        assert d.hit_count == 1
        assert d.hits[0].is_slot
        assert d.hits[0].slot_end_x_mm == pytest.approx(50.8)

    def test_hit_without_a_selected_tool_is_warned_not_silently_dropped(self):
        """A dropped hit changes every downstream count, so it must be loud."""
        d = _parse("M48\n;FILE_FORMAT=2:5\nINCH,LZ\n%\nX0100000Y0100000\nM30\n")
        assert d.hit_count == 0
        assert any("no tool selected" in w for w in d.warnings)
        assert any("reconcile" in w for w in d.warnings)

    def test_m30_ends_parsing(self):
        d = _parse(JOB_LZ + "T01\nX0999999Y0999999\n")
        assert d.hit_count == 3

    def test_extent_reflects_all_hits(self):
        d = _parse(JOB_LZ)
        x0, y0, x1, y1 = d.extent_mm
        assert x0 < x1 and y0 < y1
        assert x1 == pytest.approx(31.5976, abs=1e-3)

    def test_extent_of_an_empty_file_is_zeros_not_infinities(self):
        d = _parse("M48\nINCH,LZ\n%\nM30\n")
        assert d.extent_mm == (0.0, 0.0, 0.0, 0.0)
        assert any("no drill hits" in w for w in d.warnings)

    def test_g91_incremental_mode_is_flagged(self):
        d = _parse("M48\n;FILE_FORMAT=2:5\nINCH,LZ\nT01C0.004\n%\nG91\nT01\nX0100000Y0100000\nM30\n")
        assert any("G91" in w for w in d.warnings)


# ---------------------------------------------------------------------------
# Binary EIA rejection
# ---------------------------------------------------------------------------

class TestBinaryRejection:
    """Altium ships a binary EIA twin next to every ASCII drill file.

    Decoding the binary one as text produces plausible-looking coordinates, so
    it must be rejected before parsing rather than discovered afterwards.
    """

    def test_nul_bytes_are_binary(self):
        assert is_binary_excellon(b"T\x00T\x00#v\x00\x00 2 s k") is True

    def test_high_byte_density_is_binary(self):
        assert is_binary_excellon(bytes(range(200, 256)) * 4) is True

    def test_empty_is_treated_as_binary(self):
        assert is_binary_excellon(b"") is True

    def test_ascii_without_m48_is_rejected(self):
        """A text file that is not a drill file must not be parsed as one.

        A fabrication status report can share the .txt extension with an ASCII
        drill export, so the discriminator is content, not the filename.
        """
        assert is_binary_excellon(b"Status Report\nLayers: 10\nAll OK\n" * 20) is True

    def test_valid_ascii_is_not_binary(self):
        assert is_binary_excellon(JOB_LZ.encode()) is False

    def test_parse_raises_on_binary_input(self, tmp_path):
        p = tmp_path / "job.DRL"
        p.write_bytes(b"\x00\x01\x02T\xd4T\xd4#v\x00\x00 2 s k \xff\xfe" * 40)
        with pytest.raises(ExcellonBinaryError) as exc:
            parse_excellon(p)
        assert "binary EIA" in str(exc.value)
        assert "ASCII" in str(exc.value)

    def test_binary_input_yields_no_coordinates(self, tmp_path):
        """The point of rejecting: never emit mojibake coordinates."""
        p = tmp_path / "job.DR1"
        p.write_bytes(b"\x00\x7f\xd4v" * 300)
        with pytest.raises(ExcellonBinaryError):
            parse_excellon(p)


# ---------------------------------------------------------------------------
# Round trip through a file
# ---------------------------------------------------------------------------

def test_parse_from_disk(tmp_path):
    p = tmp_path / "job.TXT"
    p.write_text(JOB_LZ, encoding="utf-8")
    d = parse_excellon(p)
    assert d.source_file == "job.TXT"
    assert d.hit_count == 3
    assert not [w for w in d.warnings if "format was not declared" in w]

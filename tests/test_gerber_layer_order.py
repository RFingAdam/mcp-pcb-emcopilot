"""Gerber G04 comments carry layer metadata and must not be discarded.

The parser previously returned unconditionally on any `G04` line. Comments are
not inert in an Altium export: `G04 Layer_Physical_Order=N*` is the **only**
in-file statement of where a layer sits in the stack, and X2 attributes are
emitted in the comment form `G04 #@! TF....*` rather than as `%TF` commands —
which `_parse_extended_command` never sees, since it only fires on lines
beginning with `%`.

Consequence before this: stackup order was unrecoverable from the Gerber files
themselves, and `.G1` and `.G8` were indistinguishable — both merely "some inner
layer".
"""
from __future__ import annotations

import pytest

from mcp_pcb_emcopilot.parsers.gerber_parser import GerberParser, scan_gerber_header


# An Altium copper-layer header, verbatim in shape.
def _header(order: int, guid: str = "00000000-0000-4000-8000-000000000001") -> str:
    return (
        "G04*\n"
        "G04 #@! TF.GenerationSoftware,Synthetic,TestFixture, ()*\n"
        "G04*\n"
        f"G04 Layer_Physical_Order={order}*\n"
        "G04 Layer_Color=255*\n"
        "G04 Board_Origin=100000000|200000000*\n"
        "%FSLAX25Y25*%\n"
        "%MOIN*%\n"
        "G70*\n"
        f"G04 #@! TF.SameCoordinates,{guid}*\n"
        "G04 #@! TF.FilePolarity,Positive*\n"
        "G01*\n"
        "G75*\n"
        "%ADD11C,0.00500*%\n"
        "D11*\n"
        "X0Y0D02*\n"
        "X100000Y0D01*\n"
        "M02*\n"
    )


def _write(tmp_path, name: str, text: str):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


class TestG04Metadata:
    def test_physical_order_is_captured(self, tmp_path):
        """The single sharpest before/after in the ingest work."""
        p = _write(tmp_path, "board.G4", _header(5))
        data = GerberParser().parse(str(p))
        assert data.physical_order == 5

    def test_board_origin_is_captured(self, tmp_path):
        p = _write(tmp_path, "board.GTL", _header(1))
        data = GerberParser().parse(str(p))
        assert data.board_origin == (100000000, 200000000)

    def test_layer_colour_lands_in_custom_attributes(self, tmp_path):
        p = _write(tmp_path, "board.GTL", _header(1))
        data = GerberParser().parse(str(p))
        assert data.attributes.custom.get("Layer_Color") == "255"

    def test_comments_are_retained(self, tmp_path):
        p = _write(tmp_path, "board.GTL", _header(1))
        data = GerberParser().parse(str(p))
        assert any("Layer_Physical_Order" in c for c in data.comments)

    def test_x2_attributes_in_comment_form_are_parsed(self, tmp_path):
        """Altium writes `G04 #@! TF...*`, not `%TF...%`.

        `_parse_extended_command` only fires on lines starting with `%`, so
        these bypassed the attribute parser entirely.
        """
        p = _write(tmp_path, "board.GTL", _header(1))
        data = GerberParser().parse(str(p))
        assert data.attributes.file_polarity == "Positive"
        assert data.attributes.generation_software is not None

    def test_same_coordinates_id_is_captured(self, tmp_path):
        """Every layer of one export shares this id.

        A mismatch across files means they are not in the same coordinate frame,
        which is exactly the situation that silently misaligns drills.
        """
        p = _write(tmp_path, "board.GTL", _header(1, guid="ABC-123"))
        data = GerberParser().parse(str(p))
        assert data.coordinate_system_id == "ABC-123"

    def test_geometry_still_parses_with_comments_retained(self, tmp_path):
        """Regression guard: capturing comments must not disturb the parse."""
        p = _write(tmp_path, "board.GTL", _header(1))
        data = GerberParser().parse(str(p))
        assert data.traces
        assert data.integer_digits == 2
        assert data.decimal_digits == 5
        assert data.units == "inch"


class TestFilenameLayerNumber:
    """`.Gn` is the (n+1)th copper layer: the digit counts inner layers."""

    @pytest.mark.parametrize("ext,expected", [
        ("GTL", 1), ("G1", 2), ("G2", 3), ("G4", 5), ("G8", 9),
    ])
    def test_inner_layer_digit_becomes_an_ordinal(self, tmp_path, ext, expected):
        # No G04 order, so the filename convention is the only signal.
        p = _write(tmp_path, f"plain.{ext}", "%FSLAX25Y25*%\n%MOIN*%\nM02*\n")
        info = scan_gerber_header(p)
        assert info.layer_number == expected

    def test_g1_and_g8_are_distinguishable(self, tmp_path):
        """Both used to collapse to layer_number=None."""
        a = scan_gerber_header(_write(tmp_path, "a.G1", "%FSLAX25Y25*%\nM02*\n"))
        b = scan_gerber_header(_write(tmp_path, "b.G8", "%FSLAX25Y25*%\nM02*\n"))
        assert a.layer_number != b.layer_number

    def test_sides_are_still_inferred(self, tmp_path):
        top = scan_gerber_header(_write(tmp_path, "a.GTL", "%FSLAX25Y25*%\nM02*\n"))
        inner = scan_gerber_header(_write(tmp_path, "b.G3", "%FSLAX25Y25*%\nM02*\n"))
        bot = scan_gerber_header(_write(tmp_path, "c.GBL", "%FSLAX25Y25*%\nM02*\n"))
        assert (top.layer_side, inner.layer_side, bot.layer_side) == ("top", "inner", "bottom")

    def test_profile_and_mechanical_layers_are_outline_type(self, tmp_path):
        """`.gm` (no digit) is the board profile; `.gm<n>` a mechanical layer.

        Matching only `.gm1` missed both.
        """
        for name in ("p.GM", "p.GM5", "p.GKO"):
            info = scan_gerber_header(_write(tmp_path, name, "%FSLAX25Y25*%\nM02*\n"))
            assert info.layer_type == "outline", name


class TestHeaderScan:
    """A cheap header-only read, so ordering a job does not require full parses."""

    def test_order_is_read_without_parsing_geometry(self, tmp_path):
        p = _write(tmp_path, "board.G4", _header(5))
        info = scan_gerber_header(p)
        assert info.physical_order == 5
        assert info.is_gerber is True
        assert info.integer_digits == 2
        assert info.units == "inch"

    def test_explicit_order_wins_over_the_filename_convention(self, tmp_path):
        """A deliberately inconsistent file: .G1 implies 2, the comment says 7.

        The in-file statement is authoritative; the filename is a fallback.
        """
        p = _write(tmp_path, "odd.G1", _header(7))
        info = scan_gerber_header(p)
        assert info.physical_order == 7

    def test_scan_stops_before_the_aperture_table(self, tmp_path):
        """A short line budget must still reach the order comment.

        Altium writes it within the first handful of lines, well before the
        apertures — which is the point of scanning rather than parsing.
        """
        p = _write(tmp_path, "board.G4", _header(5))
        assert scan_gerber_header(p, max_lines=8).physical_order == 5

    def test_non_gerber_file_is_reported_not_raised(self, tmp_path):
        p = _write(tmp_path, "notes.txt", "just notes\nnothing gerber\n")
        info = scan_gerber_header(p)
        assert info.is_gerber is False
        assert info.physical_order is None

    def test_missing_file_does_not_raise(self, tmp_path):
        info = scan_gerber_header(tmp_path / "absent.gtl")
        assert info.is_gerber is False

    def test_scan_agrees_with_a_full_parse(self, tmp_path):
        p = _write(tmp_path, "board.G4", _header(5))
        info = scan_gerber_header(p)
        full = GerberParser().parse(str(p))
        assert info.physical_order == full.physical_order
        assert info.units == full.units
        assert info.coordinate_system_id == full.coordinate_system_id

    def test_a_ten_layer_stack_orders_completely(self, tmp_path):
        """The end goal: a permutation of 1..10 with no gaps or duplicates."""
        names = ["s.GTL"] + [f"s.G{n}" for n in range(1, 9)] + ["s.GBL"]
        for i, name in enumerate(names, start=1):
            _write(tmp_path, name, _header(i))
        orders = sorted(
            scan_gerber_header(tmp_path / n).physical_order for n in names
        )
        assert orders == list(range(1, 11))

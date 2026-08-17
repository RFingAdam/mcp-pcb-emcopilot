"""Altium sidecar parsers: .LDP, .EXTREP, .DRR, .RUL.

All fixtures are synthetic and inline, modelled on the structure of a real
10-layer HDI export but with invented names and counts.

The .LDP is the one that matters most. It states which copper layers each drill
file spans, and without it every via defaults to a through-hole — which on a
build-up board makes ground stitching look far healthier than it is, because a
microvia between two adjacent layers gets credited with connecting the whole
stack.
"""
from __future__ import annotations

import pytest

from mcp_pcb_emcopilot.parsers.altium_sidecar_parser import (
    parse_drill_report,
    parse_extension_report,
    parse_layer_pair_map,
    parse_rule_file,
    rules_to_design_rules,
)

# --- synthetic 10-layer fixtures -------------------------------------------

LDP = """Layer Pairs Export File for PCB: synth.PcbDoc
LayersSetName=Top_Bot_Plated_Thru_Holes|DrillFile=synth-plated.txt|DrillLayers=gtl,g1,g2,g3,g4,g5,g6,g7,g8,gbl
LayersSetName=L1 Top_L2 GND_Blind_Vias|DrillFile=synth-plated.tx1|DrillLayers=gtl,g1
LayersSetName=L2 GND_L3 PWR1_Buried_Vias|DrillFile=synth-plated.tx2|DrillLayers=g1,g2
LayersSetName=L9 GND_L10 Bottom_Blind_Vias|DrillFile=synth-plated.tx9|DrillLayers=g8,gbl
"""

EXTREP = """\
------------------------------------------------------------------------------
Gerber File Extension Report For: synth.GBR   1/1/2000  0:00:00
------------------------------------------------------------------------------

------------------------------------------------------------------------------
Layer Extension     Layer Description
------------------------------------------------------------------------------
.GTO                Silkscreen Top
.GTS                Solder Mask Top
.GTL                L1 Top
.G1                 L2 GND
.G2                 L3 PWR1
.G4                 L5 GND
.G8                 L9 GND
.GBL                L10 Bottom
.GM                 Profile
.GKO                Keep-Out Layer
------------------------------------------------------------------------------
"""

# Two per-span blocks plus the file-level grand total that follows them. The
# grand total reuses the "Totals" keyword, which is the trap this exercises.
DRR = """\
------------------------------------------------------------------------------
NCDrill File Report For: synth.PcbDoc   1/1/2000  0:00:00
------------------------------------------------------------------------------

Layer Pair : L1 Top to L10 Bottom
ASCII Plated RoundHoles File : synth-Plated.TXT
EIA File   : synth.DRL

Tool       Hole Size          Hole Tolerance     Hole Type    Hole Count   Plated   Tool Travel
------------------------------------------------------------------------------
T2      8mil (0.203mm)                            Round          7          PTH     1.00inch (25.40mm)
------------------------------------------------------------------------------
Totals                                                           7
Layer Pair : L9 GND to L10 Bottom
ASCII Plated RoundHoles File : synth-Plated.TX9
EIA File   : synth.DR9

Tool       Hole Size          Hole Tolerance     Hole Type    Hole Count   Plated   Tool Travel
------------------------------------------------------------------------------
T1      4mil (0.1mm)                              Round          29         PTH     2.00inch (50.80mm)
------------------------------------------------------------------------------
Totals                                                           29
------------------------------------------------------------------------------
Totals                                                           36

Total Processing Time (hh:mm:ss) : 00:00:01
"""

RUL = """DRC Rules Export File for PCB: synth.PcbDoc
RuleKind=Clearance|RuleName=Clearance_GND_NAMED|Scope=Board|Minimum=5.00
RuleKind=Clearance|RuleName=Clearance|Scope=Board|Minimum=4.00
RuleKind=Width|RuleName=Width|Scope=Board|Minimum=3.00
RuleKind=Width|RuleName=Width_MEMBUS|Scope=Board|Minimum=3.20
RuleKind=ShortCircuit|RuleName=ShortCircuit|Scope=Board|Allowed=0
RuleKind=SolderMaskExpansion|RuleName=SolderMaskExpansion|Scope=Board|Minimum=2.00
"""


def _w(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ===========================================================================
# .LDP
# ===========================================================================

class TestLayerPairMap:
    def test_all_spans_are_found(self, tmp_path):
        m = parse_layer_pair_map(_w(tmp_path, "synth.LDP", LDP))
        assert len(m.spans) == 4
        assert not m.warnings

    def test_header_path_line_is_not_a_span(self, tmp_path):
        m = parse_layer_pair_map(_w(tmp_path, "synth.LDP", LDP))
        assert all(s.drill_file for s in m.spans)

    def test_through_span_lists_every_layer(self, tmp_path):
        """A through span names all 10 copper layers, not just its endpoints."""
        m = parse_layer_pair_map(_w(tmp_path, "synth.LDP", LDP))
        through = [s for s in m.spans if s.span_kind == "through"]
        assert len(through) == 1
        assert len(through[0].layer_tokens) == 10
        assert through[0].layer_tokens[0] == "gtl"
        assert through[0].layer_tokens[-1] == "gbl"

    def test_adjacent_pairs_list_exactly_two_layers(self, tmp_path):
        m = parse_layer_pair_map(_w(tmp_path, "synth.LDP", LDP))
        for s in m.spans:
            if s.span_kind != "through":
                assert len(s.layer_tokens) == 2, s.set_name

    def test_span_kind_from_set_name(self, tmp_path):
        m = parse_layer_pair_map(_w(tmp_path, "synth.LDP", LDP))
        kinds = {s.drill_basename: s.span_kind for s in m.spans}
        assert kinds["synth-plated.txt"] == "through"
        assert kinds["synth-plated.tx1"] == "blind"
        assert kinds["synth-plated.tx2"] == "buried"

    def test_ordinals_recovered_from_set_name(self, tmp_path):
        m = parse_layer_pair_map(_w(tmp_path, "synth.LDP", LDP))
        by = {s.drill_basename: s.name_ordinals for s in m.spans}
        assert by["synth-plated.tx1"] == (1, 2)
        assert by["synth-plated.tx9"] == (9, 10)

    def test_drill_file_lookup_is_case_insensitive(self, tmp_path):
        """Altium lowercases the name inside the .LDP; disk keeps its own case.

        An exact match therefore fails, and on a case-sensitive filesystem the
        span would silently go unresolved.
        """
        m = parse_layer_pair_map(_w(tmp_path, "synth.LDP", LDP))
        assert m.find_by_drill_file("synth-Plated.TX9") is not None
        assert m.find_by_drill_file("/some/dir/SYNTH-PLATED.TX1") is not None
        assert m.find_by_drill_file("nope.tx5") is None

    def test_empty_map_is_warned_about(self, tmp_path):
        m = parse_layer_pair_map(_w(tmp_path, "empty.LDP", "just a header line\n"))
        assert not m.spans
        assert any("default to a through-hole" in w for w in m.warnings)

    def test_entry_without_drill_layers_is_flagged(self, tmp_path):
        text = "hdr\nLayersSetName=X_Blind_Vias|DrillFile=a.txt|DrillLayers=\n"
        m = parse_layer_pair_map(_w(tmp_path, "x.LDP", text))
        assert any("no DrillLayers" in w for w in m.warnings)


# ===========================================================================
# .EXTREP
# ===========================================================================

class TestExtensionReport:
    def test_extensions_map_to_layer_names(self, tmp_path):
        r = parse_extension_report(_w(tmp_path, "s.EXTREP", EXTREP))
        assert r.name_for(".GTL") == "L1 Top"
        assert r.name_for(".g4") == "L5 GND"
        assert r.name_for(".GBL") == "L10 Bottom"

    def test_names_containing_spaces_survive(self, tmp_path):
        """The separator must require 2+ spaces; names contain single ones."""
        r = parse_extension_report(_w(tmp_path, "s.EXTREP", EXTREP))
        assert r.name_for(".GKO") == "Keep-Out Layer"
        assert r.name_for(".GTS") == "Solder Mask Top"

    def test_ordinal_comes_from_the_leading_layer_number(self, tmp_path):
        r = parse_extension_report(_w(tmp_path, "s.EXTREP", EXTREP))
        assert r.ordinal_for(".GTL") == 1
        assert r.ordinal_for(".G1") == 2
        assert r.ordinal_for(".G4") == 5
        assert r.ordinal_for(".GBL") == 10

    def test_inner_layer_numbering_is_offset_by_one(self, tmp_path):
        """.Gn is the (n+1)th copper layer — .G4 is L5, not L4."""
        r = parse_extension_report(_w(tmp_path, "s.EXTREP", EXTREP))
        for ext, expected in ((".G1", 2), (".G2", 3), (".G4", 5), (".G8", 9)):
            assert r.ordinal_for(ext) == expected, ext

    def test_non_copper_layers_have_no_ordinal(self, tmp_path):
        r = parse_extension_report(_w(tmp_path, "s.EXTREP", EXTREP))
        assert r.ordinal_for(".GM") is None
        assert r.ordinal_for(".GKO") is None
        assert r.ordinal_for(".GTO") is None

    def test_separator_rules_are_not_rows(self, tmp_path):
        r = parse_extension_report(_w(tmp_path, "s.EXTREP", EXTREP))
        assert all(k.startswith(".") for k in r.by_extension)
        assert len(r.by_extension) == 10

    def test_unknown_extension_returns_none(self, tmp_path):
        r = parse_extension_report(_w(tmp_path, "s.EXTREP", EXTREP))
        assert r.name_for(".zzz") is None
        assert r.ordinal_for(".zzz") is None


# ===========================================================================
# .DRR
# ===========================================================================

class TestDrillReport:
    def test_blocks_are_separated_per_span(self, tmp_path):
        r = parse_drill_report(_w(tmp_path, "s.DRR", DRR))
        assert len(r.blocks) == 2

    def test_each_block_keeps_its_own_total(self, tmp_path):
        """Regression: the file-level grand total reuses the "Totals" keyword.

        Letting it through overwrote the final block's count with the whole-file
        figure — silently inflating one span by the sum of all of them.
        """
        r = parse_drill_report(_w(tmp_path, "s.DRR", DRR))
        assert [b.total_holes for b in r.blocks] == [7, 29]

    def test_grand_total_is_captured_separately(self, tmp_path):
        r = parse_drill_report(_w(tmp_path, "s.DRR", DRR))
        assert r.reported_grand_total == 36
        assert r.total_holes == 36
        assert r.grand_total_agrees is True

    def test_disagreeing_grand_total_is_reported(self, tmp_path):
        bad = DRR.replace("Totals                                                           36",
                          "Totals                                                           99")
        r = parse_drill_report(_w(tmp_path, "bad.DRR", bad))
        assert r.grand_total_agrees is False
        assert any("grand total" in w for w in r.warnings)

    def test_tool_diameters_in_both_units(self, tmp_path):
        r = parse_drill_report(_w(tmp_path, "s.DRR", DRR))
        t = r.blocks[0].tools[0]
        assert t.tool_code == 2
        assert t.diameter_mil == pytest.approx(8.0)
        assert t.diameter_mm == pytest.approx(0.203)

    def test_hole_count_is_not_confused_with_the_diameter(self, tmp_path):
        """Both are bare integers on the row, so position alone is ambiguous."""
        r = parse_drill_report(_w(tmp_path, "s.DRR", DRR))
        assert r.blocks[0].tools[0].hole_count == 7
        assert r.blocks[1].tools[0].hole_count == 29

    def test_hole_type_and_plating(self, tmp_path):
        r = parse_drill_report(_w(tmp_path, "s.DRR", DRR))
        t = r.blocks[0].tools[0]
        assert t.hole_type == "round"
        assert t.plated is True

    def test_npth_is_recognised(self, tmp_path):
        text = DRR.replace("PTH     1.00inch", "NPTH    1.00inch")
        r = parse_drill_report(_w(tmp_path, "n.DRR", text))
        assert r.blocks[0].tools[0].plated is False

    def test_tool_travel_in_mm(self, tmp_path):
        r = parse_drill_report(_w(tmp_path, "s.DRR", DRR))
        assert r.blocks[0].tools[0].tool_travel_mm == pytest.approx(25.40)

    def test_ascii_and_eia_filenames_are_both_recorded(self, tmp_path):
        r = parse_drill_report(_w(tmp_path, "s.DRR", DRR))
        assert r.blocks[0].ascii_file == "synth-Plated.TXT"
        assert r.blocks[0].eia_file == "synth.DRL"

    def test_block_lookup_by_ascii_filename_is_case_insensitive(self, tmp_path):
        r = parse_drill_report(_w(tmp_path, "s.DRR", DRR))
        assert r.find_block("synth-plated.tx9") is not None
        assert r.find_block("missing.txt") is None

    def test_layer_pair_text_is_kept(self, tmp_path):
        r = parse_drill_report(_w(tmp_path, "s.DRR", DRR))
        assert r.blocks[1].layer_pair == "L9 GND to L10 Bottom"

    def test_empty_report_is_warned_about(self, tmp_path):
        r = parse_drill_report(_w(tmp_path, "e.DRR", "nothing here\n"))
        assert not r.blocks
        assert any("no drill-report blocks" in w for w in r.warnings)


# ===========================================================================
# .RUL
# ===========================================================================

class TestRuleFile:
    def test_all_rules_are_parsed(self, tmp_path):
        rs = parse_rule_file(_w(tmp_path, "s.RUL", RUL))
        assert len(rs.rules) == 6

    def test_named_rules_keep_their_names(self, tmp_path):
        """Named rules are design intent, not just numeric constraints."""
        rs = parse_rule_file(_w(tmp_path, "s.RUL", RUL))
        names = {r.name for r in rs.rules}
        assert "Clearance_GND_NAMED" in names
        assert "Width_MEMBUS" in names

    def test_units_are_inferred_as_mils_and_recorded(self, tmp_path):
        """The file declares no units, so the choice must be explicit."""
        rs = parse_rule_file(_w(tmp_path, "s.RUL", RUL))
        assert rs.units == "mil"
        assert any("inferred MILS" in w for w in rs.warnings)

    def test_millimetre_rules_are_inferred_the_other_way(self, tmp_path):
        mm = "hdr\nRuleKind=Width|RuleName=W|Scope=Board|Minimum=0.100\n"
        rs = parse_rule_file(_w(tmp_path, "mm.RUL", mm))
        assert rs.units == "mm"
        assert any("inferred MILLIMETRES" in w for w in rs.warnings)

    def test_short_circuit_allowed_zero_is_false_not_truthy(self, tmp_path):
        """"0" is a non-empty string, so a naive bool() would read it as True."""
        rs = parse_rule_file(_w(tmp_path, "s.RUL", RUL))
        sc = rs.by_kind("ShortCircuit")[0]
        assert sc.allowed is False

    def test_conversion_to_design_rule_dicts(self, tmp_path):
        rs = parse_rule_file(_w(tmp_path, "s.RUL", RUL))
        dicts, scalars = rules_to_design_rules(rs)
        assert len(dicts) == 6
        by_name = {d["name"]: d for d in dicts}
        gnd = by_name["Clearance_GND_NAMED"]
        assert gnd["value_mm"] == pytest.approx(5.0 * 0.0254)
        assert gnd["value_mil"] == pytest.approx(5.0)
        assert gnd["source"] == "altium_rul"
        assert gnd["type"] == "Clearance"

    def test_scalars_take_the_tightest_constraint(self, tmp_path):
        rs = parse_rule_file(_w(tmp_path, "s.RUL", RUL))
        _, scalars = rules_to_design_rules(rs)
        # 3.00 mil, not the 3.20 mil variant and not the 4.00 mil clearance.
        assert scalars["min_trace_width_mm"] == pytest.approx(3.0 * 0.0254)
        assert scalars["min_clearance_mm"] == pytest.approx(4.0 * 0.0254)

    def test_extracted_rules_are_much_tighter_than_library_defaults(self, tmp_path):
        """The point of parsing this file at all.

        PCBDesignData defaults min_trace_width_mm and min_clearance_mm to 0.2 mm
        and reports them as if extracted. A real HDI constraint is several times
        tighter, so the default is not a conservative stand-in — it is wrong in
        the permissive direction.
        """
        rs = parse_rule_file(_w(tmp_path, "s.RUL", RUL))
        _, scalars = rules_to_design_rules(rs)
        assert scalars["min_trace_width_mm"] < 0.2 / 2

    def test_non_length_rules_carry_no_length_value(self, tmp_path):
        rs = parse_rule_file(_w(tmp_path, "s.RUL", RUL))
        dicts, _ = rules_to_design_rules(rs)
        sc = [d for d in dicts if d["type"] == "ShortCircuit"][0]
        assert sc["value_mm"] is None
        assert sc["allowed"] is False

    def test_empty_file_is_warned_about(self, tmp_path):
        rs = parse_rule_file(_w(tmp_path, "e.RUL", "header only\n"))
        assert not rs.rules
        assert any("no rules were recognised" in w for w in rs.warnings)


# ===========================================================================
# Joint use — the reason these live in one module
# ===========================================================================

def test_ldp_spans_resolve_against_drr_blocks(tmp_path):
    """The .LDP names drill files; the .DRR states their counts independently.

    Reconciling the two is the cross-check that makes drill parsing trustworthy,
    and it only works if both parsers agree on filename matching.
    """
    ldp = parse_layer_pair_map(_w(tmp_path, "s.LDP", LDP))
    drr = parse_drill_report(_w(tmp_path, "s.DRR", DRR))

    resolved = {
        s.drill_basename: drr.find_block(s.drill_file)
        for s in ldp.spans
    }
    assert resolved["synth-plated.txt"] is not None
    assert resolved["synth-plated.txt"].total_holes == 7
    assert resolved["synth-plated.tx9"].total_holes == 29
    # tx1/tx2 have no block in this fixture — an unmatched span must be
    # detectable, not silently treated as zero holes.
    assert resolved["synth-plated.tx1"] is None


def test_extrep_ordinals_resolve_ldp_layer_tokens(tmp_path):
    """.LDP gives bare tokens (g4); .EXTREP turns them into ordinals (5)."""
    ldp = parse_layer_pair_map(_w(tmp_path, "s.LDP", LDP))
    er = parse_extension_report(_w(tmp_path, "s.EXTREP", EXTREP))

    span = ldp.find_by_drill_file("synth-plated.tx9")
    ordinals = [er.ordinal_for("." + t) for t in span.layer_tokens]
    assert ordinals == [9, 10]

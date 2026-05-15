"""Tests for review_playbook module — server-side helpers for the meticulous
multi-pass review workflow."""

from __future__ import annotations

import pytest

from mcp_pcb_emcopilot import market_packs
from mcp_pcb_emcopilot.review_playbook import (
    CORE_QUESTIONS,
    PASS_CHECKLIST,
    SERVER_INSTRUCTIONS,
    StartProfessionalReviewResult,
    build_input_manifest,
    build_interview_pack,
    classify_file,
    compute_analyzer_shortlist,
    compute_standards_shortlist,
    find_input_gaps,
    load_playbook_markdown,
    start_professional_review,
)

# --- SERVER_INSTRUCTIONS -----------------------------------------------------

def test_server_instructions_mentions_entry_tool():
    assert "pcb_start_professional_review" in SERVER_INSTRUCTIONS


def test_server_instructions_references_playbook_doc():
    # The instructions must point Claude at the canonical playbook doc.
    assert "CLAUDE_REVIEW_PLAYBOOK" in SERVER_INSTRUCTIONS
    # And mention the 8-pass framing (P0..P8 or "passes")
    assert "P0" in SERVER_INSTRUCTIONS or "passes" in SERVER_INSTRUCTIONS.lower()


def test_server_instructions_is_concise():
    # Instructions should be readable, not a wall of text
    assert 200 < len(SERVER_INSTRUCTIONS) < 2000


# --- File classification -----------------------------------------------------

@pytest.mark.parametrize("path,expected_kind,expected_format", [
    ("board.kicad_pcb", "layout", "kicad"),
    ("sheet.kicad_sch", "schematic", "kicad"),
    ("design.PcbDoc", "layout", "altium"),
    ("design.SchDoc", "schematic", "altium"),
    ("layout.brd", "layout", "allegro"),
    ("top_copper.gbr", "layout", "gerber"),
    ("schematic.pdf", "schematic", "pdf"),
    ("bom.csv", "bom", "csv"),
    ("parts.xlsx", "bom", "excel"),
    ("model.step", "step", "step"),
    ("model.stp", "step", "step"),
    ("stackup.json", "stackup", "json"),
    ("design.xml", "layout", "ipc2581"),
    ("notes.net", "schematic", "netlist"),
    ("design.tar.gz", "layout", "odb"),
])
def test_classify_file_basic_extensions(path, expected_kind, expected_format):
    out = classify_file(path)
    assert out["kind"] == expected_kind, f"{path}: expected kind {expected_kind}, got {out}"
    assert out["format"] == expected_format, f"{path}: expected format {expected_format}, got {out}"


def test_classify_file_filename_hint_overrides_extension_for_bom():
    # A .json file named with 'bom' becomes a BOM
    out = classify_file("custom_bom.json")
    assert out["kind"] == "bom"


def test_classify_file_stackup_hint():
    # A .json file named with 'stackup' stays a stackup (already default for .json)
    out = classify_file("project_stackup.json")
    assert out["kind"] == "stackup"


def test_classify_file_datasheet_hint():
    out = classify_file("DS_buck_converter.pdf")
    assert out["kind"] == "datasheet"


def test_classify_file_unknown_extension():
    out = classify_file("random.foo")
    assert out["kind"] == "other"
    assert out["format"] == "foo"


# --- Input manifest + gaps ---------------------------------------------------

def test_build_input_manifest_accepts_strings_and_dicts():
    manifest = build_input_manifest([
        "board.kicad_pcb",
        {"path": "sheet.kicad_sch", "kind": "schematic", "format": "kicad"},
    ])
    assert len(manifest) == 2
    assert manifest[0]["kind"] == "layout"
    assert manifest[1]["kind"] == "schematic"


def test_find_input_gaps_layout_missing_is_critical():
    manifest = build_input_manifest(["bom.csv", "schematic.pdf"])
    gaps = find_input_gaps(manifest)
    # Layout is the only strictly critical kind
    assert "layout" in gaps
    # Recommended kinds prefixed
    assert any(g.startswith("recommended:") for g in gaps)


def test_find_input_gaps_full_package_has_no_critical_gaps():
    manifest = build_input_manifest([
        "board.kicad_pcb",
        "schematic.pdf",
        "stackup.json",
        "bom.csv",
        "model.step",
    ])
    gaps = find_input_gaps(manifest)
    # No strictly critical (no bare 'layout' / 'schematic' / 'bom' etc. without prefix)
    assert "layout" not in gaps
    # Every recommended kind is present too
    assert not any(g.startswith("recommended:") for g in gaps)


# --- Interview pack ----------------------------------------------------------

def test_build_interview_pack_core_only_when_market_unknown():
    pack = build_interview_pack([], "unknown")
    core_ids = {q["id"] for q in CORE_QUESTIONS}
    pack_ids = {q["id"] for q in pack}
    # Core questions are always present
    assert core_ids.issubset(pack_ids)
    # No market-specific ids when market unknown
    for market in market_packs.KNOWN_MARKETS:
        for q in market_packs.get_pack(market):
            assert q["id"] not in pack_ids


def test_build_interview_pack_automotive_adds_market_questions():
    pack = build_interview_pack([], "automotive")
    ids = {q["id"] for q in pack}
    for q in market_packs.get_pack("automotive"):
        assert q["id"] in ids


def test_build_interview_pack_drops_conditional_on_metadata():
    pack = build_interview_pack([], "wireless")
    for q in pack:
        assert "conditional_on" not in q


def test_build_interview_pack_dedupes_across_markets():
    # operating_environment is in CORE; merging markets must not duplicate it
    pack = build_interview_pack([], "wireless", extra_markets=["medical"])
    ids = [q["id"] for q in pack]
    assert len(ids) == len(set(ids))


# --- Standards / analyzer shortlists ----------------------------------------

def test_compute_standards_shortlist_automotive():
    standards = compute_standards_shortlist("automotive")
    assert "CISPR_25" in standards
    assert "ISO_11452_4" in standards


def test_compute_standards_shortlist_multi_market_union():
    s = compute_standards_shortlist("medical", extra_markets=["wireless"])
    assert "IEC_60601_1_2_ED_4_1" in s
    assert "FCC_47_CFR_15C" in s
    # Deduped
    assert len(s) == len(set(s))


def test_compute_analyzer_shortlist_automotive_includes_emc_analyzers():
    analyzers = compute_analyzer_shortlist("automotive")
    assert "automotive_emc" in analyzers
    assert "return_paths" in analyzers


def test_compute_standards_shortlist_unknown_market_returns_empty():
    assert compute_standards_shortlist("unknown") == []
    assert compute_analyzer_shortlist("unknown") == []


# --- Pass checklist constant -------------------------------------------------

def test_pass_checklist_has_eight_passes():
    assert list(PASS_CHECKLIST) == ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]


# --- Playbook markdown loader ------------------------------------------------

def test_load_playbook_markdown_returns_nonempty_string():
    text = load_playbook_markdown()
    assert isinstance(text, str)
    assert len(text) > 100
    # Either the real playbook or the stub mentions the 8-pass workflow
    assert "P0" in text or "intake" in text.lower()


def test_load_playbook_markdown_contains_pass_headers_when_real_doc_available():
    text = load_playbook_markdown()
    # If the real doc is on disk, it should contain all eight pass section names
    if "## Pass 0" in text:
        for n in range(9):
            assert f"## Pass {n}" in text, f"Missing Pass {n} header"


# --- start_professional_review ----------------------------------------------

def test_start_professional_review_returns_full_payload():
    result = start_professional_review(
        session_id="test-session-001",
        input_files=["board.kicad_pcb", "sheet.kicad_sch", "bom.csv", "stackup.json", "model.step"],
        declared_market="automotive",
        product_description="12 V dashboard accessory",
    )
    assert isinstance(result, StartProfessionalReviewResult)
    assert result.session_id == "test-session-001"
    assert len(result.input_manifest) == 5
    assert result.declared_market == "automotive"
    # Automotive-specific question is in the pack
    qids = {q["id"] for q in result.interview_pack}
    assert "vehicle_class" in qids
    assert "iso7637_pulses" in qids
    # Automotive standards in the shortlist
    assert "CISPR_25" in result.standards_shortlist
    # No critical gaps because layout is present
    assert "layout" not in result.gaps
    # Pass checklist matches the canonical list
    assert result.pass_checklist == list(PASS_CHECKLIST)
    # to_dict is JSON-friendly
    d = result.to_dict()
    assert d["session_id"] == "test-session-001"
    assert "playbook_markdown" in d


def test_start_professional_review_unknown_market_warns_in_notes():
    result = start_professional_review(
        session_id="test-session-002",
        input_files=["board.kicad_pcb"],
        declared_market="unknown",
    )
    assert any("market" in n.lower() for n in result.notes)
    assert result.standards_shortlist == []


def test_start_professional_review_normalises_unknown_token():
    result = start_professional_review(
        session_id="test-session-003",
        input_files=["board.kicad_pcb"],
        declared_market="aerospace_quantum",  # not a known market
    )
    assert result.declared_market == "unknown"
    # The notes call out the unknown-market substitution
    assert any("aerospace_quantum" in n for n in result.notes)


def test_start_professional_review_layout_missing_yields_critical_gap():
    result = start_professional_review(
        session_id="test-session-004",
        input_files=["schematic.pdf", "bom.csv"],
        declared_market="wireless",
    )
    assert "layout" in result.gaps

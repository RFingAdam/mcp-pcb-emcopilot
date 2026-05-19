"""Claude-driven meticulous review workflow — server-side helpers.

This module is the Python side of the *binding* multi-pass review workflow
documented in ``docs/CLAUDE_REVIEW_PLAYBOOK.md``. It exposes:

- ``SERVER_INSTRUCTIONS`` — short string surfaced on every MCP ``initialize``
  handshake. Tells Claude to call ``pcb_start_professional_review`` first.
- ``build_input_manifest(file_list)`` — classify a list of file paths by kind
  (layout / schematic / stackup / bom / step / datasheet / other).
- ``build_interview_pack(manifest, declared_market)`` — merge the core review
  questions with the per-market pack from ``market_packs.py``.
- ``compute_standards_shortlist(declared_market, manifest, hints)`` — union of
  market-driven standards.
- ``start_professional_review(...)`` — main helper invoked by the new MCP tool
  ``pcb_start_professional_review`` to build the response payload.

This module is intentionally pure — no I/O, no globals beyond the imported
data tables — so it is trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import market_packs

# =============================================================================
# Server-level instructions surfaced via Server(instructions=...)
# =============================================================================

SERVER_INSTRUCTIONS = (
    "You are conducting a meticulous senior-consulting-engineer PCB/EMC design "
    "review. Before invoking ANY analyzer or generator tool, call "
    "`pcb_start_professional_review` with the user's input files. It returns "
    "the binding 8-pass playbook (P0 intake, P1 scoping interview, P2 parse + "
    "cross-reference, P3 domain analysis, P4 standards verification, P5 "
    "simulation escalation, P6 cross-domain correlation, P7 reporting, P8 "
    "self-critique). The full playbook is also at docs/CLAUDE_REVIEW_PLAYBOOK.md. "
    "Execute every pass in order; do not skip P1 (interview) or P8 "
    "(self-critique). When a finding has severity >= HIGH or confidence < 0.7, "
    "escalate to openEMS / NEC2 via the sibling MCPs before reporting. Refuse "
    "to produce a final report unless P0-P6 are logged in session state. "
    "Always log assumptions and human-review flags."
)


# =============================================================================
# File kind classification
# =============================================================================

# Extensions that map directly to a kind. Multi-extension formats handled below.
_EXT_TO_KIND: dict[str, tuple[str, str]] = {
    # (kind, format)
    ".kicad_pcb": ("layout", "kicad"),
    ".kicad_sch": ("schematic", "kicad"),
    ".pcbdoc": ("layout", "altium"),
    ".schdoc": ("schematic", "altium"),
    ".schlib": ("schematic", "altium"),
    ".pcblib": ("layout", "altium"),
    ".brd": ("layout", "allegro"),
    ".dsn": ("layout", "specctra"),
    ".gbr": ("layout", "gerber"),
    ".ger": ("layout", "gerber"),
    ".gbl": ("layout", "gerber"),
    ".gtl": ("layout", "gerber"),
    ".drl": ("layout", "drill"),
    ".tgz": ("layout", "odb"),
    ".tar.gz": ("layout", "odb"),
    ".odb": ("layout", "odb"),
    ".step": ("step", "step"),
    ".stp": ("step", "step"),
    ".pdf": ("schematic", "pdf"),
    ".net": ("schematic", "netlist"),
    ".csv": ("bom", "csv"),
    ".xlsx": ("bom", "excel"),
    ".xls": ("bom", "excel"),
    ".json": ("stackup", "json"),  # heuristic — may be stackup OR data file
    ".yaml": ("stackup", "yaml"),
    ".yml": ("stackup", "yaml"),
    ".xml": ("layout", "ipc2581"),  # IPC-2581 is the common .xml in this domain
}


def classify_file(path: str) -> dict[str, str]:
    """Classify a single file path by extension into kind + format.

    Returns ``{"path": <path>, "kind": <kind>, "format": <format>}`` where
    kind is one of: ``layout``, ``schematic``, ``stackup``, ``bom``, ``step``,
    ``datasheet``, ``other``.
    """
    p = Path(path)
    name = p.name.lower()
    # Try compound extensions first (e.g., .tar.gz)
    for compound in (".tar.gz",):
        if name.endswith(compound):
            kind, fmt = _EXT_TO_KIND[compound]
            return {"path": str(path), "kind": kind, "format": fmt}
    ext = p.suffix.lower()
    if ext in _EXT_TO_KIND:
        kind, fmt = _EXT_TO_KIND[ext]
        # Filename hint refinement: stackup-named files in any format
        stem = p.stem.lower()
        if kind == "layout" and ext in {".json", ".yaml", ".yml"}:
            kind = "stackup"
        if kind in {"layout", "stackup"} and "stackup" in stem:
            kind = "stackup"
        if "bom" in stem and kind != "bom":
            kind = "bom"
        if "datasheet" in stem or "ds_" in stem:
            kind = "datasheet"
            fmt = ext.lstrip(".") or "unknown"
        return {"path": str(path), "kind": kind, "format": fmt}
    return {"path": str(path), "kind": "other", "format": ext.lstrip(".") or "unknown"}


def build_input_manifest(file_list: list[str | dict[str, Any]]) -> list[dict[str, str]]:
    """Classify a list of files (strings or pre-classified dicts).

    Pre-classified dicts (``{"path":..., "kind":..., "format":...}``) pass
    through unchanged. Strings get auto-classified.
    """
    manifest: list[dict[str, str]] = []
    for entry in file_list:
        if isinstance(entry, dict):
            path = str(entry.get("path", ""))
            kind = str(entry.get("kind", "")) or classify_file(path)["kind"]
            fmt = str(entry.get("format", "")) or classify_file(path)["format"]
            manifest.append({"path": path, "kind": kind, "format": fmt})
        else:
            manifest.append(classify_file(str(entry)))
    return manifest


_CRITICAL_KINDS: tuple[str, ...] = ("layout",)
_RECOMMENDED_KINDS: tuple[str, ...] = ("schematic", "stackup", "bom", "step")


def find_input_gaps(manifest: list[dict[str, str]]) -> list[str]:
    """Return a list of missing critical/recommended input kinds."""
    present = {m["kind"] for m in manifest}
    gaps = [k for k in _CRITICAL_KINDS if k not in present]
    # Recommended kinds are listed too but as 'recommended:'-prefixed
    for k in _RECOMMENDED_KINDS:
        if k not in present:
            gaps.append(f"recommended:{k}")
    return gaps


# =============================================================================
# Interview pack construction
# =============================================================================

# Core questions are kept here as the single canonical list. The legacy
# ``review_context.REVIEW_QUESTIONS`` will be refactored in Phase 4 to read
# from this same source — for now we duplicate the IDs intentionally so the
# playbook module is self-contained.

CORE_QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "ddr_standard",
        "category": "interfaces",
        "text": "What DDR standard is used in this design?",
        "type": "choice",
        "choices": ["DDR3", "DDR4", "DDR5", "LPDDR4", "LPDDR5"],
        "default": None,
        "why": "DDR standard determines timing margins, impedance targets, and length-matching rules.",
        "conditional_on": "has_ddr",
    },
    {
        "id": "emmc_speed_mode",
        "category": "interfaces",
        "text": "What eMMC speed mode is the design targeting?",
        "type": "choice",
        "choices": ["HS200", "HS400", "legacy"],
        "default": "HS200",
        "why": "eMMC speed mode sets data-strobe requirements and trace length constraints.",
        "conditional_on": "has_emmc",
    },
    {
        "id": "usb_version",
        "category": "interfaces",
        "text": "What USB version is used?",
        "type": "choice",
        "choices": ["USB2.0", "USB3.0", "USB3.1", "USB4"],
        "default": None,
        "why": "USB version determines impedance targets and routing rules.",
        "conditional_on": "has_usb",
    },
    {
        "id": "target_impedance_se",
        "category": "stackup",
        "text": "Single-ended impedance target (ohms)?",
        "type": "number",
        "default": 50,
        "why": "Needed to validate stackup and trace geometry.",
    },
    {
        "id": "target_impedance_diff",
        "category": "stackup",
        "text": "Differential impedance target (ohms)?",
        "type": "number",
        "default": 100,
        "why": "Needed for USB, PCIe, DDR strobe, and Ethernet pair validation.",
        "conditional_on": "has_diff_pairs",
    },
    {
        "id": "max_current_estimates",
        "category": "power",
        "text": "Power-rail current estimates (e.g. 'VCC_3V3: 2A, VDD_CORE: 1.5A')?",
        "type": "text",
        "default": "",
        "why": "Needed for trace-width validation and thermal analysis.",
        "conditional_on": "has_power",
    },
    {
        "id": "rf_operating_freq",
        "category": "rf",
        "text": "RF operating frequencies in MHz (comma-separated)?",
        "type": "text",
        "default": "",
        "why": "Determines wavelength-based keep-out zones, via spacing, filter targets.",
        "conditional_on": "has_rf",
    },
    {
        "id": "battery_capacity_mah",
        "category": "power",
        "text": "Battery capacity in mAh (if battery-powered)?",
        "type": "number",
        "default": None,
        "why": "Needed for power-budget and battery-life estimation.",
        "conditional_on": "has_power",
    },
    {
        "id": "operating_environment",
        "category": "interfaces",
        "text": "Target operating environment?",
        "type": "choice",
        "choices": ["consumer", "industrial", "automotive", "medical", "military"],
        "default": "consumer",
        "why": "Determines temperature range, EMC standard selection, derating rules.",
    },
    {
        "id": "fab_stackup_spec",
        "category": "stackup",
        "text": "Do you have the fab stackup specification?",
        "type": "choice",
        "choices": ["yes_upload", "no_use_extracted"],
        "default": "no_use_extracted",
        "why": "Fab stackup gives accurate dielectric thicknesses for impedance calculations.",
    },
]


def build_interview_pack(
    manifest: list[dict[str, str]],
    declared_market: str,
    extra_markets: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build the merged interview pack for the session.

    Always includes ``CORE_QUESTIONS``. Appends per-market questions from
    ``market_packs.QUESTION_BANK`` for the declared market plus any extras
    (deduped by question id). Removes ``conditional_on`` keys before returning
    because those are evaluated server-side by ``review_context``.
    """
    markets: list[str] = []
    if declared_market and declared_market != "unknown":
        markets.append(declared_market)
    for m in extra_markets or []:
        if m and m not in markets:
            markets.append(m)
    merged_market_qs = market_packs.merge_packs(markets)
    # Core first, then market packs
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for q in CORE_QUESTIONS + merged_market_qs:
        if q["id"] in seen:
            continue
        seen.add(q["id"])
        # Drop server-only metadata from the wire copy
        copy = {k: v for k, v in q.items() if k != "conditional_on"}
        out.append(copy)
    return out


# =============================================================================
# Standards + analyzer shortlists
# =============================================================================

def compute_standards_shortlist(
    declared_market: str,
    manifest: list[dict[str, str]] | None = None,
    extra_markets: list[str] | None = None,
) -> list[str]:
    """Return the standards Claude should verify against in Pass 4.

    Union of the declared market's standards plus any inferred markets. Today
    inference is minimal; Phase 4 wires in net classification.
    """
    markets: list[str] = []
    if declared_market and declared_market != "unknown":
        markets.append(declared_market)
    for m in extra_markets or []:
        if m and m not in markets:
            markets.append(m)
    return market_packs.merge_standards(markets)


def compute_analyzer_shortlist(
    declared_market: str,
    manifest: list[dict[str, str]] | None = None,
    extra_markets: list[str] | None = None,
) -> list[str]:
    """Return the analyzers Claude should run in Pass 3 for this market set."""
    markets: list[str] = []
    if declared_market and declared_market != "unknown":
        markets.append(declared_market)
    for m in extra_markets or []:
        if m and m not in markets:
            markets.append(m)
    return market_packs.merge_analyzers(markets)


# =============================================================================
# Pass checklist (the binding pass IDs)
# =============================================================================

PASS_CHECKLIST: tuple[str, ...] = (
    "P0",  # intake
    "P1",  # scoping interview
    "P2",  # parse + cross-reference
    "P3",  # domain analysis
    "P4",  # standards verification
    "P5",  # simulation escalation
    "P6",  # cross-domain correlation
    "P7",  # reporting
    "P8",  # self-critique
)


# =============================================================================
# Loading the human-readable playbook text
# =============================================================================

_PLAYBOOK_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "CLAUDE_REVIEW_PLAYBOOK.md"


def load_playbook_markdown() -> str:
    """Read CLAUDE_REVIEW_PLAYBOOK.md from disk, or return a fallback stub.

    The playbook lives in docs/ alongside the source tree. If the package is
    installed without docs (uncommon), we return a short stub pointing at the
    online location plus the 8 pass headers.
    """
    try:
        return _PLAYBOOK_PATH.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return (
            "# Claude Review Playbook (stub)\n\n"
            "The full playbook ships in `docs/CLAUDE_REVIEW_PLAYBOOK.md`.\n"
            "Required passes: P0 intake, P1 scoping interview, P2 parse + "
            "cross-reference, P3 domain analysis, P4 standards verification, "
            "P5 simulation escalation, P6 cross-domain correlation, P7 "
            "reporting, P8 self-critique. Execute every pass in order.\n"
        )


# =============================================================================
# Entry-point response builder
# =============================================================================

@dataclass
class StartProfessionalReviewResult:
    """Structured payload returned by ``pcb_start_professional_review``.

    Convertible to a plain dict via ``to_dict()`` for JSON serialisation.
    """

    session_id: str
    playbook_markdown: str
    input_manifest: list[dict[str, str]]
    gaps: list[str]
    interview_pack: list[dict[str, Any]]
    standards_shortlist: list[str]
    analyzer_shortlist: list[str]
    pass_checklist: list[str]
    declared_market: str
    product_description: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "playbook_markdown": self.playbook_markdown,
            "input_manifest": self.input_manifest,
            "gaps": self.gaps,
            "interview_pack": self.interview_pack,
            "standards_shortlist": self.standards_shortlist,
            "analyzer_shortlist": self.analyzer_shortlist,
            "pass_checklist": list(self.pass_checklist),
            "declared_market": self.declared_market,
            "product_description": self.product_description,
            "notes": list(self.notes),
        }


def start_professional_review(
    session_id: str,
    input_files: list[str | dict[str, Any]],
    declared_market: str = "unknown",
    product_description: str | None = None,
    extra_markets: list[str] | None = None,
) -> StartProfessionalReviewResult:
    """Build the response payload for the ``pcb_start_professional_review`` tool.

    No I/O beyond reading the playbook file. The caller is responsible for
    creating/registering the session before calling this.
    """
    declared = (declared_market or "unknown").strip().lower()
    if declared not in {"unknown", *market_packs.KNOWN_MARKETS}:
        # Unknown market token — keep but note it so the caller can warn
        notes = [f"Declared market '{declared_market}' is not a known preset; using core questions only."]
        declared = "unknown"
    else:
        notes = []

    manifest = build_input_manifest(input_files)
    gaps = find_input_gaps(manifest)
    interview = build_interview_pack(manifest, declared, extra_markets)
    standards = compute_standards_shortlist(declared, manifest, extra_markets)
    analyzers = compute_analyzer_shortlist(declared, manifest, extra_markets)
    playbook = load_playbook_markdown()

    # If declared==unknown but there are inputs that strongly suggest a market,
    # add an advisory note (Phase 4 will auto-infer; for now we just hint).
    if declared == "unknown":
        notes.append(
            "No market declared — only core questions returned. Call "
            "pcb_set_market or include declared_market on the next call."
        )

    return StartProfessionalReviewResult(
        session_id=session_id,
        playbook_markdown=playbook,
        input_manifest=manifest,
        gaps=gaps,
        interview_pack=interview,
        standards_shortlist=standards,
        analyzer_shortlist=analyzers,
        pass_checklist=list(PASS_CHECKLIST),
        declared_market=declared,
        product_description=product_description,
        notes=notes,
    )

"""Headless command-line interface for mcp-pcb-emcopilot.

Turns the analysis engine into a one-command product::

    mcp-pcb-emcopilot review board.kicad_pcb -o report.docx --market automotive

The ``review`` subcommand chains ``parse_pcb_file -> run_design_review ->
generate_*_report`` with no LLM or MCP host in the loop. It is the same
deterministic pipeline proven by ``tests/test_end_to_end_review.py``, wrapped
so a human (or a future HTTP API) can drive it directly.

Design notes:
  * Engine imports are lazy so ``--help`` is instant and a missing optional
    dependency produces an actionable message rather than an import traceback.
  * The summary is deliberately honest: if any analysis domain errored or was
    skipped, the review is flagged PARTIAL. A wrong "PASS" is worse than no
    tool, so a headless run must never quietly imply full coverage.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Optional, Sequence

_VALID_FORMATS = ("docx", "html", "both")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mcp-pcb-emcopilot review",
        description="Run a headless PCB EMC/SI design review and write a report.",
    )
    p.add_argument(
        "board",
        help="Path to a board/design file (KiCad, Altium, Gerber/ODB++, STEP, or BOM).",
    )
    p.add_argument(
        "-o",
        "--output",
        help="Output report path. If omitted, written next to the board. "
        "Extension selects the format when --format is not given.",
    )
    p.add_argument(
        "-f",
        "--format",
        choices=_VALID_FORMATS,
        default=None,
        help="Report format. Default: inferred from -o extension, else docx.",
    )
    p.add_argument(
        "-m",
        "--market",
        action="append",
        default=None,
        metavar="MARKET",
        help="Target market (automotive, commercial, industrial, medical, wireless). "
        "Repeatable; drives the market-specific standards intake.",
    )
    p.add_argument("--title", default="PCB Design Review Report", help="Report title.")
    p.add_argument(
        "--theme", choices=("light", "dark"), default="light", help="HTML report theme."
    )
    p.add_argument(
        "--session-id", default="cli", help="Session identifier recorded in the report."
    )
    p.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress the summary printed to stderr."
    )
    return p


def _infer_format(fmt: Optional[str], output: Optional[str]) -> str:
    if fmt:
        return fmt
    if output:
        ext = Path(output).suffix.lower().lstrip(".")
        if ext in ("docx", "html"):
            return ext
    return "docx"


def _default_output(board: Path, fmt: str) -> Path:
    ext = "html" if fmt == "html" else "docx"
    return board.with_name(f"{board.stem}_design_review.{ext}")


def run_review(argv: Optional[Sequence[str]] = None) -> int:
    """Execute the ``review`` subcommand. Returns a process exit code.

    Exit codes: 0 success, 1 runtime failure (parse/report), 2 usage error
    (missing file, unknown market).
    """
    args = _build_parser().parse_args(list(argv) if argv is not None else None)

    board = Path(args.board)
    if not board.exists():
        print(f"error: board file not found: {board}", file=sys.stderr)
        return 2

    # Lazy imports: keep --help fast and surface dependency problems clearly.
    from . import market_packs
    from .orchestrator import run_design_review
    from .parsers import parse_pcb_file

    markets = [m.strip().lower() for m in (args.market or []) if m.strip()]
    unknown = [m for m in markets if m not in market_packs.KNOWN_MARKETS]
    if unknown:
        print(
            f"error: unknown market(s): {', '.join(unknown)}. "
            f"Known markets: {', '.join(market_packs.KNOWN_MARKETS)}",
            file=sys.stderr,
        )
        return 2

    try:
        design = parse_pcb_file(str(board))
    except Exception as exc:  # parsers raise structured errors; surface cleanly
        print(f"error: failed to parse {board.name}: {exc}", file=sys.stderr)
        return 1

    if markets:
        ctx = dict(design.review_context or {})
        ctx["markets"] = markets
        design.review_context = ctx

    review = run_design_review(design, session_id=args.session_id)
    design.review_results = review.to_dict()

    fmt = _infer_format(args.format, args.output)
    base = Path(args.output) if args.output else _default_output(board, fmt)

    written: list[Path] = []

    def _write_docx(path: Path) -> bool:
        try:
            from .reports.docx_report import generate_docx_report
        except Exception as exc:
            print(
                f"warning: DOCX report unavailable ({exc}); "
                "install python-docx or use --format html",
                file=sys.stderr,
            )
            return False
        generate_docx_report(
            design, session_id=args.session_id, output_path=str(path), title=args.title
        )
        written.append(path)
        return True

    def _write_html(path: Path) -> bool:
        from .reports.html_report import generate_html_report

        generate_html_report(
            design=design,
            session_id=args.session_id,
            output_path=str(path),
            title=args.title,
            theme=args.theme,
        )
        written.append(path)
        return True

    if fmt == "both":
        _write_docx(base.with_suffix(".docx"))
        _write_html(base.with_suffix(".html"))
    elif fmt == "html":
        _write_html(base if base.suffix.lower() == ".html" else base.with_suffix(".html"))
    else:  # docx
        target = base if base.suffix.lower() == ".docx" else base.with_suffix(".docx")
        if not _write_docx(target):
            # Degrade gracefully to HTML so the user still gets a report.
            _write_html(target.with_suffix(".html"))

    if not written:
        print("error: no report was produced", file=sys.stderr)
        return 1

    if not args.quiet:
        _print_summary(review, written, markets, design)
    return 0


def _print_summary(review, written: Sequence[Path], markets: Sequence[str], design) -> None:
    """Print an honest one-screen summary to stderr (stdout stays clean)."""
    statuses = Counter(dr.status for dr in review.domain_results)
    crit = sum(dr.critical_count for dr in review.domain_results)
    warn = sum(dr.warning_count for dr in review.domain_results)
    info = sum(dr.info_count for dr in review.domain_results)
    not_assessed = statuses.get("error", 0) + statuses.get("skipped", 0)

    lines = ["── PCB EMC/SI Design Review ───────────────────────────────"]
    if markets:
        lines.append(f"  markets:  {', '.join(markets)}")
    if getattr(design, "parse_is_partial", False):
        lines.append("  parse:    ⚠ PARTIAL. The design file did not fully parse")
        for w in list(getattr(design, "warnings", []))[:5]:
            lines.append(f"              • {w}")
    lines.append(
        "  domains:  {total} ({fail} fail, {warn} warn, {ok} pass, "
        "{err} error, {skip} skipped)".format(
            total=sum(statuses.values()),
            fail=statuses.get("fail", 0),
            warn=statuses.get("warning", 0),
            ok=statuses.get("pass", 0),
            err=statuses.get("error", 0),
            skip=statuses.get("skipped", 0),
        )
    )
    lines.append(f"  findings: {crit} critical, {warn} warning, {info} info")
    for path in written:
        lines.append(f"  report:   {path}")
    if not_assessed:
        lines.append("")
        lines.append(
            f"  ⚠ {not_assessed} domain(s) errored or were skipped. This review is "
            "PARTIAL."
        )
        lines.append(
            "    Treat the result as a screening pass, not a compliance verdict; "
            "human review required."
        )
    print("\n".join(lines), file=sys.stderr)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for ``mcp-pcb-emcopilot review`` (returns an exit code)."""
    return run_review(argv)


if __name__ == "__main__":
    raise SystemExit(run_review())

"""KiCad Action Plugin that integrates with MCP PCB EMCopilot.

This plugin adds an 'EMC Review' button to KiCad's PCB editor that
sends the current board to the MCP server for analysis.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Optional

# KiCad's pcbnew module — only available inside KiCad
try:
    import pcbnew
    KICAD_AVAILABLE = True
except ImportError:
    KICAD_AVAILABLE = False


class EMCopilotPlugin:
    """KiCad action plugin for EMC design review.

    Registers as a KiCad plugin that appears in the Tools menu.
    When activated, it:
    1. Exports the current board as a .kicad_pcb file
    2. Launches the MCP server
    3. Sends the board for analysis
    4. Displays findings as markers on the PCB
    """

    def __init__(self):
        self.name = "EMCopilot Review"
        self.category = "EMC"
        self.description = "Run EMC/SI/PI design review via MCP PCB EMCopilot"
        self.icon_file_name = ""
        self.show_toolbar_button = True
        self._mcp_process: Optional[subprocess.Popen] = None

    def defaults(self):
        """Set default values."""
        self.name = "EMCopilot Review"
        self.category = "EMC"
        self.description = "Run EMC/SI/PI design review"

    def Run(self):
        """Execute the plugin action."""
        if not KICAD_AVAILABLE:
            raise RuntimeError("This plugin must be run inside KiCad")

        board = pcbnew.GetBoard()
        if board is None:
            self._show_message("No board loaded", "Error")
            return

        board_file = board.GetFileName()
        if not board_file:
            # Save to temp file
            board_file = self._save_temp_board(board)

        # Run analysis
        try:
            results = self._run_analysis(board_file)
            self._display_results(board, results)
            self._show_message(
                f"EMC Review complete. Found {len(results.get('findings', []))} issues.",
                "EMCopilot Review"
            )
        except Exception as e:
            self._show_message(f"Analysis failed: {e}", "Error")

    def _save_temp_board(self, board) -> str:
        """Save board to temporary .kicad_pcb file."""
        tmp = tempfile.NamedTemporaryFile(suffix=".kicad_pcb", delete=False)
        tmp.close()
        board.Save(tmp.name)
        return tmp.name

    def _run_analysis(self, board_file: str) -> dict:
        """Run MCP PCB EMCopilot analysis on the board file.

        Uses subprocess to call the MCP server's CLI tools.
        """
        # Try using uv run if available, fall back to direct python
        mcp_dir = os.environ.get("EMCOPILOT_DIR", "")

        cmd = [
            "uv", "run", "--directory", mcp_dir,
            "python", "-c",
            f"""
import json
from mcp_pcb_emcopilot.parsers import parse_pcb_file
from mcp_pcb_emcopilot.orchestrator import run_design_review

data = parse_pcb_file("{board_file}")
results = run_design_review(data)
print(json.dumps(results))
"""
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )

        if result.returncode != 0:
            raise RuntimeError(f"Analysis failed: {result.stderr}")

        return json.loads(result.stdout)

    def _display_results(self, board, results: dict):
        """Display analysis results as markers on the PCB."""
        findings = results.get("findings", [])

        for finding in findings:
            severity = finding.get("severity", "info")
            location = finding.get("location", "")
            message = finding.get("title", "")

            # Find component by reference
            if location:
                footprint = board.FindFootprintByReference(location)
                if footprint:
                    pos = footprint.GetPosition()
                    marker = pcbnew.PCB_MARKER(
                        pcbnew.MARKER_BASE.MARKER_SEVERITY_WARNING
                        if severity == "warning"
                        else pcbnew.MARKER_BASE.MARKER_SEVERITY_ERROR,
                        message,
                        pos
                    )
                    board.Add(marker)

        pcbnew.Refresh()

    def _show_message(self, message: str, title: str):
        """Show message dialog in KiCad."""
        if KICAD_AVAILABLE:
            import wx
            wx.MessageBox(message, title, wx.OK | wx.ICON_INFORMATION)


# Register plugin with KiCad
if KICAD_AVAILABLE:
    class EMCopilotActionPlugin(pcbnew.ActionPlugin):
        def defaults(self):
            self.name = "EMCopilot Review"
            self.category = "EMC Analysis"
            self.description = "Run EMC/SI/PI design review via MCP PCB EMCopilot"
            self.show_toolbar_button = True
            self.icon_file_name = os.path.join(
                os.path.dirname(__file__), "icon.png"
            )

        def Run(self):
            plugin = EMCopilotPlugin()
            plugin.Run()

    EMCopilotActionPlugin().register()

# MCP PCB EMCopilot KiCad Plugin

KiCad action plugin that integrates with MCP PCB EMCopilot for automated design review.

## Installation

1. Install MCP PCB EMCopilot: `pip install mcp-pcb-emcopilot`
2. Copy this directory to KiCad's plugin path:
   - Linux: `~/.local/share/kicad/7.0/scripting/plugins/`
   - macOS: `~/Library/Preferences/kicad/7.0/scripting/plugins/`
   - Windows: `%APPDATA%/kicad/7.0/scripting/plugins/`
3. Set `EMCOPILOT_DIR` environment variable to the mcp-pcb-emcopilot directory
4. Restart KiCad

## Usage

1. Open a PCB in KiCad's PCB Editor
2. Go to Tools → External Plugins → EMCopilot Review
3. Review findings displayed as markers on the board

# mcp-pcb-emcopilot

**AI-powered PCB design review — EMC, signal integrity, power integrity, thermal, and DFM in one MCP server.**
**Catch return-path breaks, decoupling gaps, and DDR/PCIe topology errors before fabrication, from your terminal or AI agent.**

---

## What it is

mcp-pcb-emcopilot is a Model Context Protocol server with **93 tools**
that parse PCB layouts (KiCad, ODB++, Gerber, IPC-2581, Altium, STEP),
analyze them across 8 engineering domains with physics-based
calculations, predict EMC compliance against FCC / CISPR / IEC, and
emit audit-grade DOCX / HTML reports with embedded board renders.

## Install

```bash
git clone https://github.com/RFingAdam/mcp-pcb-emcopilot.git
cd mcp-pcb-emcopilot
uv pip install -e .

# Optional extras
pip install cairosvg python-docx pymupdf
```

## First call

=== "MCP"

    Add to `claude_desktop_config.json`:

    ```json
    {
      "mcpServers": {
        "pcb-emcopilot": {
          "command": "uv",
          "args": ["run", "--directory", "/path/to/mcp-pcb-emcopilot", "mcp-pcb-emcopilot"]
        }
      }
    }
    ```

    Then ask your assistant:

    > *"Parse design.kicad_pcb, run a comprehensive design review, and generate a DOCX report."*

=== "CLI"

    ```bash
    uv run mcp-pcb-emcopilot   # starts the stdio MCP server
    ```

## Where to next

- [Tool reference](tools.md) — every MCP tool with arguments
- [Usage examples](usage.md) — full review on a real 4-layer board
- [Architecture](architecture.md) — how this MCP fits inside eng-mcp-suite

---

!!! note "Part of eng-mcp-suite"
    This MCP server is part of [eng-mcp-suite](https://github.com/RFingAdam/eng-mcp-suite) —
    an umbrella of engineering MCP servers across RF, EMC, PCB, signal
    integrity, EM simulation, and lab test.

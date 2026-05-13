# Usage

This page walks one realistic scenario from problem to result. For the
full tool reference, see [Tools](tools.md).

---

## Scenario: mixed-signal 4-layer board, pre-fab review

You have a 4-layer mixed-signal board (MCU + USB 2.0 + LDO + 100 MHz
clock domain) ready to send out for fab. Before you spend the money,
you want a full EMC + SI + PI + DFM review with an audit-grade report
your manager can sign off on.

## Setup

```bash
git clone https://github.com/RFingAdam/mcp-pcb-emcopilot.git
cd mcp-pcb-emcopilot
uv pip install -e .
pip install cairosvg python-docx
```

Register the MCP server:

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

## Step 1 — Parse the layout

Ask the assistant:

> *"Parse mixed_signal_v3.kicad_pcb and tell me the board outline, layer count, and net summary."*

The agent calls `pcb_parse_layout`:

```json
{ "file_path": "mixed_signal_v3.kicad_pcb" }
```

It returns a `session_id` plus a summary: 4 layers (signal / GND /
PWR / signal), 104 nets, 215 components, 1.6 mm thickness. The agent
caches the session for the rest of the conversation.

## Step 2 — Set the review context

> *"Target FCC Class B and CISPR 32 Class B. The product is a USB
> peripheral; rev is v3-prelim."*

The agent calls `pcb_set_review_context` so all downstream analyzers
score against the right standards.

## Step 3 — Run the orchestrated review

> *"Run a comprehensive design review across EMC, SI, PI, thermal, and DFM."*

The agent calls `pcb_run_design_review` which walks classifiers →
analyzers → orchestrator → findings:

```json
{
  "go_no_go": "go-with-conditions",
  "domain_scores": {
    "emc":     {"score": 78, "findings": 5},
    "si":      {"score": 84, "findings": 3},
    "pi":      {"score": 91, "findings": 1},
    "thermal": {"score": 88, "findings": 1},
    "dfm":     {"score": 95, "findings": 0}
  },
  "critical": 0,
  "high":     2,
  "medium":   5,
  "low":      3
}
```

Two high-severity findings (return-path break under the USB diff pair
at the GND-island boundary; missing 100 nF decap on a digital rail) —
both with `pcb_trace_return_path` and `pcb_analyze_decoupling`
references for the fixer.

## Step 4 — Annotate + render the board

> *"Render the board with findings annotated, and highlight the USB
> differential pair net."*

The agent calls `pcb_render_board`, `pcb_annotate_board`,
`pcb_render_net` — three SVGs that visualize the analyzer output on
top of the actual layout.

## Step 5 — Generate the DOCX

> *"Generate the DOCX report with executive summary, embedded
> renders, and per-finding severity table."*

The agent calls `pcb_generate_docx_report`. The output document has:

- Executive summary + Go/No-Go
- Per-domain score dashboard
- Embedded board render + net highlights + annotated findings
- Priority action items table (sortable by severity)
- Component summary + tool coverage appendix

You hand it to your manager. They counter-sign. You release the
gerbers.

---

## What just happened

In five tool calls (~2 min of agent time), you went from "I have a
KiCad file" to a fab-ready review document with traceable findings.
No GUI clicking, no per-net cross-check by hand, no separate EMC tool.

- For more tools: [Tool reference](tools.md)
- For how this fits in the suite: [Architecture](architecture.md)
- For sibling MCPs that compose with this one: [eng-mcp-suite catalog](https://github.com/RFingAdam/eng-mcp-suite#whats-included)

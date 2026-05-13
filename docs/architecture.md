# Architecture

## Internal layout

```
┌──────────────────────────────────────────────────────────────────┐
│  User-facing surface                                             │
│  ┌────────────────────────────┐                                  │
│  │  MCP server (stdio)        │                                  │
│  │  mcp.server.Server         │                                  │
│  │  (93 tools)                │                                  │
│  └────────────────────────────┘                                  │
└──────────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────────────────────────────────────────┐
│  Orchestration                                                   │
│  • Session manager (in-memory id → PCBDesignData)                │
│  • Review orchestrator (pcb_run_design_review)                   │
│  • Domain dispatcher (parser → classifier → analyzer)            │
│  • Report builder (markdown, DOCX with embedded renders)         │
└──────────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────────────────────────────────────────┐
│  Domain modules                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │
│  │  parsers/   │  │ classifiers │  │  analyzers/ │               │
│  │ KiCad/ODB++ │  │ design / net│  │ emc/si/pi/  │               │
│  │ Gerber/Alt. │  │ interface   │  │ thermal/dfm │               │
│  │ IPC-2581    │  │  detection  │  │  + ESD      │               │
│  │ STEP        │  └─────────────┘  └─────────────┘               │
│  └─────────────┘                                                 │
│  ┌─────────────┐  ┌─────────────┐                                │
│  │ reports/    │  │ visualizn/  │                                │
│  │ docx + md   │  │ SVG + PNG   │                                │
│  └─────────────┘  └─────────────┘                                │
└──────────────────────────────────────────────────────────────────┘
```

The server is layered: parsers normalize file formats into a single
`PCBDesignData` model; classifiers tag nets and interfaces; analyzers
run physics-based checks against that model; reports + visualization
turn analyzer findings into engineer-readable artifacts. Sessions are
in-memory keyed by id — restart-clean.

## Source layout

```
mcp-pcb-emcopilot/
├── src/mcp_pcb_emcopilot/
│   ├── __init__.py
│   ├── server.py           ← MCP server + tool registrations
│   ├── orchestrator.py     ← pcb_run_design_review walker
│   ├── session.py          ← in-memory design session manager
│   ├── parsers/            ← KiCad / ODB++ / Gerber / Altium / IPC-2581 / STEP
│   ├── classifiers/        ← design / net / interface classification
│   ├── analyzers/          ← emc / si / pi / thermal / dfm / esd / digital
│   ├── reports/            ← markdown + DOCX builders
│   ├── visualization/      ← SVG renderers, PNG export
│   ├── integrations/       ← (e.g. PCB-to-openEMS bridge)
│   └── models/pcb_data.py  ← PCBDesignData
├── tests/
├── docs/
└── assets/                 ← logo-banner.svg, logo.svg
```

## Position in eng-mcp-suite

mcp-pcb-emcopilot sits in the **layout-aware analysis** layer of the
engineering MCP stack — it takes a real PCB file in, emits findings
out. The circuit-level synthesis siblings stop at the schematic, and
the field-solver siblings cover specific geometries; this server
bridges them on actual hardware.

```
        ┌─────────────────────────────────────┐
        │   AI agent (Claude Code / Desktop)  │
        └──────┬──────────────┬───────────────┘
               │              │ via MCP
       ┌───────▼─────────────┐ ┌─▼──────────────────────────┐
       │ mcp-pcb-emcopilot   │ │ mcp-ltspice-qucs           │
       │  (layout-aware)     │ │  (schematic-only)          │
       │                     │ │ mcp-emc-regulations        │
       │                     │ │  (standards lookup)        │
       └───────┬─────────────┘ └────────────────────────────┘
               │   findings + renders
       ┌───────▼──────────────────────────┐
       │  drawio-engineering-mcp          │  (design-doc diagrams)
       └──────────────────────────────────┘
```

### Feeds (this MCP produces output that)…

- **drawio-engineering-mcp** — board renders + EMI hotspot maps for
  documentation packages.
- **mcp-emc-regulations** — predicted-emission spectra for
  margin-against-limit comparisons.

### Consumes (this MCP accepts input from)…

- **lineforge** — characteristic-impedance reference values used to
  cross-check `pcb_calc_*_impedance` results.
- **mcp-ltspice-qucs** — Touchstone `.s2p` from filter designs so the
  insertion-loss budgeter can include the schematic-level filter
  contribution.

### Workflow bundles that include this MCP

| Bundle                | Role of this MCP                                  |
| --------------------- | ------------------------------------------------- |
| `pcb-review`          | Primary layout-analysis step                      |
| `coexistence-review`  | Layout-level shielding + return-path validation   |
| `smps-emc`            | SMPS layout EMI risk scoring                      |

See the [suite manifest](https://github.com/RFingAdam/eng-mcp-suite/blob/main/manifest.yaml)
for full bundle definitions.

---

## Design decisions

- **One `PCBDesignData` model, many parsers.** Every input format
  (KiCad / ODB++ / Gerber / Altium / IPC-2581) normalizes to the
  same in-memory model so analyzers don't care about source format.
- **Analyzers as pure functions on `PCBDesignData`.** Each analyzer
  is independently callable and side-effect-free. The orchestrator
  composes them; an agent can also call any one in isolation when
  it wants to debug a single net.
- **Reports include rendered evidence.** Every finding in the DOCX
  has a board-render thumbnail showing exactly where it lives. This
  is the difference between "review document" and "actionable PR
  comment."
- **Apache-2.0 + Server low-level MCP SDK.** Wider compatibility
  surface than FastMCP-only servers (the codebase already had this
  before MCP framework conventions stabilized).

# Web UI (React)

React + Vite + Tailwind frontend for the MCP PCB EMCopilot. Salvaged from
the earlier Agentarium `pcb_em_copilot` module on 2026-04-21.

## Status

- Components and pages (`AIReviewPage`, `AnalysisReportPage`, `FindingsViewerPage`,
  `ViolationsPanel`, `ResultsViewerPage`, `ProjectDetailPage`, `RuleEditorPage`) are present.
- API client under `src/api/` assumed the Agentarium FastAPI backend shape —
  retargeting to the Flask app at `src/mcp_pcb_emcopilot/web/app.py` is the
  outstanding integration work.
- Node dependencies are NOT vendored here; run `npm install` inside this
  directory before building.

## Build

```bash
cd web-ui
npm install
npm run build     # static output in dist/
npm run dev       # vite dev server against a local Flask backend
```

## Integration roadmap

1. Retarget `src/api/*` to the Flask endpoints in `mcp_pcb_emcopilot.web.app`.
2. Add a `web-ui` extra to `pyproject.toml` that builds the frontend and
   bundles `dist/` into the installed package as static assets.
3. Serve the built assets from the Flask app at `/`.

Until then, the existing Jinja-rendered Flask UI is the supported path;
this directory is scaffolding for the next iteration.

"""Flask web UI for PCB EMCopilot design review."""
from __future__ import annotations

import html
import os
import tempfile
import uuid
from typing import Optional

try:
    from flask import Flask, Response, jsonify, redirect, request, url_for
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

from ..parsers import parse_pcb_file

# In-memory session store
_sessions: dict[str, dict] = {}


def create_app() -> Flask:
    """Create and configure the Flask application."""
    if not FLASK_AVAILABLE:
        raise ImportError("Flask is required for the web UI. Install with: pip install flask")

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB max

    @app.route("/")
    def index():
        return _render_index()

    @app.route("/api/upload", methods=["POST"])
    def upload():
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files["file"]
        if not file.filename:
            return jsonify({"error": "No filename"}), 400

        # Save to temp file
        ext = os.path.splitext(file.filename)[1]
        fd, tmp_path = tempfile.mkstemp(suffix=ext)
        os.close(fd)

        try:
            file.save(tmp_path)
            data = parse_pcb_file(tmp_path)

            session_id = str(uuid.uuid4())[:8]
            _sessions[session_id] = {
                "filename": file.filename,
                "data": data,
            }

            return redirect(f"/session/{session_id}")
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @app.route("/session/<session_id>")
    def session_view(session_id):
        session = _sessions.get(session_id)
        if not session:
            return "Session not found", 404
        return _render_session(session_id, session)

    @app.route("/api/session/<session_id>")
    def session_api(session_id):
        session = _sessions.get(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 404

        data = session["data"]
        return jsonify({
            "session_id": session_id,
            "filename": session["filename"],
            "board_width_mm": data.board_width_mm,
            "board_height_mm": data.board_height_mm,
            "layer_count": data.layer_count,
            "component_count": len(data.components),
            "net_count": len(data.nets),
            "trace_count": len(data.traces),
            "via_count": len(data.vias),
        })

    @app.route("/download/<session_id>/html")
    def download_html(session_id):
        session = _sessions.get(session_id)
        if not session:
            return "Session not found", 404

        from ..reports.html_report import generate_html_report
        path = generate_html_report(
            session["data"], session_id,
            title=f"Design Review: {session['filename']}",
        )

        with open(path) as f:
            html_content = f.read()
        os.unlink(path)

        return Response(
            html_content,
            mimetype="text/html",
            headers={
                "Content-Disposition": f"attachment; filename=review_{session_id}.html",
            },
        )

    return app


def _render_index() -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MCP PCB EMCopilot</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <div class="container">
    <h1>MCP PCB EMCopilot</h1>
    <div class="subtitle">AI-powered PCB Design Review Dashboard</div>
  </div>
</header>
<main class="container">
  <div class="upload-card">
    <h2>Upload PCB Design</h2>
    <p>Supported formats: KiCad (.kicad_pcb), ODB++ (.tgz), Gerber (.gbr), IPC-2581 (.xml), Allegro (.brd, .txt), Altium (.PcbDoc)</p>
    <form action="/api/upload" method="post" enctype="multipart/form-data" id="upload-form">
      <div class="drop-zone" id="drop-zone">
        <p>Drag &amp; drop PCB file here<br>or click to browse</p>
        <input type="file" name="file" id="file-input" accept=".kicad_pcb,.tgz,.tar.gz,.gbr,.ger,.xml,.cvg,.brd,.txt,.PcbDoc,.step,.stp,.pdf" />
      </div>
      <button type="submit" class="btn" id="upload-btn" disabled>Upload &amp; Analyze</button>
    </form>
  </div>

  <div class="sessions-list">
    <h2>Recent Sessions</h2>
    <div id="sessions">
      {"".join(
          f'<a href="/session/{sid}" class="session-link">{html.escape(s["filename"])} ({sid})</a>'
          for sid, s in _sessions.items()
      ) or '<p class="muted">No sessions yet. Upload a file to get started.</p>'}
    </div>
  </div>
</main>
<script>
var dropZone = document.getElementById('drop-zone');
var fileInput = document.getElementById('file-input');
var uploadBtn = document.getElementById('upload-btn');

dropZone.addEventListener('click', function() {{ fileInput.click(); }});
fileInput.addEventListener('change', function() {{
    if (this.files.length) {{
        dropZone.querySelector('p').textContent = this.files[0].name;
        uploadBtn.disabled = false;
    }}
}});
dropZone.addEventListener('dragover', function(e) {{ e.preventDefault(); this.classList.add('drag-over'); }});
dropZone.addEventListener('dragleave', function() {{ this.classList.remove('drag-over'); }});
dropZone.addEventListener('drop', function(e) {{
    e.preventDefault();
    this.classList.remove('drag-over');
    fileInput.files = e.dataTransfer.files;
    if (fileInput.files.length) {{
        dropZone.querySelector('p').textContent = fileInput.files[0].name;
        uploadBtn.disabled = false;
    }}
}});
</script>
</body>
</html>"""


def _render_session(session_id: str, session: dict) -> str:
    data = session["data"]

    # Build component table
    comp_rows = ""
    for c in data.components[:50]:  # Limit to 50 for display
        ref = getattr(c, 'ref_des', '') or getattr(c, 'reference', '') or ''
        val = getattr(c, 'value', '') or ''
        pkg = getattr(c, 'package', '') or getattr(c, 'footprint', '') or ''
        layer = getattr(c, 'layer', '') or ''
        comp_rows += f"<tr><td>{html.escape(ref)}</td><td>{html.escape(val)}</td><td>{html.escape(pkg)}</td><td>{html.escape(layer)}</td></tr>"

    # Build net list
    net_items = ""
    for n in data.nets[:50]:
        name = getattr(n, 'name', '') or getattr(n, 'net_name', '') or ''
        pin_count = len(getattr(n, 'pins', [])) if hasattr(n, 'pins') else 0
        net_items += f"<div class='net-item'><span class='net-name'>{html.escape(name)}</span> <span class='muted'>({pin_count} pins)</span></div>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Review: {html.escape(session["filename"])}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <div class="container">
    <h1>Design Review</h1>
    <div class="subtitle">{html.escape(session["filename"])} | Session: {session_id}</div>
  </div>
</header>
<main class="container">
  <div class="actions">
    <a href="/" class="btn btn-secondary">Back</a>
    <a href="/download/{session_id}/html" class="btn">Download HTML Report</a>
    <a href="/api/session/{session_id}" class="btn btn-secondary">View JSON</a>
  </div>

  <div class="summary-grid">
    <div class="summary-card">
      <div class="value">{data.board_width_mm or 0:.1f} x {data.board_height_mm or 0:.1f}</div>
      <div class="label">Board Size (mm)</div>
    </div>
    <div class="summary-card">
      <div class="value">{data.layer_count or len(data.layers)}</div>
      <div class="label">Layers</div>
    </div>
    <div class="summary-card">
      <div class="value">{len(data.components)}</div>
      <div class="label">Components</div>
    </div>
    <div class="summary-card">
      <div class="value">{len(data.nets)}</div>
      <div class="label">Nets</div>
    </div>
    <div class="summary-card">
      <div class="value">{len(data.traces)}</div>
      <div class="label">Traces</div>
    </div>
    <div class="summary-card">
      <div class="value">{len(data.vias)}</div>
      <div class="label">Vias</div>
    </div>
  </div>

  <div class="section">
    <h2>Components</h2>
    <table class="data-table">
      <thead><tr><th>Ref</th><th>Value</th><th>Package</th><th>Layer</th></tr></thead>
      <tbody>{comp_rows}</tbody>
    </table>
    {"<p class='muted'>Showing first 50 of " + str(len(data.components)) + " components</p>" if len(data.components) > 50 else ""}
  </div>

  <div class="section">
    <h2>Nets</h2>
    <div class="net-grid">{net_items}</div>
    {"<p class='muted'>Showing first 50 of " + str(len(data.nets)) + " nets</p>" if len(data.nets) > 50 else ""}
  </div>

  <div class="section">
    <h2>Format Info</h2>
    <table class="data-table">
      <tbody>
        <tr><td>Source Format</td><td>{html.escape(str(data.source_format))}</td></tr>
        <tr><td>Source File</td><td>{html.escape(str(data.source_file))}</td></tr>
        <tr><td>Title</td><td>{html.escape(data.title) if data.title else 'N/A'}</td></tr>
      </tbody>
    </table>
  </div>
</main>
</body>
</html>"""


_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0f172a;
    color: #e2e8f0;
    line-height: 1.6;
}
.container { max-width: 1100px; margin: 0 auto; padding: 0 24px; }
header {
    background: #0f172a;
    padding: 32px 0 24px;
    border-bottom: 3px solid #22d3ee;
    margin-bottom: 32px;
}
header h1 { font-size: 28px; font-weight: 700; color: #f1f5f9; }
header .subtitle { font-size: 14px; color: #94a3b8; margin-top: 4px; }
.muted { color: #64748b; font-size: 13px; }

.upload-card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 32px;
    margin-bottom: 24px;
}
.upload-card h2 { margin-bottom: 8px; font-size: 20px; }
.upload-card p { color: #94a3b8; margin-bottom: 16px; font-size: 13px; }

.drop-zone {
    border: 2px dashed #334155;
    border-radius: 8px;
    padding: 48px;
    text-align: center;
    cursor: pointer;
    transition: all 0.2s;
    margin-bottom: 16px;
}
.drop-zone:hover, .drop-zone.drag-over {
    border-color: #22d3ee;
    background: rgba(34, 211, 238, 0.05);
}
.drop-zone p { color: #94a3b8; }
.drop-zone input[type=file] { display: none; }

.btn {
    display: inline-block;
    padding: 10px 24px;
    background: #22d3ee;
    color: #0f172a;
    border: none;
    border-radius: 8px;
    font-weight: 600;
    font-size: 14px;
    cursor: pointer;
    text-decoration: none;
    transition: opacity 0.2s;
}
.btn:hover { opacity: 0.85; }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-secondary { background: #334155; color: #e2e8f0; }

.actions { margin-bottom: 24px; display: flex; gap: 12px; }

.summary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 16px;
    margin: 24px 0;
}
.summary-card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 16px;
    text-align: center;
}
.summary-card .value { font-size: 28px; font-weight: 700; color: #22d3ee; }
.summary-card .label { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; }

.section {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 24px;
    margin-bottom: 24px;
}
.section h2 { font-size: 18px; margin-bottom: 16px; color: #f1f5f9; }

.data-table { width: 100%; border-collapse: collapse; }
.data-table th, .data-table td {
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid #334155;
    font-size: 13px;
}
.data-table th { color: #94a3b8; font-weight: 600; }
.data-table tr:hover { background: rgba(34, 211, 238, 0.03); }

.net-grid { display: flex; flex-wrap: wrap; gap: 8px; }
.net-item {
    background: #0f172a;
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 13px;
    border: 1px solid #334155;
}
.net-name { color: #22d3ee; font-weight: 600; }

.sessions-list {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 24px;
}
.sessions-list h2 { margin-bottom: 12px; font-size: 18px; }
.session-link {
    display: block;
    padding: 10px 16px;
    color: #22d3ee;
    text-decoration: none;
    border-radius: 6px;
    margin-bottom: 4px;
    transition: background 0.2s;
}
.session-link:hover { background: rgba(34, 211, 238, 0.08); }

@media print {
    body { background: white; color: black; }
    header { border-bottom: 2px solid #333; }
    .btn, .actions { display: none; }
}
"""

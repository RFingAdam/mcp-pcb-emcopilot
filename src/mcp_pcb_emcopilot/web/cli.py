"""CLI entry point for the web UI."""
from __future__ import annotations

import argparse


def main():
    parser = argparse.ArgumentParser(description="MCP PCB EMCopilot Web UI")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    from .app import create_app
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()

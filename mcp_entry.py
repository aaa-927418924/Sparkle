"""Console-capable PyInstaller entry point for local and Remote MCP."""

from __future__ import annotations

from mcp_server import main


if __name__ == "__main__":
    raise SystemExit(main())

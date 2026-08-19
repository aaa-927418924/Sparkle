"""Console-capable PyInstaller entry point for Claude Desktop stdio MCP."""

from __future__ import annotations

from mcp_server import main


if __name__ == "__main__":
    raise SystemExit(main())

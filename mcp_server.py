"""Claude Desktop entry point for Sparkle's read-only local MCP server."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

from mcp.server import MCPServer

from sparkle_mcp import __version__
from sparkle_mcp.service import ToolService
from sparkle_mcp.tools import register_tools


LOGGER = logging.getLogger("sparkle_mcp")


def build_server(db_path: Path | str | None = None) -> MCPServer:
    server = MCPServer(
        name="sparkle",
        title="Sparkle",
        description="Read-only access to the local Sparkle clip, memo, task, and project database.",
        instructions=(
            "This server is read-only. Search first to obtain candidate IDs, then call the corresponding get tool "
            "for details. Local file paths are intentionally redacted. Never invent an ID when a search is needed."
        ),
        version=__version__,
        log_level="WARNING",
    )
    register_tools(server, ToolService(db_path))
    return server


def _configure_logging() -> None:
    # stdout is reserved for MCP JSON-RPC frames in stdio mode.
    logging.basicConfig(
        level=logging.WARNING,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Sparkle's read-only MCP server over stdio.")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Optional SQLite path. Defaults to %%APPDATA%%\\Sparkle\\clips.db (or SPARKLE_DB_PATH).",
    )
    args = parser.parse_args(argv)
    _configure_logging()
    LOGGER.info("Starting Sparkle MCP server")
    build_server(args.db_path).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

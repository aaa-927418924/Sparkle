"""Claude Desktop entry point for Sparkle's read-only local MCP server."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from mcp.server import MCPServer

from sparkle_mcp import __version__
from sparkle_mcp.service import ToolService
from sparkle_mcp.tools import register_tools


LOGGER = logging.getLogger("sparkle_mcp")


def build_server(
    db_path: Path | str | None = None,
    token_verifier: Any | None = None,
    auth: Any | None = None,
) -> MCPServer:
    server_kwargs: dict[str, Any] = {
        "name": "sparkle",
        "title": "Sparkle",
        "description": "Read-only access to the local Sparkle clip, memo, task, and project database.",
        "instructions": (
            "This server is read-only. Search first to obtain candidate IDs, then call the corresponding get tool "
            "for details. Local file paths are intentionally redacted. Never invent an ID when a search is needed."
        ),
        "version": __version__,
        "log_level": "WARNING",
    }
    if token_verifier is not None or auth is not None:
        if token_verifier is None or auth is None:
            raise ValueError("Remote MCPのtoken_verifierとauthは同時に指定してください。")
        server_kwargs.update(token_verifier=token_verifier, auth=auth)

    server = MCPServer(
        **server_kwargs,
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
    parser = argparse.ArgumentParser(description="Run Sparkle's read-only MCP server over stdio or Streamable HTTP.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport. stdio is for Claude Desktop; streamable-http is for Remote MCP clients.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Optional SQLite path. Defaults to %%APPDATA%%\\Sparkle\\clips.db (or SPARKLE_DB_PATH).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host for streamable-http mode.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8002,
        help="Bind port for streamable-http mode.",
    )
    parser.add_argument(
        "--public-url",
        default=None,
        help="Public MCP URL ending in /mcp (or SPARKLE_MCP_PUBLIC_URL).",
    )
    parser.add_argument(
        "--token-env",
        default="SPARKLE_MCP_TOKEN",
        help="Environment variable containing an optional static bearer token for Remote MCP.",
    )
    args = parser.parse_args(argv)
    _configure_logging()
    LOGGER.info("Starting Sparkle MCP server over %s", args.transport)
    if args.transport == "stdio":
        build_server(args.db_path).run(transport="stdio")
        return 0

    try:
        import uvicorn

        from remote_mcp import build_remote_mcp_runtime

        runtime = build_remote_mcp_runtime(
            db_path=args.db_path,
            host=args.host,
            port=args.port,
            public_url=args.public_url,
            static_token=os.environ.get(args.token_env),
        )
        uvicorn.run(
            runtime.app,
            host=args.host,
            port=args.port,
            log_config=None,
            access_log=False,
        )
    except (ImportError, ValueError) as exc:
        LOGGER.error("Remote MCP server could not start: %s", exc)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

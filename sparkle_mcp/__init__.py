"""Read-only MCP integration for Sparkle.

The package deliberately does not import the FastAPI application or the normal
write-enabled repository.  This keeps the Claude Desktop process isolated from
the GUI process and makes the same data/tool layer reusable by a future remote
transport.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"

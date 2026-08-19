"""Read-only SQLite access for the Sparkle MCP server."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class DatabaseAccessError(RuntimeError):
    """A safe, user-facing database access failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def default_database_path() -> Path:
    """Return Sparkle's database path without creating any directories.

    ``SPARKLE_DB_PATH`` is intentionally supported from the first version.  It
    is useful for tests, portable installations, and future per-user remote
    deployments while preserving the existing desktop default.
    """

    configured = os.environ.get("SPARKLE_DB_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()

    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / "Sparkle" / "clips.db"
    return Path.home() / ".sparkle" / "clips.db"


def _readonly_uri(path: Path) -> str:
    try:
        return f"{path.resolve().as_uri()}?mode=ro"
    except ValueError as exc:  # pragma: no cover - defensive for unusual paths
        raise DatabaseAccessError("invalid_database_path", "The Sparkle database path is invalid.") from exc


def open_readonly_connection(path: Path | str | None = None) -> sqlite3.Connection:
    """Open an existing SQLite file with SQLite's URI-level read-only mode."""

    database_path = Path(path).expanduser() if path is not None else default_database_path()
    if not database_path.is_file():
        raise DatabaseAccessError(
            "database_not_found",
            "Sparkle's database was not found. Set SPARKLE_DB_PATH if the database is in another location.",
        )

    try:
        connection = sqlite3.connect(
            _readonly_uri(database_path),
            uri=True,
            timeout=5,
            check_same_thread=False,
        )
    except sqlite3.Error as exc:
        raise DatabaseAccessError("database_unavailable", "Sparkle's database could not be opened.") from exc

    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
    except sqlite3.Error:
        connection.close()
        raise
    return connection


@contextmanager
def read_connection(path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager-like generator used by ``contextlib.contextmanager``."""

    connection = open_readonly_connection(path)
    try:
        yield connection
    finally:
        connection.close()

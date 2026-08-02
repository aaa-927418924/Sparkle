"""First-run setup state for Sparkle.

The setup screen is shown only before the first usable database exists. A
marker is written after the setup form is completed so a later launch can go
straight to the home page. Existing Sparkle databases are treated as already
initialized to avoid interrupting current users.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from paths import get_app_data_dir


SETUP_VERSION = 1
SETUP_MARKER_NAME = ".initial-setup-complete.json"

SETUP_DEFAULTS: dict[str, Any] = {
    "file_save_method": "reference",
    "task_auto_delete": "1w",
    "auto_create_note_on_task": False,
    "auto_create_note_on_project": False,
    "ai_export_enabled": True,
}


def get_setup_marker_path() -> Path:
    return get_app_data_dir() / SETUP_MARKER_NAME


def get_setup_status() -> dict[str, Any]:
    """Return first-run setup state without changing user data."""
    data_dir = get_app_data_dir()
    marker_exists = get_setup_marker_path().is_file()
    existing_database = (data_dir / "clips.db").is_file()
    completed = marker_exists or existing_database
    return {
        "required": not completed,
        "completed": completed,
        "defaults": dict(SETUP_DEFAULTS),
    }


def mark_setup_complete(settings: dict[str, Any] | None = None) -> Path:
    """Write an atomic marker after the initial settings have been saved."""
    marker = get_setup_marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": SETUP_VERSION,
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "settings": {**SETUP_DEFAULTS, **(settings or {})},
    }
    temporary = marker.with_name(f"{marker.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(marker)
    return marker

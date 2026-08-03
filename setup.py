"""First-run setup state for Sparkle.

The setup screen is shown only before the first usable database exists. A
marker is written after the setup form is completed so a later launch can go
straight to the home page. Existing Sparkle databases are treated as already
initialized to avoid interrupting current users.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from paths import get_app_data_dir


SETUP_VERSION = 1
SETUP_MARKER_NAME = ".initial-setup-complete.json"
POST_MIGRATION_ONBOARDING_VERSION = 1
POST_MIGRATION_ONBOARDING_MARKER_NAME = ".post-migration-onboarding.json"
POST_MIGRATION_ONBOARDING_STAGES = {"setup", "extension"}

SETUP_DEFAULTS: dict[str, Any] = {
    "file_save_method": "reference",
    "task_auto_delete": "1w",
    "auto_create_note_on_task": False,
    "auto_create_note_on_project": False,
    "ai_export_enabled": True,
}


def get_setup_marker_path() -> Path:
    return get_app_data_dir() / SETUP_MARKER_NAME


def get_post_migration_onboarding_marker_path() -> Path:
    return get_app_data_dir() / POST_MIGRATION_ONBOARDING_MARKER_NAME


def _write_json_marker(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)
    return path


def _load_saved_settings() -> dict[str, Any]:
    values = dict(SETUP_DEFAULTS)
    database = get_app_data_dir() / "clips.db"
    if not database.is_file():
        return values

    try:
        with sqlite3.connect(str(database), timeout=2) as connection:
            rows = connection.execute("SELECT key, value FROM settings").fetchall()
    except (OSError, sqlite3.DatabaseError):
        return values

    for key, value in rows:
        if key == "file_save_method" and value in {"copy", "reference"}:
            values[key] = value
        elif key == "task_auto_delete" and value in {"3d", "1w", "1m", "never"}:
            values[key] = value
        elif key == "ai_export_enabled" and str(value).lower() in {"true", "false"}:
            values[key] = str(value).lower() == "true"
    return values


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
        "values": _load_saved_settings(),
    }


def get_post_migration_onboarding_status() -> dict[str, Any]:
    marker = get_post_migration_onboarding_marker_path()
    if not marker.is_file():
        return {"required": False, "stage": None}
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"required": False, "stage": None}
    stage = payload.get("stage")
    if stage not in POST_MIGRATION_ONBOARDING_STAGES:
        return {"required": False, "stage": None}
    return {"required": True, "stage": stage}


def ensure_post_migration_onboarding() -> bool:
    """Recover the post-migration flow for migrations completed by older builds."""
    if get_post_migration_onboarding_status().get("required"):
        return False
    if get_setup_marker_path().is_file():
        return False
    if not (get_app_data_dir() / ".migration-complete.json").is_file():
        return False
    begin_post_migration_onboarding()
    return True


def begin_post_migration_onboarding() -> Path:
    return _write_json_marker(
        get_post_migration_onboarding_marker_path(),
        {
            "version": POST_MIGRATION_ONBOARDING_VERSION,
            "stage": "setup",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )


def advance_post_migration_onboarding(stage: str) -> bool:
    if stage not in POST_MIGRATION_ONBOARDING_STAGES:
        return False
    marker = get_post_migration_onboarding_marker_path()
    if not marker.is_file():
        return False
    return bool(
        _write_json_marker(
            marker,
            {
                "version": POST_MIGRATION_ONBOARDING_VERSION,
                "stage": stage,
                "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
        )
    )


def complete_post_migration_onboarding() -> bool:
    marker = get_post_migration_onboarding_marker_path()
    try:
        marker.unlink()
    except FileNotFoundError:
        return False
    return True


def mark_setup_complete(settings: dict[str, Any] | None = None) -> Path:
    """Write an atomic marker after the initial settings have been saved."""
    marker = get_setup_marker_path()
    payload = {
        "version": SETUP_VERSION,
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "settings": {**SETUP_DEFAULTS, **(settings or {})},
    }
    return _write_json_marker(marker, payload)

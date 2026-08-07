"""Maintenance tasks: cleanup of expired data and orphaned cache files.

Cleaners are registered in CLEANERS so new maintenance jobs (e.g. other
cache types) can be added without touching the startup/wiring code.
"""

from typing import Callable, List

from sqlite3 import Connection

from paths import get_thumbnails_dir

THUMBNAILS_DIR = get_thumbnails_dir()

# Default values for app settings (extensible: add new keys here).
SETTING_DEFAULTS = {
    "task_auto_delete": "1w",
    "file_save_method": "reference",  # "copy" or "reference"
    "ai_export_enabled": "true",
    "ai_edit_enabled": "false",
    "titlebar_mode": "custom",  # "custom" or "native"
}

# Maps a setting value to the SQLite date modifier used to compute the
# cutoff. Values not present here mean "do not auto-delete".
AUTO_DELETE_INTERVALS = {
    "3d": "-3 days",
    "1w": "-7 days",
    "1m": "-1 month",
}


def _get_setting(db: Connection, key: str) -> str:
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row:
        return row["value"]
    return SETTING_DEFAULTS.get(key, "")


def cleanup_expired_tasks(db: Connection) -> int:
    """Delete completed tasks whose completion is older than the configured
    retention period. Only completed tasks are affected; unfinished tasks
    are never touched."""
    interval = AUTO_DELETE_INTERVALS.get(_get_setting(db, "task_auto_delete"))
    if not interval:
        return 0
    cur = db.execute(
        "DELETE FROM tasks "
        "WHERE is_done = 1 AND completed_at IS NOT NULL "
        "AND datetime(completed_at) < datetime('now', ?)",
        (interval,),
    )
    return cur.rowcount


def _referenced_thumbnail_names(db: Connection) -> set:
    names = set()
    for row in db.execute(
        "SELECT thumbnail_url FROM clips WHERE thumbnail_url IS NOT NULL"
    ).fetchall():
        url = row["thumbnail_url"] or ""
        name = url.rsplit("/", 1)[-1]
        if name:
            names.add(name)
    return names


def cleanup_orphan_thumbnails(db: Connection) -> int:
    """Delete thumbnail files that are not referenced by any clip.

    Safety: only files inside THUMBNAILS_DIR are considered, and a file is
    deleted only when its basename is absent from the set of referenced
    thumbnails. In-use images are therefore never removed. This reads the
    directory once and issues a single query, minimizing disk access.
    """
    if not THUMBNAILS_DIR.is_dir():
        return 0
    referenced = _referenced_thumbnail_names(db)
    deleted = 0
    for path in THUMBNAILS_DIR.iterdir():
        if not path.is_file():
            continue
        if path.name not in referenced:
            try:
                path.unlink()
                deleted += 1
            except OSError:
                continue
    return deleted


def delete_thumbnail_file(url: str) -> None:
    """Remove a single thumbnail file referenced by a URL, if it exists.

    Used for immediate cleanup when a clip is deleted. Targeted to one file
    so we never scan the whole directory.
    """
    if not url:
        return
    name = url.rsplit("/", 1)[-1]
    if not name:
        return
    path = THUMBNAILS_DIR / name
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def cleanup_orphan_tags(db: Connection) -> int:
    """Delete tags that are not used by any clip. Categories are kept."""
    cur = db.execute(
        "DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM clip_tags)"
    )
    return cur.rowcount


# Registry of cleanup jobs. Add new callables here to extend maintenance
# (e.g. other cache types) without changing startup wiring.
CLEANERS: List[Callable[[Connection], int]] = [
    cleanup_expired_tasks,
    cleanup_orphan_thumbnails,
    cleanup_orphan_tags,
]


def run_maintenance() -> dict:
    """Run all registered cleaners once. Returns a summary of deleted counts."""
    from db import get_connection

    summary = {}
    with get_connection() as conn:
        for cleaner in CLEANERS:
            try:
                summary[cleaner.__name__] = cleaner(conn)
            except Exception:
                summary[cleaner.__name__] = -1
        conn.commit()
    return summary

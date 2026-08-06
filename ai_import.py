"""Close the loop between the AI export and the local database.

The exporter writes a read-only Markdown snapshot; this module detects manual
edits to ``clips.md`` and applies the edited fields back into SQLite.
Deletions, new sections, id changes and immutable fields (``clip_type`` and
``created_at``) are deliberately ignored so the snapshot cannot be used to
destroy data. After every blocked or applied change the snapshot is
regenerated from the database so the file always mirrors the real data.
Local-file clips keep their URL protected because the exporter never exposes
the absolute path.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_export import _ai_edit_enabled
from crud import get_or_create_category, get_or_create_tag
from maintenance import cleanup_orphan_tags
from paths import get_ai_export_dir

POLL_INTERVAL_SECONDS = 2.0

# Markers emitted by the exporter that semantically mean "empty".
_PLACEHOLDERS = {
    "（未設定）",
    "（コメントなし）",
    "（タグなし）",
    "（未分類）",
    "（なし）",
    "（無題）",
    "（不明）",
    "（ローカルファイルの絶対パスは出力していません）",
}

# Bullet labels that carry immutable metadata. The exporter writes these so
# the AI can read them, but edits are never written back to the database.
_PROTECTED_LABELS = {
    "種類",
    "作成日時",
}

_HEADING_RE = re.compile(r"^## \[(\d+)\](?:\s+)?(.*)$", re.MULTILINE)
_BULLET_RE = re.compile(r"^-\s*([^:：]*?)[:：]\s*(.*)$")


_lock = threading.RLock()
_stop_event = threading.Event()
_watcher_thread: Optional[threading.Thread] = None
_last_hash: Dict[str, str] = {}

_last_status: Dict[str, Any] = {
    "enabled": False,
    "last_apply_at": None,
    "applied": 0,
    "skipped_deletes": 0,
    "skipped_new": 0,
    "skipped_protected": 0,
    "last_error": None,
}


# --- Markdown parsing ----------------------------------------------------


def _clean_markdown_inline(value: str) -> str:
    """Strip inline Markdown styling AI tools tend to add to values."""
    text = value.strip()
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text.strip()


def _classify_field(label: str) -> Optional[str]:
    """Map a bullet label to an internal field name; None for unknown."""
    key = _clean_markdown_inline(label).strip().lower()
    if not key:
        return None
    if key in {"url", "link"} or "リンク" in key:
        return "url"
    if key == "comment" or "コメント" in key:
        return "comment"
    if key in {"category", "カテゴリー"} or "カテゴリ" in key:
        return "category"
    if key in {"tag", "tags"} or "タグ" in key:
        return "tags"
    if key.startswith("favorite") or "お気に入り" in key:
        return "favorite"
    if key == "title" or "タイトル" in key:
        return "title"
    if key in {"clip_type", "type"} or "種類" in key or "種別" in key:
        return "clip_type"
    if key in {"created_at", "created"} or "作成日時" in key:
        return "created_at"
    return None


def _empty_or_none(value: str) -> Optional[str]:
    text = _clean_markdown_inline(value)
    if not text or text in _PLACEHOLDERS:
        return None
    return text


def _parse_tags(value: str) -> List[str]:
    parts = [part.strip() for part in re.split(r"[,、]", value)]
    return [part for part in parts if part and _empty_or_none(part) is not None]


def _parse_favorite(value: str) -> Optional[int]:
    text = _clean_markdown_inline(value).strip().lower()
    if text in {"はい", "1", "true", "あり", "on"}:
        return 1
    if text in {"いいえ", "0", "false", "なし", "off"}:
        return 0
    return None


def parse_clips_md(text: str) -> List[Dict[str, Any]]:
    """Parse the exported clips Markdown into per-clip edit candidates.

    Every item carries the section ``id`` and only the fields that appear in
    the written snapshot. Fields that are absent are left unchanged by the
    importer. A ``None`` value means "explicitly cleared".
    """
    edits: List[Dict[str, Any]] = []
    matches = list(_HEADING_RE.finditer(text))
    for index, heading in enumerate(matches):
        clip_id = int(heading.group(1))
        title = _clean_markdown_inline(heading.group(2).strip())
        body = (
            text[heading.end(): matches[index + 1].start()]
            if index + 1 < len(matches)
            else text[heading.end():]
        )

        edit: Dict[str, Any] = {"id": clip_id}
        if title and title not in _PLACEHOLDERS:
            edit["title"] = title

        protected: Dict[str, Any] = {}
        for line in body.splitlines():
            bullet = _BULLET_RE.match(line.strip())
            if not bullet:
                continue
            field = _classify_field(bullet.group(1))
            if field in {"clip_type", "created_at"}:
                protected[field] = _clean_markdown_inline(bullet.group(2)).strip()
                continue
            if field is None:
                continue
            raw = bullet.group(2).strip()
            if field == "url":
                edit["url"] = _empty_or_none(raw) or ""
            elif field == "comment":
                edit["comment"] = _empty_or_none(raw)
            elif field == "category":
                edit["category"] = _empty_or_none(raw)
            elif field == "tags":
                edit["tags"] = _parse_tags(raw)
            elif field == "favorite":
                favorite = _parse_favorite(raw)
                if favorite is not None:
                    edit["favorite"] = favorite
        if protected:
            edit["_protected"] = protected
        edits.append(edit)
    return edits


# --- database application ---------------------------------------------------


def _apply_edit(db: sqlite3.Connection, edit: Dict[str, Any]) -> bool:
    clip_id = edit["id"]
    row = db.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if not row:
        return False

    changed = False

    if "title" in edit:
        title = edit["title"] or None
        if (title or None) != (row["title"] or None):
            db.execute("UPDATE clips SET title = ? WHERE id = ?", (title, clip_id))
            changed = True

    if "comment" in edit:
        comment = edit["comment"]
        if (comment or None) != (row["comment"] or None):
            db.execute("UPDATE clips SET comment = ? WHERE id = ?", (comment, clip_id))
            changed = True

    if "category" in edit:
        category_name = edit["category"]
        old_category = db.execute(
            "SELECT c.name FROM categories c WHERE c.id = ?", (row["category_id"],)
        ).fetchone()
        old_name = old_category["name"] if old_category else None
        if (category_name or None) != (old_name or None):
            category_id = (
                get_or_create_category(db, category_name) if category_name else None
            )
            if category_id != row["category_id"]:
                db.execute(
                    "UPDATE clips SET category_id = ? WHERE id = ?", (category_id, clip_id)
                )
                changed = True

    if "tags" in edit:
        tag_names = edit["tags"]
        old_tags = {
            t["name"]
            for t in db.execute(
                "SELECT t.name FROM clip_tags ct JOIN tags t ON t.id = ct.tag_id "
                "WHERE ct.clip_id = ?",
                (clip_id,),
            ).fetchall()
        }
        if set(tag_names) != old_tags:
            tag_ids = [get_or_create_tag(db, name) for name in tag_names]
            db.execute("DELETE FROM clip_tags WHERE clip_id = ?", (clip_id,))
            for tag_id in tag_ids:
                db.execute(
                    "INSERT OR IGNORE INTO clip_tags(clip_id, tag_id) VALUES (?, ?)",
                    (clip_id, tag_id),
                )
            cleanup_orphan_tags(db)
            changed = True

    if "favorite" in edit:
        favorite = edit["favorite"]
        if favorite != (row["is_favorite"] or 0):
            db.execute(
                "UPDATE clips SET is_favorite = ? WHERE id = ?", (favorite, clip_id)
            )
            changed = True

    # Local-file clips keep their URL: the exporter never prints the real path.
    if "url" in edit and (row["clip_type"] or "url") != "local":
        url = edit["url"]
        if url and url != (row["url"] or ""):
            db.execute("UPDATE clips SET url = ? WHERE id = ?", (url, clip_id))
            changed = True

    return changed


def apply_edits(edits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Write the parsed edits back into the database.

    Returns a summary with the number of changed clips, ids that were blocked
    as new sections, clips that were absent from the snapshot (blocked
    deletions), and immutable fields that were edited (blocked too).
    """
    from db import get_connection

    seen_ids = {edit["id"] for edit in edits}
    result = {"applied": 0, "skipped_new": 0, "skipped_deletes": 0, "skipped_protected": 0}

    with get_connection() as db:
        existing_ids = {r["id"] for r in db.execute("SELECT id FROM clips").fetchall()}
        changed_any = False
        for edit in edits:
            protected = edit.pop("_protected", {})
            if edit["id"] not in existing_ids:
                result["skipped_new"] += 1
                continue
            if protected:
                row = db.execute(
                    "SELECT clip_type, created_at FROM clips WHERE id = ?", (edit["id"],)
                ).fetchone()
                if row is not None:
                    for field, value in protected.items():
                        if field == "clip_type":
                            expected = "local" if (row["clip_type"] or "url") == "local" else "url"
                            candidate = (
                                "local"
                                if value in {"ローカルファイル", "local", "ローカル", "file"}
                                else "url"
                            )
                        else:
                            expected = row["created_at"] or ""
                            candidate = value
                        if candidate != expected:
                            result["skipped_protected"] += 1
            if _apply_edit(db, edit):
                result["applied"] += 1
                changed_any = True
        if changed_any:
            db.commit()
        result["skipped_deletes"] = len(existing_ids - seen_ids)
    return result


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _apply_file(target: Path) -> Dict[str, Any]:
    text = target.read_text(encoding="utf-8")
    edits = parse_clips_md(text)
    if not edits:
        return {"applied": 0, "skipped_new": 0, "skipped_deletes": 0, "skipped_protected": 0}

    # Keep a copy of the AI-edited file before the importer normalizes it.
    try:
        shutil.copy2(target, target.with_name("clips.md.bak"))
    except OSError:
        pass

    result = apply_edits(edits)
    if any(result[k] for k in ("applied", "skipped_deletes", "skipped_new", "skipped_protected")):
        # Normalize the snapshot so the file mirrors the DB, which restores
        # deleted sections, removes invented ids and reverts protected fields.
        from ai_export import export_database

        export_database()
    return result


def _watch_loop() -> None:
    while not _stop_event.is_set():
        try:
            if not _ai_edit_enabled():
                _last_hash.clear()
                _stop_event.wait(POLL_INTERVAL_SECONDS)
                continue

            clips_md = get_ai_export_dir() / "clips.md"
            if clips_md.is_file():
                current_hash = _file_hash(clips_md)
                if current_hash and current_hash != _last_hash.get("clips.md"):
                    result = _apply_file(clips_md)
                    _last_hash["clips.md"] = _file_hash(clips_md)
                    with _lock:
                        if result["applied"]:
                            _last_status["last_apply_at"] = (
                                datetime.now().astimezone().isoformat(timespec="seconds")
                            )
                        _last_status["applied"] += result["applied"]
                        _last_status["skipped_new"] += result["skipped_new"]
                        _last_status["skipped_deletes"] += result["skipped_deletes"]
                        _last_status["skipped_protected"] += result["skipped_protected"]
        except Exception as exc:
            with _lock:
                _last_status["last_error"] = str(exc)
        _stop_event.wait(POLL_INTERVAL_SECONDS)


def start_watcher() -> None:
    """Start the background poller if it is not running already."""
    global _watcher_thread
    with _lock:
        if _watcher_thread is not None and _watcher_thread.is_alive():
            return
        _stop_event.clear()
        _watcher_thread = threading.Thread(
            target=_watch_loop, name="ai-import-watcher", daemon=True
        )
        _watcher_thread.start()


def stop_watcher() -> None:
    _stop_event.set()
    if _watcher_thread is not None:
        _watcher_thread.join(timeout=1)


def get_edit_status() -> Dict[str, Any]:
    with _lock:
        result = dict(_last_status)
    result["enabled"] = _ai_edit_enabled()
    return result

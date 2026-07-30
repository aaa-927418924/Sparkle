"""Generate AI-friendly Markdown snapshots of the local database.

The exporter deliberately writes a text projection instead of exposing the
SQLite file. It only reads the database and never performs migrations or
mutations. Automatic exports are debounced so a burst of CRUD operations
produces one coherent snapshot.
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from paths import get_ai_export_dir


EXPORT_DELAY_SECONDS = 1.0
EXPORT_FILENAMES = (
    "README.md",
    "index.md",
    "all.md",
    "clips.md",
    "notes.md",
    "tasks.md",
    "projects.md",
    "taxonomy.md",
)

_timer_lock = threading.RLock()
_export_lock = threading.Lock()
_timer: Optional[threading.Timer] = None
_pending = False
_exporting = False
_last_status: Dict[str, Any] = {
    "last_exported_at": None,
    "snapshot_id": None,
    "last_error": None,
}


def _db_path() -> Path:
    # Import lazily so db.py can call request_export() without a module cycle.
    from db import DB_PATH

    return DB_PATH


def _open_readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise FileNotFoundError(f"データベースが見つかりません: {db_path}")
    connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _setting_enabled(connection: sqlite3.Connection) -> bool:
    try:
        row = connection.execute(
            "SELECT value FROM settings WHERE key = 'ai_export_enabled'"
        ).fetchone()
    except sqlite3.OperationalError:
        return True
    if row is None or row[0] is None:
        return True
    return str(row[0]).strip().lower() not in {"0", "false", "off", "no"}


def _plain(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _one_line(value: Any, fallback: str = "（未設定）") -> str:
    text = " ".join(_plain(value).splitlines()).strip()
    return text or fallback


def _fence(text: Any) -> str:
    body = _plain(text)
    if not body:
        return "（本文なし）"
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", body)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{body}\n{fence}"


def _bullet(label: str, value: Any, *, fallback: str = "") -> str:
    text = _one_line(value, fallback=fallback) if fallback else _plain(value)
    return f"- {label}: {text or '（未設定）'}"


def _rows(connection: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return connection.execute(sql, tuple(params)).fetchall()


def _build_snapshot(connection: sqlite3.Connection, snapshot_id: str, generated_at: str) -> Dict[str, str]:
    categories = {
        row["id"]: row["name"]
        for row in _rows(connection, "SELECT id, name FROM categories ORDER BY name")
    }
    tags = {
        row["id"]: row["name"]
        for row in _rows(connection, "SELECT id, name FROM tags ORDER BY name")
    }
    clip_tags: Dict[int, list[str]] = {}
    for row in _rows(
        connection,
        "SELECT clip_id, tag_id FROM clip_tags ORDER BY clip_id, tag_id",
    ):
        clip_tags.setdefault(row["clip_id"], []).append(_one_line(tags.get(row["tag_id"])))

    project_clips: Dict[int, list[int]] = {}
    for row in _rows(
        connection,
        "SELECT project_id, clip_id FROM project_clips ORDER BY project_id, clip_id",
    ):
        project_clips.setdefault(row["project_id"], []).append(row["clip_id"])
    project_notes: Dict[int, list[int]] = {}
    for row in _rows(
        connection,
        "SELECT project_id, note_id FROM project_notes ORDER BY project_id, note_id",
    ):
        project_notes.setdefault(row["project_id"], []).append(row["note_id"])
    note_clips: Dict[int, list[int]] = {}
    for row in _rows(connection, "SELECT note_id, clip_id FROM note_clips ORDER BY note_id, clip_id"):
        note_clips.setdefault(row["note_id"], []).append(row["clip_id"])
    task_notes: Dict[int, list[int]] = {}
    for row in _rows(connection, "SELECT task_id, note_id FROM task_notes ORDER BY task_id, note_id"):
        task_notes.setdefault(row["task_id"], []).append(row["note_id"])

    clips = _rows(
        connection,
        "SELECT id, url, title, comment, category_id, is_favorite, created_at, "
        "clip_type, project_id FROM clips ORDER BY created_at DESC, id DESC",
    )
    notes = _rows(
        connection,
        "SELECT id, title, body, created_at, updated_at FROM notes "
        "ORDER BY updated_at DESC, id DESC",
    )
    tasks = _rows(
        connection,
        "SELECT id, title, is_done, clip_id, due_date, priority, created_at, "
        "completed_at, project_id FROM tasks ORDER BY is_done, created_at DESC, id DESC",
    )
    projects = _rows(
        connection,
        "SELECT id, name, description, is_done, created_at FROM projects "
        "ORDER BY is_done, created_at DESC, id DESC",
    )

    clip_titles = {row["id"]: _one_line(row["title"], "（無題）") for row in clips}
    note_titles = {row["id"]: _one_line(row["title"], "（無題）") for row in notes}
    task_titles = {row["id"]: _one_line(row["title"], "（無題）") for row in tasks}
    project_titles = {row["id"]: _one_line(row["name"], "（無題）") for row in projects}

    header = f"<!-- snapshot_id: {snapshot_id} -->\n<!-- generated_at: {generated_at} -->\n"

    clip_sections = ["# クリップ一覧", "", f"生成日時: {generated_at}", ""]
    for row in clips:
        local_clip = (row["clip_type"] or "url") == "local"
        clip_sections.extend(
            [
                f"## [{row['id']}] {clip_titles[row['id']]}\n",
                _bullet("種類", "ローカルファイル" if local_clip else "URL"),
                _bullet("URL", "（ローカルファイルの絶対パスは出力していません）" if local_clip else row["url"]),
                _bullet("コメント", row["comment"], fallback="（コメントなし）"),
                _bullet("カテゴリ", categories.get(row["category_id"]), fallback="（未分類）"),
                _bullet("タグ", ", ".join(clip_tags.get(row["id"], [])), fallback="（タグなし）"),
                _bullet("お気に入り", "はい" if row["is_favorite"] else "いいえ"),
                _bullet("プロジェクトID", row["project_id"], fallback="（なし）"),
                _bullet("作成日時", row["created_at"]),
                "",
            ]
        )
    clips_md = header + "\n".join(clip_sections).rstrip() + "\n"

    note_sections = ["# ノート一覧", "", f"生成日時: {generated_at}", ""]
    for row in notes:
        linked_clips = ", ".join(
            f"[{clip_id}] {clip_titles.get(clip_id, '（不明）')}"
            for clip_id in note_clips.get(row["id"], [])
        )
        note_sections.extend(
            [
                f"## [{row['id']}] {note_titles[row['id']]}\n",
                _bullet("作成日時", row["created_at"]),
                _bullet("更新日時", row["updated_at"]),
                _bullet("関連クリップ", linked_clips, fallback="（なし）"),
                "### 本文",
                _fence(row["body"]),
                "",
            ]
        )
    notes_md = header + "\n".join(note_sections).rstrip() + "\n"

    task_sections = ["# タスク一覧", "", f"生成日時: {generated_at}", ""]
    for row in tasks:
        linked_notes = ", ".join(
            f"[{note_id}] {note_titles.get(note_id, '（不明）')}"
            for note_id in task_notes.get(row["id"], [])
        )
        task_sections.extend(
            [
                f"## [{row['id']}] {task_titles[row['id']]}\n",
                _bullet("状態", "完了" if row["is_done"] else "未完了"),
                _bullet("期限", row["due_date"], fallback="（未設定）"),
                _bullet("優先度", row["priority"], fallback="（未設定）"),
                _bullet("関連クリップ", f"[{row['clip_id']}] {clip_titles.get(row['clip_id'], '（不明）')}" if row["clip_id"] else "", fallback="（なし）"),
                _bullet("関連ノート", linked_notes, fallback="（なし）"),
                _bullet("プロジェクトID", row["project_id"], fallback="（なし）"),
                _bullet("作成日時", row["created_at"]),
                _bullet("完了日時", row["completed_at"], fallback="（未完了）"),
                "",
            ]
        )
    tasks_md = header + "\n".join(task_sections).rstrip() + "\n"

    project_sections = ["# プロジェクト一覧", "", f"生成日時: {generated_at}", ""]
    for row in projects:
        linked_clips = ", ".join(
            f"[{clip_id}] {clip_titles.get(clip_id, '（不明）')}"
            for clip_id in project_clips.get(row["id"], [])
        )
        linked_notes = ", ".join(
            f"[{note_id}] {note_titles.get(note_id, '（不明）')}"
            for note_id in project_notes.get(row["id"], [])
        )
        project_sections.extend(
            [
                f"## [{row['id']}] {project_titles[row['id']]}\n",
                _bullet("状態", "完了" if row["is_done"] else "進行中"),
                _bullet("作成日時", row["created_at"]),
                _bullet("関連クリップ", linked_clips, fallback="（なし）"),
                _bullet("関連ノート", linked_notes, fallback="（なし）"),
                "### 説明",
                _fence(row["description"]),
                "",
            ]
        )
    projects_md = header + "\n".join(project_sections).rstrip() + "\n"

    taxonomy_sections = ["# カテゴリとタグ", "", f"生成日時: {generated_at}", "", "## カテゴリ"]
    taxonomy_sections.extend(f"- [{row['id']}] {_one_line(row['name'])}" for row in _rows(connection, "SELECT id, name FROM categories ORDER BY name"))
    taxonomy_sections.extend(["", "## タグ"])
    taxonomy_sections.extend(f"- [{row['id']}] {_one_line(row['name'])}" for row in _rows(connection, "SELECT id, name FROM tags ORDER BY name"))
    taxonomy_md = header + "\n".join(taxonomy_sections).rstrip() + "\n"

    counts = {
        "クリップ": len(clips),
        "ノート": len(notes),
        "タスク": len(tasks),
        "プロジェクト": len(projects),
        "カテゴリ": len(categories),
        "タグ": len(tags),
    }
    count_lines = "\n".join(f"- {label}: {count}" for label, count in counts.items())
    index_md = (
        header
        + "# AIClipSaveApp データインデックス\n\n"
        + f"生成日時: {generated_at}\n\n"
        + "このフォルダはAIClipSaveAppの読み取り用Markdownスナップショットです。"
        "まずこのファイルを読み、必要に応じて個別ファイルを参照してください。\n\n"
        + "## 件数\n"
        + count_lines
        + "\n\n## ファイル\n"
        + "- `clips.md`: 保存したクリップ、URL、コメント、タグ\n"
        + "- `notes.md`: ノート本文と関連情報\n"
        + "- `tasks.md`: タスクの状態、期限、優先度\n"
        + "- `projects.md`: プロジェクトと関連項目\n"
        + "- `taxonomy.md`: カテゴリとタグ\n"
    )
    readme_md = (
        header
        + "# AIClipSaveApp AIエクスポート\n\n"
        + "このフォルダには、AIが読み取るためのMarkdown形式のデータが保存されています。\n\n"
        + "- SQLiteデータベース本体は含まれていません。\n"
        + "- ローカルファイルの絶対パスなど、アプリ内部の技術情報は含まれていません。\n"
        + "- `index.md`を入口にして、必要なファイルだけを読み取ってください。\n"
        + "- 通常のClaude、ChatGPT、Geminiでは`all.md`をアップロードできます。\n"
    )
    all_md = (
        header
        + "# AIClipSaveApp 全データ\n\n"
        + f"生成日時: {generated_at}\n\n"
        + "\n\n---\n\n".join((clips_md, notes_md, tasks_md, projects_md, taxonomy_md))
    )

    return {
        "README.md": readme_md,
        "index.md": index_md,
        "all.md": all_md,
        "clips.md": clips_md,
        "notes.md": notes_md,
        "tasks.md": tasks_md,
        "projects.md": projects_md,
        "taxonomy.md": taxonomy_md,
    }


def export_database(
    db_path: Optional[Path] = None,
    export_dir: Optional[Path] = None,
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """Write one consistent Markdown snapshot and return its status."""
    target_db = db_path or _db_path()
    target_dir = export_dir or get_ai_export_dir()
    with _export_lock:
        with _open_readonly(target_db) as connection:
            if not force and not _setting_enabled(connection):
                return {
                    "enabled": False,
                    "path": str(target_dir),
                    "files": list(EXPORT_FILENAMES),
                }
            connection.execute("BEGIN")
            generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
            snapshot_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            contents = _build_snapshot(connection, snapshot_id, generated_at)

        target_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in contents.items():
            temporary = target_dir / f".{filename}.{uuid.uuid4().hex}.tmp"
            try:
                temporary.write_text(content, encoding="utf-8", newline="\n")
                os.replace(temporary, target_dir / filename)
            finally:
                temporary.unlink(missing_ok=True)

    result = {
        "enabled": True,
        "path": str(target_dir),
        "files": list(contents),
        "snapshot_id": snapshot_id,
        "last_exported_at": generated_at,
        "last_error": None,
    }
    with _timer_lock:
        _last_status.update(result)
    return result


def _run_scheduled_export() -> None:
    global _pending, _exporting, _timer
    with _timer_lock:
        _timer = None
        if _exporting:
            _pending = True
            return
        _pending = False
        _exporting = True
    try:
        result = export_database()
        with _timer_lock:
            _last_status.update(result)
    except Exception as exc:
        with _timer_lock:
            _last_status["last_error"] = str(exc)
    finally:
        with _timer_lock:
            _exporting = False
            rerun = _pending
        if rerun:
            request_export()


def request_export(delay: float = EXPORT_DELAY_SECONDS) -> None:
    """Schedule a debounced export after a successful DB commit."""
    global _pending, _timer
    with _timer_lock:
        _pending = True
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(delay, _run_scheduled_export)
        _timer.daemon = True
        _timer.start()


def export_now() -> Dict[str, Any]:
    return export_database(force=True)


def get_status() -> Dict[str, Any]:
    target_dir = get_ai_export_dir()
    with _timer_lock:
        result = dict(_last_status)
    result.update(
        {
            "enabled": True,
            "path": str(target_dir),
            "files": list(EXPORT_FILENAMES),
        }
    )
    try:
        with _open_readonly(_db_path()) as connection:
            result["enabled"] = _setting_enabled(connection)
    except Exception as exc:
        result["last_error"] = str(exc)
    return result


def open_export_folder() -> Dict[str, Any]:
    target_dir = get_ai_export_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(target_dir))
    elif os.name == "posix":
        subprocess.Popen(["xdg-open", str(target_dir)])
    return {"ok": True, "path": str(target_dir)}

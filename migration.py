"""One-click migration from the former application layout to Sparkle.

The migration is intentionally kept separate from the normal database startup.
The desktop entry point can show the migration window before the new database
is initialized, then start the normal application only after the user confirms.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from paths import APP_NAME as NEW_APP_NAME, LEGACY_APP_NAME, LEGACY_DISPLAY_NAME

MIGRATION_VERSION = 1
_migration_lock = threading.RLock()


def _named_app_data_dir(name: str) -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / name
    return Path.home() / f".{name.lower()}"


def new_app_data_dir() -> Path:
    return _named_app_data_dir(NEW_APP_NAME)


def legacy_app_data_dir() -> Path:
    return _named_app_data_dir(LEGACY_APP_NAME)


def new_export_dir() -> Path:
    return Path.home() / "Documents" / NEW_APP_NAME / "ai-export"


def legacy_export_dir() -> Path:
    return Path.home() / "Documents" / LEGACY_APP_NAME / "ai-export"


def _project_dir() -> Path:
    return Path(__file__).resolve().parent


def _known_artifact_roots() -> list[Path]:
    roots = {
        _project_dir(),
        _project_dir() / "dist",
    }
    if getattr(sys, "frozen", False):
        roots.add(Path(sys.executable).resolve().parent)
    return [root for root in roots if root.exists()]


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            key = str(path.resolve()).casefold()
        except OSError:
            key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _legacy_backup_files() -> list[Path]:
    roots = [
        Path.home() / "Documents",
        Path.home() / "Downloads",
        *_known_artifact_roots(),
    ]
    candidates: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        candidates.extend(root.glob(f"{LEGACY_APP_NAME}-backup-*.zip"))
        candidates.extend(root.glob(f"{LEGACY_APP_NAME}-*.db"))
    return [path for path in _unique_paths(candidates) if path.is_file()]


def _legacy_executable_files() -> list[Path]:
    candidates: list[Path] = []
    for root in _known_artifact_roots():
        candidates.extend(root.glob(f"{LEGACY_APP_NAME}*.exe"))
    current_executable = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None
    return [
        path
        for path in _unique_paths(candidates)
        if path.is_file() and (current_executable is None or path.resolve() != current_executable)
    ]


def _legacy_autostart_value() -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, LEGACY_APP_NAME)
        return str(value) if value else None
    except (FileNotFoundError, OSError):
        return None


def _path_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*") if path.is_dir() else ():
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def _file_count(path: Path) -> int:
    if path.is_file():
        return 1
    return sum(1 for child in path.rglob("*") if child.is_file()) if path.is_dir() else 0


def _item(kind: str, label: str, source: Path, target: Path, action: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "label": label,
        "source": str(source),
        "target": str(target),
        "action": action,
        "files": _file_count(source),
        "bytes": _path_size(source),
    }


def _target_has_user_data(path: Path) -> bool:
    if not path.exists():
        return False
    allowed_runtime_files = {"app.log", "stdio.log"}
    # Normal startup may create these empty upload buckets before migration.
    allowed_upload_dirs = {"local", "thumbnails"}

    def is_empty_directory(directory: Path) -> bool:
        try:
            return directory.is_dir() and not any(directory.iterdir())
        except OSError:
            return False

    def is_runtime_upload_directory(directory: Path) -> bool:
        if not directory.is_dir():
            return False
        try:
            children = list(directory.iterdir())
        except OSError:
            return False
        return all(
            child.is_dir()
            and child.name in allowed_upload_dirs
            and is_empty_directory(child)
            for child in children
        )

    for child in path.iterdir():
        if child.name in allowed_runtime_files and child.is_file():
            continue
        if child.name == "uploads" and is_runtime_upload_directory(child):
            continue
        return True
    return False


def _data_integrity_ok(path: Path) -> tuple[bool, str]:
    database = path / "clips.db"
    if not database.is_file():
        return False, "clips.dbが見つかりません"
    connection = None
    try:
        connection = sqlite3.connect(str(database), timeout=5)
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or str(result[0]).lower() != "ok":
            return False, f"SQLite整合性チェックに失敗しました: {result[0] if result else 'unknown'}"
    except (OSError, sqlite3.DatabaseError) as exc:
        return False, f"SQLiteを検証できませんでした: {exc}"
    finally:
        if connection is not None:
            connection.close()
    return True, "ok"


def _replace_generated_branding(export_root: Path) -> None:
    if not export_root.is_dir():
        return
    for markdown in export_root.rglob("*.md"):
        try:
            content = markdown.read_text(encoding="utf-8")
            content = content.replace(LEGACY_APP_NAME, NEW_APP_NAME)
            content = content.replace(LEGACY_DISPLAY_NAME, NEW_APP_NAME)
            markdown.write_text(content, encoding="utf-8", newline="\n")
        except (OSError, UnicodeError):
            continue


def get_migration_status() -> dict[str, Any]:
    """Return detected legacy items without changing the filesystem."""
    with _migration_lock:
        old_data = legacy_app_data_dir()
        old_export = legacy_export_dir().parent
        new_data = new_app_data_dir()
        new_export = new_export_dir().parent
        items: list[dict[str, Any]] = []

        if old_data.is_dir() and any(old_data.iterdir()):
            items.append(_item("app-data", "アプリデータ", old_data, new_data, "move"))
        if old_export.is_dir() and any(old_export.iterdir()):
            items.append(_item("markdown", "Markdownエクスポート", old_export, new_export, "move"))
        for backup in _legacy_backup_files():
            target = backup.with_name(backup.name.replace(LEGACY_APP_NAME, NEW_APP_NAME, 1))
            items.append(_item("backup", "旧バックアップ", backup, target, "rename"))
        for executable in _legacy_executable_files():
            target = executable.with_name(executable.name.replace(LEGACY_APP_NAME, NEW_APP_NAME, 1))
            items.append(_item("legacy-executable", "旧アプリ/アップデータ", executable, target, "remove"))
        if _legacy_autostart_value():
            items.append({
                "kind": "autostart",
                "label": "旧スタートアップ登録",
                "source": LEGACY_APP_NAME,
                "target": NEW_APP_NAME,
                "action": "update",
                "files": 0,
                "bytes": 0,
            })

        conflict = _target_has_user_data(new_data) or (
            new_export.exists() and any(new_export.iterdir())
        )
        return {
            "required": bool(items),
            "conflict": conflict,
            "items": items,
            "new_app_name": NEW_APP_NAME,
            "legacy_app_name": LEGACY_APP_NAME,
            "new_data": str(new_data),
            "new_export": str(new_export),
        }


def _copy_tree_contents(source: Path, target: Path) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for child in source.iterdir():
        destination = target / child.name
        if child.is_dir():
            shutil.copytree(child, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(child, destination)
        copied.append(destination)
    return copied


def _remove_copied_paths(paths: Iterable[Path]) -> None:
    for path in reversed(list(paths)):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        except OSError:
            continue


def _rename_without_overwrite(source: Path, target: Path) -> Path:
    destination = target
    suffix = 1
    while destination.exists():
        destination = target.with_name(f"{target.stem}-{suffix}{target.suffix}")
        suffix += 1
    source.rename(destination)
    return destination


def _migrate_autostart(executable_path: str | None) -> None:
    if os.name != "nt" or not _legacy_autostart_value():
        return
    import winreg

    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    command = executable_path or str(Path(sys.executable).resolve())
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, NEW_APP_NAME, 0, winreg.REG_SZ, f'"{command}" --hidden')
        try:
            winreg.DeleteValue(key, LEGACY_APP_NAME)
        except FileNotFoundError:
            pass


def _write_marker(target: Path, moved_items: list[dict[str, Any]]) -> None:
    target.mkdir(parents=True, exist_ok=True)
    marker = target / ".migration-complete.json"
    marker.write_text(
        json.dumps(
            {
                "version": MIGRATION_VERSION,
                "from": LEGACY_APP_NAME,
                "to": NEW_APP_NAME,
                "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "items": moved_items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
        newline="\n",
    )


def run_migration(executable_path: str | None = None) -> dict[str, Any]:
    """Move legacy data and rename known legacy artifacts after confirmation."""
    with _migration_lock:
        status = get_migration_status()
        if not status["required"]:
            return {"ok": True, "already_done": True, "message": "移行対象はありません。"}
        if status["conflict"]:
            return {
                "ok": False,
                "error": "Sparkle側に既存データがあるため、自動上書きを中止しました。",
                "status": status,
            }

        old_data = legacy_app_data_dir()
        new_data = new_app_data_dir()
        old_export_root = legacy_export_dir().parent
        new_export_root = new_export_dir().parent
        moved: list[dict[str, Any]] = []
        warnings: list[str] = []
        copied_data: list[Path] = []
        copied_export: list[Path] = []

        try:
            if old_data.is_dir() and any(old_data.iterdir()):
                ok, reason = _data_integrity_ok(old_data)
                if not ok:
                    return {"ok": False, "error": f"旧データを移行できません: {reason}"}
                copied_data = _copy_tree_contents(old_data, new_data)
                ok, reason = _data_integrity_ok(new_data)
                if not ok:
                    _remove_copied_paths(copied_data)
                    return {"ok": False, "error": f"移行後のデータ検証に失敗しました: {reason}"}
                moved.append({"kind": "app-data", "source": str(old_data), "target": str(new_data)})

            if old_export_root.is_dir() and any(old_export_root.iterdir()):
                copied_export = _copy_tree_contents(old_export_root, new_export_root)
                _replace_generated_branding(new_export_root)
                moved.append({"kind": "markdown", "source": str(old_export_root), "target": str(new_export_root)})

            _write_marker(new_data, moved)

            for backup in _legacy_backup_files():
                try:
                    target = backup.with_name(backup.name.replace(LEGACY_APP_NAME, NEW_APP_NAME, 1))
                    destination = _rename_without_overwrite(backup, target)
                    moved.append({"kind": "backup", "source": str(backup), "target": str(destination)})
                except OSError as exc:
                    warnings.append(f"バックアップ名を変更できませんでした: {backup} ({exc})")

            for executable in _legacy_executable_files():
                try:
                    executable.unlink()
                    moved.append({"kind": "legacy-executable", "source": str(executable), "target": None})
                except OSError as exc:
                    warnings.append(f"旧アプリを削除できませんでした: {executable} ({exc})")

            try:
                _migrate_autostart(executable_path)
                if _legacy_autostart_value() is None:
                    moved.append({"kind": "autostart", "source": LEGACY_APP_NAME, "target": NEW_APP_NAME})
            except OSError as exc:
                warnings.append(f"スタートアップ登録を更新できませんでした: {exc}")

            if old_data.is_dir():
                try:
                    shutil.rmtree(old_data)
                except OSError as exc:
                    warnings.append(f"旧データを削除できませんでした: {old_data} ({exc})")
            if old_export_root.is_dir():
                try:
                    shutil.rmtree(old_export_root)
                except OSError as exc:
                    warnings.append(f"旧Markdownを削除できませんでした: {old_export_root} ({exc})")
            return {
                "ok": True,
                "message": "Sparkleへの移行が完了しました。",
                "moved": moved,
                "warnings": warnings,
                "status": get_migration_status(),
            }
        except (OSError, shutil.Error, sqlite3.DatabaseError) as exc:
            _remove_copied_paths(copied_export)
            _remove_copied_paths(copied_data)
            return {
                "ok": False,
                "error": f"移行中にエラーが発生しました: {exc}",
                "moved": moved,
                "warnings": warnings,
            }

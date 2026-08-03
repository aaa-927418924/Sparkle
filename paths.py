"""アプリの保存先パスを解決するユーティリティ。

- get_app_data_dir(): 書き込み可能なデータ保存先(DB・アップロードファイル等)。
  Windowsでは %APPDATA%\\Sparkle、それ以外では ~/.sparkle を使う。
- get_resource_dir(): 読み取り専用の同梱リソース(frontend等)の場所。
  PyInstallerでexe化されている場合は展開先(_MEIPASS)、
  通常のpython実行時はプロジェクトディレクトリを返す。
- get_exe_dir(): 実行中のexe(またはスクリプト)自身があるフォルダ。
  旧バージョンのデータを探すために使う。
"""

import os
import sys
from pathlib import Path

APP_NAME = "Sparkle"
LEGACY_APP_NAME = "AIClipSaveApp"
LEGACY_DISPLAY_NAME = "AI Clip Save App"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_app_data_dir() -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        base = Path(appdata) / APP_NAME
    else:
        base = Path.home() / f".{APP_NAME.lower()}"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_uploads_dir() -> Path:
    d = get_app_data_dir() / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_thumbnails_dir() -> Path:
    d = get_uploads_dir() / "thumbnails"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_local_files_dir() -> Path:
    d = get_uploads_dir() / "local"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_profile_dir() -> Path:
    d = get_uploads_dir() / "profile"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_ai_export_dir() -> Path:
    """Return the human-readable export directory intended for AI tools."""
    documents = Path.home() / "Documents"
    d = documents / APP_NAME / "ai-export"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _named_app_data_dir(name: str) -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / name
    return Path.home() / f".{name.lower()}"


def get_legacy_app_data_dir() -> Path:
    """Return the former application's data directory without creating it."""
    return _named_app_data_dir(LEGACY_APP_NAME)


def get_legacy_ai_export_dir() -> Path:
    """Return the former Markdown export directory without creating it."""
    return Path.home() / "Documents" / LEGACY_APP_NAME / "ai-export"


def get_resource_dir() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def get_exe_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

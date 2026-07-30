"""アプリの保存先パスを解決するユーティリティ。

- get_app_data_dir(): 書き込み可能なデータ保存先(DB・アップロードファイル等)。
  Windowsでは %APPDATA%\\AIClipSaveApp、それ以外では ~/.aiclipsaveapp を使う。
- get_resource_dir(): 読み取り専用の同梱リソース(frontend等)の場所。
  PyInstallerでexe化されている場合は展開先(_MEIPASS)、
  通常のpython実行時はプロジェクトディレクトリを返す。
- get_exe_dir(): 実行中のexe(またはスクリプト)自身があるフォルダ。
  旧バージョンのデータを探すために使う。
"""

import os
import sys
from pathlib import Path

APP_NAME = "AIClipSaveApp"


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


def get_resource_dir() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def get_exe_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def migrate_legacy_data_if_needed() -> None:
    """旧バージョン(プロジェクトフォルダ/exeの隣にclips.db・uploadsを
    保存していた頃)のデータを、初回のみappdataにコピーする。
    既にappdata側にDBがある場合や、旧データが無い場合は何もしない。
    """
    new_base = get_app_data_dir()
    new_db = new_base / "clips.db"
    if new_db.exists():
        return

    legacy_base = get_exe_dir()
    legacy_db = legacy_base / "clips.db"
    if not legacy_db.is_file():
        return

    import shutil
    try:
        shutil.copy2(legacy_db, new_db)
        legacy_uploads = legacy_base / "uploads"
        if legacy_uploads.is_dir():
            shutil.copytree(legacy_uploads, new_base / "uploads", dirs_exist_ok=True)
    except Exception:
        pass

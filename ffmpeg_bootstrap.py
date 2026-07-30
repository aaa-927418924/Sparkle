"""ffmpeg(動画サムネイル生成用)の自動セットアップ。

system PATH上にffmpegが見つからない場合、gyan.devが配布している
静的ビルド(zip、7zip不要)をバックグラウンドでダウンロードし、
appdata\\bin\\ffmpeg.exe として保存する。ダウンロード中・失敗時も
アプリ本体はブロックされず、動画サムネイルが使えないだけで動き続ける。
"""

import io
import shutil
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from paths import get_app_data_dir

FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

_bundled_ffmpeg_path: Optional[Path] = None
_download_lock = threading.Lock()


def _bin_dir() -> Path:
    d = get_app_data_dir() / "bin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_ffmpeg_path() -> Optional[str]:
    """system PATH上のffmpeg、または過去にダウンロード済みのffmpegのパスを返す。
    どちらも無ければ None。"""
    found = shutil.which("ffmpeg")
    if found:
        return found
    global _bundled_ffmpeg_path
    if _bundled_ffmpeg_path and _bundled_ffmpeg_path.is_file():
        return str(_bundled_ffmpeg_path)
    candidate = _bin_dir() / "ffmpeg.exe"
    if candidate.is_file():
        _bundled_ffmpeg_path = candidate
        return str(candidate)
    return None


def ensure_ffmpeg_async() -> None:
    """ffmpegが見つからない場合のみ、バックグラウンドスレッドでダウンロードする。
    アプリの起動をブロックしない。"""
    if get_ffmpeg_path():
        return
    threading.Thread(target=_download_ffmpeg, daemon=True).start()


def _download_ffmpeg() -> None:
    global _bundled_ffmpeg_path
    if not _download_lock.acquire(blocking=False):
        return
    try:
        target = _bin_dir() / "ffmpeg.exe"
        if target.is_file():
            _bundled_ffmpeg_path = target
            return
        with urllib.request.urlopen(FFMPEG_ZIP_URL, timeout=120) as resp:
            data = resp.read()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            exe_entry = next(
                (n for n in zf.namelist() if n.lower().replace("\\", "/").endswith("/bin/ffmpeg.exe")),
                None,
            )
            if exe_entry is None:
                return
            with zf.open(exe_entry) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
        _bundled_ffmpeg_path = target
    except Exception:
        # ネットワーク不通などで失敗しても、動画サムネイルが無効になるだけ
        pass
    finally:
        _download_lock.release()

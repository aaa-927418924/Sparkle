"""アプリの自動アップデート管理。

GitHub Releases の latest リリースから `Sparkle.exe` をダウンロードし、
リリースに `Sparkle.exe.sha256` が添付されていれば SHA-256 で検証してから
新バージョンへ置き換える。

PyInstaller の単一ファイル exe は実行中にファイルロックされるため、置換は
新 exe 自身がインストーラとして動く方式で行う:

1. 旧アプリが新 exe を `--sparkle-install <old-pid> <target>` で起動して終了する。
2. 新 exe（= 本モジュールの `main`）が旧プロセスの終了を待つ。
3. 旧 exe を `.old` へ退避 → 自身をターゲットの exe へコピー → 通常起動。

テスト時は `SPARKLE_UPDATE_URL` 環境変数でチェック先 URL を差し替えられる
（GitHub API と同じフィールド構成の JSON を返すこと）。
"""

import ctypes
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from version import APP_NAME, APP_VERSION

DEFAULT_RELEASE_URL = "https://api.github.com/repos/aaa-927418924/Sparkle/releases/latest"
EXE_ASSET_NAME = f"{APP_NAME}.exe"
SHA256_ASSET_NAME = f"{EXE_ASSET_NAME}.sha256"

STAGE_IDLE = "idle"
STAGE_CHECKING = "checking"
STAGE_LATEST = "latest"
STAGE_AVAILABLE = "available"
STAGE_DOWNLOADING = "downloading"
STAGE_VERIFYING = "verifying"
STAGE_READY = "ready"
STAGE_INSTALLING = "installing"
STAGE_ERROR = "error"

_state_lock = threading.Lock()
_state: dict[str, Any] = {
    "enabled": False,
    "stage": STAGE_IDLE,
    "current": APP_VERSION,
    "latest": None,
    "progress": 0.0,
    "downloaded": 0,
    "total": 0,
    "message": "",
    "error": None,
    "release_url": None,
    "exe_url": None,
    "sha256_url": None,
    "temp_path": None,
}


def reset_state() -> None:
    with _state_lock:
        _state.update(
            stage=STAGE_IDLE,
            latest=None,
            progress=0.0,
            downloaded=0,
            total=0,
            message="",
            error=None,
            release_url=None,
            exe_url=None,
            sha256_url=None,
            temp_path=None,
        )


def get_update_state() -> dict[str, Any]:
    with _state_lock:
        state = dict(_state)
    state["enabled"] = _is_enabled()
    return state


def _set_state(**updates: Any) -> None:
    with _state_lock:
        _state.update(updates)


def _is_enabled() -> bool:
    return bool(getattr(sys, "frozen", False))


def _release_url() -> str:
    return os.environ.get("SPARKLE_UPDATE_URL", DEFAULT_RELEASE_URL)


def _request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = response.read(1024 * 1024)
    return json.loads(payload.decode("utf-8"))


def check_for_update() -> bool:
    """Query the latest release and refresh shared state. Returns whether an update is new."""
    if not _is_enabled():
        _set_state(stage=STAGE_IDLE, error=None)
        return False

    _set_state(stage=STAGE_CHECKING, error=None, message="更新を確認しています…")
    try:
        release = _request_json(_release_url())
    except Exception as exc:
        _set_state(stage=STAGE_ERROR, error=f"更新を確認できませんでした: {exc}")
        return False

    tag = str(release.get("tag_name") or "").strip().lstrip("v")
    assets = release.get("assets") or []
    exe_asset = next((a for a in assets if a.get("name") == EXE_ASSET_NAME), None)
    sha256_asset = next((a for a in assets if a.get("name") == SHA256_ASSET_NAME), None)

    release_url = str(release.get("html_url") or str(release.get("url") or ""))
    _set_state(latest=tag, release_url=release_url)

    if not exe_asset or not tag:
        _set_state(stage=STAGE_LATEST, message="最新版です。")
        return False

    if _compare_versions(tag, APP_VERSION) <= 0:
        _set_state(stage=STAGE_LATEST, message="最新版です。")
        return False

    _set_state(
        stage=STAGE_AVAILABLE,
        exe_url=str(exe_asset.get("browser_download_url") or ""),
        sha256_url=str(sha256_asset.get("browser_download_url") or "") if sha256_asset else None,
        total=int(exe_asset.get("size") or 0),
        progress=0.0,
        downloaded=0,
        error=None,
        message="",
    )
    return True


def _compare_versions(a: str, b: str) -> int:
    left = _version_tuple(a)
    right = _version_tuple(b)
    return (left > right) - (left < right)


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(version).split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def _app_update_dir() -> Path:
    base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / APP_NAME
    folder = base / "update"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def download_update() -> bool:
    """Download the exe and verify it. Returns True on success, updating --state."""
    state = get_update_state()
    if not _is_enabled():
        _set_state(stage=STAGE_ERROR, error="ソースから実行中のため更新できません。")
        return False
    if state.get("stage") != STAGE_AVAILABLE or not state.get("exe_url"):
        _set_state(stage=STAGE_ERROR, error="更新対象が見つかりません。")
        return False

    target = _app_update_dir() / f"{APP_NAME}.new.exe"
    exe_url = str(state["exe_url"])

    try:
        if target.exists():
            target.unlink()
        _stream_download(exe_url, target)
    except Exception as exc:
        _set_state(stage=STAGE_ERROR, error=f"ダウンロードに失敗しました: {exc}")
        return False

    try:
        header = target.read_bytes()[:2]
    except OSError:
        header = b""
    if header != b"MZ":
        _set_state(stage=STAGE_ERROR, error="ダウンロードしたファイルが exe ではありません。")
        return False

    _set_state(stage=STAGE_VERIFYING, message="SHA-256 を検証しています…")
    sha256_url = state.get("sha256_url")
    if sha256_url:
        try:
            expected = _fetch_sha256(str(sha256_url))
            actual = _file_sha256(target)
        except Exception as exc:
            _set_state(stage=STAGE_ERROR, error=f"SHA-256 検証に失敗しました: {exc}")
            return False
        if not expected or actual != expected.lower():
            _set_state(stage=STAGE_ERROR, error="SHA-256 検証に失敗しました（チェックサム不一致）。")
            return False

    _set_state(
        stage=STAGE_READY,
        progress=1.0,
        downloaded=target.stat().st_size,
        total=target.stat().st_size,
        temp_path=str(target),
        error=None,
        message="",
    )
    return True


def _stream_download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    total = 0
    written = 0
    with urllib.request.urlopen(request, timeout=120) as response:
        total = int(response.headers.get("Content-Length") or 0)
        _set_state(stage=STAGE_DOWNLOADING, total=total, progress=0.0)
        with open(dest, "wb") as out_file:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                out_file.write(chunk)
                written += len(chunk)
                progress = (written / total) if total else 0.0
                _set_state(stage=STAGE_DOWNLOADING, progress=progress, downloaded=written)


def _fetch_sha256(url: str) -> Optional[str]:
    request = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read(64 * 1024).decode("utf-8", errors="ignore")
    for token in text.split():
        if len(token) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in token):
            return token.lower()
    return None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(256 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- installation ----------------------------------------------------------

def start_download() -> bool:
    """Start downloading in a background thread so the UI can poll progress."""
    state = get_update_state()
    if state.get("stage") != STAGE_AVAILABLE:
        _set_state(stage=STAGE_ERROR, error="更新対象がありません。")
        return False

    def _run() -> None:
        try:
            download_update()
        except Exception as exc:
            _set_state(stage=STAGE_ERROR, error=f"ダウンロードに失敗しました: {exc}")

    threading.Thread(target=_run, daemon=True).start()
    return True


def apply_update(on_quit: Optional[Callable[[], None]] = None) -> bool:
    """Launch the staged installer then ask the app to quit.

    ``on_quit`` (called on the main app side) performs the actual app shutdown;
    the installer process survives it and does the file replacement.
    """
    state = get_update_state()
    temp_path = state.get("temp_path")
    if state.get("stage") != STAGE_READY or not temp_path or not Path(temp_path).is_file():
        _set_state(stage=STAGE_ERROR, error="更新ファイルの準備ができていません。")
        return False

    target = _target_exe()
    if target is None:
        _set_state(stage=STAGE_ERROR, error="更新先の exe を特定できませんでした。")
        return False

    _set_state(stage=STAGE_INSTALLING, message="起動しています…")
    if not _spawn_installer(Path(temp_path), target):
        return False

    if on_quit is not None:
        try:
            on_quit()
        except Exception:
            pass
    return True


def _spawn_installer(new_exe: Path, target: Path) -> bool:
    args = [str(new_exe), "--sparkle-install", str(os.getpid()), str(target)]
    creationflags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags |= subprocess.CREATE_NO_WINDOW
    try:
        subprocess.Popen(args, creationflags=creationflags)
        return True
    except Exception as exc:
        _set_state(stage=STAGE_ERROR, error=f"更新を適用できませんでした: {exc}")
        return False


def _target_exe() -> Optional[Path]:
    if hasattr(sys, "frozen") and sys.frozen:
        return Path(sys.executable).resolve()
    path = os.environ.get("SPARKLE_EXECUTABLE")
    if path:
        return Path(path).resolve()
    return None


def run_installer() -> None:
    """Replace the old exe with the currently running one and relaunch.

    Expected argv: --sparkle-install <old-pid> <target-exe>
    """
    try:
        old_pid = int(sys.argv[2])
        target = Path(sys.argv[3]).resolve()
    except (IndexError, ValueError):
        _show_error("更新インストーラの引数が不正です。")
        return

    if old_pid:
        _wait_for_process_exit(old_pid, timeout=300.0)

    source = Path(sys.executable).resolve()
    backup = target.with_suffix(".old")

    try:
        if target.exists():
            if backup.exists():
                backup.unlink()
            _retry_os_op(lambda: target.rename(backup))
        if not _wait_for_file(target.parent):
            raise RuntimeError("ディレクトリを書き込み可能にするまで待つことができませんでした。")
        import shutil

        _retry_os_op(lambda: shutil.copy2(source, target))
        if target.read_bytes()[:2] != b"MZ":
            raise RuntimeError("新しい exe の検証に失敗しました。")
    except Exception as exc:
        _show_error(f"更新の適用に失敗しました: {exc}")
        if backup.is_file() and not target.exists():
            _retry_os_op(lambda: backup.rename(target), timeout=10.0)
        return

    try:
        subprocess.Popen([str(target)])
    except Exception:
        pass


def _retry_os_op(op, timeout: float = 30.0, interval: float = 0.5) -> None:
    """Retry a filesystem operation while a transient file lock is held."""
    deadline = time.time() + timeout
    last_error: Optional[OSError] = None
    while time.time() < deadline:
        try:
            op()
            return
        except OSError as exc:
            last_error = exc
            time.sleep(interval)
    if last_error is not None:
        raise last_error


def _wait_for_process_exit(pid: int, timeout: float) -> None:
    if os.name != "nt":
        time.sleep(1.5)
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if handle:
        try:
            kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        finally:
            kernel32.CloseHandle(handle)
    else:
        time.sleep(0.5)  # process already gone?


def _wait_for_file(directory: Path, timeout: float = 30.0) -> bool:
    probe = directory / ".sparkle-update-probe"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            probe.touch(exist_ok=False)
            probe.unlink()
            return True
        except OSError:
            time.sleep(0.25)
    return False


def _show_error(message: str) -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
    except Exception:
        pass
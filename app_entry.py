"""exe化した際のエントリーポイント。
uvicornサーバーをバックグラウンドスレッドで起動し、メインスレッドでは
タスクトレイアイコンを表示する。コンソールなしで起動されるため、
標準出力/エラーはログファイルにリダイレクトし、失敗時はメッセージボックスで知らせる。
"""

import os
import socket
import sys
import threading
import time
import traceback
from urllib.request import urlopen
import webbrowser
from pathlib import Path

from paths import get_app_data_dir, is_frozen

HOST = "127.0.0.1"
PORT = 8000
LOG_PATH = get_app_data_dir() / "app.log"
STDIO_LOG_PATH = get_app_data_dir() / "stdio.log"

# --noconsoleビルドでは sys.stdout / sys.stderr が None になり、
# それに依存するライブラリ(uvicornのログ設定など)がクラッシュするため、
# 最初にログファイルへリダイレクトしておく。
if sys.stdout is None or sys.stderr is None:
    _stream = open(STDIO_LOG_PATH, "a", encoding="utf-8", buffering=1)
    sys.stdout = _stream
    sys.stderr = _stream

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_REG_NAME = "AIClipSaveApp"

server_ref = {}


def _show_error(message: str) -> None:
    try:
        import ctypes

        # MB_ICONERROR | MB_SETFOREGROUND
        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            "AI Clip Save App",
            0x10 | 0x10000,
        )
    except Exception:
        pass


def _get_exe_path() -> str:
    if is_frozen():
        return str(Path(sys.executable).resolve())
    return str(Path(__file__).resolve())


def is_autostart_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_REG_NAME)
        return True
    except Exception:
        return False


def set_autostart_enabled(enabled: bool) -> None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_REG_NAME, 0, winreg.REG_SZ, f'"{_get_exe_path()}"')
            else:
                try:
                    winreg.DeleteValue(key, APP_REG_NAME)
                except FileNotFoundError:
                    pass
    except Exception:
        pass


def _run_server() -> None:
    try:
        import uvicorn
        from main import app  # FastAPI アプリ本体

        # noconsoleビルドでは標準入出力がNoneになり得るため、
        # Uvicornの既定ログ設定を使わず、アプリ側のファイルログだけを使う。
        config = uvicorn.Config(app, host=HOST, port=PORT, log_config=None)
        server = uvicorn.Server(config)
        server_ref["server"] = server
        server.run()
    except Exception:
        try:
            LOG_PATH.write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        raise


def _open_browser_when_ready() -> None:
    for _ in range(150):
        try:
            with socket.create_connection((HOST, PORT), timeout=0.5):
                webbrowser.open(f"http://{HOST}:{PORT}/Home")
                return
        except OSError:
            time.sleep(0.2)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as log:
            log.write("\nサーバーが起動せず、ブラウザを開けませんでした。\n")
    except Exception:
        pass

def _build_tray_image():
    from PIL import Image, ImageDraw
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([4, 4, size - 4, size - 4], radius=14, fill=(220, 122, 92, 255))
    draw.ellipse([18, 18, size - 18, size - 18], fill=(255, 255, 255, 255))
    return img


def _build_tray_icon():
    import pystray

    def _open_browser(icon, item):
        webbrowser.open(f"http://{HOST}:{PORT}/Home")

    def _toggle_autostart(icon, item):
        set_autostart_enabled(not is_autostart_enabled())

    def _exit_app(icon, item):
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("ブラウザで開く", _open_browser, default=True),
        pystray.MenuItem(
            "PC起動時に自動起動",
            _toggle_autostart,
            checked=lambda item: is_autostart_enabled(),
        ),
        pystray.MenuItem("終了", _exit_app),
    )
    return pystray.Icon("AIClipSaveApp", _build_tray_image(), "AI Clip Save App", menu)


def _is_app_server_running() -> bool:
    """Return True only when port 8000 is serving this application."""
    try:
        with urlopen(f"http://{HOST}:{PORT}/health", timeout=1.0) as response:
            body = response.read(256)
            return response.status == 200 and b'"status"' in body and b'"ok"' in body
    except Exception:
        return False


def _is_port_in_use() -> bool:
    probe = socket.socket()
    try:
        return probe.connect_ex((HOST, PORT)) == 0
    finally:
        probe.close()

def main() -> None:
    try:
        if _is_app_server_running():
            # 既に起動中(二重起動) → ブラウザでウィンドウを開くだけ
            webbrowser.open(f"http://{HOST}:{PORT}/Home")
            return
        if _is_port_in_use():
            message = (
                f"ポート {PORT} が別のアプリに使用されています。\n"
                f"AIClipSaveAppを起動する前に、ポート {PORT} を使用しているアプリを終了してください。\n\n"
                f"詳細: {LOG_PATH}"
            )
            try:
                LOG_PATH.write_text(message, encoding="utf-8")
            except Exception:
                pass
            _show_error(message)
            return

        threading.Thread(target=_run_server, daemon=True).start()
        threading.Thread(target=_open_browser_when_ready, daemon=True).start()

        icon = _build_tray_icon()
        icon.run()  # 「終了」が押されるまでここでブロックする(メインスレッド)

        server = server_ref.get("server")
        if server is not None:
            server.should_exit = True
        time.sleep(0.3)
        os._exit(0)
    except Exception:
        err = traceback.format_exc()
        try:
            LOG_PATH.write_text(err, encoding="utf-8")
        except Exception:
            pass
        _show_error(f"起動中にエラーが発生しました。\n詳細: {LOG_PATH}")
        sys.exit(1)


if __name__ == "__main__":
    main()

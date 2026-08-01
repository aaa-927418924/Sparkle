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
from urllib.request import Request, urlopen
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
window_ref = {}
exit_requested = threading.Event()
window_state = {"maximized": False}


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


def _has_webview2_runtime() -> bool:
    """Return whether the Evergreen WebView2 Runtime is installed."""
    if os.name != "nt":
        return False

    try:
        import winreg

        locations = (
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
            (winreg.HKEY_CURRENT_USER,
             r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        )
        for hive, subkey in locations:
            try:
                with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
                    version, _ = winreg.QueryValueEx(key, "pv")
                if version and str(version) != "0.0.0.0":
                    return True
            except (FileNotFoundError, OSError):
                continue
    except Exception:
        return False
    return False


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
                winreg.SetValueEx(
                    key,
                    APP_REG_NAME,
                    0,
                    winreg.REG_SZ,
                    f'"{_get_exe_path()}" --hidden',
                )
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

        app.state.desktop_activate = _activate_window

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


def _wait_for_server() -> bool:
    for _ in range(150):
        try:
            with urlopen(f"http://{HOST}:{PORT}/health", timeout=0.5) as response:
                if response.status == 200 and b'"ok"' in response.read(256):
                    return True
        except Exception:
            time.sleep(0.2)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as log:
            log.write("\nサーバーが起動せず、ネイティブウィンドウを開けませんでした。\n")
    except Exception:
        pass
    return False


def _activate_window() -> None:
    window = window_ref.get("window")
    if window is None:
        return
    try:
        window.restore()
    except Exception:
        pass
    try:
        window.show()
    except Exception:
        pass

    # pywebview exposes the native handle after the window is shown.  Bringing
    # it to the foreground makes the tray and second-launch paths feel native.
    try:
        native = window.native
        handle = getattr(native, "Handle", None)
        if handle is not None:
            try:
                hwnd = int(handle)
            except (TypeError, ValueError):
                hwnd = int(handle.ToInt64())
            import ctypes

            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _stop_server() -> None:
    server = server_ref.get("server")
    if server is not None:
        server.should_exit = True


class NativeWindowApi:
    """Expose the small set of native window actions used by the custom title bar."""

    @staticmethod
    def minimize_window() -> None:
        window = window_ref.get("window")
        if window is not None:
            window.minimize()

    @staticmethod
    def toggle_maximize_window() -> bool:
        window = window_ref.get("window")
        if window is None:
            return False

        try:
            if window_state["maximized"]:
                window.restore()
                window_state["maximized"] = False
            else:
                window.maximize()
                window_state["maximized"] = True
        except Exception:
            pass
        return window_state["maximized"]

    @staticmethod
    def close_window() -> None:
        exit_requested.set()
        _stop_server()
        window = window_ref.get("window")
        if window is not None:
            window.destroy()


def _on_window_closing(window) -> bool:
    if exit_requested.is_set():
        return True
    try:
        window.hide()
    except Exception:
        pass
    return False

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

    def _open_window(icon, item):
        _activate_window()

    def _toggle_autostart(icon, item):
        set_autostart_enabled(not is_autostart_enabled())

    def _exit_app(icon, item):
        exit_requested.set()
        _stop_server()
        window = window_ref.get("window")
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("ウィンドウを開く", _open_window, default=True),
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


def _activate_existing_app() -> bool:
    try:
        request = Request(f"http://{HOST}:{PORT}/app/activate", method="POST")
        with urlopen(request, timeout=1.0) as response:
            return response.status in (200, 204)
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
            # 既に起動中(二重起動) → 既存のネイティブウィンドウを前面表示
            _activate_existing_app()
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

        if not _has_webview2_runtime():
            _show_error(
                "Microsoft Edge WebView2 Runtimeが見つかりません。\n"
                "Windows用のWebView2 Runtimeをインストールしてから、もう一度起動してください。\n\n"
                "https://developer.microsoft.com/microsoft-edge/webview2/"
            )
            return

        server_thread = threading.Thread(target=_run_server, daemon=True)
        server_thread.start()
        if not _wait_for_server():
            _show_error(f"サーバーが起動しませんでした。\n詳細: {LOG_PATH}")
            return

        try:
            import webview
        except Exception as exc:
            _stop_server()
            _show_error(
                "ネイティブウィンドウの依存関係を読み込めませんでした。\n"
                f"{exc}\n\n詳細: {LOG_PATH}"
            )
            return

        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        webview.settings["ALLOW_DOWNLOADS"] = True

        window = webview.create_window(
            "Clips",
            url=f"http://{HOST}:{PORT}/Home",
            width=1280,
            height=820,
            min_size=(960, 640),
            resizable=True,
            frameless=True,
            easy_drag=True,
            text_select=True,
            zoomable=True,
            background_color="#202020",
            hidden="--hidden" in sys.argv[1:],
            js_api=NativeWindowApi(),
        )
        window_ref["window"] = window
        window.events.closing += _on_window_closing

        icon = _build_tray_icon()
        tray_thread = threading.Thread(target=icon.run, daemon=True)
        tray_thread.start()

        webview.start(debug=not is_frozen())

        exit_requested.set()
        _stop_server()
        icon.stop()
        server_thread.join(timeout=2.0)
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

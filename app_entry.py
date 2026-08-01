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


def _get_port() -> int:
    try:
        port = int(os.environ.get("AICLIP_PORT", "8000"))
    except (TypeError, ValueError):
        return 8000
    return port if 1 <= port <= 65535 else 8000


PORT = _get_port()
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


def _get_native_window_handle(window):
    if window is None:
        return None
    try:
        native = window.native
        handle = getattr(native, "Handle", None)
        if handle is None:
            handle = getattr(native, "handle", None)
        if handle is None:
            return None
        try:
            handle = int(handle)
        except (TypeError, ValueError, OverflowError):
            handle = int(handle.ToInt64())
        return handle or None
    except Exception:
        return None


def _get_window_geometry(window, restored: bool = False):
    if window is None:
        return None
    try:
        return {
            "x": int(window.x),
            "y": int(window.y),
            "width": int(window.width),
            "height": int(window.height),
            "restored": restored,
        }
    except Exception:
        return None


def _place_restored_window_at_cursor(window, maximized_geometry, restored_geometry, screen_x, screen_y):
    if not maximized_geometry or not restored_geometry or screen_x is None or screen_y is None:
        return restored_geometry

    try:
        cursor_x = int(screen_x)
        cursor_y = int(screen_y)
        maximized_width = max(int(maximized_geometry["width"]), 1)
        maximized_height = max(int(maximized_geometry["height"]), 1)
        restored_width = max(int(restored_geometry["width"]), 1)
        restored_height = max(int(restored_geometry["height"]), 1)

        # Keep the point grabbed in the maximized title bar under the cursor
        # after restoring, matching native Windows drag behavior.
        cursor_offset_x = min(max(cursor_x - int(maximized_geometry["x"]), 0), maximized_width - 1)
        cursor_offset_y = min(max(cursor_y - int(maximized_geometry["y"]), 0), maximized_height - 1)
        restored_x = cursor_x - min(cursor_offset_x, restored_width - 1)
        restored_y = cursor_y - min(cursor_offset_y, restored_height - 1)
        window.move(restored_x, restored_y)
        return _get_window_geometry(window, restored=True) or restored_geometry
    except Exception:
        return restored_geometry


def _enable_native_resize(window) -> None:
    """Restore the Windows sizing frame that frameless pywebview removes."""
    if os.name != "nt":
        return

    handle = _get_native_window_handle(window)
    if handle is None:
        return

    try:
        import ctypes

        user32 = ctypes.windll.user32
        pointer_size = ctypes.sizeof(ctypes.c_void_p)
        long_type = ctypes.c_longlong if pointer_size == 8 else ctypes.c_long
        get_window_long = user32.GetWindowLongPtrW if pointer_size == 8 else user32.GetWindowLongW
        set_window_long = user32.SetWindowLongPtrW if pointer_size == 8 else user32.SetWindowLongW
        get_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
        get_window_long.restype = long_type
        set_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int, long_type]
        set_window_long.restype = long_type

        hwnd = ctypes.c_void_p(handle)
        style = int(get_window_long(hwnd, -16))
        style &= ~0x00C00000  # WS_CAPTION
        style |= 0x00040000 | 0x00020000 | 0x00010000 | 0x00080000  # THICKFRAME | MIN/MAXBOX | SYSMENU
        set_window_long(hwnd, -16, style)

        user32.SetWindowPos.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = ctypes.c_int
        user32.SetWindowPos(
            hwnd,
            None,
            0,
            0,
            0,
            0,
            0x0001 | 0x0002 | 0x0004 | 0x0020,  # NOSIZE | NOMOVE | NOZORDER | FRAMECHANGED
        )
    except Exception:
        pass


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
        hwnd = _get_native_window_handle(window)
        if hwnd is not None:
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
    def restore_window_for_drag() -> bool:
        window = window_ref.get("window")
        if window is None:
            return False

        is_maximized = window_state["maximized"]
        try:
            is_maximized = is_maximized or "maximized" in str(window.state).lower()
        except Exception:
            pass
        if not is_maximized:
            return False

        try:
            window.restore()
        except Exception:
            return False
        window_state["maximized"] = False
        return True

    @staticmethod
    def begin_window_drag(screen_x=None, screen_y=None):
        window = window_ref.get("window")
        if window is None:
            return None
        maximized_geometry = _get_window_geometry(window)
        restored = NativeWindowApi.restore_window_for_drag()
        geometry = _get_window_geometry(window, restored=restored)
        if restored:
            geometry = _place_restored_window_at_cursor(
                window,
                maximized_geometry,
                geometry,
                screen_x,
                screen_y,
            )
        return geometry

    @staticmethod
    def move_window(x: int, y: int) -> None:
        window = window_ref.get("window")
        if window is not None:
            window.move(int(x), int(y))

    @staticmethod
    def begin_window_resize():
        window = window_ref.get("window")
        if window is None:
            return None
        restored = NativeWindowApi.restore_window_for_drag()
        return _get_window_geometry(window, restored=restored)

    @staticmethod
    def resize_window(width: int, height: int, x: int, y: int) -> None:
        window = window_ref.get("window")
        if window is None:
            return
        window.move(int(x), int(y))
        window.resize(int(width), int(height))

    @staticmethod
    def close_window() -> None:
        window = window_ref.get("window")
        if window is not None:
            try:
                window.hide()
            except Exception:
                pass


def _on_window_closing(window) -> bool:
    if exit_requested.is_set():
        return True
    try:
        window.hide()
    except Exception:
        pass
    return False


def _configure_native_window() -> None:
    _enable_native_resize(window_ref.get("window"))


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
    """Return True only when the configured port is serving this application."""
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
            "Sparkle",
            url=f"http://{HOST}:{PORT}/Home",
            width=1280,
            height=820,
            min_size=(960, 640),
            resizable=True,
            frameless=True,
            easy_drag=False,
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

        webview.start(_configure_native_window, debug=not is_frozen())

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

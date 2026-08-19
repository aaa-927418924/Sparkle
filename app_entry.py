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


def _enable_windows_dpi_awareness() -> bool:
    """Make the native window participate in Windows DPI scaling correctly."""
    if os.name != "nt":
        return False

    try:
        import ctypes

        user32 = ctypes.windll.user32
        set_context = getattr(user32, "SetProcessDpiAwarenessContext", None)
        if set_context is not None:
            set_context.argtypes = [ctypes.c_void_p]
            set_context.restype = ctypes.c_bool
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            if set_context(ctypes.c_void_p(-4)):
                return True
    except Exception:
        pass

    # Windows 8.1 fallback for systems without SetProcessDpiAwarenessContext.
    try:
        import ctypes

        shcore = ctypes.windll.shcore
        set_process_awareness = shcore.SetProcessDpiAwareness
        set_process_awareness.argtypes = [ctypes.c_int]
        set_process_awareness.restype = ctypes.c_long
        # PROCESS_PER_MONITOR_DPI_AWARE
        return set_process_awareness(2) == 0
    except Exception:
        return False


# This must run before pywebview creates the WinForms/WebView2 window. Without
# it Windows can bitmap-scale the whole window at 150%/175%, making the fixed
# 1510x820 startup size larger than the physical display.
_WINDOW_DPI_AWARE = _enable_windows_dpi_awareness()

from migration import get_migration_status
from paths import get_app_data_dir, get_resource_dir, is_frozen
from setup import (
    ensure_post_migration_onboarding,
    get_post_migration_onboarding_status,
    get_setup_status,
    get_setup_tutorial_status,
)
from updater import apply_update, check_for_update, get_update_state

HOST = "127.0.0.1"
DEBUG_SETUP_FLAG = "--debug-setup"
DEBUG_TUTORIAL_FLAG = "--debug-tutorial"
DEBUG_EXTENSION_GUIDE_FLAG = "--debug-extension-guide"
DEFAULT_WINDOW_SIZE = (1510, 820)
DEFAULT_MIN_WINDOW_SIZE = (960, 640)
# The onboarding screens start at this size, but the native window remains
# freely resizable. Change this tuple to adjust the onboarding layout without
# introducing an aspect-ratio lock.
ONBOARDING_WINDOW_SIZE = (958, 885)
ONBOARDING_MIN_WINDOW_SIZE = (720, 560)
DEFAULT_WINDOW_PROFILE = "default"
ONBOARDING_WINDOW_PROFILE = "onboarding"
ONBOARDING_PAGES = {"Migration", "Setup", "Tutorial", "ExtensionGuide"}
WINDOW_SCREEN_MARGIN = 24


def _get_port() -> int:
    try:
        port = int(os.environ.get("SPARKLE_PORT", "8000"))
    except (TypeError, ValueError):
        return 8000
    return port if 1 <= port <= 65535 else 8000


PORT = _get_port()
LOG_PATH = get_app_data_dir() / "app.log"
STDIO_LOG_PATH = get_app_data_dir() / "stdio.log"
WEBVIEW_STORAGE_PATH = get_app_data_dir() / "webview"
WEBVIEW_STORAGE_PATH.mkdir(parents=True, exist_ok=True)

# --noconsoleビルドでは sys.stdout / sys.stderr が None になり、
# それに依存するライブラリ(uvicornのログ設定など)がクラッシュするため、
# 最初にログファイルへリダイレクトしておく。
if sys.stdout is None or sys.stderr is None:
    _stream = open(STDIO_LOG_PATH, "a", encoding="utf-8", buffering=1)
    sys.stdout = _stream
    sys.stderr = _stream

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_REG_NAME = "Sparkle"

server_ref = {}
window_ref = {}
exit_requested = threading.Event()
window_state = {
    "maximized": False,
    "profile": DEFAULT_WINDOW_PROFILE,
    "native_resize_handle": None,
    "native_titlebar": None,
    "native_titlebar_handle": None,
}
native_drop_condition = threading.Condition()
native_drop_paths = []
native_drop_document = None
native_drop_targets = []


def _get_work_area_bounds():
    """Return the primary work area in the process's DPI units."""
    if os.name != "nt":
        return None

    try:
        import ctypes

        rect_type = type(
            "RECT",
            (ctypes.Structure,),
            {
                "_fields_": [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]
            },
        )
        rect = rect_type()
        # SPI_GETWORKAREA = 0x0030
        if not ctypes.windll.user32.SystemParametersInfoW(
            0x0030,
            0,
            ctypes.byref(rect),
            0,
        ):
            return None

        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width <= 0 or height <= 0:
            return None
        return int(rect.left), int(rect.top), width, height
    except Exception:
        return None


def _get_work_area_size():
    bounds = _get_work_area_bounds()
    return bounds[2:] if bounds else None


def _get_window_size_config(profile=DEFAULT_WINDOW_PROFILE):
    """Keep the selected window profile inside the usable display area at any DPI."""
    if profile == ONBOARDING_WINDOW_PROFILE:
        width, height = ONBOARDING_WINDOW_SIZE
        minimum_width, minimum_height = ONBOARDING_MIN_WINDOW_SIZE
        work_area = _get_work_area_size()
        if work_area:
            available_width = max(work_area[0] - WINDOW_SCREEN_MARGIN, 1)
            available_height = max(work_area[1] - WINDOW_SCREEN_MARGIN, 1)
            scale = min(1.0, available_width / width, available_height / height)
            width = max(1, int(round(width * scale)))
            height = max(1, int(round(height * scale)))
            minimum_width = min(minimum_width, width)
            minimum_height = min(minimum_height, height)
        return width, height, (minimum_width, minimum_height)

    width, height = DEFAULT_WINDOW_SIZE
    minimum_width, minimum_height = DEFAULT_MIN_WINDOW_SIZE
    work_area = _get_work_area_size()
    if work_area:
        available_width = max(work_area[0] - WINDOW_SCREEN_MARGIN, 1)
        available_height = max(work_area[1] - WINDOW_SCREEN_MARGIN, 1)
        width = min(width, available_width)
        height = min(height, available_height)
        minimum_width = min(minimum_width, width)
        minimum_height = min(minimum_height, height)

    return width, height, (minimum_width, minimum_height)


def _window_profile_for_page(page: str) -> str:
    page_name = str(page or "").split("?", 1)[0].strip("/")
    return ONBOARDING_WINDOW_PROFILE if page_name in ONBOARDING_PAGES else DEFAULT_WINDOW_PROFILE


def _show_error(message: str) -> None:
    try:
        import ctypes

        # MB_ICONERROR | MB_SETFOREGROUND
        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            "Sparkle",
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
        from remote_runtime import RemoteAccessManager

        app.state.desktop_activate = _activate_window
        app.state.update_status = get_update_state
        app.state.update_apply = _apply_pending_update
        remote_manager = RemoteAccessManager(main_port=PORT)
        app.state.remote_access_manager = remote_manager
        server_ref["remote_manager"] = remote_manager

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


def _focus_native_webview() -> bool:
    """Restore wheel/key input to the WebView2 control after navigation."""
    window = window_ref.get("window")
    native = getattr(window, "native", None) if window is not None else None
    webview = getattr(native, "webview", None)
    if webview is None:
        webview = getattr(getattr(native, "browser", None), "webview", None)
    if webview is None:
        return False

    def _focus() -> None:
        try:
            webview.Focus()
        except Exception:
            pass

    try:
        if bool(getattr(webview, "InvokeRequired", False)):
            import clr  # noqa: F401 - initializes pythonnet's System namespace
            from System import Action

            webview.Invoke(Action(_focus))
        else:
            _focus()
        return True
    except Exception:
        return False


def _get_window_geometry(window, restored: bool = False):
    if window is None:
        return None
    try:
        minimum_width, minimum_height = _get_window_size_config(
            window_state.get("profile", DEFAULT_WINDOW_PROFILE)
        )[2]
        return {
            "x": int(window.x),
            "y": int(window.y),
            "width": int(window.width),
            "height": int(window.height),
            "minimum_width": int(minimum_width),
            "minimum_height": int(minimum_height),
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


def _apply_window_caption(window, native_titlebar: bool) -> None:
    """Show or hide the Windows caption bar on a frameless window."""
    if os.name != "nt":
        return

    handle = _get_native_window_handle(window)
    if handle is None:
        return

    handle_key = int(handle)
    if (
        window_state.get("native_titlebar") is bool(native_titlebar)
        and window_state.get("native_titlebar_handle") == handle_key
    ):
        return

    # A real caption needs more than WS_CAPTION: without SYSMENU, MIN/MAXBOX
    # and THICKFRAME, the native bar renders empty (no minimize/maximize/close
    # buttons). Custom mode drops the caption AND the sizing frame; keeping
    # WS_THICKFRAME would make DWM paint a thin leftover frame edge along the
    # top of the window. Resizing still works through the app's own JS resize
    # handles.
    _apply_window_style(
        handle,
        (
            lambda style: (style | 0x00C00000 | 0x00080000 | 0x00020000 | 0x00010000 | 0x00040000)
            if native_titlebar
            else (style & ~(0x00C00000 | 0x00040000))
        ),
    )
    _apply_dwm_frame_margin(handle, native_titlebar)
    _apply_corner_preference(handle, native_titlebar)
    window_state["native_titlebar"] = bool(native_titlebar)
    window_state["native_titlebar_handle"] = handle_key


def _apply_window_style(handle, mutate_style) -> None:
    """Toggle Win32 window styles without touching pywebview's shared ctypes.

    The global ``ctypes.windll.user32`` namespace is owned by pywebview; changing
    ``argtypes``/``restype`` on it breaks pywebview's own ``SetWindowPos`` calls
    that pass ``None`` for the size arguments.  Use isolated WINFUNCTYPE
    prototypes so only this app's Win32 calls are configured.
    """
    if handle is None or os.name != "nt":
        return

    try:
        import ctypes

        user32 = ctypes.WinDLL("user32")
        pointer_size = ctypes.sizeof(ctypes.c_void_p)
        long_type = ctypes.c_longlong if pointer_size == 8 else ctypes.c_long

        get_window_long_name = "GetWindowLongPtrW" if pointer_size == 8 else "GetWindowLongW"
        set_window_long_name = "SetWindowLongPtrW" if pointer_size == 8 else "SetWindowLongW"

        get_window_long = ctypes.WINFUNCTYPE(
            long_type, ctypes.c_void_p, ctypes.c_int
        )((get_window_long_name, user32))
        set_window_long = ctypes.WINFUNCTYPE(
            long_type, ctypes.c_void_p, ctypes.c_int, long_type
        )((set_window_long_name, user32))

        hwnd = ctypes.c_void_p(handle)
        style = int(get_window_long(hwnd, -16))
        style = mutate_style(style)
        set_window_long(hwnd, -16, style)

        set_window_pos = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        )(("SetWindowPos", user32))
        set_window_pos(
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


def _apply_dwm_frame_margin(handle, native_titlebar: bool) -> None:
    """Zero/recover the DWM glass frame margin on a frameless window.

    pywebview extends the DWM glass frame 1px into the client area when the
    window has a shadow, which renders as a thin bar along the top edge of a
    frameless window.  Custom mode zeroes the margin; native mode restores the
    1px margin so the caption area renders normally.
    """
    if handle is None or os.name != "nt":
        return

    try:
        import ctypes

        dwmapi = ctypes.WinDLL("dwmapi")
        margin_value = 1 if native_titlebar else 0

        extend_frame = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_long),
        )(("DwmExtendFrameIntoClientArea", dwmapi))
        margins = (ctypes.c_long * 4)(margin_value, margin_value, margin_value, margin_value)
        extend_frame(ctypes.c_void_p(handle), margins)
    except Exception:
        pass


def _apply_corner_preference(handle, native_titlebar: bool) -> None:
    """Round the corners of a frameless window (Windows 11+).

    Frameless windows lose the rounded corners that pywebview's 1px DWM glass
    frame used to provide, so request DWM to round them explicitly.  Native
    caption mode leaves the preference to the system default.
    """
    if handle is None or os.name != "nt":
        return

    try:
        import ctypes
        import sys

        # DWMWA_WINDOW_CORNER_PREFERENCE only exists on Windows 11 (build 22000+)
        if sys.getwindowsversion().build < 22000:
            return

        dwmapi = ctypes.WinDLL("dwmapi")
        # DWMWCP_DEFAULT=0, DWMWCP_DONOTROUND=1, DWMWCP_ROUND=2
        preference = 0 if native_titlebar else 2

        set_window_attr = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        )(("DwmSetWindowAttribute", dwmapi))
        value = ctypes.c_int(preference)
        set_window_attr(ctypes.c_void_p(handle), 33, ctypes.byref(value), 4)
    except Exception:
        pass


def _enable_native_resize(window) -> None:
    """Restore the Windows sizing frame that frameless pywebview removes."""
    if os.name != "nt":
        return

    handle = _get_native_window_handle(window)
    if handle is None:
        return

    handle_key = int(handle)
    if window_state.get("native_resize_handle") == handle_key:
        return

    _apply_window_style(
        handle,
        lambda style: (style & ~0x00C00000)  # WS_CAPTION
        | 0x00040000
        | 0x00020000
        | 0x00010000
        | 0x00080000,  # THICKFRAME | MIN/MAXBOX | SYSMENU
    )
    window_state["native_resize_handle"] = handle_key


def _resize_window_for_profile(profile: str):
    if profile not in {DEFAULT_WINDOW_PROFILE, ONBOARDING_WINDOW_PROFILE}:
        profile = DEFAULT_WINDOW_PROFILE

    window = window_ref.get("window")
    if window is None:
        window_state["profile"] = profile
        return None

    if window_state.get("profile") == profile:
        return _get_window_geometry(window)

    is_maximized = bool(window_state.get("maximized"))
    try:
        is_maximized = is_maximized or "maximized" in str(window.state).lower()
    except Exception:
        pass
    if is_maximized:
        try:
            window.restore()
            window_state["maximized"] = False
        except Exception:
            return _get_window_geometry(window)

    current = _get_window_geometry(window)
    width, height, minimum_size = _get_window_size_config(profile)
    x = current["x"] if current else 0
    y = current["y"] if current else 0
    if current:
        x += (current["width"] - width) // 2
        y += (current["height"] - height) // 2

    work_area = _get_work_area_bounds()
    if work_area:
        left, top, work_width, work_height = work_area
        x = min(max(x, left), left + max(work_width - width, 0))
        y = min(max(y, top), top + max(work_height - height, 0))

    # pywebview stores min_size for new native resize requests. The custom
    # resize handles also receive these limits through _get_window_geometry.
    window.min_size = minimum_size
    window_state["profile"] = profile
    try:
        window.move(int(x), int(y))
        window.resize(int(width), int(height))
    except Exception:
        return _get_window_geometry(window)
    return _get_window_geometry(window)


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
    remote_manager = server_ref.get("remote_manager")
    if remote_manager is not None:
        try:
            remote_manager.shutdown()
        except Exception:
            pass
    server = server_ref.get("server")
    if server is not None:
        server.should_exit = True


def _apply_pending_update() -> bool:
    """Spawn the staged installer, then tear down the running app so the new
    exe can replace the locked file and relaunch."""
    def _quit_after_update() -> None:
        exit_requested.set()
        _stop_server()
        window = window_ref.get("window")
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass

    from updater import apply_update

    return apply_update(on_quit=_quit_after_update)


def _capture_native_drop(event) -> None:
    """Keep the absolute paths supplied by pywebview's WebView2 drop bridge."""
    paths = []
    try:
        files = (event or {}).get("dataTransfer", {}).get("files", [])
        for file_info in files:
            if not isinstance(file_info, dict):
                continue
            file_path = file_info.get("pywebviewFullPath")
            if file_path:
                paths.append(str(file_path))
    except Exception:
        paths = []

    # Keep only the latest drop. This prevents a copy-mode drop from becoming
    # stale input if the next drop is handled in reference mode.
    with native_drop_condition:
        native_drop_paths[:] = paths
        native_drop_condition.notify_all()


def _attach_native_drop_listener() -> None:
    """Enable pywebview's WebView2 additional-object file path handling."""
    global native_drop_document, native_drop_targets

    window = window_ref.get("window")
    if window is None:
        return

    try:
        document = window.dom.document
        if document is not native_drop_document:
            document.on("drop", _capture_native_drop)
            native_drop_document = document
            native_drop_targets = [document]

        # The upload modal stops propagation at the modal element, so a
        # document-only listener cannot see drops made inside the dialog.
        # Attach there as well; stopPropagation does not block other listeners
        # registered on the same element.
        upload_modal = window.dom.get_element("#uploadModal")
        if upload_modal is not None and not any(
            target is upload_modal for target in native_drop_targets
        ):
            upload_modal.on("drop", _capture_native_drop)
            native_drop_targets.append(upload_modal)
    except Exception:
        # The normal browser FileList and the native file picker remain usable
        # if the optional pywebview DOM bridge is unavailable.
        native_drop_document = None
        native_drop_targets = []


class NativeWindowApi:
    """Expose the small set of native window actions used by the custom title bar."""

    @staticmethod
    def clear_dropped_files() -> None:
        with native_drop_condition:
            native_drop_paths.clear()

    @staticmethod
    def focus_webview() -> bool:
        return _focus_native_webview()

    @staticmethod
    def read_dropped_files():
        """Return validated absolute paths captured from the latest OS drop."""
        with native_drop_condition:
            if not native_drop_paths:
                native_drop_condition.wait(timeout=0.8)
            pending_paths = list(native_drop_paths)
            native_drop_paths.clear()

        files = []
        seen = set()
        for raw_path in pending_paths:
            try:
                file_path = Path(raw_path).expanduser().resolve(strict=True)
                if not file_path.is_file():
                    continue
                key = os.path.normcase(str(file_path))
                if key in seen:
                    continue
                file_size = file_path.stat().st_size
            except (OSError, RuntimeError, TypeError, ValueError):
                continue

            seen.add(key)
            files.append({
                "name": file_path.name,
                "path": str(file_path),
                "size": file_size,
            })
        return files

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
    def begin_native_drag(screen_x=None, screen_y=None) -> bool:
        """Start an OS-driven window move via the non-client hit test.

        Works in both the frameless (custom title bar) and caption (native
        title bar) modes, and gives edge snapping / maximize restore for free.
        """
        window = window_ref.get("window")
        if window is None:
            return False
        handle = _get_native_window_handle(window)
        if handle is None:
            return False
        try:
            import ctypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            user32 = ctypes.windll.user32
            cursor = POINT()
            ok = user32.GetCursorPos(ctypes.byref(cursor))
            lparam = ((int(cursor.y) & 0xFFFF) << 16) | (int(cursor.x) & 0xFFFF)
            hwnd = ctypes.c_void_p(handle)
            user32.ReleaseCapture()
            res = user32.SendMessageW(hwnd, 0x00A1, 2, lparam)  # WM_NCLBUTTONDOWN, HTCAPTION
            print(f"[drag] begin_native_drag ok={ok} pos=({cursor.x},{cursor.y}) hwnd={int(handle)} res={res}", file=sys.stderr)
            return True
        except Exception as exc:
            print(f"[drag] begin_native_drag error={exc!r}", file=sys.stderr)
            return False

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
    def set_window_profile(profile: str):
        """Switch between the editable onboarding and default window profiles."""
        return _resize_window_for_profile(str(profile or ""))

    @staticmethod
    def set_titlebar_mode(mode: str) -> bool:
        """Switch between the custom in-app title bar and the native caption bar.

        Returns True when the native Windows titlebar is now active.
        """
        native = str(mode).strip().lower() == "native"
        window = window_ref.get("window")
        if window is not None:
            _apply_window_caption(window, native)
        return native

    @staticmethod
    def close_window() -> None:
        window = window_ref.get("window")
        if window is not None:
            try:
                window.hide()
            except Exception:
                pass

    @staticmethod
    def exit_application() -> None:
        exit_requested.set()
        _stop_server()
        window = window_ref.get("window")
        if window is not None:
            try:
                window.destroy()
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


def _get_window_titlebar_setting() -> bool:
    """Return True when the saved titlebar_mode is 'native'."""
    try:
        data_dir = Path(os.environ.get("APPDATA", "")) / "Sparkle"
        db_path = data_dir / "clips.db"
        if not db_path.exists():
            return False
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute("SELECT value FROM settings WHERE key = 'titlebar_mode'").fetchone()
        finally:
            conn.close()
        return bool(row and row[0] == "native")
    except Exception:
        return False


def _configure_native_window() -> None:
    _apply_native_chrome()
    _attach_native_drop_listener()


def _apply_native_chrome() -> None:
    """Apply the caption/resize frame once the native handle exists.

    ``webview.start(func)`` runs ``func`` on a background thread before the
    WinForms window is created, so the native handle is still missing there.
    The same call is therefore repeated from the ``loaded`` event, by which
    point the handle is available. Once the style is applied, page navigation
    does not touch the Win32 frame again; changing the setting explicitly is
    the only operation that reapplies it.
    """
    window = window_ref.get("window")
    if window is None:
        return
    _enable_native_resize(window)
    _apply_window_caption(window, _get_window_titlebar_setting())


def _build_tray_image():
    from PIL import Image, ImageDraw

    icon_path = get_resource_dir() / "Icon.png"
    try:
        with Image.open(icon_path) as source:
            resampling = getattr(Image, "Resampling", Image)
            return source.convert("RGBA").resize((64, 64), resampling.LANCZOS)
    except Exception:
        pass

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
    return pystray.Icon("Sparkle", _build_tray_image(), "Sparkle", menu)


def _cleanup_old_exe_backup() -> None:
    """Remove the previous exe left behind by an installer run (.old)."""
    if not is_frozen():
        return
    try:
        backup = Path(sys.executable).resolve().with_suffix(".old")
        if backup.is_file():
            backup.unlink()
    except OSError:
        pass


def _check_update_in_background() -> None:
    try:
        check_for_update()
    except Exception:
        pass


def _is_app_server_running() -> bool:
    """Return True only when the configured port is serving this application."""
    try:
        with urlopen(f"http://{HOST}:{PORT}/health", timeout=1.0) as response:
            body = response.read(256)
            return response.status == 200 and b'"status"' in body and b'"ok"' in body and b'"app":"Sparkle"' in body
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
    if "--sparkle-install" in sys.argv[1:]:
        # 新exeがインストーラとして起動された場合。旧プロセスの終了を待って
        # 自分を置き換え、通常起動し直す。サーバー/ウィンドウは立ち上げない。
        try:
            from updater import run_installer

            run_installer()
        finally:
            sys.exit(0)

    _cleanup_old_exe_backup()

    try:
        migration_required = bool(get_migration_status().get("required"))
        if not migration_required:
            ensure_post_migration_onboarding()
        setup_required = bool(get_setup_status().get("required"))
        post_migration_onboarding = get_post_migration_onboarding_status()
        post_migration_required = bool(post_migration_onboarding.get("required"))
        tutorial_status = get_setup_tutorial_status()
        tutorial_required = bool(tutorial_status.get("required"))
        tutorial_stage = tutorial_status.get("stage")
        debug_setup = DEBUG_SETUP_FLAG in sys.argv[1:]
        debug_tutorial = DEBUG_TUTORIAL_FLAG in sys.argv[1:]
        debug_extension_guide = DEBUG_EXTENSION_GUIDE_FLAG in sys.argv[1:]
        if _is_app_server_running():
            # 既に起動中(二重起動) → 既存のネイティブウィンドウを前面表示
            _activate_existing_app()
            return
        if _is_port_in_use():
            message = (
                f"ポート {PORT} が別のアプリに使用されています。\n"
                f"Sparkleを起動する前に、ポート {PORT} を使用しているアプリを終了してください。\n\n"
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

        # Remote Web access is optional. Reconnect its configured route
        # asynchronously so startup remains usable even if
        # the Tailscale service is still coming up.
        remote_manager = server_ref.get("remote_manager")
        if remote_manager is not None:
            threading.Thread(
                target=remote_manager.start_on_launch,
                name="sparkle-remote-access-start",
                daemon=True,
            ).start()

        # 起動時に更新をバックグラウンドで確認する。ネットワーク/表示を待たない。
        threading.Thread(target=_check_update_in_background, daemon=True).start()

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

        os.environ["SPARKLE_EXECUTABLE"] = _get_exe_path()
        if debug_extension_guide:
            initial_page = "ExtensionGuide?debug=extension"
        elif debug_tutorial:
            initial_page = "Tutorial?debug=tutorial"
        elif migration_required:
            initial_page = "Migration"
        elif debug_setup:
            initial_page = "Setup?debug=setup"
        elif post_migration_required:
            stage = post_migration_onboarding.get("stage")
            initial_page = "ExtensionGuide?source=migration" if stage == "extension" else "Setup?source=migration"
        elif setup_required:
            initial_page = "Setup"
        elif tutorial_required:
            initial_page = "ExtensionGuide?source=setup" if tutorial_stage == "extension" else "Tutorial"
        else:
            initial_page = "Home"

        initial_window_profile = _window_profile_for_page(initial_page)
        window_state["profile"] = initial_window_profile
        window_width, window_height, minimum_window_size = _get_window_size_config(initial_window_profile)
        window = webview.create_window(
            "Sparkle",
            url=f"http://{HOST}:{PORT}/{initial_page}",
            width=window_width,
            height=window_height,
            min_size=minimum_window_size,
            resizable=True,
            frameless=True,
            easy_drag=False,
            text_select=True,
            # Keep the native WebView at its default 100% zoom.  The app has
            # a fixed workbench layout, so browser zoom would make its sizing
            # and drag/resize affordances inconsistent.
            zoomable=False,
            background_color="#202020",
            hidden=(
                "--hidden" in sys.argv[1:]
                and not migration_required
                and not setup_required
                and not post_migration_required
                and not tutorial_required
                and not debug_setup
                and not debug_tutorial
                and not debug_extension_guide
            ),
            js_api=NativeWindowApi(),
        )
        window_ref["window"] = window
        window.events.loaded += _attach_native_drop_listener
        window.events.loaded += _apply_native_chrome
        window.events.loaded += _focus_native_webview
        window.events.closing += _on_window_closing

        icon = _build_tray_icon()
        tray_thread = threading.Thread(target=icon.run, daemon=True)
        tray_thread.start()

        webview.start(
            _configure_native_window,
            debug=not is_frozen(),
            private_mode=False,
            storage_path=str(WEBVIEW_STORAGE_PATH),
        )

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

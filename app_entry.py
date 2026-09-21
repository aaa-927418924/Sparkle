"""exe化した際のエントリーポイント。
uvicornサーバーをバックグラウンドスレッドで起動し、メインスレッドでは
タスクトレイアイコンを表示する。コンソールなしで起動されるため、
標準出力/エラーはログファイルにリダイレクトし、失敗時はメッセージボックスで知らせる。
"""

import os
import socket
import sys
import tempfile
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
# Force a fresh top-level document after frontend changes. WebView2 keeps a
# persistent profile, so the route itself also needs a versioned URL.
FRONTEND_CACHE_TOKEN = "sidebar-icons-left-v5-shell-scroll-v1-legacy-sort-v1-remote-mcp-disabled-v1-native-backdrop-v9"

# DWM system backdrop values used by Windows 11.  The native material is only
# enabled when Windows' own transparency preference is enabled; the disabled
# path keeps pywebview's existing opaque background path unchanged.
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_NONE = 1
# Desktop Acrylic is the native system backdrop that reacts to content behind
# the window.  This is still DWM-owned; the WebView only exposes the material
# through its transparent controller surface.
DWMSBT_TRANSIENTWINDOW = 3
WCA_ACCENT_POLICY = 19
ACCENT_DISABLED = 0
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4


def _get_port() -> int:
    try:
        port = int(os.environ.get("SPARKLE_PORT", "8000"))
    except (TypeError, ValueError):
        return 8000
    return port if 1 <= port <= 65535 else 8000


PORT = _get_port()
LOG_PATH = get_app_data_dir() / "app.log"
STDIO_LOG_PATH = Path(
    os.environ.get("SPARKLE_STDIO_LOG_PATH", str(get_app_data_dir() / "stdio.log"))
)
WEBVIEW_STORAGE_PATH = get_app_data_dir() / "webview"
WEBVIEW_STORAGE_PATH.mkdir(parents=True, exist_ok=True)


def _open_stdio_log():
    """Open the normal stdio log, with a writable test-host fallback."""
    try:
        STDIO_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        return open(STDIO_LOG_PATH, "a", encoding="utf-8", buffering=1)
    except OSError:
        try:
            fallback = Path(tempfile.gettempdir()) / "Sparkle" / "stdio.log"
            fallback.parent.mkdir(parents=True, exist_ok=True)
            return open(fallback, "a", encoding="utf-8", buffering=1)
        except OSError:
            return open(os.devnull, "a", encoding="utf-8", buffering=1)


# --noconsoleビルドでは sys.stdout / sys.stderr が None になり、
# それに依存するライブラリ(uvicornのログ設定など)がクラッシュするため、
# 最初にログファイルへリダイレクトしておく。
if sys.stdout is None or sys.stderr is None:
    _stream = _open_stdio_log()
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
    "native_titlebar": None,
    "native_titlebar_handle": None,
    "native_backdrop_enabled": None,
    "native_backdrop_handle": None,
    "native_backdrop_mode": None,
    "native_system_backdrop_applied": None,
    "native_acrylic_backdrop_applied": None,
    "native_surface_mode": None,
    "native_surface_ready": False,
    "native_dwm_diagnostics": {},
    "native_document_script_id": None,
    "native_document_script_core": None,
    "native_document_script_core_key": None,
    "native_document_script_pending": False,
    "native_document_script_desired": False,
    "native_navigation_listener_registered": False,
    "native_layout_listener_registered": False,
    "native_window_visible": False,
    "native_initial_navigation_completed": False,
    "transparency_listener_registered": False,
    "native_backdrop_retry_generation": 0,
    "native_backdrop_retry_timers": [],
    "native_navigation_pending": False,
}
native_drop_condition = threading.Condition()
native_drop_paths = []
native_drop_document = None
native_drop_targets = []


def _is_windows_transparency_enabled() -> bool:
    """Return Windows 11's user preference for translucent system surfaces.

    Windows stores the Transparency effects switch in the Personalize key. A
    missing value means the Windows default, which is enabled; read failures
    remain conservative and keep the existing opaque application surface.
    """
    if os.name != "nt":
        return False

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            0,
            winreg.KEY_READ,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "EnableTransparency")
        try:
            return int(value) != 0
        except (TypeError, ValueError):
            return bool(value)
    except FileNotFoundError:
        return True
    except Exception:
        return False


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


def _frontend_url(page: str) -> str:
    separator = "&" if "?" in page else "?"
    native_hint = "&nativeBackdrop=1" if _is_windows_transparency_enabled() else ""
    return f"http://{HOST}:{PORT}/{page}{separator}ui={FRONTEND_CACHE_TOKEN}{native_hint}"


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
        remote_manager = RemoteAccessManager(main_port=PORT, remote_mcp_enabled=False)
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


def _begin_native_nonclient_interaction(window, handle, hit_test: int) -> bool:
    """Start a Windows move/resize loop from the WinForms UI thread.

    WebView2 sends a JavaScript API call to a worker thread. ``ReleaseCapture``
    is thread-owned, however, so calling it from that worker does not release
    the WebView control's mouse capture. Likewise, posting
    ``WM_NCLBUTTONDOWN`` from the worker does not reliably enter the Form's
    native move/size loop. Queue the whole operation on the WinForms control,
    where both calls run in the same input thread as the WebView.
    """
    if window is None or handle is None or os.name != "nt":
        return False

    try:
        import ctypes

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        get_cursor_pos = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.POINTER(POINT)
        )(("GetCursorPos", user32))
        release_capture = ctypes.WINFUNCTYPE(ctypes.c_int)(
            ("ReleaseCapture", user32)
        )
        send_message = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        )(("SendMessageW", user32))

        def begin_on_ui_thread() -> None:
            cursor = POINT()
            if not get_cursor_pos(ctypes.byref(cursor)):
                return

            # WM_NCLBUTTONDOWN expects the cursor position packed as two words.
            lparam = ((int(cursor.y) & 0xFFFF) << 16) | (int(cursor.x) & 0xFFFF)
            release_capture()
            # This enters the normal Windows modal move/size loop. It must run
            # on the Form's UI thread, but the JS bridge remains free because
            # BeginInvoke only queues this callback.
            send_message(
                ctypes.c_void_p(int(handle)),
                0x00A1,  # WM_NCLBUTTONDOWN
                ctypes.c_size_t(int(hit_test)),
                ctypes.c_ssize_t(lparam),
            )

        native = getattr(window, "native", None)
        if native is None:
            return False

        import clr  # noqa: F401 - initializes pythonnet's System namespace
        from System import Action

        if bool(getattr(native, "InvokeRequired", False)):
            native.BeginInvoke(Action(begin_on_ui_thread))
            return True

        begin_on_ui_thread()
        return True
    except Exception as exc:
        print(f"[window] native non-client interaction failed: {exc!r}", file=sys.stderr)
        return False


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
            try:
                import clr  # noqa: F401 - initializes pythonnet's System namespace
            except ImportError:
                # Some test/browser hosts provide System.Action directly but do
                # not install pythonnet's optional clr module.
                pass
            from System import Action

            webview.Invoke(Action(_focus))
        else:
            _focus()
        return True
    except Exception:
        return False


def _copy_text_to_windows_clipboard(text: str) -> bool:
    """Write Unicode text to the Windows clipboard without relying on WebView focus."""
    if os.name != "nt":
        return False

    import ctypes
    from ctypes import wintypes

    value = str(text)
    buffer = ctypes.create_unicode_buffer(value)
    size = ctypes.sizeof(buffer)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.OpenClipboard.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]

    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

    # Another process can briefly own the clipboard. Retry so a normal copy
    # does not fail just because a clipboard manager is updating its history.
    for _ in range(5):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.03)
    else:
        return False

    handle = None
    try:
        if not user32.EmptyClipboard():
            return False

        # CF_UNICODETEXT (13) expects a UTF-16LE string including its NUL.
        handle = kernel32.GlobalAlloc(0x0002, size)  # GMEM_MOVEABLE
        if not handle:
            return False
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return False
        try:
            ctypes.memmove(pointer, ctypes.addressof(buffer), size)
        finally:
            kernel32.GlobalUnlock(handle)

        if not user32.SetClipboardData(13, handle):  # CF_UNICODETEXT
            return False

        # Ownership transfers to the clipboard after SetClipboardData succeeds.
        handle = None
        return True
    finally:
        if handle:
            kernel32.GlobalFree(handle)
        user32.CloseClipboard()


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


def _apply_window_caption(window, native_titlebar: bool, force: bool = False) -> None:
    """Show or hide the Windows caption bar on a frameless window."""
    if os.name != "nt":
        return

    handle = _get_native_window_handle(window)
    if handle is None:
        return

    handle_key = int(handle)
    if (
        not force
        and
        window_state.get("native_titlebar") is bool(native_titlebar)
        and window_state.get("native_titlebar_handle") == handle_key
    ):
        return

    # A real caption needs more than WS_CAPTION: without SYSMENU, MIN/MAXBOX
    # and THICKFRAME, the native bar renders empty (no minimize/maximize/close
    # buttons). Custom mode drops both the caption and THICKFRAME. Keeping the
    # native sizing frame in a frameless window creates a non-client inset at
    # the top of the WebView, which leaves a visible gap above the custom bar.
    # Custom edge handles use the WebView fallback; the native frame is only
    # needed when the standard Windows caption is enabled.
    _apply_window_style(
        handle,
        (
            lambda style: (style | 0x00C00000 | 0x00080000 | 0x00020000 | 0x00010000 | 0x00040000)
            if native_titlebar
            else (style & ~(0x00C00000 | 0x00040000))
        ),
    )
    # The native backdrop owns the DWM frame extension while it is active.
    # Avoid resetting it to the ordinary pywebview margin before the backdrop
    # state has a chance to reassert itself.
    if not bool(window_state.get("native_backdrop_enabled")):
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


def _native_exception_text(error) -> str:
    try:
        detail = str(error).replace("\r", " ").replace("\n", " ").replace("|", "/")
        return f"{type(error).__name__}:{detail[:240]}"
    except Exception:
        return type(error).__name__


def _native_value_text(value) -> str:
    if value is None:
        return "none"
    try:
        return str(value).replace("\r", " ").replace("\n", " ").replace("|", "/")[:180]
    except Exception as error:
        return _native_exception_text(error)


def _native_hresult_text(value) -> str:
    if value is None:
        return "none"
    try:
        signed = int(value)
        return f"0x{signed & 0xFFFFFFFF:08X}/{signed}"
    except Exception:
        return _native_exception_text(value)


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


def _apply_dwm_backdrop_frame(handle, enabled: bool):
    """Expose the DWM material through the full client area when enabled."""
    if handle is None or os.name != "nt":
        return None

    try:
        import ctypes

        dwmapi = ctypes.WinDLL("dwmapi")
        extend_frame = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_long),
        )(("DwmExtendFrameIntoClientArea", dwmapi))
        margin_value = -1 if enabled else 0
        margins = (ctypes.c_long * 4)(
            margin_value,
            margin_value,
            margin_value,
            margin_value,
        )
        result = int(extend_frame(ctypes.c_void_p(handle), margins))
        window_state["native_dwm_extend_hr"] = result
        window_state["native_dwm_extend_error"] = None
        return result
    except Exception as error:
        window_state["native_dwm_extend_hr"] = None
        window_state["native_dwm_extend_error"] = _native_exception_text(error)
        return None


def _read_native_backdrop_attributes(handle) -> dict:
    """Read back the DWM material attributes for runtime diagnostics."""
    result = {
        "attr38_hr": None,
        "attr38_value": None,
        "error": None,
    }
    if handle is None or os.name != "nt":
        return result

    try:
        import ctypes

        dwmapi = ctypes.WinDLL("dwmapi")
        get_window_attr = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        )(("DwmGetWindowAttribute", dwmapi))
        hwnd = ctypes.c_void_p(handle)
        value = ctypes.c_int()
        hresult = int(
            get_window_attr(
                hwnd,
                DWMWA_SYSTEMBACKDROP_TYPE,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
        )
        result["attr38_hr"] = hresult
        if hresult == 0:
            result["attr38_value"] = int(value.value)
    except Exception as error:
        result["error"] = _native_exception_text(error)
    return result


def _native_backdrop_readback_matches(handle, expected_value: int) -> bool:
    """Return whether DWM currently reports the requested system material."""
    readback = _read_native_backdrop_attributes(handle)
    return bool(
        readback.get("attr38_hr") == 0
        and readback.get("attr38_value") == expected_value
    )


def _apply_native_system_backdrop(handle, enabled: bool) -> bool:
    """Select the native Windows material without using a CSS blur effect."""
    if handle is None or os.name != "nt":
        return False

    try:
        import ctypes

        # A frameless WinForms form has no non-client frame for DWM to carry
        # into the client region. Extend the frame over the full window while
        # the native material is enabled so transparent WebView2 pixels reveal
        # the system backdrop. Clear the extension on the existing opaque path.
        extend_result = _apply_dwm_backdrop_frame(handle, enabled)
        dwmapi = ctypes.WinDLL("dwmapi")
        set_window_attr = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        )(("DwmSetWindowAttribute", dwmapi))

        # The main-window Mica material is intentionally wallpaper-oriented
        # and does not react when another app moves behind Sparkle.  Desktop
        # Acrylic is the native system material that provides the expected
        # behind-window response while keeping all blur/composition work in
        # DWM rather than in CSS.
        requested_backdrop_type = DWMSBT_TRANSIENTWINDOW if enabled else DWMSBT_NONE
        backdrop_value = ctypes.c_int(requested_backdrop_type)
        attr38_result = int(
            set_window_attr(
                ctypes.c_void_p(handle),
                DWMWA_SYSTEMBACKDROP_TYPE,
                ctypes.byref(backdrop_value),
                ctypes.sizeof(backdrop_value),
            )
        )

        # Attribute 39 is DWMWA_LAST (the enum sentinel), not a writable alpha
        # attribute. WebView2 transparency is configured on the WinForms and
        # WebView2 surfaces below; DWM material convergence is verified only by
        # reading back attribute 38.
        readback = _read_native_backdrop_attributes(handle)
        window_state["native_dwm_diagnostics"] = {
            "extend_hr": extend_result,
            "extend_error": window_state.get("native_dwm_extend_error"),
            "attr38_hr": attr38_result,
            "attr38_requested": requested_backdrop_type,
            "read38_hr": readback.get("attr38_hr"),
            "read38_value": readback.get("attr38_value"),
            "read38_converged": (
                readback.get("attr38_hr") == 0
                and readback.get("attr38_value") == requested_backdrop_type
            ),
            "error": None,
        }

        # Do not fall back to the older Mica attribute here.  The requested
        # material is Desktop Acrylic (TRANSIENTWINDOW), and selecting Mica
        # would make the visual depend on the wallpaper instead of the window
        # behind Sparkle.  The caller can use legacy Win32 Acrylic only when
        # this SystemBackdrop call is unavailable.
        return attr38_result == 0
    except Exception as error:
        previous = window_state.get("native_dwm_diagnostics") or {}
        window_state["native_dwm_diagnostics"] = {
            "extend_hr": previous.get("extend_hr", window_state.get("native_dwm_extend_hr")),
            "extend_error": previous.get("extend_error", window_state.get("native_dwm_extend_error")),
            "attr38_hr": previous.get("attr38_hr"),
            "read38_hr": previous.get("read38_hr"),
            "read38_value": previous.get("read38_value"),
            "read38_converged": previous.get("read38_converged"),
            "error": _native_exception_text(error),
        }
        return False


def _apply_native_acrylic_backdrop(handle, enabled: bool, background_color: str) -> bool:
    """Apply Win32 Acrylic for frameless WinForms/WebView2 windows."""
    if handle is None or os.name != "nt":
        return False

    try:
        import ctypes

        class AccentPolicy(ctypes.Structure):
            _fields_ = [
                ("accent_state", ctypes.c_int),
                ("accent_flags", ctypes.c_int),
                ("gradient_color", ctypes.c_uint),
                ("animation_id", ctypes.c_int),
            ]

        class WindowCompositionAttributeData(ctypes.Structure):
            _fields_ = [
                ("attribute", ctypes.c_int),
                ("data", ctypes.POINTER(AccentPolicy)),
                ("size_of_data", ctypes.c_size_t),
            ]

        user32 = ctypes.WinDLL("user32")
        set_window_composition_attribute = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.POINTER(WindowCompositionAttributeData),
        )(("SetWindowCompositionAttribute", user32))

        policy = AccentPolicy()
        policy.accent_state = (
            ACCENT_ENABLE_ACRYLICBLURBEHIND if enabled else ACCENT_DISABLED
        )
        if enabled:
            color = str(background_color or "#202231").lstrip("#")
            if len(color) != 6:
                color = "202231"
            red = int(color[0:2], 16)
            green = int(color[2:4], 16)
            blue = int(color[4:6], 16)
            # AccentPolicy uses an ABGR packed color. Keep the existing shell
            # tone as the native Acrylic tint; this is not an OFF fallback.
            # This path is only a fallback for runtimes where the Windows 11
            # SystemBackdrop API is unavailable.  Keep its tint lighter so
            # the behind-window Acrylic remains visible without changing the
            # existing opaque OFF palette.
            policy.gradient_color = (0xB8 << 24) | (blue << 16) | (green << 8) | red
        else:
            policy.gradient_color = 0

        data = WindowCompositionAttributeData(
            WCA_ACCENT_POLICY,
            ctypes.pointer(policy),
            ctypes.sizeof(policy),
        )
        return bool(
            set_window_composition_attribute(
                ctypes.c_void_p(handle), ctypes.byref(data)
            )
        )
    except Exception:
        return False


def _get_native_webview_control(native):
    if native is None:
        return None
    webview = getattr(native, "webview", None)
    if webview is None:
        webview = getattr(getattr(native, "browser", None), "webview", None)
    return webview


def _get_core_webview2(webview):
    if webview is None:
        return None
    try:
        return webview.CoreWebView2
    except Exception:
        return None


def _get_core_webview2_key(core):
    if core is None:
        return None
    try:
        return int(core.GetHashCode())
    except Exception:
        return str(core)


def _sync_native_document_class(webview, enabled: bool) -> None:
    """Update the already loaded document without changing its navigation."""
    if webview is None:
        return

    state = "true" if enabled else "false"
    try:
        webview.ExecuteScriptAsync(
            "(function applySparkleBackdropClass() {"
            "var root = document.documentElement;"
            "if (!root) return;"
            "var enabled = " + state + ";"
            "root.classList.toggle('native-backdrop-enabled', enabled);"
            "root.dataset.nativeBackdrop = enabled ? 'on' : 'off';"
            "})();"
        )
    except Exception:
        pass


def _install_native_document_script(window, enabled: bool) -> bool:
    """Install the native-only WebView2 document bootstrap for future pages."""
    native = getattr(window, "native", None) if window is not None else None
    webview = _get_native_webview_control(native)
    core = _get_core_webview2(webview)
    core_key = _get_core_webview2_key(core)
    window_state["native_document_script_desired"] = bool(enabled)
    if core is None:
        return False

    previous_core = window_state.get("native_document_script_core")
    previous_id = window_state.get("native_document_script_id")
    if not enabled:
        if previous_core is not None and previous_id:
            try:
                previous_core.RemoveScriptToExecuteOnDocumentCreated(previous_id)
            except Exception:
                pass
        window_state["native_document_script_id"] = None
        window_state["native_document_script_core"] = None
        window_state["native_document_script_core_key"] = None
        window_state["native_document_script_pending"] = False
        return True

    if (
        window_state.get("native_document_script_core_key") == core_key
        and (previous_id or window_state.get("native_document_script_pending"))
    ):
        return True

    if previous_core is not None and previous_id:
        try:
            previous_core.RemoveScriptToExecuteOnDocumentCreated(previous_id)
        except Exception:
            pass

    script = (
        "(function(){"
        "var root=document.documentElement;"
        "if(!root)return;"
        "root.classList.add('native-backdrop-enabled');"
        "root.dataset.nativeBackdrop='on';"
        "})();"
    )

    try:
        task = core.AddScriptToExecuteOnDocumentCreatedAsync(script)
        window_state["native_document_script_pending"] = True

        def finish(completed_task):
            window_state["native_document_script_pending"] = False
            try:
                script_id = str(completed_task.Result)
            except Exception:
                return
            if not window_state.get("native_document_script_desired"):
                try:
                    core.RemoveScriptToExecuteOnDocumentCreated(script_id)
                except Exception:
                    pass
                return
            window_state["native_document_script_id"] = script_id
            window_state["native_document_script_core"] = core
            window_state["native_document_script_core_key"] = core_key

        try:
            from System import Action, String
            from System.Threading.Tasks import Task

            task.ContinueWith(Action[Task[String]](finish))
        except Exception:
            finish(task)
        return True
    except Exception:
        window_state["native_document_script_pending"] = False
        return False


def _reassert_native_material(window, *, mode_override=None) -> bool:
    """Reassert only the active DWM material, without touching WebView2 state."""
    if window is None or os.name != "nt":
        return False

    handle = _get_native_window_handle(window)
    if handle is None:
        return False

    mode = (
        mode_override
        if mode_override is not None
        else window_state.get("native_backdrop_mode")
    )
    background_color = str(getattr(window, "background_color", "#202231"))
    if mode == "system":
        _apply_native_system_backdrop(handle, True)
        return _native_backdrop_readback_matches(handle, DWMSBT_TRANSIENTWINDOW)
    elif mode == "acrylic":
        if _apply_native_acrylic_backdrop(handle, True, background_color):
            _apply_dwm_backdrop_frame(handle, True)
        return True
    else:
        _apply_native_system_backdrop(handle, False)
        _apply_dwm_frame_margin(handle, _get_window_titlebar_setting())
        return _native_backdrop_readback_matches(handle, DWMSBT_NONE)


def _apply_native_backdrop(
    window, enabled: bool, diagnostic_phase: str = "sync", reassert: bool = False
) -> None:
    """Apply one native material and keep the WebView2 surface in that state."""
    if window is None or os.name != "nt":
        return

    native = getattr(window, "native", None)
    handle = _get_native_window_handle(window)
    if native is None or handle is None:
        return

    background_color = str(getattr(window, "background_color", "#202231"))
    previous_enabled = window_state.get("native_backdrop_enabled")
    previous_mode = window_state.get("native_backdrop_mode")
    handle_changed = window_state.get("native_backdrop_handle") != int(handle)
    state_changed = (
        previous_enabled is None
        or bool(previous_enabled) != bool(enabled)
        or handle_changed
        or previous_mode is None
    )

    system_backdrop_applied = bool(
        window_state.get("native_system_backdrop_applied")
    )
    acrylic_backdrop_applied = bool(
        window_state.get("native_acrylic_backdrop_applied")
    )
    mode = previous_mode or "off"

    if state_changed:
        if enabled:
            # SystemBackdrop is the requested Desktop Acrylic material. Clear
            # only a stale legacy fallback before selecting the active mode.
            _apply_native_acrylic_backdrop(handle, False, background_color)
            system_backdrop_applied = _apply_native_system_backdrop(handle, True)
            acrylic_backdrop_applied = False
            if system_backdrop_applied:
                mode = "system"
            else:
                # Do not leave a failed SystemBackdrop frame extension behind
                # while switching to the legacy fallback.
                _apply_native_system_backdrop(handle, False)
                acrylic_backdrop_applied = _apply_native_acrylic_backdrop(
                    handle, True, background_color
                )
                if acrylic_backdrop_applied:
                    _apply_dwm_backdrop_frame(handle, True)
                    mode = "acrylic"
                else:
                    mode = "off"
                    _apply_dwm_frame_margin(
                        handle, _get_window_titlebar_setting()
                    )
        else:
            # Clear both native implementations on the OFF transition so a
            # previous process version cannot leave a stale material active.
            _apply_native_acrylic_backdrop(handle, False, background_color)
            _apply_native_system_backdrop(handle, False)
            _apply_dwm_frame_margin(handle, _get_window_titlebar_setting())
            system_backdrop_applied = False
            acrylic_backdrop_applied = False
            mode = "off"

    show_native_material = bool(
        enabled and mode in {"system", "acrylic"}
    )
    native_visible = bool(getattr(native, "Visible", False))
    initial_navigation_completed = bool(
        window_state.get("native_initial_navigation_completed")
    )
    if native_visible:
        window_state["native_window_visible"] = True

    webview = _get_native_webview_control(native)
    surface_mode = "transparent" if show_native_material else "opaque"
    surface_changed = window_state.get("native_surface_mode") != surface_mode
    if webview is not None and not window_state.get("native_surface_ready"):
        surface_changed = True

    surface_errors = []
    surface_backcolor_before = None
    surface_backcolor_after = None
    webview_background_before = None
    webview_background_after = None

    def record_surface_error(label, error):
        surface_errors.append(f"{label}:{_native_exception_text(error)}")

    try:
        try:
            surface_backcolor_before = _native_value_text(native.BackColor)
        except Exception as error:
            record_surface_error("BackColor.read-before", error)
        if webview is not None:
            try:
                webview_background_before = _native_value_text(
                    webview.DefaultBackgroundColor
                )
            except Exception as error:
                record_surface_error("DefaultBackgroundColor.read-before", error)

        from System.Drawing import Color, ColorTranslator

        if surface_changed:
            if show_native_material:
                transparent_color = Color.FromArgb(0, 0, 0, 0)
                try:
                    import System.Windows.Forms as WinForms
                except Exception as error:
                    WinForms = None
                    record_surface_error("WinForms.import", error)

                if WinForms is not None:
                    try:
                        native.SetStyle(
                            WinForms.ControlStyles.SupportsTransparentBackColor,
                            True,
                        )
                    except Exception as error:
                        record_surface_error("SetStyle.SupportsTransparentBackColor", error)
                    try:
                        # Prevent a top-level Form erase from replacing the DWM
                        # material with a white surface after a move.
                        native.SetStyle(WinForms.ControlStyles.Opaque, True)
                    except Exception as error:
                        record_surface_error("SetStyle.Opaque", error)
                try:
                    native.BackColor = transparent_color
                except Exception as error:
                    record_surface_error("BackColor.set-transparent", error)
                try:
                    surface_backcolor_after = _native_value_text(native.BackColor)
                except Exception as error:
                    record_surface_error("BackColor.read-after", error)
                if webview is not None:
                    try:
                        webview.DefaultBackgroundColor = transparent_color
                    except Exception as error:
                        record_surface_error(
                            "DefaultBackgroundColor.set-transparent", error
                        )
                    try:
                        webview_background_after = _native_value_text(
                            webview.DefaultBackgroundColor
                        )
                    except Exception as error:
                        record_surface_error(
                            "DefaultBackgroundColor.read-after", error
                        )
            else:
                # This is the original opaque path. Do not add a new OFF
                # fallback color for the transparency feature.
                if not background_color:
                    return
                try:
                    import System.Windows.Forms as WinForms
                except Exception as error:
                    WinForms = None
                    record_surface_error("WinForms.import", error)

                if WinForms is not None:
                    try:
                        native.SetStyle(
                            WinForms.ControlStyles.SupportsTransparentBackColor,
                            False,
                        )
                    except Exception as error:
                        record_surface_error("SetStyle.SupportsTransparentBackColor", error)
                    try:
                        native.SetStyle(WinForms.ControlStyles.Opaque, False)
                    except Exception as error:
                        record_surface_error("SetStyle.Opaque", error)
                try:
                    opaque_color = ColorTranslator.FromHtml(background_color)
                    native.BackColor = opaque_color
                except Exception as error:
                    record_surface_error("BackColor.set-opaque", error)
                try:
                    surface_backcolor_after = _native_value_text(native.BackColor)
                except Exception as error:
                    record_surface_error("BackColor.read-after", error)
                if webview is not None:
                    try:
                        webview.DefaultBackgroundColor = Color.FromArgb(
                            255,
                            int(background_color.lstrip("#")[0:2], 16),
                            int(background_color.lstrip("#")[2:4], 16),
                            int(background_color.lstrip("#")[4:6], 16),
                        )
                    except Exception as error:
                        record_surface_error(
                            "DefaultBackgroundColor.set-opaque", error
                        )
                    try:
                        webview_background_after = _native_value_text(
                            webview.DefaultBackgroundColor
                        )
                    except Exception as error:
                        record_surface_error(
                            "DefaultBackgroundColor.read-after", error
                        )

            window_state["native_surface_mode"] = surface_mode
            window_state["native_surface_ready"] = webview is not None
            try:
                native.Invalidate(True)
            except Exception as error:
                record_surface_error("Invalidate", error)
            if show_native_material:
                # Surface writes can rebuild the DWM frame. Reassert exactly
                # once, without changing the controller or its transparency.
                try:
                    _reassert_native_material(window, mode_override=mode)
                except Exception as error:
                    record_surface_error("native-material.reassert", error)

        try:
            _install_native_document_script(window, show_native_material)
            _sync_native_document_class(webview, show_native_material)
        except Exception as error:
            record_surface_error("document-sync", error)
    except Exception as error:
        record_surface_error("surface-block", error)

    if reassert and not surface_changed:
        try:
            _reassert_native_material(window)
        except Exception as error:
            record_surface_error("native-material.reassert", error)

    window_state["native_backdrop_enabled"] = show_native_material
    window_state["native_backdrop_handle"] = int(handle)
    window_state["native_backdrop_mode"] = mode
    window_state["native_system_backdrop_applied"] = system_backdrop_applied
    window_state["native_acrylic_backdrop_applied"] = acrylic_backdrop_applied

    dwm_diagnostics = window_state.get("native_dwm_diagnostics") or {}
    dwm_readback = _read_native_backdrop_attributes(handle)
    read38_converged = (
        dwm_readback.get("attr38_hr") == 0
        and dwm_readback.get("attr38_value")
        == dwm_diagnostics.get("attr38_requested")
    )

    try:
        with LOG_PATH.open("a", encoding="utf-8") as log:
            log.write(
                "[native-backdrop] "
                f"phase={diagnostic_phase} "
                f"enabled={enabled} mode={mode} system={system_backdrop_applied} "
                f"acrylic={acrylic_backdrop_applied} shown={show_native_material} "
                f"surface={surface_mode} surface_changed={surface_changed} "
                f"visible={native_visible} initial_done={initial_navigation_completed} "
                f"transparent={getattr(window, 'transparent', None)} "
                f"extend_hr={_native_hresult_text(dwm_diagnostics.get('extend_hr'))} "
                f"extend_error={_native_value_text(dwm_diagnostics.get('extend_error'))} "
                f"attr38_hr={_native_hresult_text(dwm_diagnostics.get('attr38_hr'))} "
                f"attr38_requested={_native_value_text(dwm_diagnostics.get('attr38_requested'))} "
                f"attr39_hr=not-applicable "
                f"dwm_error={_native_value_text(dwm_diagnostics.get('error'))} "
                f"read38_hr={_native_hresult_text(dwm_readback.get('attr38_hr'))} "
                f"read38={_native_value_text(dwm_readback.get('attr38_value'))} "
                f"read38_converged={_native_value_text(read38_converged)} "
                f"read39_hr=not-applicable read39=not-applicable "
                f"readback_error={_native_value_text(dwm_readback.get('error'))} "
                f"surface_errors={_native_value_text(';'.join(surface_errors) or 'none')} "
                f"backcolor_before={_native_value_text(surface_backcolor_before)} "
                f"backcolor_after={_native_value_text(surface_backcolor_after)} "
                f"webview_bg_before={_native_value_text(webview_background_before)} "
                f"webview_bg_after={_native_value_text(webview_background_after)} "
                f"handle={int(handle)}\n"
            )
    except Exception:
        pass

    return surface_changed


def _sync_native_backdrop(
    *, reassert: bool = False, diagnostic_phase: str = "sync"
) -> None:
    """Re-read the Windows preference and apply it on the WinForms UI thread."""
    window = window_ref.get("window")
    native = getattr(window, "native", None) if window is not None else None
    if native is None:
        return

    enabled = _is_windows_transparency_enabled()

    def apply() -> None:
        surface_changed = _apply_native_backdrop(
            window,
            enabled,
            diagnostic_phase=diagnostic_phase,
            reassert=reassert,
        )

    try:
        if bool(getattr(native, "InvokeRequired", False)):
            try:
                import clr  # noqa: F401 - initializes pythonnet's System namespace
            except ImportError:
                pass
            from System import Action

            native.BeginInvoke(Action(apply))
        else:
            apply()
    except Exception:
        pass


def _cancel_native_backdrop_retries() -> None:
    """Cancel the current finite retry sequence and invalidate its callbacks."""
    generation = int(window_state.get("native_backdrop_retry_generation") or 0) + 1
    timers = list(window_state.get("native_backdrop_retry_timers") or [])
    window_state["native_backdrop_retry_generation"] = generation
    window_state["native_backdrop_retry_timers"] = []
    for timer in timers:
        try:
            timer.cancel()
        except Exception:
            pass


def _native_backdrop_readback_matches_current(window) -> bool:
    """Check the current preference and mode against DWM attribute 38."""
    if window is None or os.name != "nt":
        return False

    mode = window_state.get("native_backdrop_mode")
    if mode == "acrylic":
        # The legacy fallback does not use SystemBackdrop attribute 38 as its
        # source of truth. Its successful Win32 composition call is enough.
        return True

    handle = _get_native_window_handle(window)
    if handle is None:
        return False

    transparency_enabled = _is_windows_transparency_enabled()
    if transparency_enabled and mode == "system":
        expected = DWMSBT_TRANSIENTWINDOW
    elif not transparency_enabled:
        expected = DWMSBT_NONE
    else:
        # The system material has not been selected yet, so let the retry write
        # it before attempting the first convergence check.
        return False
    return _native_backdrop_readback_matches(handle, expected)


def _run_native_backdrop_retry(token: int, diagnostic_phase: str, attempt: int) -> None:
    """Reapply only while the bounded sequence has not converged."""
    if exit_requested.is_set() or token != window_state.get(
        "native_backdrop_retry_generation"
    ):
        return

    window = window_ref.get("window")
    native = getattr(window, "native", None) if window is not None else None
    if window is None or native is None:
        return
    if not bool(getattr(native, "Visible", False)):
        # Keep the remaining timers alive; the shown event can race the first
        # timer during pywebview's transparent-window show/hide workaround.
        return

    if attempt > 1 and _native_backdrop_readback_matches_current(window):
        _cancel_native_backdrop_retries()
        return

    _sync_native_backdrop(
        reassert=True,
        diagnostic_phase=f"{diagnostic_phase}-retry-{attempt}",
    )


def _schedule_native_backdrop_retries(
    delays: tuple[float, ...], diagnostic_phase: str
) -> None:
    """Retry DWM writes at bounded delays until attribute 38 converges."""
    if os.name != "nt" or exit_requested.is_set():
        return

    _cancel_native_backdrop_retries()
    token = int(window_state.get("native_backdrop_retry_generation") or 0)
    timers = []
    window_state["native_backdrop_retry_timers"] = timers

    for attempt, delay in enumerate(delays, start=1):
        timer = threading.Timer(
            max(0.0, float(delay)),
            _run_native_backdrop_retry,
            args=(token, diagnostic_phase, attempt),
        )
        timer.daemon = True
        timers.append(timer)
        timer.start()


def _on_windows_user_preference_changed(sender, event_args) -> None:
    # DWM may rebuild the window and overwrite attribute 38 during this
    # callback. Reassert immediately, then verify/retry after that rebuild.
    _sync_native_backdrop(reassert=True, diagnostic_phase="preference")
    _schedule_native_backdrop_retries((0.5, 1.5, 3.0), "preference")


def _register_windows_transparency_listener() -> None:
    if window_state.get("transparency_listener_registered") or os.name != "nt":
        return

    try:
        from Microsoft.Win32 import SystemEvents

        SystemEvents.UserPreferenceChanged += _on_windows_user_preference_changed
        window_state["transparency_listener_registered"] = True
    except Exception:
        pass


def _refresh_native_frame_after_navigation_starting(
    sender=None, event_args=None
) -> None:
    """Mark navigation pending without rewriting the WebView2 surface."""
    window_state["native_navigation_pending"] = True
    _cancel_native_backdrop_retries()


def _refresh_native_frame_after_navigation_completed(
    sender=None, event_args=None
) -> None:
    """Reassert the active material after a completed WebView2 navigation."""
    window = window_ref.get("window")
    if window is None:
        return

    try:
        if event_args is None or not bool(event_args.IsSuccess):
            return
        window_state["native_initial_navigation_completed"] = True
        window_state["native_navigation_pending"] = False
    except Exception:
        return

    _sync_native_backdrop(reassert=True, diagnostic_phase="navigation")
    _schedule_native_backdrop_retries((0.25, 1.0, 2.5), "navigation")


def _refresh_native_frame_after_webview_ready(sender=None, event_args=None) -> None:
    """Apply transparency again after WebView2 creates its controller."""
    try:
        if event_args is not None and not bool(event_args.IsSuccess):
            return
    except Exception:
        pass
    _sync_native_backdrop(reassert=True, diagnostic_phase="webview-ready")
    native = getattr(window_ref.get("window"), "native", None)
    if bool(getattr(native, "Visible", False)):
        _schedule_native_backdrop_retries((0.25, 1.0, 2.5), "startup")


def _register_native_navigation_listener(window) -> None:
    if window is None or window_state.get("native_navigation_listener_registered"):
        return

    native = getattr(window, "native", None)
    webview = _get_native_webview_control(native)
    if webview is None:
        return

    try:
        webview.NavigationStarting += _refresh_native_frame_after_navigation_starting
        webview.NavigationCompleted += _refresh_native_frame_after_navigation_completed
        window_state["native_navigation_listener_registered"] = True
    except Exception:
        pass

    try:
        webview.CoreWebView2InitializationCompleted += _refresh_native_frame_after_webview_ready
    except Exception:
        pass


def _refresh_native_frame_after_layout(sender=None, event_args=None) -> None:
    """Restore the native material after WinForms moves or resizes the form."""
    window = window_ref.get("window")
    if window is None:
        return

    # DWM can discard the extended client frame while a frameless transparent
    # form is being moved.  Reapply only the native corner/material state here.
    # Re-running _apply_window_caption would first clear the DWM frame margin
    # and briefly restore the WinForms background, which is the source of the
    # white surface seen after a move.  Caption style changes are handled by
    # the explicit titlebar setting path instead.
    handle = _get_native_window_handle(window)
    if handle is not None:
        _apply_corner_preference(handle, _get_window_titlebar_setting())
    _sync_native_backdrop(reassert=True, diagnostic_phase="move-resize")


def _register_native_layout_listener(window) -> None:
    """Reapply the native frame whenever the WinForms host changes geometry."""
    if window is None or window_state.get("native_layout_listener_registered"):
        return

    native = getattr(window, "native", None)
    if native is None:
        return

    attached = False
    try:
        native.Move += _refresh_native_frame_after_layout
        attached = True
    except Exception:
        pass
    try:
        native.ResizeEnd += _refresh_native_frame_after_layout
        attached = True
    except Exception:
        pass
    try:
        native.DpiChanged += _refresh_native_frame_after_layout
        attached = True
    except Exception:
        pass

    window_state["native_layout_listener_registered"] = attached


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
    def copy_text_to_clipboard(text: str) -> bool:
        return _copy_text_to_windows_clipboard(text)

    @staticmethod
    def is_windows_transparency_enabled() -> bool:
        return _is_windows_transparency_enabled()

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
        """Start an OS-driven window move without blocking the JS bridge."""
        window = window_ref.get("window")
        if window is None:
            return False
        handle = _get_native_window_handle(window)
        if handle is None:
            return False
        maximized_geometry = _get_window_geometry(window)
        restored = NativeWindowApi.restore_window_for_drag()
        if restored:
            restored_geometry = _get_window_geometry(window, restored=True)
            _place_restored_window_at_cursor(
                window,
                maximized_geometry,
                restored_geometry,
                screen_x,
                screen_y,
            )
        return _begin_native_nonclient_interaction(window, handle, 2)  # HTCAPTION

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
    def begin_native_resize(direction: str) -> bool:
        """Start an OS-driven edge resize without a WebView mouse loop."""
        hit_tests = {
            "w": 10,   # HTLEFT
            "e": 11,   # HTRIGHT
            "n": 12,   # HTTOP
            "nw": 13,  # HTTOPLEFT
            "ne": 14,  # HTTOPRIGHT
            "s": 15,   # HTBOTTOM
            "sw": 16,  # HTBOTTOMLEFT
            "se": 17,  # HTBOTTOMRIGHT
        }
        hit_test = hit_tests.get(str(direction or "").strip().lower())
        if hit_test is None:
            return False

        window = window_ref.get("window")
        if window is None:
            return False
        handle = _get_native_window_handle(window)
        if handle is None:
            return False

        NativeWindowApi.restore_window_for_drag()
        return _begin_native_nonclient_interaction(window, handle, hit_test)

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
            _sync_native_backdrop(reassert=True, diagnostic_phase="titlebar")
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
    # pywebview re-shows a transparent WinForms window at navigation start.
    # Reapply the frame margin and corner preference after that show cycle so
    # page changes cannot leave a stale titlebar or square client corner.
    _apply_window_caption(window, _get_window_titlebar_setting(), force=False)
    _register_native_navigation_listener(window)
    _register_native_layout_listener(window)
    _register_windows_transparency_listener()
    _sync_native_backdrop(reassert=True, diagnostic_phase="startup-chrome")
    _schedule_native_backdrop_retries((0.25, 1.0, 2.5), "startup")


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
        native_backdrop_enabled = _is_windows_transparency_enabled()
        # WebView2 defaults to white between navigations and before the first
        # controller property update.  Set its documented transparent initial
        # color before the environment/controller is created, but only when
        # Windows Transparency effects are enabled.  The OFF path deliberately
        # leaves the environment untouched so the existing opaque background
        # remains the sole fallback.
        if native_backdrop_enabled:
            os.environ["WEBVIEW2_DEFAULT_BACKGROUND_COLOR"] = "00000000"
        window = webview.create_window(
            "Sparkle",
            url=_frontend_url(initial_page),
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
            background_color="#202231",
            # Let pywebview create the Form/WebView2 pair with its native
            # transparent surface when Windows Transparency is enabled.  The
            # native sync disables pywebview's navigation-time Show/Activate
            # workaround after the first handle/material handoff.
            transparent=native_backdrop_enabled,
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
        # pywebview fires ``loaded`` from its JS bridge thread.  On some
        # WebView2 startup paths that event can arrive before the WinForms
        # handle has finished being shown, so repeat the native backdrop sync
        # from the guaranteed native ``shown`` event as well.
        window.events.shown += _apply_native_chrome
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

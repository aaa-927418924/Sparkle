from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FrontendInteractionTests(unittest.TestCase):
    def test_native_window_drag_is_preferred_with_legacy_fallback(self):
        source = (ROOT / "frontend" / "codex-shell.js").read_text(encoding="utf-8")

        native_call = source.index("Promise.resolve(api.begin_native_drag")
        fallback_call = source.index(
            "startWindowDragFallback(api, startScreenX, startScreenY)",
            native_call,
        )

        self.assertLess(native_call, fallback_call)
        self.assertIn("function startWindowDragFallback", source)
        self.assertIn("window.removeEventListener(\"mousemove\", onMouseMove)", source)

    def test_sidebar_rejects_horizontal_overflow_and_touch_pan(self):
        source = (ROOT / "frontend" / "codex-shell.css").read_text(encoding="utf-8")
        shell_rules = source[source.index("/* Expanded navigation:"):]

        self.assertRegex(
            shell_rules,
            re.compile(
                r"\.sidebar,.*?\.sidebar\.sidebar--index\s*\{.*?"
                r"overflow-x:\s*hidden;.*?"
                r"overscroll-behavior-x:\s*none;.*?"
                r"touch-action:\s*pan-y;",
                re.DOTALL,
            ),
        )

    def test_native_resize_is_preferred_and_native_handles_are_hidden(self):
        js_source = (ROOT / "frontend" / "codex-shell.js").read_text(encoding="utf-8")
        css_source = (ROOT / "frontend" / "codex-shell.css").read_text(encoding="utf-8")

        self.assertIn("api.begin_native_resize(direction)", js_source)
        self.assertIn("function startWindowResizeFallback", js_source)
        self.assertIn("html.native-titlebar .window-resize-handle", css_source)

    def test_native_window_api_uses_ui_thread_non_client_messages(self):
        source = (ROOT / "app_entry.py").read_text(encoding="utf-8")
        drag_start = source.index("def begin_native_drag")
        resize_start = source.index("def begin_native_resize")
        native_api = source[drag_start:resize_start]

        self.assertIn("SendMessageW", source)
        self.assertIn("BeginInvoke", source)
        self.assertIn("ReleaseCapture", source)
        self.assertNotIn("PostMessageW", native_api)
        self.assertIn("HTCAPTION", native_api)


if __name__ == "__main__":
    unittest.main()

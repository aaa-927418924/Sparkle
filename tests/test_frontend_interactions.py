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


if __name__ == "__main__":
    unittest.main()

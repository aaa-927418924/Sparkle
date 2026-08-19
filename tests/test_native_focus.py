import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

_test_appdata = tempfile.TemporaryDirectory()
with patch.dict(os.environ, {"APPDATA": _test_appdata.name}):
    import app_entry


class FakeWebView:
    def __init__(self, invoke_required=False):
        self.InvokeRequired = invoke_required
        self.focus_count = 0
        self.invoke_count = 0

    def Focus(self):
        self.focus_count += 1

    def Invoke(self, callback):
        self.invoke_count += 1
        callback()


class NativeFocusTests(unittest.TestCase):
    def setUp(self):
        self.previous_window = app_entry.window_ref.get("window")

    def tearDown(self):
        if self.previous_window is None:
            app_entry.window_ref.pop("window", None)
        else:
            app_entry.window_ref["window"] = self.previous_window

    def test_focuses_webview_control_directly(self):
        webview = FakeWebView()
        app_entry.window_ref["window"] = types.SimpleNamespace(
            native=types.SimpleNamespace(webview=webview)
        )

        self.assertTrue(app_entry._focus_native_webview())
        self.assertEqual(webview.focus_count, 1)
        self.assertEqual(webview.invoke_count, 0)

    def test_marshals_focus_to_native_ui_thread(self):
        webview = FakeWebView(invoke_required=True)
        app_entry.window_ref["window"] = types.SimpleNamespace(
            native=types.SimpleNamespace(webview=webview)
        )
        fake_system = types.SimpleNamespace(Action=lambda callback: callback)

        with patch.dict(sys.modules, {"System": fake_system}):
            self.assertTrue(app_entry.NativeWindowApi.focus_webview())

        self.assertEqual(webview.invoke_count, 1)
        self.assertEqual(webview.focus_count, 1)


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FrontendInteractionTests(unittest.TestCase):
    def test_project_assistant_drawer_uses_fast_transparent_toggle_composer(self):
        html = (ROOT / "frontend" / "projects.html").read_text(encoding="utf-8")
        js = (ROOT / "frontend" / "project-assistant.js").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "style.css").read_text(encoding="utf-8")

        self.assertIn('type="checkbox" role="switch"', html)
        self.assertNotIn('<select id="projectAssistantScope"', html)
        self.assertNotIn("projectAssistantSubmit", html)
        self.assertNotIn("このプロジェクトについて質問や依頼を入力してください。変更操作は実行前に確認します。", html + js)
        self.assertIn(">Ask AI<", html)
        self.assertNotIn(">専属AI<", html)
        self.assertIn("project-assistant-source-history-20260821-v4", html)
        self.assertIn('class="project-assistant-actions" role="dialog"', html)
        self.assertIn('aria-describedby="projectAssistantActionHelp"', html)
        self.assertIn('event.key !== "Enter" || event.shiftKey || event.isComposing', js)
        self.assertIn("function safeSourceHref(value)", js)
        self.assertIn('link.className = "project-assistant-source-link"', js)
        self.assertIn('text.className = "project-assistant-source-label"', js)
        self.assertIn('link.target = "_blank"', js)
        self.assertIn("appendSources(bubble, message.sources)", js)
        self.assertIn("removeResolvedAction", js)
        self.assertIn("card.remove()", js)
        drawer_css = css[css.index("/* Project assistant drawer") :]
        dialog_start = drawer_css.index(".project-assistant-dialog {")
        dialog_end = drawer_css.index(".project-assistant-header {", dialog_start)
        dialog_css = drawer_css[dialog_start:dialog_end]
        action_start = drawer_css.index(".project-assistant-actions {")
        action_end = drawer_css.index(".project-assistant-actions .modal-sub", action_start)
        action_css = drawer_css[action_start:action_end]
        self.assertIn("right: 0;", drawer_css)
        self.assertIn("background: transparent;", drawer_css)
        self.assertIn("transform: none;", dialog_css)
        self.assertIn("transition: none;", dialog_css)
        self.assertNotIn("transition-property: transform", dialog_css)
        self.assertNotIn("translateX(100%)", drawer_css)
        self.assertNotIn("project-assistant-modal.is-open", drawer_css)
        self.assertNotIn("requestAnimationFrame", js)
        self.assertIn("position: absolute;", action_css)
        self.assertIn("bottom: 156px;", action_css)
        self.assertIn("overflow-y: auto;", action_css)
        self.assertIn("text-overflow: ellipsis;", drawer_css)

    def test_pointer_focus_recovery_does_not_steal_editor_focus(self):
        source = (ROOT / "frontend" / "page-transition.js").read_text(encoding="utf-8")

        self.assertIn("function isTextEditingTarget(target)", source)
        self.assertIn("isTextEditingTarget(document.activeElement)", source)
        self.assertIn("isTextEditingTarget(event.target)", source)
        self.assertIn('document.addEventListener("pointermove", recoverFocusFromPointer', source)
        self.assertNotIn('document.addEventListener("pointermove", focusPageIfNeeded', source)
        self.assertIn("focusPageIfNeeded(false)", source)
        for page in ("index.html", "notes.html", "note-editor.html", "projects.html"):
            html = (ROOT / "frontend" / page).read_text(encoding="utf-8")
            self.assertIn("page-transition.js?v=page-swipe-20260821-focus-safe-v1", html)

    def test_clipboard_copy_is_available_for_assistant_history_and_text_boxes(self):
        shell = (ROOT / "frontend" / "codex-shell.js").read_text(encoding="utf-8")
        assistant = (ROOT / "frontend" / "project-assistant.js").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "style.css").read_text(encoding="utf-8")
        native = (ROOT / "app_entry.py").read_text(encoding="utf-8")

        self.assertIn('document.addEventListener("copy"', shell)
        self.assertIn("window.sparkleCopyText = copyText", shell)
        self.assertIn("copy_text_to_clipboard", shell)
        self.assertIn('className = "project-assistant-message-copy"', assistant)
        self.assertIn('role === "user" ? "ユーザー側テキスト" : "回答テキスト"', assistant)
        self.assertIn("user-select: text;", css)
        self.assertIn("def _copy_text_to_windows_clipboard", native)
        self.assertIn("def copy_text_to_clipboard", native)
        for page in ("index.html", "notes.html", "note-editor.html", "projects.html"):
            html = (ROOT / "frontend" / page).read_text(encoding="utf-8")
            self.assertIn("codex-shell.js?v=codex-shell-20260821-clipboard-v1", html)

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

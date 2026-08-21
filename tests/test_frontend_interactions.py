from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FrontendInteractionTests(unittest.TestCase):
    def test_clip_attachment_uses_card_grids_and_home_range_action(self):
        home = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        home_js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        projects = (ROOT / "frontend" / "projects.html").read_text(encoding="utf-8")
        projects_js = (ROOT / "frontend" / "projects.js").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "style.css").read_text(encoding="utf-8")

        self.assertIn('id="batchProjectBtn"', home)
        self.assertIn('id="projectAttachModal"', home)
        self.assertIn("async function openProjectAttachModal()", home_js)
        self.assertIn("attachSelectedClipsToProject", home_js)
        self.assertIn("/projects/${projectId}/clips/${clipId}", home_js)
        self.assertIn('class="pm-linked-list pm-clip-linked-list"', projects)
        self.assertIn("clip-picker-dialog", projects)
        self.assertIn('id="clipLinkedCount"', projects)
        self.assertIn('type="button" class="pm-clip-item pm-home-clip-card"', projects_js)
        self.assertIn("function clipCardInfoHtml", projects_js)
        self.assertIn("pm-clip-media", projects_js)
        self.assertIn("/projects/${project.id}/duplicate", projects_js)
        self.assertIn("/projects/${state.currentProjectId}/tasks/${taskId}", projects_js)
        self.assertIn("linkedToProject(t, state.currentProjectId)", projects_js)
        self.assertIn("#clipModal .pm-clip-linked-list", css)
        self.assertIn("#clipModal .pm-home-clip-card", css)
        self.assertIn("grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));", css)

    def test_project_detail_clip_cards_support_scoped_range_selection(self):
        html = (ROOT / "frontend" / "projects.html").read_text(encoding="utf-8")
        source = (ROOT / "frontend" / "projects.js").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "style.css").read_text(encoding="utf-8")

        self.assertNotIn('id="detailClipSelectionBar"', html)
        self.assertNotIn('id="clearDetailClipSelectionBtn"', html)
        self.assertIn('id="detailClipBatchBar"', html)
        self.assertIn('id="detailClipDeleteBtn"', html)
        self.assertNotIn('class="card-select-toggle"', source)
        self.assertIn("detailClipSelectedIds", source)
        self.assertIn("function deleteSelectedDetailClips(event)", source)
        self.assertIn("/projects/${projectId}/clips/${clipId}", source)
        self.assertIn("els.detailClips.addEventListener(\"mousedown\"", source)
        self.assertIn("function finishDetailClipRubberBand(event)", source)
        self.assertIn("toggleDetailClipSelection(clipId)", source)
        self.assertIn("detailClipAutoScrollStep", source)
        self.assertIn('e.target.closest("#detailClips")', source)
        self.assertIn("#detailClips.is-range-selecting", css)
        self.assertIn(".card.selected:hover", css)
        self.assertNotIn(".card-select-toggle", css)

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
        self.assertIn("project-clip-picker-home-card-20260821-v2", html)
        self.assertNotIn('id="projectAssistantClose"', html)
        self.assertIn('class="project-assistant-toolbar"', html)
        self.assertIn('id="projectAssistantClearHistory"', html)
        self.assertIn("project-assistant-streaming-20260821-v1", html)
        self.assertIn('class="project-assistant-actions" role="dialog"', html)
        self.assertIn('aria-describedby="projectAssistantActionHelp"', html)
        self.assertIn('event.key !== "Enter" || event.shiftKey || event.isComposing', js)
        self.assertIn("function safeSourceHref(value)", js)
        self.assertIn('link.className = "project-assistant-source-link"', js)
        self.assertIn('text.className = "project-assistant-source-label"', js)
        self.assertIn('link.target = "_blank"', js)
        self.assertIn("appendSources(bubble, message.sources)", js)
        self.assertIn('className = "project-assistant-message-actions"', js)
        self.assertIn("function beginEditMessage(message, bubble)", js)
        self.assertIn("async function submitInlineEdit()", js)
        self.assertIn("project-assistant-inline-editor", css)
        self.assertIn("function createMessageIconButton(iconName, label)", js)
        self.assertIn('mask-image: url("icons/pencil.svg")', css)
        self.assertIn('mask-image: url("icons/trash.svg")', css)
        self.assertIn("function appendScopeDivider(scope", js)
        self.assertIn("function handleScopeChange()", js)
        self.assertIn("project-assistant-scope-divider", css)
        self.assertIn("履歴は保持されます。", js)
        self.assertIn("scope: request.scope", js)
        self.assertIn("async function deleteUserMessage(messageId)", js)
        self.assertIn("Number(message.id) === lastUserId", js)
        self.assertIn("state.activeRequest", js)
        self.assertIn("state.backgroundResult", js)
        self.assertIn("function syncPendingRequestUi()", js)
        self.assertIn("/assistant/stream", js)
        self.assertIn("function parseAssistantSseBlock", js)
        self.assertIn('appendBubble("assistant", "Thinking"', js)
        self.assertIn("project-assistant-thinking-preview", js)
        self.assertIn("thinkingComplete", js)
        self.assertIn("function hideThinkingPreview(request)", js)
        self.assertIn("project-assistant-thinking-preview-label", js)
        self.assertNotIn('document.createElement("details")', js)
        self.assertNotIn(".project-assistant-thinking-preview summary", css)
        self.assertNotIn("thinking-orbs", html + js + css)
        self.assertNotIn("projectAssistantEditCancel", html + js)
        self.assertNotIn("state.controller?.abort()", js)
        self.assertNotIn("|| !state.open", js)
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
        self.assertIn("border-radius: 0;", dialog_css)
        self.assertIn(".project-assistant-modal .project-assistant-dialog", drawer_css)
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
        self.assertNotIn("project-assistant-message-copy", assistant)
        self.assertNotIn("project-assistant-message-tools", assistant)
        self.assertNotIn("project-assistant-message-copy", css)
        self.assertIn('event.target?.id === "projectAssistantMessage"', shell)
        self.assertIn("user-select: text;", css)
        self.assertIn(".project-assistant-message-actions", css)
        self.assertIn(".project-assistant-thinking-label", css)
        self.assertIn("project-assistant-generating", css)
        self.assertIn("def _copy_text_to_windows_clipboard", native)
        self.assertIn("def copy_text_to_clipboard", native)
        for page in ("index.html", "notes.html", "note-editor.html", "projects.html"):
            html = (ROOT / "frontend" / page).read_text(encoding="utf-8")
            self.assertIn("codex-shell.js?v=codex-shell-20260821-clipboard-v2", html)

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

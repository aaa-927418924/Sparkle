from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FrontendInteractionTests(unittest.TestCase):
    def test_home_tag_filters_render_as_individual_removable_buttons(self):
        home = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        home_css = (ROOT / "frontend" / "home-figma.css").read_text(encoding="utf-8")
        shell_css = (ROOT / "frontend" / "codex-shell.css").read_text(encoding="utf-8")

        self.assertIn('id="activeTag" class="active-tags"', home)
        active_markup = home[home.index('<div id="activeTag"') : home.index('</div>', home.index('<div id="activeTag"'))]
        self.assertNotIn("タグ:", active_markup)
        self.assertIn("function renderActiveTags()", source)
        self.assertIn('class="active-tag-filter"', source)
        self.assertIn("state.activeTags = state.activeTags.filter", source)
        self.assertIn('aria-pressed="${active}"', source)
        self.assertIn("border-color: #9c9c9c;", home_css)
        self.assertIn("color: #9c9c9c;", home_css)
        self.assertIn("border-color: #ffffff;", home_css)
        self.assertIn("color: #ffffff;", home_css)
        self.assertIn("--bg: #161616;", shell_css)
        self.assertIn("--sidebar-bg: #212121;", shell_css)
        self.assertIn("--surface-raised: #202020;", shell_css)
        self.assertIn("background: var(--surface-active);", shell_css)
        self.assertNotIn("box-shadow: inset 0 0 0 1px var(--border-strong);", shell_css)
        self.assertIn(".home-page .cat-btn.active", home_css)
        self.assertIn("color: #9c9c9c;", home_css)
        self.assertIn("color: #ffffff;", home_css)

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

    def test_project_deletion_reports_errors_and_restores_failed_batch_selection(self):
        source = (ROOT / "frontend" / "projects.js").read_text(encoding="utf-8")

        self.assertIn("detail = typeof payload?.detail === \"string\"", source)
        self.assertIn("function restoreSelection(ids)", source)
        self.assertIn("function removeProjectPin(projectId)", source)
        self.assertIn("await api(`/projects/${id}`, { method: \"DELETE\" })", source)
        self.assertIn("const failedIds = []", source)
        self.assertNotIn("const res = await fetch(`${API}/projects/${id}`, { method: \"DELETE\" })", source)

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

    def test_custom_titlebar_and_sidebar_history_controls_are_present(self):
        shell = (ROOT / "frontend" / "codex-shell.js").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "codex-shell.css").read_text(encoding="utf-8")
        pages = ("index.html", "notes.html", "projects.html", "note-editor.html", "profile.html", "settings.html")

        for page in pages:
            html = (ROOT / "frontend" / page).read_text(encoding="utf-8")
            self.assertIn('class="app-titlebar window-drag-region"', html)
            self.assertIn('class="app-titlebar-history"', html)
            self.assertIn('data-history-action="back"', html)
            self.assertIn('data-history-action="forward"', html)
            self.assertLess(html.index('class="app-titlebar-history"'), html.index('class="layout"'))
            self.assertNotIn('class="sidebar-history"', html)
            self.assertNotIn('class="sidebar-titlebar"', html)
            self.assertNotIn('class="sidebar-brand-icon"', html)

        self.assertIn("window.history.back()", shell)
        self.assertIn("window.history.forward()", shell)
        self.assertIn("[data-history-action]", shell)
        self.assertIn("[data-history-action]", shell[shell.index("function canStartSidebarDrag"):])
        self.assertIn("--app-titlebar-height: 32px;", css)
        self.assertIn("background: var(--sidebar-bg);", css)
        self.assertIn("border-top: 0;", css)
        self.assertIn(".app-titlebar-history-icon", css)
        self.assertIn(".app-titlebar .window-control:focus-visible", css)
        self.assertIn("outline-offset: 0;", css)
        titlebar_rule = css[css.index(".app-titlebar {"):css.index(".app-titlebar-drag-space")]
        self.assertIn("position: fixed;", titlebar_rule)
        self.assertIn("top: 0;", titlebar_rule)
        self.assertIn("left: 0;", titlebar_rule)
        self.assertIn("right: 0;", titlebar_rule)
        self.assertIn("z-index: 1100;", titlebar_rule)
        self.assertIn("margin-top: var(--app-titlebar-height);", css)
        self.assertIn("html:not(.native-titlebar) .migration-window", css)
        for page in (
            "index.html",
            "notes.html",
            "projects.html",
            "note-editor.html",
            "profile.html",
            "settings.html",
            "migration.html",
            "setup.html",
            "tutorial.html",
            "extension-guide.html",
        ):
            html = (ROOT / "frontend" / page).read_text(encoding="utf-8")
            self.assertIn("custom-titlebar-history-v4-fixed", html)

    def test_primary_sidebar_icons_are_removed_from_markup(self):
        pages = ("index.html", "notes.html", "projects.html", "note-editor.html", "profile.html", "settings.html")
        for page in pages:
            html = (ROOT / "frontend" / page).read_text(encoding="utf-8")
            nav_links = re.findall(
                r'<a\b[^>]*data-nav="(home|memo|projects)"[^>]*>.*?</a>',
                html,
                re.DOTALL,
            )
            self.assertEqual(len(nav_links), 3)
            for match in re.finditer(
                r'<a\b[^>]*data-nav="(?:home|memo|projects)"[^>]*>.*?</a>',
                html,
                re.DOTALL,
            ):
                self.assertNotIn('class="icon icon-nav"', match.group(0))
            self.assertNotIn("sidebar-primary-icon-policy", html)

        app_entry = (ROOT / "app_entry.py").read_text(encoding="utf-8")
        shell_css = (ROOT / "frontend" / "codex-shell.css").read_text(encoding="utf-8")
        self.assertNotIn("SIDEBAR_ICON_POLICY_SCRIPT", app_entry)
        self.assertNotIn("_apply_sidebar_icon_policy", app_entry)
        self.assertNotIn('data-nav="home"] .icon-nav', shell_css)
        self.assertNotIn('data-nav="memo"] .icon-nav', shell_css)
        self.assertNotIn('data-nav="projects"] .icon-nav', shell_css)

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
        native_source = (ROOT / "app_entry.py").read_text(encoding="utf-8")

        self.assertIn("api.begin_native_resize(direction)", js_source)
        self.assertIn(
            'const hasNativeResize = hasNativeTitlebar && typeof api?.begin_native_resize === "function";',
            js_source,
        )
        self.assertIn("function startWindowResizeFallback", js_source)
        self.assertIn("html.native-titlebar .window-resize-handle", css_source)
        self.assertIn("else (style & ~(0x00C00000 | 0x00040000))", native_source)
        self.assertNotIn('"native_resize_handle"', native_source)

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

    def test_note_editor_is_body_only_and_keeps_title_in_state(self):
        html = (ROOT / "frontend" / "note-editor.html").read_text(encoding="utf-8")
        source = (ROOT / "frontend" / "note-editor.js").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "style.css").read_text(encoding="utf-8")

        for removed_id in (
            "backLink",
            "noteTitle",
            "modeEdit",
            "modeView",
            "mdToolbar",
            "noteBodyPreview",
            "mdCheatsheet",
        ):
            self.assertNotIn(f'id="{removed_id}"', html)
        self.assertNotIn("vendor/marked.min.js", html)
        self.assertIn('id="noteBodyRaw"', html)
        self.assertIn('id="settingsModal"', html)
        self.assertIn('title: ""', source)
        self.assertIn("state.title", source)
        self.assertIn('"無題のメモ"', source)
        self.assertNotIn("MD_ACTIONS", source)
        self.assertNotIn("setMode", source)
        editor_css = css[css.index("body.note-editor-page .main.editor-main") :]
        self.assertIn("max-width: none;", editor_css)
        self.assertIn("margin-inline-start: 240px;", editor_css)
        self.assertIn("padding: 0;", editor_css)
        self.assertIn("height: 100%;", editor_css)
        self.assertIn("background: var(--bg);", editor_css)
        self.assertIn("resize: none;", editor_css)
        self.assertIn("box-shadow: none;", editor_css)

    def test_note_editor_has_accessible_markdown_highlight_layer_and_line_numbers(self):
        html = (ROOT / "frontend" / "note-editor.html").read_text(encoding="utf-8")
        source = (ROOT / "frontend" / "note-editor.js").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "style.css").read_text(encoding="utf-8")
        vendor_dir = ROOT / "frontend" / "vendor"

        self.assertIn('class="editor-sr-only" for="noteBodyRaw"', html)
        self.assertIn('id="markdownEditor"', html)
        self.assertIn('id="noteLineNumbers" aria-hidden="true"', html)
        self.assertIn('id="noteBodyHighlight" aria-hidden="true"', html)
        self.assertIn('id="noteBodyHighlightCode"', html)
        self.assertIn('id="noteEditorCanvas"', html)
        self.assertIn('aria-label="メモ本文（Markdown）"', html)
        self.assertIn('wrap="off"', html)

        highlight_script = html.index('src="vendor/highlight.min.js?v=highlightjs-11.12.0"')
        markdown_script = html.index('src="vendor/highlight-markdown.min.js?v=highlightjs-11.12.0-markdown"')
        editor_script = html.index('src="note-editor.js?v=note-editor-ui-20260803-remote-latency-v1-full-surface-v1-highlightjs-11.12.0-grok-visibility-v2"')
        self.assertLess(highlight_script, markdown_script)
        self.assertLess(markdown_script, editor_script)
        self.assertIn("grok-visibility-v2", html)
        self.assertIn("note-editor-overlay-v1", html)
        self.assertTrue((vendor_dir / "highlight.min.js").is_file())
        self.assertTrue((vendor_dir / "highlight-markdown.min.js").is_file())
        self.assertTrue((vendor_dir / "highlight.LICENSE.md").is_file())
        self.assertIn("Highlight.js v11.12.0", (vendor_dir / "highlight.min.js").read_text(encoding="utf-8"))
        self.assertIn("compiled for Highlight.js 11.12.0", (vendor_dir / "highlight-markdown.min.js").read_text(encoding="utf-8"))

        self.assertIn("function escapeHtml", source)
        self.assertIn("function highlightMarkdown", source)
        self.assertIn("function getHighlighter", source)
        self.assertIn('engine.getLanguage("markdown")', source)
        self.assertIn('engine.highlight(source, { language: "markdown", ignoreIllegals: true }).value', source)
        self.assertIn('classList.add("hljs", "language-markdown")', source)
        self.assertIn('dataset.highlighted = "yes"', source)
        self.assertIn("return escapeHtml(source);", source)
        self.assertIn("innerHTML = highlightMarkdown(source)", source)
        self.assertIn("els.bodyRaw.addEventListener(\"scroll\", syncMarkdownEditorScroll", source)
        self.assertIn("updateMarkdownEditor();", source)
        self.assertIn("translate(${-x}px, ${-y}px)", source)
        self.assertIn("translateY(${-y}px)", source)
        self.assertIn("font-variant-numeric: tabular-nums;", css)
        self.assertIn("grid-template-columns: auto minmax(0, 1fr);", css)
        self.assertIn("color: transparent;", css)
        self.assertIn("caret-color: var(--text);", css)
        self.assertIn("background: var(--bg);", css)
        self.assertIn('font-family: "Cascadia Mono", Consolas, "Courier New", Meiryo, "Segoe UI",', css)
        self.assertIn("font-weight: 400;", css)
        self.assertIn("font-synthesis: none;", css)
        self.assertIn(".note-editor-page .markdown-editor *", css)
        focus_start = css.index(".note-editor-page .editor-canvas > .editor-textarea:focus,")
        focus_end = css.index("}", focus_start)
        focus_rule = css[focus_start : focus_end + 1]
        self.assertIn("background: transparent;", focus_rule)
        self.assertIn("color: transparent;", focus_rule)
        legacy_focus_start = css.index(".note-editor-page .editor-textarea:focus,")
        self.assertLess(legacy_focus_start, focus_start)
        self.assertIn("background: transparent;", css[legacy_focus_start : css.index("}", legacy_focus_start) + 1])
        self.assertIn(".note-editor-page .editor-highlight .hljs-section", css)
        self.assertIn(".note-editor-page .editor-highlight .hljs-strong", css)
        self.assertIn("--editor-heading: #569cd6;", css)
        self.assertIn("--editor-code: #ce9178;", css)
        shell_css = (ROOT / "frontend" / "codex-shell.css").read_text(encoding="utf-8")
        self.assertIn("body:not(.note-editor-page) .editor-textarea", shell_css)
        self.assertIn("body.note-editor-page .editor-canvas > .editor-textarea:focus", shell_css)
        self.assertIn("-webkit-text-fill-color: transparent !important;", shell_css)
        for token_class in ("hljs-section", "hljs-strong", "hljs-emphasis", "hljs-code", "hljs-link", "hljs-quote", "hljs-bullet"):
            self.assertIn(f".{token_class}", css)
        self.assertNotIn("md-token", source)
        self.assertNotIn("renderInlineMarkdown", source)
        self.assertNotIn("renderMarkdownLine", source)

    def test_notes_memos_have_inline_rename_action_and_conflict_safe_modal(self):
        html = (ROOT / "frontend" / "notes.html").read_text(encoding="utf-8")
        source = (ROOT / "frontend" / "notes.js").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "notes-figma.css").read_text(encoding="utf-8")

        self.assertIn('id="noteRenameModal"', html)
        self.assertIn('for="noteRenameTitle"', html)
        self.assertIn('id="noteRenameCancel"', html)
        self.assertIn('id="noteRenameSave"', html)
        pin = source.index('data-pin="${n.id}"')
        rename = source.index('data-rename="${n.id}"')
        delete = source.index('data-del="${n.id}"')
        self.assertLess(pin, rename)
        self.assertLess(rename, delete)
        self.assertIn('src="icons/pencil.svg"', source)
        self.assertIn('title="名前を変更"', source)
        self.assertIn('aria-label="名前を変更"', source)
        self.assertIn("expected_updated_at: noteRenameExpectedUpdatedAt", source)
        self.assertIn('e?.status === 409', source)
        self.assertIn("最新の内容を確認してから", source)
        self.assertIn("window.refreshPinnedDataInBackground?.(\"note\", updated.id)", source)
        self.assertIn("window.refreshAllPinnedProjectsInBackground?.()", source)
        self.assertIn("els.noteRenameTitle.focus()", source)
        self.assertIn("els.noteRenameTitle.select()", source)
        self.assertIn("if (trigger?.isConnected) trigger.focus()", source)
        self.assertIn("@media (hover: none)", css)
        self.assertIn("opacity: 1;", css[css.index("@media (hover: none)") :])
        self.assertIn("pointer-events: auto;", css[css.index("@media (hover: none)") :])


if __name__ == "__main__":
    unittest.main()

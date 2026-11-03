from pathlib import Path
import re
import sqlite3
import unittest

from maintenance import SETTING_DEFAULTS, cleanup_removed_titlebar_setting


ROOT = Path(__file__).resolve().parents[1]


class SettingsCategoryTests(unittest.TestCase):
    def test_settings_page_exposes_the_six_requested_categories(self):
        html = (ROOT / "frontend" / "settings.html").read_text(encoding="utf-8")
        category_buttons = re.findall(
            r'data-settings-category-button="([^"]+)"[^>]*title="([^"]+)"',
            html,
        )
        self.assertEqual(
            category_buttons,
            [
                ("general", "一般"),
                ("theme", "テーマ"),
                ("connections", "接続"),
                ("ai", "AI"),
                ("advanced", "高度な機能"),
                ("plugins", "\u30d7\u30e9\u30b0\u30a4\u30f3"),
            ],
        )
        self.assertNotIn('id="settingsCategoryTitle"', html)
        self.assertNotIn("settings-category-heading", html)
        self.assertIn('data-settings-category-panel="general"', html)
        self.assertIn('data-settings-category-panel="theme" hidden', html)
        self.assertIn('data-settings-category-panel="connections" hidden', html)
        self.assertIn('data-settings-category-panel="ai" hidden', html)
        self.assertIn('data-settings-category-panel="advanced" hidden', html)
        self.assertIn('data-settings-category-panel="plugins" hidden', html)
        self.assertIn('aria-label="設定カテゴリ"', html)
        self.assertIn('settings-categories.js?v=settings-categories-plugins-v1', html)
        self.assertIn('plugin-manager.js?v=plugin-manager-v3-permissions-v1', html)

        expected_groups = {
            "fileSaveMethod": "general",
            "taskAutoDelete": "general",
            "autoCreateNoteOnProject": "general",
            "appearanceBackgroundChoose": "theme",
            "remoteAccessMode": "connections",
            "aiExportEnabled": "ai",
            "dbExportBtn": "advanced",
            "setupTutorialBtn": "advanced",
            "updateCheckBtn": "general",
        }
        for setting_id, expected_category in expected_groups.items():
            with self.subTest(setting=setting_id):
                before_setting = html[: html.index(f'id="{setting_id}"')]
                panels = re.findall(
                    r'data-settings-category-panel="([^"]+)"', before_setting
                )
                self.assertTrue(panels, f"No category panel before {setting_id}")
                self.assertEqual(panels[-1], expected_category)

        css = (ROOT / "frontend" / "codex-shell.css").read_text(encoding="utf-8")
        self.assertIn("@container settings-main (max-width: 1000px)", css)
        self.assertIn("clip-path: inset(50%);", css)

    def test_removed_settings_are_absent_from_all_settings_copies(self):
        pages = (
            "index.html",
            "notes.html",
            "projects.html",
            "note-editor.html",
            "settings.html",
        )
        for name in pages:
            with self.subTest(page=name):
                html = (ROOT / "frontend" / name).read_text(encoding="utf-8")
                self.assertNotIn("clearSearchHistory", html)
                self.assertNotIn("検索履歴</span>", html)
                self.assertNotIn("nativeTitlebar", html)
                self.assertNotIn("Windows標準のタイトルバー", html)

    def test_titlebar_is_custom_only_and_legacy_preferences_are_deleted(self):
        html_pages = tuple((ROOT / "frontend").glob("*.html"))
        html_pages += tuple((ROOT / "frontend" / "remote").glob("*.html"))
        for path in html_pages:
            with self.subTest(page=path.name):
                html = path.read_text(encoding="utf-8")
                self.assertNotIn('localStorage.getItem("sparkle.titlebarMode")', html)

        pins = (ROOT / "frontend" / "pins.js").read_text(encoding="utf-8")
        app_entry = (ROOT / "app_entry.py").read_text(encoding="utf-8")
        router_source = (ROOT / "routers.py").read_text(encoding="utf-8")
        self.assertNotIn("loadTitlebarMode", pins)
        self.assertNotIn("set_titlebar_mode", pins)
        self.assertNotIn("nativeTitlebar", pins)
        self.assertNotIn("set_titlebar_mode", app_entry)
        self.assertIn('"auto_create_note_on_task", "titlebar_mode"', router_source)
        self.assertNotIn("titlebar_mode", SETTING_DEFAULTS)

    def test_obsolete_titlebar_preference_is_removed_from_settings_storage(self):
        db = sqlite3.connect(":memory:")
        try:
            db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT INTO settings(key, value) VALUES (?, ?)", ("titlebar_mode", "native"))
            db.execute("INSERT INTO settings(key, value) VALUES (?, ?)", ("task_auto_delete", "1w"))

            removed = cleanup_removed_titlebar_setting(db)

            self.assertEqual(removed, 1)
            self.assertEqual(
                db.execute("SELECT key FROM settings ORDER BY key").fetchall(),
                [("task_auto_delete",)],
            )
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
